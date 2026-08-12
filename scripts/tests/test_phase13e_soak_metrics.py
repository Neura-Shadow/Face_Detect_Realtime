"""Phase 13E soak drift-detection tests.

A soak verdict is only as good as the rule that decides "this drifted". These
tests pin those rules against synthetic series shaped like the real ones: a
flat steady state, a slow leak, a working set that rises and falls, a thermal
ramp and a latency trend.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from workers.core.soak_metrics import (  # noqa: E402
    MONOTONE_RESOURCE_SERIES,
    DriftLimits,
    SoakSeries,
    classify_soak,
    distribution,
    evaluate_backpressure_recovery,
    evaluate_drift,
    is_progressive,
    percentile,
    window_stats,
)

TOTAL_SEC = 1000.0
WINDOW_SEC = 100.0


def series_from(name: str, values: List[float], *, total_sec: float = TOTAL_SEC) -> SoakSeries:
    series = SoakSeries(name)
    step = total_sec / float(len(values))
    for index, value in enumerate(values):
        series.add(index * step, value)
    return series


def flat(name: str, value: float, count: int = 200) -> SoakSeries:
    return series_from(name, [value] * count)


def ramp(name: str, start: float, end: float, count: int = 200) -> SoakSeries:
    step = (end - start) / float(count - 1)
    return series_from(name, [start + step * index for index in range(count)])


def sawtooth(name: str, low: float, high: float, count: int = 200) -> SoakSeries:
    return series_from(name, [low if index % 2 else high for index in range(count)])


class TestDistribution(unittest.TestCase):
    def test_percentiles_are_nearest_rank(self) -> None:
        # Nearest rank over a zero-indexed list: rank = round(q * (n - 1)), so
        # the median of 1..100 is element 50, i.e. 51.0. This matches the
        # Phase 13C ``latency_stats`` estimator, and the two must agree because
        # both feed the same latency budget comparison.
        ordered = [float(value) for value in range(1, 101)]
        self.assertEqual(percentile(ordered, 50.0), 51.0)
        self.assertEqual(percentile(ordered, 100.0), 100.0)
        self.assertEqual(percentile(ordered, 0.0), 1.0)
        self.assertIsNone(percentile([], 50.0))

    def test_distribution_reports_every_required_statistic(self) -> None:
        stats = distribution([1.0, 2.0, 3.0, 4.0])
        self.assertEqual(stats["count"], 4)
        self.assertEqual(stats["min"], 1.0)
        self.assertEqual(stats["max"], 4.0)
        self.assertEqual(stats["mean"], 2.5)
        for key in ("p50", "p95", "p99"):
            self.assertIsNotNone(stats[key])

    def test_an_empty_distribution_is_not_zero(self) -> None:
        stats = distribution([])
        self.assertEqual(stats["count"], 0)
        self.assertIsNone(stats["p99"])


class TestSoakSeries(unittest.TestCase):
    def test_non_finite_and_none_samples_are_ignored(self) -> None:
        series = SoakSeries("rss")
        series.add(0.0, 10.0)
        series.add(1.0, None)
        series.add(2.0, float("nan"))
        series.add(3.0, float("inf"))
        series.add(4.0, "not a number")
        series.add(5.0, 20.0)
        self.assertEqual(len(series), 2)
        self.assertEqual(series.values, [10.0, 20.0])

    def test_downsampling_bounds_the_serialised_series(self) -> None:
        series = flat("rss", 1.0, count=5000)
        payload = series.to_dict(max_points=100)
        self.assertTrue(payload["series_downsampled"])
        self.assertLessEqual(len(payload["series"]), 100)
        self.assertEqual(payload["sample_count"], 5000)


class TestWindows(unittest.TestCase):
    def test_start_and_end_windows_are_taken_from_the_right_ends(self) -> None:
        series = ramp("rss", 100.0, 200.0)
        stats = window_stats(series, window_sec=WINDOW_SEC, total_sec=TOTAL_SEC)
        self.assertTrue(stats["available"])
        self.assertLess(stats["start_window"]["mean"], stats["end_window"]["mean"])
        self.assertAlmostEqual(stats["start_window"]["min"], 100.0, places=4)
        self.assertAlmostEqual(stats["end_window"]["max"], 200.0, places=4)

    def test_rolling_windows_cover_the_run(self) -> None:
        stats = window_stats(flat("rss", 5.0), window_sec=WINDOW_SEC, total_sec=TOTAL_SEC)
        self.assertEqual(stats["rolling_window_count"], 10)

    def test_an_empty_series_is_unavailable_not_zero(self) -> None:
        stats = window_stats(SoakSeries("rss"), window_sec=WINDOW_SEC)
        self.assertFalse(stats["available"])


class TestProgressiveGrowth(unittest.TestCase):
    def test_a_monotone_rise_is_progressive(self) -> None:
        rolling = [{"mean": float(value)} for value in range(6)]
        self.assertTrue(is_progressive(rolling, min_windows=4))

    def test_a_working_set_that_rises_and_falls_is_not_progressive(self) -> None:
        rolling = [{"mean": value} for value in (1.0, 3.0, 2.0, 4.0, 3.5, 4.5)]
        self.assertFalse(is_progressive(rolling, min_windows=4))

    def test_too_few_windows_is_never_progressive(self) -> None:
        self.assertFalse(is_progressive([{"mean": 1.0}, {"mean": 2.0}], min_windows=4))


class TestResourceDrift(unittest.TestCase):
    def setUp(self) -> None:
        self.limits = DriftLimits()

    def _verdict(self, series: SoakSeries) -> dict:
        stats = window_stats(series, window_sec=WINDOW_SEC, total_sec=TOTAL_SEC)
        return evaluate_drift(series, stats, limits=self.limits, kind="resource")

    def test_a_flat_resource_does_not_drift(self) -> None:
        verdict = self._verdict(flat("process_rss_bytes", 400e6))
        self.assertFalse(verdict["drift_detected"], verdict["reasons"])

    def test_a_large_rss_leak_is_detected(self) -> None:
        verdict = self._verdict(ramp("process_rss_bytes", 400e6, 1200e6))
        self.assertTrue(verdict["drift_detected"])
        self.assertIn("rss_growth_bytes_exceeded", verdict["reasons"])

    def test_a_small_rss_rise_within_both_limits_is_accepted(self) -> None:
        verdict = self._verdict(ramp("process_rss_bytes", 400e6, 420e6))
        self.assertFalse(verdict["drift_detected"], verdict["reasons"])

    def test_file_descriptor_growth_is_detected(self) -> None:
        verdict = self._verdict(ramp("open_fd_count", 40.0, 400.0))
        self.assertTrue(verdict["drift_detected"])
        self.assertIn("fd_growth_exceeded", verdict["reasons"])

    def test_thread_growth_is_detected(self) -> None:
        verdict = self._verdict(ramp("thread_count", 12.0, 60.0))
        self.assertTrue(verdict["drift_detected"])
        self.assertIn("thread_growth_exceeded", verdict["reasons"])

    def test_steady_nonzero_swap_is_not_drift(self) -> None:
        verdict = self._verdict(sawtooth("swap_used_bytes", 100e6, 120e6))
        self.assertFalse(verdict["drift_detected"], verdict["reasons"])

    def test_only_progressive_swap_growth_is_drift(self) -> None:
        verdict = self._verdict(ramp("swap_used_bytes", 0.0, 900e6))
        self.assertTrue(verdict["drift_detected"])
        self.assertIn("swap_growth_progressive", verdict["reasons"])


class TestLatencyAndTemperatureDrift(unittest.TestCase):
    def setUp(self) -> None:
        self.limits = DriftLimits()

    def test_stable_latency_does_not_drift(self) -> None:
        series = sawtooth("frame_to_command_ms", 88.0, 94.0)
        stats = window_stats(series, window_sec=WINDOW_SEC, total_sec=TOTAL_SEC)
        verdict = evaluate_drift(series, stats, limits=self.limits, kind="latency")
        self.assertFalse(verdict["drift_detected"], verdict["reasons"])

    def test_a_rising_latency_trend_is_detected(self) -> None:
        series = ramp("frame_to_command_ms", 90.0, 200.0)
        stats = window_stats(series, window_sec=WINDOW_SEC, total_sec=TOTAL_SEC)
        verdict = evaluate_drift(series, stats, limits=self.limits, kind="latency")
        self.assertTrue(verdict["drift_detected"])
        self.assertIn("latency_p99_growth_exceeded", verdict["reasons"])

    def test_a_modest_thermal_rise_is_accepted(self) -> None:
        series = ramp("tj_temperature_c", 48.0, 55.0)
        stats = window_stats(series, window_sec=WINDOW_SEC, total_sec=TOTAL_SEC)
        verdict = evaluate_drift(series, stats, limits=self.limits, kind="temperature")
        self.assertFalse(verdict["drift_detected"], verdict["reasons"])
        # The rise is measured between window maxima, and each window covers 10%
        # of the run, so it is slightly less than the full 48->55 span.
        self.assertGreater(verdict["temperature_rise_c"], 5.0)
        self.assertLess(verdict["temperature_rise_c"], self.limits.temperature_rise_c_max)

    def test_a_large_thermal_ramp_is_detected(self) -> None:
        series = ramp("tj_temperature_c", 45.0, 80.0)
        stats = window_stats(series, window_sec=WINDOW_SEC, total_sec=TOTAL_SEC)
        verdict = evaluate_drift(series, stats, limits=self.limits, kind="temperature")
        self.assertTrue(verdict["drift_detected"])
        self.assertIn("temperature_rise_exceeded", verdict["reasons"])


class TestBackpressureRecovery(unittest.TestCase):
    def test_latency_returning_to_baseline_recovers(self) -> None:
        payload = evaluate_backpressure_recovery(
            pre_burst_p99_ms=95.0, burst_p99_ms=400.0, post_burst_p99_ms=99.0
        )
        self.assertTrue(payload["recovered"], payload["reasons"])

    def test_latency_staying_high_does_not_recover(self) -> None:
        payload = evaluate_backpressure_recovery(
            pre_burst_p99_ms=95.0, burst_p99_ms=400.0, post_burst_p99_ms=300.0
        )
        self.assertFalse(payload["recovered"])
        self.assertIn("latency_did_not_recover", payload["reasons"])

    def test_missing_samples_never_read_as_recovered(self) -> None:
        payload = evaluate_backpressure_recovery(
            pre_burst_p99_ms=None, burst_p99_ms=None, post_burst_p99_ms=None
        )
        self.assertFalse(payload["recovered"])
        self.assertIn("insufficient_samples", payload["reasons"])


class TestClassification(unittest.TestCase):
    def _verdict(self, name: str, kind: str, detected: bool) -> dict:
        return {"name": name, "kind": kind, "drift_detected": detected, "reasons": ["x"] if detected else []}

    def test_a_clean_soak_holds_steady_state(self) -> None:
        result = classify_soak(
            [self._verdict("process_rss_bytes", "resource", False)],
            backpressure={"recovered": True},
        )
        self.assertTrue(result["steady_state_held"])
        self.assertEqual(result["drift_labels"], [])

    def test_each_kind_maps_to_its_honest_label(self) -> None:
        result = classify_soak(
            [
                self._verdict("process_rss_bytes", "resource", True),
                self._verdict("tj_temperature_c", "temperature", True),
                self._verdict("frame_to_command_ms", "latency", True),
            ]
        )
        self.assertIn("memory_drift", result["drift_labels"])
        self.assertIn("thermal_drift", result["drift_labels"])
        self.assertIn("latency_drift", result["drift_labels"])
        self.assertFalse(result["steady_state_held"])

    def test_observed_throttling_is_thermal_drift_even_without_a_ramp(self) -> None:
        result = classify_soak([], thermal_throttling_observed=True)
        self.assertEqual(result["drift_labels"], ["thermal_drift"])

    def test_failed_backpressure_recovery_is_labelled(self) -> None:
        result = classify_soak(
            [], backpressure={"recovered": False, "reasons": ["latency_did_not_recover"]}
        )
        self.assertIn("backpressure_recovery_failed", result["drift_labels"])

    def test_the_monotone_resource_list_is_the_one_checked(self) -> None:
        for name in MONOTONE_RESOURCE_SERIES:
            self.assertIn(name, ("process_rss_bytes", "open_fd_count", "thread_count",
                                 "swap_used_bytes"))


if __name__ == "__main__":
    unittest.main()

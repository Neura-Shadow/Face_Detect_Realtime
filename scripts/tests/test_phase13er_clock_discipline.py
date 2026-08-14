"""Phase 13E-R clock discipline tests.

The whole point of this module is one inequality that must hold for hours::

    issued_timestamp_us <= receiver_now_us

Phase 13E measured what happens when it stops holding: the frozen Phase 13A rule
rejects a command whose issue timestamp is in the receiver's future with zero
tolerance, and 55,804 of 56,671 commands were refused as stale.

These tests simulate two independent oscillators at -50, -10, 0, +10 and +50 ppm
for three simulated hours each, and assert the inequality on every command. The
same simulation is run against the old one-shot model to show the test actually
catches the defect rather than passing vacuously.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from workers.core.clock_discipline import (  # noqa: E402
    DEFAULT_RESYNC_INTERVAL_SEC,
    MIN_DRIFT_BASELINE_SEC,
    DisciplinedClock,
    estimate_drift_ppm,
)
from workers.core.clock_sync import JetsonClockDomain  # noqa: E402

SIMULATED_HOURS = 3.0
SIMULATED_SEC = SIMULATED_HOURS * 3600.0
COMMAND_PERIOD_SEC = 0.16
DRIFT_CASES_PPM = (-50.0, -10.0, 0.0, 10.0, 50.0)
BASE_OFFSET_US = -427_158_519_423
#: Round-trip uncertainty of a real sync on this link was measured at ~513 us.
SYNC_UNCERTAINTY_US = 513


class SimulatedPair:
    """Two independent monotonic clocks with a fixed relative rate error."""

    def __init__(self, drift_ppm: float, *, base_offset_us: int = BASE_OFFSET_US) -> None:
        self.drift_ppm = float(drift_ppm)
        self.base_offset_us = int(base_offset_us)

    def pc_us(self, t_sec: float) -> int:
        return int(round(t_sec * 1e6))

    def jetson_us(self, t_sec: float) -> int:
        return int(round(t_sec * 1e6 * (1.0 + self.drift_ppm / 1e6))) + self.base_offset_us

    def true_offset_us(self, t_sec: float) -> int:
        return self.jetson_us(t_sec) - self.pc_us(t_sec)

    def measure(self, t_sec: float, *, bias_us: int = 0) -> int:
        """A sync measurement, optionally biased by estimation error."""

        return self.true_offset_us(t_sec) + int(bias_us)


def run_simulation(
    model: object,
    pair: SimulatedPair,
    *,
    resync_interval_sec: float = DEFAULT_RESYNC_INTERVAL_SEC,
    duration_sec: float = SIMULATED_SEC,
    resync: bool = True,
) -> Dict[str, object]:
    """Drive a clock model through the simulation, recording future skew.

    ``resync=False`` reproduces the Phase 13E configuration: sync once at
    startup, then trust that measurement for the rest of the run.
    """

    skews = []  # type: List[int]
    next_resync = 0.0
    synced = False
    t = 0.0
    while t < duration_sec:
        if t >= next_resync and (resync or not synced):
            pc_now = pair.pc_us(t)
            # Alternate the measurement bias so the estimator sees realistic
            # scatter rather than a perfectly clean ramp.
            bias = SYNC_UNCERTAINTY_US if int(t / resync_interval_sec) % 2 else -SYNC_UNCERTAINTY_US
            model.update(  # type: ignore[attr-defined]
                jetson_minus_pc_offset_us=pair.measure(t, bias_us=bias),
                clock_uncertainty_us=SYNC_UNCERTAINTY_US,
                round_trip_us=1028,
                observed_at_pc_us=pc_now,
            )
            next_resync = t + resync_interval_sec
            synced = True
        issued = model.issued_timestamp_us(pair.jetson_us(t))  # type: ignore[attr-defined]
        skews.append(int(issued) - pair.pc_us(t))
        t += COMMAND_PERIOD_SEC
    return {
        "samples": len(skews),
        "max_future_skew_us": max(skews),
        "min_skew_us": min(skews),
        "future_reject_count": sum(1 for value in skews if value > 0),
    }


class TestDriftEstimation(unittest.TestCase):
    def test_drift_ppm_is_recovered_from_the_window(self) -> None:
        for ppm in DRIFT_CASES_PPM:
            pair = SimulatedPair(ppm)
            model = DisciplinedClock(resync_interval_sec=DEFAULT_RESYNC_INTERVAL_SEC)
            for index in range(20):
                t = index * DEFAULT_RESYNC_INTERVAL_SEC
                model.update(
                    jetson_minus_pc_offset_us=pair.measure(t),
                    clock_uncertainty_us=SYNC_UNCERTAINTY_US,
                    round_trip_us=1000,
                    observed_at_pc_us=pair.pc_us(t),
                )
            self.assertAlmostEqual(model.drift_ppm, ppm, delta=1.0, msg="ppm=%s" % ppm)

    def test_a_single_observation_reports_no_drift(self) -> None:
        self.assertEqual(estimate_drift_ppm([]), (0.0, 0.0))


class TestShortBaselineDrift(unittest.TestCase):
    """A baseline too short to measure rate must not claim one.

    Found by the first Gate D reboot: the boot-recovery check synced and
    resynced about a second apart, a few hundred microseconds of scatter over
    that baseline implied 455 ppm, the model declared itself degraded for
    implausible drift, and AI authority was withheld from a healthy service.
    """

    def test_two_syncs_a_second_apart_claim_no_drift(self) -> None:
        model = DisciplinedClock(resync_interval_sec=15.0)
        # 400 us of scatter across 1.0 s would be 400 ppm if fitted as a rate.
        model.update(jetson_minus_pc_offset_us=BASE_OFFSET_US, clock_uncertainty_us=411,
                     round_trip_us=1000, observed_at_pc_us=0)
        model.update(jetson_minus_pc_offset_us=BASE_OFFSET_US + 400, clock_uncertainty_us=411,
                     round_trip_us=1000, observed_at_pc_us=1_000_000)
        self.assertEqual(model.drift_ppm, 0.0)
        self.assertFalse(model.drift_estimable)
        self.assertAlmostEqual(model.drift_baseline_sec, 1.0, places=3)
        self.assertNotIn("implausible_drift_ppm", model.degraded_reasons(1_000_000))

    def test_the_scatter_still_inflates_the_guard(self) -> None:
        # Not claiming a slope must not mean claiming certainty.
        model = DisciplinedClock(resync_interval_sec=15.0)
        model.update(jetson_minus_pc_offset_us=BASE_OFFSET_US, clock_uncertainty_us=411,
                     round_trip_us=1000, observed_at_pc_us=0)
        model.update(jetson_minus_pc_offset_us=BASE_OFFSET_US + 400, clock_uncertainty_us=411,
                     round_trip_us=1000, observed_at_pc_us=1_000_000)
        self.assertGreaterEqual(model.drift_residual_us, 200.0)
        self.assertGreater(model.guard_us(1_000_000), 411 + 1000)

    def test_a_long_enough_baseline_still_reports_real_drift(self) -> None:
        pair = SimulatedPair(50.0)
        model = DisciplinedClock(resync_interval_sec=15.0)
        for index in range(6):
            t = index * 15.0
            model.update(jetson_minus_pc_offset_us=pair.measure(t), clock_uncertainty_us=500,
                         round_trip_us=1000, observed_at_pc_us=pair.pc_us(t))
        self.assertTrue(model.drift_estimable)
        self.assertAlmostEqual(model.drift_ppm, 50.0, delta=1.0)

    def test_genuinely_implausible_drift_is_still_caught(self) -> None:
        # The baseline guard must not become a way to hide a real fault.
        pair = SimulatedPair(5000.0)
        model = DisciplinedClock(resync_interval_sec=15.0, max_offset_jump_us=10_000_000)
        for index in range(6):
            t = index * 15.0
            model.update(jetson_minus_pc_offset_us=pair.measure(t), clock_uncertainty_us=500,
                         round_trip_us=1000, observed_at_pc_us=pair.pc_us(t))
        self.assertTrue(model.drift_estimable)
        self.assertIn("implausible_drift_ppm", model.degraded_reasons(pair.pc_us(75.0)))

    def test_minimum_baseline_is_documented(self) -> None:
        self.assertGreater(MIN_DRIFT_BASELINE_SEC, 0.0)


class TestFutureSkewNeverPositive(unittest.TestCase):
    """The inequality that Phase 13E violated, over three simulated hours."""

    def test_disciplined_clock_never_issues_into_the_future(self) -> None:
        for ppm in DRIFT_CASES_PPM:
            pair = SimulatedPair(ppm)
            model = DisciplinedClock(resync_interval_sec=DEFAULT_RESYNC_INTERVAL_SEC)
            result = run_simulation(model, pair)
            self.assertGreater(result["samples"], 60000, "ppm=%s" % ppm)
            self.assertEqual(
                result["future_reject_count"],
                0,
                "ppm=%s produced %s future-dated commands (max skew %s us)"
                % (ppm, result["future_reject_count"], result["max_future_skew_us"]),
            )
            self.assertLessEqual(result["max_future_skew_us"], 0, "ppm=%s" % ppm)

    def test_the_guard_stays_small_enough_to_be_harmless(self) -> None:
        # The guard may only ever make a command older. It must not eat a
        # meaningful part of a 1 s validity window while doing so.
        pair = SimulatedPair(50.0)
        model = DisciplinedClock(resync_interval_sec=DEFAULT_RESYNC_INTERVAL_SEC)
        result = run_simulation(model, pair)
        self.assertGreater(result["min_skew_us"], -100_000, "guard should stay well under 100 ms")

    def test_the_one_shot_model_fails_the_same_simulation(self) -> None:
        # Proves the test is not vacuous: this is the Phase 13E defect.
        failures = {}  # type: Dict[float, int]
        for ppm in DRIFT_CASES_PPM:
            pair = SimulatedPair(ppm)
            legacy = JetsonClockDomain(
                jetson_minus_pc_offset_us=pair.true_offset_us(0.0),
                clock_uncertainty_us=SYNC_UNCERTAINTY_US,
                clock_sync_valid=True,
            )
            skews = []  # type: List[int]
            t = 0.0
            while t < SIMULATED_SEC:
                issued = legacy.issued_timestamp_us(pair.jetson_us(t))
                skews.append(issued - pair.pc_us(t))
                t += COMMAND_PERIOD_SEC
            failures[ppm] = sum(1 for value in skews if value > 0)
        # A positive rate error pushes the Jetson ahead and breaks the rule.
        self.assertGreater(failures[50.0], 0)
        self.assertGreater(failures[10.0], 0)
        # A negative rate error happens to stay safe, which is why short runs
        # and half the population never saw this.
        self.assertEqual(failures[-50.0], 0)

    def test_resync_is_what_fixes_it(self) -> None:
        pair = SimulatedPair(50.0)
        without = run_simulation(
            DisciplinedClock(resync_interval_sec=DEFAULT_RESYNC_INTERVAL_SEC),
            pair,
            resync=False,
            duration_sec=600.0,
        )
        with_resync = run_simulation(
            DisciplinedClock(resync_interval_sec=DEFAULT_RESYNC_INTERVAL_SEC),
            pair,
            duration_sec=600.0,
        )
        self.assertEqual(with_resync["future_reject_count"], 0)
        self.assertGreater(without["future_reject_count"], 0)


class TestResyncAcceptance(unittest.TestCase):
    def _model(self) -> DisciplinedClock:
        return DisciplinedClock(resync_interval_sec=15.0)

    def test_a_healthy_sync_is_kept(self) -> None:
        model = self._model()
        self.assertTrue(
            model.update(
                jetson_minus_pc_offset_us=BASE_OFFSET_US,
                clock_uncertainty_us=500,
                round_trip_us=1000,
                observed_at_pc_us=0,
            )
        )
        self.assertEqual(model.resync_count, 1)
        self.assertEqual(model.generation, 1)
        self.assertEqual(model.resync_failure_count, 0)

    def test_an_over_budget_uncertainty_is_rejected(self) -> None:
        model = self._model()
        self.assertFalse(
            model.update(
                jetson_minus_pc_offset_us=BASE_OFFSET_US,
                clock_uncertainty_us=50_000,
                round_trip_us=900_000,
                observed_at_pc_us=0,
            )
        )
        self.assertEqual(model.resync_failure_count, 1)
        self.assertEqual(model.last_reject_reason, "uncertainty_above_budget")

    def test_an_offset_discontinuity_is_rejected(self) -> None:
        model = self._model()
        model.update(
            jetson_minus_pc_offset_us=BASE_OFFSET_US, clock_uncertainty_us=500,
            round_trip_us=1000, observed_at_pc_us=0,
        )
        self.assertFalse(
            model.update(
                jetson_minus_pc_offset_us=BASE_OFFSET_US + 5_000_000,
                clock_uncertainty_us=500, round_trip_us=1000, observed_at_pc_us=15_000_000,
            )
        )
        self.assertEqual(model.offset_jump_count, 1)
        self.assertEqual(model.last_reject_reason, "offset_discontinuity")

    def test_an_invalid_sync_is_counted_not_applied(self) -> None:
        model = self._model()
        self.assertFalse(
            model.update(
                jetson_minus_pc_offset_us=BASE_OFFSET_US, clock_uncertainty_us=500,
                round_trip_us=1000, observed_at_pc_us=0, valid=False,
            )
        )
        self.assertEqual(model.resync_count, 0)
        self.assertEqual(model.resync_failure_count, 1)

    def test_the_window_is_bounded(self) -> None:
        model = DisciplinedClock(resync_interval_sec=15.0, window_capacity=8)
        for index in range(100):
            model.update(
                jetson_minus_pc_offset_us=BASE_OFFSET_US + index,
                clock_uncertainty_us=500, round_trip_us=1000,
                observed_at_pc_us=index * 15_000_000,
            )
        payload = model.to_dict()
        self.assertEqual(payload["clock_window_size"], 8)
        self.assertEqual(payload["clock_window_capacity"], 8)
        self.assertEqual(payload["clock_window_high_watermark"], 8)
        self.assertEqual(model.resync_count, 100)


class TestDegradation(unittest.TestCase):
    def _synced(self, **kwargs) -> DisciplinedClock:
        model = DisciplinedClock(resync_interval_sec=15.0, **kwargs)
        model.update(
            jetson_minus_pc_offset_us=BASE_OFFSET_US, clock_uncertainty_us=500,
            round_trip_us=1000, observed_at_pc_us=0,
        )
        return model

    def test_no_sync_is_degraded(self) -> None:
        model = DisciplinedClock()
        self.assertTrue(model.clock_sync_degraded)
        self.assertIn("no_valid_clock_sync", model.degraded_reasons())

    def test_a_fresh_sync_is_healthy(self) -> None:
        model = self._synced()
        self.assertEqual(model.degraded_reasons(0), [])

    def test_an_old_model_is_degraded(self) -> None:
        model = self._synced()
        # Three resync intervals is the trust horizon; 10 is far past it.
        self.assertIn("clock_model_too_old", model.degraded_reasons(150_000_000))

    def test_staleness_is_judged_against_the_live_clock_by_default(self) -> None:
        # A model that stops being refreshed must stop being trusted without
        # anyone having to pass it a timestamp. This is the Phase 13E gap.
        model = self._synced()
        self.assertTrue(model.clock_sync_degraded)
        self.assertIn("clock_model_too_old", model.degraded_reasons())

    def test_implausible_drift_is_degraded(self) -> None:
        pair = SimulatedPair(5000.0)
        model = DisciplinedClock(resync_interval_sec=15.0, max_offset_jump_us=10_000_000)
        for index in range(6):
            t = index * 15.0
            model.update(
                jetson_minus_pc_offset_us=pair.measure(t), clock_uncertainty_us=500,
                round_trip_us=1000, observed_at_pc_us=pair.pc_us(t),
            )
        self.assertIn("implausible_drift_ppm", model.degraded_reasons(pair.pc_us(75.0)))

    def test_uncertainty_above_budget_is_degraded(self) -> None:
        model = self._synced()
        model.clock_uncertainty_us = 9000
        self.assertIn("clock_uncertainty_above_budget", model.degraded_reasons(0))

    def test_evidence_records_every_required_field(self) -> None:
        payload = self._synced().to_dict(0)
        for key in (
            "clock_resync_count", "clock_resync_failure_count", "clock_model_age_ms",
            "estimated_offset_us", "estimated_drift_ppm", "clock_uncertainty_us",
            "clock_guard_us", "clock_model_generation", "clock_sync_degraded",
        ):
            self.assertIn(key, payload)


if __name__ == "__main__":
    unittest.main()

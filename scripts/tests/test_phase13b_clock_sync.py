"""Phase 13B clock-domain synchronisation tests.

Pins the mandated sign convention:

    jetson_minus_pc_offset_us = ((t2 - t1) + (t3 - t4)) / 2
    network_delay_us          = (t4 - t1) - (t3 - t2)
    clock_uncertainty_us      = max(0, network_delay_us / 2)
    pc_clock_us               = jetson_clock_us - jetson_minus_pc_offset_us
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.clock_sync import (
    DEFAULT_MAX_UNCERTAINTY_US,
    DEFAULT_SAMPLE_COUNT,
    ClockSyncSample,
    JetsonClockDomain,
    clock_source_info,
    estimate_clock_offset,
    monotonic_us,
)


def build_samples(
    *,
    offset_us: int,
    one_way_us: int,
    processing_us: int,
    count: int = DEFAULT_SAMPLE_COUNT,
    jitter_us: int = 0,
) -> list:
    """Synthesise probes for a Jetson clock that runs ``offset_us`` ahead."""

    samples = []
    for index in range(count):
        extra = jitter_us * index
        t1 = 1_000_000 + index * 10_000
        t2 = t1 + one_way_us + extra + offset_us
        t3 = t2 + processing_us
        t4 = t3 - offset_us + one_way_us + extra
        samples.append(
            ClockSyncSample(
                t1_pc_send_us=t1, t2_jetson_recv_us=t2, t3_jetson_send_us=t3, t4_pc_recv_us=t4
            )
        )
    return samples


class TestClockSyncSample(unittest.TestCase):
    def test_offset_sign_convention(self) -> None:
        sample = ClockSyncSample(
            t1_pc_send_us=1000,
            t2_jetson_recv_us=1000 + 200 + 50_000,
            t3_jetson_send_us=1000 + 300 + 50_000,
            t4_pc_recv_us=1000 + 500,
        )
        expected = ((sample.t2_jetson_recv_us - sample.t1_pc_send_us)
                    + (sample.t3_jetson_send_us - sample.t4_pc_recv_us)) / 2.0
        self.assertAlmostEqual(sample.offset_us, expected)
        self.assertAlmostEqual(sample.offset_us, 50_000.0)

    def test_network_delay_excludes_jetson_processing(self) -> None:
        sample = ClockSyncSample(
            t1_pc_send_us=0,
            t2_jetson_recv_us=100,
            t3_jetson_send_us=900,
            t4_pc_recv_us=1000,
        )
        self.assertAlmostEqual(sample.network_delay_us, 200.0)
        self.assertEqual(sample.rtt_us, 1000)
        self.assertTrue(sample.valid)


class TestEstimateClockOffset(unittest.TestCase):
    def test_min_rtt_estimator_recovers_the_true_offset(self) -> None:
        result = estimate_clock_offset(
            build_samples(offset_us=250_000, one_way_us=400, processing_us=120, jitter_us=50)
        )
        self.assertTrue(result.clock_sync_valid)
        self.assertFalse(result.clock_sync_degraded)
        self.assertEqual(result.estimator, "min_rtt")
        self.assertAlmostEqual(result.jetson_minus_pc_offset_us, 250_000, delta=100)
        self.assertEqual(result.clock_uncertainty_us, 400)
        self.assertEqual(result.clock_sample_count, DEFAULT_SAMPLE_COUNT)
        self.assertEqual(result.clock_valid_sample_count, DEFAULT_SAMPLE_COUNT)
        self.assertTrue(result.one_way_latency_allowed)

    def test_negative_offset_is_preserved(self) -> None:
        result = estimate_clock_offset(
            build_samples(offset_us=-125_000, one_way_us=300, processing_us=100)
        )
        self.assertAlmostEqual(result.jetson_minus_pc_offset_us, -125_000, delta=100)

    def test_conversion_round_trips_into_the_pc_domain(self) -> None:
        result = estimate_clock_offset(
            build_samples(offset_us=77_000, one_way_us=250, processing_us=60)
        )
        jetson_now = 5_000_000
        pc_now = result.to_pc_clock_us(jetson_now)
        self.assertAlmostEqual(pc_now, jetson_now - result.jetson_minus_pc_offset_us)
        self.assertAlmostEqual(pc_now, 5_000_000 - 77_000, delta=100)

    def test_too_few_samples_is_degraded(self) -> None:
        result = estimate_clock_offset(
            build_samples(offset_us=0, one_way_us=100, processing_us=10, count=5)
        )
        self.assertFalse(result.clock_sync_valid)
        self.assertTrue(result.clock_sync_degraded)
        self.assertIn("insufficient", result.reason)

    def test_uncertainty_above_budget_is_degraded(self) -> None:
        result = estimate_clock_offset(
            build_samples(offset_us=0, one_way_us=60_000, processing_us=100)
        )
        self.assertGreater(result.clock_uncertainty_us, DEFAULT_MAX_UNCERTAINTY_US)
        self.assertFalse(result.clock_sync_valid)
        self.assertTrue(result.clock_sync_degraded)
        self.assertFalse(result.one_way_latency_allowed)

    def test_no_valid_samples_is_degraded(self) -> None:
        result = estimate_clock_offset([])
        self.assertFalse(result.clock_sync_valid)
        self.assertTrue(result.clock_sync_degraded)
        self.assertEqual(result.clock_valid_sample_count, 0)

    def test_result_dict_carries_every_required_field(self) -> None:
        payload = estimate_clock_offset(
            build_samples(offset_us=1000, one_way_us=200, processing_us=50)
        ).to_dict()
        for name in (
            "jetson_minus_pc_offset_us",
            "clock_rtt_us",
            "clock_uncertainty_us",
            "clock_sample_count",
            "clock_sync_valid",
            "clock_sync_degraded",
        ):
            self.assertIn(name, payload)


class TestJetsonClockDomain(unittest.TestCase):
    def test_issued_timestamp_never_moves_into_the_pc_future(self) -> None:
        domain = JetsonClockDomain(
            jetson_minus_pc_offset_us=50_000,
            clock_uncertainty_us=300,
            clock_sync_valid=True,
        )
        jetson_now = 10_000_000
        issued = domain.issued_timestamp_us(jetson_now)
        self.assertEqual(issued, jetson_now - 50_000 - 300)
        self.assertLess(issued, domain.to_pc_clock_us(jetson_now))

    def test_degraded_domain_suppresses_one_way_latency(self) -> None:
        degraded = JetsonClockDomain(
            jetson_minus_pc_offset_us=0,
            clock_uncertainty_us=DEFAULT_MAX_UNCERTAINTY_US + 1,
            clock_sync_valid=True,
        )
        self.assertTrue(degraded.clock_sync_degraded)
        self.assertIsNone(degraded.one_way_latency_ms(1_000_000, 1_000_500))

    def test_valid_domain_reports_one_way_latency(self) -> None:
        domain = JetsonClockDomain(
            jetson_minus_pc_offset_us=100_000,
            clock_uncertainty_us=200,
            clock_sync_valid=True,
        )
        latency = domain.one_way_latency_ms(1_000_000, 1_102_000)
        self.assertIsNotNone(latency)
        self.assertAlmostEqual(latency, 2.0, places=3)

    def test_invalid_sync_is_always_degraded(self) -> None:
        domain = JetsonClockDomain(
            jetson_minus_pc_offset_us=0, clock_uncertainty_us=0, clock_sync_valid=False
        )
        self.assertTrue(domain.clock_sync_degraded)
        self.assertIsNone(domain.one_way_latency_ms(1, 2))


class TestMonotonicClock(unittest.TestCase):
    def test_monotonic_us_is_monotonic(self) -> None:
        first = monotonic_us()
        second = monotonic_us()
        self.assertGreaterEqual(second, first)
        self.assertGreater(first, 0)

    def test_clock_source_is_monotonic_and_fine_enough(self) -> None:
        """The clock must resolve far below the 5000 us uncertainty budget.

        Windows `time.monotonic()` is GetTickCount64-backed with a 15.625 ms
        granularity, which is coarser than the whole budget; Phase 13B therefore
        uses `perf_counter_ns`. This test fails loudly if that ever regresses.
        """

        info = clock_source_info()
        self.assertTrue(info["clock_source_monotonic"])
        self.assertLessEqual(info["clock_source_resolution_ns"], 1_000)
        self.assertLess(
            info["clock_source_resolution_ns"] / 1000.0, DEFAULT_MAX_UNCERTAINTY_US / 10.0
        )

    def test_successive_reads_resolve_below_one_millisecond(self) -> None:
        deltas = []
        for _ in range(2000):
            first = monotonic_us()
            second = monotonic_us()
            if second > first:
                deltas.append(second - first)
        self.assertTrue(deltas, "clock never advanced across 2000 back-to-back reads")
        self.assertLess(min(deltas), 1000)


if __name__ == "__main__":
    unittest.main()

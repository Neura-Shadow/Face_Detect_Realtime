"""Phase 13E-R bounded metric container tests.

These containers exist so a long run stops growing in memory. The tests check
both halves of that claim: the numbers stay usable, and the memory stays fixed
no matter how many samples arrive.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.bounded_metrics import (  # noqa: E402
    BoundedCounter,
    BoundedSeries,
    JsonlSink,
    OnlineStat,
)


class TestOnlineStat(unittest.TestCase):
    def test_matches_exact_statistics(self) -> None:
        stat = OnlineStat()
        for value in range(1, 101):
            stat.observe(value)
        self.assertEqual(stat.count, 100)
        self.assertEqual(stat.minimum, 1.0)
        self.assertEqual(stat.maximum, 100.0)
        self.assertAlmostEqual(stat.mean, 50.5)
        self.assertAlmostEqual(stat.stdev, 29.0114919, places=5)

    def test_ignores_nonfinite_samples(self) -> None:
        stat = OnlineStat()
        stat.observe(float("nan"))
        stat.observe(float("inf"))
        self.assertEqual(stat.count, 0)
        self.assertIsNone(stat.mean)

    def test_empty_stat_reports_nothing(self) -> None:
        payload = OnlineStat().to_dict()
        self.assertEqual(payload["count"], 0)
        self.assertIsNone(payload["mean"])


class TestBoundedSeries(unittest.TestCase):
    def test_memory_is_fixed_regardless_of_sample_count(self) -> None:
        series = BoundedSeries("latency_ms", bucket_width=1.0, bucket_count=256, ring_capacity=64)
        for index in range(200_000):
            series.observe(index % 200)
        payload = series.to_dict()
        self.assertEqual(payload["count"], 200_000)
        self.assertEqual(payload["ring_capacity"], 64)
        self.assertEqual(payload["ring_high_watermark"], 64)
        self.assertEqual(len(series.recent()), 64)
        self.assertEqual(len(series._buckets), 256)

    def test_percentiles_land_within_one_bucket_of_exact(self) -> None:
        series = BoundedSeries("latency_ms", bucket_width=1.0, bucket_count=1024)
        series.extend(range(1, 1001))
        self.assertEqual(series.to_dict()["histogram_overflow_count"], 0)
        # Nearest-rank exact values for 1..1000.
        for quantile, exact in ((0.50, 500), (0.95, 950), (0.99, 990)):
            estimate = series.percentile(quantile)
            self.assertLessEqual(
                abs(estimate - exact), series.bucket_width,
                "q=%s estimate=%s exact=%s" % (quantile, estimate, exact),
            )

    def test_exact_bounds_survive_histogram_overflow(self) -> None:
        series = BoundedSeries("latency_ms", bucket_width=1.0, bucket_count=10)
        series.extend([1.0, 5.0, 900.0])
        payload = series.to_dict()
        self.assertEqual(payload["max"], 900.0)
        self.assertEqual(payload["min"], 1.0)
        self.assertEqual(payload["histogram_overflow_count"], 1)
        self.assertEqual(series.percentile(0.99), 900.0)

    def test_negative_values_are_supported(self) -> None:
        # issued_future_skew_us is negative during healthy runtime.
        series = BoundedSeries(
            "issued_future_skew_us", lower_bound=-100_000.0, bucket_width=100.0, bucket_count=2048
        )
        series.extend([-1513, -1600, -1490, -2000])
        payload = series.to_dict()
        self.assertEqual(payload["max"], -1490.0)
        self.assertEqual(payload["histogram_underflow_count"], 0)
        self.assertLessEqual(payload["p99"], 0)

    def test_nonfinite_samples_are_counted_not_mixed_in(self) -> None:
        series = BoundedSeries("latency_ms")
        series.extend([1.0, float("nan"), 3.0])
        payload = series.to_dict()
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["nonfinite_count"], 1)

    def test_empty_series_has_no_percentiles(self) -> None:
        payload = BoundedSeries("latency_ms").to_dict()
        self.assertIsNone(payload["p95"])
        self.assertEqual(payload["count"], 0)


class TestBoundedCounter(unittest.TestCase):
    def test_known_keys_tally_exactly(self) -> None:
        counter = BoundedCounter(max_keys=4)
        for _ in range(10):
            counter.bump("ACCEPTED")
        counter.bump("STALE_REJECT")
        self.assertEqual(counter.to_dict(), {"ACCEPTED": 10, "STALE_REJECT": 1})

    def test_key_explosion_is_capped(self) -> None:
        counter = BoundedCounter(max_keys=4)
        for index in range(100):
            counter.bump("key_%d" % index)
        self.assertEqual(len(counter.to_dict()), 4)
        self.assertEqual(counter.dropped_key_count, 96)


class TestJsonlSink(unittest.TestCase):
    def test_records_stream_to_disk_and_tail_stays_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "records.jsonl")
            sink = JsonlSink(path, tail_capacity=8, flush_every=4)
            for index in range(1000):
                sink.write({"frame_id": index})
            sink.close()
            lines = Path(path).read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1000)
            self.assertEqual(json.loads(lines[-1])["frame_id"], 999)
            self.assertEqual(len(sink.tail()), 8)
            self.assertEqual(sink.written_count, 1000)
            self.assertEqual(sink.write_failure_count, 0)

    def test_a_sink_without_a_path_still_keeps_a_tail(self) -> None:
        sink = JsonlSink(None, tail_capacity=4)
        for index in range(50):
            sink.write({"frame_id": index})
        self.assertEqual(len(sink.tail()), 4)
        self.assertEqual(sink.written_count, 50)
        self.assertFalse(sink.to_dict()["streamed"])

    def test_an_unserialisable_record_is_counted_not_raised(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sink = JsonlSink(str(Path(tmp) / "records.jsonl"))
            sink.write({"bad": object()})
            sink.close()
            self.assertEqual(sink.write_failure_count, 1)
            self.assertIn("TypeError", sink.last_error)


if __name__ == "__main__":
    unittest.main()

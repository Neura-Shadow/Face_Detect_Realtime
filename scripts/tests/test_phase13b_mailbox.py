"""Phase 13B bounded buffering tests: fixed pool + depth-1 latest-frame mailbox."""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.latest_frame_mailbox import (
    DEFAULT_POOL_SIZE,
    MAILBOX_DEPTH,
    BufferOwnershipError,
    BufferState,
    FixedBufferPool,
    FrameFlowMetrics,
    LatestFrameMailbox,
)


class TestFixedBufferPool(unittest.TestCase):
    def setUp(self) -> None:
        self.pool = FixedBufferPool(size=3, capacity_bytes=1024)

    def test_default_pool_size_is_three(self) -> None:
        self.assertEqual(DEFAULT_POOL_SIZE, 3)

    def test_pool_is_bounded_and_reports_acquire_failures(self) -> None:
        buffers = [self.pool.acquire() for _ in range(3)]
        self.assertTrue(all(item is not None for item in buffers))
        self.assertIsNone(self.pool.acquire())
        self.assertEqual(self.pool.snapshot()["buffer_acquire_failures"], 1)
        self.assertEqual(self.pool.snapshot()["buffer_pool_high_watermark"], 3)
        for item in buffers:
            self.pool.release(item)
        self.assertEqual(self.pool.in_use, 0)

    def test_ownership_states_are_deterministic(self) -> None:
        buffer = self.pool.acquire()
        self.assertIs(buffer.state, BufferState.TRANSPORT_OWNED)
        self.pool.transfer(buffer, BufferState.MAILBOX_OWNED)
        self.assertIs(buffer.state, BufferState.MAILBOX_OWNED)
        self.pool.transfer(buffer, BufferState.PROCESSING_OWNED)
        self.assertIs(buffer.state, BufferState.PROCESSING_OWNED)
        self.pool.release(buffer)
        self.assertIs(buffer.state, BufferState.FREE)

    def test_double_release_is_rejected(self) -> None:
        buffer = self.pool.acquire()
        self.pool.release(buffer)
        with self.assertRaises(BufferOwnershipError):
            self.pool.release(buffer)

    def test_use_after_release_is_rejected(self) -> None:
        buffer = self.pool.acquire()
        self.pool.release(buffer)
        with self.assertRaises(BufferOwnershipError):
            self.pool.transfer(buffer, BufferState.MAILBOX_OWNED)
        with self.assertRaises(BufferOwnershipError):
            buffer.payload()

    def test_transfer_to_free_is_rejected(self) -> None:
        buffer = self.pool.acquire()
        with self.assertRaises(ValueError):
            self.pool.transfer(buffer, BufferState.FREE)
        self.pool.release(buffer)

    def test_foreign_buffer_release_is_rejected(self) -> None:
        other = FixedBufferPool(size=1, capacity_bytes=16)
        foreign = other.acquire()
        with self.assertRaises(BufferOwnershipError):
            self.pool.release(foreign)
        other.release(foreign)

    def test_leak_check_reports_outstanding_buffers(self) -> None:
        buffer = self.pool.acquire()
        self.assertTrue(self.pool.leak_check()["buffer_leak_detected"])
        self.pool.release(buffer)
        self.assertFalse(self.pool.leak_check()["buffer_leak_detected"])


class TestLatestFrameMailbox(unittest.TestCase):
    def setUp(self) -> None:
        self.pool = FixedBufferPool(size=3, capacity_bytes=64)
        self.mailbox = LatestFrameMailbox(self.pool)

    def test_configured_depth_is_one(self) -> None:
        self.assertEqual(MAILBOX_DEPTH, 1)

    def test_newest_frame_wins_and_older_buffer_is_released(self) -> None:
        first = self.pool.acquire()
        second = self.pool.acquire()
        self.assertFalse(self.mailbox.publish(first))
        self.assertTrue(self.mailbox.publish(second))
        self.assertIs(first.state, BufferState.FREE)
        self.assertIs(second.state, BufferState.MAILBOX_OWNED)
        snapshot = self.mailbox.snapshot()
        self.assertEqual(snapshot["max_mailbox_depth"], 1)
        self.assertEqual(snapshot["latest_frame_overwrite_count"], 1)

        taken = self.mailbox.take()
        self.assertIs(taken, second)
        self.assertIs(taken.state, BufferState.PROCESSING_OWNED)
        self.pool.release(taken)
        self.assertIsNone(self.mailbox.take())

    def test_depth_never_exceeds_one_under_burst(self) -> None:
        for _ in range(50):
            buffer = self.pool.acquire()
            self.assertIsNotNone(buffer)
            self.mailbox.publish(buffer)
            self.assertLessEqual(self.mailbox.depth, 1)
        self.assertEqual(self.mailbox.max_depth_observed, 1)
        self.mailbox.drain()
        self.assertEqual(self.pool.in_use, 0)

    def test_concurrent_publish_and_take_keep_the_pool_balanced(self) -> None:
        stop = threading.Event()
        errors = []

        def producer() -> None:
            try:
                for _ in range(400):
                    buffer = self.pool.acquire()
                    if buffer is None:
                        continue
                    self.mailbox.publish(buffer)
            except Exception as exc:  # pragma: no cover - surfaced via assertion
                errors.append(exc)
            finally:
                stop.set()

        def consumer() -> None:
            try:
                while not stop.is_set():
                    buffer = self.mailbox.take()
                    if buffer is not None:
                        self.pool.release(buffer)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=producer), threading.Thread(target=consumer)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.mailbox.drain()
        while True:
            buffer = self.mailbox.take()
            if buffer is None:
                break
            self.pool.release(buffer)
        self.assertEqual(errors, [])
        self.assertEqual(self.mailbox.max_depth_observed, 1)
        self.assertFalse(self.pool.leak_check()["buffer_leak_detected"])


class TestFrameFlowMetrics(unittest.TestCase):
    def test_required_metric_names_are_present(self) -> None:
        pool = FixedBufferPool(size=3, capacity_bytes=32)
        mailbox = LatestFrameMailbox(pool)
        metrics = FrameFlowMetrics()
        metrics.frames_received = 300
        metrics.frames_decoded = 299
        metrics.frames_processed = 298
        metrics.frames_dropped_transport = 1
        metrics.frames_dropped_mailbox = 2
        metrics.stale_frame_reject_count = 1
        metrics.record_reject("FRAME_CRC_REJECT")
        for value in (5.0, 7.0, 9.0, 11.0, 13.0):
            metrics.record_frame_age(value)
        payload = metrics.to_dict(pool, mailbox)

        for name in (
            "frames_received",
            "frames_decoded",
            "frames_processed",
            "frames_dropped_transport",
            "frames_dropped_mailbox",
            "buffer_acquire_failures",
            "max_mailbox_depth",
            "latest_frame_overwrite_count",
            "buffer_pool_size",
            "buffer_pool_high_watermark",
            "stale_frame_reject_count",
            "frame_age_ms_p50",
            "frame_age_ms_p95",
            "frame_age_ms_p99",
        ):
            self.assertIn(name, payload)
        self.assertEqual(payload["frame_reject_counts"]["FRAME_CRC_REJECT"], 1)
        self.assertEqual(payload["buffer_pool_size"], 3)
        self.assertEqual(payload["frame_age_ms_p50"], 9.0)
        self.assertEqual(payload["frame_age_ms_p95"], 13.0)
        self.assertEqual(payload["frame_age_ms_p99"], 13.0)

    def test_frame_age_percentiles_ignore_missing_samples(self) -> None:
        pool = FixedBufferPool(size=1, capacity_bytes=8)
        mailbox = LatestFrameMailbox(pool)
        metrics = FrameFlowMetrics()
        metrics.record_frame_age(None)
        payload = metrics.to_dict(pool, mailbox)
        self.assertIsNone(payload["frame_age_ms_p50"])
        self.assertEqual(payload["frame_age_sample_count"], 0)


if __name__ == "__main__":
    unittest.main()

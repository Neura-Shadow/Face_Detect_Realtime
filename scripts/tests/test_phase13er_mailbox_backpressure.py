"""Phase 13E-R regression tests for two defects that only appear under overload.

Phase 13E never overloaded the pipeline, so neither of these was visible. The
first real burst surfaced both at once:

1. Reading and processing shared a thread, so the depth-1 mailbox was never
   contended and ``frames_dropped_mailbox`` stayed at zero no matter how fast
   frames arrived. The backlog accumulated in the kernel socket buffer instead
   and frames aged out — an unbounded queue wearing a bounded one's metrics.

2. ``buffer_leak_detected`` was computed from any non-free buffer, so reading
   metrics while a frame was legitimately in flight reported a leak. Idle runs
   happened to be clean, which is why it had never fired.
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.latest_frame_mailbox import (  # noqa: E402
    BufferState,
    FixedBufferPool,
    FrameFlowMetrics,
    LatestFrameMailbox,
)


class TestLeakAllowance(unittest.TestCase):
    def test_an_in_flight_buffer_is_not_a_leak_while_running(self) -> None:
        pool = FixedBufferPool(size=3, capacity_bytes=64)
        held = pool.acquire(BufferState.TRANSPORT_OWNED)
        self.assertIsNotNone(held)
        self.assertFalse(pool.leak_check(max_in_flight=1)["buffer_leak_detected"])
        self.assertTrue(pool.leak_check(max_in_flight=0)["buffer_leak_detected"])
        self.assertEqual(pool.leak_check(max_in_flight=1)["buffer_in_flight_count"], 1)

    def test_more_held_than_allowed_is_still_a_leak(self) -> None:
        pool = FixedBufferPool(size=3, capacity_bytes=64)
        pool.acquire(BufferState.TRANSPORT_OWNED)
        pool.acquire(BufferState.TRANSPORT_OWNED)
        self.assertTrue(pool.leak_check(max_in_flight=1)["buffer_leak_detected"])

    def test_shutdown_semantics_are_unchanged(self) -> None:
        pool = FixedBufferPool(size=2, capacity_bytes=64)
        buffer = pool.acquire(BufferState.TRANSPORT_OWNED)
        pool.release(buffer)
        report = pool.leak_check()
        self.assertFalse(report["buffer_leak_detected"])
        self.assertEqual(report["leaked_buffer_indices"], [])

    def test_flow_metrics_carry_the_allowance_through(self) -> None:
        pool = FixedBufferPool(size=3, capacity_bytes=64)
        mailbox = LatestFrameMailbox(pool)
        flow = FrameFlowMetrics()
        pool.acquire(BufferState.TRANSPORT_OWNED)
        running = flow.to_dict(pool, mailbox, max_in_flight=3)
        at_rest = flow.to_dict(pool, mailbox)
        self.assertFalse(running["buffer_leak_detected"])
        self.assertTrue(at_rest["buffer_leak_detected"])
        self.assertEqual(running["buffer_in_flight_count"], 1)
        self.assertEqual(running["buffer_max_in_flight_allowance"], 3)


class TestLatestFrameOnlyUnderOverload(unittest.TestCase):
    """The mailbox must discard superseded frames, not queue them."""

    def _fill(self, pool: FixedBufferPool, value: bytes) -> object:
        buffer = pool.acquire(BufferState.TRANSPORT_OWNED)
        assert buffer is not None
        buffer.data[: len(value)] = value
        buffer.length = len(value)
        return buffer

    def test_a_fast_producer_causes_drops_not_growth(self) -> None:
        pool = FixedBufferPool(size=3, capacity_bytes=64)
        mailbox = LatestFrameMailbox(pool)
        drops = 0
        for index in range(20):
            buffer = self._fill(pool, b"frame-%02d" % index)
            if mailbox.publish(buffer):
                drops += 1
        # Depth never exceeds one no matter how many frames arrive.
        self.assertEqual(mailbox.snapshot()["max_mailbox_depth"], 1)
        self.assertEqual(drops, 19)
        # The survivor is the newest, not the oldest.
        newest = mailbox.take()
        self.assertEqual(newest.payload(), b"frame-19")
        pool.release(newest)

    def test_a_slow_consumer_still_sees_the_newest_frame(self) -> None:
        pool = FixedBufferPool(size=3, capacity_bytes=64)
        mailbox = LatestFrameMailbox(pool)
        seen = []
        stop = threading.Event()

        def consume() -> None:
            while not stop.is_set():
                buffer = mailbox.take()
                if buffer is None:
                    time.sleep(0.001)
                    continue
                seen.append(bytes(buffer.payload()))
                # Deliberately slower than the producer.
                time.sleep(0.01)
                pool.release(buffer)

        worker = threading.Thread(target=consume)
        worker.start()
        try:
            for index in range(60):
                buffer = self._fill(pool, b"f%03d" % index)
                mailbox.publish(buffer)
                time.sleep(0.001)
            time.sleep(0.1)
        finally:
            stop.set()
            worker.join(timeout=5)

        self.assertGreater(len(seen), 0)
        # The consumer skipped ahead rather than working through a backlog.
        self.assertLess(len(seen), 60)
        self.assertEqual(seen, sorted(seen), "frames must never be delivered out of order")

    def test_the_pool_is_never_exhausted_by_overload(self) -> None:
        pool = FixedBufferPool(size=3, capacity_bytes=64)
        mailbox = LatestFrameMailbox(pool)
        for index in range(500):
            buffer = self._fill(pool, b"f%03d" % (index % 1000))
            mailbox.publish(buffer)
            taken = mailbox.take()
            if taken is not None:
                pool.release(taken)
        self.assertEqual(pool.acquire_failure_count, 0)
        self.assertEqual(pool.snapshot()["buffer_pool_in_use"], 0)


if __name__ == "__main__":
    unittest.main()

"""Phase 13E-R independent frame producer tests.

Phase 13E's backpressure gate failed for a reason the metrics did not show:
the burst loop called ``session.tick()`` before every publish, so CARLA set the
rate and a nominal 10 FPS burst delivered 2.48. These tests pin the property
that fixes it -- the producer's rate is set by its own clock -- and the property
that makes the gate meaningful: input must actually outrun a slow consumer.
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

from simulation.independent_frame_producer import (  # noqa: E402
    EncodedFrame,
    EncodedFrameRing,
    IndependentFrameProducer,
)


class FakePublishResult:
    def __init__(self, published: bool, send_ms: float = 0.1, error: str = "") -> None:
        self.published = published
        self.send_ms = send_ms
        self.error = error
        self.frame_id = 0


class FakePublisher:
    """Records publishes; can simulate a slow or failing transport."""

    def __init__(self, *, send_delay_sec: float = 0.0, fail_after: Optional[int] = None) -> None:
        self.send_delay_sec = send_delay_sec
        self.fail_after = fail_after
        self.calls = 0
        self.payloads = []  # type: List[bytes]
        self.simulation_timestamps = []  # type: List[int]
        self.lock = threading.Lock()

    def publish_encoded(self, payload, *, width, height, channels=3,
                        simulation_timestamp_us=0, **kwargs) -> FakePublishResult:
        if self.send_delay_sec:
            time.sleep(self.send_delay_sec)
        with self.lock:
            self.calls += 1
            self.payloads.append(payload)
            self.simulation_timestamps.append(simulation_timestamp_us)
            count = self.calls
        if self.fail_after is not None and count > self.fail_after:
            return FakePublishResult(False, error="transport closed")
        return FakePublishResult(True)


def make_frames(count: int = 3) -> List[EncodedFrame]:
    return [
        EncodedFrame(b"jpeg-%d" % index, width=640, height=360, simulation_timestamp_us=index)
        for index in range(count)
    ]


class TestPacing(unittest.TestCase):
    def test_rate_is_set_by_the_producer_not_the_caller(self) -> None:
        publisher = FakePublisher()
        producer = IndependentFrameProducer(publisher, make_frames(), target_fps=50.0)
        producer.start()
        time.sleep(1.0)
        metrics = producer.stop()
        # Nothing in this test ticks a simulator; the producer paced itself.
        self.assertGreaterEqual(metrics["producer_frames_published"], 25)
        self.assertFalse(metrics["producer_paced_by_carla_tick"])
        self.assertEqual(metrics["producer_transport"], "real_jilf_tcp")

    def test_input_outruns_a_slow_consumer(self) -> None:
        # This is the Phase 13E gap: the burst must be able to exceed what the
        # consumer retires. A 40 ms send is a 25 FPS ceiling; ask for 100.
        publisher = FakePublisher(send_delay_sec=0.04)
        producer = IndependentFrameProducer(publisher, make_frames(), target_fps=100.0)
        producer.start()
        time.sleep(1.0)
        metrics = producer.stop()
        self.assertGreater(metrics["producer_frames_published"], 10)
        self.assertLess(metrics["producer_input_fps"], 100.0)
        # It kept trying at its own cadence rather than blocking forever.
        self.assertGreater(metrics["producer_late_wakeups"] + metrics["producer_catchup_resets"], 0)

    def test_catchup_is_bounded(self) -> None:
        # A stalled send must not be followed by an unbounded make-up burst.
        publisher = FakePublisher(send_delay_sec=0.0)
        producer = IndependentFrameProducer(publisher, make_frames(), target_fps=20.0)
        producer.start()
        time.sleep(0.3)
        producer.stop()
        # 20 FPS for ~0.3 s is ~6 frames; a runaway would be hundreds.
        self.assertLess(publisher.calls, 60)

    def test_replayed_frames_carry_a_fresh_timestamp(self) -> None:
        publisher = FakePublisher()
        producer = IndependentFrameProducer(publisher, make_frames(), target_fps=100.0)
        producer.start()
        time.sleep(0.3)
        producer.stop()
        stamps = publisher.simulation_timestamps
        self.assertGreater(len(stamps), 2)
        # A frozen timestamp would make every replayed frame look equally stale.
        self.assertGreater(len(set(stamps)), 1)
        self.assertEqual(stamps, sorted(stamps))

    def test_all_ring_frames_are_used(self) -> None:
        publisher = FakePublisher()
        frames = make_frames(4)
        producer = IndependentFrameProducer(publisher, frames, target_fps=100.0)
        producer.start()
        time.sleep(0.4)
        producer.stop()
        self.assertEqual(set(publisher.payloads), {frame.payload for frame in frames})


class TestFailureHandling(unittest.TestCase):
    def test_publish_failures_are_counted_not_raised(self) -> None:
        publisher = FakePublisher(fail_after=3)
        producer = IndependentFrameProducer(publisher, make_frames(), target_fps=100.0)
        producer.start()
        time.sleep(0.4)
        metrics = producer.stop()
        self.assertEqual(metrics["producer_frames_published"], 3)
        self.assertGreater(metrics["producer_publish_failures"], 0)
        self.assertEqual(metrics["producer_last_error"], "transport closed")

    def test_a_raising_transport_does_not_kill_the_thread(self) -> None:
        class Exploding:
            def __init__(self) -> None:
                self.calls = 0

            def publish_encoded(self, payload, **kwargs):
                self.calls += 1
                raise OSError("socket gone")

        publisher = Exploding()
        producer = IndependentFrameProducer(publisher, make_frames(), target_fps=100.0)
        producer.start()
        time.sleep(0.3)
        metrics = producer.stop()
        self.assertGreater(publisher.calls, 1)
        self.assertEqual(metrics["producer_frames_published"], 0)
        self.assertIn("socket gone", metrics["producer_last_error"])

    def test_an_empty_frame_set_is_rejected_up_front(self) -> None:
        with self.assertRaises(ValueError):
            IndependentFrameProducer(FakePublisher(), [], target_fps=10.0)

    def test_stop_is_idempotent_enough_to_call_in_a_finally(self) -> None:
        producer = IndependentFrameProducer(FakePublisher(), make_frames(), target_fps=50.0)
        producer.start()
        producer.stop()
        self.assertFalse(producer.running)
        producer.stop()


class TestEncodedFrameRing(unittest.TestCase):
    class RecordingPublisher:
        def __init__(self) -> None:
            self.encoded = 0

        def bgra_to_bgr(self, bgra: np.ndarray) -> np.ndarray:
            return bgra[:, :, :3]

        def encode(self, bgr: np.ndarray) -> bytes:
            self.encoded += 1
            return b"payload-%d" % self.encoded

    def test_ring_stops_at_capacity(self) -> None:
        publisher = self.RecordingPublisher()
        ring = EncodedFrameRing(capacity=3)
        bgra = np.zeros((360, 640, 4), dtype=np.uint8)
        kept = [ring.capture_bgra(publisher, bgra) for _ in range(10)]
        self.assertEqual(kept.count(True), 3)
        self.assertTrue(ring.full)
        self.assertEqual(len(ring.frames()), 3)
        # Encoding stopped once full; it did not keep paying the cost.
        self.assertEqual(publisher.encoded, 3)

    def test_ring_records_its_provenance(self) -> None:
        publisher = self.RecordingPublisher()
        ring = EncodedFrameRing(capacity=2)
        bgra = np.zeros((360, 640, 4), dtype=np.uint8)
        ring.capture_bgra(publisher, bgra, simulation_timestamp_us=42)
        payload = ring.to_dict()
        self.assertEqual(payload["encoded_frame_ring_capacity"], 2)
        self.assertEqual(payload["encoded_frame_ring_size"], 1)
        self.assertEqual(payload["encoded_frame_source"], "carla_camera_capture")
        self.assertEqual(ring.frames()[0].simulation_timestamp_us, 42)

    def test_dimensions_come_from_the_captured_frame(self) -> None:
        ring = EncodedFrameRing(capacity=1)
        ring.capture_bgra(self.RecordingPublisher(), np.zeros((720, 1280, 4), dtype=np.uint8))
        frame = ring.frames()[0]
        self.assertEqual((frame.width, frame.height, frame.channels), (1280, 720, 3))

    def test_an_encode_failure_is_not_retained(self) -> None:
        class Failing:
            def bgra_to_bgr(self, bgra):
                return bgra

            def encode(self, bgr):
                raise ValueError("encoder unavailable")

        ring = EncodedFrameRing(capacity=2)
        self.assertFalse(ring.capture_bgra(Failing(), np.zeros((8, 8, 4), dtype=np.uint8)))
        self.assertEqual(len(ring.frames()), 0)


if __name__ == "__main__":
    unittest.main()

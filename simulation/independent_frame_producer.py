"""Phase 13E-R Goal 2 frame producer, paced by its own clock.

Phase 13E tried to prove backpressure by publishing inside the CARLA driving
loop. Every publish was preceded by ``session.tick()``, so the "10 FPS burst"
actually ran at 2.48 FPS: the simulator, not the pipeline, was the bottleneck.
Input never exceeded what the Jetson could retire, so nothing was ever dropped
and latest-frame-only was never exercised. The gate could not be demonstrated.

This producer removes the simulator from the pacing path. It runs on its own
thread, publishes pre-encoded JPEG payloads over the same real JILF transport,
and is limited only by the socket and its own target interval. The consumer is
unchanged: the real Jetson, real FP16 engine, real mailbox of depth one.

Frames are real CARLA camera output captured during the run and replayed from a
bounded ring, so the content that reaches the engine is representative even
though the pacing is synthetic. Payloads are encoded once up front, because a
producer that re-encodes every frame is rate-limited by the PC's JPEG encoder
rather than by its own clock — the same class of mistake as pacing on ticks.

No claim is made here about CARLA closed-loop control rate during a burst. The
burst measures the transport and the consumer, and says so.

Runtime compatibility: Jetson Python 3.8.10 (this module runs on the PC).
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.bounded_metrics import BoundedSeries
from workers.core.clock_sync import monotonic_us

DEFAULT_TARGET_FPS = 12.0
DEFAULT_RING_CAPACITY = 8
#: Never try to make up more than this much lost time after a slow send; a
#: producer that chases its own backlog turns a hiccup into a runaway burst.
MAX_CATCHUP_SEC = 0.5


class EncodedFrame:
    """One pre-encoded JPEG payload with the header fields it needs."""

    __slots__ = ("payload", "width", "height", "channels", "simulation_timestamp_us")

    def __init__(
        self,
        payload: bytes,
        *,
        width: int,
        height: int,
        channels: int = 3,
        simulation_timestamp_us: int = 0,
    ) -> None:
        self.payload = payload
        self.width = int(width)
        self.height = int(height)
        self.channels = int(channels)
        self.simulation_timestamp_us = int(simulation_timestamp_us)


class IndependentFrameProducer:
    """Publishes at a target rate on a dedicated thread, independent of CARLA."""

    def __init__(
        self,
        publisher: Any,
        frames: Sequence[EncodedFrame],
        *,
        target_fps: float = DEFAULT_TARGET_FPS,
        advance_simulation_timestamp: bool = True,
    ) -> None:
        if not frames:
            raise ValueError("IndependentFrameProducer requires at least one encoded frame")
        self.publisher = publisher
        self.frames = list(frames)
        self.target_fps = float(target_fps)
        self.interval_sec = 1.0 / max(1e-6, self.target_fps)
        self.advance_simulation_timestamp = bool(advance_simulation_timestamp)

        self._thread = None  # type: Optional[threading.Thread]
        self._stop = threading.Event()
        self._lock = threading.Lock()

        self.publish_attempts = 0
        self.frames_published = 0
        self.publish_failures = 0
        self.late_wakeups = 0
        self.catchup_resets = 0
        self.started_monotonic_us = 0
        self.stopped_monotonic_us = 0
        self.send_ms = BoundedSeries("producer_send_ms", bucket_width=0.5, bucket_count=8192)
        self.interval_ms = BoundedSeries(
            "producer_interval_ms", bucket_width=1.0, bucket_count=8192
        )
        self.last_error = ""

    # ── lifecycle ───────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("producer already started")
        self._stop.clear()
        self.started_monotonic_us = monotonic_us()
        self._thread = threading.Thread(
            target=self._run, name="phase13er-frame-producer", daemon=True
        )
        self._thread.start()

    def stop(self, *, timeout_sec: float = 10.0) -> Dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_sec)
            self._thread = None
        self.stopped_monotonic_us = monotonic_us()
        return self.metrics()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── loop ────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        next_at = time.perf_counter()
        last_publish = None  # type: Optional[float]
        index = 0
        while not self._stop.is_set():
            now = time.perf_counter()
            remaining = next_at - now
            if remaining > 0:
                # Short sleeps keep the stop signal responsive and keep the
                # wake-up close to the deadline on Windows' coarse timer.
                self._stop.wait(min(remaining, 0.002))
                continue
            if now - next_at > MAX_CATCHUP_SEC:
                self.catchup_resets += 1
                next_at = now
            elif now - next_at > self.interval_sec:
                self.late_wakeups += 1
            next_at += self.interval_sec

            frame = self.frames[index % len(self.frames)]
            index += 1
            self._publish(frame)
            if last_publish is not None:
                self.interval_ms.observe((now - last_publish) * 1000.0)
            last_publish = now

    def _publish(self, frame: EncodedFrame) -> None:
        simulation_timestamp_us = frame.simulation_timestamp_us
        if self.advance_simulation_timestamp:
            # Replayed payloads must not carry a frozen simulation timestamp,
            # or the consumer would judge every burst frame equally stale.
            simulation_timestamp_us = monotonic_us()
        try:
            result = self.publisher.publish_encoded(
                frame.payload,
                width=frame.width,
                height=frame.height,
                channels=frame.channels,
                simulation_timestamp_us=simulation_timestamp_us,
            )
        except Exception as exc:  # pragma: no cover - transport already wraps its own
            with self._lock:
                self.publish_attempts += 1
                self.publish_failures += 1
                self.last_error = "%s: %s" % (type(exc).__name__, exc)
            return
        with self._lock:
            self.publish_attempts += 1
            if result.published:
                self.frames_published += 1
                self.send_ms.observe(float(result.send_ms))
            else:
                self.publish_failures += 1
                if result.error:
                    self.last_error = str(result.error)

    # ── evidence ────────────────────────────────────────────────────────────

    def elapsed_sec(self) -> float:
        end = self.stopped_monotonic_us or monotonic_us()
        if not self.started_monotonic_us:
            return 0.0
        return max(0.0, (end - self.started_monotonic_us) / 1e6)

    def metrics(self) -> Dict[str, Any]:
        elapsed = self.elapsed_sec()
        with self._lock:
            published = self.frames_published
            attempts = self.publish_attempts
            failures = self.publish_failures
        return {
            "producer_target_fps": round(self.target_fps, 3),
            "producer_elapsed_sec": round(elapsed, 3),
            "producer_publish_attempts": attempts,
            "producer_frames_published": published,
            "producer_publish_failures": failures,
            "producer_input_fps": round(published / elapsed, 3) if elapsed > 0 else 0.0,
            "producer_attempt_fps": round(attempts / elapsed, 3) if elapsed > 0 else 0.0,
            "producer_late_wakeups": self.late_wakeups,
            "producer_catchup_resets": self.catchup_resets,
            "producer_ring_size": len(self.frames),
            "producer_send_ms": self.send_ms.to_dict(),
            "producer_interval_ms": self.interval_ms.to_dict(),
            "producer_last_error": self.last_error,
            "producer_paced_by": "dedicated_thread_monotonic_clock",
            "producer_paced_by_carla_tick": False,
            "producer_transport": "real_jilf_tcp",
        }


class EncodedFrameRing:
    """Bounded ring of recently captured frames, encoded once for replay."""

    def __init__(self, capacity: int = DEFAULT_RING_CAPACITY) -> None:
        self.capacity = max(1, int(capacity))
        self._frames = []  # type: List[EncodedFrame]
        self._lock = threading.Lock()
        self.captured_count = 0

    def capture_bgra(
        self, publisher: Any, bgra: np.ndarray, *, simulation_timestamp_us: int = 0
    ) -> bool:
        """Encode and retain one CARLA BGRA frame. Returns whether it was kept.

        The conversion goes through the publisher's own mandated colour path, so
        replayed payloads are byte-identical to what the live path would send.
        """

        with self._lock:
            if len(self._frames) >= self.capacity:
                return False
        try:
            payload = publisher.encode(publisher.bgra_to_bgr(bgra))
        except Exception:
            return False
        height, width = int(bgra.shape[0]), int(bgra.shape[1])
        with self._lock:
            if len(self._frames) >= self.capacity:
                return False
            self._frames.append(
                EncodedFrame(
                    payload,
                    width=width,
                    height=height,
                    channels=3,
                    simulation_timestamp_us=simulation_timestamp_us,
                )
            )
            self.captured_count += 1
        return True

    def frames(self) -> List[EncodedFrame]:
        with self._lock:
            return list(self._frames)

    @property
    def full(self) -> bool:
        with self._lock:
            return len(self._frames) >= self.capacity

    def to_dict(self) -> Dict[str, Any]:
        frames = self.frames()
        return {
            "encoded_frame_ring_capacity": self.capacity,
            "encoded_frame_ring_size": len(frames),
            "encoded_frame_payload_bytes": [len(item.payload) for item in frames],
            "encoded_frame_source": "carla_camera_capture",
        }

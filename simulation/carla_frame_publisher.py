"""Phase 13B bounded CARLA frame publisher (simulation PC -> real Jetson).

Colour path (mandatory, no shortcuts):

    CARLA raw BGRA -> explicit BGRA-to-BGR -> JPEG encode -> TCP JPEG payload

The Jetson decodes that payload back to BGR8. Raw CARLA BGRA is never sent
while the header declares BGR8.

The publisher is bounded: exactly one frame is in flight at a time and there is
no pending-frame list. If the transport cannot take a frame, the frame is
dropped and counted; nothing queues up.
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.bounded_metrics import BoundedSeries
from workers.core.clock_sync import monotonic_us
from workers.core.frame_transport import (
    FrameStreamClient,
    FrameTransportError,
    JpegCodec,
    JpegCodecError,
)
from workers.core.jil_protocol import (
    FRAME_HEADER_SIZE,
    FrameCodec,
    FrameHeader,
    PixelFormat,
    crc32_iso_hdlc,
    encode_frame_header,
)

DEFAULT_CAMERA_WIDTH = 640
DEFAULT_CAMERA_HEIGHT = 360
DEFAULT_JPEG_QUALITY = 85


@dataclass
class FramePublisherFaults:
    """Deterministic one-at-a-time frame fault injection switches."""

    corrupt_payload_crc: int = 0
    oversized_payload: int = 0
    invalid_dimensions: int = 0
    unsupported_codec: int = 0
    unsupported_version: int = 0
    partial_payload: int = 0
    zero_payload: int = 0
    stale_timestamp: int = 0

    def any_active(self) -> bool:
        return any(
            getattr(self, name) for name in (
                "corrupt_payload_crc",
                "oversized_payload",
                "invalid_dimensions",
                "unsupported_codec",
                "unsupported_version",
                "partial_payload",
                "zero_payload",
                "stale_timestamp",
            )
        )


#: Faults that reject the 56-byte header before the payload is read. The rest
#: of that frame stays in the TCP stream, so the publisher must reconnect to
#: keep the stream framed. A payload-CRC fault is fully consumed and does not.
HEADER_LEVEL_FAULTS = frozenset(
    {
        "oversized_frame_payload",
        "invalid_frame_dimensions",
        "unsupported_frame_codec",
        "unsupported_frame_protocol_version",
        "zero_size_frame_payload",
        "partial_frame_payload",
    }
)


@dataclass
class PublishResult:
    """Outcome of a single publish attempt."""

    published: bool
    frame_id: int
    payload_bytes: int = 0
    encode_ms: float = 0.0
    send_ms: float = 0.0
    fault: Optional[str] = None
    error: Optional[str] = None

    @property
    def requires_reconnect(self) -> bool:
        return self.fault in HEADER_LEVEL_FAULTS


class CarlaFramePublisher:
    """Bounded JPEG frame publisher over the Phase 13B TCP frame transport."""

    def __init__(
        self,
        client: FrameStreamClient,
        *,
        codec: Optional[JpegCodec] = None,
        width: int = DEFAULT_CAMERA_WIDTH,
        height: int = DEFAULT_CAMERA_HEIGHT,
        jpeg_quality: int = DEFAULT_JPEG_QUALITY,
        max_payload_bytes: Optional[int] = None,
    ) -> None:
        self.client = client
        self.codec = codec or JpegCodec(quality=jpeg_quality)
        self.width = int(width)
        self.height = int(height)
        self.max_payload_bytes = int(max_payload_bytes or client.max_payload_bytes)
        self.faults = FramePublisherFaults()
        self.stale_offset_us = 30_000_000
        self.frames_published = 0
        self.frames_dropped_backpressure = 0
        self.frames_failed = 0
        self.frames_fault_injected = 0
        self.bytes_published = 0
        # Phase 13E-R Goal 3: these were unbounded lists. A ten-frames-per-second
        # burst on top of a two-hour soak makes that a leak, not a detail.
        self.encode_ms = BoundedSeries(
            "frame_encode_ms", bucket_width=0.1, bucket_count=8192
        )
        self.payload_bytes = BoundedSeries(
            "frame_payload_bytes", bucket_width=1024.0, bucket_count=8192, digits=0
        )
        self._last_encode_ms = 0.0
        self._frame_id = 0
        self._publish_lock = threading.Lock()

    # ── colour path ─────────────────────────────────────────────────────────

    @staticmethod
    def carla_image_to_bgra(image: Any) -> np.ndarray:
        """Convert a ``carla.Image`` into an HxWx4 BGRA array (no colour change)."""

        raw = np.frombuffer(image.raw_data, dtype=np.uint8)
        return raw.reshape((int(image.height), int(image.width), 4))

    def bgra_to_bgr(self, bgra: np.ndarray) -> np.ndarray:
        """Explicit CARLA BGRA -> BGR conversion before JPEG encoding."""

        return np.ascontiguousarray(self.codec.bgra_to_bgr(bgra))

    # ── publishing ──────────────────────────────────────────────────────────

    def next_frame_id(self) -> int:
        self._frame_id += 1
        return self._frame_id

    def encode(self, bgr: np.ndarray) -> bytes:
        started = time.perf_counter()
        payload = self.codec.encode_bgr(bgr)
        self._last_encode_ms = (time.perf_counter() - started) * 1000.0
        self.encode_ms.observe(self._last_encode_ms)
        return payload

    def publish_bgr(
        self,
        bgr: np.ndarray,
        *,
        frame_id: Optional[int] = None,
        simulation_timestamp_us: int = 0,
        flags: int = 0,
    ) -> PublishResult:
        """Encode and publish one BGR frame, honouring active fault injection."""

        resolved_frame_id = self.next_frame_id() if frame_id is None else int(frame_id)
        if not self.client.connected:
            self.frames_dropped_backpressure += 1
            return PublishResult(False, resolved_frame_id, error="frame client not connected")

        try:
            payload = self.encode(bgr)
        except JpegCodecError as exc:
            self.frames_failed += 1
            return PublishResult(False, resolved_frame_id, error=exc.message, fault="jpeg_encode")

        height, width = int(bgr.shape[0]), int(bgr.shape[1])
        channels = int(bgr.shape[2]) if bgr.ndim == 3 else 1
        return self.publish_encoded(
            payload,
            width=width,
            height=height,
            channels=channels,
            frame_id=resolved_frame_id,
            simulation_timestamp_us=simulation_timestamp_us,
            flags=flags,
            encode_ms=self._last_encode_ms,
        )

    def publish_encoded(
        self,
        payload: bytes,
        *,
        width: int,
        height: int,
        channels: int = 3,
        frame_id: Optional[int] = None,
        simulation_timestamp_us: int = 0,
        flags: int = 0,
        encode_ms: float = 0.0,
    ) -> PublishResult:
        """Publish an already-encoded JPEG payload.

        Phase 13E-R Goal 2 needs a producer whose rate is set by its own clock
        rather than by how fast the PC can JPEG-encode, so the burst republishes
        payloads encoded once up front. Header construction, fault injection and
        the wire format are identical to :meth:`publish_bgr`.
        """

        resolved_frame_id = self.next_frame_id() if frame_id is None else int(frame_id)
        if not self.client.connected:
            self.frames_dropped_backpressure += 1
            return PublishResult(False, resolved_frame_id, error="frame client not connected")
        width = int(width)
        height = int(height)
        channels = int(channels)

        fault = None  # type: Optional[str]
        stale_offset_us = 0
        header_payload_size = len(payload)
        header_crc = crc32_iso_hdlc(payload)
        header_codec = int(FrameCodec.JPEG)
        header_version = 1
        wire_payload = payload
        truncate_to = None  # type: Optional[int]

        if self.faults.corrupt_payload_crc:
            self.faults.corrupt_payload_crc -= 1
            fault = "frame_payload_crc_corruption"
            mutated = bytearray(payload)
            mutated[len(mutated) // 2] ^= 0x01
            wire_payload = bytes(mutated)
        elif self.faults.oversized_payload:
            self.faults.oversized_payload -= 1
            fault = "oversized_frame_payload"
            header_payload_size = self.max_payload_bytes + 1
        elif self.faults.invalid_dimensions:
            self.faults.invalid_dimensions -= 1
            fault = "invalid_frame_dimensions"
            width = 0
        elif self.faults.unsupported_codec:
            self.faults.unsupported_codec -= 1
            fault = "unsupported_frame_codec"
            header_codec = 0x7FFF
        elif self.faults.unsupported_version:
            self.faults.unsupported_version -= 1
            fault = "unsupported_frame_protocol_version"
            header_version = 2
        elif self.faults.zero_payload:
            self.faults.zero_payload -= 1
            fault = "zero_size_frame_payload"
            header_payload_size = 0
            wire_payload = b""
        elif self.faults.partial_payload:
            self.faults.partial_payload -= 1
            fault = "partial_frame_payload"
            truncate_to = max(1, len(payload) // 2)
        elif self.faults.stale_timestamp:
            self.faults.stale_timestamp -= 1
            fault = "stale_frame_timestamp"
            stale_offset_us = self.stale_offset_us

        header = FrameHeader(
            frame_id=resolved_frame_id,
            simulation_timestamp_us=int(simulation_timestamp_us),
            pc_monotonic_us=max(0, monotonic_us() - stale_offset_us),
            width=width,
            height=height,
            payload_size=header_payload_size,
            payload_crc32=header_crc,
            channels=channels,
            codec=header_codec,
            pixel_format=int(PixelFormat.BGR8),
            flags=flags,
            protocol_version=header_version,
        )
        message = encode_frame_header(header) + wire_payload
        if truncate_to is not None:
            message = message[: FRAME_HEADER_SIZE + truncate_to]

        started = time.perf_counter()
        try:
            # One writer at a time: the frame socket is a single TCP stream and
            # an interleaved write would desynchronise its framing.
            with self._publish_lock:
                if fault is None or fault == "stale_frame_timestamp":
                    self.client.send_frame_message(message)
                else:
                    self.client.send_raw(message)
                    self.frames_fault_injected += 1
        except FrameTransportError as exc:
            self.frames_failed += 1
            return PublishResult(
                False, resolved_frame_id, encode_ms=encode_ms, fault=fault, error=exc.message
            )
        send_ms = (time.perf_counter() - started) * 1000.0

        if fault is None or fault == "stale_frame_timestamp":
            self.frames_published += 1
            self.bytes_published += len(message)
            self.payload_bytes.observe(len(payload))
        return PublishResult(
            published=fault is None,
            frame_id=resolved_frame_id,
            payload_bytes=len(payload),
            encode_ms=round(encode_ms, 3),
            send_ms=round(send_ms, 3),
            fault=fault,
        )

    def publish_bgra(
        self,
        bgra: np.ndarray,
        *,
        frame_id: Optional[int] = None,
        simulation_timestamp_us: int = 0,
        flags: int = 0,
    ) -> PublishResult:
        """Publish a CARLA BGRA frame through the mandated colour path."""

        return self.publish_bgr(
            self.bgra_to_bgr(bgra),
            frame_id=frame_id,
            simulation_timestamp_us=simulation_timestamp_us,
            flags=flags,
        )

    def metrics(self) -> Dict[str, Any]:
        encode = self.encode_ms.to_dict()
        payload_bytes = self.payload_bytes.to_dict()
        payload = {
            "frames_published": self.frames_published,
            "frames_dropped_backpressure": self.frames_dropped_backpressure,
            "frames_failed": self.frames_failed,
            "frames_fault_injected": self.frames_fault_injected,
            "frame_bytes_published": self.bytes_published,
            "frame_encode_ms_mean": encode["mean"],
            "frame_encode_ms_max": encode["max"],
            "frame_encode_ms_stats": encode,
            "frame_payload_bytes_mean": payload_bytes["mean"],
            "frame_payload_bytes_max": payload_bytes["max"],
            "frame_publisher_bounded": True,
            "frame_publisher_pending_queue_depth": 0,
            "camera_width": self.width,
            "camera_height": self.height,
        }
        payload.update(self.codec.describe())
        payload.update(self.client.metrics())
        return payload


def synthetic_bgr_frame(
    width: int,
    height: int,
    *,
    frame_index: int = 0,
    seed: int = 13,
) -> np.ndarray:
    """Deterministic synthetic BGR frame for Gate A / Gate B transport tests.

    The gradient keeps per-channel mean and standard deviation inside the Phase
    13B input-only range contract, so a transport-only run does not trip a range
    rejection that has nothing to do with transport.
    """

    rng = np.random.RandomState(seed + frame_index)
    y_axis = np.linspace(40, 210, height, dtype=np.float32).reshape(height, 1)
    x_axis = np.linspace(40, 210, width, dtype=np.float32).reshape(1, width)
    base = (y_axis + x_axis) / 2.0
    frame = np.empty((height, width, 3), dtype=np.uint8)
    frame[:, :, 0] = np.clip(base + 10.0, 0, 255).astype(np.uint8)
    frame[:, :, 1] = np.clip(base, 0, 255).astype(np.uint8)
    frame[:, :, 2] = np.clip(base - 10.0, 0, 255).astype(np.uint8)
    noise = rng.randint(-6, 7, size=(height, width, 3))
    return np.clip(frame.astype(np.int16) + noise, 20, 235).astype(np.uint8)

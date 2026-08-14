"""Phase 13B bounded frame buffering: fixed pool + depth-1 latest-frame mailbox.

Phase 13B forbids unbounded queueing between the TCP frame transport and the
Jetson processing stage. This module provides:

* :class:`FixedBufferPool` — a fixed number of pre-allocated payload buffers
  with deterministic ownership states and deterministic release.
* :class:`LatestFrameMailbox` — a mailbox whose depth is exactly 1; publishing
  a newer frame evicts and releases the older one instead of growing a queue.
* :class:`FrameFlowMetrics` — the Phase 13B required frame-flow counters.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

MAILBOX_DEPTH = 1
DEFAULT_POOL_SIZE = 3


class BufferState(Enum):
    """Deterministic buffer ownership states."""

    FREE = "FREE"
    TRANSPORT_OWNED = "TRANSPORT_OWNED"
    MAILBOX_OWNED = "MAILBOX_OWNED"
    PROCESSING_OWNED = "PROCESSING_OWNED"


class BufferOwnershipError(RuntimeError):
    """Raised on double release, use-after-release, or foreign buffer release."""


class PooledBuffer:
    """A single fixed-capacity payload buffer owned by :class:`FixedBufferPool`."""

    __slots__ = ("index", "capacity", "data", "state", "length", "meta", "generation")

    def __init__(self, index: int, capacity: int) -> None:
        self.index = index
        self.capacity = capacity
        self.data = bytearray(capacity)
        self.state = BufferState.FREE
        self.length = 0
        self.meta = {}  # type: Dict[str, Any]
        self.generation = 0

    def view(self) -> memoryview:
        """Writable view over the whole buffer capacity."""

        return memoryview(self.data)

    def payload(self) -> bytes:
        """Immutable copy of the currently filled region."""

        if self.state is BufferState.FREE:
            raise BufferOwnershipError("payload() on a released buffer (index=%d)" % self.index)
        return bytes(self.data[: self.length])

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return "PooledBuffer(index=%d, state=%s, length=%d)" % (
            self.index,
            self.state.value,
            self.length,
        )


class FixedBufferPool:
    """Fixed-size pool of payload buffers with deterministic ownership."""

    def __init__(self, *, size: int = DEFAULT_POOL_SIZE, capacity_bytes: int) -> None:
        if size <= 0:
            raise ValueError("buffer pool size must be positive")
        if capacity_bytes <= 0:
            raise ValueError("buffer capacity must be positive")
        self._lock = threading.Lock()
        self._buffers = [PooledBuffer(index, capacity_bytes) for index in range(size)]
        self._free = list(self._buffers)  # type: List[PooledBuffer]
        self.size = size
        self.capacity_bytes = capacity_bytes
        self.acquire_failure_count = 0
        self.high_watermark = 0

    @property
    def in_use(self) -> int:
        with self._lock:
            return self.size - len(self._free)

    def acquire(self, owner: BufferState = BufferState.TRANSPORT_OWNED) -> Optional[PooledBuffer]:
        """Acquire a free buffer, or ``None`` when the bounded pool is exhausted."""

        if owner is BufferState.FREE:
            raise ValueError("acquire owner must not be FREE")
        with self._lock:
            if not self._free:
                self.acquire_failure_count += 1
                return None
            buffer = self._free.pop()
            buffer.state = owner
            buffer.length = 0
            buffer.meta = {}
            in_use = self.size - len(self._free)
            if in_use > self.high_watermark:
                self.high_watermark = in_use
            return buffer

    def transfer(self, buffer: PooledBuffer, owner: BufferState) -> None:
        """Move an in-use buffer between non-free ownership states."""

        if owner is BufferState.FREE:
            raise ValueError("use release() to return a buffer to the pool")
        with self._lock:
            self._assert_owned(buffer)
            buffer.state = owner

    def release(self, buffer: Optional[PooledBuffer]) -> None:
        """Return a buffer to the pool; double release is an explicit error."""

        if buffer is None:
            return
        with self._lock:
            if buffer.index >= self.size or self._buffers[buffer.index] is not buffer:
                raise BufferOwnershipError("release of a buffer that is not pool-owned")
            if buffer.state is BufferState.FREE:
                raise BufferOwnershipError("double release of buffer index=%d" % buffer.index)
            buffer.state = BufferState.FREE
            buffer.length = 0
            buffer.meta = {}
            buffer.generation += 1
            self._free.append(buffer)

    def _assert_owned(self, buffer: PooledBuffer) -> None:
        if buffer.index >= self.size or self._buffers[buffer.index] is not buffer:
            raise BufferOwnershipError("buffer is not pool-owned")
        if buffer.state is BufferState.FREE:
            raise BufferOwnershipError("use-after-release on buffer index=%d" % buffer.index)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "buffer_pool_size": self.size,
                "buffer_pool_capacity_bytes": self.capacity_bytes,
                "buffer_pool_in_use": self.size - len(self._free),
                "buffer_pool_high_watermark": self.high_watermark,
                "buffer_acquire_failures": self.acquire_failure_count,
                "buffer_states": [item.state.value for item in self._buffers],
            }

    def leak_check(self, *, max_in_flight: int = 0) -> Dict[str, Any]:
        """Report buffers still owned outside the pool.

        ``max_in_flight`` is how many buffers the pipeline may legitimately hold
        at this instant: one being received, one waiting in the depth-1 mailbox,
        one being processed. At shutdown that allowance is zero and any held
        buffer is a leak. Called mid-run with an allowance of zero, a perfectly
        healthy in-flight frame reads as a leak — which is what happened the
        first time the pipeline was actually driven into overload.
        """

        with self._lock:
            held = [item.index for item in self._buffers if item.state is not BufferState.FREE]
            return {
                "leaked_buffer_indices": held,
                "buffer_in_flight_count": len(held),
                "buffer_max_in_flight_allowance": int(max_in_flight),
                "buffer_leak_detected": len(held) > int(max_in_flight),
            }


class LatestFrameMailbox:
    """Depth-1 mailbox: the newest frame always wins, the older one is released."""

    def __init__(self, pool: FixedBufferPool) -> None:
        self._pool = pool
        self._lock = threading.Lock()
        self._slot = None  # type: Optional[PooledBuffer]
        self.depth = 0
        self.max_depth_observed = 0
        self.overwrite_count = 0

    def publish(self, buffer: PooledBuffer) -> bool:
        """Publish the newest frame. Returns ``True`` if an older frame was dropped."""

        dropped = None  # type: Optional[PooledBuffer]
        with self._lock:
            if self._slot is not None:
                dropped = self._slot
                self._slot = None
                self.depth = 0
                self.overwrite_count += 1
            self._pool.transfer(buffer, BufferState.MAILBOX_OWNED)
            self._slot = buffer
            self.depth = 1
            if self.depth > self.max_depth_observed:
                self.max_depth_observed = self.depth
        if dropped is not None:
            self._pool.release(dropped)
            return True
        return False

    def take(self) -> Optional[PooledBuffer]:
        """Take the latest frame for processing, or ``None`` when empty."""

        with self._lock:
            buffer = self._slot
            self._slot = None
            self.depth = 0
        if buffer is not None:
            self._pool.transfer(buffer, BufferState.PROCESSING_OWNED)
        return buffer

    def drain(self) -> None:
        """Release any frame still held at shutdown."""

        with self._lock:
            buffer = self._slot
            self._slot = None
            self.depth = 0
        if buffer is not None:
            self._pool.release(buffer)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "mailbox_configured_depth": MAILBOX_DEPTH,
                "mailbox_depth": self.depth,
                "max_mailbox_depth": self.max_depth_observed,
                "latest_frame_overwrite_count": self.overwrite_count,
            }


def _percentile(values: List[float], percentile: float) -> Optional[float]:
    """Nearest-rank percentile so results stay deterministic without numpy."""

    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    rank = int(round((percentile / 100.0) * (len(ordered) - 1)))
    rank = max(0, min(len(ordered) - 1, rank))
    return round(ordered[rank], 3)


@dataclass
class FrameFlowMetrics:
    """Phase 13B required frame-flow counters and frame-age distribution."""

    frames_received: int = 0
    frames_decoded: int = 0
    frames_processed: int = 0
    frames_dropped_transport: int = 0
    frames_dropped_mailbox: int = 0
    stale_frame_reject_count: int = 0
    frame_decode_failure_count: int = 0
    frame_age_samples_ms: List[float] = field(default_factory=list)
    reject_counts: Dict[str, int] = field(default_factory=dict)

    def record_reject(self, classification: str) -> None:
        self.reject_counts[classification] = self.reject_counts.get(classification, 0) + 1

    def record_frame_age(self, age_ms: Optional[float]) -> None:
        if age_ms is None:
            return
        self.frame_age_samples_ms.append(float(age_ms))

    def to_dict(
        self,
        pool: FixedBufferPool,
        mailbox: LatestFrameMailbox,
        *,
        max_in_flight: int = 0,
    ) -> Dict[str, Any]:
        pool_snapshot = pool.snapshot()
        mailbox_snapshot = mailbox.snapshot()
        leak = pool.leak_check(max_in_flight=max_in_flight)
        return {
            "frames_received": self.frames_received,
            "frames_decoded": self.frames_decoded,
            "frames_processed": self.frames_processed,
            "frames_dropped_transport": self.frames_dropped_transport,
            "frames_dropped_mailbox": self.frames_dropped_mailbox,
            "buffer_acquire_failures": pool_snapshot["buffer_acquire_failures"],
            "max_mailbox_depth": mailbox_snapshot["max_mailbox_depth"],
            "latest_frame_overwrite_count": mailbox_snapshot["latest_frame_overwrite_count"],
            "buffer_pool_size": pool_snapshot["buffer_pool_size"],
            "buffer_pool_high_watermark": pool_snapshot["buffer_pool_high_watermark"],
            "stale_frame_reject_count": self.stale_frame_reject_count,
            "frame_decode_failure_count": self.frame_decode_failure_count,
            "frame_age_ms_p50": _percentile(self.frame_age_samples_ms, 50.0),
            "frame_age_ms_p95": _percentile(self.frame_age_samples_ms, 95.0),
            "frame_age_ms_p99": _percentile(self.frame_age_samples_ms, 99.0),
            "frame_age_sample_count": len(self.frame_age_samples_ms),
            "frame_reject_counts": dict(self.reject_counts),
            "buffer_pool_in_use": pool_snapshot["buffer_pool_in_use"],
            "buffer_pool_high_watermark": pool_snapshot["buffer_pool_high_watermark"],
            "buffer_in_flight_count": leak["buffer_in_flight_count"],
            "buffer_max_in_flight_allowance": leak["buffer_max_in_flight_allowance"],
            "buffer_leak_detected": leak["buffer_leak_detected"],
        }

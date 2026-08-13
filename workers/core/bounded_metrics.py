"""Phase 13E-R bounded metric containers for long-duration runs.

Phase 13E kept every per-frame sample in a Python list. Over a two-hour soak at
6 FPS that is tens of thousands of dicts whose only purpose is to be summarised
at the end, and the growth is unbounded in the run duration — the one thing a
soak is supposed to prove does not happen.

This module provides the three shapes that replace those lists:

``OnlineStat``
    Exact count/min/max/mean/variance in constant memory (Welford).

``BoundedSeries``
    ``OnlineStat`` plus a fixed-bucket histogram for percentiles and a bounded
    ring of the most recent samples. Memory is fixed at construction.

``JsonlSink``
    Streams per-frame records to disk instead of accumulating them in RAM.

The histogram makes percentiles *estimates*, and the estimate is reported with
the bucket width that produced it so a reader can see its resolution rather
than having to trust it. Minimum and maximum stay exact.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import json
import math
import os
import threading
from collections import deque
from typing import Any, Deque, Dict, Iterable, List, Optional

DEFAULT_RING_CAPACITY = 512
DEFAULT_BUCKET_COUNT = 4096


class OnlineStat:
    """Exact summary statistics in constant memory."""

    __slots__ = ("count", "minimum", "maximum", "_mean", "_m2")

    def __init__(self) -> None:
        self.count = 0
        self.minimum = None  # type: Optional[float]
        self.maximum = None  # type: Optional[float]
        self._mean = 0.0
        self._m2 = 0.0

    def observe(self, value: float) -> None:
        value = float(value)
        if not math.isfinite(value):
            return
        self.count += 1
        if self.minimum is None or value < self.minimum:
            self.minimum = value
        if self.maximum is None or value > self.maximum:
            self.maximum = value
        delta = value - self._mean
        self._mean += delta / self.count
        self._m2 += delta * (value - self._mean)

    @property
    def mean(self) -> Optional[float]:
        return self._mean if self.count else None

    @property
    def variance(self) -> Optional[float]:
        if self.count < 2:
            return None
        return self._m2 / (self.count - 1)

    @property
    def stdev(self) -> Optional[float]:
        variance = self.variance
        return math.sqrt(variance) if variance is not None else None

    def to_dict(self, *, digits: int = 3) -> Dict[str, Any]:
        return {
            "count": self.count,
            "min": None if self.minimum is None else round(self.minimum, digits),
            "max": None if self.maximum is None else round(self.maximum, digits),
            "mean": None if self.mean is None else round(self.mean, digits),
            "stdev": None if self.stdev is None else round(self.stdev, digits),
        }


class BoundedSeries:
    """Fixed-memory sample series with histogram percentiles and a recent ring."""

    def __init__(
        self,
        name: str,
        *,
        lower_bound: float = 0.0,
        bucket_width: float = 1.0,
        bucket_count: int = DEFAULT_BUCKET_COUNT,
        ring_capacity: int = DEFAULT_RING_CAPACITY,
        digits: int = 3,
    ) -> None:
        if bucket_width <= 0:
            raise ValueError("bucket_width must be positive")
        self.name = str(name)
        self.lower_bound = float(lower_bound)
        self.bucket_width = float(bucket_width)
        self.bucket_count = max(1, int(bucket_count))
        self.digits = int(digits)
        self.stat = OnlineStat()
        self._buckets = [0] * self.bucket_count
        self.underflow_count = 0
        self.overflow_count = 0
        self.nonfinite_count = 0
        self._ring = deque(maxlen=max(1, int(ring_capacity)))  # type: Deque[float]
        self.ring_high_watermark = 0

    # ── ingest ──────────────────────────────────────────────────────────────

    def observe(self, value: float) -> None:
        numeric = float(value)
        if not math.isfinite(numeric):
            self.nonfinite_count += 1
            return
        self.stat.observe(numeric)
        self._ring.append(numeric)
        self.ring_high_watermark = max(self.ring_high_watermark, len(self._ring))
        index = int(math.floor((numeric - self.lower_bound) / self.bucket_width))
        if index < 0:
            self.underflow_count += 1
        elif index >= self.bucket_count:
            self.overflow_count += 1
        else:
            self._buckets[index] += 1

    def extend(self, values: Iterable[float]) -> None:
        for value in values:
            self.observe(value)

    # ── read ────────────────────────────────────────────────────────────────

    @property
    def count(self) -> int:
        return self.stat.count

    @property
    def ring_capacity(self) -> int:
        return int(self._ring.maxlen or 0)

    def recent(self) -> List[float]:
        return list(self._ring)

    def percentile(self, quantile: float) -> Optional[float]:
        """Histogram-estimated percentile, reported at the bucket upper edge.

        Samples outside the histogram range fall back to the exact minimum or
        maximum, so the estimate is never fabricated from an empty region.
        """

        total = self.stat.count
        if total <= 0:
            return None
        quantile = min(max(float(quantile), 0.0), 1.0)
        # Nearest-rank: the smallest value at or above which `quantile` of the
        # population lies, matching the convention used elsewhere in the phase.
        target = max(1, int(math.ceil(quantile * total)))
        if target <= self.underflow_count:
            return self.stat.minimum
        cumulative = self.underflow_count
        for index, bucket in enumerate(self._buckets):
            if bucket == 0:
                continue
            cumulative += bucket
            if cumulative >= target:
                edge = self.lower_bound + (index + 1) * self.bucket_width
                maximum = self.stat.maximum
                if maximum is not None and edge > maximum:
                    return maximum
                return edge
        return self.stat.maximum

    def to_dict(self) -> Dict[str, Any]:
        payload = self.stat.to_dict(digits=self.digits)
        payload.update(
            {
                # Same key the Phase 13C `latency_stats` shape uses, so existing
                # readers of these blocks keep working.
                "sample_count": self.stat.count,
                "p50": self._round(self.percentile(0.50)),
                "p95": self._round(self.percentile(0.95)),
                "p99": self._round(self.percentile(0.99)),
                "percentile_method": "fixed_bucket_histogram",
                "histogram_bucket_width": self.bucket_width,
                "histogram_bucket_count": self.bucket_count,
                "histogram_lower_bound": self.lower_bound,
                "histogram_underflow_count": self.underflow_count,
                "histogram_overflow_count": self.overflow_count,
                "nonfinite_count": self.nonfinite_count,
                "ring_capacity": self._ring.maxlen,
                "ring_high_watermark": self.ring_high_watermark,
            }
        )
        return payload

    def _round(self, value: Optional[float]) -> Optional[float]:
        return None if value is None else round(value, self.digits)


class BoundedCounter:
    """Fixed-key tally that never grows past a cap of distinct keys."""

    def __init__(self, *, max_keys: int = 64) -> None:
        self.max_keys = max(1, int(max_keys))
        self.counts = {}  # type: Dict[str, int]
        self.dropped_key_count = 0

    def bump(self, key: str, amount: int = 1) -> None:
        name = str(key)
        if name in self.counts:
            self.counts[name] += int(amount)
        elif len(self.counts) < self.max_keys:
            self.counts[name] = int(amount)
        else:
            self.dropped_key_count += int(amount)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.counts)


class JsonlSink:
    """Append-only JSONL writer with a bounded in-memory tail.

    Per-frame records are evidence, so they are streamed to disk rather than
    dropped; only the tail is kept in memory for the end-of-run summary.
    """

    def __init__(
        self,
        path: Optional[str],
        *,
        tail_capacity: int = DEFAULT_RING_CAPACITY,
        flush_every: int = 64,
    ) -> None:
        self.path = path
        self.flush_every = max(1, int(flush_every))
        self.written_count = 0
        self.write_failure_count = 0
        self.last_error = ""
        self._tail = deque(maxlen=max(1, int(tail_capacity)))  # type: Deque[Dict[str, Any]]
        self._lock = threading.Lock()
        self._handle = None  # type: Optional[Any]
        self._since_flush = 0
        if path:
            directory = os.path.dirname(os.path.abspath(path))
            if directory:
                os.makedirs(directory, exist_ok=True)
            self._handle = open(path, "a", encoding="utf-8")

    def write(self, record: Dict[str, Any]) -> None:
        with self._lock:
            self._tail.append(record)
            if self._handle is None:
                self.written_count += 1
                return
            try:
                self._handle.write(json.dumps(record, sort_keys=True) + "\n")
                self.written_count += 1
                self._since_flush += 1
                if self._since_flush >= self.flush_every:
                    self._handle.flush()
                    self._since_flush = 0
            except (OSError, TypeError, ValueError) as exc:
                self.write_failure_count += 1
                self.last_error = "%s: %s" % (type(exc).__name__, exc)

    def tail(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._tail)

    def flush(self) -> None:
        with self._lock:
            if self._handle is not None:
                self._handle.flush()
                self._since_flush = 0

    def close(self) -> None:
        with self._lock:
            if self._handle is not None:
                self._handle.flush()
                self._handle.close()
                self._handle = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "written_count": self.written_count,
            "write_failure_count": self.write_failure_count,
            "last_error": self.last_error,
            "tail_capacity": self._tail.maxlen,
            "tail_size": len(self._tail),
            "streamed": self._handle is not None or bool(self.path),
        }

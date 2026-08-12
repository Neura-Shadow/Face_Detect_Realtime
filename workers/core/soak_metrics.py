"""Phase 13E soak time-series, windowed drift detection and classification.

A soak either holds a steady state for hours or it does not, and the difference
is only visible by comparing the beginning of the run with the end of it. This
module owns that comparison:

* ``SoakSeries`` accumulates a named time series and reports the distribution;
* ``window_stats`` summarises a start / rolling / end window of one series;
* ``evaluate_drift`` compares those windows against declared limits and returns
  a verdict per series;
* ``classify_soak`` turns the verdicts into the honest labels this phase is
  required to use — ``thermal_drift``, ``memory_drift``, ``latency_drift`` and
  ``backpressure_recovery_failed`` — rather than a bare pass/fail.

Nothing here talks to a Jetson, a GPU or CARLA, so the drift rules can be
tested exhaustively on the simulation PC.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: A resource series that only ever grows is a leak; these are checked for it.
MONOTONE_RESOURCE_SERIES = (
    "process_rss_bytes",
    "open_fd_count",
    "thread_count",
    "swap_used_bytes",
)


def percentile(ordered: Sequence[float], value: float) -> Optional[float]:
    """Nearest-rank percentile; deterministic and numpy-free."""

    if not ordered:
        return None
    rank = int(round((float(value) / 100.0) * (len(ordered) - 1)))
    return float(ordered[max(0, min(len(ordered) - 1, rank))])


def distribution(samples: Sequence[float]) -> Dict[str, Any]:
    values = [float(item) for item in samples if item is not None and math.isfinite(float(item))]
    if not values:
        return {"count": 0, "min": None, "p50": None, "p95": None, "p99": None,
                "max": None, "mean": None}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": round(ordered[0], 4),
        "p50": round(percentile(ordered, 50.0), 4),
        "p95": round(percentile(ordered, 95.0), 4),
        "p99": round(percentile(ordered, 99.0), 4),
        "max": round(ordered[-1], 4),
        "mean": round(sum(ordered) / len(ordered), 4),
    }


class SoakSeries:
    """One named ``(elapsed_seconds, value)`` series."""

    def __init__(self, name: str) -> None:
        self.name = str(name)
        self.times = []  # type: List[float]
        self.values = []  # type: List[float]

    def add(self, elapsed_sec: float, value: Any) -> None:
        if value is None:
            return
        try:
            number = float(value)
        except (TypeError, ValueError):
            return
        if not math.isfinite(number):
            return
        self.times.append(float(elapsed_sec))
        self.values.append(number)

    def __len__(self) -> int:
        return len(self.values)

    def slice_window(self, start_sec: float, end_sec: float) -> List[float]:
        return [
            value
            for time_s, value in zip(self.times, self.values)
            if start_sec <= time_s < end_sec or (end_sec == float("inf") and time_s >= start_sec)
        ]

    def to_dict(self, *, max_points: int = 0) -> Dict[str, Any]:
        payload = {
            "name": self.name,
            "sample_count": len(self.values),
            "distribution": distribution(self.values),
        }  # type: Dict[str, Any]
        if max_points and len(self.values) > max_points:
            stride = len(self.values) / float(max_points)
            indices = sorted({int(index * stride) for index in range(max_points)})
            payload["series"] = [
                [round(self.times[i], 3), round(self.values[i], 6)]
                for i in indices
                if i < len(self.values)
            ]
            payload["series_downsampled"] = True
        else:
            payload["series"] = [
                [round(t, 3), round(v, 6)] for t, v in zip(self.times, self.values)
            ]
            payload["series_downsampled"] = False
        return payload


def window_stats(
    series: SoakSeries, *, window_sec: float, total_sec: Optional[float] = None
) -> Dict[str, Any]:
    """Start window, end window and the rolling windows in between."""

    if not len(series):
        return {"available": False, "reason": "no samples"}
    duration = float(total_sec if total_sec is not None else series.times[-1])
    window = max(1.0, float(window_sec))
    start_values = series.slice_window(series.times[0], series.times[0] + window)
    end_values = [value for t, value in zip(series.times, series.values) if t >= duration - window]
    rolling = []  # type: List[Dict[str, Any]]
    edge = series.times[0]
    while edge < duration:
        chunk = series.slice_window(edge, edge + window)
        if chunk:
            rolling.append(
                {
                    "start_sec": round(edge, 3),
                    "mean": round(sum(chunk) / len(chunk), 6),
                    "max": round(max(chunk), 6),
                    "count": len(chunk),
                }
            )
        edge += window
    return {
        "available": bool(start_values and end_values),
        "window_sec": window,
        "start_window": distribution(start_values),
        "end_window": distribution(end_values),
        "rolling_windows": rolling,
        "rolling_window_count": len(rolling),
    }


@dataclass
class DriftLimits:
    """Declared soak limits. Recorded verbatim in the evidence."""

    #: Relative growth of a monotone resource between start and end windows.
    resource_growth_ratio_max: float = 1.15
    #: Absolute RSS growth allowance, so a small process is not judged by ratio alone.
    rss_growth_bytes_max: int = 256 * 1024 * 1024
    #: File descriptors and threads must be flat, not merely bounded.
    fd_growth_max: int = 8
    thread_growth_max: int = 4
    #: Latency is allowed to move, but not to trend upward across the run.
    latency_p99_growth_ratio_max: float = 1.25
    #: Temperature rise between start and end windows.
    temperature_rise_c_max: float = 12.0
    #: A rolling window sequence that only ever rises is progressive growth.
    progressive_growth_min_windows: int = 4

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def is_progressive(rolling: Sequence[Dict[str, Any]], *, min_windows: int = 4) -> bool:
    """True when every rolling window is above the one before it.

    A resource that rises and falls is a working set. A resource that rises in
    every window without exception is the shape of a leak, which is the
    distinction this phase is required to make about swap in particular.
    """

    means = [float(item["mean"]) for item in rolling]
    if len(means) < int(min_windows):
        return False
    return all(later > earlier for earlier, later in zip(means, means[1:]))


def evaluate_drift(
    series: SoakSeries,
    stats: Dict[str, Any],
    *,
    limits: DriftLimits,
    kind: str,
) -> Dict[str, Any]:
    """Compare one series' start and end windows against the declared limits.

    ``kind`` is ``resource``, ``latency`` or ``temperature``.
    """

    verdict = {
        "name": series.name,
        "kind": kind,
        "available": bool(stats.get("available")),
        "drift_detected": False,
        "reasons": [],
    }  # type: Dict[str, Any]
    if not stats.get("available"):
        verdict["reasons"].append("insufficient_samples")
        return verdict

    start = stats["start_window"]
    end = stats["end_window"]
    start_mean = start.get("mean")
    end_mean = end.get("mean")
    verdict["start_mean"] = start_mean
    verdict["end_mean"] = end_mean
    verdict["absolute_growth"] = (
        round(float(end_mean) - float(start_mean), 6)
        if start_mean is not None and end_mean is not None
        else None
    )
    verdict["growth_ratio"] = (
        round(float(end_mean) / float(start_mean), 6)
        if start_mean not in (None, 0) and end_mean is not None
        else None
    )
    verdict["progressive"] = is_progressive(
        stats.get("rolling_windows", []), min_windows=limits.progressive_growth_min_windows
    )

    if kind == "resource":
        growth = verdict["absolute_growth"] or 0.0
        ratio = verdict["growth_ratio"]
        if series.name == "process_rss_bytes":
            if growth > limits.rss_growth_bytes_max:
                verdict["reasons"].append("rss_growth_bytes_exceeded")
            if ratio is not None and ratio > limits.resource_growth_ratio_max:
                verdict["reasons"].append("rss_growth_ratio_exceeded")
        elif series.name == "open_fd_count":
            if growth > limits.fd_growth_max:
                verdict["reasons"].append("fd_growth_exceeded")
        elif series.name == "thread_count":
            if growth > limits.thread_growth_max:
                verdict["reasons"].append("thread_growth_exceeded")
        elif series.name == "swap_used_bytes":
            # Swap is allowed to be non-zero; it is not allowed to only ever rise.
            if verdict["progressive"] and growth > 0:
                verdict["reasons"].append("swap_growth_progressive")
        elif ratio is not None and ratio > limits.resource_growth_ratio_max:
            verdict["reasons"].append("resource_growth_ratio_exceeded")
    elif kind == "latency":
        start_p99 = start.get("p99")
        end_p99 = end.get("p99")
        verdict["start_p99"] = start_p99
        verdict["end_p99"] = end_p99
        if start_p99 not in (None, 0) and end_p99 is not None:
            ratio = round(float(end_p99) / float(start_p99), 6)
            verdict["p99_growth_ratio"] = ratio
            if ratio > limits.latency_p99_growth_ratio_max:
                verdict["reasons"].append("latency_p99_growth_exceeded")
    elif kind == "temperature":
        start_max = start.get("max")
        end_max = end.get("max")
        rise = (
            round(float(end_max) - float(start_max), 4)
            if start_max is not None and end_max is not None
            else None
        )
        verdict["temperature_rise_c"] = rise
        if rise is not None and rise > limits.temperature_rise_c_max:
            verdict["reasons"].append("temperature_rise_exceeded")

    verdict["drift_detected"] = bool(verdict["reasons"])
    return verdict


def evaluate_backpressure_recovery(
    *,
    pre_burst_p99_ms: Optional[float],
    burst_p99_ms: Optional[float],
    post_burst_p99_ms: Optional[float],
    recovery_ratio_max: float = 1.25,
) -> Dict[str, Any]:
    """Latency must return to its pre-burst level once the burst ends."""

    payload = {
        "pre_burst_p99_ms": pre_burst_p99_ms,
        "burst_p99_ms": burst_p99_ms,
        "post_burst_p99_ms": post_burst_p99_ms,
        "recovery_ratio_max": float(recovery_ratio_max),
        "recovered": False,
        "reasons": [],
    }  # type: Dict[str, Any]
    if pre_burst_p99_ms in (None, 0) or post_burst_p99_ms is None:
        payload["reasons"].append("insufficient_samples")
        return payload
    ratio = round(float(post_burst_p99_ms) / float(pre_burst_p99_ms), 6)
    payload["recovery_ratio"] = ratio
    if ratio > float(recovery_ratio_max):
        payload["reasons"].append("latency_did_not_recover")
    payload["recovered"] = not payload["reasons"]
    return payload


def classify_soak(
    drift_verdicts: Sequence[Dict[str, Any]],
    *,
    backpressure: Optional[Dict[str, Any]] = None,
    thermal_throttling_observed: bool = False,
) -> Dict[str, Any]:
    """Turn the per-series verdicts into the phase's honest drift labels."""

    labels = []  # type: List[str]
    detail = {}  # type: Dict[str, List[str]]
    for verdict in drift_verdicts:
        if not verdict.get("drift_detected"):
            continue
        kind = verdict.get("kind")
        if kind == "temperature":
            label = "thermal_drift"
        elif kind == "latency":
            label = "latency_drift"
        else:
            label = "memory_drift"
        if label not in labels:
            labels.append(label)
        detail.setdefault(label, []).append(
            "%s:%s" % (verdict.get("name"), ",".join(verdict.get("reasons", [])))
        )
    if thermal_throttling_observed and "thermal_drift" not in labels:
        labels.append("thermal_drift")
        detail.setdefault("thermal_drift", []).append("thermal_throttling_observed")
    if backpressure is not None and not backpressure.get("recovered", True):
        labels.append("backpressure_recovery_failed")
        detail.setdefault("backpressure_recovery_failed", []).extend(
            backpressure.get("reasons", [])
        )
    return {
        "drift_labels": labels,
        "drift_detail": detail,
        "steady_state_held": not labels,
    }

"""Phase 13E-R disciplined clock model with bounded periodic resync.

Phase 13E measured the failure this module exists to fix. The PC↔Jetson offset
was estimated once at session start and never refreshed. The two machines run
independent monotonic oscillators, so their relative rate differs by a few parts
per million. The mapped Jetson timestamp started marginally *behind* the PC
clock, drifted, crossed zero after roughly 140 seconds, and from then on every
command carried an ``issued_timestamp_us`` in the receiver's future — which the
frozen Phase 13A rule rejects with zero tolerance. 55,804 of 56,671 commands
were refused as stale.

The C validity rule is correct and is **not** changed here. What changes is the
sender: it now keeps a live model of the offset *and its rate of change*, and
biases every issue timestamp backwards by a guard band big enough to cover what
it does not know.

    guard_us = clock_uncertainty_us + estimated_drift_error_us + safety_margin_us
    issued_timestamp_us = estimated_pc_now_us - guard_us

The guard can only ever make a command look **older**, never fresher, so it
cannot mask a genuinely stale command — it only prevents a fresh one from being
pushed past the receiver's clock by estimation error.

Sign convention is unchanged from Phase 13B::

    jetson_minus_pc_offset_us = ((t2 - t1) + (t3 - t4)) / 2
    pc_time_us = jetson_time_us - jetson_minus_pc_offset_us

History is bounded: the model keeps a fixed-capacity window of recent syncs and
never accumulates an unbounded record.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional, Tuple

DEFAULT_RESYNC_INTERVAL_SEC = 15.0
DEFAULT_WINDOW_CAPACITY = 32
DEFAULT_SAFETY_MARGIN_US = 1000
DEFAULT_MAX_UNCERTAINTY_US = 5000
DEFAULT_MAX_DRIFT_PPM = 100.0
DEFAULT_MAX_OFFSET_JUMP_US = 50_000
#: A model older than this many resync intervals is not trusted.
DEFAULT_MAX_AGE_INTERVALS = 3.0


@dataclass(frozen=True)
class ClockObservation:
    """One accepted periodic sync result, in the PC time domain."""

    observed_at_pc_us: int
    jetson_minus_pc_offset_us: int
    clock_uncertainty_us: int
    round_trip_us: int
    generation: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "observed_at_pc_us": self.observed_at_pc_us,
            "jetson_minus_pc_offset_us": self.jetson_minus_pc_offset_us,
            "clock_uncertainty_us": self.clock_uncertainty_us,
            "round_trip_us": self.round_trip_us,
            "generation": self.generation,
        }


def estimate_drift_ppm(observations: List[ClockObservation]) -> Tuple[float, float]:
    """Least-squares rate of change of the offset, in ppm, plus residual error.

    The offset is expressed in microseconds and time in microseconds, so the
    slope is already microseconds per microsecond — parts per million is the
    same number scaled by 1e6.
    """

    if len(observations) < 2:
        return 0.0, 0.0
    times = [float(item.observed_at_pc_us) for item in observations]
    offsets = [float(item.jetson_minus_pc_offset_us) for item in observations]
    mean_t = sum(times) / len(times)
    mean_o = sum(offsets) / len(offsets)
    denominator = sum((t - mean_t) ** 2 for t in times)
    if denominator <= 0.0:
        return 0.0, 0.0
    slope = sum((t - mean_t) * (o - mean_o) for t, o in zip(times, offsets)) / denominator
    intercept = mean_o - slope * mean_t
    residuals = [abs(o - (slope * t + intercept)) for t, o in zip(times, offsets)]
    return slope * 1e6, (max(residuals) if residuals else 0.0)


class DisciplinedClock:
    """Bounded periodic clock discipline with a conservative sender guard.

    Drop-in superset of the Phase 13B ``JetsonClockDomain``: it keeps the same
    method names and sign convention so the node can use it wherever it used
    the one-shot domain.
    """

    def __init__(
        self,
        *,
        jetson_minus_pc_offset_us: int = 0,
        clock_uncertainty_us: int = DEFAULT_MAX_UNCERTAINTY_US + 1,
        clock_sync_valid: bool = False,
        max_uncertainty_us: int = DEFAULT_MAX_UNCERTAINTY_US,
        resync_interval_sec: float = DEFAULT_RESYNC_INTERVAL_SEC,
        window_capacity: int = DEFAULT_WINDOW_CAPACITY,
        safety_margin_us: int = DEFAULT_SAFETY_MARGIN_US,
        max_drift_ppm: float = DEFAULT_MAX_DRIFT_PPM,
        max_offset_jump_us: int = DEFAULT_MAX_OFFSET_JUMP_US,
        max_age_intervals: float = DEFAULT_MAX_AGE_INTERVALS,
    ) -> None:
        self.max_uncertainty_us = int(max_uncertainty_us)
        self.resync_interval_sec = float(resync_interval_sec)
        self.safety_margin_us = int(safety_margin_us)
        self.max_drift_ppm = float(max_drift_ppm)
        self.max_offset_jump_us = int(max_offset_jump_us)
        self.max_age_intervals = float(max_age_intervals)
        self._window = deque(maxlen=max(2, int(window_capacity)))  # type: Deque[ClockObservation]

        self.generation = 0
        self.resync_count = 0
        self.resync_failure_count = 0
        self.offset_jump_count = 0
        self.window_high_watermark = 0
        self.last_reject_reason = ""

        self.jetson_minus_pc_offset_us = int(jetson_minus_pc_offset_us)
        self.clock_uncertainty_us = int(clock_uncertainty_us)
        self.clock_sync_valid = bool(clock_sync_valid)
        self._last_update_pc_us = None  # type: Optional[int]
        if clock_sync_valid:
            self.update(
                jetson_minus_pc_offset_us=jetson_minus_pc_offset_us,
                clock_uncertainty_us=clock_uncertainty_us,
                round_trip_us=0,
                observed_at_pc_us=0,
                valid=True,
            )

    # ── model updates ───────────────────────────────────────────────────────

    def update(
        self,
        *,
        jetson_minus_pc_offset_us: int,
        clock_uncertainty_us: int,
        round_trip_us: int,
        observed_at_pc_us: int,
        valid: bool = True,
    ) -> bool:
        """Fold one periodic sync into the model. Returns whether it was kept."""

        offset = float(jetson_minus_pc_offset_us)
        uncertainty = float(clock_uncertainty_us)
        if not valid:
            self.resync_failure_count += 1
            self.last_reject_reason = "sync_reported_invalid"
            return False
        if not math.isfinite(offset) or not math.isfinite(uncertainty):
            self.resync_failure_count += 1
            self.last_reject_reason = "nonfinite_estimate"
            return False
        if uncertainty > self.max_uncertainty_us:
            self.resync_failure_count += 1
            self.last_reject_reason = "uncertainty_above_budget"
            return False
        if self._window:
            jump = abs(int(jetson_minus_pc_offset_us) - self._window[-1].jetson_minus_pc_offset_us)
            if jump > self.max_offset_jump_us:
                self.resync_failure_count += 1
                self.offset_jump_count += 1
                self.last_reject_reason = "offset_discontinuity"
                return False

        self.generation += 1
        self.resync_count += 1
        self._window.append(
            ClockObservation(
                observed_at_pc_us=int(observed_at_pc_us),
                jetson_minus_pc_offset_us=int(jetson_minus_pc_offset_us),
                clock_uncertainty_us=int(clock_uncertainty_us),
                round_trip_us=int(round_trip_us),
                generation=self.generation,
            )
        )
        self.window_high_watermark = max(self.window_high_watermark, len(self._window))
        self.jetson_minus_pc_offset_us = int(jetson_minus_pc_offset_us)
        self.clock_uncertainty_us = int(clock_uncertainty_us)
        self.clock_sync_valid = True
        self._last_update_pc_us = int(observed_at_pc_us)
        self.last_reject_reason = ""
        return True

    # ── estimates ───────────────────────────────────────────────────────────

    @property
    def drift_ppm(self) -> float:
        return round(estimate_drift_ppm(list(self._window))[0], 6)

    @property
    def drift_residual_us(self) -> float:
        return round(estimate_drift_ppm(list(self._window))[1], 3)

    def model_age_us(self, now_pc_us: int) -> int:
        if self._last_update_pc_us is None:
            return 0
        return max(0, int(now_pc_us) - int(self._last_update_pc_us))

    def estimated_offset_us(self, now_pc_us: int) -> float:
        """Offset projected forward to ``now`` using the measured drift."""

        if not self._window:
            return float(self.jetson_minus_pc_offset_us)
        age_us = self.model_age_us(now_pc_us)
        return float(self.jetson_minus_pc_offset_us) + (self.drift_ppm / 1e6) * float(age_us)

    def drift_error_us(self, now_pc_us: int) -> float:
        """How far the projection could be wrong over the model's current age.

        Both the measured drift and the residual scatter of the fit are charged
        against the guard: an unmodelled rate error of ``drift_ppm`` accumulates
        linearly with age, and the residual bounds how badly the window fits a
        straight line.
        """

        age_sec = self.model_age_us(now_pc_us) / 1e6
        return abs(self.drift_ppm) * age_sec + self.drift_residual_us

    def guard_us(self, now_pc_us: int) -> int:
        return int(
            math.ceil(
                float(self.clock_uncertainty_us)
                + self.drift_error_us(now_pc_us)
                + float(self.safety_margin_us)
            )
        )

    # ── Phase 13B compatible surface ────────────────────────────────────────

    def to_pc_clock_us(self, jetson_clock_us: int) -> int:
        return int(jetson_clock_us - self.jetson_minus_pc_offset_us)

    def estimated_pc_now_us(self, jetson_clock_us: int) -> int:
        """Map a Jetson instant into PC time using the drift-projected offset."""

        raw_pc_us = self.to_pc_clock_us(jetson_clock_us)
        return int(round(float(jetson_clock_us) - self.estimated_offset_us(raw_pc_us)))

    def issued_timestamp_us(self, jetson_clock_us: Optional[int] = None) -> int:
        """PC-domain issue timestamp, biased backwards by the guard band."""

        from workers.core.clock_sync import monotonic_us

        base = monotonic_us() if jetson_clock_us is None else int(jetson_clock_us)
        pc_now = self.estimated_pc_now_us(base)
        return int(pc_now - self.guard_us(pc_now))

    @property
    def clock_sync_degraded(self) -> bool:
        return bool(self.degraded_reasons())

    def degraded_reasons(self, now_pc_us: Optional[int] = None) -> List[str]:
        """Why AI authority must be withheld, or an empty list when healthy.

        ``now_pc_us`` defaults to the live clock so staleness is always part of
        the verdict: a model that stopped being refreshed must stop being
        trusted, which is precisely what Phase 13E lacked.
        """

        reasons = []  # type: List[str]
        if not self.clock_sync_valid or not self._window:
            reasons.append("no_valid_clock_sync")
            return reasons
        if now_pc_us is None:
            from workers.core.clock_sync import monotonic_us

            now_pc_us = self.estimated_pc_now_us(monotonic_us())
        if self.clock_uncertainty_us > self.max_uncertainty_us:
            reasons.append("clock_uncertainty_above_budget")
        if not math.isfinite(float(self.jetson_minus_pc_offset_us)):
            reasons.append("nonfinite_offset")
        drift = self.drift_ppm
        if not math.isfinite(drift):
            reasons.append("nonfinite_drift")
        elif abs(drift) > self.max_drift_ppm:
            reasons.append("implausible_drift_ppm")
        age_ms = self.model_age_us(now_pc_us) / 1000.0
        if age_ms > self.resync_interval_sec * self.max_age_intervals * 1000.0:
            reasons.append("clock_model_too_old")
        return reasons

    def one_way_latency_ms(self, pc_send_monotonic_us: int, jetson_recv_us: int) -> Optional[float]:
        if self.clock_sync_degraded:
            return None
        delta_us = self.to_pc_clock_us(jetson_recv_us) - int(pc_send_monotonic_us)
        if delta_us < 0:
            return None
        return round(delta_us / 1000.0, 3)

    # ── evidence ────────────────────────────────────────────────────────────

    def to_dict(self, now_pc_us: Optional[int] = None) -> Dict[str, Any]:
        reference = (
            int(now_pc_us)
            if now_pc_us is not None
            else (self._last_update_pc_us if self._last_update_pc_us is not None else 0)
        )
        return {
            "jetson_minus_pc_offset_us": self.jetson_minus_pc_offset_us,
            "estimated_offset_us": round(self.estimated_offset_us(reference), 3),
            "estimated_drift_ppm": self.drift_ppm,
            "clock_drift_residual_us": self.drift_residual_us,
            "clock_uncertainty_us": self.clock_uncertainty_us,
            "clock_guard_us": self.guard_us(reference),
            "clock_model_age_ms": round(self.model_age_us(reference) / 1000.0, 3),
            "clock_model_generation": self.generation,
            "clock_resync_count": self.resync_count,
            "clock_resync_failure_count": self.resync_failure_count,
            "clock_offset_jump_count": self.offset_jump_count,
            "clock_window_capacity": self._window.maxlen,
            "clock_window_size": len(self._window),
            "clock_window_high_watermark": self.window_high_watermark,
            "clock_resync_interval_sec": self.resync_interval_sec,
            "clock_safety_margin_us": self.safety_margin_us,
            "clock_max_drift_ppm": self.max_drift_ppm,
            "clock_sync_valid": self.clock_sync_valid,
            "clock_sync_degraded": self.clock_sync_degraded,
            "clock_degraded_reasons": self.degraded_reasons(reference),
            "clock_sign_convention": (
                "jetson_minus_pc_offset_us=((t2-t1)+(t3-t4))/2; "
                "pc_time_us=jetson_time_us-estimated_offset_us"
            ),
            "clock_source": "time.perf_counter_ns",
            "clock_discipline": "bounded_periodic_resync",
        }

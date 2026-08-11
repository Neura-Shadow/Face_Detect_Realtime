"""Phase 13B PC/Jetson clock-domain synchronisation.

The simulation PC and the real Jetson run independent monotonic clocks. Phase
13B issues Phase 13A command packets in the *PC* clock domain, so the Jetson
must convert its own monotonic timestamps before filling
``issued_timestamp_us`` / ``valid_until_us``.

Mandatory sign convention (do not change):

    jetson_minus_pc_offset_us = ((t2 - t1) + (t3 - t4)) / 2
    network_delay_us          = (t4 - t1) - (t3 - t2)
    clock_uncertainty_us      = max(0, network_delay_us / 2)
    pc_clock_us               = jetson_clock_us - jetson_minus_pc_offset_us

where ``t1`` is the PC send timestamp, ``t2`` the Jetson receive timestamp,
``t3`` the Jetson send timestamp and ``t4`` the PC receive timestamp.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

DEFAULT_SAMPLE_COUNT = 20
DEFAULT_MAX_UNCERTAINTY_US = 5000


def monotonic_us() -> int:
    """Monotonic microsecond timestamp used on both PC and Jetson."""

    return time.monotonic_ns() // 1000


@dataclass(frozen=True)
class ClockSyncSample:
    """One NTP-style four-timestamp probe."""

    t1_pc_send_us: int
    t2_jetson_recv_us: int
    t3_jetson_send_us: int
    t4_pc_recv_us: int

    @property
    def offset_us(self) -> float:
        """``jetson_minus_pc_offset_us`` for this sample."""

        return (
            (self.t2_jetson_recv_us - self.t1_pc_send_us)
            + (self.t3_jetson_send_us - self.t4_pc_recv_us)
        ) / 2.0

    @property
    def network_delay_us(self) -> float:
        """Round-trip network delay excluding Jetson processing time."""

        return (self.t4_pc_recv_us - self.t1_pc_send_us) - (
            self.t3_jetson_send_us - self.t2_jetson_recv_us
        )

    @property
    def rtt_us(self) -> int:
        return self.t4_pc_recv_us - self.t1_pc_send_us

    @property
    def valid(self) -> bool:
        return self.rtt_us >= 0 and self.network_delay_us >= 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "t1_pc_send_us": self.t1_pc_send_us,
            "t2_jetson_recv_us": self.t2_jetson_recv_us,
            "t3_jetson_send_us": self.t3_jetson_send_us,
            "t4_pc_recv_us": self.t4_pc_recv_us,
            "offset_us": round(self.offset_us, 3),
            "network_delay_us": round(self.network_delay_us, 3),
            "rtt_us": self.rtt_us,
            "valid": self.valid,
        }


@dataclass(frozen=True)
class ClockSyncResult:
    """Aggregated clock-sync estimate and its Phase 13B authority verdict."""

    jetson_minus_pc_offset_us: int
    clock_rtt_us: int
    clock_uncertainty_us: int
    clock_sample_count: int
    clock_valid_sample_count: int
    clock_sync_valid: bool
    clock_sync_degraded: bool
    max_uncertainty_us: int
    estimator: str
    reason: str

    @property
    def one_way_latency_allowed(self) -> bool:
        """One-way latency may only be reported when sync is inside budget."""

        return self.clock_sync_valid and not self.clock_sync_degraded

    def to_pc_clock_us(self, jetson_clock_us: int) -> int:
        """Convert a Jetson monotonic timestamp into the PC clock domain."""

        return int(jetson_clock_us - self.jetson_minus_pc_offset_us)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "jetson_minus_pc_offset_us": self.jetson_minus_pc_offset_us,
            "clock_rtt_us": self.clock_rtt_us,
            "clock_uncertainty_us": self.clock_uncertainty_us,
            "clock_sample_count": self.clock_sample_count,
            "clock_valid_sample_count": self.clock_valid_sample_count,
            "clock_sync_valid": self.clock_sync_valid,
            "clock_sync_degraded": self.clock_sync_degraded,
            "clock_max_uncertainty_us": self.max_uncertainty_us,
            "clock_offset_estimator": self.estimator,
            "clock_sync_reason": self.reason,
            "one_way_latency_allowed": self.one_way_latency_allowed,
            "clock_sign_convention": (
                "jetson_minus_pc_offset_us=((t2-t1)+(t3-t4))/2; "
                "pc_clock_us=jetson_clock_us-jetson_minus_pc_offset_us"
            ),
        }


def estimate_clock_offset(
    samples: List[ClockSyncSample],
    *,
    max_uncertainty_us: int = DEFAULT_MAX_UNCERTAINTY_US,
    min_sample_count: int = DEFAULT_SAMPLE_COUNT,
) -> ClockSyncResult:
    """Pick the minimum-RTT valid sample as the offset estimator.

    Minimum RTT is the standard robust estimator for NTP-style probes: the
    sample with the least queueing delay carries the least asymmetry error, and
    it preserves the mandated sign convention exactly.
    """

    valid = [sample for sample in samples if sample.valid]
    if not valid:
        return ClockSyncResult(
            jetson_minus_pc_offset_us=0,
            clock_rtt_us=0,
            clock_uncertainty_us=max_uncertainty_us + 1,
            clock_sample_count=len(samples),
            clock_valid_sample_count=0,
            clock_sync_valid=False,
            clock_sync_degraded=True,
            max_uncertainty_us=max_uncertainty_us,
            estimator="min_rtt",
            reason="no valid clock-sync samples were collected",
        )

    best = min(valid, key=lambda sample: sample.rtt_us)
    uncertainty = int(max(0.0, best.network_delay_us / 2.0))
    enough_samples = len(valid) >= min_sample_count
    within_budget = uncertainty <= max_uncertainty_us
    valid_sync = enough_samples and within_budget
    if valid_sync:
        reason = "clock sync within budget"
    elif not enough_samples:
        reason = "insufficient valid clock-sync samples (%d < %d)" % (len(valid), min_sample_count)
    else:
        reason = "clock uncertainty %d us exceeds budget %d us" % (uncertainty, max_uncertainty_us)

    return ClockSyncResult(
        jetson_minus_pc_offset_us=int(round(best.offset_us)),
        clock_rtt_us=int(best.rtt_us),
        clock_uncertainty_us=uncertainty,
        clock_sample_count=len(samples),
        clock_valid_sample_count=len(valid),
        clock_sync_valid=valid_sync,
        clock_sync_degraded=not valid_sync,
        max_uncertainty_us=max_uncertainty_us,
        estimator="min_rtt",
        reason=reason,
    )


class JetsonClockDomain:
    """Jetson-side helper converting local monotonic time into PC clock time."""

    def __init__(
        self,
        *,
        jetson_minus_pc_offset_us: int,
        clock_uncertainty_us: int,
        clock_sync_valid: bool,
        max_uncertainty_us: int = DEFAULT_MAX_UNCERTAINTY_US,
    ) -> None:
        self.jetson_minus_pc_offset_us = int(jetson_minus_pc_offset_us)
        self.clock_uncertainty_us = int(clock_uncertainty_us)
        self.clock_sync_valid = bool(clock_sync_valid)
        self.max_uncertainty_us = int(max_uncertainty_us)

    @property
    def clock_sync_degraded(self) -> bool:
        return (not self.clock_sync_valid) or self.clock_uncertainty_us > self.max_uncertainty_us

    def to_pc_clock_us(self, jetson_clock_us: int) -> int:
        return int(jetson_clock_us - self.jetson_minus_pc_offset_us)

    def issued_timestamp_us(self, jetson_clock_us: Optional[int] = None) -> int:
        """PC-domain issue timestamp with an uncertainty guard band.

        The frozen Phase 13A parser rejects any command whose
        ``issued_timestamp_us`` is in the receiver's future. Subtracting the
        measured uncertainty keeps a valid command from being pushed past the
        PC clock by conversion error; it can only ever make a command *older*,
        never fresher, so the guard band cannot mask a stale command.
        """

        base = monotonic_us() if jetson_clock_us is None else int(jetson_clock_us)
        return self.to_pc_clock_us(base) - self.clock_uncertainty_us

    def one_way_latency_ms(self, pc_send_monotonic_us: int, jetson_recv_us: int) -> Optional[float]:
        """One-way transport latency, or ``None`` when clock sync is degraded."""

        if self.clock_sync_degraded:
            return None
        delta_us = self.to_pc_clock_us(jetson_recv_us) - int(pc_send_monotonic_us)
        if delta_us < 0:
            return None
        return round(delta_us / 1000.0, 3)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "jetson_minus_pc_offset_us": self.jetson_minus_pc_offset_us,
            "clock_uncertainty_us": self.clock_uncertainty_us,
            "clock_sync_valid": self.clock_sync_valid,
            "clock_sync_degraded": self.clock_sync_degraded,
            "clock_max_uncertainty_us": self.max_uncertainty_us,
        }

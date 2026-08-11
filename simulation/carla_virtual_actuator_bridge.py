"""Phase 13B CARLA virtual actuator bridge.

The bridge applies control to the simulated CARLA vehicle **only** from a
control value that the portable C Virtual Safety MCU already accepted. It never
re-parses the 64-byte command packet in Python to decide authority: it consumes
``safety_mcu_receive_result_t`` and maps the C-validated q15 values.

Everything actuated here is simulated. No physical actuator is driven.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.carla_adapter import CarlaControlCommand
from workers.core.clock_sync import monotonic_us

DEFAULT_COMMAND_VALIDITY_MS = 500

SAFE_STOP_COMMAND = CarlaControlCommand(
    throttle=0.0,
    steer=0.0,
    brake=1.0,
    reverse=False,
    source_action="safe_stop",
    source_plan_id="phase13b-safe-stop",
)


@dataclass(frozen=True)
class ActuationRecord:
    """One virtual actuation decision, recorded for evidence."""

    tick_index: int
    applied_monotonic_us: int
    safe_stop: bool
    reason: str
    sequence: Optional[int]
    steer: float
    throttle: float
    brake: float
    mcu_state: Optional[int]
    classification: Optional[str]
    command_age_ms: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tick_index": self.tick_index,
            "applied_monotonic_us": self.applied_monotonic_us,
            "safe_stop": self.safe_stop,
            "reason": self.reason,
            "sequence": self.sequence,
            "steer": round(self.steer, 6),
            "throttle": round(self.throttle, 6),
            "brake": round(self.brake, 6),
            "mcu_state": self.mcu_state,
            "classification": self.classification,
            "command_age_ms": self.command_age_ms,
        }


class VirtualActuatorBridge:
    """Map C-accepted control results onto ``carla.VehicleControl``."""

    def __init__(
        self,
        *,
        command_validity_ms: int = DEFAULT_COMMAND_VALIDITY_MS,
        max_records: int = 4000,
    ) -> None:
        self.command_validity_ms = int(command_validity_ms)
        self.max_records = int(max_records)
        self.control_applied_count = 0
        self.active_control_applied_count = 0
        self.safe_stop_applied_count = 0
        self.hold_applied_count = 0
        self.tick_index = 0
        self.records = []  # type: List[ActuationRecord]
        self._held_result = None  # type: Optional[Any]
        self._held_received_us = 0
        self._held_command = None  # type: Optional[CarlaControlCommand]

    # ── decision ────────────────────────────────────────────────────────────

    @staticmethod
    def command_from_result(result: Any) -> CarlaControlCommand:
        """Build a CARLA control command from the C-validated q15 values."""

        steer = max(-1.0, min(1.0, float(result.steering)))
        throttle = max(0.0, min(1.0, float(result.throttle)))
        brake = max(0.0, min(1.0, float(result.brake)))
        return CarlaControlCommand(
            throttle=throttle,
            steer=steer,
            brake=brake,
            reverse=False,
            source_action="c_accepted_diagnostic_control",
            source_plan_id="phase13b-seq-%d" % int(result.sequence),
        )

    @staticmethod
    def is_safe_stop(result: Any) -> bool:
        """A C-accepted SAFE_STOP command carries zero throttle and full brake."""

        return int(result.throttle_q15) == 0 and int(result.brake_q15) > 0

    def decide(
        self,
        result: Optional[Any],
        *,
        now_us: Optional[int] = None,
        reason: str = "",
    ) -> CarlaControlCommand:
        """Return the control to apply for this tick.

        ``result`` must be the C Virtual Safety MCU result for the command that
        matches this tick, or ``None`` when no matching command arrived. A
        rejected or missing command always yields SAFE_STOP. A previously
        accepted command may be held for at most ``command_validity_ms``.
        """

        current_us = monotonic_us() if now_us is None else int(now_us)
        self.tick_index += 1

        if result is not None and bool(result.accepted):
            command = self.command_from_result(result)
            self._held_result = result
            self._held_received_us = current_us
            self._held_command = command
            safe_stop = self.is_safe_stop(result)
            self._record(
                current_us,
                safe_stop=safe_stop,
                reason=reason or ("c_accepted_safe_stop" if safe_stop else "c_accepted_control"),
                sequence=int(result.sequence),
                command=command,
                mcu_state=int(result.mcu_state),
                classification=result.classification,
                command_age_ms=0.0,
            )
            return command

        if result is not None and not bool(result.accepted):
            self._invalidate_hold()
            self._record(
                current_us,
                safe_stop=True,
                reason=reason or "command_rejected",
                sequence=int(result.sequence),
                command=SAFE_STOP_COMMAND,
                mcu_state=int(result.mcu_state),
                classification=result.classification,
                command_age_ms=None,
            )
            return SAFE_STOP_COMMAND

        # No matching command this tick: hold the last C-accepted control only
        # while its configured validity window is still open.
        if self._held_command is not None and self._held_result is not None:
            age_ms = (current_us - self._held_received_us) / 1000.0
            if age_ms <= self.command_validity_ms:
                held = self._held_result
                safe_stop = self.is_safe_stop(held)
                self.hold_applied_count += 1
                self._record(
                    current_us,
                    safe_stop=safe_stop,
                    reason=reason or "held_valid_command",
                    sequence=int(held.sequence),
                    command=self._held_command,
                    mcu_state=int(held.mcu_state),
                    classification=held.classification,
                    command_age_ms=round(age_ms, 3),
                )
                return self._held_command
            self._invalidate_hold()
            self._record(
                current_us,
                safe_stop=True,
                reason=reason or "command_validity_expired",
                sequence=None,
                command=SAFE_STOP_COMMAND,
                mcu_state=None,
                classification="STALE_REJECT",
                command_age_ms=round(age_ms, 3),
            )
            return SAFE_STOP_COMMAND

        self._record(
            current_us,
            safe_stop=True,
            reason=reason or "no_valid_command",
            sequence=None,
            command=SAFE_STOP_COMMAND,
            mcu_state=None,
            classification="TRANSPORT_TIMEOUT",
            command_age_ms=None,
        )
        return SAFE_STOP_COMMAND

    def force_safe_stop(self, reason: str, *, now_us: Optional[int] = None) -> CarlaControlCommand:
        """Apply SAFE_STOP for an explicit transport/clock/heartbeat fault."""

        current_us = monotonic_us() if now_us is None else int(now_us)
        self.tick_index += 1
        self._invalidate_hold()
        self._record(
            current_us,
            safe_stop=True,
            reason=reason,
            sequence=None,
            command=SAFE_STOP_COMMAND,
            mcu_state=None,
            classification="SAFE_STOP",
            command_age_ms=None,
        )
        return SAFE_STOP_COMMAND

    def _invalidate_hold(self) -> None:
        self._held_result = None
        self._held_command = None
        self._held_received_us = 0

    def _record(
        self,
        now_us: int,
        *,
        safe_stop: bool,
        reason: str,
        sequence: Optional[int],
        command: CarlaControlCommand,
        mcu_state: Optional[int],
        classification: Optional[str],
        command_age_ms: Optional[float],
    ) -> None:
        self.control_applied_count += 1
        if safe_stop:
            self.safe_stop_applied_count += 1
        else:
            self.active_control_applied_count += 1
        if len(self.records) < self.max_records:
            self.records.append(
                ActuationRecord(
                    tick_index=self.tick_index,
                    applied_monotonic_us=now_us,
                    safe_stop=safe_stop,
                    reason=reason,
                    sequence=sequence,
                    steer=command.steer,
                    throttle=command.throttle,
                    brake=command.brake,
                    mcu_state=mcu_state,
                    classification=classification,
                    command_age_ms=command_age_ms,
                )
            )

    # ── evidence ────────────────────────────────────────────────────────────

    def metrics(self) -> Dict[str, Any]:
        return {
            "virtual_actuator_control_applied_count": self.control_applied_count,
            "virtual_actuator_active_control_applied_count": self.active_control_applied_count,
            "virtual_actuator_safe_stop_applied_count": self.safe_stop_applied_count,
            "virtual_actuator_hold_applied_count": self.hold_applied_count,
            "virtual_actuator_command_validity_ms": self.command_validity_ms,
            "virtual_actuator_target": "simulated_carla_vehicle",
            "physical_actuator_control_executed": False,
            "control_authority_source": "portable_c_virtual_safety_mcu",
            "python_reparsed_command_for_authority": False,
        }

    def records_as_dicts(self) -> List[Dict[str, Any]]:
        return [record.to_dict() for record in self.records]

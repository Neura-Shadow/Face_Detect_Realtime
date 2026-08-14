"""Linux host 與 Safety MCU 之間的固定大小 command contract。"""

from __future__ import annotations

import math
import struct
import time
import zlib
from dataclasses import dataclass, replace
from enum import IntEnum
from typing import Final

from .range_shift_monitor import RangeShiftResult, RangeShiftState

PROTOCOL_VERSION: Final[int] = 1
PACKET_ENDIAN: Final[str] = "little"
PACKET_SIZE: Final[int] = 64
CRC_OFFSET: Final[int] = 60
CONTROL_SCALE: Final[int] = 32767
MAX_RESULT_AGE_MS: Final[int] = 150
PACKET_STRUCT: Final[struct.Struct] = struct.Struct("<HHIQQQIBBhHHHHIIII")


class MessageType(IntEnum):
    COMMAND = 1
    HEARTBEAT = 2


class ControlMode(IntEnum):
    HOLD = 0
    MANUAL = 1
    AI_ACTIVE = 2
    SAFE_STOP = 3


class CommandFlags(IntEnum):
    AI_RESULT_VALID = 1 << 0
    SAFETY_GATE_APPROVED = 1 << 1
    RANGE_SHIFT_REJECTED = 1 << 2
    SAFE_COMMAND = 1 << 3


class MCUState(IntEnum):
    BOOT = 0
    STANDBY = 1
    READY = 2
    ACTIVE = 3
    DEGRADED = 4
    FAILSAFE = 5


class PacketResult(IntEnum):
    ACCEPTED = 0
    LENGTH_REJECT = 1
    CRC_REJECT = 2
    STALE_REJECT = 3
    SEQUENCE_REJECT = 4
    LEASE_REJECT = 5
    VERSION_REJECT = 6
    RANGE_REJECT = 7
    STATE_REJECT = 8


@dataclass(frozen=True)
class CommandPacket:
    protocol_version: int
    message_type: int
    sequence: int
    source_timestamp_us: int
    issued_timestamp_us: int
    valid_until_us: int
    command_lease_id: int
    control_mode: int
    range_shift_state: int
    steering_q15: int
    throttle_q15: int
    brake_q15: int
    ai_confidence_q15: int
    reserved_u16: int
    result_age_ms: int
    flags: int
    reserved_u32: int
    crc32: int = 0

    @property
    def steering(self) -> float:
        return self.steering_q15 / CONTROL_SCALE

    @property
    def throttle(self) -> float:
        return self.throttle_q15 / CONTROL_SCALE

    @property
    def brake(self) -> float:
        return self.brake_q15 / CONTROL_SCALE

    @property
    def ai_confidence(self) -> float:
        return self.ai_confidence_q15 / CONTROL_SCALE


@dataclass(frozen=True)
class MCUResponse:
    accepted: bool
    result: PacketResult
    state: MCUState
    reason: str
    sequence: int | None


class ProtocolError(ValueError):
    """Host-side packet decode 發現格式或 CRC 錯誤。"""


def _q15(value: float, *, signed: bool) -> int:
    if not math.isfinite(value):
        raise ValueError("控制值必須是有限數")
    low = -1.0 if signed else 0.0
    if not low <= value <= 1.0:
        raise ValueError(f"控制值 {value} 超出 [{low}, 1.0]")
    return int(round(value * CONTROL_SCALE))


def encode_packet(packet: CommandPacket) -> bytes:
    """將 command 轉成 64-byte little-endian packet 並寫入 CRC-32/IEEE。"""

    if PACKET_STRUCT.size != PACKET_SIZE:
        raise RuntimeError(f"packet layout 漂移: {PACKET_STRUCT.size}")
    values = (
        packet.protocol_version,
        packet.message_type,
        packet.sequence,
        packet.source_timestamp_us,
        packet.issued_timestamp_us,
        packet.valid_until_us,
        packet.command_lease_id,
        packet.control_mode,
        packet.range_shift_state,
        packet.steering_q15,
        packet.throttle_q15,
        packet.brake_q15,
        packet.ai_confidence_q15,
        packet.reserved_u16,
        packet.result_age_ms,
        packet.flags,
        packet.reserved_u32,
        0,
    )
    encoded = PACKET_STRUCT.pack(*values)
    checksum = zlib.crc32(encoded[:CRC_OFFSET]) & 0xFFFFFFFF
    return encoded[:CRC_OFFSET] + struct.pack("<I", checksum)


def decode_packet(data: bytes, *, verify_crc: bool = True) -> CommandPacket:
    if len(data) != PACKET_SIZE:
        raise ProtocolError(f"packet 長度必須是 {PACKET_SIZE}, got {len(data)}")
    values = PACKET_STRUCT.unpack(data)
    packet = CommandPacket(*values)
    expected = zlib.crc32(data[:CRC_OFFSET]) & 0xFFFFFFFF
    if verify_crc and packet.crc32 != expected:
        raise ProtocolError(f"CRC mismatch: packet={packet.crc32:#x}, expected={expected:#x}")
    return packet


class EmbeddedCommandBridge:
    """將 SafetyGate 結果與 range gate 轉為 bounded command packet。"""

    def __init__(self, *, lease_duration_us: int = 500_000) -> None:
        if lease_duration_us <= 0:
            raise ValueError("lease_duration_us 必須大於 0")
        self.lease_duration_us = lease_duration_us
        self._sequence = 0

    def build_command(
        self,
        *,
        source_timestamp_us: int,
        issued_timestamp_us: int,
        command_lease_id: int,
        safety_gate_approved: bool,
        range_result: RangeShiftResult,
        steering: float,
        throttle: float,
        brake: float,
        ai_confidence: float,
        result_age_ms: int,
    ) -> tuple[CommandPacket, bytes]:
        self._sequence = (self._sequence + 1) & 0xFFFFFFFF
        ai_authority = safety_gate_approved and range_result.ai_result_valid
        flags = 0
        if safety_gate_approved:
            flags |= CommandFlags.SAFETY_GATE_APPROVED
        if range_result.ai_result_valid:
            flags |= CommandFlags.AI_RESULT_VALID

        if ai_authority:
            mode = ControlMode.AI_ACTIVE
        else:
            mode = ControlMode.SAFE_STOP
            steering, throttle, brake = 0.0, 0.0, 1.0
            flags |= CommandFlags.SAFE_COMMAND
            if range_result.state != RangeShiftState.VALID:
                flags |= CommandFlags.RANGE_SHIFT_REJECTED

        packet = CommandPacket(
            protocol_version=PROTOCOL_VERSION,
            message_type=MessageType.COMMAND,
            sequence=self._sequence,
            source_timestamp_us=source_timestamp_us,
            issued_timestamp_us=issued_timestamp_us,
            valid_until_us=issued_timestamp_us + self.lease_duration_us,
            command_lease_id=command_lease_id,
            control_mode=mode,
            range_shift_state=range_result.state,
            steering_q15=_q15(steering, signed=True),
            throttle_q15=_q15(throttle, signed=False),
            brake_q15=_q15(brake, signed=False),
            ai_confidence_q15=_q15(ai_confidence, signed=False),
            reserved_u16=0,
            result_age_ms=max(0, int(result_age_ms)),
            flags=int(flags),
            reserved_u32=0,
        )
        encoded = encode_packet(packet)
        return replace(packet, crc32=struct.unpack_from("<I", encoded, CRC_OFFSET)[0]), encoded


class SafetyMCUEmulator:
    """與 portable C reference 同語意的 Safety MCU 軟體 emulator。"""

    def __init__(self, *, heartbeat_timeout_us: int = 300_000, range_failsafe_threshold: int = 3) -> None:
        self.state = MCUState.BOOT
        self.heartbeat_timeout_us = heartbeat_timeout_us
        self.range_failsafe_threshold = range_failsafe_threshold
        self.active_lease_id = 0
        self.lease_expires_us = 0
        self.last_sequence: int | None = None
        self.last_valid_rx_us = 0
        self.consecutive_range_rejects = 0
        self.watchdog_kick_allowed = False
        self.counters = {result.name.lower(): 0 for result in PacketResult if result != PacketResult.ACCEPTED}
        self.counters.update({"packets_accepted": 0, "failsafe_entry_count": 0, "failsafe_recovery_count": 0, "range_reject_count": 0})

    def complete_boot(self) -> bool:
        return self._transition(MCUState.STANDBY)

    def arm(self) -> bool:
        return self._transition(MCUState.READY)

    def set_command_lease(self, lease_id: int, expires_us: int) -> None:
        self.active_lease_id = lease_id
        self.lease_expires_us = expires_us

    def clear_failsafe(self) -> bool:
        if self.state != MCUState.FAILSAFE:
            return False
        if self._transition(MCUState.STANDBY):
            self.counters["failsafe_recovery_count"] += 1
            self.last_sequence = None
            self.consecutive_range_rejects = 0
            return True
        return False

    def receive(self, data: bytes, *, now_us: int) -> MCUResponse:
        if len(data) != PACKET_SIZE:
            return self._reject(PacketResult.LENGTH_REJECT, "invalid packet length", None)
        try:
            packet = decode_packet(data)
        except ProtocolError:
            return self._reject(PacketResult.CRC_REJECT, "CRC validation failed", None)

        if packet.protocol_version != PROTOCOL_VERSION:
            return self._reject(PacketResult.VERSION_REJECT, "protocol version mismatch", packet.sequence)
        if packet.valid_until_us < now_us or packet.issued_timestamp_us > now_us:
            return self._reject(PacketResult.STALE_REJECT, "command validity window rejected", packet.sequence)
        if self.last_sequence is not None and packet.sequence <= self.last_sequence:
            return self._reject(PacketResult.SEQUENCE_REJECT, "duplicate or out-of-order sequence", packet.sequence)
        if packet.command_lease_id != self.active_lease_id or now_us > self.lease_expires_us:
            return self._reject(PacketResult.LEASE_REJECT, "command lease invalid or expired", packet.sequence)
        if not self._packet_ranges_valid(packet):
            return self._reject(PacketResult.RANGE_REJECT, "packet control/range field invalid", packet.sequence)
        if self.state not in (MCUState.READY, MCUState.ACTIVE, MCUState.DEGRADED):
            return self._reject(PacketResult.STATE_REJECT, "MCU state does not accept commands", packet.sequence)

        self.last_sequence = packet.sequence
        self.last_valid_rx_us = now_us
        self.counters["packets_accepted"] += 1
        safe_due_to_range = packet.range_shift_state != RangeShiftState.VALID
        if packet.control_mode == ControlMode.AI_ACTIVE and not safe_due_to_range:
            self.consecutive_range_rejects = 0
            self._transition(MCUState.ACTIVE)
        elif safe_due_to_range:
            self.counters["range_reject_count"] += 1
            self.consecutive_range_rejects += 1
            target = (
                MCUState.FAILSAFE
                if self.consecutive_range_rejects >= self.range_failsafe_threshold
                else MCUState.DEGRADED
            )
            self._transition(target)
        else:
            self.consecutive_range_rejects = 0
            self._transition(MCUState.DEGRADED)
        self.watchdog_kick_allowed = self.state in (MCUState.READY, MCUState.ACTIVE, MCUState.DEGRADED)
        return MCUResponse(True, PacketResult.ACCEPTED, self.state, "accepted", packet.sequence)

    def tick(self, *, now_us: int) -> MCUState:
        if self.state in (MCUState.READY, MCUState.ACTIVE, MCUState.DEGRADED):
            if self.last_valid_rx_us == 0 or now_us - self.last_valid_rx_us > self.heartbeat_timeout_us:
                self._transition(MCUState.FAILSAFE)
        return self.state

    def _reject(self, result: PacketResult, reason: str, sequence: int | None) -> MCUResponse:
        self.counters[result.name.lower()] += 1
        return MCUResponse(False, result, self.state, reason, sequence)

    @staticmethod
    def _packet_ranges_valid(packet: CommandPacket) -> bool:
        if packet.message_type not in (MessageType.COMMAND, MessageType.HEARTBEAT):
            return False
        if packet.control_mode not in tuple(item.value for item in ControlMode):
            return False
        if packet.range_shift_state not in tuple(item.value for item in RangeShiftState):
            return False
        if not -CONTROL_SCALE <= packet.steering_q15 <= CONTROL_SCALE:
            return False
        if not 0 <= packet.throttle_q15 <= CONTROL_SCALE or not 0 <= packet.brake_q15 <= CONTROL_SCALE:
            return False
        if not 0 <= packet.ai_confidence_q15 <= CONTROL_SCALE:
            return False
        if packet.reserved_u16 != 0 or packet.reserved_u32 != 0:
            return False
        if not 0 <= packet.result_age_ms <= MAX_RESULT_AGE_MS:
            return False
        if packet.control_mode == ControlMode.AI_ACTIVE and packet.range_shift_state != RangeShiftState.VALID:
            return False
        return True

    def _transition(self, target: MCUState) -> bool:
        allowed = {
            MCUState.BOOT: {MCUState.STANDBY, MCUState.FAILSAFE},
            MCUState.STANDBY: {MCUState.READY, MCUState.FAILSAFE},
            MCUState.READY: {MCUState.ACTIVE, MCUState.DEGRADED, MCUState.FAILSAFE},
            MCUState.ACTIVE: {MCUState.READY, MCUState.DEGRADED, MCUState.FAILSAFE},
            MCUState.DEGRADED: {MCUState.READY, MCUState.ACTIVE, MCUState.FAILSAFE},
            MCUState.FAILSAFE: {MCUState.STANDBY},
        }
        if target == self.state:
            return True
        if target not in allowed[self.state]:
            return False
        if target == MCUState.FAILSAFE and self.state != MCUState.FAILSAFE:
            self.counters["failsafe_entry_count"] += 1
        self.state = target
        self.watchdog_kick_allowed = target in (MCUState.READY, MCUState.ACTIVE, MCUState.DEGRADED)
        return True


def monotonic_time_us() -> int:
    """提供 host 端 command issuance 的單調時間基準。"""

    return time.monotonic_ns() // 1_000

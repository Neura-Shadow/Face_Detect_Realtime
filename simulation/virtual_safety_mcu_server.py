"""Phase 13B PC-side Virtual Safety MCU server backed by the portable C library.

The portable C parser/FSM is the Phase 13B runtime source of truth. This module
loads ``ma_vlna_safety_mcu_ffi`` with ctypes and drives it from the UDP command
receiver; it never re-implements packet validation in Python and never
re-parses an accepted 64-byte command to decide actuator authority.

``workers.core.embedded_command_bridge.SafetyMCUEmulator`` may be used as a
unit-test oracle only. It is not the Phase 13B runtime authority.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.clock_sync import monotonic_us
from workers.core.embedded_command_bridge import PACKET_SIZE as COMMAND_PACKET_SIZE
from workers.core.embedded_command_bridge import PROTOCOL_VERSION as COMMAND_PROTOCOL_VERSION
from workers.core.jil_protocol import (
    AckMessageType,
    AckStatusPacket,
    classification_for_result_code,
)
from workers.core.udp_command_transport import (
    AckUdpSender,
    CommandUdpReceiver,
    UdpTransportError,
)

FFI_ABI_VERSION = 1
DEFAULT_HEARTBEAT_TIMEOUT_US = 1_000_000
DEFAULT_RANGE_FAILSAFE_THRESHOLD = 3
CONTROL_SCALE = 32767

WINDOWS_LIBRARY_NAME = "ma_vlna_safety_mcu_ffi.dll"
LINUX_LIBRARY_NAME = "libma_vlna_safety_mcu_ffi.so"
#: Build artifacts live under the gitignored evidence root and are never committed.
DEFAULT_FFI_BUILD_DIR = REPO_ROOT / "experiments" / "phase13" / "_ffi_build"


class SafetyMcuFfiError(RuntimeError):
    """FFI library load, ABI mismatch or contract mismatch."""

    classification = "virtual_mcu_ffi_failed"


class SafetyMcuReceiveResult(ctypes.Structure):
    """ctypes mirror of ``safety_mcu_receive_result_t`` (28 bytes, fixed layout)."""

    _fields_ = [
        ("accepted", ctypes.c_uint8),
        ("mcu_state", ctypes.c_uint8),
        ("result_code", ctypes.c_uint8),
        ("range_shift_state", ctypes.c_uint8),
        ("sequence", ctypes.c_uint32),
        ("steering_q15", ctypes.c_int16),
        ("throttle_q15", ctypes.c_uint16),
        ("brake_q15", ctypes.c_uint16),
        ("reserved_u16", ctypes.c_uint16),
        ("fault_flags", ctypes.c_uint32),
        ("last_valid_command_age_ms", ctypes.c_uint32),
        ("heartbeat_age_ms", ctypes.c_uint32),
    ]

    @property
    def steering(self) -> float:
        return self.steering_q15 / float(CONTROL_SCALE)

    @property
    def throttle(self) -> float:
        return self.throttle_q15 / float(CONTROL_SCALE)

    @property
    def brake(self) -> float:
        return self.brake_q15 / float(CONTROL_SCALE)

    @property
    def classification(self) -> str:
        return classification_for_result_code(self.result_code)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": bool(self.accepted),
            "mcu_state": int(self.mcu_state),
            "result_code": int(self.result_code),
            "classification": self.classification,
            "range_shift_state": int(self.range_shift_state),
            "sequence": int(self.sequence),
            "steering_q15": int(self.steering_q15),
            "throttle_q15": int(self.throttle_q15),
            "brake_q15": int(self.brake_q15),
            "steering": round(self.steering, 6),
            "throttle": round(self.throttle, 6),
            "brake": round(self.brake, 6),
            "fault_flags": int(self.fault_flags),
            "last_valid_command_age_ms": int(self.last_valid_command_age_ms),
            "heartbeat_age_ms": int(self.heartbeat_age_ms),
        }


class SafetyMcuCounters(ctypes.Structure):
    """ctypes mirror of ``safety_mcu_counters_t`` (56 bytes, fixed layout)."""

    _fields_ = [
        ("packets_accepted", ctypes.c_uint32),
        ("length_reject_count", ctypes.c_uint32),
        ("crc_reject_count", ctypes.c_uint32),
        ("stale_reject_count", ctypes.c_uint32),
        ("sequence_reject_count", ctypes.c_uint32),
        ("lease_reject_count", ctypes.c_uint32),
        ("version_reject_count", ctypes.c_uint32),
        ("control_range_reject_count", ctypes.c_uint32),
        ("state_reject_count", ctypes.c_uint32),
        ("range_reject_count", ctypes.c_uint32),
        ("failsafe_entry_count", ctypes.c_uint32),
        ("failsafe_recovery_count", ctypes.c_uint32),
        ("receive_call_count", ctypes.c_uint32),
        ("session_count", ctypes.c_uint32),
    ]

    def to_dict(self) -> Dict[str, int]:
        return {name: int(getattr(self, name)) for name, _ in self._fields_}


def default_library_name() -> str:
    return WINDOWS_LIBRARY_NAME if os.name == "nt" else LINUX_LIBRARY_NAME


def find_safety_mcu_library(explicit_path: Optional[str] = None) -> Optional[Path]:
    """Locate the FFI shared library without building anything."""

    if explicit_path:
        candidate = Path(explicit_path)
        return candidate if candidate.is_file() else None
    name = default_library_name()
    search_roots = [
        DEFAULT_FFI_BUILD_DIR,
        REPO_ROOT / "embedded" / "build",
        REPO_ROOT / "build",
    ]
    for root in search_roots:
        candidate = root / name
        if candidate.is_file():
            return candidate
        if root.is_dir():
            for found in sorted(root.rglob(name)):
                return found
    return None


def build_safety_mcu_library(
    *,
    build_dir: Optional[Path] = None,
    generator: Optional[str] = None,
    c_compiler: Optional[str] = None,
) -> Dict[str, Any]:
    """Configure and build the FFI shared library into an ignored build tree."""

    import shutil

    target_dir = Path(build_dir) if build_dir else DEFAULT_FFI_BUILD_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    cmake = shutil.which("cmake")
    if cmake is None:
        return {"built": False, "error": "cmake not found", "build_dir": str(target_dir)}

    configure = [cmake, "-S", str(REPO_ROOT / "embedded"), "-B", str(target_dir)]
    if generator is None and os.name == "nt" and shutil.which("mingw32-make"):
        generator = "MinGW Makefiles"
        if c_compiler is None:
            c_compiler = shutil.which("gcc")
    if generator:
        configure.extend(["-G", generator])
    if c_compiler:
        configure.append("-DCMAKE_C_COMPILER=%s" % c_compiler)

    commands = []  # type: List[Dict[str, Any]]
    for command in (configure, [cmake, "--build", str(target_dir), "--target", "ma_vlna_safety_mcu_ffi"]):
        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        commands.append(
            {
                "command": command,
                "returncode": completed.returncode,
                "stdout_tail": completed.stdout.strip().splitlines()[-8:],
                "stderr_tail": completed.stderr.strip().splitlines()[-8:],
            }
        )
        if completed.returncode != 0:
            return {"built": False, "commands": commands, "build_dir": str(target_dir)}

    library = find_safety_mcu_library(None)
    return {
        "built": library is not None,
        "commands": commands,
        "build_dir": str(target_dir),
        "library_path": str(library) if library else None,
    }


class SafetyMcuLibrary:
    """Thin ctypes binding over the Phase 13B narrow C ABI."""

    def __init__(self, library_path: Path) -> None:
        self.library_path = Path(library_path)
        if not self.library_path.is_file():
            raise SafetyMcuFfiError("FFI library not found: %s" % self.library_path)
        self._lib = ctypes.CDLL(str(self.library_path))
        self._bind()
        self.abi_version = int(self._lib.safety_mcu_get_abi_version())
        self.protocol_version = int(self._lib.safety_mcu_get_protocol_version())
        self.command_packet_size = int(self._lib.safety_mcu_get_command_packet_size())
        self.crc_coverage_bytes = int(self._lib.safety_mcu_get_crc_coverage_bytes())
        self.control_scale = int(self._lib.safety_mcu_get_control_scale())
        self.verify_contract()

    def _bind(self) -> None:
        lib = self._lib
        lib.safety_mcu_get_abi_version.restype = ctypes.c_uint32
        lib.safety_mcu_get_protocol_version.restype = ctypes.c_uint16
        lib.safety_mcu_get_command_packet_size.restype = ctypes.c_uint32
        lib.safety_mcu_get_crc_coverage_bytes.restype = ctypes.c_uint32
        lib.safety_mcu_get_control_scale.restype = ctypes.c_uint32
        lib.safety_mcu_get_receive_result_size.restype = ctypes.c_uint32
        lib.safety_mcu_get_counters_size.restype = ctypes.c_uint32
        lib.safety_mcu_crc32.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t]
        lib.safety_mcu_crc32.restype = ctypes.c_uint32

        lib.safety_mcu_create.argtypes = [ctypes.c_uint64, ctypes.c_uint32]
        lib.safety_mcu_create.restype = ctypes.c_void_p
        lib.safety_mcu_destroy.argtypes = [ctypes.c_void_p]
        lib.safety_mcu_destroy.restype = None
        lib.safety_mcu_reset.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint32]
        lib.safety_mcu_reset.restype = ctypes.c_int32

        for name in ("safety_mcu_complete_boot", "safety_mcu_arm", "safety_mcu_clear_failsafe"):
            function = getattr(lib, name)
            function.argtypes = [ctypes.c_void_p]
            function.restype = ctypes.c_int32

        lib.safety_mcu_set_lease.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint64]
        lib.safety_mcu_set_lease.restype = ctypes.c_int32
        lib.safety_mcu_begin_session.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint64]
        lib.safety_mcu_begin_session.restype = ctypes.c_int32

        lib.safety_mcu_receive_packet.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
            ctypes.c_uint64,
            ctypes.POINTER(SafetyMcuReceiveResult),
        ]
        lib.safety_mcu_receive_packet.restype = ctypes.c_int32
        lib.safety_mcu_tick.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        lib.safety_mcu_tick.restype = ctypes.c_uint8
        lib.safety_mcu_get_state.argtypes = [ctypes.c_void_p]
        lib.safety_mcu_get_state.restype = ctypes.c_uint8
        lib.safety_mcu_get_counters.argtypes = [ctypes.c_void_p, ctypes.POINTER(SafetyMcuCounters)]
        lib.safety_mcu_get_counters.restype = ctypes.c_int32

    def verify_contract(self) -> None:
        """Reject any library whose ABI or Phase 13A contract does not match."""

        if self.abi_version != FFI_ABI_VERSION:
            raise SafetyMcuFfiError(
                "FFI ABI version mismatch: library=%d expected=%d"
                % (self.abi_version, FFI_ABI_VERSION)
            )
        if self.protocol_version != COMMAND_PROTOCOL_VERSION:
            raise SafetyMcuFfiError(
                "Phase 13A protocol version mismatch: library=%d expected=%d"
                % (self.protocol_version, COMMAND_PROTOCOL_VERSION)
            )
        if self.command_packet_size != COMMAND_PACKET_SIZE:
            raise SafetyMcuFfiError(
                "Phase 13A command packet size mismatch: library=%d expected=%d"
                % (self.command_packet_size, COMMAND_PACKET_SIZE)
            )
        result_size = int(self._lib.safety_mcu_get_receive_result_size())
        if result_size != ctypes.sizeof(SafetyMcuReceiveResult):
            raise SafetyMcuFfiError(
                "receive result layout mismatch: c=%d ctypes=%d"
                % (result_size, ctypes.sizeof(SafetyMcuReceiveResult))
            )
        counters_size = int(self._lib.safety_mcu_get_counters_size())
        if counters_size != ctypes.sizeof(SafetyMcuCounters):
            raise SafetyMcuFfiError(
                "counters layout mismatch: c=%d ctypes=%d"
                % (counters_size, ctypes.sizeof(SafetyMcuCounters))
            )

    def crc32(self, data: bytes) -> int:
        buffer = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
        return int(self._lib.safety_mcu_crc32(buffer, len(data)))

    def describe(self) -> Dict[str, Any]:
        return {
            "mcu_library_path": str(self.library_path),
            "mcu_ffi_abi_version": self.abi_version,
            "mcu_protocol_version": self.protocol_version,
            "mcu_command_packet_size": self.command_packet_size,
            "mcu_crc_coverage_bytes": self.crc_coverage_bytes,
            "mcu_control_scale": self.control_scale,
            "mcu_receive_result_size": ctypes.sizeof(SafetyMcuReceiveResult),
            "mcu_counters_size": ctypes.sizeof(SafetyMcuCounters),
            "mcu_runtime_authority": "portable_c_library",
            "python_emulator_used_as_runtime_authority": False,
        }

    # ── instance operations ─────────────────────────────────────────────────

    def create(
        self,
        *,
        heartbeat_timeout_us: int = DEFAULT_HEARTBEAT_TIMEOUT_US,
        range_failsafe_threshold: int = DEFAULT_RANGE_FAILSAFE_THRESHOLD,
    ) -> int:
        handle = self._lib.safety_mcu_create(
            ctypes.c_uint64(int(heartbeat_timeout_us)), ctypes.c_uint32(int(range_failsafe_threshold))
        )
        if not handle:
            raise SafetyMcuFfiError("safety_mcu_create returned NULL")
        return int(handle)

    def destroy(self, handle: int) -> None:
        self._lib.safety_mcu_destroy(ctypes.c_void_p(handle))

    def complete_boot(self, handle: int) -> int:
        return int(self._lib.safety_mcu_complete_boot(ctypes.c_void_p(handle)))

    def arm(self, handle: int) -> int:
        return int(self._lib.safety_mcu_arm(ctypes.c_void_p(handle)))

    def clear_failsafe(self, handle: int) -> int:
        return int(self._lib.safety_mcu_clear_failsafe(ctypes.c_void_p(handle)))

    def set_lease(self, handle: int, lease_id: int, expires_us: int) -> int:
        return int(
            self._lib.safety_mcu_set_lease(
                ctypes.c_void_p(handle), ctypes.c_uint32(int(lease_id)), ctypes.c_uint64(int(expires_us))
            )
        )

    def begin_session(self, handle: int, lease_id: int, expires_us: int) -> int:
        return int(
            self._lib.safety_mcu_begin_session(
                ctypes.c_void_p(handle), ctypes.c_uint32(int(lease_id)), ctypes.c_uint64(int(expires_us))
            )
        )

    def receive_packet(self, handle: int, packet: bytes, now_us: int) -> SafetyMcuReceiveResult:
        result = SafetyMcuReceiveResult()
        buffer = (ctypes.c_uint8 * max(1, len(packet))).from_buffer_copy(
            packet if packet else b"\x00"
        )
        status = int(
            self._lib.safety_mcu_receive_packet(
                ctypes.c_void_p(handle),
                buffer,
                ctypes.c_size_t(len(packet)),
                ctypes.c_uint64(int(now_us)),
                ctypes.byref(result),
            )
        )
        if status != 0:
            raise SafetyMcuFfiError("safety_mcu_receive_packet failed with status %d" % status)
        return result

    def tick(self, handle: int, now_us: int) -> int:
        return int(self._lib.safety_mcu_tick(ctypes.c_void_p(handle), ctypes.c_uint64(int(now_us))))

    def get_state(self, handle: int) -> int:
        return int(self._lib.safety_mcu_get_state(ctypes.c_void_p(handle)))

    def get_counters(self, handle: int) -> SafetyMcuCounters:
        counters = SafetyMcuCounters()
        status = int(
            self._lib.safety_mcu_get_counters(ctypes.c_void_p(handle), ctypes.byref(counters))
        )
        if status != 0:
            raise SafetyMcuFfiError("safety_mcu_get_counters failed with status %d" % status)
        return counters


@dataclass
class McuFaultInjection:
    """Deterministic one-at-a-time PC-side fault injection switches."""

    drop_next_ack: int = 0
    corrupt_next_ack_crc: int = 0
    stall_ack_us: int = 0
    force_ack_sequence: Optional[int] = None

    def any_active(self) -> bool:
        return bool(
            self.drop_next_ack
            or self.corrupt_next_ack_crc
            or self.stall_ack_us
            or self.force_ack_sequence is not None
        )


class VirtualSafetyMCUServer:
    """UDP command listener that delegates every decision to the C library."""

    def __init__(
        self,
        *,
        library: SafetyMcuLibrary,
        receiver: CommandUdpReceiver,
        ack_sender: AckUdpSender,
        heartbeat_timeout_us: int = DEFAULT_HEARTBEAT_TIMEOUT_US,
        range_failsafe_threshold: int = DEFAULT_RANGE_FAILSAFE_THRESHOLD,
        event_sink: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> None:
        self.library = library
        self.receiver = receiver
        self.ack_sender = ack_sender
        self.heartbeat_timeout_us = int(heartbeat_timeout_us)
        self.range_failsafe_threshold = int(range_failsafe_threshold)
        self._event_sink = event_sink
        self.handle = library.create(
            heartbeat_timeout_us=self.heartbeat_timeout_us,
            range_failsafe_threshold=self.range_failsafe_threshold,
        )
        self.faults = McuFaultInjection()
        self.lock = threading.Lock()
        self._thread = None  # type: Optional[threading.Thread]
        self._stop = threading.Event()
        self.last_result = None  # type: Optional[SafetyMcuReceiveResult]
        self.last_accepted_result = None  # type: Optional[SafetyMcuReceiveResult]
        self.last_accepted_monotonic_us = 0
        self.command_accept_count = 0
        self.command_reject_count = 0
        self.wrong_size_datagram_count = 0
        self.unexpected_sender_count = 0
        self.acks_sent = 0
        self.acks_dropped = 0
        self.acks_corrupted = 0
        self.classification_counts = {}  # type: Dict[str, int]
        self.first_valid_received = False

    # ── bring-up ────────────────────────────────────────────────────────────

    def bootstrap(self, *, lease_id: int, lease_expires_us: int) -> Dict[str, Any]:
        """BOOT -> STANDBY -> READY plus an explicit session/lease bootstrap."""

        boot = self.library.complete_boot(self.handle)
        arm = self.library.arm(self.handle)
        session = self.library.begin_session(self.handle, lease_id, lease_expires_us)
        state = self.library.get_state(self.handle)
        payload = {
            "complete_boot_status": boot,
            "arm_status": arm,
            "begin_session_status": session,
            "mcu_state": state,
            "command_lease_id": lease_id,
            "lease_expires_us": lease_expires_us,
        }
        self._emit("virtual_mcu_bootstrap", payload)
        return payload

    def refresh_lease(self, lease_id: int, lease_expires_us: int) -> None:
        with self.lock:
            self.library.set_lease(self.handle, lease_id, lease_expires_us)

    def recover_from_failsafe(self, *, lease_id: int, lease_expires_us: int) -> Dict[str, Any]:
        """Explicit FAILSAFE recovery; never implicit on reconnect."""

        with self.lock:
            cleared = self.library.clear_failsafe(self.handle)
            armed = self.library.arm(self.handle)
            session = self.library.begin_session(self.handle, lease_id, lease_expires_us)
            state = self.library.get_state(self.handle)
            self.first_valid_received = False
        payload = {
            "clear_failsafe_status": cleared,
            "arm_status": armed,
            "begin_session_status": session,
            "mcu_state": state,
        }
        self._emit("virtual_mcu_failsafe_recovery", payload)
        return payload

    # ── runtime ─────────────────────────────────────────────────────────────

    def process_one(self, *, timeout_sec: Optional[float] = None) -> Optional[SafetyMcuReceiveResult]:
        """Receive one datagram, run the C MCU and send the ACK/status packet."""

        try:
            data, addr = self.receiver.receive(timeout_sec=timeout_sec)
        except UdpTransportError as exc:
            if exc.classification == "LENGTH_REJECT":
                self.wrong_size_datagram_count += 1
                self._bump("LENGTH_REJECT")
                self._emit("command_datagram_wrong_size", {"classification": "LENGTH_REJECT"})
            elif exc.classification == "UNEXPECTED_SENDER":
                self.unexpected_sender_count += 1
                self._bump("UNEXPECTED_SENDER")
                self._emit("command_datagram_unexpected_sender", {"classification": "UNEXPECTED_SENDER"})
            return None

        receive_us = monotonic_us()
        with self.lock:
            result = self.library.receive_packet(self.handle, data, receive_us)
            accepted = bool(result.accepted)
            if accepted:
                self.command_accept_count += 1
                self.last_accepted_result = result
                self.last_accepted_monotonic_us = receive_us
                self.first_valid_received = True
            else:
                self.command_reject_count += 1
            self.last_result = result
            self._bump(result.classification)

            ack = AckStatusPacket(
                acked_sequence=int(result.sequence),
                receive_timestamp_us=receive_us,
                send_timestamp_us=monotonic_us(),
                mcu_state=int(result.mcu_state),
                result_code=int(result.result_code),
                accepted=1 if accepted else 0,
                range_shift_state=int(result.range_shift_state),
                fault_flags=int(result.fault_flags),
                last_valid_command_age_ms=int(result.last_valid_command_age_ms),
                heartbeat_age_ms=int(result.heartbeat_age_ms),
                message_type=int(AckMessageType.COMMAND_ACK),
            )
            drop = self.faults.drop_next_ack > 0
            corrupt = self.faults.corrupt_next_ack_crc > 0
            forced_sequence = self.faults.force_ack_sequence
            stall_us = self.faults.stall_ack_us
            if drop:
                self.faults.drop_next_ack -= 1
            if corrupt:
                self.faults.corrupt_next_ack_crc -= 1
            if forced_sequence is not None:
                self.faults.force_ack_sequence = None
                ack = AckStatusPacket(
                    acked_sequence=int(forced_sequence),
                    receive_timestamp_us=ack.receive_timestamp_us,
                    send_timestamp_us=ack.send_timestamp_us,
                    mcu_state=ack.mcu_state,
                    result_code=ack.result_code,
                    accepted=ack.accepted,
                    range_shift_state=ack.range_shift_state,
                    fault_flags=ack.fault_flags,
                    last_valid_command_age_ms=ack.last_valid_command_age_ms,
                    heartbeat_age_ms=ack.heartbeat_age_ms,
                    message_type=ack.message_type,
                )
            if stall_us:
                self.faults.stall_ack_us = 0

        if stall_us:
            time.sleep(stall_us / 1_000_000.0)
        if drop:
            self.acks_dropped += 1
        elif corrupt:
            from workers.core.jil_protocol import encode_ack_packet

            encoded = bytearray(encode_ack_packet(ack))
            encoded[10] ^= 0x01  # flip a covered byte so the ACK CRC fails
            self.ack_sender.send_raw(bytes(encoded))
            self.acks_corrupted += 1
            self.acks_sent += 1
        else:
            self.ack_sender.send_ack(ack)
            self.acks_sent += 1

        self._emit(
            "command_processed",
            {
                "source_host": addr[0],
                "sequence": int(result.sequence),
                "classification": result.classification,
                "accepted": accepted,
                "mcu_state": int(result.mcu_state),
                "ack_dropped": drop,
                "ack_corrupted": corrupt,
            },
        )
        return result

    def processed_count(self) -> int:
        """Total commands the C MCU has classified (accepted plus rejected)."""

        return self.command_accept_count + self.command_reject_count

    def wait_for_next_result(
        self, baseline: int, *, timeout_sec: float
    ) -> Optional[SafetyMcuReceiveResult]:
        """Block until the C MCU classifies another command, or time out."""

        deadline = time.time() + float(timeout_sec)
        while time.time() < deadline:
            if self.processed_count() > baseline:
                return self.last_result
            time.sleep(0.002)
        return None

    def tick(self, *, now_us: Optional[int] = None) -> int:
        """Advance the C watchdog. Never ticks before the first accepted packet."""

        with self.lock:
            if not self.first_valid_received:
                return self.library.get_state(self.handle)
            return self.library.tick(self.handle, monotonic_us() if now_us is None else int(now_us))

    def serve_forever(self, *, poll_timeout_sec: float = 0.2) -> None:
        while not self._stop.is_set():
            self.process_one(timeout_sec=poll_timeout_sec)
            self.tick()

    def start(self, *, poll_timeout_sec: float = 0.2) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self.serve_forever,
            kwargs={"poll_timeout_sec": poll_timeout_sec},
            name="virtual-safety-mcu",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=5)

    def close(self) -> None:
        self.stop()
        if self.handle:
            self.library.destroy(self.handle)
            self.handle = 0

    # ── evidence ────────────────────────────────────────────────────────────

    def _bump(self, classification: str) -> None:
        self.classification_counts[classification] = (
            self.classification_counts.get(classification, 0) + 1
        )

    def _emit(self, event_type: str, details: Dict[str, Any]) -> None:
        if self._event_sink is not None:
            self._event_sink(event_type, details)

    def metrics(self) -> Dict[str, Any]:
        with self.lock:
            if self.handle:
                counters = self.library.get_counters(self.handle).to_dict()
                state = self.library.get_state(self.handle)
            else:  # closed instance: report the last known shape without the FFI
                counters = {name: 0 for name, _ in SafetyMcuCounters._fields_}
                state = None
        payload = {
            "virtual_mcu_state": state,
            "virtual_mcu_counters": counters,
            "command_accept_count": self.command_accept_count,
            "command_reject_count": self.command_reject_count,
            "command_wrong_size_datagram_count": self.wrong_size_datagram_count,
            "command_unexpected_sender_count": self.unexpected_sender_count,
            "acks_sent": self.acks_sent,
            "acks_dropped_injected": self.acks_dropped,
            "acks_corrupted_injected": self.acks_corrupted,
            "classification_counts": dict(self.classification_counts),
            "heartbeat_timeout_us": self.heartbeat_timeout_us,
            "range_failsafe_threshold": self.range_failsafe_threshold,
        }
        payload.update(self.library.describe())
        payload.update(self.receiver.metrics())
        payload.update(self.ack_sender.metrics())
        return payload

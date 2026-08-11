"""Phase 13B C FFI tests: ABI layout, contract verification and oracle cross-check.

The portable C library is the Phase 13B runtime source of truth. These tests
prove the ctypes mirror matches the C layout byte for byte, that the runtime
refuses a library whose Phase 13A contract does not match, and that the C
decisions agree with the Python ``SafetyMCUEmulator`` used purely as a test
oracle.
"""

from __future__ import annotations

import ctypes
import sys
import unittest
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from simulation.virtual_safety_mcu_server import (
    FFI_ABI_VERSION,
    SafetyMcuCounters,
    SafetyMcuLibrary,
    SafetyMcuReceiveResult,
    build_safety_mcu_library,
    find_safety_mcu_library,
)
from workers.core.embedded_command_bridge import (
    CONTROL_SCALE,
    PACKET_SIZE,
    PROTOCOL_VERSION,
    CommandPacket,
    ControlMode,
    MCUState,
    MessageType,
    PacketResult,
    SafetyMCUEmulator,
    encode_packet,
)
from workers.core.jil_protocol import classification_for_result_code
from workers.core.range_shift_monitor import RangeShiftState

LEASE_ID = 0x13B0F00D
NOW_US = 5_000_000


def _library() -> SafetyMcuLibrary:
    path = find_safety_mcu_library(None)
    if path is None:
        build_safety_mcu_library()
        path = find_safety_mcu_library(None)
    if path is None:
        raise unittest.SkipTest("safety MCU FFI shared library could not be built")
    return SafetyMcuLibrary(path)


def make_packet(
    sequence: int,
    *,
    lease_id: int = LEASE_ID,
    issued_us: int = NOW_US,
    valid_until_us: int = NOW_US + 500_000,
    control_mode: int = int(ControlMode.AI_ACTIVE),
    range_state: int = int(RangeShiftState.VALID),
    steering_q15: int = -1200,
    throttle_q15: int = 6553,
    brake_q15: int = 0,
    result_age_ms: int = 20,
    protocol_version: int = PROTOCOL_VERSION,
) -> bytes:
    packet = CommandPacket(
        protocol_version=protocol_version,
        message_type=int(MessageType.COMMAND),
        sequence=sequence,
        source_timestamp_us=max(0, issued_us - 1000),
        issued_timestamp_us=issued_us,
        valid_until_us=valid_until_us,
        command_lease_id=lease_id,
        control_mode=control_mode,
        range_shift_state=range_state,
        steering_q15=steering_q15,
        throttle_q15=throttle_q15,
        brake_q15=brake_q15,
        ai_confidence_q15=30000,
        reserved_u16=0,
        result_age_ms=result_age_ms,
        flags=0,
        reserved_u32=0,
    )
    return encode_packet(packet)


class TestCtypesLayout(unittest.TestCase):
    def test_receive_result_layout_matches_the_c_struct(self) -> None:
        self.assertEqual(ctypes.sizeof(SafetyMcuReceiveResult), 28)
        offsets = {name: getattr(SafetyMcuReceiveResult, name).offset
                   for name, _ in SafetyMcuReceiveResult._fields_}
        self.assertEqual(offsets["accepted"], 0)
        self.assertEqual(offsets["mcu_state"], 1)
        self.assertEqual(offsets["result_code"], 2)
        self.assertEqual(offsets["range_shift_state"], 3)
        self.assertEqual(offsets["sequence"], 4)
        self.assertEqual(offsets["steering_q15"], 8)
        self.assertEqual(offsets["throttle_q15"], 10)
        self.assertEqual(offsets["brake_q15"], 12)
        self.assertEqual(offsets["fault_flags"], 16)
        self.assertEqual(offsets["last_valid_command_age_ms"], 20)
        self.assertEqual(offsets["heartbeat_age_ms"], 24)

    def test_counters_layout(self) -> None:
        self.assertEqual(ctypes.sizeof(SafetyMcuCounters), 56)
        self.assertEqual(len(SafetyMcuCounters._fields_), 14)


class TestSafetyMcuLibraryContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library = _library()

    def test_abi_and_phase13a_contract(self) -> None:
        self.assertEqual(self.library.abi_version, FFI_ABI_VERSION)
        self.assertEqual(self.library.protocol_version, PROTOCOL_VERSION)
        self.assertEqual(self.library.command_packet_size, PACKET_SIZE)
        self.assertEqual(self.library.command_packet_size, 64)
        self.assertEqual(self.library.crc_coverage_bytes, 60)
        self.assertEqual(self.library.control_scale, CONTROL_SCALE)

    def test_c_and_python_crc_agree(self) -> None:
        import zlib

        payload = b"phase13b-crc-agreement"
        self.assertEqual(self.library.crc32(payload), zlib.crc32(payload) & 0xFFFFFFFF)

    def test_describe_reports_c_as_runtime_authority(self) -> None:
        described = self.library.describe()
        self.assertEqual(described["mcu_runtime_authority"], "portable_c_library")
        self.assertFalse(described["python_emulator_used_as_runtime_authority"])

    def test_instances_are_independent(self) -> None:
        first = self.library.create(heartbeat_timeout_us=300_000, range_failsafe_threshold=3)
        second = self.library.create(heartbeat_timeout_us=300_000, range_failsafe_threshold=3)
        try:
            self.assertNotEqual(first, second)
            self.library.complete_boot(first)
            self.library.arm(first)
            self.library.begin_session(first, LEASE_ID, NOW_US + 10_000_000)
            accepted = self.library.receive_packet(first, make_packet(1), NOW_US)
            rejected = self.library.receive_packet(second, make_packet(1), NOW_US)
            self.assertTrue(accepted.accepted)
            self.assertFalse(rejected.accepted)
            self.assertEqual(self.library.get_counters(second).packets_accepted, 0)
        finally:
            self.library.destroy(first)
            self.library.destroy(second)


class TestCDecisionsMatchPythonOracle(unittest.TestCase):
    """The Python emulator is a test oracle only, never the runtime authority."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.library = _library()

    def setUp(self) -> None:
        self.handle = self.library.create(
            heartbeat_timeout_us=300_000, range_failsafe_threshold=3
        )
        self.library.complete_boot(self.handle)
        self.library.arm(self.handle)
        self.library.begin_session(self.handle, LEASE_ID, NOW_US + 10_000_000)

        self.oracle = SafetyMCUEmulator(heartbeat_timeout_us=300_000, range_failsafe_threshold=3)
        self.oracle.complete_boot()
        self.oracle.arm()
        self.oracle.set_command_lease(LEASE_ID, NOW_US + 10_000_000)

    def tearDown(self) -> None:
        self.library.destroy(self.handle)

    def _compare(self, packet_bytes: bytes, now_us: int = NOW_US) -> tuple:
        c_result = self.library.receive_packet(self.handle, packet_bytes, now_us)
        oracle = self.oracle.receive(packet_bytes, now_us=now_us)
        self.assertEqual(
            int(c_result.result_code),
            int(oracle.result),
            "C result %s disagrees with the Python oracle %s"
            % (c_result.classification, oracle.result.name),
        )
        self.assertEqual(bool(c_result.accepted), bool(oracle.accepted))
        self.assertEqual(int(c_result.mcu_state), int(oracle.state))
        return c_result, oracle

    def test_valid_command_accepted_with_control_values(self) -> None:
        c_result, _ = self._compare(make_packet(1))
        self.assertTrue(c_result.accepted)
        self.assertEqual(c_result.classification, "ACCEPTED")
        self.assertEqual(int(c_result.sequence), 1)
        self.assertEqual(int(c_result.steering_q15), -1200)
        self.assertEqual(int(c_result.throttle_q15), 6553)
        self.assertEqual(int(c_result.brake_q15), 0)
        self.assertAlmostEqual(c_result.throttle, 6553 / 32767.0, places=6)
        self.assertEqual(int(c_result.mcu_state), int(MCUState.ACTIVE))

    def test_crc_corruption_rejected_without_control_values(self) -> None:
        self._compare(make_packet(1))
        corrupted = bytearray(make_packet(2))
        corrupted[12] ^= 0x01
        c_result, _ = self._compare(bytes(corrupted))
        self.assertEqual(c_result.classification, "CRC_REJECT")
        self.assertEqual(int(c_result.throttle_q15), 0)
        self.assertEqual(int(c_result.sequence), 0)

    def test_duplicate_and_out_of_order_sequence_rejected(self) -> None:
        self._compare(make_packet(5))
        c_result, _ = self._compare(make_packet(5))
        self.assertEqual(c_result.classification, "SEQUENCE_REJECT")
        c_result, _ = self._compare(make_packet(4))
        self.assertEqual(c_result.classification, "SEQUENCE_REJECT")

    def test_stale_command_rejected(self) -> None:
        c_result, _ = self._compare(
            make_packet(2, issued_us=NOW_US - 1_000_000, valid_until_us=NOW_US - 1)
        )
        self.assertEqual(c_result.classification, "STALE_REJECT")

    def test_wrong_lease_rejected(self) -> None:
        c_result, _ = self._compare(make_packet(2, lease_id=LEASE_ID ^ 0xFFFF))
        self.assertEqual(c_result.classification, "LEASE_REJECT")

    def test_wrong_protocol_version_rejected(self) -> None:
        c_result, _ = self._compare(make_packet(2, protocol_version=PROTOCOL_VERSION + 1))
        self.assertEqual(c_result.classification, "VERSION_REJECT")

    def test_out_of_range_control_rejected(self) -> None:
        c_result, _ = self._compare(make_packet(2, throttle_q15=CONTROL_SCALE + 1))
        self.assertEqual(c_result.classification, "RANGE_REJECT")

    def test_result_age_beyond_contract_rejected(self) -> None:
        c_result, _ = self._compare(make_packet(2, result_age_ms=500))
        self.assertEqual(c_result.classification, "RANGE_REJECT")

    def test_ai_active_with_range_shift_rejected(self) -> None:
        c_result, _ = self._compare(
            make_packet(2, range_state=int(RangeShiftState.NAN_OR_INF))
        )
        self.assertEqual(c_result.classification, "RANGE_REJECT")

    def test_safe_stop_with_range_shift_is_accepted(self) -> None:
        c_result, _ = self._compare(
            make_packet(
                2,
                control_mode=int(ControlMode.SAFE_STOP),
                range_state=int(RangeShiftState.NAN_OR_INF),
                steering_q15=0,
                throttle_q15=0,
                brake_q15=CONTROL_SCALE,
            )
        )
        self.assertTrue(c_result.accepted)
        self.assertEqual(int(c_result.throttle_q15), 0)
        self.assertEqual(int(c_result.brake_q15), CONTROL_SCALE)
        self.assertEqual(int(c_result.mcu_state), int(MCUState.DEGRADED))

    def test_wrong_datagram_size_is_a_length_reject(self) -> None:
        c_result = self.library.receive_packet(self.handle, make_packet(9)[:32], NOW_US)
        self.assertEqual(c_result.classification, "LENGTH_REJECT")
        self.assertEqual(
            int(c_result.result_code), int(PacketResult.LENGTH_REJECT)
        )

    def test_heartbeat_loss_enters_failsafe_and_needs_explicit_recovery(self) -> None:
        self._compare(make_packet(1))
        state = self.library.tick(self.handle, NOW_US + 300_001)
        self.assertEqual(state, int(MCUState.FAILSAFE))
        # A command arriving in FAILSAFE must not be accepted.
        blocked = self.library.receive_packet(
            self.handle,
            make_packet(2, issued_us=NOW_US + 300_001, valid_until_us=NOW_US + 800_000),
            NOW_US + 300_001,
        )
        self.assertFalse(blocked.accepted)
        self.assertEqual(blocked.classification, "STATE_REJECT")
        self.assertEqual(self.library.clear_failsafe(self.handle), 0)
        self.assertEqual(self.library.get_state(self.handle), int(MCUState.STANDBY))

    def test_begin_session_is_required_to_rewind_the_sequence_window(self) -> None:
        self._compare(make_packet(10))
        rejected = self.library.receive_packet(self.handle, make_packet(3), NOW_US)
        self.assertEqual(rejected.classification, "SEQUENCE_REJECT")
        self.library.begin_session(self.handle, LEASE_ID, NOW_US + 10_000_000)
        accepted = self.library.receive_packet(self.handle, make_packet(3), NOW_US)
        self.assertTrue(accepted.accepted)
        self.assertEqual(self.library.get_counters(self.handle).session_count, 2)

    def test_counters_agree_with_the_oracle(self) -> None:
        self._compare(make_packet(1))
        corrupted = bytearray(make_packet(2))
        corrupted[12] ^= 0x01
        self._compare(bytes(corrupted))
        self._compare(make_packet(1))
        self._compare(make_packet(3, lease_id=0xDEAD))
        counters = self.library.get_counters(self.handle)
        self.assertEqual(counters.packets_accepted, self.oracle.counters["packets_accepted"])
        self.assertEqual(counters.crc_reject_count, self.oracle.counters["crc_reject"])
        self.assertEqual(counters.sequence_reject_count, self.oracle.counters["sequence_reject"])
        self.assertEqual(counters.lease_reject_count, self.oracle.counters["lease_reject"])
        self.assertEqual(counters.receive_call_count, 4)

    def test_classification_mapping_is_consistent(self) -> None:
        c_result, _ = self._compare(make_packet(1))
        self.assertEqual(
            c_result.classification, classification_for_result_code(int(c_result.result_code))
        )


class TestActuatorBridgeUsesCValues(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library = _library()

    def test_bridge_maps_c_accepted_control_only(self) -> None:
        from simulation.carla_virtual_actuator_bridge import VirtualActuatorBridge

        handle = self.library.create(heartbeat_timeout_us=300_000, range_failsafe_threshold=3)
        try:
            self.library.complete_boot(handle)
            self.library.arm(handle)
            self.library.begin_session(handle, LEASE_ID, NOW_US + 10_000_000)
            bridge = VirtualActuatorBridge(command_validity_ms=200)

            accepted = self.library.receive_packet(handle, make_packet(1), NOW_US)
            command = bridge.decide(accepted, now_us=1_000_000)
            self.assertAlmostEqual(command.throttle, 6553 / 32767.0, places=6)
            self.assertAlmostEqual(command.steer, -1200 / 32767.0, places=6)
            self.assertEqual(bridge.active_control_applied_count, 1)

            rejected = self.library.receive_packet(handle, make_packet(1), NOW_US)
            safe = bridge.decide(rejected, now_us=1_000_100)
            self.assertEqual(safe.throttle, 0.0)
            self.assertEqual(safe.brake, 1.0)
            self.assertEqual(bridge.safe_stop_applied_count, 1)

            expired = bridge.decide(None, now_us=1_000_100 + 500_000)
            self.assertEqual(expired.brake, 1.0)
            metrics = bridge.metrics()
            self.assertEqual(metrics["control_authority_source"], "portable_c_virtual_safety_mcu")
            self.assertFalse(metrics["physical_actuator_control_executed"])
            self.assertFalse(metrics["python_reparsed_command_for_authority"])
        finally:
            self.library.destroy(handle)


if __name__ == "__main__":
    unittest.main()

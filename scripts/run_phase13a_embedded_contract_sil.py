"""Phase 13A embedded command contract software-in-the-loop verification。"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.config import ActionStep, AgentConfig, PerceptionConfig, PlannerAction
from workers.core.edge_perception import EdgePerception
from workers.core.embedded_command_bridge import (
    CONTROL_SCALE,
    PACKET_SIZE,
    PROTOCOL_VERSION,
    CommandPacket,
    ControlMode,
    EmbeddedCommandBridge,
    MCUState,
    PacketResult,
    SafetyMCUEmulator,
    decode_packet,
    encode_packet,
)
from workers.core.range_shift_monitor import (
    RangeContract,
    RangeShiftMonitor,
    RangeShiftResult,
    RangeShiftState,
)
from workers.core.safety_gate import SafetyGate

PHASE = "Phase 13A-EMBEDDED-CONTRACT-SIL"
PASS_STATUS = (
    "Phase 13A-EMBEDDED-CONTRACT-SIL Pass — command protocol, Safety MCU state "
    "machine, range-shift rejection, stale-command rejection, and host SIL tests passed."
)
BLOCKED_STATUS = "Phase 13A-EMBEDDED-CONTRACT-SIL Blocked — one or more SIL gates failed."
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "phase13"
CONTRACT_PATH = REPO_ROOT / "embedded" / "protocol" / "command_contract.json"

BOUNDARY_FIELDS = {
    "real_mcu_verified": False,
    "hil_verified": False,
    "actuator_control_executed": False,
    "carla_benchmark_verified": False,
    "model_accuracy_verified": False,
    "ota_security_verified": False,
    "leaderboard_evaluated": False,
    "route_benchmark_verified": False,
    "infraction_benchmark_verified": False,
}


@dataclass(frozen=True)
class TestRecord:
    name: str
    passed: bool
    expected: str
    observed: str
    detail: str = ""


@dataclass(frozen=True)
class CommandRun:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_sec: float

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _next_run_dir(output_dir: Path) -> Path:
    timestamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    candidate = output_dir / timestamp
    suffix = 1
    while candidate.exists():
        candidate = output_dir / f"{timestamp}-{suffix}"
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _event(events: list[dict[str, Any]], event_type: str, **details: Any) -> None:
    events.append(
        {
            "timestamp": _utc_now().isoformat(),
            "event_type": event_type,
            **details,
        }
    )


def _run(command: list[str], *, cwd: Path) -> CommandRun:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return CommandRun(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_sec=time.perf_counter() - started,
    )


def _valid_inputs(seed: int = 13) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    raw = rng.integers(32, 224, size=(64, 96, 3), dtype=np.uint8)
    rgb = raw[:, :, ::-1]
    normalized = np.transpose(rgb.astype(np.float32) / 255.0, (2, 0, 1))[None, ...]
    activation = rng.normal(0.0, 1.0, size=(1, 16, 8, 12)).astype(np.float32)
    quantized = rng.integers(-64, 65, size=(1, 16, 8, 12), dtype=np.int8)
    return {
        "raw_input": raw,
        "normalized_input": normalized,
        "source_pixel_format": "BGR8",
        "model_color_order": "RGB",
        "input_layout": "NCHW",
        "activations": {"backbone.stage3": activation},
        "quantized_activations": {"head.int8": (quantized, -128, 127)},
        "outputs": {
            "steering": 0.12,
            "throttle": 0.25,
            "brake": 0.0,
            "ai_confidence": 0.92,
        },
        "result_age_ms": 20.0,
    }


def _record(
    records: list[TestRecord],
    events: list[dict[str, Any]],
    *,
    name: str,
    passed: bool,
    expected: Any,
    observed: Any,
    detail: str = "",
) -> None:
    record = TestRecord(name, passed, str(expected), str(observed), detail)
    records.append(record)
    _event(events, "sil_test", **asdict(record))


def _range_test(
    name: str,
    expected: RangeShiftState,
    mutate: Callable[[dict[str, Any]], None],
    records: list[TestRecord],
    events: list[dict[str, Any]],
) -> RangeShiftResult:
    monitor = RangeShiftMonitor()
    values = _valid_inputs()
    mutate(values)
    result = monitor.evaluate(**values)
    _record(
        records,
        events,
        name=name,
        passed=result.state == expected and not result.ai_result_valid,
        expected=expected.name,
        observed=result.state.name,
        detail=result.reason,
    )
    return result


def _build_c_tests(events: list[dict[str, Any]]) -> tuple[str, list[CommandRun], bool]:
    cmake = shutil.which("cmake")
    ctest = shutil.which("ctest")
    gcc = shutil.which("gcc")
    make = shutil.which("mingw32-make")
    available = all((cmake, ctest, gcc, make))
    _event(
        events,
        "c_toolchain_checked",
        cmake=cmake,
        ctest=ctest,
        gcc=gcc,
        mingw32_make=make,
        available=available,
    )
    if not available:
        return "skipped_no_portable_c_toolchain", [], False

    results: list[CommandRun] = []
    with tempfile.TemporaryDirectory(prefix="ma_vlna_phase13a_") as temporary:
        build_dir = Path(temporary) / "build"
        configure = _run(
            [
                str(cmake),
                "-S",
                str(REPO_ROOT / "embedded"),
                "-B",
                str(build_dir),
                "-G",
                "MinGW Makefiles",
                f"-DCMAKE_C_COMPILER={gcc}",
            ],
            cwd=REPO_ROOT,
        )
        results.append(configure)
        if configure.ok:
            build = _run([str(cmake), "--build", str(build_dir)], cwd=REPO_ROOT)
            results.append(build)
            if build.ok:
                tests = _run([str(ctest), "--test-dir", str(build_dir), "--output-on-failure"], cwd=REPO_ROOT)
                results.append(tests)
    passed = len(results) == 3 and all(result.ok for result in results)
    _event(events, "portable_c_tests", passed=passed, command_count=len(results))
    return ("passed" if passed else "failed"), results, True


def _contract_check(records: list[TestRecord], events: list[dict[str, Any]]) -> dict[str, Any]:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    field_names = {field["name"] for field in contract["fields"]}
    required = {
        "protocol_version",
        "message_type",
        "sequence",
        "source_timestamp_us",
        "issued_timestamp_us",
        "valid_until_us",
        "command_lease_id",
        "control_mode",
        "steering",
        "throttle",
        "brake",
        "ai_confidence",
        "range_shift_state",
        "result_age_ms",
        "flags",
        "crc32",
    }
    passed = (
        contract["protocol_version"] == PROTOCOL_VERSION
        and contract["packet_size_bytes"] == PACKET_SIZE
        and contract["byte_order"] == "little_endian"
        and required <= field_names
        and contract["crc"]["crc_offset"] == 60
    )
    _record(records, events, name="command contract schema", passed=passed, expected="version=1,size=64,little-endian", observed=f"version={contract['protocol_version']},size={contract['packet_size_bytes']},endian={contract['byte_order']}")
    return contract


def _exercise_sil(records: list[TestRecord], events: list[dict[str, Any]]) -> dict[str, Any]:
    packets_sent = 0
    encode_samples_us: list[float] = []
    decode_samples_us: list[float] = []

    config = AgentConfig(perception=PerceptionConfig(backend="dummy", model_name="dummy"))
    frame_values = _valid_inputs()
    frame = frame_values["raw_input"]
    perception = EdgePerception(config).process(frame, frame_id=13)
    perception_ok = "dummy" in perception.backend.lower() and not perception.fallback_used
    _record(
        records,
        events,
        name="edge perception vertical slice",
        passed=perception_ok,
        expected="DummyPerceptionBackend without fallback",
        observed=f"{perception.backend}, fallback={perception.fallback_used}",
    )

    gate = SafetyGate(config)
    planner_action = PlannerAction(
        plan_id="phase13a-sil",
        timestamp=_utc_now().isoformat(),
        source="local_planner",
        action_sequence=[ActionStep(action="forward", duration_sec=0.1, speed_mps=1.0, steering_deg=2.0)],
        validated=True,
    )
    gate_result = gate.validate_planner_action(planner_action)
    _record(records, events, name="MA-VLNA SafetyGate approval", passed=gate_result.approved, expected=True, observed=gate_result.approved)

    monitor = RangeShiftMonitor()
    valid_result: RangeShiftResult | None = None
    for _ in range(monitor.contract.recovery_valid_samples):
        valid_result = monitor.evaluate(**frame_values)
    assert valid_result is not None
    _record(records, events, name="initial consecutive-valid authority gate", passed=valid_result.ai_result_valid, expected=True, observed=valid_result.ai_result_valid)

    bridge = EmbeddedCommandBridge(lease_duration_us=500_000)
    mcu = SafetyMCUEmulator(heartbeat_timeout_us=300_000, range_failsafe_threshold=3)
    fsm_boot_ok = mcu.state == MCUState.BOOT and mcu.complete_boot() and mcu.state == MCUState.STANDBY
    fsm_arm_ok = mcu.arm() and mcu.state == MCUState.READY
    _record(records, events, name="FSM BOOT-STANDBY-READY", passed=fsm_boot_ok and fsm_arm_ok, expected="BOOT->STANDBY->READY", observed=mcu.state.name)

    now_us = 1_000_000
    lease_id = 0x130A
    mcu.set_command_lease(lease_id, now_us + 10_000_000)
    encode_start = time.perf_counter_ns()
    packet, encoded = bridge.build_command(
        source_timestamp_us=now_us - 20_000,
        issued_timestamp_us=now_us,
        command_lease_id=lease_id,
        safety_gate_approved=gate_result.approved,
        range_result=valid_result,
        steering=0.12,
        throttle=0.25,
        brake=0.0,
        ai_confidence=0.92,
        result_age_ms=20,
    )
    encode_samples_us.append((time.perf_counter_ns() - encode_start) / 1_000.0)
    decode_start = time.perf_counter_ns()
    response = mcu.receive(encoded, now_us=now_us)
    decode_samples_us.append((time.perf_counter_ns() - decode_start) / 1_000.0)
    packets_sent += 1
    vertical_ok = response.accepted and response.state == MCUState.ACTIVE and decode_packet(encoded).control_mode == ControlMode.AI_ACTIVE
    _record(records, events, name="valid command accepted", passed=vertical_ok, expected="ACCEPTED/ACTIVE", observed=f"{response.result.name}/{response.state.name}")

    corrupted = bytearray(encoded)
    corrupted[12] ^= 0x01
    result = mcu.receive(bytes(corrupted), now_us=now_us)
    packets_sent += 1
    _record(records, events, name="CRC failure rejected", passed=result.result == PacketResult.CRC_REJECT, expected="CRC_REJECT", observed=result.result.name)

    stale_packet, stale_bytes = bridge.build_command(
        source_timestamp_us=now_us - 1000,
        issued_timestamp_us=now_us - 1000,
        command_lease_id=lease_id,
        safety_gate_approved=True,
        range_result=valid_result,
        steering=0.0,
        throttle=0.1,
        brake=0.0,
        ai_confidence=0.9,
        result_age_ms=1,
    )
    stale_bytes = encode_packet(replace(stale_packet, valid_until_us=now_us - 1))
    result = mcu.receive(stale_bytes, now_us=now_us)
    packets_sent += 1
    _record(records, events, name="stale command rejected", passed=result.result == PacketResult.STALE_REJECT, expected="STALE_REJECT", observed=result.result.name)

    fresh_packet, fresh_bytes = bridge.build_command(
        source_timestamp_us=now_us,
        issued_timestamp_us=now_us,
        command_lease_id=lease_id,
        safety_gate_approved=True,
        range_result=valid_result,
        steering=0.0,
        throttle=0.1,
        brake=0.0,
        ai_confidence=0.9,
        result_age_ms=0,
    )
    result = mcu.receive(fresh_bytes, now_us=now_us)
    packets_sent += 1
    _record(records, events, name="fresh command accepted before sequence tests", passed=result.accepted, expected="ACCEPTED", observed=result.result.name)
    duplicate = mcu.receive(fresh_bytes, now_us=now_us)
    packets_sent += 1
    _record(records, events, name="duplicate sequence rejected", passed=duplicate.result == PacketResult.SEQUENCE_REJECT, expected="SEQUENCE_REJECT", observed=duplicate.result.name)
    out_of_order = encode_packet(replace(fresh_packet, sequence=max(0, fresh_packet.sequence - 1)))
    result = mcu.receive(out_of_order, now_us=now_us)
    packets_sent += 1
    _record(records, events, name="out-of-order sequence rejected", passed=result.result == PacketResult.SEQUENCE_REJECT, expected="SEQUENCE_REJECT", observed=result.result.name)

    lease_packet, _ = bridge.build_command(
        source_timestamp_us=now_us,
        issued_timestamp_us=now_us,
        command_lease_id=lease_id,
        safety_gate_approved=True,
        range_result=valid_result,
        steering=0.0,
        throttle=0.1,
        brake=0.0,
        ai_confidence=0.9,
        result_age_ms=0,
    )
    mcu.set_command_lease(lease_id, now_us - 1)
    result = mcu.receive(encode_packet(lease_packet), now_us=now_us)
    packets_sent += 1
    _record(records, events, name="expired lease rejected", passed=result.result == PacketResult.LEASE_REJECT, expected="LEASE_REJECT", observed=result.result.name)
    mcu.set_command_lease(lease_id, now_us + 10_000_000)

    mismatch_packet = replace(lease_packet, protocol_version=PROTOCOL_VERSION + 1, sequence=lease_packet.sequence + 1)
    result = mcu.receive(encode_packet(mismatch_packet), now_us=now_us)
    packets_sent += 1
    _record(records, events, name="protocol mismatch rejected", passed=result.result == PacketResult.VERSION_REJECT, expected="VERSION_REJECT", observed=result.result.name)

    control_packet = replace(lease_packet, sequence=lease_packet.sequence + 2, throttle_q15=CONTROL_SCALE + 1)
    result = mcu.receive(encode_packet(control_packet), now_us=now_us)
    packets_sent += 1
    _record(records, events, name="out-of-range control rejected", passed=result.result == PacketResult.RANGE_REJECT, expected="RANGE_REJECT", observed=result.result.name)

    heartbeat_state = mcu.tick(now_us=now_us + 300_001)
    _record(records, events, name="heartbeat loss enters FAILSAFE", passed=heartbeat_state == MCUState.FAILSAFE, expected="FAILSAFE", observed=heartbeat_state.name)
    recovery_ok = mcu.clear_failsafe() and mcu.arm()
    mcu.set_command_lease(lease_id, now_us + 10_000_000)
    _record(records, events, name="explicit FAILSAFE recovery", passed=recovery_ok and mcu.state == MCUState.READY, expected="STANDBY->READY", observed=mcu.state.name)

    range_results = [
        _range_test("NaN/Inf input rejected", RangeShiftState.NAN_OR_INF, lambda values: values["normalized_input"].__setitem__((0, 0, 0, 0), np.nan), records, events),
        _range_test("normalization mismatch rejected", RangeShiftState.NORMALIZATION_MISMATCH, lambda values: values.__setitem__("normalized_input", values["normalized_input"] * 255.0), records, events),
        _range_test("activation saturation rejected", RangeShiftState.QUANTIZATION_SATURATION, lambda values: values.__setitem__("quantized_activations", {"head.int8": (np.full((1, 16, 8, 12), 127, dtype=np.int8), -128, 127)}), records, events),
        _range_test("input range shift rejected", RangeShiftState.INPUT_RANGE_SHIFT, lambda values: values.__setitem__("raw_input", values["raw_input"].astype(np.float32) + 300.0), records, events),
        _range_test("color order mismatch rejected", RangeShiftState.COLOR_ORDER_MISMATCH, lambda values: values.__setitem__("model_color_order", "BGR"), records, events),
        _range_test("activation percentile shift rejected", RangeShiftState.ACTIVATION_RANGE_SHIFT, lambda values: values.__setitem__("activations", {"backbone.stage3": np.full((1, 16, 8, 12), 20.0, dtype=np.float32)}), records, events),
        _range_test("output range invalid rejected", RangeShiftState.OUTPUT_RANGE_INVALID, lambda values: values["outputs"].__setitem__("throttle", 1.5), records, events),
    ]
    nan_result, normalization_result, saturation_result = range_results[:3]

    recovery_monitor = RangeShiftMonitor()
    bad_values = _valid_inputs()
    bad_values["normalized_input"][0, 0, 0, 0] = np.nan
    initial_failure = recovery_monitor.evaluate(**bad_values)
    recovery_samples = [recovery_monitor.evaluate(**_valid_inputs()) for _ in range(3)]
    recovery_passed = (
        not initial_failure.ai_result_valid
        and not recovery_samples[0].ai_result_valid
        and not recovery_samples[1].ai_result_valid
        and recovery_samples[2].ai_result_valid
        and recovery_samples[2].recovered
    )
    _record(records, events, name="range-shift recovery requires consecutive valid samples", passed=recovery_passed, expected="invalid,invalid,valid on sample 3", observed=",".join(item.state.name for item in recovery_samples))

    for range_result in (nan_result, normalization_result, saturation_result):
        _, safe_bytes = bridge.build_command(
            source_timestamp_us=now_us,
            issued_timestamp_us=now_us,
            command_lease_id=lease_id,
            safety_gate_approved=True,
            range_result=range_result,
            steering=0.4,
            throttle=0.5,
            brake=0.0,
            ai_confidence=0.9,
            result_age_ms=10,
        )
        decoded = decode_packet(safe_bytes)
        mode_safe = decoded.control_mode == ControlMode.SAFE_STOP and decoded.throttle == 0.0 and decoded.brake == 1.0
        response = mcu.receive(safe_bytes, now_us=now_us)
        packets_sent += 1
        _record(records, events, name=f"bridge blocks ACTIVE for {range_result.state.name}", passed=mode_safe and response.accepted, expected="SAFE_STOP accepted", observed=f"{ControlMode(decoded.control_mode).name}/{response.state.name}")

    range_policy_ok = mcu.state == MCUState.FAILSAFE and mcu.counters["range_reject_count"] == 3
    _record(records, events, name="range policy DEGRADED-to-FAILSAFE", passed=range_policy_ok, expected="3 rejects -> FAILSAFE", observed=f"{mcu.counters['range_reject_count']} rejects -> {mcu.state.name}")

    total_failures = sum(1 for record in records if not record.passed)
    expected_rejects = {
        "crc_reject": 1,
        "stale_reject": 1,
        "sequence_reject": 2,
        "lease_reject": 1,
        "version_reject": 1,
        "range_reject": 1,
    }
    observed_rejects = {
        "crc_reject": mcu.counters["crc_reject"],
        "stale_reject": mcu.counters["stale_reject"],
        "sequence_reject": mcu.counters["sequence_reject"],
        "lease_reject": mcu.counters["lease_reject"],
        "version_reject": mcu.counters["version_reject"],
        "range_reject": mcu.counters["range_reject"],
    }
    false_accept_count = sum(max(0, observed_rejects[name] - count) for name, count in expected_rejects.items())
    false_reject_count = sum(max(0, count - observed_rejects[name]) for name, count in expected_rejects.items())

    return {
        "packets_sent": packets_sent,
        "packets_accepted": mcu.counters["packets_accepted"],
        "crc_reject_count": mcu.counters["crc_reject"],
        "stale_reject_count": mcu.counters["stale_reject"],
        "sequence_reject_count": mcu.counters["sequence_reject"],
        "lease_reject_count": mcu.counters["lease_reject"],
        "range_reject_count": mcu.counters["range_reject_count"],
        "protocol_version_reject_count": mcu.counters["version_reject"],
        "control_range_reject_count": mcu.counters["range_reject"],
        "failsafe_entry_count": mcu.counters["failsafe_entry_count"],
        "failsafe_recovery_count": mcu.counters["failsafe_recovery_count"],
        "range_shift_detection_count": sum(not result.sample_valid for result in range_results)
        + recovery_monitor.range_shift_detection_count,
        "false_accept_count": false_accept_count,
        "false_reject_count": false_reject_count,
        "command_encode_us": round(sum(encode_samples_us) / len(encode_samples_us), 3),
        "command_decode_us": round(sum(decode_samples_us) / len(decode_samples_us), 3),
        "python_test_failure_count": total_failures,
        "fsm_final_state": mcu.state.name,
        "watchdog_kick_allowed": mcu.watchdog_kick_allowed,
    }


def _commands_text(argv: list[str], c_results: list[CommandRun]) -> str:
    lines = ["# Phase 13A commands", "python " + " ".join(argv), ""]
    for result in c_results:
        lines.extend(
            [
                "$ " + subprocess.list2cmdline(result.command),
                f"exit_code={result.returncode} duration_sec={result.duration_sec:.3f}",
                result.stdout.strip(),
                result.stderr.strip(),
                "",
            ]
        )
    return "\n".join(line for line in lines if line is not None).rstrip() + "\n"


def _readme(run_dir: Path, status: str, c_status: str) -> str:
    return f"""# Phase 13A Embedded Contract SIL Evidence

Status: `{status}`

- Protocol: version `{PROTOCOL_VERSION}`, `{PACKET_SIZE}` bytes, little-endian, CRC-32/IEEE.
- Portable C build/CTest: `{c_status}`.
- Evidence directory: `{run_dir.relative_to(REPO_ROOT).as_posix()}`.

This is host software-in-the-loop evidence only. It does not claim real MCU or
HIL validation, actuator control, CARLA benchmark, model accuracy, or OTA/security validation.
"""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13A embedded contract SIL")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    actual_argv = argv if argv is not None else sys.argv[1:]
    args = parse_args(actual_argv)
    output_dir = args.output_dir if args.output_dir.is_absolute() else REPO_ROOT / args.output_dir
    run_dir = _next_run_dir(output_dir)
    events: list[dict[str, Any]] = []
    records: list[TestRecord] = []

    contract = _contract_check(records, events)
    metrics = _exercise_sil(records, events)
    c_status, c_results, c_toolchain_available = _build_c_tests(events)
    c_gate_passed = c_status == "passed" or not c_toolchain_available
    all_python_passed = all(record.passed for record in records)
    boundary_verified = all(value is False for value in BOUNDARY_FIELDS.values())
    overall_passed = (
        all_python_passed
        and c_gate_passed
        and metrics["false_accept_count"] == 0
        and metrics["false_reject_count"] == 0
        and boundary_verified
    )
    status = PASS_STATUS if overall_passed else BLOCKED_STATUS

    summary = {
        "phase": PHASE,
        "status": status,
        "passed": overall_passed,
        "created_at_utc": _utc_now().isoformat(),
        "protocol_version": PROTOCOL_VERSION,
        "packet_size_bytes": PACKET_SIZE,
        "packet_endian": "little_endian",
        "crc_algorithm": contract["crc"]["algorithm"],
        "fsm_test_result": "passed" if all(record.passed for record in records if record.name.startswith("FSM") or "FAILSAFE" in record.name or "range policy" in record.name) else "failed",
        "range_shift_tests_passed": all(record.passed for record in records if "range" in record.name.lower() or "NaN" in record.name or "normalization" in record.name or "saturation" in record.name),
        "portable_c_toolchain_available": c_toolchain_available,
        "portable_c_build_test_status": c_status,
        "portable_c_firmware_pass_claimed": False,
        "sil_test_count": len(records),
        "sil_test_passed_count": sum(record.passed for record in records),
        "sil_test_failed_count": sum(not record.passed for record in records),
        "tests": [asdict(record) for record in records],
        "metrics": metrics,
        "range_contract": RangeContract().to_dict(),
        "generated_evidence_git_policy": "ignored_local_only",
        **BOUNDARY_FIELDS,
    }
    manifest = {
        "phase": PHASE,
        "status": status,
        "created_at_utc": summary["created_at_utc"],
        "repository_root": str(REPO_ROOT),
        "run_dir": str(run_dir),
        "python_executable": sys.executable,
        "contract_path": str(CONTRACT_PATH),
        "output_files": ["manifest.json", "summary.json", "events.jsonl", "commands.txt", "README.md"],
        "portable_c_commands": [result.command for result in c_results],
        "boundary": BOUNDARY_FIELDS,
    }

    _write_json(run_dir / "manifest.json", manifest)
    _write_json(run_dir / "summary.json", summary)
    (run_dir / "events.jsonl").write_text("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events), encoding="utf-8")
    (run_dir / "commands.txt").write_text(_commands_text([str(Path(__file__).resolve().relative_to(REPO_ROOT)), *actual_argv], c_results), encoding="utf-8")
    (run_dir / "README.md").write_text(_readme(run_dir, status, c_status), encoding="utf-8")

    print(status)
    print(f"evidence_dir={run_dir}")
    print(f"protocol_version={PROTOCOL_VERSION}")
    print(f"packet_size_bytes={PACKET_SIZE}")
    print(f"sil_tests={summary['sil_test_passed_count']}/{summary['sil_test_count']}")
    print(f"portable_c_build_test_status={c_status}")
    return 0 if overall_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

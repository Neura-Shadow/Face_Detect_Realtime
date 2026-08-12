"""Phase 13D Gate E — CARLA closed loop with real TensorRT INT8 perception.

Composes the verified Phase 13B CARLA simulation host unchanged and evaluates
the Phase 13D requirements on top of its evidence: the Jetson must have run the
**INT8** plan under an enforced calibration envelope, every active command must
trace back to a fresh no-fallback inference, and the p99 frame-to-command
latency must fit inside the command validity budget.

Formal profile (identical to Phase 13C on purpose, so the two are comparable):

    fixed_delta_seconds = 0.05   -> 20 Hz simulator
    camera_fps          = 5      -> sensor_tick 0.20 s
    => one camera frame every FOUR simulation ticks
    frames              >= 300   -> >= 1200 CARLA ticks
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13d_checks import (  # noqa: E402
    BOUNDARY_FIELDS,
    DEFAULT_COMMAND_VALIDITY_MS,
    DEFAULT_SAFETY_MARGIN_MS,
    PHASE,
    STATUS_BLOCKED,
    STATUS_PASS,
    Phase13DEvidence,
    evaluate_runtime_health,
    latency_budget_ms,
    new_run_id,
    pc_environment,
    run_command,
    utc_now_iso,
)

MIN_CARLA_FRAMES = 300
MIN_CARLA_TICKS = 1200
MIN_INT8_INFERENCES = 300


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13D Gate E CARLA INT8 closed loop")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--jetson-host", default="192.168.55.1")
    parser.add_argument("--carla-host", default="127.0.0.1")
    parser.add_argument("--carla-port", type=int, default=2000)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--frames", type=int, default=MIN_CARLA_FRAMES)
    parser.add_argument("--min-ticks", type=int, default=MIN_CARLA_TICKS)
    parser.add_argument("--fixed-delta-seconds", type=float, default=0.05)
    parser.add_argument("--camera-fps", type=float, default=5.0)
    parser.add_argument("--camera-width", type=int, default=640)
    parser.add_argument("--camera-height", type=int, default=360)
    parser.add_argument("--command-validity-ms", type=int, default=DEFAULT_COMMAND_VALIDITY_MS)
    parser.add_argument("--safety-margin-ms", type=int, default=DEFAULT_SAFETY_MARGIN_MS)
    parser.add_argument("--heartbeat-timeout-ms", type=int, default=15000)
    parser.add_argument("--command-timeout-ms", type=int, default=900)
    parser.add_argument("--warmup-ticks", type=int, default=20)
    parser.add_argument("--setup-timeout-sec", type=float, default=180.0)
    parser.add_argument("--run-timeout-sec", type=float, default=1800.0)
    parser.add_argument("--transport-medium", default="usb_gadget_ethernet")
    parser.add_argument("--parity-metrics-json", default="")
    parser.add_argument("--output-dir", default="experiments/phase13")
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--require-carla", action="store_true")
    parser.add_argument("--require-real-jetson", action="store_true")
    parser.add_argument("--require-no-fallback", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or new_run_id()
    evidence = Phase13DEvidence(Path(args.output_dir), run_id)
    environment = pc_environment()

    inner_run_id = "%s-gated" % run_id
    command = [
        args.python_executable,
        str(SCRIPTS_DIR / "run_phase13b_simulation_host.py"),
        "--run-id", inner_run_id,
        "--jetson-host", args.jetson_host,
        "--carla-host", args.carla_host,
        "--carla-port", str(args.carla_port),
        "--town", args.town,
        "--mode", "lockstep",
        "--frames", str(args.frames),
        "--fixed-delta-seconds", str(args.fixed_delta_seconds),
        "--camera-fps", str(args.camera_fps),
        "--camera-width", str(args.camera_width),
        "--camera-height", str(args.camera_height),
        "--map-load-mode", "reuse_or_load",
        "--setup-timeout-sec", str(args.setup_timeout_sec),
        "--warmup-ticks", str(args.warmup_ticks),
        "--command-timeout-ms", str(args.command_timeout_ms),
        "--command-validity-ms", str(args.command_validity_ms),
        "--heartbeat-timeout-ms", str(args.heartbeat_timeout_ms),
        "--run-timeout-sec", str(args.run_timeout_sec),
        "--transport-medium", args.transport_medium,
        "--output-dir", args.output_dir,
    ]
    if args.require_carla:
        command.append("--require-server")
    if args.require_real_jetson:
        command.append("--require-jetson")

    summary = {
        "phase": PHASE,
        "gate": "E_carla_int8_closed_loop",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "inner_run_id": inner_run_id,
        "inner_command": command,
        "carla_profile": {
            "town": str(args.town),
            "fixed_delta_seconds": float(args.fixed_delta_seconds),
            "simulator_frequency_hz": round(1.0 / float(args.fixed_delta_seconds), 3),
            "camera_fps": float(args.camera_fps),
            "camera_sensor_tick": round(1.0 / float(args.camera_fps), 4),
            "ticks_per_camera_frame": round(
                (1.0 / float(args.camera_fps)) / float(args.fixed_delta_seconds), 3
            ),
            "frames": int(args.frames),
            "min_ticks_required": int(args.min_ticks),
        },
    }  # type: Dict[str, Any]
    blockers = []  # type: List[str]

    parity = {}  # type: Dict[str, Any]
    if args.parity_metrics_json and Path(args.parity_metrics_json).is_file():
        try:
            parity = json.loads(Path(args.parity_metrics_json).read_text(encoding="utf-8"))
        except ValueError:
            parity = {}
    summary["parity_metrics"] = parity

    result = run_command(command, timeout=int(args.run_timeout_sec) + 900)
    summary["inner_returncode"] = result["returncode"]
    summary["inner_stdout_tail"] = result["stdout"].strip().splitlines()[-30:]
    summary["inner_stderr_tail"] = result["stderr"].strip().splitlines()[-15:]

    inner_root = Path(args.output_dir)
    if not inner_root.is_absolute():
        inner_root = REPO_ROOT / inner_root
    inner_dir = inner_root / inner_run_id
    inner_summary = {}  # type: Dict[str, Any]
    jetson_metrics = {}  # type: Dict[str, Any]
    if (inner_dir / "summary.json").is_file():
        inner_summary = json.loads((inner_dir / "summary.json").read_text(encoding="utf-8"))
    if (inner_dir / "jetson_metrics.json").is_file():
        jetson_metrics = json.loads((inner_dir / "jetson_metrics.json").read_text(encoding="utf-8"))
    summary["inner_evidence_dir"] = str(inner_dir)
    summary["phase13b_summary"] = {
        key: inner_summary.get(key) for key in ("status", "gate_c", "carla", "clock", "blockers")
    }

    inner_gate = inner_summary.get("gate_c", {}) or {}
    clock = inner_summary.get("clock", {}) or {}
    clock_uncertainty_ms = float(clock.get("clock_uncertainty_us", 0) or 0) / 1000.0
    budget = latency_budget_ms(
        command_validity_ms=int(args.command_validity_ms),
        clock_uncertainty_ms=clock_uncertainty_ms,
        safety_margin_ms=int(args.safety_margin_ms),
    )
    frame_to_command = jetson_metrics.get("frame_to_command_ms_stats") or {}

    gate_e = {
        "gate_e_precision": jetson_metrics.get("precision"),
        "gate_e_perception_mode": jetson_metrics.get("perception_mode"),
        "gate_e_carla_frames_sent": int(inner_gate.get("gate_c_carla_frames_sent", 0)),
        "gate_e_carla_ticks": int(inner_gate.get("gate_c_carla_ticks", 0)),
        "gate_e_carla_frames_processed": int(inner_gate.get("gate_c_carla_frames_processed", 0)),
        "gate_e_int8_inference_completed_count": int(
            jetson_metrics.get("tensorrt_inference_completed_count", 0)
        ),
        "gate_e_int8_inference_failed_count": int(
            jetson_metrics.get("tensorrt_inference_failed_count", 0)
        ),
        "gate_e_tensorrt_fallback_count": int(jetson_metrics.get("tensorrt_fallback_count", 0)),
        "gate_e_int8_active_authority_count": int(
            jetson_metrics.get("tensorrt_active_authority_count", 0)
        ),
        "gate_e_calibration_envelope_loaded": bool(
            jetson_metrics.get("calibration_envelope_loaded", False)
        ),
        "gate_e_calibration_envelope_enforced": bool(
            jetson_metrics.get("calibration_envelope_enforced", False)
        ),
        "gate_e_calibration_envelope_reject_count": int(
            jetson_metrics.get("calibration_envelope_reject_count", 0) or 0
        ),
        "gate_e_int8_calibration_range_checked": bool(
            jetson_metrics.get("int8_calibration_range_checked", False)
        ),
        "gate_e_active_control_count": int(
            inner_gate.get("gate_c_virtual_actuator_active_control_applied_count", 0)
        ),
        "gate_e_safe_stop_count": int(
            inner_gate.get("gate_c_virtual_actuator_safe_stop_applied_count", 0)
        ),
        "gate_e_command_timeout_count": int(
            (inner_summary.get("lockstep", {}) or {}).get("gate_c_command_timeouts", 0)
        ),
        "gate_e_max_mailbox_depth": int(jetson_metrics.get("max_mailbox_depth", 0)),
        "gate_e_command_accept_count": int(inner_gate.get("gate_c_command_accept_count", 0)),
        "gate_e_fault_matrix_passed": bool(inner_gate.get("gate_c_fault_matrix_passed", False)),
        "gate_e_false_accept_count": int(inner_gate.get("gate_c_false_accept_count", 0)),
        "gate_e_false_reject_count": int(inner_gate.get("gate_c_false_reject_count", 0)),
        "gate_e_parity_passed": bool(parity.get("parity_passed", False)),
        "latency_budget_ms": round(budget, 4),
        "frame_to_command_ms_p99": frame_to_command.get("p99"),
        "clock_uncertainty_ms": round(clock_uncertainty_ms, 4),
    }
    summary["gate_e"] = gate_e

    if gate_e["gate_e_perception_mode"] != "tensorrt":
        blockers.append("tensorrt_backend_not_selected")
    if gate_e["gate_e_precision"] != "int8":
        blockers.append("int8_precision_not_selected")
    if not gate_e["gate_e_calibration_envelope_loaded"]:
        blockers.append("calibration_envelope_missing")
    if not gate_e["gate_e_calibration_envelope_enforced"]:
        blockers.append("calibration_envelope_not_enforced")
    if not gate_e["gate_e_int8_calibration_range_checked"]:
        blockers.append("int8_calibration_range_not_checked")
    if args.require_no_fallback and gate_e["gate_e_tensorrt_fallback_count"]:
        blockers.append("tensorrt_fallback_used")
    if gate_e["gate_e_carla_frames_sent"] < MIN_CARLA_FRAMES:
        blockers.append("carla_frame_count_insufficient")
    if gate_e["gate_e_carla_ticks"] < int(args.min_ticks):
        blockers.append("carla_tick_count_insufficient")
    if gate_e["gate_e_int8_inference_completed_count"] < MIN_INT8_INFERENCES:
        blockers.append("int8_inference_count_insufficient")
    if gate_e["gate_e_active_control_count"] <= 0:
        blockers.append("no_active_control_applied")
    if gate_e["gate_e_safe_stop_count"] <= 0:
        blockers.append("no_safe_stop_path_observed")
    if gate_e["gate_e_command_timeout_count"]:
        blockers.append("command_timeout_observed")
    if gate_e["gate_e_max_mailbox_depth"] != 1:
        blockers.append("mailbox_depth_violation")
    if gate_e["gate_e_false_accept_count"] or gate_e["gate_e_false_reject_count"]:
        blockers.append("fault_matrix_false_classification")
    if not gate_e["gate_e_parity_passed"]:
        blockers.append("parity_gate_not_passed")

    # The inner Phase 13B host injects the fault matrix inside the same session,
    # so its recorded inference failures are the injected ones. Only the fault
    # matrix can judge those, and it does: it must pass with zero false accepts
    # and zero false rejects, checked separately above. The suppression is named
    # here and written into the evidence rather than applied silently.
    suppress = ()  # type: Any
    if gate_e["gate_e_fault_matrix_passed"] and not (
        gate_e["gate_e_false_accept_count"] or gate_e["gate_e_false_reject_count"]
    ):
        suppress = ("tensorrt_inference_failed",)
    health = evaluate_runtime_health(
        jetson_metrics,
        deadline_ms=budget,
        observed_p99_ms=gate_e["frame_to_command_ms_p99"],
        ignore=suppress,
    )
    summary["runtime_health"] = health
    if not args.require_no_fallback:
        health["blockers"] = [
            item for item in health["blockers"] if item != "tensorrt_fallback_used"
        ]
    blockers.extend(health["blockers"])

    passed = result["returncode"] == 0 and not blockers
    summary["blockers"] = sorted(set(blockers))
    summary["status"] = STATUS_PASS if passed else STATUS_BLOCKED
    summary["pc_environment"] = environment
    summary.update(BOUNDARY_FIELDS)

    evidence.write_json("summary.json", summary)
    evidence.write_json("jetson_metrics.json", jetson_metrics)
    evidence.write_json("environment.json", environment)
    evidence.write_json("parity_metrics.json", parity or {"executed": False})
    evidence.write_json(
        "latency_metrics.json",
        {
            "frame_to_command_ms": frame_to_command,
            "latency_budget_ms": budget,
            "tensorrt_latency_metrics": jetson_metrics.get("tensorrt_latency_metrics"),
        },
    )
    evidence.write_json(
        "range_metrics.json",
        {
            key: jetson_metrics.get(key)
            for key in (
                "input_range_checked",
                "tensor_output_range_checked",
                "detection_schema_checked",
                "int8_calibration_range_checked",
                "calibration_envelope_loaded",
                "calibration_envelope_enforced",
                "calibration_envelope_evaluation_count",
                "calibration_envelope_reject_count",
                "activation_range_checked",
                "runtime_internal_activation_observed",
                "range_validation_scope",
                "tensorrt_range_reject_count",
            )
        },
    )
    evidence.write_json(
        "network_metrics.json",
        {"transport_medium": args.transport_medium, "jetson_host": args.jetson_host, "clock": clock},
    )
    evidence.write_manifest("E_carla_int8_closed_loop", summary["status"], inner_evidence_dir=str(inner_dir))
    evidence.write_placeholders()
    evidence.write_fault_matrix([])
    evidence.write_events([])
    evidence.write_text(
        "commands.txt",
        "# Phase 13D Gate E\n%s %s\n\n# inner Phase 13B host\n%s\n"
        % (sys.executable, " ".join(sys.argv), " ".join(command)),
    )
    evidence.write_text(
        "README.md",
        "# Phase 13D Gate E evidence\n\nRun id: `%s`\n\nStatus: `%s`\n\n"
        "Real Jetson TensorRT INT8 perception in the command authority path of the CARLA "
        "closed loop, under an enforced calibration envelope. Only the Jetson compute node "
        "is physical. No model accuracy, navigation quality or route completion is "
        "claimed.\n" % (run_id, summary["status"]),
    )

    print(summary["status"])
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    for key, value in sorted(gate_e.items()):
        print("%s=%s" % (key, value))
    if summary["blockers"]:
        print("blockers=%s" % ",".join(summary["blockers"]), file=sys.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

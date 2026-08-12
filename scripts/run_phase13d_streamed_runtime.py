"""Phase 13D Gate D — streamed INT8 runtime over the Phase 13B bridge.

Composes the verified Phase 13B transport rather than forking it: the same
``JilSessionDriver``, the same JILF frame path, the same unchanged Phase 13A
64-byte command, the same C Virtual Safety MCU and the same JILA ACK. The only
differences from Phase 13C Gate C are that the Jetson node runs the **INT8**
plan and that it is gated by the calibration envelope, so a frame drawn from
outside the calibration distribution loses AI authority instead of being
quantized with the wrong scales and trusted anyway.

Gate D proves streamed INT8 inference; it does not involve CARLA.
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

from run_phase13b_jil_checks import JilSessionDriver  # noqa: E402
from run_phase13d_checks import (  # noqa: E402
    BOUNDARY_FIELDS,
    DEFAULT_COMMAND_VALIDITY_MS,
    DEFAULT_SAFETY_MARGIN_MS,
    PHASE,
    STATUS_BLOCKED,
    STATUS_RUNTIME_PASS,
    Phase13DEvidence,
    evaluate_runtime_health,
    latency_budget_ms,
    new_run_id,
    pc_environment,
    run_regressions,
    utc_now_iso,
)

MIN_STREAMED_INFERENCES = 300


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13D Gate D streamed INT8 runtime")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--jetson-host", default="192.168.55.1")
    parser.add_argument("--frame-port", type=int, default=13510)
    parser.add_argument("--control-port", type=int, default=13513)
    parser.add_argument("--command-port", type=int, default=13511)
    parser.add_argument("--ack-port", type=int, default=13512)
    parser.add_argument("--pc-bind-host", default="0.0.0.0")
    parser.add_argument("--mcu-library", default="")
    parser.add_argument("--frames", type=int, default=MIN_STREAMED_INFERENCES)
    parser.add_argument("--camera-width", type=int, default=640)
    parser.add_argument("--camera-height", type=int, default=360)
    parser.add_argument("--command-validity-ms", type=int, default=DEFAULT_COMMAND_VALIDITY_MS)
    parser.add_argument("--safety-margin-ms", type=int, default=DEFAULT_SAFETY_MARGIN_MS)
    parser.add_argument("--heartbeat-timeout-ms", type=int, default=15000)
    parser.add_argument("--frame-interval-sec", type=float, default=0.1)
    parser.add_argument("--transport-medium", default="usb_gadget_ethernet")
    parser.add_argument("--parity-metrics-json", default="")
    parser.add_argument("--output-dir", default="experiments/phase13")
    parser.add_argument("--require-real-jetson", action="store_true")
    parser.add_argument("--require-no-fallback", action="store_true")
    parser.add_argument("--require-parity", action="store_true")
    parser.add_argument("--skip-fault-matrix", action="store_true")
    parser.add_argument("--skip-regressions", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or new_run_id()
    evidence = Phase13DEvidence(Path(args.output_dir), run_id)
    environment = pc_environment()

    driver = JilSessionDriver(
        run_id=run_id,
        jetson_host=args.jetson_host,
        frame_port=args.frame_port,
        control_port=args.control_port,
        command_port=args.command_port,
        ack_port=args.ack_port,
        pc_bind_host=args.pc_bind_host,
        mcu_library_path=args.mcu_library or None,
        heartbeat_timeout_ms=args.heartbeat_timeout_ms,
        command_validity_ms=args.command_validity_ms,
        camera_width=args.camera_width,
        camera_height=args.camera_height,
    )

    summary = {
        "phase": PHASE,
        "gate": "D_streamed_int8_runtime",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "transport_medium": args.transport_medium,
    }  # type: Dict[str, Any]
    jetson_evidence = {"metrics": {}, "events": []}  # type: Dict[str, Any]
    blockers = []  # type: List[str]
    status = STATUS_BLOCKED
    exit_code = 1

    parity = {}  # type: Dict[str, Any]
    if args.parity_metrics_json and Path(args.parity_metrics_json).is_file():
        try:
            parity = json.loads(Path(args.parity_metrics_json).read_text(encoding="utf-8"))
        except ValueError:
            parity = {}
    summary["parity_metrics"] = parity
    if args.require_parity and not parity.get("parity_passed"):
        blockers.append("parity_gate_not_passed")

    regressions = (
        {"regressions_skipped": True} if args.skip_regressions else run_regressions()
    )
    summary["regressions"] = regressions
    if not args.skip_regressions:
        for key in (
            "phase13a_unit_regression_passed",
            "phase13b_unit_regression_passed",
            "phase13c_unit_regression_passed",
        ):
            if not regressions.get(key):
                blockers.append(key.replace("_passed", "_failed"))

    try:
        mcu = driver.start_virtual_mcu()
        summary["virtual_mcu"] = mcu
        if not mcu.get("ok"):
            raise RuntimeError("virtual safety MCU could not start")

        hello = driver.connect_control()
        jetson_env = dict(hello.get("environment", {}))
        summary["jetson_environment"] = jetson_env
        if args.require_real_jetson and not jetson_env.get("real_jetson_detected", False):
            blockers.append("jetson_environment_mismatch")
            raise RuntimeError("real Jetson required but not detected")

        runtime_pc_sha = environment.get("runtime_pc_git_sha", "")
        runtime_jetson_sha = jetson_env.get("runtime_jetson_git_sha", "")
        summary["runtime_pc_git_sha"] = runtime_pc_sha
        summary["runtime_jetson_git_sha"] = runtime_jetson_sha
        summary["runtime_git_sha_match"] = bool(runtime_pc_sha) and runtime_pc_sha == runtime_jetson_sha
        if args.require_real_jetson and not summary["runtime_git_sha_match"]:
            blockers.append("git_sha_mismatch")
            raise RuntimeError("runtime git SHA mismatch between PC and Jetson")

        summary["clock"] = driver.synchronise_clocks()
        driver.start_session(start_frame_server=True)
        if not driver.connect_frames():
            blockers.append("frame_transport_failed")
            raise RuntimeError("frame transport could not be established")

        summary["frames"] = driver.publish_synthetic_frames(
            int(args.frames), interval_sec=float(args.frame_interval_sec), wait_timeout_sec=600.0
        )
        if not args.skip_fault_matrix:
            summary["phase13b_fault_matrix"] = driver.run_fault_matrix("D13D")

        jetson_evidence = driver.collect_jetson_evidence()
        metrics = jetson_evidence["metrics"]

        clock_uncertainty_ms = float(summary["clock"].get("clock_uncertainty_us", 0)) / 1000.0
        budget = latency_budget_ms(
            command_validity_ms=int(args.command_validity_ms),
            clock_uncertainty_ms=clock_uncertainty_ms,
            safety_margin_ms=int(args.safety_margin_ms),
        )
        frame_to_command = metrics.get("frame_to_command_ms_stats") or {}
        fault = summary.get("phase13b_fault_matrix", {}) or {}

        gate_d = {
            "gate_d_precision": metrics.get("precision"),
            "gate_d_perception_mode": metrics.get("perception_mode"),
            "gate_d_streamed_inference_count": int(
                metrics.get("tensorrt_inference_completed_count", 0)
            ),
            "gate_d_valid_int8_inference_count": int(
                metrics.get("tensorrt_active_authority_count", 0)
            ),
            "gate_d_tensorrt_warmup_count": int(metrics.get("tensorrt_warmup_count", 0) or 0),
            "gate_d_frames_received": int(metrics.get("frames_received", 0)),
            "gate_d_frames_decoded": int(metrics.get("frames_decoded", 0)),
            "gate_d_frames_processed": int(metrics.get("frames_processed", 0)),
            "gate_d_max_mailbox_depth": int(metrics.get("max_mailbox_depth", 0)),
            "gate_d_mailbox_drop_count": int(metrics.get("frames_dropped_mailbox", 0)),
            "gate_d_tensorrt_fallback_count": int(metrics.get("tensorrt_fallback_count", 0)),
            "gate_d_tensorrt_inference_failed_count": int(
                metrics.get("tensorrt_inference_failed_count", 0)
            ),
            "gate_d_tensorrt_range_reject_count": int(
                metrics.get("tensorrt_range_reject_count", 0)
            ),
            "gate_d_calibration_envelope_loaded": bool(
                metrics.get("calibration_envelope_loaded", False)
            ),
            "gate_d_calibration_envelope_enforced": bool(
                metrics.get("calibration_envelope_enforced", False)
            ),
            "gate_d_calibration_envelope_reject_count": int(
                metrics.get("calibration_envelope_reject_count", 0) or 0
            ),
            "gate_d_int8_calibration_range_checked": bool(
                metrics.get("int8_calibration_range_checked", False)
            ),
            "gate_d_command_accept_count": int(driver.server.command_accept_count),
            "gate_d_command_reject_count": int(driver.server.command_reject_count),
            "gate_d_valid_acks_received": int(metrics.get("valid_acks_received", 0)),
            "gate_d_fault_matrix_passed": bool(fault.get("fault_matrix_passed", False)),
            "gate_d_false_accept_count": int(fault.get("false_accept_count", 0)),
            "gate_d_false_reject_count": int(fault.get("false_reject_count", 0)),
            "gate_d_parity_passed": bool(parity.get("parity_passed", False)),
            "latency_budget_ms": round(budget, 4),
            "frame_to_command_ms_p99": frame_to_command.get("p99"),
        }
        summary["gate_d"] = gate_d

        if gate_d["gate_d_perception_mode"] != "tensorrt":
            blockers.append("tensorrt_backend_not_selected")
        if gate_d["gate_d_precision"] != "int8":
            blockers.append("int8_precision_not_selected")
        if not gate_d["gate_d_calibration_envelope_loaded"]:
            blockers.append("calibration_envelope_missing")
        if not gate_d["gate_d_calibration_envelope_enforced"]:
            blockers.append("calibration_envelope_not_enforced")
        if not gate_d["gate_d_int8_calibration_range_checked"]:
            blockers.append("int8_calibration_range_not_checked")
        if args.require_no_fallback and gate_d["gate_d_tensorrt_fallback_count"]:
            blockers.append("tensorrt_fallback_used")
        if gate_d["gate_d_streamed_inference_count"] < MIN_STREAMED_INFERENCES:
            blockers.append("streamed_inference_count_insufficient")
        if gate_d["gate_d_valid_int8_inference_count"] < MIN_STREAMED_INFERENCES:
            blockers.append("valid_int8_inference_count_insufficient")
        if gate_d["gate_d_max_mailbox_depth"] != 1:
            blockers.append("mailbox_depth_violation")
        if gate_d["gate_d_command_accept_count"] < MIN_STREAMED_INFERENCES:
            blockers.append("command_accept_count_insufficient")
        if gate_d["gate_d_false_accept_count"] or gate_d["gate_d_false_reject_count"]:
            blockers.append("fault_matrix_false_classification")
        if not args.skip_fault_matrix and not gate_d["gate_d_fault_matrix_passed"]:
            blockers.append("phase13b_fault_matrix_regression_failed")

        health = evaluate_runtime_health(
            metrics,
            deadline_ms=budget,
            observed_p99_ms=gate_d["frame_to_command_ms_p99"],
        )
        summary["runtime_health"] = health
        if not args.require_no_fallback:
            health["blockers"] = [
                item for item in health["blockers"] if item != "tensorrt_fallback_used"
            ]
        blockers.extend(health["blockers"])

        passed = not blockers and not driver.blockers
        status = STATUS_RUNTIME_PASS if passed else STATUS_BLOCKED
        exit_code = 0 if passed else 1
    except Exception as exc:
        summary["error"] = repr(exc)[:400]
        driver.emit("gate_d_error", error=repr(exc)[:300])
    finally:
        pc_metrics = driver.pc_metrics()
        summary["status"] = status
        summary["blockers"] = sorted(set(blockers + list(driver.blockers)))
        summary["pc_environment"] = environment
        summary.update(BOUNDARY_FIELDS)
        metrics = jetson_evidence.get("metrics", {})
        evidence.write_json("summary.json", summary)
        evidence.write_json("jetson_metrics.json", metrics)
        evidence.write_json("environment.json", environment)
        evidence.write_json("parity_metrics.json", parity or {"executed": False})
        evidence.write_json(
            "latency_metrics.json",
            {
                "frame_to_command_ms": metrics.get("frame_to_command_ms_stats"),
                "tensorrt_latency_metrics": metrics.get("tensorrt_latency_metrics"),
                "command_rtt_ms_mean": metrics.get("command_rtt_ms_mean"),
            },
        )
        evidence.write_json(
            "range_metrics.json",
            {
                key: metrics.get(key)
                for key in (
                    "input_range_checked",
                    "tensor_output_range_checked",
                    "detection_schema_checked",
                    "int8_calibration_range_checked",
                    "calibration_envelope_loaded",
                    "calibration_envelope_enforced",
                    "calibration_envelope_evaluation_count",
                    "calibration_envelope_reject_count",
                    "calibration_envelope_violation_counts",
                    "activation_range_checked",
                    "runtime_internal_activation_observed",
                    "quantization_saturation_checked_at_runtime",
                    "range_validation_scope",
                    "tensorrt_range_reject_count",
                    "range_reject_counts",
                )
            },
        )
        evidence.write_json(
            "network_metrics.json",
            {
                "transport_medium": args.transport_medium,
                "jetson_host": args.jetson_host,
                "pc_source_address": driver.pc_address,
                "clock": driver.clock_result.to_dict() if driver.clock_result else None,
            },
        )
        evidence.write_json("pc_metrics.json", pc_metrics)
        evidence.write_fault_matrix(driver.fault_rows)
        evidence.write_events(driver.events + list(jetson_evidence.get("events", [])))
        evidence.write_manifest("D_streamed_int8_runtime", status)
        evidence.write_placeholders()
        evidence.write_text(
            "commands.txt", "# Phase 13D Gate D\n%s %s\n" % (sys.executable, " ".join(sys.argv))
        )
        evidence.write_text(
            "README.md",
            "# Phase 13D Gate D evidence\n\nRun id: `%s`\n\nStatus: `%s`\n\n"
            "Streamed real-Jetson TensorRT INT8 inference over the verified Phase 13B "
            "transport, gated by the calibration envelope. No CARLA. No model accuracy is "
            "claimed.\n" % (run_id, status),
        )
        driver.shutdown()

    print(status)
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    for key, value in sorted(summary.get("gate_d", {}).items()):
        print("%s=%s" % (key, value))
    if summary.get("blockers"):
        print("blockers=%s" % ",".join(summary["blockers"]), file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

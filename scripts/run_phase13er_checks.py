"""Phase 13E-R Gate A: prove the three mechanisms locally before spending target time.

Gate A does not need a Jetson, but it does need more than unit tests. All three
Phase 13E-R goals are about behaviour that only appears when a real transport, a
real control channel and a real C Virtual Safety MCU are in the loop:

* Goal 1 -- periodic resync has to survive the control channel and produce a
  drift estimate the node actually applies to its issue timestamps.
* Goal 2 -- the producer has to outrun a real consumer over a real socket. On
  loopback the consumer is fast, so the burst rate is raised until it does; the
  point is that overload is reachable at all, which Phase 13E never showed.
* Goal 3 -- the bounded containers have to hold under a real run and report
  their own high-water marks.

The Jetson gates then repeat this against the real target and the FP16 engine.
Nothing here claims Jetson runtime, TensorRT inference, or a soak result.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, str(_path))

from run_phase13b_jil_checks import (  # noqa: E402
    EvidenceWriter,
    JilSessionDriver,
    new_run_id,
    pc_environment,
    utc_now_iso,
)
from run_phase13b_loopback_checks import start_local_node  # noqa: E402
from simulation.independent_frame_producer import (  # noqa: E402
    EncodedFrame,
    IndependentFrameProducer,
)
from simulation.carla_frame_publisher import synthetic_bgr_frame  # noqa: E402
from simulation.virtual_safety_mcu_server import (  # noqa: E402
    build_safety_mcu_library,
    find_safety_mcu_library,
)
from workers.core.clock_discipline import DEFAULT_RESYNC_INTERVAL_SEC  # noqa: E402

PHASE = "13E-R-CLOCK-DRIFT-BACKPRESSURE-RECOVERY"
DEFAULT_OUTPUT_DIR = "experiments/phase13"
DEFAULT_LOOPBACK_HOST = "127.0.0.1"

UNIT_TEST_PATTERNS = (
    "test_phase13er_*.py",
    "test_phase13e_*.py",
    "test_phase13b_*.py",
    "test_phase13c_*.py",
    "test_phase13d_*.py",
    "test_phase13a_*.py",
)


def run_unit_tests(pattern: str) -> Dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "scripts/tests", "-p", pattern],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
    )
    output = result.stdout or ""
    return {
        "pattern": pattern,
        "passed": result.returncode == 0,
        "returncode": result.returncode,
        "output_tail": output.strip().splitlines()[-8:],
    }


def check_clock_discipline(driver: JilSessionDriver, cycles: int) -> Dict[str, Any]:
    """Goal 1: drive several real resyncs and read back the node's model."""

    models = []  # type: List[Dict[str, Any]]
    for _ in range(max(2, int(cycles))):
        response = driver.resync_clocks()
        models.append(
            {
                "accepted": bool(response.get("clock_sync_accepted")),
                "generation": response.get("clock_model_generation"),
                "estimated_drift_ppm": response.get("estimated_drift_ppm"),
                "clock_guard_us": response.get("clock_guard_us"),
                "clock_uncertainty_us": response.get("clock_uncertainty_us"),
                "clock_model_age_ms": response.get("clock_model_age_ms"),
                "clock_window_size": response.get("clock_window_size"),
                "clock_sync_degraded": response.get("clock_sync_degraded"),
            }
        )
        # Space the probes so the drift fit has a real time axis to work with.
        time.sleep(0.25)

    last = models[-1] if models else {}
    return {
        "resync_cycles": len(models),
        "resync_count": driver.clock_resync_count,
        "resync_failure_count": driver.clock_resync_failure_count,
        "models": models,
        "final_model": last,
        "generation_advanced": bool(
            len(models) >= 2
            and last.get("generation") is not None
            and int(last.get("generation") or 0) > int(models[0].get("generation") or 0)
        ),
        "guard_covers_uncertainty": bool(
            last.get("clock_guard_us") is not None
            and last.get("clock_uncertainty_us") is not None
            and int(last["clock_guard_us"]) >= int(last["clock_uncertainty_us"])
        ),
        "window_bounded": bool(
            last.get("clock_window_size") is not None and int(last["clock_window_size"]) <= 32
        ),
        "healthy_after_resync": last.get("clock_sync_degraded") is False,
    }


def check_backpressure(
    driver: JilSessionDriver, *, target_fps: float, duration_sec: float, width: int, height: int
) -> Dict[str, Any]:
    """Goal 2: overload the loopback consumer from an independent producer."""

    payload = driver.publisher.encode(synthetic_bgr_frame(width, height, frame_index=0))
    frames = [
        EncodedFrame(payload, width=width, height=height, simulation_timestamp_us=0)
        for _ in range(2)
    ]
    before = driver.control.request("get_metrics").get("metrics", {})
    driver.control.request("begin_metric_window", window="gate_a_backpressure")

    producer = IndependentFrameProducer(driver.publisher, frames, target_fps=target_fps)
    started = time.time()
    producer.start()
    while time.time() - started < duration_sec:
        driver.maybe_resync_clocks()
        time.sleep(0.05)
    producer_metrics = producer.stop()
    window = driver.control.request("end_metric_window")
    after = driver.control.request("get_metrics").get("metrics", {})

    elapsed = max(1e-6, time.time() - started)
    processed = int(after.get("frames_processed", 0) or 0) - int(
        before.get("frames_processed", 0) or 0
    )
    dropped = int(after.get("frames_dropped_mailbox", 0) or 0) - int(
        before.get("frames_dropped_mailbox", 0) or 0
    )
    input_fps = float(producer_metrics.get("producer_input_fps", 0.0))
    processed_fps = round(processed / elapsed, 3)
    depth = int(after.get("max_mailbox_depth", 0) or 0)
    report = {
        "target_fps": target_fps,
        "duration_sec": round(elapsed, 3),
        "input_fps": input_fps,
        "processed_fps": processed_fps,
        "frames_processed": processed,
        "mailbox_drop_count": dropped,
        "max_mailbox_depth": depth,
        "latest_frame_only": depth == 1,
        "unbounded_queue_detected": depth > 1,
        "input_exceeds_processed": input_fps > processed_fps,
        "overload_demonstrated": input_fps > processed_fps and dropped > 0,
        "window": window,
    }
    report.update(producer_metrics)
    return report


def check_bounded_memory(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Goal 3: the node reports fixed capacities and stays inside them."""

    capacity = metrics.get("metrics_ring_capacity")
    watermark = metrics.get("metrics_ring_high_watermark")
    return {
        "metrics_ring_capacity": capacity,
        "metrics_ring_high_watermark": watermark,
        "metrics_ring_capacity_by_series": metrics.get("metrics_ring_capacity_by_series"),
        "metrics_storage": metrics.get("metrics_storage"),
        "metrics_unbounded_list_count": metrics.get("metrics_unbounded_list_count"),
        "frame_record_sink": metrics.get("frame_record_sink"),
        "within_capacity": bool(
            capacity is not None and watermark is not None and int(watermark) <= int(capacity)
        ),
        "streamed_records": bool((metrics.get("frame_record_sink") or {}).get("streamed")),
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13E-R Gate A local checks")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--loopback-host", default=DEFAULT_LOOPBACK_HOST)
    parser.add_argument("--bind-host", default=DEFAULT_LOOPBACK_HOST)
    parser.add_argument("--frame-port", type=int, default=48801)
    parser.add_argument("--control-port", type=int, default=48802)
    parser.add_argument("--command-port", type=int, default=48803)
    parser.add_argument("--ack-port", type=int, default=48804)
    parser.add_argument("--camera-width", type=int, default=320)
    parser.add_argument("--camera-height", type=int, default=180)
    parser.add_argument("--clock-samples", type=int, default=40)
    parser.add_argument("--clock-resync-samples", type=int, default=12)
    parser.add_argument("--clock-resync-interval-sec", type=float, default=DEFAULT_RESYNC_INTERVAL_SEC)
    parser.add_argument("--resync-cycles", type=int, default=6)
    parser.add_argument(
        "--burst-fps", type=float, default=400.0,
        help="Loopback consumers are fast; the burst must exceed them to overload.",
    )
    parser.add_argument("--burst-sec", type=float, default=20.0)
    parser.add_argument("--warmup-frames", type=int, default=20)
    parser.add_argument("--heartbeat-timeout-ms", type=int, default=3000)
    parser.add_argument("--command-validity-ms", type=int, default=500)
    parser.add_argument("--diagnostic-throttle", type=float, default=0.20)
    parser.add_argument("--ack-timeout-ms", type=int, default=500)
    parser.add_argument("--mcu-library", default="")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--node-start-timeout-sec", type=float, default=90.0)
    parser.add_argument("--skip-unit-tests", action="store_true")
    parser.add_argument("--metrics-ring-capacity", type=int, default=512)
    parser.add_argument(
        "--no-decoupled-consumer", dest="decoupled_consumer", action="store_false",
        help="Run the node in the Phase 13B lock-step mode instead (diagnostic).",
    )
    parser.set_defaults(decoupled_consumer=True)
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or ("%s-13er-gatea" % new_run_id())
    evidence = EvidenceWriter(Path(args.output_dir), run_id)

    summary = {
        "phase": PHASE,
        "gate": "A",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "transport_medium": "loopback",
        "environment": pc_environment(argparse.Namespace(transport_medium="loopback")),
        "real_jetson_runtime_claimed": False,
        "tensorrt_inference_claimed": False,
        "full_hil_verified": False,
    }  # type: Dict[str, Any]

    unit_reports = []  # type: List[Dict[str, Any]]
    if not args.skip_unit_tests:
        for pattern in UNIT_TEST_PATTERNS:
            unit_reports.append(run_unit_tests(pattern))
    summary["unit_tests"] = unit_reports
    summary["unit_tests_passed"] = bool(unit_reports) and all(
        item["passed"] for item in unit_reports
    )

    library = find_safety_mcu_library(args.mcu_library or None)
    if library is None and not args.mcu_library:
        summary["mcu_library_build"] = build_safety_mcu_library()
        library = find_safety_mcu_library(None)
    summary["mcu_library_path"] = str(library) if library else None

    log_path = evidence.run_dir / "raw_outputs" / "phase13er_node.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    node = start_local_node(args, run_id, log_path)
    driver = JilSessionDriver(
        run_id=run_id,
        jetson_host=args.loopback_host,
        frame_port=args.frame_port,
        control_port=args.control_port,
        command_port=args.command_port,
        ack_port=args.ack_port,
        pc_bind_host=args.loopback_host,
        mcu_library_path=args.mcu_library or (str(library) if library else None),
        heartbeat_timeout_ms=args.heartbeat_timeout_ms,
        command_validity_ms=args.command_validity_ms,
        clock_samples=args.clock_samples,
        camera_width=args.camera_width,
        camera_height=args.camera_height,
        clock_resync_interval_sec=args.clock_resync_interval_sec,
        clock_resync_samples=args.clock_resync_samples,
        pin_source_host=True,
        auto_build_mcu_library=False,
    )

    try:
        mcu = driver.start_virtual_mcu()
        summary["virtual_mcu"] = {k: v for k, v in mcu.items() if k != "events"}
        if not mcu.get("ok"):
            raise RuntimeError("virtual safety MCU could not start")

        deadline = time.time() + float(args.node_start_timeout_sec)
        connected = False
        while time.time() < deadline and not connected:
            if node.poll() is not None:
                raise RuntimeError("node exited early with code %s" % node.returncode)
            try:
                driver.connect_control(connect_timeout_sec=3.0)
                connected = True
            except OSError:
                time.sleep(0.5)
        if not connected:
            raise RuntimeError("node control channel never became reachable")

        summary["clock"] = driver.synchronise_clocks()
        driver.start_session(start_frame_server=True)
        if not driver.connect_frames():
            raise RuntimeError("loopback frame transport could not be established")

        # Warm the pipeline so the burst measures steady state, not first-frame cost.
        summary["warmup"] = driver.publish_synthetic_frames(
            int(args.warmup_frames), wait_timeout_sec=60.0
        )
        summary["clock_discipline"] = check_clock_discipline(driver, args.resync_cycles)
        summary["backpressure"] = check_backpressure(
            driver,
            target_fps=float(args.burst_fps),
            duration_sec=float(args.burst_sec),
            width=int(args.camera_width),
            height=int(args.camera_height),
        )

        jetson = driver.collect_jetson_evidence()
        node_metrics = jetson["metrics"]
        summary["bounded_memory"] = check_bounded_memory(node_metrics)
        summary["node_metrics"] = node_metrics
        summary["issued_future_skew_us_max"] = node_metrics.get("issued_future_skew_us_max")
        summary["future_timestamp_reject_count"] = node_metrics.get(
            "future_timestamp_reject_count"
        )
    except Exception as exc:
        summary["error"] = repr(exc)[:400]
        driver.emit("phase13er_gate_a_error", error=repr(exc)[:300])
    finally:
        summary["pc_metrics"] = driver.pc_metrics()
        driver.shutdown()
        try:
            node.wait(timeout=30)
        except subprocess.TimeoutExpired:
            node.terminate()
            try:
                node.wait(timeout=10)
            except subprocess.TimeoutExpired:
                node.kill()

    clock = summary.get("clock_discipline", {}) or {}
    burst = summary.get("backpressure", {}) or {}
    memory = summary.get("bounded_memory", {}) or {}
    skew_max = summary.get("issued_future_skew_us_max")

    blockers = []  # type: List[str]
    if not summary.get("unit_tests_passed") and not args.skip_unit_tests:
        blockers.append("unit_tests_failed")
    if not clock.get("generation_advanced"):
        blockers.append("clock_resync_did_not_advance")
    if clock.get("resync_failure_count"):
        blockers.append("clock_resync_failures_observed")
    if not clock.get("guard_covers_uncertainty"):
        blockers.append("clock_guard_below_uncertainty")
    if not clock.get("window_bounded"):
        blockers.append("clock_window_unbounded")
    if skew_max is not None and float(skew_max) > 0:
        blockers.append("issued_timestamp_future_skew")
    if int(summary.get("future_timestamp_reject_count") or 0) > 0:
        blockers.append("future_timestamp_rejects_observed")
    if not burst.get("overload_demonstrated"):
        blockers.append("backpressure_overload_not_demonstrated")
    if burst.get("unbounded_queue_detected"):
        blockers.append("unbounded_queue_detected")
    if not burst.get("latest_frame_only"):
        blockers.append("mailbox_depth_violation")
    if not memory.get("within_capacity"):
        blockers.append("metrics_ring_capacity_exceeded")
    if not memory.get("streamed_records"):
        blockers.append("frame_records_not_streamed")
    if "error" in summary:
        blockers.append("gate_a_run_failed")

    summary["blockers"] = sorted(set(blockers))
    summary["gate_a_passed"] = not summary["blockers"]
    summary["status"] = "Gate A Pass" if summary["gate_a_passed"] else "Blocked"

    evidence.write_json("phase13er_gate_a_summary.json", summary)
    evidence.write_events(driver.events)
    print("%s %s" % (PHASE, summary["status"]))
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    print("clock_resync_count=%s" % clock.get("resync_count"))
    print("estimated_drift_ppm=%s" % (clock.get("final_model") or {}).get("estimated_drift_ppm"))
    print("clock_guard_us=%s" % (clock.get("final_model") or {}).get("clock_guard_us"))
    print("issued_future_skew_us_max=%s" % skew_max)
    print("future_timestamp_reject_count=%s" % summary.get("future_timestamp_reject_count"))
    print("burst_input_fps=%s" % burst.get("input_fps"))
    print("burst_processed_fps=%s" % burst.get("processed_fps"))
    print("mailbox_drop_count=%s" % burst.get("mailbox_drop_count"))
    print("max_mailbox_depth=%s" % burst.get("max_mailbox_depth"))
    print("metrics_ring_high_watermark=%s" % memory.get("metrics_ring_high_watermark"))
    if summary["blockers"]:
        print("blockers=%s" % ",".join(summary["blockers"]))
    return 0 if summary["gate_a_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

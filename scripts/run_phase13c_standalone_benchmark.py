"""Phase 13C standalone TensorRT benchmark — runs on the real Jetson.

Bounded, no-fallback inference against the target-built FP16 engine:

* >= 50 warm-up iterations (discarded);
* >= 300 measured iterations;
* per-stage latency from ``perf_counter_ns`` plus CUDA-event GPU time;
* zero per-frame device allocation, zero CUDA errors, zero execute failures.

No FPS threshold is asserted: the throughput of this board is *measured*, not
predicted. The closed-loop deadline is enforced later, in Gate D.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13c_checks import (  # noqa: E402
    BOUNDARY_FIELDS,
    PHASE,
    STATUS_BLOCKED,
    STATUS_ENGINE_PASS,
    Phase13CEvidence,
    latency_stats,
    new_run_id,
    utc_now_iso,
)
from workers.core.jetson_resource_monitor import JetsonResourceMonitor
from workers.core.tensorrt_asset_contract import (
    EngineManifest,
    InputContract,
    ModelManifest,
    OutputContract,
    PostprocessProfile,
)
from workers.core.tensorrt_perception import (
    TensorRTPerceptionBackend,
    TensorRTPerceptionError,
    load_class_names,
)
from workers.core.tensorrt_range_monitor import TensorRTRangeMonitor
from workers.core.tensorrt_runtime import (
    TensorRTEngineRunner,
    TensorRTRuntimeError,
    cuda_preflight,
    tensorrt_preflight,
)

MIN_WARMUP = 50
MIN_ITERATIONS = 300


def synthetic_bgr_frame(width: int, height: int, index: int) -> np.ndarray:
    """Deterministic frame; the benchmark measures the engine, not the scene."""

    rng = np.random.RandomState(9000 + index)
    y_axis = np.linspace(30, 220, height, dtype=np.float32).reshape(height, 1)
    x_axis = np.linspace(30, 220, width, dtype=np.float32).reshape(1, width)
    base = (y_axis + x_axis) / 2.0
    frame = np.empty((height, width, 3), dtype=np.uint8)
    frame[:, :, 0] = np.clip(base + 12.0, 0, 255).astype(np.uint8)
    frame[:, :, 1] = np.clip(base, 0, 255).astype(np.uint8)
    frame[:, :, 2] = np.clip(base - 12.0, 0, 255).astype(np.uint8)
    noise = rng.randint(-5, 6, size=(height, width, 3))
    return np.clip(frame.astype(np.int16) + noise, 16, 240).astype(np.uint8)


def load_contracts(
    model_manifest_path: Optional[str], engine_manifest_path: Optional[str], profile_name: str
) -> Dict[str, Any]:
    """Contracts come from the recorded manifests, never from assumptions."""

    input_contract = InputContract()
    output_contract = OutputContract()
    profile = PostprocessProfile(name=profile_name)
    class_names_source = ""
    model_manifest = None  # type: Optional[ModelManifest]
    engine_manifest = None  # type: Optional[EngineManifest]

    if model_manifest_path and Path(model_manifest_path).is_file():
        model_manifest = ModelManifest.load(Path(model_manifest_path))
        stored_input = model_manifest.input_contract or {}
        if stored_input:
            input_contract = InputContract(
                input_name=str(stored_input.get("input_name", "images")),
                batch_size=int(stored_input.get("batch_size", 1)),
                channels=int(stored_input.get("channels", 3)),
                height=int(stored_input.get("height", 640)),
                width=int(stored_input.get("width", 640)),
                input_dtype=str(stored_input.get("input_dtype", "float32")),
                input_color_order=str(stored_input.get("input_color_order", "RGB")),
                source_pixel_format=str(stored_input.get("source_pixel_format", "BGR8")),
                normalization_scale=float(stored_input.get("normalization_scale", 255.0)),
            )
        stored_output = model_manifest.output_contract or {}
        if stored_output:
            output_contract = OutputContract(
                output_names=list(stored_output.get("output_names", ["output0"])),
                output_shapes=[list(item) for item in stored_output.get("output_shapes", [])],
                output_dtypes=list(stored_output.get("output_dtypes", ["float32"])),
                layout=str(stored_output.get("layout", "unknown")),
                nms_embedded=bool(stored_output.get("nms_embedded", False)),
                has_objectness=bool(stored_output.get("has_objectness", False)),
                class_count=int(stored_output.get("class_count", 0)),
                class_names_source=str(stored_output.get("class_names_source", "")),
            )
            class_names_source = output_contract.class_names_source
        stored_profile = model_manifest.postprocess_profile or {}
        if stored_profile:
            profile = PostprocessProfile(
                name=str(stored_profile.get("name", profile_name)),
                confidence_threshold=float(stored_profile.get("confidence_threshold", 0.25)),
                nms_iou_threshold=float(stored_profile.get("nms_iou_threshold", 0.45)),
                max_detections=int(stored_profile.get("max_detections", 300)),
            )
    if engine_manifest_path and Path(engine_manifest_path).is_file():
        engine_manifest = EngineManifest.load(Path(engine_manifest_path))

    return {
        "input_contract": input_contract,
        "output_contract": output_contract,
        "postprocess_profile": profile,
        "class_names_source": class_names_source,
        "model_manifest": model_manifest,
        "engine_manifest": engine_manifest,
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13C standalone TensorRT benchmark")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--engine", required=True)
    parser.add_argument("--model-manifest", default="")
    parser.add_argument("--engine-manifest", default="")
    parser.add_argument("--profile", default="yolov9-c")
    parser.add_argument("--class-names", default="")
    parser.add_argument("--warmup", type=int, default=MIN_WARMUP)
    parser.add_argument("--iterations", type=int, default=MIN_ITERATIONS)
    parser.add_argument("--frame-width", type=int, default=640)
    parser.add_argument("--frame-height", type=int, default=360)
    parser.add_argument("--frame-pool", type=int, default=16)
    parser.add_argument("--output-dir", default="experiments/phase13")
    parser.add_argument("--require-no-fallback", action="store_true")
    parser.add_argument("--require-real-jetson", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or new_run_id()
    evidence = Phase13CEvidence(Path(args.output_dir), run_id)

    trt_report = tensorrt_preflight()
    cuda_report = cuda_preflight()
    summary = {
        "phase": PHASE,
        "gate": "B_standalone_benchmark",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "jetson_arch": platform.machine(),
        "real_jetson_detected": platform.machine() == "aarch64",
        "tensorrt": trt_report,
        "cuda": cuda_report,
        "standalone_warmup_count": 0,
        "standalone_measured_inference_count": 0,
        "tensorrt_fallback_count": 0,
        "tensorrt_backend_no_fallback": True,
    }  # type: Dict[str, Any]
    blockers = []  # type: List[str]

    if args.require_real_jetson and platform.machine() != "aarch64":
        blockers.append("jetson_environment_mismatch")
    if not trt_report["tensorrt_available"]:
        blockers.append("tensorrt_builder_unavailable")
    if cuda_report["cuda_allocator_backend"] == "unavailable":
        blockers.append("cuda_runtime_unavailable")
    if int(args.warmup) < MIN_WARMUP:
        blockers.append("insufficient_warmup")
    if int(args.iterations) < MIN_ITERATIONS:
        blockers.append("insufficient_iterations")

    contracts = load_contracts(args.model_manifest, args.engine_manifest, args.profile)
    input_contract = contracts["input_contract"]
    class_names, class_names_source = load_class_names(
        args.class_names or contracts["class_names_source"] or None
    )
    summary["class_names_source"] = class_names_source
    summary["class_count"] = len(class_names)

    resources = JetsonResourceMonitor()
    latency = {
        "preprocess_ms": [],
        "h2d_ms": [],
        "tensorrt_enqueue_ms": [],
        "gpu_execution_ms": [],
        "d2h_ms": [],
        "postprocess_ms": [],
        "inference_total_ms": [],
        "frame_to_perception_ms": [],
    }  # type: Dict[str, List[float]]
    range_monitor = TensorRTRangeMonitor()
    backend = None  # type: Optional[TensorRTPerceptionBackend]
    runner = None  # type: Optional[TensorRTEngineRunner]

    if not blockers:
        try:
            runner = TensorRTEngineRunner(
                str(args.engine),
                expected_input_shape=input_contract.shape,
                expected_input_name=input_contract.input_name,
            )
        except TensorRTRuntimeError as exc:
            blockers.append(exc.classification)
            summary["engine_load_error"] = exc.message

    if runner is not None and not blockers:
        resources.start()
        backend = TensorRTPerceptionBackend(
            runner,
            input_contract=input_contract,
            output_contract=contracts["output_contract"],
            profile=contracts["postprocess_profile"],
            class_names=class_names,
            model_name=str(args.profile),
        )
        pool = [
            synthetic_bgr_frame(int(args.frame_width), int(args.frame_height), index)
            for index in range(max(1, int(args.frame_pool)))
        ]
        try:
            for index in range(int(args.warmup)):
                backend.detect(pool[index % len(pool)])
            summary["standalone_warmup_count"] = int(args.warmup)

            allocation_baseline = runner.device_allocation_count
            for index in range(int(args.iterations)):
                detections, _ = backend.detect(pool[index % len(pool)])
                timing = backend.last_timing
                for key in latency:
                    value = timing.get(key)
                    if value is not None:
                        latency[key].append(float(value))
                verdict = range_monitor.evaluate(
                    input_stats=backend.last_stats,
                    detections=detections,
                    output_stats=backend.last_stats,
                    inference_ms=float(timing.get("frame_to_perception_ms", 0.0)),
                    result_age_ms=0.0,
                    engine_execute_ok=True,
                    fallback_used=False,
                )
                if verdict.state.name not in ("VALID", "RECOVERY_PENDING"):
                    summary.setdefault("range_rejections", []).append(verdict.to_dict())
            summary["standalone_measured_inference_count"] = int(args.iterations)
            runner.per_frame_device_allocation_count = (
                runner.device_allocation_count - allocation_baseline
            )
        except (TensorRTPerceptionError, TensorRTRuntimeError) as exc:
            blockers.append(getattr(exc, "classification", "engine_execute_failed"))
            summary["benchmark_error"] = getattr(exc, "message", repr(exc))[:300]
        finally:
            resources.stop()

    latency_metrics = {name: latency_stats(values) for name, values in latency.items()}
    total = latency_metrics.get("frame_to_perception_ms", {})
    mean_ms = total.get("mean") or 0.0
    summary["standalone_throughput_fps"] = round(1000.0 / mean_ms, 3) if mean_ms else None
    summary["latency_metrics"] = latency_metrics

    if runner is not None:
        summary.update(runner.metrics())
        if runner.per_frame_device_allocation_count:
            blockers.append("per_frame_device_allocation")
        if runner.engine_execute_failure_count:
            blockers.append("engine_execute_failed")
        if runner.cuda.error_count:
            blockers.append("cuda_execution_error")
    if backend is not None:
        summary["tensorrt_fallback_count"] = 0 if not backend.fallback_used else 1
        if backend.fallback_used and args.require_no_fallback:
            blockers.append("tensorrt_fallback_used")

    telemetry = resources.summary()
    summary["jetson_telemetry"] = telemetry
    if telemetry.get("thermal_throttling_observed"):
        blockers.append("thermal_throttling_observed")

    summary["blockers"] = sorted(set(blockers))
    passed = (
        not summary["blockers"]
        and summary["standalone_measured_inference_count"] >= MIN_ITERATIONS
        and summary["standalone_warmup_count"] >= MIN_WARMUP
    )
    summary["status"] = STATUS_ENGINE_PASS if passed else STATUS_BLOCKED
    summary.update(range_monitor.evidence())
    summary.update(BOUNDARY_FIELDS)

    if runner is not None:
        runner.close()

    evidence.write_json("summary.json", summary)
    evidence.write_json("latency_metrics.json", latency_metrics)
    evidence.write_json("range_metrics.json", range_monitor.evidence())
    evidence.write_json("jetson_metrics.json", telemetry)
    evidence.write_json(
        "manifest.json",
        {
            "phase": PHASE,
            "gate": "B_standalone_benchmark",
            "run_id": run_id,
            "status": summary["status"],
            "created_at_utc": utc_now_iso(),
            "evidence_dir": str(evidence.run_dir),
            "generated_evidence_git_policy": "ignored_local_only",
            **BOUNDARY_FIELDS,
        },
    )
    evidence.write_text(
        "commands.txt",
        "# Phase 13C standalone benchmark\n%s %s\n" % (sys.executable, " ".join(sys.argv)),
    )
    evidence.write_text(
        "README.md",
        "# Phase 13C standalone benchmark evidence\n\nRun id: `%s`\n\nStatus: `%s`\n\n"
        "Bounded no-fallback TensorRT FP16 inference on the real Jetson GPU. Throughput "
        "is measured, not asserted against a predicted threshold.\n" % (run_id, summary["status"]),
    )

    print(summary["status"])
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    print("standalone_warmup_count=%s" % summary["standalone_warmup_count"])
    print("standalone_measured_inference_count=%s" % summary["standalone_measured_inference_count"])
    print("standalone_throughput_fps=%s" % summary["standalone_throughput_fps"])
    print("per_frame_device_allocation_count=%s" % summary.get("per_frame_device_allocation_count"))
    print("cuda_error_count=%s" % summary.get("cuda_error_count"))
    if summary["blockers"]:
        print("blockers=%s" % ",".join(summary["blockers"]), file=sys.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

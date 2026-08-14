"""Phase 13D FP16-vs-INT8 benchmark — both engines, one Jetson, one run.

Comparing an INT8 number measured today against an FP16 number measured in
Phase 13C would compare two thermal states, not two precisions. So both plans
are benchmarked back to back in the same process, on the same board, over the
same frames, with the same warm-up and iteration counts:

* >= 50 warm-up iterations (discarded);
* >= 300 measured iterations per precision;
* per-stage latency from ``perf_counter_ns`` plus CUDA-event GPU time;
* zero per-frame device allocation, zero CUDA errors, zero execute failures,
  zero perception fallback, no observed thermal throttling.

The speedup reported is the measured ratio of the two, not a prediction, and it
says nothing about detection quality.

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

from run_phase13c_standalone_benchmark import load_contracts, synthetic_bgr_frame  # noqa: E402
from run_phase13d_checks import (  # noqa: E402
    BOUNDARY_FIELDS,
    PHASE,
    STATUS_BLOCKED,
    STATUS_ENGINE_PASS,
    Phase13DEvidence,
    evaluate_runtime_health,
    latency_stats,
    new_run_id,
    utc_now_iso,
)
from workers.core.int8_calibration_dataset import DatasetManifest  # noqa: E402
from workers.core.jetson_resource_monitor import JetsonResourceMonitor  # noqa: E402
from workers.core.tensorrt_perception import (  # noqa: E402
    TensorRTPerceptionBackend,
    TensorRTPerceptionError,
    load_class_names,
)
from workers.core.tensorrt_runtime import (  # noqa: E402
    TensorRTEngineRunner,
    TensorRTRuntimeError,
    cuda_preflight,
    tensorrt_preflight,
)

MIN_WARMUP = 50
MIN_ITERATIONS = 300

LATENCY_KEYS = (
    "preprocess_ms",
    "h2d_ms",
    "tensorrt_enqueue_ms",
    "gpu_execution_ms",
    "d2h_ms",
    "postprocess_ms",
    "inference_total_ms",
    "frame_to_perception_ms",
)


def load_frame_pool(args: argparse.Namespace) -> Dict[str, Any]:
    """Real holdout frames when a manifest is given, else synthetic frames."""

    if args.dataset_manifest and Path(args.dataset_manifest).is_file():
        import cv2  # type: ignore[import-not-found]

        manifest = DatasetManifest.load(Path(args.dataset_manifest))
        records = manifest.split(str(args.frame_split))
        root_override = Path(args.dataset_root_override) if args.dataset_root_override else None
        frames = []  # type: List[Any]
        for record in records[: max(1, int(args.frame_pool))]:
            path = Path(record.path) if root_override is None else root_override / record.relative_path
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is not None:
                frames.append(image)
        if frames:
            return {
                "frames": frames,
                "frame_source": "dataset_%s_split" % args.frame_split,
                "frame_pool_size": len(frames),
                "dataset_sha256": manifest.dataset_sha256,
            }
    return {
        "frames": [
            synthetic_bgr_frame(int(args.frame_width), int(args.frame_height), index)
            for index in range(max(1, int(args.frame_pool)))
        ],
        "frame_source": "synthetic_deterministic",
        "frame_pool_size": max(1, int(args.frame_pool)),
        "dataset_sha256": "",
    }


def benchmark_engine(
    *,
    label: str,
    engine_path: str,
    precision: str,
    contracts: Dict[str, Any],
    class_names: List[str],
    pool: List[Any],
    warmup: int,
    iterations: int,
    profile_name: str,
) -> Dict[str, Any]:
    """Warm up, then measure one engine. Never falls back on failure."""

    payload = {
        "label": label,
        "engine_path": engine_path,
        "precision": precision,
        "warmup_count": 0,
        "measured_inference_count": 0,
        "blockers": [],
    }  # type: Dict[str, Any]
    input_contract = contracts["input_contract"]
    try:
        runner = TensorRTEngineRunner(
            engine_path,
            expected_input_shape=input_contract.shape,
            expected_input_name=input_contract.input_name,
        )
    except TensorRTRuntimeError as exc:
        payload["blockers"].append(exc.classification)
        payload["error"] = exc.message
        return payload

    backend = TensorRTPerceptionBackend(
        runner,
        input_contract=input_contract,
        output_contract=contracts["output_contract"],
        profile=contracts["postprocess_profile"],
        class_names=class_names,
        model_name=profile_name,
        precision=precision,
    )
    samples = {key: [] for key in LATENCY_KEYS}  # type: Dict[str, List[float]]
    detection_counts = []  # type: List[int]
    try:
        for index in range(int(warmup)):
            backend.detect(pool[index % len(pool)])
        payload["warmup_count"] = int(warmup)

        allocation_baseline = runner.device_allocation_count
        for index in range(int(iterations)):
            detections, _ = backend.detect(pool[index % len(pool)])
            detection_counts.append(len(detections))
            timing = backend.last_timing
            for key in LATENCY_KEYS:
                value = timing.get(key)
                if value is not None:
                    samples[key].append(float(value))
        payload["measured_inference_count"] = int(iterations)
        runner.per_frame_device_allocation_count = (
            runner.device_allocation_count - allocation_baseline
        )
    except (TensorRTPerceptionError, TensorRTRuntimeError) as exc:
        payload["blockers"].append(getattr(exc, "classification", "engine_execute_failed"))
        payload["error"] = getattr(exc, "message", repr(exc))[:300]
    finally:
        metrics = runner.metrics()
        payload["runner_metrics"] = metrics
        payload["fallback_used"] = bool(backend.fallback_used)
        backend.close()

    payload["latency_metrics"] = {key: latency_stats(values) for key, values in samples.items()}
    total = payload["latency_metrics"].get("frame_to_perception_ms", {})
    mean_ms = total.get("mean") or 0.0
    payload["throughput_fps"] = round(1000.0 / mean_ms, 3) if mean_ms else None
    payload["detection_count_mean"] = (
        round(sum(detection_counts) / float(len(detection_counts)), 3) if detection_counts else None
    )
    health = dict(metrics)
    health["tensorrt_fallback_count"] = 1 if payload["fallback_used"] else 0
    payload["blockers"].extend(evaluate_runtime_health(health)["blockers"])
    if payload["warmup_count"] < MIN_WARMUP:
        payload["blockers"].append("insufficient_warmup")
    if payload["measured_inference_count"] < MIN_ITERATIONS:
        payload["blockers"].append("insufficient_iterations")
    return payload


def _ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return round(float(numerator) / float(denominator), 4)


def compare_precisions(fp16: Dict[str, Any], int8: Dict[str, Any]) -> Dict[str, Any]:
    """Measured ratios only; nothing here is predicted or extrapolated."""

    fp16_total = fp16.get("latency_metrics", {}).get("frame_to_perception_ms", {})
    int8_total = int8.get("latency_metrics", {}).get("frame_to_perception_ms", {})
    fp16_gpu = fp16.get("latency_metrics", {}).get("gpu_execution_ms", {})
    int8_gpu = int8.get("latency_metrics", {}).get("gpu_execution_ms", {})
    return {
        "fp16_frame_to_perception_ms": {
            key: fp16_total.get(key) for key in ("p50", "p95", "p99", "mean", "max")
        },
        "int8_frame_to_perception_ms": {
            key: int8_total.get(key) for key in ("p50", "p95", "p99", "mean", "max")
        },
        "fp16_gpu_execution_ms": {key: fp16_gpu.get(key) for key in ("p50", "p95", "p99")},
        "int8_gpu_execution_ms": {key: int8_gpu.get(key) for key in ("p50", "p95", "p99")},
        "frame_to_perception_speedup_p50": _ratio(fp16_total.get("p50"), int8_total.get("p50")),
        "frame_to_perception_speedup_p95": _ratio(fp16_total.get("p95"), int8_total.get("p95")),
        "frame_to_perception_speedup_p99": _ratio(fp16_total.get("p99"), int8_total.get("p99")),
        "gpu_execution_speedup_p50": _ratio(fp16_gpu.get("p50"), int8_gpu.get("p50")),
        "fp16_throughput_fps": fp16.get("throughput_fps"),
        "int8_throughput_fps": int8.get("throughput_fps"),
        "speedup_is_measured_not_predicted": True,
        "accuracy_compared": False,
        "map_compared": False,
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13D FP16 vs INT8 benchmark")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--fp16-engine", required=True)
    parser.add_argument("--int8-engine", required=True)
    parser.add_argument("--model-manifest", default="")
    parser.add_argument("--fp16-engine-manifest", default="")
    parser.add_argument("--int8-engine-manifest", default="")
    parser.add_argument("--profile", default="yolov9-c")
    parser.add_argument("--class-names", default="")
    parser.add_argument("--dataset-manifest", default="")
    parser.add_argument("--dataset-root-override", default="")
    parser.add_argument("--frame-split", default="holdout", choices=("holdout", "calibration"))
    parser.add_argument("--warmup", type=int, default=MIN_WARMUP)
    parser.add_argument("--iterations", type=int, default=MIN_ITERATIONS)
    parser.add_argument("--frame-width", type=int, default=640)
    parser.add_argument("--frame-height", type=int, default=360)
    parser.add_argument("--frame-pool", type=int, default=16)
    parser.add_argument("--output-dir", default="experiments/phase13")
    parser.add_argument("--require-real-jetson", action="store_true")
    parser.add_argument("--require-benchmark", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or new_run_id()
    evidence = Phase13DEvidence(Path(args.output_dir), run_id)

    trt_report = tensorrt_preflight()
    cuda_report = cuda_preflight()
    summary = {
        "phase": PHASE,
        "gate": "C_precision_benchmark",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "jetson_arch": platform.machine(),
        "real_jetson_detected": platform.machine() == "aarch64",
        "tensorrt": trt_report,
        "cuda": cuda_report,
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

    contracts = load_contracts(args.model_manifest, args.int8_engine_manifest, args.profile)
    class_names, class_names_source = load_class_names(
        args.class_names or contracts["class_names_source"] or None
    )
    summary["class_names_source"] = class_names_source
    summary["class_count"] = len(class_names)

    pool_info = load_frame_pool(args)
    summary["frame_pool"] = {
        key: value for key, value in pool_info.items() if key != "frames"
    }

    resources = JetsonResourceMonitor()
    fp16 = {}  # type: Dict[str, Any]
    int8 = {}  # type: Dict[str, Any]
    comparison = {}  # type: Dict[str, Any]

    if not blockers:
        resources.start()
        try:
            fp16 = benchmark_engine(
                label="fp16",
                engine_path=str(args.fp16_engine),
                precision="fp16",
                contracts=contracts,
                class_names=class_names,
                pool=pool_info["frames"],
                warmup=int(args.warmup),
                iterations=int(args.iterations),
                profile_name=str(args.profile),
            )
            int8 = benchmark_engine(
                label="int8",
                engine_path=str(args.int8_engine),
                precision="int8",
                contracts=contracts,
                class_names=class_names,
                pool=pool_info["frames"],
                warmup=int(args.warmup),
                iterations=int(args.iterations),
                profile_name=str(args.profile),
            )
        finally:
            resources.stop()
        blockers.extend("fp16:%s" % item for item in fp16.get("blockers", []))
        blockers.extend("int8:%s" % item for item in int8.get("blockers", []))
        comparison = compare_precisions(fp16, int8)

    telemetry = resources.summary()
    summary["jetson_telemetry"] = telemetry
    blockers.extend(evaluate_runtime_health(telemetry)["blockers"])

    summary["fp16"] = fp16
    summary["int8"] = int8
    summary["precision_comparison"] = comparison
    summary["blockers"] = sorted(set(blockers))
    passed = (
        not summary["blockers"]
        and int(fp16.get("measured_inference_count", 0)) >= MIN_ITERATIONS
        and int(int8.get("measured_inference_count", 0)) >= MIN_ITERATIONS
    )
    summary["benchmark_passed"] = passed
    summary["status"] = STATUS_ENGINE_PASS if passed else STATUS_BLOCKED
    summary.update(BOUNDARY_FIELDS)

    evidence.write_json("summary.json", summary)
    evidence.write_json(
        "precision_benchmark.json",
        {
            "fp16": fp16.get("latency_metrics"),
            "int8": int8.get("latency_metrics"),
            "comparison": comparison,
            "frame_pool": summary["frame_pool"],
        },
    )
    evidence.write_json(
        "latency_metrics.json",
        {"fp16": fp16.get("latency_metrics"), "int8": int8.get("latency_metrics")},
    )
    evidence.write_json("jetson_metrics.json", telemetry)
    evidence.write_json(
        "environment.json", {"tensorrt": trt_report, "cuda": cuda_report, "arch": platform.machine()}
    )
    evidence.write_manifest("C_precision_benchmark", summary["status"])
    evidence.write_placeholders()
    evidence.write_fault_matrix([])
    evidence.write_events([])
    evidence.write_text(
        "commands.txt",
        "# Phase 13D precision benchmark\n%s %s\n" % (sys.executable, " ".join(sys.argv)),
    )
    evidence.write_text(
        "README.md",
        "# Phase 13D FP16-vs-INT8 benchmark evidence\n\nRun id: `%s`\n\nStatus: `%s`\n\n"
        "Both plans measured back to back on the same Jetson over the same frames. The "
        "speedup is a measured latency ratio and carries no claim about detection "
        "quality.\n" % (run_id, summary["status"]),
    )

    print(summary["status"])
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    for label, payload in (("fp16", fp16), ("int8", int8)):
        total = payload.get("latency_metrics", {}).get("frame_to_perception_ms", {})
        print(
            "%s_measured=%s p50=%s p95=%s p99=%s fps=%s"
            % (
                label,
                payload.get("measured_inference_count"),
                total.get("p50"),
                total.get("p95"),
                total.get("p99"),
                payload.get("throughput_fps"),
            )
        )
    for key in (
        "frame_to_perception_speedup_p50",
        "frame_to_perception_speedup_p99",
        "gpu_execution_speedup_p50",
    ):
        print("%s=%s" % (key, comparison.get(key)))
    if summary["blockers"]:
        print("blockers=%s" % ",".join(summary["blockers"]), file=sys.stderr)
    if args.require_benchmark and not passed:
        return 1
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

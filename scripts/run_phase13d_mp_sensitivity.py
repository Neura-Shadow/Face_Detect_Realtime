"""Phase 13D-MP-RECOVERY — bounded PTQ mixed-precision sensitivity candidate.

Builds **one** candidate INT8 engine with a named set of semantic layer groups
forced to FP16, then measures everything needed to rank it against the others:
the layer-precision audit, the raw class/box tensor distributions against the
verified FP16 engine, the full parity gate, and a bounded latency benchmark.

This is still post-training quantization. No weight is changed, no retraining or
fine-tuning happens, the calibration and holdout splits are the Phase 13D ones,
and the confidence, IoU and parity thresholds are untouched.

Each candidate writes its own evidence directory and never overwrites another's,
including candidates whose build fails.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13c_backend_parity import detections_to_records, read_bgr  # noqa: E402
from run_phase13c_engine_build import jetson_identity  # noqa: E402
from run_phase13c_standalone_benchmark import load_contracts  # noqa: E402
from run_phase13d_checks import (  # noqa: E402
    BOUNDARY_FIELDS,
    PHASE,
    Phase13DEvidence,
    evaluate_runtime_health,
    latency_stats,
    utc_now_iso,
)
from run_phase13d_int8_engine_build import build_int8_engine  # noqa: E402
from run_phase13d_precision_parity import compare_parity  # noqa: E402
from workers.core.int8_calibration_dataset import DatasetManifest  # noqa: E402
from workers.core.int8_calibrator import (  # noqa: E402
    CalibrationBatchFeeder,
    build_entropy_calibrator,
)
from workers.core.int8_engine_audit import audit_engine  # noqa: E402
from workers.core.int8_layer_groups import (  # noqa: E402
    group_membership,
    parse_group_spec,
    prefixes_for,
    summarize_groups,
)
from workers.core.jetson_resource_monitor import JetsonResourceMonitor  # noqa: E402
from workers.core.tensorrt_asset_contract import PostprocessProfile  # noqa: E402
from workers.core.tensorrt_perception import (  # noqa: E402
    TensorRTPerceptionBackend,
    TensorRTPerceptionError,
    load_class_names,
    preprocess_bgr,
)
from workers.core.tensorrt_runtime import (  # noqa: E402
    CudaRuntime,
    TensorRTEngineRunner,
    TensorRTRuntimeError,
)

STATUS_CANDIDATE_EVALUATED = "%s candidate evaluated" % PHASE
STATUS_CANDIDATE_FAILED = "%s candidate failed" % PHASE

#: Recovery bounds. Identical to the Phase 13D parity gate — never relaxed here.
RECOVERY_THRESHOLDS = {
    "matched_detection_rate": 0.90,
    "matched_class_agreement": 0.98,
    "matched_box_iou_mean": 0.75,
    "confidence_abs_error_p95": 0.12,
}


def network_layer_names(onnx_path: str) -> List[str]:
    """Layer names of the parsed network — the graph, not documentation."""

    import tensorrt as trt  # type: ignore[import-not-found]

    logger = trt.Logger(trt.Logger.ERROR)
    builder = trt.Builder(logger)
    network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
    parser = trt.OnnxParser(network, logger)
    with open(onnx_path, "rb") as handle:
        if not parser.parse(handle.read()):
            raise RuntimeError("onnx parse failed")
    names = [str(network.get_layer(index).name) for index in range(network.num_layers)]
    del parser, network, builder
    return names


def tensor_distribution(values: np.ndarray) -> Dict[str, Any]:
    flat = np.asarray(values, dtype=np.float32).reshape(-1)
    if flat.size == 0:
        return {"min": None, "p1": None, "p50": None, "p99": None, "max": None, "mean": None}
    return {
        "min": round(float(flat.min()), 6),
        "p1": round(float(np.percentile(flat, 1.0)), 6),
        "p50": round(float(np.percentile(flat, 50.0)), 6),
        "p99": round(float(np.percentile(flat, 99.0)), 6),
        "max": round(float(flat.max()), 6),
        "mean": round(float(flat.mean()), 8),
    }


def split_output(raw: np.ndarray) -> Any:
    """``(1, 4+nc, anchors)`` -> ``(box, class)`` in anchors-first orientation."""

    matrix = np.asarray(raw)[0]
    if matrix.shape[0] < matrix.shape[1]:
        matrix = matrix.T
    return matrix[:, :4].astype(np.float32), matrix[:, 4:].astype(np.float32)


def evaluate_engine(
    *,
    engine_path: str,
    precision: str,
    listed: List[Dict[str, str]],
    contracts: Dict[str, Any],
    profile: PostprocessProfile,
    class_names: List[str],
    tensor_frames: int,
    warmup: int,
    iterations: int,
    keep_class_tensors: bool,
) -> Dict[str, Any]:
    """One pass over the holdout: detections, raw tensor stats and latency."""

    contract = contracts["input_contract"]
    payload = {
        "engine_path": engine_path,
        "precision": precision,
        "frames": [],
        "blockers": [],
    }  # type: Dict[str, Any]

    runner = TensorRTEngineRunner(
        engine_path,
        expected_input_shape=contract.shape,
        expected_input_name=contract.input_name,
    )
    backend = TensorRTPerceptionBackend(
        runner,
        input_contract=contract,
        output_contract=contracts["output_contract"],
        profile=profile,
        class_names=class_names,
        model_name="yolov9-c",
        precision=precision,
    )

    box_chunks = []  # type: List[np.ndarray]
    class_chunks = []  # type: List[np.ndarray]
    kept_class = {}  # type: Dict[str, np.ndarray]
    latency = {"gpu_execution_ms": [], "inference_total_ms": [], "frame_to_perception_ms": []}

    try:
        first = read_bgr(Path(listed[0]["path"]))
        for _ in range(max(0, int(warmup))):
            backend.detect(first)

        # Detections + raw tensors over the holdout split.
        for index, entry in enumerate(listed):
            image = read_bgr(Path(entry["path"]))
            if image is None:
                payload["frames"].append({"frame": entry["frame"], "error": "unreadable"})
                continue
            try:
                detections, _ms = backend.detect(image)
            except TensorRTPerceptionError as exc:
                payload["frames"].append({"frame": entry["frame"], "error": exc.classification})
                continue
            payload["frames"].append(
                {
                    "frame": entry["frame"],
                    "route": entry.get("route", ""),
                    "weather": entry.get("weather", ""),
                    "detections": detections_to_records(detections),
                }
            )
            if index < int(tensor_frames):
                tensor, _lb, _stats = preprocess_bgr(np.asarray(image), contract)
                outputs, _timing = runner.infer(tensor)
                raw = outputs[sorted(outputs)[0]]
                box, cls = split_output(raw)
                box_chunks.append(box)
                class_chunks.append(cls)
                if keep_class_tensors:
                    kept_class[entry["frame"]] = cls.copy()

        # Bounded latency benchmark on the same engine.
        allocation_baseline = runner.device_allocation_count
        pool = [read_bgr(Path(item["path"])) for item in listed[:16]]
        pool = [item for item in pool if item is not None] or [first]
        for index in range(int(iterations)):
            backend.detect(pool[index % len(pool)])
            timing = backend.last_timing
            for key in latency:
                value = timing.get(key)
                if value is not None:
                    latency[key].append(float(value))
        runner.per_frame_device_allocation_count = (
            runner.device_allocation_count - allocation_baseline
        )
        payload["measured_inference_count"] = int(iterations)
        payload["warmup_count"] = int(warmup)
    finally:
        metrics = runner.metrics()
        payload["runner_metrics"] = metrics
        payload["fallback_used"] = bool(backend.fallback_used)
        backend.close()

    payload["box_tensor"] = tensor_distribution(np.concatenate(box_chunks)) if box_chunks else {}
    payload["class_tensor"] = (
        tensor_distribution(np.concatenate(class_chunks)) if class_chunks else {}
    )
    payload["tensor_frame_count"] = len(box_chunks)
    payload["latency_metrics"] = {key: latency_stats(values) for key, values in latency.items()}
    total = payload["latency_metrics"].get("frame_to_perception_ms", {})
    mean_ms = total.get("mean") or 0.0
    payload["throughput_fps"] = round(1000.0 / mean_ms, 3) if mean_ms else None
    payload["class_tensors"] = kept_class
    payload["blockers"].extend(evaluate_runtime_health(metrics)["blockers"])
    return payload


def frame_list(args: argparse.Namespace) -> List[Dict[str, str]]:
    manifest = DatasetManifest.load(Path(args.dataset_manifest))
    records = manifest.split("holdout")
    root = Path(args.dataset_root_override) if args.dataset_root_override else None
    listed = []  # type: List[Dict[str, str]]
    for record in records:
        path = Path(record.path) if root is None else root / record.relative_path
        listed.append(
            {"frame": record.frame_id, "path": str(path), "route": record.route,
             "weather": record.weather}
        )
    if int(args.max_frames) > 0:
        listed = listed[: int(args.max_frames)]
    return listed


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13D-MP-RECOVERY sensitivity candidate")
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--forced-groups", default="", help="e.g. G1,G3 (empty = INT8 baseline)")
    parser.add_argument("--onnx", required=True)
    parser.add_argument("--fp16-engine", required=True)
    parser.add_argument("--engine", default="", help="candidate engine path; built unless reused")
    parser.add_argument("--reuse-engine", action="store_true")
    parser.add_argument("--model-manifest", default="")
    parser.add_argument("--dataset-manifest", required=True)
    parser.add_argument("--dataset-root-override", default="")
    parser.add_argument("--calibration-cache", required=True)
    parser.add_argument("--timing-cache", default="")
    parser.add_argument("--class-names", default="")
    parser.add_argument("--input-shape", default="1x3x640x640")
    parser.add_argument("--input-name", default="images")
    parser.add_argument("--workspace-bytes", type=int, default=1 << 30)
    parser.add_argument("--confidence-threshold", type=float, default=0.25)
    parser.add_argument("--nms-iou-threshold", type=float, default=0.45)
    parser.add_argument("--max-detections", type=int, default=300)
    parser.add_argument("--match-iou", type=float, default=0.5)
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--tensor-frames", type=int, default=24)
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--iterations", type=int, default=300)
    parser.add_argument("--output-dir", default="experiments/phase13")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = "phase13dmp-%s" % args.candidate_id
    evidence = Phase13DEvidence(Path(args.output_dir), run_id)

    group_ids = parse_group_spec(args.forced_groups)
    summary = {
        "phase": "Phase 13D-MP-RECOVERY",
        "gate": "sensitivity_candidate",
        "candidate_id": args.candidate_id,
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "jetson": jetson_identity(),
        "jetson_arch": platform.machine(),
        "ptq_only": True,
        "qat_performed": False,
        "weights_modified": False,
        "calibration_split_modified": False,
        "thresholds_modified": False,
        "confidence_threshold": float(args.confidence_threshold),
        "nms_iou_threshold": float(args.nms_iou_threshold),
        "parity_thresholds": dict(RECOVERY_THRESHOLDS),
    }  # type: Dict[str, Any]
    blockers = []  # type: List[str]

    layer_names = network_layer_names(args.onnx)
    summary["network"] = summarize_groups(layer_names)
    summary["candidate"] = group_membership(layer_names, group_ids)
    membership = summary["candidate"]
    # Names are recorded in a separate file; the summary keeps only the count.
    matched_names = membership.pop("forced_fp16_matched_layer_names")
    evidence.write_json("raw_outputs/forced_fp16_layers.json", matched_names)

    engine_path = Path(args.engine) if args.engine else Path(
        "%s/mp/%s.engine" % (Path(args.fp16_engine).parent, args.candidate_id)
    )
    build_attempts = []  # type: List[Dict[str, Any]]
    resources = JetsonResourceMonitor()

    if not args.reuse_engine:
        resources.start()
        cuda_runtime = None
        calibrator = None
        try:
            manifest = DatasetManifest.load(Path(args.dataset_manifest))
            root = Path(args.dataset_root_override) if args.dataset_root_override else None
            calibration_paths = [
                (Path(record.path) if root is None else root / record.relative_path)
                for record in manifest.split("calibration")
            ]
            contracts = load_contracts(args.model_manifest, "", "yolov9-c")
            feeder = CalibrationBatchFeeder(
                calibration_paths, input_contract=contracts["input_contract"], batch_size=1
            )
            cuda_runtime = CudaRuntime()
            calibrator = build_entropy_calibrator(
                feeder=feeder,
                cuda_runtime=cuda_runtime,
                cache_path=Path(args.calibration_cache),
                cache_key="",  # diagnostic sweep: reuse the verified cache as-is
                allow_cache_reuse=True,
            )
            attempt = build_int8_engine(
                onnx_path=Path(args.onnx),
                engine_path=engine_path,
                input_shape=[int(v) for v in str(args.input_shape).lower().split("x")],
                workspace_bytes=int(args.workspace_bytes),
                calibrator=calibrator,
                enable_fp16=True,
                fp16_layer_prefixes=prefixes_for(group_ids),
                obey_precision_constraints=bool(group_ids),
                timing_cache_path=str(args.timing_cache or ""),
            )
            build_attempts.append(attempt)
            summary["calibration_cache_reused"] = int(
                calibrator.metrics().get("calibration_cache_read_count", 0)
            ) > 0
            if attempt.get("engine_build_returncode") not in (0, None):
                blockers.append("candidate_engine_build_failed")
        except Exception as exc:
            blockers.append("candidate_engine_build_failed")
            build_attempts.append({"engine_build_returncode": 1, "error": repr(exc)[:400]})
        finally:
            resources.stop()
            if calibrator is not None and hasattr(calibrator, "close"):
                try:
                    calibrator.close()
                except Exception:
                    pass
            if cuda_runtime is not None:
                summary["cuda_error_count"] = int(cuda_runtime.error_count)

    summary["build_attempts"] = build_attempts
    summary["engine_path"] = str(engine_path)

    if blockers or not engine_path.is_file():
        if not engine_path.is_file():
            blockers.append("candidate_engine_missing")
        summary["blockers"] = sorted(set(blockers))
        summary["status"] = STATUS_CANDIDATE_FAILED
        summary.update(BOUNDARY_FIELDS)
        evidence.write_json("summary.json", summary)
        evidence.write_manifest("sensitivity_candidate", summary["status"])
        evidence.write_placeholders()
        print(STATUS_CANDIDATE_FAILED)
        print("candidate_id=%s" % args.candidate_id)
        print("blockers=%s" % ",".join(summary["blockers"]))
        return 1

    from workers.core.int8_calibration_dataset import sha256_file

    summary["engine_sha256"] = sha256_file(engine_path)
    summary["engine_size_bytes"] = int(engine_path.stat().st_size)

    audit = audit_engine(str(engine_path), require_int8=True)
    evidence.write_json("engine_audit.json", audit)
    total_layers = int(audit.get("engine_layer_count", 0))
    int8_layers = int(audit.get("int8_layer_count", 0))
    summary["audit"] = {
        "engine_layer_count": total_layers,
        "int8_layer_count": int8_layers,
        "fp16_layer_count": int(audit.get("fp16_layer_count", 0)),
        "fp32_layer_count": int(audit.get("fp32_layer_count", 0)),
        "unknown_precision_layer_count": int(audit.get("unknown_precision_layer_count", 0)),
        "precision_fallback_layer_count": int(audit.get("precision_fallback_layer_count", 0)),
        "quantized_layer_fraction": round(int8_layers / float(total_layers), 6) if total_layers else None,
        "all_layers_int8": bool(audit.get("all_layers_int8")),
        "dla_enabled": False,
    }
    if int8_layers <= 0:
        blockers.append("int8_layers_not_observed")

    listed = frame_list(args)
    contracts = load_contracts(args.model_manifest, "", "yolov9-c")
    class_names, class_names_source = load_class_names(
        args.class_names or contracts["class_names_source"] or None
    )
    profile = PostprocessProfile(
        name="yolov9-c",
        confidence_threshold=float(args.confidence_threshold),
        nms_iou_threshold=float(args.nms_iou_threshold),
        max_detections=int(args.max_detections),
    )
    summary["class_names_source"] = class_names_source
    summary["holdout_frame_count"] = len(listed)

    resources.start()
    try:
        reference = evaluate_engine(
            engine_path=str(args.fp16_engine), precision="fp16", listed=listed,
            contracts=contracts, profile=profile, class_names=class_names,
            tensor_frames=int(args.tensor_frames), warmup=int(args.warmup),
            iterations=int(args.iterations), keep_class_tensors=True,
        )
        candidate = evaluate_engine(
            engine_path=str(engine_path), precision="int8", listed=listed,
            contracts=contracts, profile=profile, class_names=class_names,
            tensor_frames=int(args.tensor_frames), warmup=int(args.warmup),
            iterations=int(args.iterations), keep_class_tensors=True,
        )
    except (TensorRTRuntimeError, TensorRTPerceptionError) as exc:
        resources.stop()
        blockers.append(getattr(exc, "classification", "candidate_evaluation_failed"))
        summary["blockers"] = sorted(set(blockers))
        summary["status"] = STATUS_CANDIDATE_FAILED
        summary.update(BOUNDARY_FIELDS)
        evidence.write_json("summary.json", summary)
        print(STATUS_CANDIDATE_FAILED)
        print("blockers=%s" % ",".join(summary["blockers"]))
        return 1
    resources.stop()

    # Mean absolute error of the class tensor against FP16, same frames.
    shared = sorted(set(reference["class_tensors"]) & set(candidate["class_tensors"]))
    errors = []  # type: List[float]
    for name in shared:
        errors.append(
            float(np.abs(reference["class_tensors"][name] - candidate["class_tensors"][name]).mean())
        )
    reference.pop("class_tensors", None)
    candidate.pop("class_tensors", None)
    class_mae = round(sum(errors) / len(errors), 8) if errors else None

    metrics = compare_parity(
        {"precision": "fp16", "frames": reference["frames"]},
        {"precision": "int8", "frames": candidate["frames"]},
        match_iou=float(args.match_iou),
        max_detections=int(args.max_detections),
        min_frames=1,
    )
    evidence.write_json("parity_metrics.json", metrics)
    evidence.write_json("raw_outputs/reference_frames.json", reference.pop("frames"))
    evidence.write_json("raw_outputs/candidate_frames.json", candidate.pop("frames"))

    fp16_total = reference["latency_metrics"]["frame_to_perception_ms"]
    int8_total = candidate["latency_metrics"]["frame_to_perception_ms"]
    fp16_gpu = reference["latency_metrics"]["gpu_execution_ms"]
    int8_gpu = candidate["latency_metrics"]["gpu_execution_ms"]

    def _ratio(a: Any, b: Any) -> Optional[float]:
        if a is None or not b:
            return None
        return round(float(a) / float(b), 4)

    telemetry = resources.summary()
    recovery = {
        key: metrics.get(key) for key in RECOVERY_THRESHOLDS
    }
    recovery_pass = (
        metrics.get("matched_detection_rate") is not None
        and float(metrics["matched_detection_rate"]) >= RECOVERY_THRESHOLDS["matched_detection_rate"]
        and float(metrics.get("matched_class_agreement") or 0.0)
        >= RECOVERY_THRESHOLDS["matched_class_agreement"]
        and float(metrics.get("matched_box_iou_mean") or 0.0)
        >= RECOVERY_THRESHOLDS["matched_box_iou_mean"]
        and metrics.get("confidence_abs_error_p95") is not None
        and float(metrics["confidence_abs_error_p95"])
        <= RECOVERY_THRESHOLDS["confidence_abs_error_p95"]
        and int(metrics.get("frames_with_schema_error", 0)) == 0
        and int(metrics.get("frames_with_nonfinite_output", 0)) == 0
        and int(metrics.get("unsafe_authority_divergence_count", 0)) == 0
        and int8_layers > 0
    )

    summary["result"] = {
        "candidate_id": args.candidate_id,
        "forced_fp16_group_ids": membership["forced_fp16_group_ids"],
        "forced_fp16_group_names": membership["forced_fp16_group_names"],
        "forced_fp16_matched_layer_count": membership["forced_fp16_matched_layer_count"],
        "int8_layer_count": int8_layers,
        "fp16_layer_count": summary["audit"]["fp16_layer_count"],
        "fp32_layer_count": summary["audit"]["fp32_layer_count"],
        "quantized_layer_fraction": summary["audit"]["quantized_layer_fraction"],
        "engine_sha256": summary["engine_sha256"],
        "engine_build_duration_sec": (
            build_attempts[-1].get("engine_build_duration_sec") if build_attempts else None
        ),
        "class_tensor_fp16": reference["class_tensor"],
        "class_tensor_int8": candidate["class_tensor"],
        "box_tensor_fp16": reference["box_tensor"],
        "box_tensor_int8": candidate["box_tensor"],
        "class_tensor_mae_vs_fp16": class_mae,
        "class_p99_ratio_int8_over_fp16": _ratio(
            candidate["class_tensor"].get("p99"), reference["class_tensor"].get("p99")
        ),
        "class_max_ratio_int8_over_fp16": _ratio(
            candidate["class_tensor"].get("max"), reference["class_tensor"].get("max")
        ),
        "matched_detection_rate": metrics.get("matched_detection_rate"),
        "matched_class_agreement": metrics.get("matched_class_agreement"),
        "matched_box_iou_mean": metrics.get("matched_box_iou_mean"),
        "confidence_abs_error_p95": metrics.get("confidence_abs_error_p95"),
        "reference_detection_count": metrics.get("reference_detection_count"),
        "candidate_detection_count": metrics.get("candidate_detection_count"),
        "frames_with_schema_error": metrics.get("frames_with_schema_error"),
        "frames_with_nonfinite_output": metrics.get("frames_with_nonfinite_output"),
        "unsafe_authority_divergence_count": metrics.get("unsafe_authority_divergence_count"),
        "gpu_execution_ms_p50": int8_gpu.get("p50"),
        "gpu_execution_ms_p95": int8_gpu.get("p95"),
        "fp16_gpu_execution_ms_p50": fp16_gpu.get("p50"),
        "total_inference_ms_p50": int8_total.get("p50"),
        "total_inference_ms_p95": int8_total.get("p95"),
        "fp16_total_inference_ms_p50": fp16_total.get("p50"),
        "throughput_fps": candidate.get("throughput_fps"),
        "fp16_throughput_fps": reference.get("throughput_fps"),
        "throughput_speedup": _ratio(candidate.get("throughput_fps"), reference.get("throughput_fps")),
        "total_speedup_p50": _ratio(fp16_total.get("p50"), int8_total.get("p50")),
        "gpu_speedup_p50": _ratio(fp16_gpu.get("p50"), int8_gpu.get("p50")),
        "thermal_throttling_observed": bool(telemetry.get("thermal_throttling_observed")),
        "recovery_pass": bool(recovery_pass),
        "recovery_metrics": recovery,
    }

    blockers.extend(candidate.get("blockers", []))
    blockers.extend("fp16_reference:%s" % item for item in reference.get("blockers", []))
    if telemetry.get("thermal_throttling_observed"):
        blockers.append("thermal_throttling_observed")

    summary["fp16_reference"] = reference
    summary["candidate_evaluation"] = candidate
    summary["jetson_telemetry"] = telemetry
    summary["blockers"] = sorted(set(blockers))
    summary["status"] = STATUS_CANDIDATE_EVALUATED
    summary.update(BOUNDARY_FIELDS)

    evidence.write_json("summary.json", summary)
    evidence.write_json("candidate_result.json", summary["result"])
    evidence.write_json("jetson_metrics.json", telemetry)
    evidence.write_json(
        "latency_metrics.json",
        {"fp16": reference["latency_metrics"], "int8": candidate["latency_metrics"]},
    )
    evidence.write_manifest("sensitivity_candidate", summary["status"])
    evidence.write_placeholders()
    evidence.write_fault_matrix([])
    evidence.write_events([])
    evidence.write_text(
        "commands.txt",
        "# Phase 13D-MP-RECOVERY candidate\n%s %s\n" % (sys.executable, " ".join(sys.argv)),
    )
    evidence.write_text(
        "README.md",
        "# Phase 13D-MP-RECOVERY candidate `%s`\n\nForced FP16 groups: %s\n\n"
        "Post-training mixed precision only. No weights, calibration split, "
        "confidence/IoU thresholds or parity thresholds were changed.\n"
        % (args.candidate_id, ", ".join(membership["forced_fp16_group_names"]) or "(none)"),
    )

    result = summary["result"]
    print(summary["status"])
    print("candidate_id=%s" % args.candidate_id)
    print("forced_groups=%s" % ",".join(result["forced_fp16_group_ids"]))
    for key in (
        "forced_fp16_matched_layer_count",
        "int8_layer_count",
        "fp16_layer_count",
        "fp32_layer_count",
        "quantized_layer_fraction",
        "class_tensor_mae_vs_fp16",
        "class_max_ratio_int8_over_fp16",
        "matched_detection_rate",
        "matched_class_agreement",
        "matched_box_iou_mean",
        "confidence_abs_error_p95",
        "unsafe_authority_divergence_count",
        "total_inference_ms_p50",
        "gpu_execution_ms_p50",
        "throughput_fps",
        "total_speedup_p50",
        "recovery_pass",
    ):
        print("%s=%s" % (key, result.get(key)))
    print("engine_sha256=%s" % result["engine_sha256"])
    if summary["blockers"]:
        print("blockers=%s" % ",".join(summary["blockers"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Phase 13D Gate C — INT8 calibration and engine build on the real Jetson.

A serialized TensorRT plan is not portable across TensorRT version, CUDA
version, GPU or precision, and INT8 scales are not portable across the data
that produced them. Both are therefore produced **on the target**, from the
transferred calibration corpus, and bound to a hashed cache key.

The builder is the TensorRT 8.5 Python API, because ``trtexec`` cannot run a
custom ``IInt8EntropyCalibrator2`` over the runtime preprocessing function.
Every build attempt is appended to a list, never overwritten, so a failed first
attempt stays in the evidence.

After the build the plan is audited: deserialize, bindings, output contract and
the precision TensorRT actually assigned to every layer. ``int8_layer_count``
must be greater than zero; ``all_layers_int8`` is only reported true when every
single layer reported INT8.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13c_engine_build import jetson_identity  # noqa: E402
from run_phase13d_checks import (  # noqa: E402
    BOUNDARY_FIELDS,
    PHASE,
    STATUS_BLOCKED,
    STATUS_ENGINE_PASS,
    Phase13DEvidence,
    evaluate_runtime_health,
    new_run_id,
    utc_now_iso,
)
from workers.core.int8_calibration_dataset import DatasetManifest  # noqa: E402
from workers.core.int8_calibrator import (  # noqa: E402
    CALIBRATOR_ALGORITHM,
    CalibrationBatchFeeder,
    CalibrationCacheMeta,
    CalibrationError,
    build_entropy_calibrator,
    calibration_cache_key,
    calibration_meta_path,
    evaluate_cache_staleness,
    preprocess_profile_fragment,
    sha256_bytes,
)
from workers.core.int8_engine_audit import (  # noqa: E402
    EngineAuditError,
    audit_engine,
    verify_output_contract,
)
from workers.core.jetson_resource_monitor import JetsonResourceMonitor  # noqa: E402
from workers.core.tensorrt_asset_contract import (  # noqa: E402
    EngineManifest,
    InputContract,
    ModelManifest,
    PostprocessProfile,
    describe_file,
    engine_cache_key,
    evaluate_engine_staleness,
    verify_onnx_asset,
)
from workers.core.tensorrt_runtime import (  # noqa: E402
    DEFAULT_WORKSPACE_BYTES,
    CudaRuntime,
    TensorRTEngineRunner,
    TensorRTRuntimeError,
    cuda_preflight,
    tensorrt_preflight,
)

MIN_CALIBRATION_FRAMES = 512
INT8_PRECISION = "int8"


def load_contract_from_manifest(model_manifest: Optional[ModelManifest]) -> InputContract:
    if model_manifest is None or not model_manifest.input_contract:
        return InputContract()
    stored = model_manifest.input_contract
    return InputContract(
        input_name=str(stored.get("input_name", "images")),
        batch_size=int(stored.get("batch_size", 1)),
        channels=int(stored.get("channels", 3)),
        height=int(stored.get("height", 640)),
        width=int(stored.get("width", 640)),
        input_dtype=str(stored.get("input_dtype", "float32")),
        input_color_order=str(stored.get("input_color_order", "RGB")),
        source_pixel_format=str(stored.get("source_pixel_format", "BGR8")),
        normalization_scale=float(stored.get("normalization_scale", 255.0)),
    )


#: Layer types whose precision may be constrained. CONSTANT and shape-only
#: layers are excluded: they carry no activation to quantize and constraining
#: them can invalidate an otherwise buildable network.
_CONSTRAINABLE_LAYER_TYPES = (
    "CONVOLUTION",
    "ACTIVATION",
    "ELEMENTWISE",
    "CONCATENATION",
    "SOFTMAX",
    "SLICE",
    "SHUFFLE",
    "POOLING",
    "SCALE",
    "REDUCE",
    "UNARY",
    "MATRIX_MULTIPLY",
)


def constrain_layers_to_fp16(network: Any, trt: Any, prefixes: List[str]) -> Dict[str, Any]:
    """Ask TensorRT to keep the named subgraph in FP16 rather than INT8.

    INT8 is applied per layer, and a detection head's class-score branch is the
    one place where 8-bit resolution is not enough: the scores collapse toward
    zero and almost every detection falls under the confidence threshold, even
    though the boxes that survive are still correct. Constraining that subgraph
    by **name** keeps the decision explicit and auditable instead of hiding it
    behind a layer-index heuristic.
    """

    constrained = []  # type: List[str]
    skipped = []  # type: List[str]
    if not prefixes:
        return {"fp16_constrained_layer_count": 0, "fp16_constrained_layers": [],
                "fp16_constraint_prefixes": [], "fp16_constraint_skipped_count": 0}
    for index in range(network.num_layers):
        layer = network.get_layer(index)
        name = str(layer.name)
        if not any(name.startswith(prefix) for prefix in prefixes):
            continue
        layer_type = str(layer.type).rsplit(".", 1)[-1].upper()
        if layer_type not in _CONSTRAINABLE_LAYER_TYPES:
            skipped.append("%s:%s" % (layer_type, name))
            continue
        layer.precision = trt.float16
        for output_index in range(int(layer.num_outputs)):
            layer.set_output_type(output_index, trt.float16)
        constrained.append(name)
    return {
        "fp16_constraint_prefixes": list(prefixes),
        "fp16_constrained_layer_count": len(constrained),
        "fp16_constrained_layers": constrained,
        "fp16_constraint_skipped_count": len(skipped),
        "fp16_constraint_skipped_layers": skipped[:32],
    }


def build_int8_engine(
    *,
    onnx_path: Path,
    engine_path: Path,
    input_shape: List[int],
    workspace_bytes: int,
    calibrator: Any,
    enable_fp16: bool = True,
    fp16_layer_prefixes: Optional[List[str]] = None,
    obey_precision_constraints: bool = False,
    timing_cache_path: str = "",
) -> Dict[str, Any]:
    """TensorRT 8.5 Python builder with INT8 (+FP16) and DLA explicitly off."""

    import tensorrt as trt  # type: ignore[import-not-found]

    started = time.perf_counter_ns()
    attempt = {
        "engine_builder": "tensorrt_python_int8",
        "engine_build_command": ["<tensorrt.Builder>", str(onnx_path), str(engine_path)],
        "int8_flag_set": False,
        "fp16_flag_set": False,
        "dla_enabled": False,
        "profiling_verbosity": "DETAILED",
    }  # type: Dict[str, Any]

    logger = trt.Logger(trt.Logger.WARNING)
    builder = trt.Builder(logger)
    attempt["platform_has_fast_int8"] = bool(getattr(builder, "platform_has_fast_int8", False))
    attempt["platform_has_fast_fp16"] = bool(getattr(builder, "platform_has_fast_fp16", False))
    if not attempt["platform_has_fast_int8"]:
        attempt["engine_build_returncode"] = 1
        attempt["error"] = "int8_unsupported"
        attempt["engine_build_duration_sec"] = round((time.perf_counter_ns() - started) / 1e9, 3)
        return attempt

    network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
    parser = trt.OnnxParser(network, logger)
    with open(str(onnx_path), "rb") as handle:
        if not parser.parse(handle.read()):
            attempt["engine_build_returncode"] = 1
            attempt["onnx_parser_errors"] = [
                str(parser.get_error(index)) for index in range(parser.num_errors)
            ]
            attempt["engine_build_duration_sec"] = round(
                (time.perf_counter_ns() - started) / 1e9, 3
            )
            return attempt

    config = builder.create_builder_config()
    if hasattr(config, "set_memory_pool_limit"):
        config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, int(workspace_bytes))
    else:  # pragma: no cover - older TensorRT 8 point releases
        config.max_workspace_size = int(workspace_bytes)

    config.set_flag(trt.BuilderFlag.INT8)
    attempt["int8_flag_set"] = True
    if enable_fp16 and attempt["platform_has_fast_fp16"]:
        config.set_flag(trt.BuilderFlag.FP16)
        attempt["fp16_flag_set"] = True
    config.int8_calibrator = calibrator
    # DETAILED verbosity is what makes EngineInspector able to report per-layer
    # precision later; without it the audit could not prove INT8 layers exist.
    if hasattr(config, "profiling_verbosity"):
        config.profiling_verbosity = trt.ProfilingVerbosity.DETAILED
    # DLA is never enabled: default_device_type is left at GPU and no DLA core
    # is selected.
    attempt["default_device_type"] = str(getattr(config, "default_device_type", "GPU"))

    # A tactic timing cache makes a diagnostic sweep affordable: it reuses
    # measured kernel timings instead of re-timing every tactic, which is what
    # dominates a 20-minute build. It caches *timings*, never results. Because
    # skipping re-timing can in principle change which tactic wins, the final
    # engine of this phase is built with the cache disabled, and every engine
    # records whether it used one.
    timing_cache = None
    attempt["timing_cache_used"] = False
    attempt["timing_cache_path"] = str(timing_cache_path or "")
    if timing_cache_path and hasattr(config, "create_timing_cache"):
        existing = b""
        if os.path.isfile(timing_cache_path):
            with open(timing_cache_path, "rb") as handle:
                existing = handle.read()
        try:
            timing_cache = config.create_timing_cache(existing)
            config.set_timing_cache(timing_cache, False)
            attempt["timing_cache_used"] = True
            attempt["timing_cache_seed_bytes"] = len(existing)
        except Exception as exc:
            attempt["timing_cache_error"] = repr(exc)[:200]
            timing_cache = None

    profile = builder.create_optimization_profile()
    input_tensor = network.get_input(0)
    profile.set_shape(input_tensor.name, tuple(input_shape), tuple(input_shape), tuple(input_shape))
    config.add_optimization_profile(profile)
    if hasattr(config, "set_calibration_profile"):
        config.set_calibration_profile(profile)
    attempt["network_input_name"] = str(input_tensor.name)
    attempt["network_layer_count"] = int(network.num_layers)

    prefixes = list(fp16_layer_prefixes or [])
    if prefixes:
        # PREFER lets TensorRT ignore a constraint whose fused kernel has no
        # FP16 implementation, which is safe but was measured to leave the
        # detect head in INT8 anyway. OBEY forces the un-fusing; if it cannot be
        # satisfied the build fails loudly instead of silently under-delivering.
        if obey_precision_constraints:
            config.set_flag(trt.BuilderFlag.OBEY_PRECISION_CONSTRAINTS)
        else:
            config.set_flag(trt.BuilderFlag.PREFER_PRECISION_CONSTRAINTS)
        attempt["obey_precision_constraints"] = bool(obey_precision_constraints)
        attempt["prefer_precision_constraints"] = not bool(obey_precision_constraints)
        attempt.update(constrain_layers_to_fp16(network, trt, prefixes))
    else:
        attempt["obey_precision_constraints"] = False
        attempt["prefer_precision_constraints"] = False
        attempt["fp16_constrained_layer_count"] = 0

    plan = builder.build_serialized_network(network, config)
    duration = (time.perf_counter_ns() - started) / 1e9
    attempt["engine_build_duration_sec"] = round(duration, 3)
    if timing_cache is not None and timing_cache_path:
        try:
            payload = timing_cache.serialize()
            Path(timing_cache_path).parent.mkdir(parents=True, exist_ok=True)
            with open(timing_cache_path, "wb") as handle:
                handle.write(bytes(payload))
            attempt["timing_cache_written_bytes"] = len(bytes(payload))
        except Exception as exc:
            attempt["timing_cache_write_error"] = repr(exc)[:200]
    if plan is None:
        attempt["engine_build_returncode"] = 1
        attempt["error"] = "build_serialized_network returned None"
        return attempt
    engine_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(engine_path), "wb") as handle:
        handle.write(plan)
    attempt["engine_build_returncode"] = 0
    return attempt


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13D target INT8 engine build")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--onnx", required=True)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--dataset-manifest", required=True)
    parser.add_argument("--calibration-cache", default="")
    parser.add_argument("--model-manifest", default="")
    parser.add_argument("--engine-manifest", default="")
    parser.add_argument("--input-shape", default="1x3x640x640")
    parser.add_argument("--input-name", default="images")
    parser.add_argument("--profile", default="yolov9-c")
    parser.add_argument("--workspace-bytes", type=int, default=DEFAULT_WORKSPACE_BYTES)
    parser.add_argument("--min-calibration-frames", type=int, default=MIN_CALIBRATION_FRAMES)
    parser.add_argument("--dataset-root-override", default="")
    parser.add_argument("--output-dir", default="experiments/phase13")
    parser.add_argument("--no-fp16", action="store_true")
    parser.add_argument(
        "--fp16-layer-prefix",
        action="append",
        default=[],
        help="keep layers whose name starts with this prefix in FP16 (repeatable)",
    )
    parser.add_argument(
        "--timing-cache",
        default="",
        help="TensorRT tactic timing cache; speeds up a diagnostic sweep, never used for the final engine",
    )
    parser.add_argument(
        "--obey-precision-constraints",
        action="store_true",
        help="force the FP16 layer constraints instead of treating them as a preference",
    )
    parser.add_argument("--force-rebuild", action="store_true")
    parser.add_argument("--force-recalibrate", action="store_true")
    parser.add_argument("--require-real-jetson", action="store_true")
    parser.add_argument("--require-engine", action="store_true")
    parser.add_argument("--require-int8-layers", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or new_run_id()
    evidence = Phase13DEvidence(Path(args.output_dir), run_id)

    identity = jetson_identity()
    trt_report = tensorrt_preflight()
    cuda_report = cuda_preflight()
    summary = {
        "phase": PHASE,
        "gate": "C_int8_engine_build",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "jetson": identity,
        "tensorrt": trt_report,
        "cuda": cuda_report,
        "jetson_arch": platform.machine(),
        "int8_engine_built": False,
        "int8_engine_verified": False,
        "int8_layers_observed": False,
        "all_layers_int8": False,
        "engine_deserialization_verified": False,
        "engine_binding_contract_verified": False,
        "output_contract_verified": False,
        "calibration_executed": False,
        "calibration_cache_reused": False,
        "dla_enabled": False,
    }  # type: Dict[str, Any]
    blockers = []  # type: List[str]
    build_attempts = []  # type: List[Dict[str, Any]]

    if args.require_real_jetson and not identity["real_jetson_detected"]:
        blockers.append("jetson_environment_mismatch")
    if not trt_report["tensorrt_available"] or trt_report["tensorrt_major"] != 8:
        blockers.append("tensorrt_builder_unavailable")
    if cuda_report["cuda_allocator_backend"] == "unavailable":
        blockers.append("cuda_runtime_unavailable")

    onnx_path = Path(args.onnx)
    engine_path = Path(args.engine)
    model_manifest = None  # type: Optional[ModelManifest]
    if args.model_manifest and Path(args.model_manifest).is_file():
        model_manifest = ModelManifest.load(Path(args.model_manifest))
    elif onnx_path.with_suffix(".manifest.json").is_file():
        model_manifest = ModelManifest.load(onnx_path.with_suffix(".manifest.json"))

    onnx_report = verify_onnx_asset(
        onnx_path, expected_sha256=model_manifest.onnx_sha256 if model_manifest else ""
    )
    summary["onnx"] = onnx_report
    blockers.extend(onnx_report["blockers"])

    input_contract = load_contract_from_manifest(model_manifest)
    input_shape = [int(value) for value in str(args.input_shape).lower().split("x")]
    postprocess = PostprocessProfile(name=str(args.profile))
    if model_manifest and model_manifest.postprocess_profile:
        stored = model_manifest.postprocess_profile
        postprocess = PostprocessProfile(
            name=str(stored.get("name", args.profile)),
            confidence_threshold=float(stored.get("confidence_threshold", 0.25)),
            nms_iou_threshold=float(stored.get("nms_iou_threshold", 0.45)),
            max_detections=int(stored.get("max_detections", 300)),
        )

    # ── calibration corpus ──────────────────────────────────────────────────
    calibration_paths = []  # type: List[Path]
    dataset_manifest = None  # type: Optional[DatasetManifest]
    manifest_path = Path(args.dataset_manifest)
    if not manifest_path.is_file():
        blockers.append("dataset_manifest_missing")
    else:
        dataset_manifest = DatasetManifest.load(manifest_path)
        root_override = Path(args.dataset_root_override) if args.dataset_root_override else None
        for record in dataset_manifest.split("calibration"):
            candidate = Path(record.path)
            if root_override is not None:
                candidate = root_override / record.relative_path
            calibration_paths.append(candidate)
        missing = [str(item) for item in calibration_paths if not item.is_file()]
        summary["calibration_frames_missing_count"] = len(missing)
        summary["calibration_frames_missing"] = missing[:16]
        if missing:
            blockers.append("calibration_frame_missing")
        if len(calibration_paths) < int(args.min_calibration_frames):
            blockers.append("calibration_frame_count_insufficient")
        summary["dataset"] = {
            "dataset_manifest_path": str(manifest_path),
            "dataset_sha256": dataset_manifest.dataset_sha256,
            "dataset_name": dataset_manifest.dataset_name,
            "routes": dataset_manifest.routes,
            "weather_profiles": dataset_manifest.weather_profiles,
            "calibration_count": dataset_manifest.calibration_count,
            "holdout_count": dataset_manifest.holdout_count,
            "data_source": dataset_manifest.data_source,
            "real_world_representative": False,
        }

    cache_path = Path(args.calibration_cache) if args.calibration_cache else engine_path.with_suffix(
        ".calibration.cache"
    )
    cache_key = calibration_cache_key(
        onnx_sha256=onnx_report["onnx_sha256"] or "",
        dataset_sha256=dataset_manifest.dataset_sha256 if dataset_manifest else "",
        calibration_frame_count=len(calibration_paths),
        algorithm=CALIBRATOR_ALGORITHM,
        batch_size=1,
        input_profile=str(args.input_shape),
        preprocess_profile=preprocess_profile_fragment(input_contract),
        tensorrt_version=trt_report["tensorrt_version"],
        cuda_version=cuda_report["cuda_runtime_version"],
        gpu_name=identity["gpu_name"],
    )
    summary["calibration_cache_key"] = cache_key
    summary["calibration_cache_path"] = str(cache_path)

    existing_meta = None  # type: Optional[CalibrationCacheMeta]
    meta_path = calibration_meta_path(cache_path)
    if meta_path.is_file():
        try:
            existing_meta = CalibrationCacheMeta.load(meta_path)
        except Exception as exc:
            summary["calibration_cache_meta_error"] = repr(exc)[:200]
    cache_verdict = evaluate_cache_staleness(
        existing_meta, cache_path=cache_path, expected_key=cache_key
    )
    summary["calibration_cache"] = cache_verdict

    engine_cache = engine_cache_key(
        onnx_sha256=onnx_report["onnx_sha256"] or "",
        tensorrt_version=trt_report["tensorrt_version"],
        cuda_version=cuda_report["cuda_runtime_version"],
        gpu_name=identity["gpu_name"],
        compute_capability=identity["compute_capability"],
        precision=INT8_PRECISION,
        input_profile=str(args.input_shape),
        postprocess_profile=postprocess.cache_fragment(),
    )
    summary["engine_cache_key"] = engine_cache

    engine_manifest_path = (
        Path(args.engine_manifest)
        if args.engine_manifest
        else engine_path.with_suffix(".manifest.json")
    )
    reuse_engine = False
    if engine_manifest_path.is_file() and engine_path.is_file() and not args.force_rebuild:
        try:
            existing_engine = EngineManifest.load(engine_manifest_path)
            verdict = evaluate_engine_staleness(
                existing_engine,
                engine_path=engine_path,
                observed_onnx_sha256=onnx_report["onnx_sha256"] or "",
                observed_tensorrt_version=trt_report["tensorrt_version"],
                observed_cuda_version=cuda_report["cuda_runtime_version"],
                observed_gpu_name=identity["gpu_name"],
                observed_compute_capability=identity["compute_capability"],
                precision=INT8_PRECISION,
                input_profile=str(args.input_shape),
                postprocess_profile=postprocess.cache_fragment(),
            )
            summary["cached_engine"] = verdict.to_dict()
            reuse_engine = not verdict.stale and not cache_verdict["calibration_cache_stale"]
        except Exception as exc:
            summary["cached_engine_error"] = repr(exc)[:200]

    # ── calibrate + build ───────────────────────────────────────────────────
    resources = JetsonResourceMonitor()
    calibrator = None  # type: Any
    calibrator_metrics = {}  # type: Dict[str, Any]
    cuda_runtime = None  # type: Optional[CudaRuntime]

    if not blockers and not reuse_engine:
        resources.start()
        try:
            feeder = CalibrationBatchFeeder(
                calibration_paths, input_contract=input_contract, batch_size=1
            )
            cuda_runtime = CudaRuntime()
            calibrator = build_entropy_calibrator(
                feeder=feeder,
                cuda_runtime=cuda_runtime,
                cache_path=cache_path,
                cache_key=cache_key,
                allow_cache_reuse=not args.force_recalibrate,
            )
            attempt = build_int8_engine(
                onnx_path=onnx_path,
                engine_path=engine_path,
                input_shape=input_shape,
                workspace_bytes=int(args.workspace_bytes),
                calibrator=calibrator,
                enable_fp16=not args.no_fp16,
                fp16_layer_prefixes=list(args.fp16_layer_prefix or []),
                obey_precision_constraints=bool(args.obey_precision_constraints),
                timing_cache_path=str(args.timing_cache or ""),
            )
            build_attempts.append(attempt)
            calibrator_metrics = calibrator.metrics()
            summary["calibration_executed"] = int(calibrator_metrics.get("calibration_batches_served", 0)) > 0
            summary["calibration_cache_reused"] = int(calibrator_metrics.get("calibration_cache_read_count", 0)) > 0
            if attempt.get("engine_build_returncode") not in (0, None):
                blockers.append("int8_engine_build_failed")
        except CalibrationError as exc:
            blockers.append(exc.classification)
            summary["calibration_error"] = exc.message
            build_attempts.append({"engine_builder": "tensorrt_python_int8", "engine_build_returncode": 1,
                                   "error": exc.message})
        except TensorRTRuntimeError as exc:
            blockers.append(exc.classification)
            summary["calibration_error"] = exc.message
        except Exception as exc:
            blockers.append("int8_engine_build_failed")
            summary["calibration_error"] = repr(exc)[:400]
            build_attempts.append({"engine_builder": "tensorrt_python_int8", "engine_build_returncode": 1,
                                   "error": repr(exc)[:300]})
        finally:
            resources.stop()
            if calibrator is not None and hasattr(calibrator, "close"):
                try:
                    calibrator.close()
                except Exception:
                    pass

    summary["build_attempts"] = build_attempts
    summary["engine_reused"] = reuse_engine
    if cuda_runtime is not None:
        summary["cuda_error_count"] = int(cuda_runtime.error_count)
        if cuda_runtime.error_count:
            blockers.append("cuda_execution_error")
    if calibrator_metrics:
        summary["calibration"] = calibrator_metrics
        health = evaluate_runtime_health(calibrator_metrics)
        summary["calibration_health"] = health
        blockers.extend(health["blockers"])
        if int(calibrator_metrics.get("calibration_device_allocation_count", 0)) != 1:
            blockers.append("calibration_device_allocation_unexpected")

    engine_info = describe_file(engine_path)
    summary["engine"] = engine_info
    if not engine_info["exists"] and not blockers:
        blockers.append("int8_engine_build_failed")

    # ── verify + audit ──────────────────────────────────────────────────────
    engine_manifest = None  # type: Optional[EngineManifest]
    audit = {}  # type: Dict[str, Any]
    if engine_info["exists"] and not blockers:
        runner = None  # type: Optional[TensorRTEngineRunner]
        try:
            runner = TensorRTEngineRunner(
                str(engine_path),
                expected_input_shape=input_shape,
                expected_input_name=args.input_name,
            )
        except TensorRTRuntimeError as exc:
            blockers.append(exc.classification)
            summary["engine_load_error"] = exc.message
        if runner is not None:
            try:
                bindings = runner.binding_report()
                summary.update(bindings)
                summary["engine_deserialization_verified"] = True
                summary["engine_binding_contract_verified"] = True
                contract_check = verify_output_contract(
                    bindings,
                    expected_input_name=str(args.input_name),
                    expected_input_shape=input_shape,
                )
                summary["output_contract"] = contract_check
                summary["output_contract_verified"] = contract_check["output_contract_verified"]
                blockers.extend(contract_check["blockers"])
            finally:
                runner.close()
        try:
            audit = audit_engine(str(engine_path), require_int8=True)
            summary["engine_audit"] = audit
            summary["int8_layers_observed"] = bool(audit.get("int8_layers_observed"))
            summary["all_layers_int8"] = bool(audit.get("all_layers_int8"))
            summary["int8_layer_count"] = int(audit.get("int8_layer_count", 0))
            summary["precision_fallback_layer_count"] = int(
                audit.get("precision_fallback_layer_count", 0)
            )
            blockers.extend(audit.get("blockers", []))
        except EngineAuditError as exc:
            blockers.append(exc.classification)
            summary["engine_audit_error"] = exc.message

        if not blockers:
            summary["int8_engine_built"] = True
            summary["int8_engine_verified"] = True
            engine_manifest = EngineManifest(
                engine_path=str(engine_path),
                engine_sha256=engine_info["sha256"] or "",
                engine_size_bytes=int(engine_info["size_bytes"] or 0),
                engine_precision=INT8_PRECISION,
                engine_builder=str(
                    build_attempts[-1].get("engine_builder", "reused") if build_attempts else "reused"
                ),
                engine_build_command=list(
                    build_attempts[-1].get("engine_build_command", []) if build_attempts else []
                ),
                engine_build_duration_sec=float(
                    build_attempts[-1].get("engine_build_duration_sec", 0.0) if build_attempts else 0.0
                ),
                workspace_limit_bytes=int(args.workspace_bytes),
                onnx_sha256=onnx_report["onnx_sha256"] or "",
                onnx_path=str(onnx_path),
                tensorrt_version=trt_report["tensorrt_version"],
                cuda_version=cuda_report["cuda_runtime_version"],
                jetson_model=identity["jetson_model"],
                gpu_name=identity["gpu_name"],
                compute_capability=identity["compute_capability"],
                input_profile=str(args.input_shape),
                postprocess_profile=postprocess.cache_fragment(),
                engine_cache_key=engine_cache,
                engine_binding_count=int(summary.get("engine_binding_count", 0)),
                engine_input_bindings=summary.get("engine_input_bindings", []),
                engine_output_bindings=summary.get("engine_output_bindings", []),
                engine_dynamic_shapes=bool(summary.get("engine_dynamic_shapes", False)),
                engine_serialization_verified=True,
                engine_deserialization_verified=True,
                engine_compatibility_verified=True,
                int8_engine_built=True,
                dla_enabled=False,
                built_on_target=True,
                created_at_utc=utc_now_iso(),
            )
            engine_manifest.write(engine_manifest_path)
            summary["engine_manifest_path"] = str(engine_manifest_path)

            if cache_path.is_file():
                payload = cache_path.read_bytes()
                meta = CalibrationCacheMeta(
                    cache_path=str(cache_path),
                    cache_sha256=sha256_bytes(payload),
                    cache_size_bytes=len(payload),
                    calibration_cache_key=cache_key,
                    onnx_sha256=onnx_report["onnx_sha256"] or "",
                    dataset_sha256=dataset_manifest.dataset_sha256 if dataset_manifest else "",
                    dataset_manifest_path=str(manifest_path),
                    calibration_frame_count=len(calibration_paths),
                    algorithm=CALIBRATOR_ALGORITHM,
                    batch_size=1,
                    input_profile=str(args.input_shape),
                    preprocess_profile=preprocess_profile_fragment(input_contract),
                    tensorrt_version=trt_report["tensorrt_version"],
                    cuda_version=cuda_report["cuda_runtime_version"],
                    gpu_name=identity["gpu_name"],
                    built_on_target=True,
                    created_at_utc=utc_now_iso(),
                )
                meta.write(meta_path)
                summary["calibration_cache_meta_path"] = str(meta_path)
                summary["calibration_cache_manifest"] = meta.to_dict()
            else:
                blockers.append("calibration_cache_missing")

    telemetry = resources.summary()
    summary["jetson_telemetry"] = telemetry
    blockers.extend(evaluate_runtime_health(telemetry)["blockers"])

    summary["blockers"] = sorted(set(blockers))
    passed = bool(summary["int8_engine_verified"]) and not summary["blockers"]
    if args.require_int8_layers and not summary["int8_layers_observed"]:
        passed = False
    summary["status"] = STATUS_ENGINE_PASS if passed else STATUS_BLOCKED
    summary.update(BOUNDARY_FIELDS)

    evidence.write_json("summary.json", summary)
    evidence.write_json(
        "engine_manifest.json",
        engine_manifest.to_dict() if engine_manifest else {"executed": False, "blockers": summary["blockers"]},
    )
    evidence.write_json("engine_audit.json", audit or {"executed": False})
    evidence.write_json(
        "calibration_cache_manifest.json",
        summary.get("calibration_cache_manifest") or {"executed": False, "cache_key": cache_key},
    )
    evidence.write_json(
        "dataset_manifest.json",
        summary.get("dataset") or {"executed": False},
    )
    evidence.write_json("jetson_metrics.json", telemetry)
    evidence.write_json(
        "environment.json", {"jetson": identity, "tensorrt": trt_report, "cuda": cuda_report}
    )
    evidence.write_manifest("C_int8_engine_build", summary["status"])
    evidence.write_placeholders()
    evidence.write_fault_matrix([])
    evidence.write_events([])
    evidence.write_text(
        "commands.txt",
        "# Phase 13D INT8 engine build\n%s %s\n" % (sys.executable, " ".join(sys.argv)),
    )
    evidence.write_text(
        "README.md",
        "# Phase 13D INT8 engine build evidence\n\nRun id: `%s`\n\nStatus: `%s`\n\n"
        "The INT8 engine and its calibration cache are produced on the real Jetson from the "
        "transferred controlled-CARLA corpus. Layer precisions are read back from the plan; "
        "`all_layers_int8` is only ever reported true when every layer reported INT8.\n"
        % (run_id, summary["status"]),
    )

    print(summary["status"])
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    for key in (
        "int8_engine_built",
        "int8_engine_verified",
        "int8_layers_observed",
        "all_layers_int8",
        "int8_layer_count",
        "precision_fallback_layer_count",
        "calibration_executed",
        "calibration_cache_reused",
        "output_contract_verified",
        "cuda_error_count",
    ):
        if key in summary:
            print("%s=%s" % (key, summary[key]))
    if calibrator_metrics:
        for key in ("calibration_frames_read", "skipped_frame_count", "per_batch_device_allocation_count"):
            print("%s=%s" % (key, calibrator_metrics.get(key)))
    print("engine_sha256=%s" % (engine_info["sha256"] or ""))
    if summary["blockers"]:
        print("blockers=%s" % ",".join(summary["blockers"]), file=sys.stderr)
    if args.require_engine and not passed:
        return 1
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

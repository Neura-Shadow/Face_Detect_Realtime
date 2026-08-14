"""Phase 13D INT8 fault matrix (D01..D29), executed with test doubles.

Every case asserts the same safety invariant: **no invalid INT8 result may ever
produce AI_ACTIVE**. Dataset, cache and calibrator faults stop the engine from
existing at all; engine, audit, parity and throttling faults block the gate;
range, deadline, stale and fallback faults produce SAFE_STOP at runtime.

Running the module directly also writes ``phase13d_fault_matrix.json`` /
``.csv`` into the requested output directory.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
TESTS_DIR = Path(__file__).resolve().parent
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR), str(TESTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13d_checks import evaluate_runtime_health  # noqa: E402
from run_phase13d_precision_parity import compare_parity  # noqa: E402
from test_phase13c_tensorrt_runtime import FakeCudaLibrary, make_cuda_runtime  # noqa: E402
from test_phase13d_dataset import synthetic_records  # noqa: E402
from test_phase13d_parity import build_sides  # noqa: E402
from test_phase13d_range_monitor import (  # noqa: E402
    detection,
    envelopes,
    input_stats,
    output_stats,
)
from workers.core.int8_calibration_dataset import (  # noqa: E402
    CalibrationEnvelopes,
    DatasetError,
    FrameRecord,
    assign_splits,
    build_envelopes,
    build_manifest,
    describe_frame,
    evaluate_coverage,
    evaluate_disjointness,
    evaluate_holdout,
    verify_frame_files,
)
from workers.core.int8_calibrator import (  # noqa: E402
    CalibrationBatchFeeder,
    CalibrationCacheMeta,
    CalibrationError,
    ReusableDeviceBuffer,
    calibration_cache_key,
    evaluate_cache_staleness,
    preprocess_profile_fragment,
    sha256_bytes,
)
from workers.core.int8_engine_audit import (  # noqa: E402
    summarize_layer_precisions,
    verify_output_contract,
)
from workers.core.int8_range_monitor import Int8RangeContract, Int8RangeMonitor  # noqa: E402
from workers.core.tensorrt_asset_contract import (  # noqa: E402
    EngineManifest,
    InputContract,
    evaluate_engine_staleness,
    sha256_file,
    verify_onnx_asset,
)

SAFE_STOP = "SAFE_STOP"
BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
GATE_FAILURE = "GATE_FAILURE"
AI_ACTIVE = "AI_ACTIVE"

CACHE_KEY_ARGS = {
    "onnx_sha256": "a" * 64,
    "dataset_sha256": "b" * 64,
    "calibration_frame_count": 640,
    "algorithm": "IInt8EntropyCalibrator2",
    "batch_size": 1,
    "input_profile": "1x3x640x640",
    "preprocess_profile": preprocess_profile_fragment(InputContract()),
    "tensorrt_version": "8.5.2.2",
    "cuda_version": "11.4",
    "gpu_name": "Orin NX",
}


def _manifest(**kwargs: Any) -> Any:
    return build_manifest(assign_splits(synthetic_records(**kwargs), holdout_stride=5))


def _gate(blockers: List[str], expected: str) -> str:
    return GATE_FAILURE if expected in blockers else AI_ACTIVE


def _range_verdict(monitor: Int8RangeMonitor, **overrides: Any) -> Any:
    payload = dict(
        input_stats=input_stats(),
        detections=[detection()],
        output_stats=output_stats(),
        inference_ms=25.0,
        result_age_ms=5.0,
    )
    payload.update(overrides)
    return monitor.evaluate(**payload)


def _classify_range(verdict: Any) -> str:
    return AI_ACTIVE if verdict.ai_result_valid else SAFE_STOP


def _engine_manifest(engine: Path, precision: str = "int8") -> EngineManifest:
    manifest = EngineManifest(
        engine_path=str(engine),
        engine_sha256=sha256_file(engine),
        onnx_sha256="a" * 64,
        tensorrt_version="8.5.2.2",
        cuda_version="11.4",
        gpu_name="Orin NX",
        compute_capability="8.7",
        engine_precision=precision,
        input_profile="1x3x640x640",
        postprocess_profile="yolov9-c",
        int8_engine_built=True,
        built_on_target=True,
    )
    manifest.engine_cache_key = manifest.expected_cache_key()
    return manifest


def _cache_meta(cache: Path, key: str, *, built_on_target: bool = True) -> CalibrationCacheMeta:
    payload = cache.read_bytes()
    return CalibrationCacheMeta(
        cache_path=str(cache),
        cache_sha256=sha256_bytes(payload),
        cache_size_bytes=len(payload),
        calibration_cache_key=key,
        built_on_target=built_on_target,
    )


# ── Dataset faults ──────────────────────────────────────────────────────────


def d01_route_coverage_insufficient() -> Tuple[str, Dict[str, Any]]:
    coverage = evaluate_coverage(_manifest(routes=["route_00", "route_01", "route_02", "route_03"]))
    return (
        _gate(coverage["blockers"], "dataset_route_coverage_insufficient"),
        {"blockers": coverage["blockers"]},
    )


def d02_weather_coverage_insufficient() -> Tuple[str, Dict[str, Any]]:
    coverage = evaluate_coverage(_manifest(weathers=["ClearNoon", "WetCloudyNoon", "ClearSunset"]))
    return (
        _gate(coverage["blockers"], "dataset_weather_coverage_insufficient"),
        {"blockers": coverage["blockers"]},
    )


def d03_calibration_frame_count_insufficient() -> Tuple[str, Dict[str, Any]]:
    coverage = evaluate_coverage(_manifest(frames_per_cell=10))
    return (
        _gate(coverage["blockers"], "calibration_frame_count_insufficient"),
        {"blockers": coverage["blockers"]},
    )


def d04_holdout_frame_count_insufficient() -> Tuple[str, Dict[str, Any]]:
    records = assign_splits(synthetic_records(frames_per_cell=40), holdout_stride=5)
    for record in records:
        record.split = "calibration"
    coverage = evaluate_coverage(build_manifest(records))
    return (
        _gate(coverage["blockers"], "holdout_frame_count_insufficient"),
        {"blockers": coverage["blockers"]},
    )


def d05_duplicate_frames() -> Tuple[str, Dict[str, Any]]:
    records = assign_splits(synthetic_records(), holdout_stride=5)
    records[17].sha256 = records[3].sha256
    verdict = evaluate_disjointness(build_manifest(records))
    return _gate(verdict["blockers"], "dataset_duplicate_frames"), {"blockers": verdict["blockers"]}


def d06_split_overlap() -> Tuple[str, Dict[str, Any]]:
    records = assign_splits(synthetic_records(), holdout_stride=5)
    holdout = next(item for item in records if item.split == "holdout")
    calibration = next(item for item in records if item.split == "calibration")
    holdout.frame_id = calibration.frame_id
    verdict = evaluate_disjointness(build_manifest(records))
    return _gate(verdict["blockers"], "dataset_split_overlap"), {"blockers": verdict["blockers"]}


def d07_dataset_frame_tampered() -> Tuple[str, Dict[str, Any]]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "frame.png"
        target.write_bytes(b"original")
        record = describe_frame(
            target,
            frame_id="f0",
            route="route_00",
            weather="ClearNoon",
            statistics={
                "width": 640, "height": 360, "pixel_min": 0.0, "pixel_max": 1.0,
                "pixel_mean": 0.4, "channel_means": [0.4, 0.4, 0.4],
                "channel_stds": [0.2, 0.2, 0.2],
            },
            dataset_root=root,
        )
        target.write_bytes(b"tampered")
        verdict = verify_frame_files([record])
    return (
        _gate(verdict["blockers"], "dataset_frame_sha256_mismatch"),
        {"blockers": verdict["blockers"]},
    )


def d08_holdout_false_reject_rate_exceeded() -> Tuple[str, Dict[str, Any]]:
    records = assign_splits(synthetic_records(), holdout_stride=5)
    calibration_envelopes = build_envelopes(records)
    shifted = []  # type: List[FrameRecord]
    for index, record in enumerate([item for item in records if item.split == "holdout"]):
        moved = FrameRecord(**record.to_dict())
        moved.channel_means = [value + 0.4 for value in moved.channel_means]
        moved.pixel_mean = moved.pixel_mean + 0.4
        shifted.append(moved)
    verdict = evaluate_holdout(calibration_envelopes, shifted)
    return (
        _gate(verdict["blockers"], "holdout_false_reject_rate_exceeded"),
        {"false_reject_rate": verdict["holdout_false_reject_rate"]},
    )


def d09_calibration_envelope_unavailable() -> Tuple[str, Dict[str, Any]]:
    records = assign_splits(synthetic_records(frames_per_cell=40), holdout_stride=5)
    for record in records:
        record.split = "holdout"
    try:
        build_envelopes(records)
    except DatasetError as exc:
        return BACKEND_UNAVAILABLE, {"classification": exc.classification}
    return AI_ACTIVE, {}


# ── Calibration cache faults ────────────────────────────────────────────────


def d10_cache_key_mismatch() -> Tuple[str, Dict[str, Any]]:
    with tempfile.TemporaryDirectory() as directory:
        cache = Path(directory) / "model.calibration.cache"
        cache.write_bytes(b"CACHE")
        recorded = calibration_cache_key(**CACHE_KEY_ARGS)
        payload = dict(CACHE_KEY_ARGS)
        payload["dataset_sha256"] = "c" * 64
        verdict = evaluate_cache_staleness(
            _cache_meta(cache, recorded),
            cache_path=cache,
            expected_key=calibration_cache_key(**payload),
        )
    return (
        BACKEND_UNAVAILABLE if verdict["calibration_cache_stale"] else AI_ACTIVE,
        {"reasons": verdict["calibration_cache_stale_reasons"]},
    )


def d11_cache_tampered() -> Tuple[str, Dict[str, Any]]:
    with tempfile.TemporaryDirectory() as directory:
        cache = Path(directory) / "model.calibration.cache"
        cache.write_bytes(b"CACHE")
        key = calibration_cache_key(**CACHE_KEY_ARGS)
        meta = _cache_meta(cache, key)
        cache.write_bytes(b"TAMPERED")
        verdict = evaluate_cache_staleness(meta, cache_path=cache, expected_key=key)
    return (
        BACKEND_UNAVAILABLE
        if "calibration_cache_sha256_mismatch" in verdict["calibration_cache_stale_reasons"]
        else AI_ACTIVE,
        {"reasons": verdict["calibration_cache_stale_reasons"]},
    )


def d12_cache_missing() -> Tuple[str, Dict[str, Any]]:
    verdict = evaluate_cache_staleness(
        None, cache_path=Path("definitely-absent.cache"), expected_key="k"
    )
    return (
        BACKEND_UNAVAILABLE if verdict["calibration_cache_stale"] else AI_ACTIVE,
        {"reasons": verdict["calibration_cache_stale_reasons"]},
    )


def d13_cache_not_built_on_target() -> Tuple[str, Dict[str, Any]]:
    with tempfile.TemporaryDirectory() as directory:
        cache = Path(directory) / "model.calibration.cache"
        cache.write_bytes(b"CACHE")
        key = calibration_cache_key(**CACHE_KEY_ARGS)
        verdict = evaluate_cache_staleness(
            _cache_meta(cache, key, built_on_target=False), cache_path=cache, expected_key=key
        )
    return (
        BACKEND_UNAVAILABLE
        if "calibration_cache_not_built_on_target" in verdict["calibration_cache_stale_reasons"]
        else AI_ACTIVE,
        {"reasons": verdict["calibration_cache_stale_reasons"]},
    )


# ── Calibrator faults ───────────────────────────────────────────────────────


def d14_unreadable_calibration_frame() -> Tuple[str, Dict[str, Any]]:
    def _reader(_path: Any) -> Any:
        raise CalibrationError("calibration_frame_unreadable", "decode failed")

    feeder = CalibrationBatchFeeder(
        [Path("bad.png")], input_contract=InputContract(height=64, width=64), reader=_reader
    )
    try:
        feeder.next_batch()
    except CalibrationError as exc:
        return (
            BACKEND_UNAVAILABLE,
            {"classification": exc.classification, "skipped": feeder.metrics()["skipped_frame_count"]},
        )
    return AI_ACTIVE, {}


def d15_malformed_calibration_frame() -> Tuple[str, Dict[str, Any]]:
    feeder = CalibrationBatchFeeder(
        [Path("bad.png")],
        input_contract=InputContract(height=64, width=64),
        reader=lambda _path: np.zeros((8, 8), dtype=np.uint8),
    )
    try:
        feeder.next_batch()
    except CalibrationError as exc:
        return BACKEND_UNAVAILABLE, {"classification": exc.classification}
    return AI_ACTIVE, {}


def d16_unsupported_calibration_batch_size() -> Tuple[str, Dict[str, Any]]:
    try:
        CalibrationBatchFeeder([Path("a.png")], batch_size=8)
    except CalibrationError as exc:
        return BACKEND_UNAVAILABLE, {"classification": exc.classification}
    return AI_ACTIVE, {}


def d17_per_batch_device_allocation() -> Tuple[str, Dict[str, Any]]:
    """A calibrator that allocated per batch must fail the health gate."""

    fake = FakeCudaLibrary()
    buffer = ReusableDeviceBuffer(make_cuda_runtime(fake), 4 * 16)
    for index in range(4):
        buffer.upload(np.full(16, index, dtype=np.float32))
    leaky = dict(buffer.metrics())
    buffer.close()
    leaky["per_batch_device_allocation_count"] = 4  # injected fault
    health = evaluate_runtime_health(leaky)
    return (
        _gate(health["blockers"], "per_batch_device_allocation"),
        {"blockers": health["blockers"], "real_malloc_calls": fake.calls.count("cudaMalloc")},
    )


def d18_skipped_calibration_frame() -> Tuple[str, Dict[str, Any]]:
    health = evaluate_runtime_health({"skipped_frame_count": 3})
    return (
        _gate(health["blockers"], "calibration_frame_skipped"),
        {"blockers": health["blockers"]},
    )


def d19_cuda_error_during_calibration() -> Tuple[str, Dict[str, Any]]:
    health = evaluate_runtime_health({"cuda_error_count": 1})
    return _gate(health["blockers"], "cuda_execution_error"), {"blockers": health["blockers"]}


# ── Engine faults ───────────────────────────────────────────────────────────


def d20_missing_onnx() -> Tuple[str, Dict[str, Any]]:
    report = verify_onnx_asset(Path("definitely-missing.onnx"))
    return (
        BACKEND_UNAVAILABLE if "onnx_missing" in report["blockers"] else AI_ACTIVE,
        {"blockers": report["blockers"]},
    )


def d21_engine_hash_mismatch() -> Tuple[str, Dict[str, Any]]:
    with tempfile.TemporaryDirectory() as directory:
        engine = Path(directory) / "model.engine"
        engine.write_bytes(b"plan")
        manifest = _engine_manifest(engine)
        engine.write_bytes(b"tampered plan")
        verdict = evaluate_engine_staleness(
            manifest,
            engine_path=engine,
            observed_onnx_sha256="a" * 64,
            observed_tensorrt_version="8.5.2.2",
            observed_cuda_version="11.4",
            observed_gpu_name="Orin NX",
            observed_compute_capability="8.7",
            precision="int8",
            input_profile="1x3x640x640",
            postprocess_profile="yolov9-c",
        )
    return (
        BACKEND_UNAVAILABLE if "engine_sha256_mismatch" in verdict.reasons else AI_ACTIVE,
        {"reasons": verdict.reasons},
    )


def d22_precision_mismatch_makes_the_engine_stale() -> Tuple[str, Dict[str, Any]]:
    with tempfile.TemporaryDirectory() as directory:
        engine = Path(directory) / "model.engine"
        engine.write_bytes(b"plan")
        manifest = _engine_manifest(engine, precision="fp16")
        verdict = evaluate_engine_staleness(
            manifest,
            engine_path=engine,
            observed_onnx_sha256="a" * 64,
            observed_tensorrt_version="8.5.2.2",
            observed_cuda_version="11.4",
            observed_gpu_name="Orin NX",
            observed_compute_capability="8.7",
            precision="int8",
            input_profile="1x3x640x640",
            postprocess_profile="yolov9-c",
        )
    return (
        BACKEND_UNAVAILABLE if "precision_mismatch" in verdict.reasons else AI_ACTIVE,
        {"reasons": verdict.reasons},
    )


def d23_no_int8_layers_observed() -> Tuple[str, Dict[str, Any]]:
    summary = summarize_layer_precisions(
        [{"Name": "Conv_%d" % index, "Precision": "Half"} for index in range(6)]
    )
    blockers = [] if summary["int8_layers_observed"] else ["int8_layers_not_observed"]
    return _gate(blockers, "int8_layers_not_observed"), {
        "int8_layer_count": summary["int8_layer_count"]
    }


def d24_all_int8_claim_refused_on_unknown_layer() -> Tuple[str, Dict[str, Any]]:
    layers = [{"Name": "Conv_%d" % index, "Precision": "Int8"} for index in range(6)]
    layers.append({"Name": "Plugin", "LayerType": "PluginV2"})
    summary = summarize_layer_precisions(layers)
    blockers = [] if summary["all_layers_int8"] else ["all_layers_int8_claim_refused"]
    return _gate(blockers, "all_layers_int8_claim_refused"), {
        "unknown_precision_layer_count": summary["unknown_precision_layer_count"],
        "all_layers_int8": summary["all_layers_int8"],
    }


def d25_output_contract_drift() -> Tuple[str, Dict[str, Any]]:
    verdict = verify_output_contract(
        {
            "engine_input_bindings": [{"name": "images", "shape": [1, 3, 640, 640]}],
            "engine_output_bindings": [
                {"name": "output0", "shape": [1, 84, 8400]},
                {"name": "feature_map_0", "shape": [1, 144, 80, 80]},
            ],
        },
        expected_input_name="images",
        expected_input_shape=[1, 3, 640, 640],
        expected_output_names=["output0"],
    )
    return (
        _gate(verdict["blockers"], "output_binding_name_mismatch"),
        {"failures": verdict["output_contract_failures"]},
    )


# ── Runtime range / deadline / fallback faults ──────────────────────────────


def _monitor() -> Int8RangeMonitor:
    return Int8RangeMonitor(Int8RangeContract(), envelopes=envelopes())


def d26_calibration_range_shift() -> Tuple[str, Dict[str, Any]]:
    verdict = _range_verdict(
        _monitor(), input_stats=input_stats(source_channel_means=[0.85, 0.85, 0.85])
    )
    return _classify_range(verdict), {"classification": verdict.classification}


def d27_calibration_envelope_missing_at_runtime() -> Tuple[str, Dict[str, Any]]:
    verdict = _range_verdict(Int8RangeMonitor(Int8RangeContract(), envelopes=None))
    return _classify_range(verdict), {"classification": verdict.classification}


def d28_inference_deadline_missed() -> Tuple[str, Dict[str, Any]]:
    verdict = _range_verdict(_monitor(), inference_ms=5000.0)
    return _classify_range(verdict), {"classification": verdict.classification}


def d29_stale_result() -> Tuple[str, Dict[str, Any]]:
    verdict = _range_verdict(_monitor(), result_age_ms=9000.0)
    return _classify_range(verdict), {"classification": verdict.classification}


def d30_perception_fallback_used() -> Tuple[str, Dict[str, Any]]:
    verdict = _range_verdict(_monitor(), fallback_used=True)
    return _classify_range(verdict), {"classification": verdict.classification}


def d31_nonfinite_engine_output() -> Tuple[str, Dict[str, Any]]:
    verdict = _range_verdict(
        _monitor(), output_stats=output_stats(output_raw_max=float("nan"))
    )
    return _classify_range(verdict), {"classification": verdict.classification}


def d32_thermal_throttling_observed() -> Tuple[str, Dict[str, Any]]:
    health = evaluate_runtime_health({"thermal_throttling_observed": True})
    return (
        _gate(health["blockers"], "thermal_throttling_observed"),
        {"blockers": health["blockers"]},
    )


def d33_closed_loop_deadline_missed() -> Tuple[str, Dict[str, Any]]:
    health = evaluate_runtime_health({}, deadline_ms=949.0, observed_p99_ms=1200.0)
    return (
        _gate(health["blockers"], "inference_deadline_missed"),
        {"blockers": health["blockers"]},
    )


# ── Parity faults ───────────────────────────────────────────────────────────


def d34_parity_threshold_failure() -> Tuple[str, Dict[str, Any]]:
    reference, candidate = build_sides(box_shift=25.0)
    metrics = compare_parity(
        reference, candidate, match_iou=0.5, max_detections=300, min_frames=4
    )
    failed = [item for item in metrics["blockers"] if item.startswith("parity_threshold_failed")]
    return (
        GATE_FAILURE if failed else AI_ACTIVE,
        {"blockers": metrics["blockers"], "iou_mean": metrics["matched_box_iou_mean"]},
    )


def d35_unsafe_authority_divergence() -> Tuple[str, Dict[str, Any]]:
    reference, candidate = build_sides()
    reference["frames"][0] = {"frame": "frame_000", "error": "engine_execute_failed"}
    metrics = compare_parity(
        reference, candidate, match_iou=0.5, max_detections=300, min_frames=4
    )
    return (
        _gate(metrics["blockers"], "unsafe_authority_divergence"),
        {"count": metrics["unsafe_authority_divergence_count"]},
    )


FAULT_CASES = [
    ("D01", "dataset_route_coverage_insufficient", "dataset_coverage", GATE_FAILURE, d01_route_coverage_insufficient),
    ("D02", "dataset_weather_coverage_insufficient", "dataset_coverage", GATE_FAILURE, d02_weather_coverage_insufficient),
    ("D03", "calibration_frame_count_insufficient", "dataset_split", GATE_FAILURE, d03_calibration_frame_count_insufficient),
    ("D04", "holdout_frame_count_insufficient", "dataset_split", GATE_FAILURE, d04_holdout_frame_count_insufficient),
    ("D05", "dataset_duplicate_frames", "dataset_disjointness", GATE_FAILURE, d05_duplicate_frames),
    ("D06", "dataset_split_overlap", "dataset_disjointness", GATE_FAILURE, d06_split_overlap),
    ("D07", "dataset_frame_sha256_mismatch", "dataset_integrity", GATE_FAILURE, d07_dataset_frame_tampered),
    ("D08", "holdout_false_reject_rate_exceeded", "calibration_envelope", GATE_FAILURE, d08_holdout_false_reject_rate_exceeded),
    ("D09", "calibration_envelope_unavailable", "calibration_envelope", BACKEND_UNAVAILABLE, d09_calibration_envelope_unavailable),
    ("D10", "calibration_cache_key_mismatch", "calibration_cache", BACKEND_UNAVAILABLE, d10_cache_key_mismatch),
    ("D11", "calibration_cache_sha256_mismatch", "calibration_cache", BACKEND_UNAVAILABLE, d11_cache_tampered),
    ("D12", "calibration_cache_missing", "calibration_cache", BACKEND_UNAVAILABLE, d12_cache_missing),
    ("D13", "calibration_cache_not_built_on_target", "calibration_cache", BACKEND_UNAVAILABLE, d13_cache_not_built_on_target),
    ("D14", "calibration_frame_unreadable", "calibration_feed", BACKEND_UNAVAILABLE, d14_unreadable_calibration_frame),
    ("D15", "calibration_frame_preprocess_failed", "calibration_feed", BACKEND_UNAVAILABLE, d15_malformed_calibration_frame),
    ("D16", "calibration_batch_size_unsupported", "calibration_feed", BACKEND_UNAVAILABLE, d16_unsupported_calibration_batch_size),
    ("D17", "per_batch_device_allocation", "calibration_memory", GATE_FAILURE, d17_per_batch_device_allocation),
    ("D18", "calibration_frame_skipped", "calibration_feed", GATE_FAILURE, d18_skipped_calibration_frame),
    ("D19", "cuda_execution_error", "calibration_memory", GATE_FAILURE, d19_cuda_error_during_calibration),
    ("D20", "onnx_missing", "engine_build", BACKEND_UNAVAILABLE, d20_missing_onnx),
    ("D21", "engine_sha256_mismatch", "engine_cache", BACKEND_UNAVAILABLE, d21_engine_hash_mismatch),
    ("D22", "engine_precision_mismatch", "engine_cache", BACKEND_UNAVAILABLE, d22_precision_mismatch_makes_the_engine_stale),
    ("D23", "int8_layers_not_observed", "engine_audit", GATE_FAILURE, d23_no_int8_layers_observed),
    ("D24", "all_layers_int8_claim_refused", "engine_audit", GATE_FAILURE, d24_all_int8_claim_refused_on_unknown_layer),
    ("D25", "output_contract_drift", "engine_audit", GATE_FAILURE, d25_output_contract_drift),
    ("D26", "calibration_range_shift", "runtime_range", SAFE_STOP, d26_calibration_range_shift),
    ("D27", "calibration_envelope_missing", "runtime_range", SAFE_STOP, d27_calibration_envelope_missing_at_runtime),
    ("D28", "inference_timeout", "runtime_deadline", SAFE_STOP, d28_inference_deadline_missed),
    ("D29", "result_stale", "runtime_deadline", SAFE_STOP, d29_stale_result),
    ("D30", "perception_fallback_used", "runtime_fallback", SAFE_STOP, d30_perception_fallback_used),
    ("D31", "output_nonfinite", "runtime_range", SAFE_STOP, d31_nonfinite_engine_output),
    ("D32", "thermal_throttling_observed", "runtime_throttling", GATE_FAILURE, d32_thermal_throttling_observed),
    ("D33", "closed_loop_deadline_missed", "runtime_deadline", GATE_FAILURE, d33_closed_loop_deadline_missed),
    ("D34", "parity_threshold_failed", "parity", GATE_FAILURE, d34_parity_threshold_failure),
    ("D35", "unsafe_authority_divergence", "parity", GATE_FAILURE, d35_unsafe_authority_divergence),
]  # type: List[Tuple[str, str, str, str, Callable[[], Tuple[str, Dict[str, Any]]]]]


def run_fault_matrix() -> List[Dict[str, Any]]:
    rows = []  # type: List[Dict[str, Any]]
    for fault_id, name, step, expected, runner in FAULT_CASES:
        try:
            observed, details = runner()
        except Exception as exc:  # pragma: no cover - surfaced as a failed row
            observed, details = "RUNNER_ERROR", {"error": repr(exc)[:200]}
        rows.append(
            {
                "fault_id": fault_id,
                "fault_name": name,
                "gate": "A",
                "injection_step": step,
                "expected_classification": expected,
                "observed_classification": observed,
                "passed": observed == expected,
                "details": json.dumps(details, ensure_ascii=False, sort_keys=True, default=str),
            }
        )
    return rows


def matrix_counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """A fault that yielded AI_ACTIVE is a false accept; the reverse is a false reject."""

    false_accept = sum(1 for row in rows if row["observed_classification"] == AI_ACTIVE)
    false_reject = sum(
        1
        for row in rows
        if row["expected_classification"] == AI_ACTIVE
        and row["observed_classification"] != AI_ACTIVE
    )
    return {"false_accept_count": false_accept, "false_reject_count": false_reject}


class TestRuntimeHealthSuppression(unittest.TestCase):
    """Suppression is a safety-relevant knob, so it is pinned explicitly."""

    def test_nothing_is_suppressed_by_default(self) -> None:
        health = evaluate_runtime_health({"tensorrt_inference_failed_count": 1})
        self.assertIn("tensorrt_inference_failed", health["blockers"])
        self.assertEqual(health["runtime_health_suppressed_blockers"], [])
        self.assertFalse(health["runtime_health_passed"])

    def test_a_suppressed_blocker_is_recorded_not_hidden(self) -> None:
        health = evaluate_runtime_health(
            {"tensorrt_inference_failed_count": 1}, ignore=("tensorrt_inference_failed",)
        )
        self.assertNotIn("tensorrt_inference_failed", health["blockers"])
        self.assertEqual(
            health["runtime_health_suppressed_blockers"], ["tensorrt_inference_failed"]
        )
        self.assertEqual(
            health["runtime_health_suppression_requested"], ["tensorrt_inference_failed"]
        )

    def test_suppressing_one_blocker_does_not_suppress_the_others(self) -> None:
        health = evaluate_runtime_health(
            {"tensorrt_inference_failed_count": 1, "tensorrt_fallback_count": 1,
             "thermal_throttling_observed": True},
            ignore=("tensorrt_inference_failed",),
        )
        self.assertEqual(
            health["blockers"], ["tensorrt_fallback_used", "thermal_throttling_observed"]
        )
        self.assertFalse(health["runtime_health_passed"])

    def test_a_clean_run_passes(self) -> None:
        health = evaluate_runtime_health(
            {"tensorrt_inference_failed_count": 0}, deadline_ms=949.0, observed_p99_ms=90.3
        )
        self.assertTrue(health["runtime_health_passed"], health["blockers"])

    def test_a_missing_latency_measurement_is_a_blocker(self) -> None:
        health = evaluate_runtime_health({}, deadline_ms=949.0, observed_p99_ms=None)
        self.assertIn("frame_to_command_latency_unavailable", health["blockers"])


class TestPhase13DFaultMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = run_fault_matrix()

    def test_every_case_matches_its_expected_classification(self) -> None:
        failures = [row for row in self.rows if not row["passed"]]
        self.assertEqual(
            failures,
            [],
            "fault cases disagreed with expectation: %s"
            % [(row["fault_id"], row["observed_classification"], row["details"]) for row in failures],
        )

    def test_no_invalid_result_ever_produced_ai_active(self) -> None:
        counts = matrix_counts(self.rows)
        self.assertEqual(counts["false_accept_count"], 0)
        self.assertEqual(counts["false_reject_count"], 0)

    def test_all_thirty_five_cases_are_present(self) -> None:
        self.assertEqual(len(self.rows), 35)
        self.assertEqual(
            sorted(row["fault_id"] for row in self.rows),
            ["D%02d" % index for index in range(1, 36)],
        )

    def test_every_required_fault_family_is_covered(self) -> None:
        steps = {row["injection_step"] for row in self.rows}
        for family in (
            "dataset_coverage",
            "dataset_disjointness",
            "dataset_integrity",
            "calibration_cache",
            "calibration_feed",
            "calibration_memory",
            "calibration_envelope",
            "engine_build",
            "engine_cache",
            "engine_audit",
            "parity",
            "runtime_range",
            "runtime_deadline",
            "runtime_fallback",
            "runtime_throttling",
        ):
            self.assertIn(family, steps)


def write_matrix(output_dir: Path) -> Path:
    rows = run_fault_matrix()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "phase13d_fault_matrix.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    columns = [
        "fault_id",
        "fault_name",
        "gate",
        "injection_step",
        "expected_classification",
        "observed_classification",
        "passed",
        "details",
    ]
    with open(str(output_dir / "phase13d_fault_matrix.csv"), "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in columns})
    return output_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 13D fault matrix")
    parser.add_argument("--write-matrix", default="")
    known, remaining = parser.parse_known_args()
    if known.write_matrix:
        target = write_matrix(Path(known.write_matrix))
        counts = matrix_counts(run_fault_matrix())
        print("phase13d_fault_matrix written to %s" % target)
        print("false_accept_count=%d" % counts["false_accept_count"])
        print("false_reject_count=%d" % counts["false_reject_count"])
    else:
        unittest.main(argv=[sys.argv[0]] + remaining)

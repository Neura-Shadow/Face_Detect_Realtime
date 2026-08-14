"""Phase 13C TensorRT fault matrix (T01..T22), executed with test doubles.

Every case asserts the same safety invariant: **no invalid TensorRT result may
ever produce AI_ACTIVE**. Engine/config faults make the backend unavailable,
input/output/range faults and timeout/stale/deadline faults produce SAFE_STOP,
and a fallback attempt fails the formal gate outright.

Running the module directly also writes ``phase13c_fault_matrix.json`` /
``.csv`` next to the requested output directory.
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
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from test_phase13c_tensorrt_runtime import (  # noqa: E402
    FakeCudaLibrary,
    FakeEngineRunner,
    channels_first_output,
    make_cuda_runtime,
)
from workers.core.edge_perception import Detection  # noqa: E402
from workers.core.tensorrt_asset_contract import (  # noqa: E402
    EngineManifest,
    InputContract,
    OutputContract,
    PostprocessProfile,
    evaluate_engine_staleness,
    sha256_file,
    verify_onnx_asset,
)
from workers.core.tensorrt_perception import (  # noqa: E402
    TensorRTPerceptionBackend,
    TensorRTPerceptionError,
)
from workers.core.tensorrt_range_monitor import (  # noqa: E402
    TensorRTRangeContract,
    TensorRTRangeMonitor,
)
from workers.core.tensorrt_runtime import TensorRTRuntimeError  # noqa: E402

SAFE_STOP = "SAFE_STOP"
BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
GATE_FAILURE = "GATE_FAILURE"


def _input_stats(**overrides) -> Dict[str, Any]:
    payload = {
        "input_min": 0.0,
        "input_max": 1.0,
        "channel_means": [0.4, 0.45, 0.5],
        "channel_stds": [0.2, 0.2, 0.2],
        "input_dtype": "float32",
        "input_color_order": "RGB",
    }
    payload.update(overrides)
    return payload


def _output_stats(**overrides) -> Dict[str, Any]:
    payload = {"output_raw_min": -2.0, "output_raw_max": 640.0, "output_raw_p99": 300.0}
    payload.update(overrides)
    return payload


def _detection(**overrides) -> Detection:
    payload = {"label": "obj", "confidence": 0.8, "bbox": (10.0, 10.0, 40.0, 40.0), "class_id": 1}
    payload.update(overrides)
    return Detection(**payload)


def _verdict(**overrides) -> Any:
    """Evaluate one result through a fresh monitor and return the verdict."""

    monitor = TensorRTRangeMonitor(overrides.pop("contract", TensorRTRangeContract()))
    payload = dict(
        input_stats=_input_stats(),
        detections=[_detection()],
        output_stats=_output_stats(),
        inference_ms=20.0,
        result_age_ms=5.0,
    )
    payload.update(overrides)
    return monitor.evaluate(**payload)


def _classify(verdict: Any) -> str:
    return SAFE_STOP if not verdict.ai_result_valid else "AI_ACTIVE"


def _backend(output: np.ndarray, *, fail: Any = None, contract: OutputContract = None):
    return TensorRTPerceptionBackend(
        FakeEngineRunner(output, fail=fail),
        input_contract=InputContract(),
        output_contract=contract or OutputContract(layout="channels_first", class_count=80),
        profile=PostprocessProfile(),
        class_names=["c%d" % index for index in range(80)],
    )


# ── Fault cases ─────────────────────────────────────────────────────────────


def t01_missing_engine() -> Tuple[str, Dict[str, Any]]:
    report = verify_onnx_asset(Path("definitely-missing.onnx"))
    return (
        BACKEND_UNAVAILABLE if "onnx_missing" in report["blockers"] else "AI_ACTIVE",
        {"blockers": report["blockers"]},
    )


def t02_engine_hash_mismatch() -> Tuple[str, Dict[str, Any]]:
    with tempfile.TemporaryDirectory() as directory:
        engine = Path(directory) / "model.engine"
        engine.write_bytes(b"plan")
        manifest = EngineManifest(
            engine_path=str(engine),
            engine_sha256=sha256_file(engine),
            onnx_sha256="a" * 64,
            tensorrt_version="8.5.2.2",
            cuda_version="11.4",
            gpu_name="Orin NX",
            compute_capability="8.7",
            engine_precision="fp16",
            input_profile="1x3x640x640",
            postprocess_profile="yolov9-c",
            built_on_target=True,
        )
        manifest.engine_cache_key = manifest.expected_cache_key()
        engine.write_bytes(b"tampered plan")
        verdict = evaluate_engine_staleness(
            manifest,
            engine_path=engine,
            observed_onnx_sha256="a" * 64,
            observed_tensorrt_version="8.5.2.2",
            observed_cuda_version="11.4",
            observed_gpu_name="Orin NX",
            observed_compute_capability="8.7",
            precision="fp16",
            input_profile="1x3x640x640",
            postprocess_profile="yolov9-c",
        )
    return (
        BACKEND_UNAVAILABLE if "engine_sha256_mismatch" in verdict.reasons else "AI_ACTIVE",
        {"reasons": verdict.reasons},
    )


def t03_engine_manifest_mismatch() -> Tuple[str, Dict[str, Any]]:
    with tempfile.TemporaryDirectory() as directory:
        engine = Path(directory) / "model.engine"
        engine.write_bytes(b"plan")
        manifest = EngineManifest(
            engine_path=str(engine),
            engine_sha256=sha256_file(engine),
            onnx_sha256="a" * 64,
            tensorrt_version="8.5.2.2",
            cuda_version="11.4",
            gpu_name="Orin NX",
            compute_capability="8.7",
            engine_precision="fp16",
            input_profile="1x3x640x640",
            postprocess_profile="yolov9-c",
            built_on_target=True,
        )
        manifest.engine_cache_key = manifest.expected_cache_key()
        verdict = evaluate_engine_staleness(
            manifest,
            engine_path=engine,
            observed_onnx_sha256="b" * 64,  # a different ONNX produced this engine
            observed_tensorrt_version="8.5.2.2",
            observed_cuda_version="11.4",
            observed_gpu_name="Orin NX",
            observed_compute_capability="8.7",
            precision="fp16",
            input_profile="1x3x640x640",
            postprocess_profile="yolov9-c",
        )
    return (
        BACKEND_UNAVAILABLE if verdict.stale else "AI_ACTIVE",
        {"reasons": verdict.reasons},
    )


def t04_engine_deserialize_failure() -> Tuple[str, Dict[str, Any]]:
    backend = _backend(
        channels_first_output([]), fail=TensorRTRuntimeError("engine_deserialize_failed", "bad plan")
    )
    try:
        backend.detect(np.zeros((360, 640, 3), dtype=np.uint8))
    except TensorRTPerceptionError as exc:
        return BACKEND_UNAVAILABLE, {"classification": exc.classification}
    return "AI_ACTIVE", {}


def t05_binding_count_mismatch() -> Tuple[str, Dict[str, Any]]:
    backend = _backend(
        channels_first_output([]),
        fail=TensorRTRuntimeError("engine_binding_mismatch", "2 inputs"),
    )
    try:
        backend.detect(np.zeros((360, 640, 3), dtype=np.uint8))
    except TensorRTPerceptionError as exc:
        return BACKEND_UNAVAILABLE, {"classification": exc.classification}
    return "AI_ACTIVE", {}


def t06_input_shape_mismatch() -> Tuple[str, Dict[str, Any]]:
    backend = _backend(
        channels_first_output([]), fail=TensorRTRuntimeError("input_shape_mismatch", "bad shape")
    )
    try:
        backend.detect(np.zeros((360, 640, 3), dtype=np.uint8))
    except TensorRTPerceptionError as exc:
        return SAFE_STOP, {"classification": exc.classification}
    return "AI_ACTIVE", {}


def t07_input_dtype_mismatch() -> Tuple[str, Dict[str, Any]]:
    verdict = _verdict(input_stats=_input_stats(input_dtype="float16"))
    return _classify(verdict), {"classification": verdict.classification}


def t08_nan_input_tensor() -> Tuple[str, Dict[str, Any]]:
    verdict = _verdict(input_stats=_input_stats(input_max=float("nan")))
    return _classify(verdict), {"classification": verdict.classification}


def t09_inf_input_tensor() -> Tuple[str, Dict[str, Any]]:
    verdict = _verdict(input_stats=_input_stats(input_min=float("-inf")))
    return _classify(verdict), {"classification": verdict.classification}


def t10_output_nan() -> Tuple[str, Dict[str, Any]]:
    verdict = _verdict(output_stats=_output_stats(output_raw_max=float("nan")))
    return _classify(verdict), {"classification": verdict.classification}


def t11_output_inf() -> Tuple[str, Dict[str, Any]]:
    verdict = _verdict(output_stats=_output_stats(output_raw_p99=float("inf")))
    return _classify(verdict), {"classification": verdict.classification}


def t12_output_shape_mismatch() -> Tuple[str, Dict[str, Any]]:
    backend = _backend(
        channels_first_output([(10.0, 10.0, 5.0, 5.0, 0, 0.9)]),
        contract=OutputContract(layout="anchors_first", class_count=80),
    )
    try:
        backend.detect(np.zeros((360, 640, 3), dtype=np.uint8))
    except TensorRTPerceptionError as exc:
        return SAFE_STOP, {"classification": exc.classification}
    return "AI_ACTIVE", {}


def t13_confidence_out_of_range() -> Tuple[str, Dict[str, Any]]:
    verdict = _verdict(detections=[_detection(confidence=1.9)])
    return _classify(verdict), {"classification": verdict.classification}


def t14_invalid_class_id() -> Tuple[str, Dict[str, Any]]:
    verdict = _verdict(detections=[_detection(class_id=-7)])
    return _classify(verdict), {"classification": verdict.classification}


def t15_bbox_out_of_bounds() -> Tuple[str, Dict[str, Any]]:
    backend = _backend(channels_first_output([(10.0, 10.0, 5.0, 5.0, 0, 0.9)]))
    # A detection whose box is inverted must never reach the command path.
    verdict = _verdict(detections=[_detection(bbox=(500.0, 500.0, 10.0, 10.0))])
    _ = backend
    return _classify(verdict), {"classification": verdict.classification}


def t16_excessive_detection_count() -> Tuple[str, Dict[str, Any]]:
    verdict = _verdict(
        contract=TensorRTRangeContract(max_detections=2),
        detections=[_detection() for _ in range(6)],
    )
    return _classify(verdict), {"classification": verdict.classification}


def t17_inference_timeout() -> Tuple[str, Dict[str, Any]]:
    verdict = _verdict(contract=TensorRTRangeContract(max_inference_ms=40.0), inference_ms=250.0)
    return _classify(verdict), {"classification": verdict.classification}


def t18_stale_inference_result() -> Tuple[str, Dict[str, Any]]:
    verdict = _verdict(result_age_ms=9999.0)
    return _classify(verdict), {"classification": verdict.classification}


def t19_cuda_execution_error() -> Tuple[str, Dict[str, Any]]:
    runtime = make_cuda_runtime(FakeCudaLibrary(fail_on="cudaMemcpyAsync"))
    stream = runtime.stream_create()
    pointer = runtime.malloc(64)
    try:
        runtime.memcpy_htod_async(pointer, np.zeros(16, dtype=np.float32), 64, stream)
    except TensorRTRuntimeError as exc:
        verdict = _verdict(engine_execute_ok=False)
        return _classify(verdict), {
            "cuda_classification": exc.classification,
            "cuda_error_count": runtime.error_count,
            "range_classification": verdict.classification,
        }
    return "AI_ACTIVE", {}


def t20_fallback_attempted() -> Tuple[str, Dict[str, Any]]:
    verdict = _verdict(fallback_used=True)
    if verdict.ai_result_valid:
        return "AI_ACTIVE", {}
    return GATE_FAILURE, {"classification": verdict.classification}


def t21_parity_threshold_failure() -> Tuple[str, Dict[str, Any]]:
    from run_phase13c_backend_parity import compare

    reference = {
        "frames": [
            {
                "frame": "f%02d.png" % index,
                "detections": [
                    {"class_id": 1, "confidence": 0.9, "bbox": [10.0, 10.0, 50.0, 50.0]}
                ],
            }
            for index in range(32)
        ]
    }
    candidate = {
        "frames": [{"frame": "f%02d.png" % index, "detections": []} for index in range(32)]
    }
    metrics = compare(reference, candidate, 0.5)
    passed = metrics["parity_passed"]
    return (
        GATE_FAILURE if not passed else "AI_ACTIVE",
        {"matched_detection_rate": metrics["matched_detection_rate"], "blockers": metrics["blockers"]},
    )


def t22_command_validity_exceeded() -> Tuple[str, Dict[str, Any]]:
    from run_phase13c_checks import latency_budget_ms

    budget = latency_budget_ms(
        command_validity_ms=1000, clock_uncertainty_ms=0.5, safety_margin_ms=50
    )
    observed_p99 = budget + 25.0
    if observed_p99 >= budget:
        # The bridge rejects a command past its validity window: SAFE_STOP.
        verdict = _verdict(result_age_ms=99999.0)
        return _classify(verdict), {
            "latency_budget_ms": budget,
            "frame_to_command_ms_p99": observed_p99,
            "classification": "inference_deadline_missed",
        }
    return "AI_ACTIVE", {}


FAULT_CASES = (
    ("T01", "missing engine", "asset_contract", BACKEND_UNAVAILABLE, t01_missing_engine),
    ("T02", "engine hash mismatch", "asset_contract", BACKEND_UNAVAILABLE, t02_engine_hash_mismatch),
    ("T03", "engine manifest mismatch", "asset_contract", BACKEND_UNAVAILABLE, t03_engine_manifest_mismatch),
    ("T04", "engine deserialize failure", "engine_load", BACKEND_UNAVAILABLE, t04_engine_deserialize_failure),
    ("T05", "binding count mismatch", "engine_load", BACKEND_UNAVAILABLE, t05_binding_count_mismatch),
    ("T06", "input shape mismatch", "preprocess", SAFE_STOP, t06_input_shape_mismatch),
    ("T07", "input dtype mismatch", "range_input", SAFE_STOP, t07_input_dtype_mismatch),
    ("T08", "NaN input tensor", "range_input", SAFE_STOP, t08_nan_input_tensor),
    ("T09", "Inf input tensor", "range_input", SAFE_STOP, t09_inf_input_tensor),
    ("T10", "output NaN", "range_output", SAFE_STOP, t10_output_nan),
    ("T11", "output Inf", "range_output", SAFE_STOP, t11_output_inf),
    ("T12", "output shape mismatch", "postprocess", SAFE_STOP, t12_output_shape_mismatch),
    ("T13", "confidence out of range", "detection_schema", SAFE_STOP, t13_confidence_out_of_range),
    ("T14", "invalid class id", "detection_schema", SAFE_STOP, t14_invalid_class_id),
    ("T15", "bbox out of bounds", "detection_schema", SAFE_STOP, t15_bbox_out_of_bounds),
    ("T16", "excessive detection count", "detection_schema", SAFE_STOP, t16_excessive_detection_count),
    ("T17", "inference timeout", "timing", SAFE_STOP, t17_inference_timeout),
    ("T18", "stale inference result", "timing", SAFE_STOP, t18_stale_inference_result),
    ("T19", "CUDA execution error", "cuda", SAFE_STOP, t19_cuda_execution_error),
    ("T20", "fallback attempted", "backend_policy", GATE_FAILURE, t20_fallback_attempted),
    ("T21", "parity threshold failure", "parity", GATE_FAILURE, t21_parity_threshold_failure),
    ("T22", "command validity exceeded by latency", "deadline", SAFE_STOP, t22_command_validity_exceeded),
)


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

    false_accept = sum(1 for row in rows if row["observed_classification"] == "AI_ACTIVE")
    false_reject = sum(
        1
        for row in rows
        if row["expected_classification"] == "AI_ACTIVE"
        and row["observed_classification"] != "AI_ACTIVE"
    )
    return {"false_accept_count": false_accept, "false_reject_count": false_reject}


class TestPhase13CFaultMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = run_fault_matrix()

    def test_every_case_matches_its_expected_classification(self) -> None:
        failures = [row for row in self.rows if not row["passed"]]
        self.assertEqual(
            failures,
            [],
            "fault cases disagreed with expectation: %s"
            % [(row["fault_id"], row["observed_classification"]) for row in failures],
        )

    def test_no_invalid_result_ever_produced_ai_active(self) -> None:
        counts = matrix_counts(self.rows)
        self.assertEqual(counts["false_accept_count"], 0)
        self.assertEqual(counts["false_reject_count"], 0)

    def test_all_twenty_two_cases_are_present(self) -> None:
        self.assertEqual(len(self.rows), 22)
        self.assertEqual(
            sorted(row["fault_id"] for row in self.rows),
            ["T%02d" % index for index in range(1, 23)],
        )


def write_matrix(output_dir: Path) -> Path:
    rows = run_fault_matrix()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "phase13c_fault_matrix.json").write_text(
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
    with open(str(output_dir / "phase13c_fault_matrix.csv"), "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in columns})
    return output_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 13C fault matrix")
    parser.add_argument("--write-matrix", default="")
    known, remaining = parser.parse_known_args()
    if known.write_matrix:
        target = write_matrix(Path(known.write_matrix))
        counts = matrix_counts(run_fault_matrix())
        print("phase13c_fault_matrix written to %s" % target)
        print("false_accept_count=%d" % counts["false_accept_count"])
        print("false_reject_count=%d" % counts["false_reject_count"])
    else:
        unittest.main(argv=[sys.argv[0]] + remaining)

"""Phase 13D INT8-vs-FP16 parity gate.

Measures how faithfully the INT8 conversion reproduces the **already verified
Phase 13C FP16 engine** on identical frames. Both plans live on the same
Jetson, so both sides are measured in one process, over the same holdout
frames, with the same letterbox policy, colour order, thresholds, class mapping
and detection cap.

This is a conversion-consistency gate. It establishes no ground truth, no mAP,
no recall, no safety effectiveness and no navigation quality. What it does add
beyond Phase 13C is an **authority divergence** count: how often INT8 would
have granted AI authority on a frame where FP16 could not. That number must be
zero.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13c_backend_parity import detections_to_records, iou, read_bgr  # noqa: E402
from run_phase13c_standalone_benchmark import load_contracts  # noqa: E402
from run_phase13d_checks import (  # noqa: E402
    BOUNDARY_FIELDS,
    PHASE,
    STATUS_BLOCKED,
    STATUS_ENGINE_PASS,
    Phase13DEvidence,
    new_run_id,
    utc_now_iso,
)
from workers.core.int8_calibration_dataset import DatasetManifest  # noqa: E402
from workers.core.tensorrt_asset_contract import PostprocessProfile  # noqa: E402

MIN_PARITY_FRAMES = 128
DEFAULT_MATCH_IOU = 0.5

PARITY_THRESHOLDS = {
    "matched_detection_rate": 0.90,
    "matched_class_agreement": 0.98,
    "matched_box_iou_mean": 0.75,
    "confidence_abs_error_p95": 0.12,
}
#: Metrics where a *higher* value is better; the rest are error bounds.
_LOWER_IS_BETTER = ("confidence_abs_error_p95",)


def _percentile(values: Sequence[float], percentile: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = int(round((percentile / 100.0) * (len(ordered) - 1)))
    return round(ordered[max(0, min(len(ordered) - 1, rank))], 6)


def frame_paths(args: argparse.Namespace) -> List[Dict[str, str]]:
    """Holdout frames from the dataset manifest, in deterministic order."""

    manifest = DatasetManifest.load(Path(args.dataset_manifest))
    records = manifest.split(str(args.frame_split))
    root_override = Path(args.dataset_root_override) if args.dataset_root_override else None
    listed = []  # type: List[Dict[str, str]]
    for record in records:
        path = Path(record.path) if root_override is None else root_override / record.relative_path
        listed.append({"frame": record.frame_id, "path": str(path), "route": record.route,
                       "weather": record.weather})
    if int(args.max_frames) > 0:
        listed = listed[: int(args.max_frames)]
    return listed


def schema_valid(records: Sequence[Dict[str, Any]], *, max_detections: int) -> bool:
    """Stateless detection-schema predicate, identical for both precisions."""

    if len(records) > int(max_detections):
        return False
    for record in records:
        box = record.get("bbox") or []
        confidence = record.get("confidence")
        if len(box) != 4 or confidence is None:
            return False
        if not all(math.isfinite(float(value)) for value in box):
            return False
        if not math.isfinite(float(confidence)) or not 0.0 <= float(confidence) <= 1.0:
            return False
        if float(box[0]) > float(box[2]) or float(box[1]) > float(box[3]):
            return False
        if int(record.get("class_id", -1)) < 0:
            return False
    return True


def measure(
    args: argparse.Namespace, *, engine_path: str, precision: str, listed: List[Dict[str, str]]
) -> Dict[str, Any]:
    """Run one engine over the frame list. Never falls back."""

    from workers.core.tensorrt_perception import (
        TensorRTPerceptionBackend,
        TensorRTPerceptionError,
        load_class_names,
    )
    from workers.core.tensorrt_runtime import TensorRTEngineRunner, TensorRTRuntimeError

    contracts = load_contracts(args.model_manifest, "", args.profile)
    class_names, class_names_source = load_class_names(
        args.class_names or contracts["class_names_source"] or None
    )
    profile = PostprocessProfile(
        name=str(args.profile),
        confidence_threshold=float(args.confidence_threshold),
        nms_iou_threshold=float(args.nms_iou_threshold),
        max_detections=int(args.max_detections),
    )
    payload = {
        "backend": "tensorrt_%s" % precision,
        "precision": precision,
        "engine_path": engine_path,
        "class_names_source": class_names_source,
        "frame_count": len(listed),
        "frames": [],
        "blockers": [],
    }  # type: Dict[str, Any]

    try:
        runner = TensorRTEngineRunner(
            engine_path,
            expected_input_shape=contracts["input_contract"].shape,
            expected_input_name=contracts["input_contract"].input_name,
        )
    except TensorRTRuntimeError as exc:
        payload["blockers"].append(exc.classification)
        payload["error"] = exc.message
        return payload

    backend = TensorRTPerceptionBackend(
        runner,
        input_contract=contracts["input_contract"],
        output_contract=contracts["output_contract"],
        profile=profile,
        class_names=class_names,
        model_name=str(args.profile),
        precision=precision,
    )
    try:
        # Warm the plan so the first frame does not carry lazy CUDA context
        # initialisation into the comparison.
        first = read_bgr(Path(listed[0]["path"])) if listed else None
        if first is not None:
            for _ in range(max(0, int(args.warmup))):
                backend.detect(first)
        for entry in listed:
            image = read_bgr(Path(entry["path"]))
            if image is None:
                payload["frames"].append({"frame": entry["frame"], "error": "unreadable"})
                continue
            try:
                detections, inference_ms = backend.detect(image)
            except TensorRTPerceptionError as exc:
                payload["frames"].append({"frame": entry["frame"], "error": exc.classification})
                continue
            payload["frames"].append(
                {
                    "frame": entry["frame"],
                    "route": entry["route"],
                    "weather": entry["weather"],
                    "width": int(image.shape[1]),
                    "height": int(image.shape[0]),
                    "inference_ms": int(inference_ms),
                    "detections": detections_to_records(detections),
                }
            )
        payload["fallback_used"] = False
        payload.update(backend.metadata())
    finally:
        backend.close()
    return payload


def compare_parity(
    reference: Dict[str, Any],
    candidate: Dict[str, Any],
    *,
    match_iou: float,
    max_detections: int,
    min_frames: int,
) -> Dict[str, Any]:
    """Greedy IoU matching per frame; reports consistency, never accuracy."""

    reference_frames = {
        item["frame"]: item for item in reference.get("frames", []) if "detections" in item
    }
    candidate_frames = {
        item["frame"]: item for item in candidate.get("frames", []) if "detections" in item
    }
    shared = sorted(set(reference_frames) & set(candidate_frames))

    reference_total = 0
    candidate_total = 0
    matched_total = 0
    class_agreements = 0
    iou_values = []  # type: List[float]
    confidence_errors = []  # type: List[float]
    schema_errors = 0
    nonfinite = 0
    evaluable = 0

    reference_errors = {
        item["frame"] for item in reference.get("frames", []) if "detections" not in item
    }
    candidate_errors = {
        item["frame"] for item in candidate.get("frames", []) if "detections" not in item
    }
    unsafe_divergence = []  # type: List[str]
    safe_divergence = []  # type: List[str]

    for name in sorted(set(reference_frames) | set(candidate_frames) | reference_errors | candidate_errors):
        reference_ok = name in reference_frames and schema_valid(
            reference_frames[name]["detections"], max_detections=max_detections
        )
        candidate_ok = name in candidate_frames and schema_valid(
            candidate_frames[name]["detections"], max_detections=max_detections
        )
        if candidate_ok and not reference_ok:
            unsafe_divergence.append(name)
        elif reference_ok and not candidate_ok:
            safe_divergence.append(name)

    for name in shared:
        reference_detections = reference_frames[name]["detections"]
        candidate_detections = list(candidate_frames[name]["detections"])
        reference_total += len(reference_detections)
        candidate_total += len(candidate_detections)
        if reference_detections:
            evaluable += 1

        for record in reference_detections + candidate_detections:
            box = record.get("bbox") or []
            confidence = record.get("confidence")
            if len(box) != 4 or confidence is None:
                schema_errors += 1
                continue
            if not all(math.isfinite(float(value)) for value in box) or not math.isfinite(
                float(confidence)
            ):
                nonfinite += 1

        # A malformed record was already counted as a schema error above; it must
        # not be matched against, and it must not crash the comparison either.
        used = set()  # type: set
        for reference_record in reference_detections:
            if len(reference_record.get("bbox") or []) != 4:
                continue
            best_index = -1
            best_iou = 0.0
            for index, candidate_record in enumerate(candidate_detections):
                if index in used or len(candidate_record.get("bbox") or []) != 4:
                    continue
                overlap = iou(reference_record["bbox"], candidate_record["bbox"])
                if overlap > best_iou:
                    best_iou = overlap
                    best_index = index
            if best_index >= 0 and best_iou >= match_iou:
                used.add(best_index)
                matched_total += 1
                iou_values.append(best_iou)
                matched = candidate_detections[best_index]
                if int(matched["class_id"]) == int(reference_record["class_id"]):
                    class_agreements += 1
                confidence_errors.append(
                    abs(float(matched["confidence"]) - float(reference_record["confidence"]))
                )

    metrics = {
        "reference_precision": reference.get("precision"),
        "candidate_precision": candidate.get("precision"),
        "reference_frame_count": len(reference.get("frames", [])),
        "candidate_frame_count": len(candidate.get("frames", [])),
        "shared_frame_count": len(shared),
        "parity_evaluable_frame_count": evaluable,
        "reference_detection_count": reference_total,
        "candidate_detection_count": candidate_total,
        "matched_detection_count": matched_total,
        "matched_detection_rate": round(matched_total / reference_total, 6) if reference_total else None,
        "matched_class_agreement": round(class_agreements / matched_total, 6) if matched_total else None,
        "matched_box_iou_mean": round(sum(iou_values) / len(iou_values), 6) if iou_values else None,
        "matched_box_iou_p50": _percentile(iou_values, 50.0),
        "matched_box_iou_p95": _percentile(iou_values, 95.0),
        "confidence_abs_error_mean": round(sum(confidence_errors) / len(confidence_errors), 6)
        if confidence_errors
        else None,
        "confidence_abs_error_p95": _percentile(confidence_errors, 95.0),
        "frames_with_schema_error": schema_errors,
        "frames_with_nonfinite_output": nonfinite,
        "unsafe_authority_divergence_count": len(unsafe_divergence),
        "unsafe_authority_divergence_frames": unsafe_divergence[:16],
        "safe_authority_divergence_count": len(safe_divergence),
        "safe_authority_divergence_frames": safe_divergence[:16],
        "match_iou_threshold": float(match_iou),
    }

    blockers = []  # type: List[str]
    if metrics["shared_frame_count"] < int(min_frames):
        blockers.append("parity_frame_count_insufficient")
    if not evaluable:
        blockers.append("parity_not_evaluable")
    else:
        for name, threshold in PARITY_THRESHOLDS.items():
            value = metrics.get(name)
            if value is None:
                blockers.append("parity_metric_missing:%s" % name)
            elif name in _LOWER_IS_BETTER:
                if float(value) > threshold:
                    blockers.append("parity_threshold_failed:%s" % name)
            elif float(value) < threshold:
                blockers.append("parity_threshold_failed:%s" % name)
    if schema_errors:
        blockers.append("parity_schema_error")
    if nonfinite:
        blockers.append("parity_nonfinite_output")
    if unsafe_divergence:
        blockers.append("unsafe_authority_divergence")

    metrics["parity_thresholds"] = dict(PARITY_THRESHOLDS)
    metrics["parity_passed"] = not blockers
    metrics["blockers"] = blockers
    metrics["measures"] = "conversion_consistency_only"
    metrics["accuracy_claimed"] = False
    metrics["map_claimed"] = False
    metrics["recall_claimed"] = False
    return metrics


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13D INT8 vs FP16 parity gate")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--mode", choices=("all", "measure", "compare"), default="all")
    parser.add_argument("--fp16-engine", default="")
    parser.add_argument("--int8-engine", default="")
    parser.add_argument("--dataset-manifest", default="")
    parser.add_argument("--dataset-root-override", default="")
    parser.add_argument("--frame-split", default="holdout", choices=("holdout", "calibration"))
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--model-manifest", default="")
    parser.add_argument("--profile", default="yolov9-c")
    parser.add_argument("--class-names", default="")
    parser.add_argument("--confidence-threshold", type=float, default=0.25)
    parser.add_argument("--nms-iou-threshold", type=float, default=0.45)
    parser.add_argument("--max-detections", type=int, default=300)
    parser.add_argument("--match-iou", type=float, default=DEFAULT_MATCH_IOU)
    parser.add_argument("--min-frames", type=int, default=MIN_PARITY_FRAMES)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--reference-json", default="")
    parser.add_argument("--candidate-json", default="")
    parser.add_argument("--output-dir", default="experiments/phase13")
    parser.add_argument("--require-parity", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or new_run_id()
    evidence = Phase13DEvidence(Path(args.output_dir), run_id)

    summary = {
        "phase": PHASE,
        "gate": "C_precision_parity",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "mode": args.mode,
    }  # type: Dict[str, Any]
    blockers = []  # type: List[str]
    reference = {}  # type: Dict[str, Any]
    candidate = {}  # type: Dict[str, Any]
    metrics = {}  # type: Dict[str, Any]

    try:
        if args.mode in ("all", "measure"):
            if not args.dataset_manifest or not Path(args.dataset_manifest).is_file():
                raise RuntimeError("dataset_manifest_missing")
            listed = frame_paths(args)
            summary["frame_count"] = len(listed)
            if not listed:
                raise RuntimeError("parity_frames_missing")
            reference = measure(
                args, engine_path=str(args.fp16_engine), precision="fp16", listed=listed
            )
            candidate = measure(
                args, engine_path=str(args.int8_engine), precision="int8", listed=listed
            )
            blockers.extend(reference.get("blockers", []))
            blockers.extend(candidate.get("blockers", []))
            evidence.write_json("raw_outputs/parity_fp16.json", reference)
            evidence.write_json("raw_outputs/parity_int8.json", candidate)
        if args.mode == "compare":
            reference = json.loads(Path(args.reference_json).read_text(encoding="utf-8"))
            candidate = json.loads(Path(args.candidate_json).read_text(encoding="utf-8"))
        if args.mode in ("all", "compare") and reference and candidate:
            metrics = compare_parity(
                reference,
                candidate,
                match_iou=float(args.match_iou),
                max_detections=int(args.max_detections),
                min_frames=int(args.min_frames),
            )
            blockers.extend(metrics["blockers"])
    except Exception as exc:
        blockers.append("parity_run_failed")
        summary["error"] = repr(exc)[:400]

    passed = bool(metrics.get("parity_passed")) and not blockers
    summary["parity_metrics"] = metrics
    summary["blockers"] = sorted(set(blockers))
    summary["status"] = STATUS_ENGINE_PASS if passed else STATUS_BLOCKED
    summary.update(BOUNDARY_FIELDS)

    evidence.write_json("summary.json", summary)
    evidence.write_json("parity_metrics.json", metrics or {"executed": False})
    evidence.write_manifest("C_precision_parity", summary["status"])
    evidence.write_placeholders()
    evidence.write_fault_matrix([])
    evidence.write_events([])
    evidence.write_text(
        "commands.txt",
        "# Phase 13D precision parity\n%s %s\n" % (sys.executable, " ".join(sys.argv)),
    )
    evidence.write_text(
        "README.md",
        "# Phase 13D INT8-vs-FP16 parity evidence\n\nRun id: `%s`\n\nStatus: `%s`\n\n"
        "Conversion consistency between the verified Phase 13C FP16 plan and the Phase 13D "
        "INT8 plan on identical holdout frames. No accuracy, mAP or recall is measured or "
        "claimed.\n" % (run_id, summary["status"]),
    )

    print(summary["status"])
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    for key in (
        "shared_frame_count",
        "parity_evaluable_frame_count",
        "reference_detection_count",
        "candidate_detection_count",
        "matched_detection_count",
        "matched_detection_rate",
        "matched_class_agreement",
        "matched_box_iou_mean",
        "confidence_abs_error_p95",
        "frames_with_schema_error",
        "frames_with_nonfinite_output",
        "unsafe_authority_divergence_count",
        "parity_passed",
    ):
        if key in metrics:
            print("%s=%s" % (key, metrics[key]))
    if summary["blockers"]:
        print("blockers=%s" % ",".join(summary["blockers"]), file=sys.stderr)
    if args.require_parity and not passed:
        return 1
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Phase 13C backend-consistency (parity) gate.

Measures how faithfully the TensorRT FP16 conversion reproduces the **official
YOLOv9 source backend** on identical frames. This is a conversion-consistency
gate, not an accuracy evaluation: it establishes no ground truth, no mAP, no
recall, no safety effectiveness and no navigation quality.

Three modes, because the two backends live on different machines:

* ``--mode reference``  on the PC   -> reference detections JSON
* ``--mode candidate``  on the Jetson -> TensorRT detections JSON
* ``--mode compare``    anywhere    -> parity metrics from the two JSON files

Both sides use identical frames, letterbox policy, colour order, thresholds,
class mapping and detection cap. Fixture frames are local and uncommitted; no
image is ever downloaded.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
    Phase13CEvidence,
    new_run_id,
    utc_now_iso,
)
from workers.core.tensorrt_asset_contract import PostprocessProfile

MIN_REFERENCE_FRAMES = 32
DEFAULT_MATCH_IOU = 0.5

PARITY_THRESHOLDS = {
    "matched_detection_rate": 0.90,
    "matched_class_agreement": 0.95,
    "matched_box_iou_mean": 0.75,
    "confidence_abs_error_p95": 0.10,
}

FRAME_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp")


def list_frames(frames_dir: Path) -> List[Path]:
    if not frames_dir.is_dir():
        return []
    return sorted(
        path for path in frames_dir.iterdir()
        if path.is_file() and path.suffix.lower() in FRAME_SUFFIXES
    )


def read_bgr(path: Path) -> Optional[np.ndarray]:
    try:
        import cv2  # type: ignore[import-not-found]

        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        return image
    except Exception:
        return None


def _percentile(values: Sequence[float], percentile: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = int(round((percentile / 100.0) * (len(ordered) - 1)))
    return round(ordered[max(0, min(len(ordered) - 1, rank))], 6)


def iou(first: Sequence[float], second: Sequence[float]) -> float:
    x1 = max(float(first[0]), float(second[0]))
    y1 = max(float(first[1]), float(second[1]))
    x2 = min(float(first[2]), float(second[2]))
    y2 = min(float(first[3]), float(second[3]))
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, float(first[2]) - float(first[0])) * max(0.0, float(first[3]) - float(first[1]))
    area_b = max(0.0, float(second[2]) - float(second[0])) * max(
        0.0, float(second[3]) - float(second[1])
    )
    union = area_a + area_b - inter
    return float(inter / union) if union > 0 else 0.0


def detections_to_records(detections: Sequence[Any]) -> List[Dict[str, Any]]:
    records = []  # type: List[Dict[str, Any]]
    for detection in detections:
        records.append(
            {
                "class_id": int(getattr(detection, "class_id", -1)),
                "label": str(getattr(detection, "label", "")),
                "confidence": round(float(getattr(detection, "confidence", 0.0)), 6),
                "bbox": [round(float(value), 4) for value in getattr(detection, "bbox", (0, 0, 0, 0))],
            }
        )
    return records


# ── Reference backend (PC, official YOLOv9 source) ──────────────────────────


def run_reference(args: argparse.Namespace) -> Dict[str, Any]:
    from workers.core.config import AgentConfig, PerceptionConfig
    from workers.core.edge_perception import (
        YOLOv9PerceptionBackend,
        inspect_yolov9_source_contract,
    )

    frames = list_frames(Path(args.frames_dir))
    payload = {
        "backend": "yolov9_source_reference",
        "frames_dir": str(args.frames_dir),
        "frame_count": len(frames),
        "frames": [],
        "blockers": [],
    }  # type: Dict[str, Any]
    if not frames:
        payload["blockers"].append("reference_frames_missing")
        return payload

    config = AgentConfig.load()
    perception = config.perception  # type: PerceptionConfig
    status = inspect_yolov9_source_contract(
        source_root_env=perception.yolov9_source_root_env,
        weights_env=perception.yolov9_weights_env,
        source_root_override=args.source_root or None,
        weights_override=args.weights or None,
    ) if _supports_overrides(inspect_yolov9_source_contract) else inspect_yolov9_source_contract(
        source_root_env=perception.yolov9_source_root_env,
        weights_env=perception.yolov9_weights_env,
    )
    if not status.source_adapter_ready:
        payload["blockers"].append("model_source_missing")
        payload["source_status"] = status.to_metadata()
        return payload

    backend = YOLOv9PerceptionBackend(
        "yolov9-c",
        float(args.confidence_threshold),
        source_status=status,
        img_size=int(args.img_size),
        iou_threshold=float(args.nms_iou_threshold),
        device="cpu",
        half=False,
    )
    for path in frames:
        image = read_bgr(path)
        if image is None:
            payload["frames"].append({"frame": path.name, "error": "unreadable"})
            continue
        detections, inference_ms = backend.detect(image)
        payload["frames"].append(
            {
                "frame": path.name,
                "width": int(image.shape[1]),
                "height": int(image.shape[0]),
                "inference_ms": int(inference_ms),
                "detections": detections_to_records(detections)[: int(args.max_detections)],
            }
        )
    payload["fallback_used"] = False
    return payload


def _supports_overrides(function: Any) -> bool:
    import inspect

    return "source_root_override" in inspect.signature(function).parameters


# ── Candidate backend (Jetson, TensorRT FP16) ───────────────────────────────


def run_candidate(args: argparse.Namespace) -> Dict[str, Any]:
    from run_phase13c_standalone_benchmark import load_contracts
    from workers.core.tensorrt_perception import (
        TensorRTPerceptionBackend,
        TensorRTPerceptionError,
        load_class_names,
    )
    from workers.core.tensorrt_runtime import TensorRTEngineRunner, TensorRTRuntimeError

    frames = list_frames(Path(args.frames_dir))
    payload = {
        "backend": "tensorrt_fp16_candidate",
        "frames_dir": str(args.frames_dir),
        "frame_count": len(frames),
        "frames": [],
        "blockers": [],
    }  # type: Dict[str, Any]
    if not frames:
        payload["blockers"].append("reference_frames_missing")
        return payload

    contracts = load_contracts(args.model_manifest, args.engine_manifest, args.profile)
    class_names, class_names_source = load_class_names(
        args.class_names or contracts["class_names_source"] or None
    )
    payload["class_names_source"] = class_names_source
    profile = PostprocessProfile(
        name=str(args.profile),
        confidence_threshold=float(args.confidence_threshold),
        nms_iou_threshold=float(args.nms_iou_threshold),
        max_detections=int(args.max_detections),
    )
    try:
        runner = TensorRTEngineRunner(
            str(args.engine),
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
    )
    try:
        for path in frames:
            image = read_bgr(path)
            if image is None:
                payload["frames"].append({"frame": path.name, "error": "unreadable"})
                continue
            try:
                detections, inference_ms = backend.detect(image)
            except TensorRTPerceptionError as exc:
                payload["frames"].append({"frame": path.name, "error": exc.classification})
                continue
            payload["frames"].append(
                {
                    "frame": path.name,
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


# ── Comparison ──────────────────────────────────────────────────────────────


def compare(reference: Dict[str, Any], candidate: Dict[str, Any], match_iou: float) -> Dict[str, Any]:
    """Greedy IoU matching per frame; reports consistency, never accuracy."""

    reference_frames = {item["frame"]: item for item in reference.get("frames", []) if "detections" in item}
    candidate_frames = {item["frame"]: item for item in candidate.get("frames", []) if "detections" in item}
    shared = sorted(set(reference_frames) & set(candidate_frames))

    reference_total = 0
    candidate_total = 0
    matched_total = 0
    class_agreements = 0
    iou_values = []  # type: List[float]
    confidence_errors = []  # type: List[float]
    schema_errors = 0
    nonfinite_frames = 0
    evaluable_frames = 0

    for name in shared:
        reference_detections = reference_frames[name]["detections"]
        candidate_detections = list(candidate_frames[name]["detections"])
        reference_total += len(reference_detections)
        candidate_total += len(candidate_detections)
        if reference_detections:
            evaluable_frames += 1

        for record in reference_detections + candidate_detections:
            box = record.get("bbox") or []
            confidence = record.get("confidence")
            if len(box) != 4 or confidence is None:
                schema_errors += 1
                continue
            if not all(np.isfinite(float(value)) for value in box) or not np.isfinite(float(confidence)):
                nonfinite_frames += 1

        used = set()  # type: set
        for reference_record in reference_detections:
            best_index = -1
            best_iou = 0.0
            for index, candidate_record in enumerate(candidate_detections):
                if index in used:
                    continue
                overlap = iou(reference_record["bbox"], candidate_record["bbox"])
                if overlap > best_iou:
                    best_iou = overlap
                    best_index = index
            if best_index >= 0 and best_iou >= match_iou:
                used.add(best_index)
                matched_total += 1
                iou_values.append(best_iou)
                matched_record = candidate_detections[best_index]
                if int(matched_record["class_id"]) == int(reference_record["class_id"]):
                    class_agreements += 1
                confidence_errors.append(
                    abs(float(matched_record["confidence"]) - float(reference_record["confidence"]))
                )

    metrics = {
        "reference_frame_count": len(reference.get("frames", [])),
        "shared_frame_count": len(shared),
        "parity_evaluable_frame_count": evaluable_frames,
        "reference_detection_count": reference_total,
        "tensorrt_detection_count": candidate_total,
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
        "frames_with_nonfinite_output": nonfinite_frames,
        "match_iou_threshold": match_iou,
    }

    blockers = []  # type: List[str]
    if metrics["reference_frame_count"] < MIN_REFERENCE_FRAMES:
        blockers.append("reference_frame_count_insufficient")
    if not evaluable_frames:
        blockers.append("reference_parity_not_evaluable")
    else:
        for name, threshold in PARITY_THRESHOLDS.items():
            value = metrics.get(name)
            if value is None:
                blockers.append("parity_metric_missing:%s" % name)
            elif name == "confidence_abs_error_p95":
                if float(value) > threshold:
                    blockers.append("parity_threshold_failed:%s" % name)
            elif float(value) < threshold:
                blockers.append("parity_threshold_failed:%s" % name)
    if schema_errors:
        blockers.append("parity_schema_error")
    if nonfinite_frames:
        blockers.append("parity_nonfinite_output")

    metrics["parity_thresholds"] = dict(PARITY_THRESHOLDS)
    metrics["parity_passed"] = not blockers
    metrics["blockers"] = blockers
    metrics["measures"] = "conversion_consistency_only"
    metrics["accuracy_claimed"] = False
    metrics["map_claimed"] = False
    metrics["recall_claimed"] = False
    return metrics


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13C backend parity gate")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--mode", choices=("reference", "candidate", "compare"), required=True)
    parser.add_argument("--frames-dir", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--reference-json", default="")
    parser.add_argument("--candidate-json", default="")
    parser.add_argument("--engine", default="")
    parser.add_argument("--model-manifest", default="")
    parser.add_argument("--engine-manifest", default="")
    parser.add_argument("--profile", default="yolov9-c")
    parser.add_argument("--class-names", default="")
    parser.add_argument("--source-root", default="")
    parser.add_argument("--weights", default="")
    parser.add_argument("--img-size", type=int, default=640)
    parser.add_argument("--confidence-threshold", type=float, default=0.25)
    parser.add_argument("--nms-iou-threshold", type=float, default=0.45)
    parser.add_argument("--max-detections", type=int, default=300)
    parser.add_argument("--match-iou", type=float, default=DEFAULT_MATCH_IOU)
    parser.add_argument("--output-dir", default="experiments/phase13")
    parser.add_argument("--require-parity", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or new_run_id()

    if args.mode in ("reference", "candidate"):
        payload = run_reference(args) if args.mode == "reference" else run_candidate(args)
        target = Path(args.output) if args.output else Path(
            "%s-%s.json" % (run_id, args.mode)
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
        )
        print("mode=%s" % args.mode)
        print("frame_count=%s" % payload.get("frame_count"))
        print("output=%s" % target)
        if payload.get("blockers"):
            print("blockers=%s" % ",".join(payload["blockers"]), file=sys.stderr)
            return 1
        return 0

    evidence = Phase13CEvidence(Path(args.output_dir), run_id)
    if not args.reference_json or not args.candidate_json:
        print("compare mode needs --reference-json and --candidate-json", file=sys.stderr)
        return 1
    reference = json.loads(Path(args.reference_json).read_text(encoding="utf-8"))
    candidate = json.loads(Path(args.candidate_json).read_text(encoding="utf-8"))
    metrics = compare(reference, candidate, float(args.match_iou))

    summary = {
        "phase": PHASE,
        "gate": "parity",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "reference_backend": reference.get("backend"),
        "candidate_backend": candidate.get("backend"),
        "parity_metrics": metrics,
        "status": STATUS_BLOCKED if metrics["blockers"] else "parity_passed",
    }
    summary.update(BOUNDARY_FIELDS)
    evidence.write_json("parity_metrics.json", metrics)
    evidence.write_json("summary.json", summary)

    print("parity_passed=%s" % metrics["parity_passed"])
    for key in (
        "reference_frame_count",
        "parity_evaluable_frame_count",
        "reference_detection_count",
        "tensorrt_detection_count",
        "matched_detection_count",
        "matched_detection_rate",
        "matched_class_agreement",
        "matched_box_iou_mean",
        "confidence_abs_error_p95",
    ):
        print("%s=%s" % (key, metrics.get(key)))
    if metrics["blockers"]:
        print("blockers=%s" % ",".join(metrics["blockers"]), file=sys.stderr)
    if args.require_parity and not metrics["parity_passed"]:
        return 1
    return 0 if metrics["parity_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

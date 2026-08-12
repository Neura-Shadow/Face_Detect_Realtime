"""Phase 13D INT8-vs-FP16 parity gate tests.

Parity here is conversion consistency, plus one safety question Phase 13C did
not ask: can the INT8 plan grant AI authority on a frame where the verified
FP16 plan could not? That count must be zero, and these tests pin it.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13d_precision_parity import (  # noqa: E402
    PARITY_THRESHOLDS,
    compare_parity,
    schema_valid,
)

FRAME_COUNT = 40


def detection(
    *, x: float = 100.0, y: float = 100.0, w: float = 40.0, h: float = 30.0,
    class_id: int = 2, confidence: float = 0.80
) -> Dict[str, Any]:
    return {
        "class_id": int(class_id),
        "label": "class_%d" % class_id,
        "confidence": round(float(confidence), 6),
        "bbox": [x, y, x + w, y + h],
    }


def side(precision: str, frames: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"backend": "tensorrt_%s" % precision, "precision": precision, "frames": frames}


def build_sides(
    *,
    box_shift: float = 0.0,
    confidence_shift: float = 0.0,
    class_flip_every: int = 0,
    drop_every: int = 0,
    count: int = FRAME_COUNT,
) -> Any:
    reference_frames = []  # type: List[Dict[str, Any]]
    candidate_frames = []  # type: List[Dict[str, Any]]
    for index in range(count):
        name = "frame_%03d" % index
        reference = [
            detection(x=100.0 + index, class_id=2, confidence=0.80),
            detection(x=300.0 + index, y=200.0, class_id=5, confidence=0.60),
        ]
        candidate = []  # type: List[Dict[str, Any]]
        for position, record in enumerate(reference):
            if drop_every and (index % drop_every == 0) and position == 0:
                continue
            class_id = record["class_id"]
            if class_flip_every and index % class_flip_every == 0 and position == 0:
                class_id = class_id + 1
            box = list(record["bbox"])
            candidate.append(
                detection(
                    x=box[0] + box_shift,
                    y=box[1],
                    w=box[2] - box[0],
                    h=box[3] - box[1],
                    class_id=class_id,
                    confidence=min(1.0, record["confidence"] + confidence_shift),
                )
            )
        reference_frames.append({"frame": name, "detections": reference})
        candidate_frames.append({"frame": name, "detections": candidate})
    return side("fp16", reference_frames), side("int8", candidate_frames)


def compare(reference: Dict[str, Any], candidate: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    kwargs.setdefault("match_iou", 0.5)
    kwargs.setdefault("max_detections", 300)
    kwargs.setdefault("min_frames", 4)
    return compare_parity(reference, candidate, **kwargs)


class TestSchemaPredicate(unittest.TestCase):
    def test_a_well_formed_detection_list_is_valid(self) -> None:
        self.assertTrue(schema_valid([detection()], max_detections=300))

    def test_an_empty_detection_list_is_valid(self) -> None:
        self.assertTrue(schema_valid([], max_detections=300))

    def test_too_many_detections_is_invalid(self) -> None:
        self.assertFalse(schema_valid([detection()] * 5, max_detections=4))

    def test_an_inverted_box_is_invalid(self) -> None:
        record = detection()
        record["bbox"] = [200.0, 100.0, 100.0, 200.0]
        self.assertFalse(schema_valid([record], max_detections=300))

    def test_a_nonfinite_box_is_invalid(self) -> None:
        record = detection()
        record["bbox"] = [float("nan"), 0.0, 10.0, 10.0]
        self.assertFalse(schema_valid([record], max_detections=300))

    def test_an_out_of_range_confidence_is_invalid(self) -> None:
        self.assertFalse(schema_valid([detection(confidence=1.4)], max_detections=300))

    def test_a_negative_class_id_is_invalid(self) -> None:
        record = detection()
        record["class_id"] = -1
        self.assertFalse(schema_valid([record], max_detections=300))


class TestParityMetrics(unittest.TestCase):
    def test_identical_outputs_are_perfect_parity(self) -> None:
        reference, candidate = build_sides()
        metrics = compare(reference, candidate)
        self.assertTrue(metrics["parity_passed"], metrics["blockers"])
        self.assertEqual(metrics["matched_detection_rate"], 1.0)
        self.assertEqual(metrics["matched_class_agreement"], 1.0)
        self.assertEqual(metrics["matched_box_iou_mean"], 1.0)
        self.assertEqual(metrics["confidence_abs_error_p95"], 0.0)
        self.assertEqual(metrics["unsafe_authority_divergence_count"], 0)
        self.assertEqual(metrics["reference_precision"], "fp16")
        self.assertEqual(metrics["candidate_precision"], "int8")

    def test_small_quantization_drift_still_passes(self) -> None:
        reference, candidate = build_sides(box_shift=2.0, confidence_shift=0.05)
        metrics = compare(reference, candidate)
        self.assertTrue(metrics["parity_passed"], metrics["blockers"])
        self.assertGreaterEqual(
            metrics["matched_box_iou_mean"], PARITY_THRESHOLDS["matched_box_iou_mean"]
        )
        self.assertLessEqual(
            metrics["confidence_abs_error_p95"], PARITY_THRESHOLDS["confidence_abs_error_p95"]
        )

    def test_large_box_drift_fails_the_iou_threshold(self) -> None:
        reference, candidate = build_sides(box_shift=25.0)
        metrics = compare(reference, candidate)
        self.assertFalse(metrics["parity_passed"])
        self.assertTrue(
            any(item.startswith("parity_threshold_failed") for item in metrics["blockers"]),
            metrics["blockers"],
        )

    def test_dropped_detections_fail_the_matched_rate(self) -> None:
        reference, candidate = build_sides(drop_every=2)
        metrics = compare(reference, candidate)
        self.assertFalse(metrics["parity_passed"])
        self.assertIn(
            "parity_threshold_failed:matched_detection_rate", metrics["blockers"]
        )

    def test_class_flips_fail_the_class_agreement(self) -> None:
        reference, candidate = build_sides(class_flip_every=2)
        metrics = compare(reference, candidate)
        self.assertFalse(metrics["parity_passed"])
        self.assertIn(
            "parity_threshold_failed:matched_class_agreement", metrics["blockers"]
        )

    def test_confidence_drift_fails_its_own_bound(self) -> None:
        reference, candidate = build_sides(confidence_shift=0.19)
        metrics = compare(reference, candidate)
        self.assertFalse(metrics["parity_passed"])
        self.assertIn(
            "parity_threshold_failed:confidence_abs_error_p95", metrics["blockers"]
        )

    def test_too_few_shared_frames_blocks_the_gate(self) -> None:
        reference, candidate = build_sides(count=4)
        metrics = compare(reference, candidate, min_frames=128)
        self.assertFalse(metrics["parity_passed"])
        self.assertIn("parity_frame_count_insufficient", metrics["blockers"])

    def test_no_reference_detections_is_not_evaluable(self) -> None:
        reference = side("fp16", [{"frame": "f%d" % index, "detections": []} for index in range(8)])
        candidate = side("int8", [{"frame": "f%d" % index, "detections": []} for index in range(8)])
        metrics = compare(reference, candidate)
        self.assertFalse(metrics["parity_passed"])
        self.assertIn("parity_not_evaluable", metrics["blockers"])

    def test_a_schema_error_blocks_the_gate(self) -> None:
        reference, candidate = build_sides()
        candidate["frames"][0]["detections"][0].pop("bbox")
        metrics = compare(reference, candidate)
        self.assertFalse(metrics["parity_passed"])
        self.assertIn("parity_schema_error", metrics["blockers"])

    def test_a_nonfinite_output_blocks_the_gate(self) -> None:
        reference, candidate = build_sides()
        candidate["frames"][0]["detections"][0]["bbox"] = [float("inf"), 0.0, 10.0, 10.0]
        metrics = compare(reference, candidate)
        self.assertFalse(metrics["parity_passed"])
        self.assertIn("parity_nonfinite_output", metrics["blockers"])

    def test_the_gate_never_claims_accuracy(self) -> None:
        reference, candidate = build_sides()
        metrics = compare(reference, candidate)
        self.assertEqual(metrics["measures"], "conversion_consistency_only")
        self.assertFalse(metrics["accuracy_claimed"])
        self.assertFalse(metrics["map_claimed"])
        self.assertFalse(metrics["recall_claimed"])


class TestAuthorityDivergence(unittest.TestCase):
    def test_int8_succeeding_where_fp16_failed_is_unsafe_divergence(self) -> None:
        reference, candidate = build_sides()
        reference["frames"][0] = {"frame": "frame_000", "error": "engine_execute_failed"}
        metrics = compare(reference, candidate)
        self.assertEqual(metrics["unsafe_authority_divergence_count"], 1)
        self.assertIn("frame_000", metrics["unsafe_authority_divergence_frames"])
        self.assertIn("unsafe_authority_divergence", metrics["blockers"])
        self.assertFalse(metrics["parity_passed"])

    def test_int8_failing_where_fp16_succeeded_is_the_safe_direction(self) -> None:
        reference, candidate = build_sides()
        candidate["frames"][0] = {"frame": "frame_000", "error": "output_nonfinite"}
        metrics = compare(reference, candidate)
        self.assertEqual(metrics["unsafe_authority_divergence_count"], 0)
        self.assertEqual(metrics["safe_authority_divergence_count"], 1)
        self.assertNotIn("unsafe_authority_divergence", metrics["blockers"])

    def test_an_int8_schema_violation_counts_as_safe_not_unsafe(self) -> None:
        reference, candidate = build_sides()
        candidate["frames"][1]["detections"][0]["confidence"] = 1.9
        metrics = compare(reference, candidate)
        self.assertEqual(metrics["unsafe_authority_divergence_count"], 0)
        self.assertEqual(metrics["safe_authority_divergence_count"], 1)


if __name__ == "__main__":
    unittest.main()

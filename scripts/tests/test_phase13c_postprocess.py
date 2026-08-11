"""Phase 13C output-schema, NMS and detection-validation tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.tensorrt_asset_contract import OutputContract, PostprocessProfile
from workers.core.tensorrt_perception import (
    LetterboxResult,
    TensorRTPerceptionError,
    decode_detections,
    infer_output_layout,
    nms_numpy,
)

IDENTITY_BOX = LetterboxResult(
    original_width=640,
    original_height=640,
    letterbox_width=640,
    letterbox_height=640,
    scale_ratio=1.0,
    pad_x=0.0,
    pad_y=0.0,
)


def channels_first_output(rows, class_count=80):
    """Build a (1, 4 + nc, anchors) tensor from (cx, cy, w, h, cls, score)."""

    anchors = max(1, len(rows))
    matrix = np.zeros((4 + class_count, anchors), dtype=np.float32)
    for index, (cx, cy, w, h, class_id, score) in enumerate(rows):
        matrix[0, index] = cx
        matrix[1, index] = cy
        matrix[2, index] = w
        matrix[3, index] = h
        matrix[4 + class_id, index] = score
    return matrix[None, ...]


class TestLayoutInference(unittest.TestCase):
    def test_channels_first_is_detected(self) -> None:
        info = infer_output_layout((1, 84, 8400))
        self.assertEqual(info["layout"], "channels_first")
        self.assertEqual(info["attributes"], 84)
        self.assertEqual(info["anchors"], 8400)

    def test_anchors_first_is_detected(self) -> None:
        info = infer_output_layout((1, 25200, 85))
        self.assertEqual(info["layout"], "anchors_first")
        self.assertEqual(info["attributes"], 85)
        self.assertEqual(info["anchors"], 25200)

    def test_rank_and_batch_are_enforced(self) -> None:
        for shape in ((84, 8400), (2, 84, 8400), (1, 84, 8400, 1)):
            with self.assertRaises(TensorRTPerceptionError) as ctx:
                infer_output_layout(shape)
            self.assertEqual(ctx.exception.classification, "output_shape_mismatch")

    def test_shape_with_no_wide_enough_axis_is_rejected(self) -> None:
        # Neither axis can hold 4 box values plus at least one class score.
        with self.assertRaises(TensorRTPerceptionError) as ctx:
            infer_output_layout((1, 3, 4))
        self.assertEqual(ctx.exception.classification, "output_shape_mismatch")

    def test_single_anchor_tensor_is_read_as_channels_first(self) -> None:
        # A naive "larger axis is the anchor axis" rule would misread this.
        info = infer_output_layout((1, 84, 1))
        self.assertEqual(info["layout"], "channels_first")
        self.assertEqual(info["attributes"], 84)
        self.assertEqual(info["anchors"], 1)

    def test_recorded_contract_layout_wins_over_the_heuristic(self) -> None:
        info = infer_output_layout((1, 85, 25200), declared_layout="channels_first")
        self.assertEqual(info["layout"], "channels_first")
        self.assertEqual(info["attributes"], 85)
        info = infer_output_layout((1, 25200, 85), declared_layout="anchors_first")
        self.assertEqual(info["layout"], "anchors_first")

    def test_shape_that_cannot_match_the_recorded_layout_is_rejected(self) -> None:
        with self.assertRaises(TensorRTPerceptionError) as ctx:
            infer_output_layout((1, 84, 1), declared_layout="anchors_first")
        self.assertEqual(ctx.exception.classification, "output_shape_mismatch")


class TestNms(unittest.TestCase):
    def test_overlapping_boxes_collapse(self) -> None:
        boxes = np.array(
            [[0, 0, 100, 100], [5, 5, 105, 105], [500, 500, 600, 600]], dtype=np.float32
        )
        scores = np.array([0.9, 0.8, 0.7], dtype=np.float32)
        keep = nms_numpy(boxes, scores, 0.45)
        self.assertEqual(sorted(keep), [0, 2])

    def test_highest_score_survives(self) -> None:
        boxes = np.array([[0, 0, 100, 100], [1, 1, 101, 101]], dtype=np.float32)
        scores = np.array([0.4, 0.95], dtype=np.float32)
        self.assertEqual(nms_numpy(boxes, scores, 0.45), [1])

    def test_disjoint_boxes_all_survive(self) -> None:
        boxes = np.array([[0, 0, 10, 10], [50, 50, 60, 60]], dtype=np.float32)
        scores = np.array([0.5, 0.6], dtype=np.float32)
        self.assertEqual(sorted(nms_numpy(boxes, scores, 0.45)), [0, 1])

    def test_empty_input(self) -> None:
        self.assertEqual(nms_numpy(np.zeros((0, 4), dtype=np.float32), np.zeros(0), 0.5), [])


class TestDecode(unittest.TestCase):
    def _contract(self, **kwargs):
        payload = dict(layout="channels_first", class_count=80, has_objectness=False)
        payload.update(kwargs)
        return OutputContract(**payload)

    def test_single_detection_decodes(self) -> None:
        raw = channels_first_output([(100.0, 100.0, 50.0, 40.0, 2, 0.9)])
        decoded = decode_detections(
            raw,
            letterbox=IDENTITY_BOX,
            output_contract=self._contract(),
            profile=PostprocessProfile(),
            class_names=["c%d" % index for index in range(80)],
        )
        self.assertEqual(len(decoded.detections), 1)
        detection = decoded.detections[0]
        self.assertEqual(detection.class_id, 2)
        self.assertAlmostEqual(detection.confidence, 0.9, places=5)
        self.assertAlmostEqual(detection.bbox[0], 75.0, places=3)
        self.assertAlmostEqual(detection.bbox[1], 80.0, places=3)
        self.assertAlmostEqual(detection.bbox[2], 125.0, places=3)
        self.assertAlmostEqual(detection.bbox[3], 120.0, places=3)
        self.assertEqual(detection.label, "c2")

    def test_below_threshold_is_dropped(self) -> None:
        raw = channels_first_output([(100.0, 100.0, 50.0, 40.0, 1, 0.1)])
        decoded = decode_detections(
            raw,
            letterbox=IDENTITY_BOX,
            output_contract=self._contract(),
            profile=PostprocessProfile(confidence_threshold=0.25),
        )
        self.assertEqual(decoded.detections, [])
        self.assertEqual(decoded.candidate_count, 0)

    def test_max_detections_is_enforced(self) -> None:
        rows = [(50.0 + index * 80, 50.0, 20.0, 20.0, index % 80, 0.9) for index in range(7)]
        decoded = decode_detections(
            channels_first_output(rows),
            letterbox=IDENTITY_BOX,
            output_contract=self._contract(),
            profile=PostprocessProfile(max_detections=3),
        )
        self.assertEqual(len(decoded.detections), 3)

    def test_objectness_layout_multiplies_scores(self) -> None:
        class_count = 80
        matrix = np.zeros((1, 1, 5 + class_count), dtype=np.float32)
        matrix[0, 0, :4] = [100.0, 100.0, 40.0, 40.0]
        matrix[0, 0, 4] = 0.8  # objectness
        matrix[0, 0, 5 + 3] = 0.5  # class probability
        decoded = decode_detections(
            matrix,
            letterbox=IDENTITY_BOX,
            output_contract=self._contract(layout="anchors_first", has_objectness=True),
            profile=PostprocessProfile(confidence_threshold=0.3),
        )
        self.assertEqual(len(decoded.detections), 1)
        self.assertAlmostEqual(decoded.detections[0].confidence, 0.4, places=5)

    def test_nonfinite_output_is_rejected(self) -> None:
        raw = channels_first_output([(100.0, 100.0, 50.0, 40.0, 0, 0.9)])
        raw[0, 0, 0] = np.nan
        with self.assertRaises(TensorRTPerceptionError) as ctx:
            decode_detections(
                raw,
                letterbox=IDENTITY_BOX,
                output_contract=self._contract(),
                profile=PostprocessProfile(),
            )
        self.assertEqual(ctx.exception.classification, "output_nonfinite")

    def test_layout_disagreement_with_contract_is_rejected(self) -> None:
        raw = channels_first_output([(100.0, 100.0, 50.0, 40.0, 0, 0.9)])
        with self.assertRaises(TensorRTPerceptionError) as ctx:
            decode_detections(
                raw,
                letterbox=IDENTITY_BOX,
                output_contract=self._contract(layout="anchors_first"),
                profile=PostprocessProfile(),
            )
        self.assertEqual(ctx.exception.classification, "output_shape_mismatch")

    def test_class_count_disagreement_is_rejected(self) -> None:
        raw = channels_first_output([(100.0, 100.0, 50.0, 40.0, 0, 0.9)], class_count=80)
        with self.assertRaises(TensorRTPerceptionError) as ctx:
            decode_detections(
                raw,
                letterbox=IDENTITY_BOX,
                output_contract=self._contract(class_count=20),
                profile=PostprocessProfile(),
            )
        self.assertEqual(ctx.exception.classification, "output_shape_mismatch")

    def test_confidence_above_one_is_rejected(self) -> None:
        raw = channels_first_output([(100.0, 100.0, 50.0, 40.0, 0, 1.7)])
        with self.assertRaises(TensorRTPerceptionError) as ctx:
            decode_detections(
                raw,
                letterbox=IDENTITY_BOX,
                output_contract=self._contract(),
                profile=PostprocessProfile(),
            )
        self.assertEqual(ctx.exception.classification, "confidence_out_of_range")

    def test_boxes_are_clipped_into_source_bounds(self) -> None:
        raw = channels_first_output([(600.0, 600.0, 400.0, 400.0, 0, 0.9)])
        decoded = decode_detections(
            raw,
            letterbox=IDENTITY_BOX,
            output_contract=self._contract(),
            profile=PostprocessProfile(),
        )
        box = decoded.detections[0].bbox
        self.assertLessEqual(box[2], 640.0)
        self.assertLessEqual(box[3], 640.0)
        self.assertGreaterEqual(box[0], 0.0)

    def test_letterbox_padding_is_reversed(self) -> None:
        padded = LetterboxResult(
            original_width=640,
            original_height=360,
            letterbox_width=640,
            letterbox_height=640,
            scale_ratio=1.0,
            pad_x=0.0,
            pad_y=140.0,
        )
        raw = channels_first_output([(320.0, 320.0, 40.0, 40.0, 0, 0.9)])
        decoded = decode_detections(
            raw,
            letterbox=padded,
            output_contract=self._contract(),
            profile=PostprocessProfile(),
        )
        box = decoded.detections[0].bbox
        # 320 in letterbox space maps to 180 in the 360-tall source frame.
        self.assertAlmostEqual((box[1] + box[3]) / 2.0, 180.0, places=3)

    def test_raw_statistics_are_recorded(self) -> None:
        raw = channels_first_output([(100.0, 100.0, 50.0, 40.0, 0, 0.9)])
        decoded = decode_detections(
            raw,
            letterbox=IDENTITY_BOX,
            output_contract=self._contract(),
            profile=PostprocessProfile(),
        )
        payload = decoded.to_dict()
        for key in ("output_raw_min", "output_raw_max", "output_raw_p99", "max_confidence"):
            self.assertIn(key, payload)


if __name__ == "__main__":
    unittest.main()

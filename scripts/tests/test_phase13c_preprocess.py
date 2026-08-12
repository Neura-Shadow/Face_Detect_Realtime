"""Phase 13C preprocessing and letterbox reverse-mapping tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.tensorrt_asset_contract import InputContract
from workers.core.tensorrt_perception import (
    LETTERBOX_PAD_VALUE,
    TensorRTPerceptionError,
    letterbox_bgr,
    preprocess_bgr,
    reverse_letterbox,
)


def frame(height: int, width: int, value: int = 128) -> np.ndarray:
    return np.full((height, width, 3), value, dtype=np.uint8)


class TestLetterbox(unittest.TestCase):
    def test_square_input_needs_no_padding(self) -> None:
        canvas, box = letterbox_bgr(frame(640, 640), width=640, height=640)
        self.assertEqual(canvas.shape, (640, 640, 3))
        self.assertAlmostEqual(box.scale_ratio, 1.0)
        self.assertEqual(box.pad_x, 0.0)
        self.assertEqual(box.pad_y, 0.0)

    def test_wide_input_pads_vertically_only(self) -> None:
        canvas, box = letterbox_bgr(frame(360, 640), width=640, height=640)
        self.assertEqual(canvas.shape, (640, 640, 3))
        self.assertAlmostEqual(box.scale_ratio, 1.0)
        self.assertEqual(box.pad_x, 0.0)
        self.assertEqual(box.pad_y, 140.0)
        # Padding uses the YOLOv9 grey, not black.
        self.assertEqual(int(canvas[0, 0, 0]), LETTERBOX_PAD_VALUE)
        self.assertEqual(int(canvas[639, 0, 0]), LETTERBOX_PAD_VALUE)

    def test_tall_input_pads_horizontally_only(self) -> None:
        canvas, box = letterbox_bgr(frame(640, 320), width=640, height=640)
        self.assertEqual(box.pad_y, 0.0)
        self.assertEqual(box.pad_x, 160.0)
        self.assertAlmostEqual(box.scale_ratio, 1.0)

    def test_large_input_is_scaled_down(self) -> None:
        canvas, box = letterbox_bgr(frame(1080, 1920), width=640, height=640)
        self.assertEqual(canvas.shape, (640, 640, 3))
        self.assertAlmostEqual(box.scale_ratio, 640.0 / 1920.0, places=6)
        self.assertEqual(box.original_width, 1920)
        self.assertEqual(box.original_height, 1080)

    def test_ratio_is_preserved(self) -> None:
        _, box = letterbox_bgr(frame(300, 900), width=640, height=640)
        scaled_w = box.original_width * box.scale_ratio
        scaled_h = box.original_height * box.scale_ratio
        self.assertAlmostEqual(scaled_w / scaled_h, 900.0 / 300.0, places=3)

    def test_non_three_channel_input_is_rejected(self) -> None:
        with self.assertRaises(TensorRTPerceptionError) as ctx:
            letterbox_bgr(np.zeros((10, 10, 4), dtype=np.uint8))
        self.assertEqual(ctx.exception.classification, "input_shape_mismatch")


class TestPreprocess(unittest.TestCase):
    def test_tensor_contract(self) -> None:
        contract = InputContract()
        tensor, box, stats = preprocess_bgr(frame(360, 640), contract)
        self.assertEqual(list(tensor.shape), [1, 3, 640, 640])
        self.assertEqual(tensor.dtype, np.float32)
        self.assertTrue(tensor.flags["C_CONTIGUOUS"])
        self.assertGreaterEqual(stats["input_min"], 0.0)
        self.assertLessEqual(stats["input_max"], 1.0)
        self.assertEqual(stats["input_color_order"], "RGB")
        self.assertEqual(stats["source_pixel_format"], "BGR8")
        self.assertEqual(stats["normalization_scale"], 255.0)
        self.assertEqual(len(stats["channel_means"]), 3)
        self.assertEqual(len(stats["channel_stds"]), 3)
        self.assertEqual(stats["original_width"], 640)
        self.assertEqual(stats["original_height"], 360)
        self.assertEqual(box.letterbox_width, 640)

    def test_bgr_to_rgb_conversion_is_explicit(self) -> None:
        source = np.zeros((64, 64, 3), dtype=np.uint8)
        source[:, :, 0] = 255  # blue in BGR
        tensor, _, _ = preprocess_bgr(source, InputContract())
        # After BGR->RGB the blue content must land in channel index 2.
        self.assertAlmostEqual(float(tensor[0, 2].max()), 1.0, places=5)
        self.assertAlmostEqual(float(tensor[0, 0].max()), 0.0, places=5)

    def test_normalization_divides_by_255(self) -> None:
        source = np.full((32, 32, 3), 255, dtype=np.uint8)
        tensor, _, stats = preprocess_bgr(source, InputContract())
        self.assertAlmostEqual(float(tensor.max()), 1.0, places=6)
        self.assertAlmostEqual(stats["input_max"], 1.0, places=6)

    def test_source_frame_statistics_are_recorded_separately(self) -> None:
        """Source stats must reflect the frame, not the letterbox padding."""

        black = np.zeros((360, 640, 3), dtype=np.uint8)
        _, _, stats = preprocess_bgr(black, InputContract())
        for value in stats["source_channel_means"]:
            self.assertAlmostEqual(value, 0.0, places=6)
        # The padded tensor is lifted by the 114/255 grey border, which is why
        # the range contract must not use it as the input-range signal.
        self.assertGreater(max(stats["channel_means"]), 0.1)
        self.assertAlmostEqual(stats["source_input_min"], 0.0, places=6)
        self.assertAlmostEqual(stats["source_input_max"], 0.0, places=6)

    def test_source_statistics_track_a_bright_frame(self) -> None:
        bright = np.full((360, 640, 3), 255, dtype=np.uint8)
        _, _, stats = preprocess_bgr(bright, InputContract())
        for value in stats["source_channel_means"]:
            self.assertAlmostEqual(value, 1.0, places=6)

    def test_non_uint8_input_is_rejected(self) -> None:
        with self.assertRaises(TensorRTPerceptionError) as ctx:
            preprocess_bgr(np.zeros((32, 32, 3), dtype=np.float32), InputContract())
        self.assertEqual(ctx.exception.classification, "input_dtype_mismatch")

    def test_unsupported_color_order_is_rejected(self) -> None:
        with self.assertRaises(TensorRTPerceptionError) as ctx:
            preprocess_bgr(frame(32, 32), InputContract(input_color_order="YUV"))
        self.assertEqual(ctx.exception.classification, "input_contract_mismatch")

    def test_bgr_contract_skips_channel_reversal(self) -> None:
        source = np.zeros((32, 32, 3), dtype=np.uint8)
        source[:, :, 0] = 255
        tensor, _, _ = preprocess_bgr(source, InputContract(input_color_order="BGR"))
        self.assertAlmostEqual(float(tensor[0, 0].max()), 1.0, places=5)


class TestReverseLetterbox(unittest.TestCase):
    def test_round_trip_recovers_the_source_box(self) -> None:
        source_box = np.array([[100.0, 50.0, 300.0, 200.0]], dtype=np.float32)
        _, box = letterbox_bgr(frame(360, 640), width=640, height=640)
        forward = source_box.copy()
        forward *= box.scale_ratio
        forward[:, [0, 2]] += box.pad_x
        forward[:, [1, 3]] += box.pad_y
        recovered = reverse_letterbox(forward, box)
        np.testing.assert_allclose(recovered, source_box, atol=1e-3)

    def test_boxes_are_clipped_to_source_bounds(self) -> None:
        _, box = letterbox_bgr(frame(360, 640), width=640, height=640)
        far = np.array([[-500.0, -500.0, 5000.0, 5000.0]], dtype=np.float32)
        clipped = reverse_letterbox(far, box)
        self.assertGreaterEqual(float(clipped[0, 0]), 0.0)
        self.assertGreaterEqual(float(clipped[0, 1]), 0.0)
        self.assertLessEqual(float(clipped[0, 2]), float(box.original_width))
        self.assertLessEqual(float(clipped[0, 3]), float(box.original_height))

    def test_scaled_down_source_round_trips(self) -> None:
        _, box = letterbox_bgr(frame(1080, 1920), width=640, height=640)
        source_box = np.array([[200.0, 100.0, 800.0, 600.0]], dtype=np.float32)
        forward = source_box * box.scale_ratio
        forward[:, [0, 2]] += box.pad_x
        forward[:, [1, 3]] += box.pad_y
        recovered = reverse_letterbox(forward, box)
        np.testing.assert_allclose(recovered, source_box, atol=1e-2)

    def test_empty_input_is_returned_unchanged(self) -> None:
        _, box = letterbox_bgr(frame(64, 64), width=640, height=640)
        empty = np.zeros((0, 4), dtype=np.float32)
        self.assertEqual(reverse_letterbox(empty, box).shape, (0, 4))


if __name__ == "__main__":
    unittest.main()

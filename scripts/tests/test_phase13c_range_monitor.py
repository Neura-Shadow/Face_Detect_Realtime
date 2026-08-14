"""Phase 13C TensorRT range / fail-closed contract tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.edge_perception import Detection
from workers.core.range_shift_monitor import RangeShiftState
from workers.core.tensorrt_range_monitor import (
    RANGE_VALIDATION_SCOPE,
    TensorRTRangeContract,
    TensorRTRangeMonitor,
)


def good_input() -> dict:
    return {
        "input_min": 0.0,
        "input_max": 1.0,
        "channel_means": [0.4, 0.45, 0.5],
        "channel_stds": [0.2, 0.2, 0.2],
        "source_channel_means": [0.4, 0.45, 0.5],
        "source_channel_stds": [0.2, 0.2, 0.2],
        "input_dtype": "float32",
        "input_color_order": "RGB",
    }


def good_output() -> dict:
    return {"output_raw_min": -3.0, "output_raw_max": 640.0, "output_raw_p99": 320.0}


def detection(confidence: float = 0.8, class_id: int = 1, bbox=(10.0, 10.0, 50.0, 50.0)) -> Detection:
    return Detection(label="obj", confidence=confidence, bbox=bbox, class_id=class_id)


class TestValidPath(unittest.TestCase):
    def setUp(self) -> None:
        self.monitor = TensorRTRangeMonitor()

    def _evaluate(self, **overrides):
        payload = dict(
            input_stats=good_input(),
            detections=[detection()],
            output_stats=good_output(),
            inference_ms=25.0,
            result_age_ms=10.0,
        )
        payload.update(overrides)
        return self.monitor.evaluate(**payload)

    def test_authority_requires_three_consecutive_valid_results(self) -> None:
        first = self._evaluate()
        second = self._evaluate()
        third = self._evaluate()
        self.assertEqual(first.state, RangeShiftState.RECOVERY_PENDING)
        self.assertFalse(first.ai_result_valid)
        self.assertFalse(second.ai_result_valid)
        self.assertTrue(third.ai_result_valid)
        self.assertEqual(third.state, RangeShiftState.VALID)

    def test_a_rejection_restarts_the_recovery_counter(self) -> None:
        for _ in range(3):
            self._evaluate()
        self.assertTrue(self._evaluate().ai_result_valid)
        rejected = self._evaluate(input_stats=dict(good_input(), input_max=9.0))
        self.assertFalse(rejected.ai_result_valid)
        self.assertFalse(self._evaluate().ai_result_valid)
        self.assertFalse(self._evaluate().ai_result_valid)
        self.assertTrue(self._evaluate().ai_result_valid)

    def test_zero_detections_is_valid(self) -> None:
        for _ in range(3):
            verdict = self._evaluate(detections=[])
        self.assertTrue(verdict.ai_result_valid)


class TestFailClosed(unittest.TestCase):
    def setUp(self) -> None:
        self.monitor = TensorRTRangeMonitor()

    def _evaluate(self, **overrides):
        payload = dict(
            input_stats=good_input(),
            detections=[detection()],
            output_stats=good_output(),
            inference_ms=25.0,
            result_age_ms=10.0,
        )
        payload.update(overrides)
        return self.monitor.evaluate(**payload)

    def test_fallback_is_always_rejected(self) -> None:
        verdict = self._evaluate(fallback_used=True)
        self.assertFalse(verdict.ai_result_valid)
        self.assertEqual(verdict.classification, "fallback_used")

    def test_engine_execution_failure_is_rejected(self) -> None:
        verdict = self._evaluate(engine_execute_ok=False)
        self.assertEqual(verdict.classification, "engine_execute_failed")

    def test_nonfinite_input_is_rejected(self) -> None:
        verdict = self._evaluate(input_stats=dict(good_input(), input_max=float("nan")))
        self.assertEqual(verdict.state, RangeShiftState.NAN_OR_INF)
        self.assertEqual(verdict.classification, "input_nonfinite")

    def test_input_outside_normalized_range_is_rejected(self) -> None:
        verdict = self._evaluate(input_stats=dict(good_input(), input_max=4.0))
        self.assertEqual(verdict.state, RangeShiftState.INPUT_RANGE_SHIFT)

    def test_input_dtype_mismatch_is_rejected(self) -> None:
        verdict = self._evaluate(input_stats=dict(good_input(), input_dtype="float16"))
        self.assertEqual(verdict.classification, "input_dtype_mismatch")

    def test_color_order_mismatch_is_rejected(self) -> None:
        verdict = self._evaluate(input_stats=dict(good_input(), input_color_order="BGR"))
        self.assertEqual(verdict.state, RangeShiftState.COLOR_ORDER_MISMATCH)

    def test_channel_count_mismatch_is_rejected(self) -> None:
        # Both the source and tensor means carry the wrong channel count; the
        # monitor reads the source stats first, so that is what must be short.
        verdict = self._evaluate(
            input_stats=dict(
                good_input(), source_channel_means=[0.5, 0.5], channel_means=[0.5, 0.5]
            )
        )
        self.assertEqual(verdict.classification, "input_channel_count_mismatch")

    def test_nonfinite_output_is_rejected(self) -> None:
        verdict = self._evaluate(output_stats=dict(good_output(), output_raw_max=float("inf")))
        self.assertEqual(verdict.state, RangeShiftState.NAN_OR_INF)
        self.assertEqual(verdict.classification, "output_nonfinite")

    def test_output_magnitude_beyond_contract_is_rejected(self) -> None:
        verdict = self._evaluate(output_stats=dict(good_output(), output_raw_max=1e12))
        self.assertEqual(verdict.classification, "output_range_invalid")

    def test_confidence_out_of_range_is_rejected(self) -> None:
        verdict = self._evaluate(detections=[detection(confidence=1.4)])
        self.assertEqual(verdict.classification, "confidence_out_of_range")

    def test_invalid_class_id_is_rejected(self) -> None:
        verdict = self._evaluate(detections=[detection(class_id=-3)])
        self.assertEqual(verdict.classification, "invalid_class_id")

    def test_inverted_bbox_is_rejected(self) -> None:
        verdict = self._evaluate(detections=[detection(bbox=(90.0, 90.0, 10.0, 10.0))])
        self.assertEqual(verdict.classification, "bbox_invalid")

    def test_nonfinite_bbox_is_rejected(self) -> None:
        verdict = self._evaluate(detections=[detection(bbox=(0.0, 0.0, float("nan"), 5.0))])
        self.assertEqual(verdict.classification, "bbox_nonfinite")

    def test_excessive_detection_count_is_rejected(self) -> None:
        monitor = TensorRTRangeMonitor(TensorRTRangeContract(max_detections=2))
        verdict = monitor.evaluate(
            input_stats=good_input(),
            detections=[detection() for _ in range(5)],
            output_stats=good_output(),
            inference_ms=10.0,
            result_age_ms=1.0,
        )
        self.assertEqual(verdict.classification, "detection_count_exceeded")

    def test_inference_timeout_is_rejected(self) -> None:
        monitor = TensorRTRangeMonitor(TensorRTRangeContract(max_inference_ms=50.0))
        verdict = monitor.evaluate(
            input_stats=good_input(),
            detections=[detection()],
            output_stats=good_output(),
            inference_ms=120.0,
            result_age_ms=1.0,
        )
        self.assertEqual(verdict.classification, "inference_timeout")

    def test_stale_result_is_rejected(self) -> None:
        verdict = self._evaluate(result_age_ms=100000.0)
        self.assertEqual(verdict.classification, "result_stale")

    def test_negative_result_age_is_rejected(self) -> None:
        verdict = self._evaluate(result_age_ms=-5.0)
        self.assertEqual(verdict.classification, "result_stale")


class TestSourceFrameBounds(unittest.TestCase):
    """The channel-mean bound must be applied to the SOURCE frame.

    Letterbox padding (114/255 grey) fills 44% of a 640x360 frame padded to
    640x640, so an all-black source still measures ~0.197 on the padded tensor.
    Checking the padded tensor would silently accept a black frame — which is
    exactly what the real Gate D run exposed.
    """

    def _evaluate(self, stats):
        return TensorRTRangeMonitor().evaluate(
            input_stats=stats,
            detections=[detection()],
            output_stats=good_output(),
            inference_ms=20.0,
            result_age_ms=5.0,
        )

    def test_bounds_are_not_degenerate(self) -> None:
        for low, high in TensorRTRangeContract().input_channel_mean_bounds:
            self.assertGreater(low, 0.0, "a 0.0 lower bound can never fire")
            self.assertLess(high, 1.0, "a 1.0 upper bound can never fire")

    def test_black_source_frame_is_rejected_despite_padded_tensor_means(self) -> None:
        stats = good_input()
        stats["source_channel_means"] = [0.0, 0.0, 0.0]
        stats["channel_means"] = [0.197, 0.197, 0.197]  # padding lifts the tensor
        verdict = self._evaluate(stats)
        self.assertFalse(verdict.ai_result_valid)
        self.assertEqual(verdict.state, RangeShiftState.INPUT_RANGE_SHIFT)
        self.assertEqual(verdict.classification, "input_range_shift")

    def test_saturated_source_frame_is_rejected(self) -> None:
        stats = good_input()
        stats["source_channel_means"] = [1.0, 1.0, 1.0]
        verdict = self._evaluate(stats)
        self.assertFalse(verdict.ai_result_valid)
        self.assertEqual(verdict.classification, "input_range_shift")

    def test_source_means_take_precedence_over_tensor_means(self) -> None:
        stats = good_input()
        stats["source_channel_means"] = [0.5, 0.5, 0.5]
        stats["channel_means"] = [0.0, 0.0, 0.0]  # would fail if it were used
        verdict = self._evaluate(stats)
        self.assertNotEqual(verdict.classification, "input_range_shift")

    def test_tensor_means_are_used_when_source_stats_are_absent(self) -> None:
        stats = good_input()
        del stats["source_channel_means"]
        stats["channel_means"] = [0.0, 0.0, 0.0]
        verdict = self._evaluate(stats)
        self.assertEqual(verdict.classification, "input_range_shift")


class TestEvidence(unittest.TestCase):
    def test_scope_is_honest_about_what_is_not_checked(self) -> None:
        evidence = TensorRTRangeMonitor().evidence()
        self.assertTrue(evidence["input_range_checked"])
        self.assertTrue(evidence["tensor_output_range_checked"])
        self.assertTrue(evidence["detection_schema_checked"])
        self.assertFalse(evidence["activation_range_checked"])
        self.assertFalse(evidence["quantization_saturation_checked"])
        self.assertFalse(evidence["int8_calibration_range_checked"])
        self.assertFalse(evidence["internal_tensor_monitoring_claimed"])
        self.assertEqual(evidence["range_validation_scope"], RANGE_VALIDATION_SCOPE)
        self.assertEqual(evidence["range_validation_scope"], "tensorrt_fp16_input_and_final_output")

    def test_reject_counters_are_reported(self) -> None:
        monitor = TensorRTRangeMonitor()
        monitor.evaluate(
            input_stats=good_input(),
            detections=[detection(confidence=2.0)],
            output_stats=good_output(),
            inference_ms=10.0,
            result_age_ms=1.0,
        )
        evidence = monitor.evidence()
        self.assertEqual(evidence["tensorrt_range_reject_count"], 1)
        self.assertEqual(evidence["range_reject_counts"]["confidence_out_of_range"], 1)


if __name__ == "__main__":
    unittest.main()

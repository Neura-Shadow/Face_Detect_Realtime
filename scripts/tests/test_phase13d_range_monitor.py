"""Phase 13D INT8 calibration-envelope range monitor tests.

The INT8 monitor keeps every Phase 13C rule and adds one: a frame drawn from
outside the calibration distribution loses AI authority, because the engine's
activation scales were fixed on that distribution. These tests pin both halves,
including the invariant that no rejected result ever grants authority and that
the phase never claims to observe TensorRT's internal activations.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from workers.core.edge_perception import Detection  # noqa: E402
from workers.core.int8_calibration_dataset import CalibrationEnvelopes  # noqa: E402
from workers.core.int8_range_monitor import (  # noqa: E402
    RANGE_VALIDATION_SCOPE_INT8,
    Int8RangeContract,
    Int8RangeMonitor,
    envelope_from_bounds,
    load_envelopes,
    runtime_statistics,
)
from workers.core.range_shift_monitor import RangeShiftState  # noqa: E402


def envelopes() -> CalibrationEnvelopes:
    return envelope_from_bounds(
        [(0.20, 0.60), (0.20, 0.60), (0.20, 0.60)],
        [(0.10, 0.30), (0.10, 0.30), (0.10, 0.30)],
        pixel_min_bounds=[0.0, 0.05],
        pixel_max_bounds=[0.90, 1.0],
        pixel_mean_bounds=[0.20, 0.60],
    )


def input_stats(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "input_min": 0.0,
        "input_max": 1.0,
        "channel_means": [0.44, 0.44, 0.44],
        "channel_stds": [0.2, 0.2, 0.2],
        "source_input_min": 0.0,
        "source_input_max": 0.98,
        "source_channel_means": [0.40, 0.42, 0.44],
        "source_channel_stds": [0.18, 0.19, 0.20],
        "input_dtype": "float32",
        "input_color_order": "RGB",
    }
    payload.update(overrides)
    return payload


def output_stats(**overrides: Any) -> Dict[str, Any]:
    payload = {"output_raw_min": -2.0, "output_raw_max": 640.0, "output_raw_p99": 300.0}
    payload.update(overrides)
    return payload


def detection(**overrides: Any) -> Detection:
    payload = {"label": "obj", "confidence": 0.8, "bbox": (10.0, 10.0, 40.0, 40.0), "class_id": 1}
    payload.update(overrides)
    return Detection(**payload)


def evaluate(monitor: Int8RangeMonitor, **overrides: Any) -> Any:
    payload = dict(
        input_stats=input_stats(),
        detections=[detection()],
        output_stats=output_stats(),
        inference_ms=25.0,
        result_age_ms=5.0,
    )
    payload.update(overrides)
    return monitor.evaluate(**payload)


def monitor(**kwargs: Any) -> Int8RangeMonitor:
    """A monitor for the range tests: authority explicitly enabled.

    The Phase 13D-MP-RECOVERY freeze makes ``authoritative`` default to False,
    which is asserted separately in ``TestNonAuthoritativeFreeze``. The range
    tests are about the range logic, so they opt in explicitly.
    """

    kwargs.setdefault("envelopes", envelopes())
    contract = kwargs.pop("contract", Int8RangeContract(authoritative=True))
    return Int8RangeMonitor(contract, **kwargs)


class TestRuntimeStatisticsProjection(unittest.TestCase):
    def test_source_statistics_are_preferred_over_letterboxed_ones(self) -> None:
        projected = runtime_statistics(input_stats())
        self.assertEqual(projected["channel_means"], [0.40, 0.42, 0.44])
        self.assertEqual(projected["channel_stds"], [0.18, 0.19, 0.20])
        self.assertAlmostEqual(projected["pixel_min"], 0.0)
        self.assertAlmostEqual(projected["pixel_max"], 0.98)

    def test_pixel_mean_is_derived_from_the_channel_means(self) -> None:
        projected = runtime_statistics(input_stats())
        self.assertAlmostEqual(projected["pixel_mean"], (0.40 + 0.42 + 0.44) / 3.0, places=6)

    def test_letterboxed_statistics_are_used_only_as_a_fallback(self) -> None:
        stats = input_stats()
        del stats["source_channel_means"]
        del stats["source_channel_stds"]
        projected = runtime_statistics(stats)
        self.assertEqual(projected["channel_means"], [0.44, 0.44, 0.44])


class TestEnvelopeGate(unittest.TestCase):
    def test_three_consecutive_in_envelope_results_grant_authority(self) -> None:
        gate = monitor()
        first = evaluate(gate)
        second = evaluate(gate)
        third = evaluate(gate)
        self.assertFalse(first.ai_result_valid)
        self.assertEqual(first.state, RangeShiftState.RECOVERY_PENDING)
        self.assertFalse(second.ai_result_valid)
        self.assertTrue(third.ai_result_valid)
        self.assertEqual(third.state, RangeShiftState.VALID)
        self.assertEqual(third.classification, "ACCEPTED")

    def test_a_frame_outside_the_envelope_loses_authority(self) -> None:
        gate = monitor()
        for _ in range(3):
            evaluate(gate)
        verdict = evaluate(gate, input_stats=input_stats(source_channel_means=[0.85, 0.85, 0.85]))
        self.assertFalse(verdict.ai_result_valid)
        self.assertEqual(verdict.classification, "calibration_range_shift")
        self.assertEqual(verdict.state, RangeShiftState.INPUT_RANGE_SHIFT)
        self.assertTrue(verdict.observations["calibration_envelope_violations"])

    def test_a_dark_shifted_frame_loses_authority(self) -> None:
        gate = monitor()
        verdict = evaluate(
            gate,
            input_stats=input_stats(
                source_channel_means=[0.05, 0.05, 0.05], source_input_max=0.2
            ),
        )
        self.assertFalse(verdict.ai_result_valid)
        self.assertEqual(verdict.classification, "calibration_range_shift")

    def test_a_flattened_contrast_frame_loses_authority(self) -> None:
        gate = monitor()
        verdict = evaluate(gate, input_stats=input_stats(source_channel_stds=[0.01, 0.01, 0.01]))
        self.assertFalse(verdict.ai_result_valid)
        self.assertEqual(verdict.classification, "calibration_range_shift")

    def test_recovery_requires_three_more_valid_results_after_a_shift(self) -> None:
        gate = monitor()
        for _ in range(3):
            evaluate(gate)
        evaluate(gate, input_stats=input_stats(source_channel_means=[0.85, 0.85, 0.85]))
        self.assertFalse(evaluate(gate).ai_result_valid)
        self.assertFalse(evaluate(gate).ai_result_valid)
        recovered = evaluate(gate)
        self.assertTrue(recovered.ai_result_valid)
        self.assertTrue(recovered.recovered)

    def test_a_missing_envelope_fails_closed(self) -> None:
        gate = Int8RangeMonitor(Int8RangeContract(authoritative=True), envelopes=None)
        verdict = evaluate(gate)
        self.assertFalse(verdict.ai_result_valid)
        self.assertEqual(verdict.classification, "calibration_envelope_missing")

    def test_the_envelope_can_be_declared_unenforced_only_explicitly(self) -> None:
        gate = Int8RangeMonitor(
            Int8RangeContract(calibration_envelope_enforced=False, authoritative=True),
            envelopes=None,
        )
        for _ in range(3):
            verdict = evaluate(gate)
        self.assertTrue(verdict.ai_result_valid)
        self.assertFalse(gate.evidence()["calibration_envelope_enforced"])

    def test_envelope_rejections_are_counted(self) -> None:
        gate = monitor()
        for _ in range(2):
            evaluate(gate, input_stats=input_stats(source_channel_means=[0.85, 0.85, 0.85]))
        evidence = gate.evidence()
        self.assertEqual(evidence["calibration_envelope_reject_count"], 2)
        self.assertTrue(evidence["calibration_envelope_violation_counts"])


class TestPhase13CRulesStillHold(unittest.TestCase):
    def test_fallback_is_still_forbidden(self) -> None:
        verdict = evaluate(monitor(), fallback_used=True)
        self.assertFalse(verdict.ai_result_valid)
        self.assertEqual(verdict.classification, "fallback_used")

    def test_engine_failure_is_still_fail_closed(self) -> None:
        verdict = evaluate(monitor(), engine_execute_ok=False)
        self.assertFalse(verdict.ai_result_valid)
        self.assertEqual(verdict.classification, "engine_execute_failed")

    def test_nonfinite_input_is_still_rejected_before_the_envelope(self) -> None:
        verdict = evaluate(monitor(), input_stats=input_stats(input_max=float("inf")))
        self.assertFalse(verdict.ai_result_valid)
        self.assertEqual(verdict.classification, "input_nonfinite")

    def test_colour_order_mismatch_is_still_rejected(self) -> None:
        verdict = evaluate(monitor(), input_stats=input_stats(input_color_order="BGR"))
        self.assertFalse(verdict.ai_result_valid)
        self.assertEqual(verdict.classification, "input_color_order_mismatch")

    def test_a_stale_result_is_still_rejected(self) -> None:
        verdict = evaluate(monitor(), result_age_ms=5000.0)
        self.assertFalse(verdict.ai_result_valid)
        self.assertEqual(verdict.classification, "result_stale")

    def test_an_over_budget_inference_is_still_rejected(self) -> None:
        verdict = evaluate(monitor(), inference_ms=5000.0)
        self.assertFalse(verdict.ai_result_valid)
        self.assertEqual(verdict.classification, "inference_timeout")

    def test_an_out_of_range_confidence_is_still_rejected(self) -> None:
        verdict = evaluate(monitor(), detections=[detection(confidence=1.7)])
        self.assertFalse(verdict.ai_result_valid)
        self.assertEqual(verdict.classification, "confidence_out_of_range")


class TestNonAuthoritativeFreeze(unittest.TestCase):
    """Phase 13D-MP-RECOVERY freeze: INT8 may run, but may not command."""

    def _frozen(self) -> Int8RangeMonitor:
        return Int8RangeMonitor(Int8RangeContract(), envelopes=envelopes())

    def test_int8_is_non_authoritative_by_default(self) -> None:
        gate = self._frozen()
        self.assertFalse(gate.authoritative)
        self.assertFalse(Int8RangeContract().authoritative)

    def test_a_perfectly_valid_int8_result_still_cannot_grant_authority(self) -> None:
        gate = self._frozen()
        for _ in range(6):
            verdict = evaluate(gate)
        self.assertFalse(verdict.ai_result_valid)
        self.assertEqual(verdict.classification, "int8_non_authoritative")
        self.assertEqual(verdict.state, RangeShiftState.RECOVERY_PENDING)
        self.assertTrue(verdict.sample_valid)

    def test_withholding_authority_is_not_recorded_as_a_range_rejection(self) -> None:
        gate = self._frozen()
        for _ in range(6):
            evaluate(gate)
        evidence = gate.evidence()
        self.assertEqual(evidence["tensorrt_range_reject_count"], 0)
        self.assertEqual(evidence["calibration_envelope_reject_count"], 0)
        self.assertEqual(evidence["int8_non_authoritative_suppression_count"], 4)

    def test_a_genuine_fault_still_reports_as_a_fault_not_as_policy(self) -> None:
        gate = self._frozen()
        verdict = evaluate(gate, fallback_used=True)
        self.assertEqual(verdict.classification, "fallback_used")
        self.assertFalse(verdict.ai_result_valid)
        verdict = evaluate(gate, input_stats=input_stats(source_channel_means=[0.85, 0.85, 0.85]))
        self.assertEqual(verdict.classification, "calibration_range_shift")

    def test_the_freeze_is_reported_in_the_evidence(self) -> None:
        evidence = self._frozen().evidence()
        self.assertFalse(evidence["int8_authoritative"])
        self.assertFalse(evidence["int8_may_grant_ai_active"])
        self.assertEqual(evidence["int8_backend_role"], "experimental_non_authoritative")

    def test_authority_can_only_be_granted_deliberately(self) -> None:
        gate = Int8RangeMonitor(Int8RangeContract(authoritative=True), envelopes=envelopes())
        for _ in range(3):
            verdict = evaluate(gate)
        self.assertTrue(verdict.ai_result_valid)
        evidence = gate.evidence()
        self.assertTrue(evidence["int8_may_grant_ai_active"])
        self.assertEqual(evidence["int8_backend_role"], "authoritative")
        self.assertEqual(evidence["int8_non_authoritative_suppression_count"], 0)


class TestEvidence(unittest.TestCase):
    def test_int8_evidence_fields_are_declared(self) -> None:
        evidence = monitor().evidence()
        self.assertEqual(evidence["precision"], "int8")
        self.assertEqual(evidence["range_validation_scope"], RANGE_VALIDATION_SCOPE_INT8)
        self.assertTrue(evidence["int8_calibration_range_checked"])
        self.assertTrue(evidence["calibration_envelope_loaded"])
        self.assertTrue(evidence["calibration_envelope_enforced"])
        self.assertTrue(evidence["input_range_checked"])
        self.assertTrue(evidence["tensor_output_range_checked"])
        self.assertTrue(evidence["detection_schema_checked"])

    def test_activation_claims_stay_false(self) -> None:
        evidence = monitor().evidence()
        self.assertFalse(evidence["activation_range_checked"])
        self.assertFalse(evidence["runtime_internal_activation_observed"])
        self.assertFalse(evidence["quantization_saturation_checked_at_runtime"])
        self.assertFalse(evidence["internal_tensor_monitoring_claimed"])
        self.assertFalse(evidence["qat_verified"])

    def test_an_offline_proxy_is_reported_as_offline(self) -> None:
        gate = monitor(activation_proxy={"activation_proxy_layer_count": 12})
        evidence = gate.evidence()
        self.assertTrue(evidence["activation_proxy_available"])
        self.assertTrue(evidence["activation_proxy_is_offline_source_model_only"])
        self.assertFalse(evidence["runtime_internal_activation_observed"])

    def test_the_envelope_itself_is_recorded(self) -> None:
        evidence = monitor().evidence()
        self.assertEqual(len(evidence["calibration_envelope"]["channel_mean_bounds"]), 3)


class TestEnvelopeLoading(unittest.TestCase):
    def test_a_bare_envelope_file_loads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration_envelope.json"
            path.write_text(json.dumps(envelopes().to_dict()), encoding="utf-8")
            loaded = load_envelopes(str(path))
            self.assertIsNotNone(loaded)
            self.assertEqual(len(loaded.channel_mean_bounds), 3)

    def test_a_wrapped_envelope_file_loads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "range_metrics.json"
            path.write_text(
                json.dumps({"calibration_envelope": envelopes().to_dict()}), encoding="utf-8"
            )
            loaded = load_envelopes(str(path))
            self.assertIsNotNone(loaded)
            self.assertEqual(len(loaded.channel_std_bounds), 3)

    def test_an_absent_path_returns_none_so_the_caller_can_fail_closed(self) -> None:
        self.assertIsNone(load_envelopes(""))
        self.assertIsNone(load_envelopes("/definitely/not/here.json"))


if __name__ == "__main__":
    unittest.main()

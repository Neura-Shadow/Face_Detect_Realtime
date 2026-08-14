"""Phase 13C TensorRT input / final-output range contract, fail-closed.

Phase 13B validated frame **inputs** only, because a dummy backend has no
tensors. Phase 13C runs a real engine, so the contract is extended to the
engine's declared input tensor and its **final decoded output** — and to
nothing more. Internal activations are not exposed by a serialized TensorRT
plan, so activation-range and quantization-saturation evidence is still
explicitly *not* claimed:

    input_range_checked                = true
    tensor_output_range_checked        = true
    detection_schema_checked           = true
    activation_range_checked           = false
    quantization_saturation_checked    = false
    int8_calibration_range_checked     = false
    range_validation_scope             = tensorrt_fp16_input_and_final_output

The Phase 13A recovery rule is preserved: after any rejection, three
consecutive valid results are required before AI authority may resume.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import math
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.range_shift_monitor import RangeShiftState

RANGE_VALIDATION_SCOPE = "tensorrt_fp16_input_and_final_output"
DEFAULT_RECOVERY_VALID_SAMPLES = 3


@dataclass(frozen=True)
class TensorRTRangeContract:
    """Bounds the engine input and the final decoded output must satisfy."""

    input_min: float = 0.0
    input_max: float = 1.0
    input_epsilon: float = 1e-4
    # Applied to the SOURCE frame, not the letterboxed tensor. (0.0, 1.0) would
    # be degenerate: every possible normalized value satisfies it, so the check
    # could never fire. These bounds match the proven Phase 13B input-only
    # profile and still reject an all-black, saturated or otherwise degenerate
    # frame.
    input_channel_mean_bounds: Sequence[Sequence[float]] = (
        (0.02, 0.98),
        (0.02, 0.98),
        (0.02, 0.98),
    )
    expected_input_dtype: str = "float32"
    expected_input_shape: Sequence[int] = (1, 3, 640, 640)
    expected_color_order: str = "RGB"
    output_abs_max: float = 1.0e6
    confidence_min: float = 0.0
    confidence_max: float = 1.0
    max_detections: int = 300
    max_result_age_ms: int = 150
    max_inference_ms: float = 1000.0
    recovery_valid_samples: int = DEFAULT_RECOVERY_VALID_SAMPLES

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["input_channel_mean_bounds"] = [
            list(item) for item in self.input_channel_mean_bounds
        ]
        payload["expected_input_shape"] = list(self.expected_input_shape)
        return payload


@dataclass
class TensorRTRangeResult:
    """One verdict, shaped so the Phase 13B command path can consume it."""

    state: RangeShiftState
    sample_valid: bool
    ai_result_valid: bool
    reason: str
    classification: str
    consecutive_valid_samples: int = 0
    recovered: bool = False
    observations: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "range_state": self.state.name,
            "sample_valid": self.sample_valid,
            "ai_result_valid": self.ai_result_valid,
            "reason": self.reason,
            "classification": self.classification,
            "consecutive_valid_samples": self.consecutive_valid_samples,
            "recovered": self.recovered,
            "observations": dict(self.observations),
        }


class TensorRTRangeMonitor:
    """Fail-closed gate over the TensorRT input tensor and decoded detections."""

    def __init__(self, contract: Optional[TensorRTRangeContract] = None) -> None:
        self.contract = contract or TensorRTRangeContract()
        self._consecutive_valid = 0
        self._ever_failed = False
        self.evaluation_count = 0
        self.reject_count = 0
        self.reject_counts = {}  # type: Dict[str, int]

    # ── evaluation ──────────────────────────────────────────────────────────

    def evaluate(
        self,
        *,
        input_stats: Dict[str, Any],
        detections: Sequence[Any],
        output_stats: Dict[str, Any],
        inference_ms: float,
        result_age_ms: float,
        engine_execute_ok: bool = True,
        fallback_used: bool = False,
    ) -> TensorRTRangeResult:
        """Validate one complete TensorRT result. Any violation fails closed."""

        self.evaluation_count += 1
        observations = {
            "inference_ms": round(float(inference_ms), 4),
            "result_age_ms": round(float(result_age_ms), 4),
            "detection_count": len(detections),
        }  # type: Dict[str, Any]
        observations.update({k: v for k, v in input_stats.items() if not isinstance(v, (bytes, bytearray))})
        observations.update({k: v for k, v in output_stats.items() if not isinstance(v, (bytes, bytearray))})

        if fallback_used:
            return self._fail(
                RangeShiftState.OUTPUT_RANGE_INVALID,
                "perception fallback is forbidden in a formal Phase 13C gate",
                "fallback_used",
                observations,
            )
        if not engine_execute_ok:
            return self._fail(
                RangeShiftState.OUTPUT_RANGE_INVALID,
                "engine execution reported failure",
                "engine_execute_failed",
                observations,
            )

        verdict = self._check_input(input_stats, observations)
        if verdict is not None:
            return verdict
        verdict = self._check_output(output_stats, observations)
        if verdict is not None:
            return verdict
        verdict = self._check_detections(detections, observations)
        if verdict is not None:
            return verdict
        verdict = self._check_timing(inference_ms, result_age_ms, observations)
        if verdict is not None:
            return verdict

        self._consecutive_valid += 1
        recovered = self._ever_failed and self._consecutive_valid >= self.contract.recovery_valid_samples
        if self._consecutive_valid < self.contract.recovery_valid_samples:
            return TensorRTRangeResult(
                state=RangeShiftState.RECOVERY_PENDING,
                sample_valid=True,
                ai_result_valid=False,
                reason="awaiting %d consecutive valid TensorRT results"
                % self.contract.recovery_valid_samples,
                classification="RECOVERY_PENDING",
                consecutive_valid_samples=self._consecutive_valid,
                recovered=False,
                observations=observations,
            )
        return TensorRTRangeResult(
            state=RangeShiftState.VALID,
            sample_valid=True,
            ai_result_valid=True,
            reason="tensorrt input and final output within contract",
            classification="ACCEPTED",
            consecutive_valid_samples=self._consecutive_valid,
            recovered=recovered,
            observations=observations,
        )

    # ── individual checks ───────────────────────────────────────────────────

    def _check_input(
        self, stats: Dict[str, Any], observations: Dict[str, Any]
    ) -> Optional[TensorRTRangeResult]:
        minimum = stats.get("input_min")
        maximum = stats.get("input_max")
        if minimum is None or maximum is None:
            return self._fail(
                RangeShiftState.NORMALIZATION_MISMATCH,
                "input statistics missing",
                "input_stats_missing",
                observations,
            )
        if not math.isfinite(float(minimum)) or not math.isfinite(float(maximum)):
            return self._fail(
                RangeShiftState.NAN_OR_INF,
                "input tensor contains NaN/Inf",
                "input_nonfinite",
                observations,
            )
        epsilon = self.contract.input_epsilon
        if float(minimum) < self.contract.input_min - epsilon or float(maximum) > self.contract.input_max + epsilon:
            return self._fail(
                RangeShiftState.INPUT_RANGE_SHIFT,
                "normalized input outside [%s, %s]" % (self.contract.input_min, self.contract.input_max),
                "input_range_shift",
                observations,
            )

        dtype = str(stats.get("input_dtype", ""))
        if dtype and dtype != self.contract.expected_input_dtype:
            return self._fail(
                RangeShiftState.NORMALIZATION_MISMATCH,
                "input dtype %s does not match contract %s"
                % (dtype, self.contract.expected_input_dtype),
                "input_dtype_mismatch",
                observations,
            )
        order = str(stats.get("input_color_order", "") or "")
        if order and order.upper() != self.contract.expected_color_order.upper():
            return self._fail(
                RangeShiftState.COLOR_ORDER_MISMATCH,
                "input color order %s does not match contract %s"
                % (order, self.contract.expected_color_order),
                "input_color_order_mismatch",
                observations,
            )

        # Prefer the source-frame means; letterbox padding makes the padded
        # tensor's means unusable as an input-range signal.
        means = stats.get("source_channel_means")
        if means is None:
            means = stats.get("channel_means")
        if isinstance(means, (list, tuple)) and self.contract.input_channel_mean_bounds:
            bounds = list(self.contract.input_channel_mean_bounds)
            if len(means) != len(bounds):
                return self._fail(
                    RangeShiftState.NORMALIZATION_MISMATCH,
                    "channel count %d does not match contract %d" % (len(means), len(bounds)),
                    "input_channel_count_mismatch",
                    observations,
                )
            for value, (low, high) in zip(means, bounds):
                if not math.isfinite(float(value)):
                    return self._fail(
                        RangeShiftState.NAN_OR_INF,
                        "channel mean is not finite",
                        "input_nonfinite",
                        observations,
                    )
                if not float(low) <= float(value) <= float(high):
                    return self._fail(
                        RangeShiftState.INPUT_RANGE_SHIFT,
                        "channel mean %.6f outside [%s, %s]" % (float(value), low, high),
                        "input_range_shift",
                        observations,
                    )
        return None

    def _check_output(
        self, stats: Dict[str, Any], observations: Dict[str, Any]
    ) -> Optional[TensorRTRangeResult]:
        for key in ("output_raw_min", "output_raw_max", "output_raw_p99"):
            value = stats.get(key)
            if value is None:
                continue
            if not math.isfinite(float(value)):
                return self._fail(
                    RangeShiftState.NAN_OR_INF,
                    "%s is not finite" % key,
                    "output_nonfinite",
                    observations,
                )
            if abs(float(value)) > self.contract.output_abs_max:
                return self._fail(
                    RangeShiftState.OUTPUT_RANGE_INVALID,
                    "%s magnitude %.3f exceeds %.3f"
                    % (key, abs(float(value)), self.contract.output_abs_max),
                    "output_range_invalid",
                    observations,
                )
        return None

    def _check_detections(
        self, detections: Sequence[Any], observations: Dict[str, Any]
    ) -> Optional[TensorRTRangeResult]:
        if len(detections) > self.contract.max_detections:
            return self._fail(
                RangeShiftState.OUTPUT_RANGE_INVALID,
                "%d detections exceed max %d" % (len(detections), self.contract.max_detections),
                "detection_count_exceeded",
                observations,
            )
        for detection in detections:
            confidence = float(getattr(detection, "confidence", float("nan")))
            if not math.isfinite(confidence):
                return self._fail(
                    RangeShiftState.NAN_OR_INF,
                    "detection confidence is not finite",
                    "output_nonfinite",
                    observations,
                )
            if not self.contract.confidence_min <= confidence <= self.contract.confidence_max:
                return self._fail(
                    RangeShiftState.OUTPUT_RANGE_INVALID,
                    "confidence %.6f outside [%s, %s]"
                    % (confidence, self.contract.confidence_min, self.contract.confidence_max),
                    "confidence_out_of_range",
                    observations,
                )
            class_id = int(getattr(detection, "class_id", -1))
            if class_id < 0:
                return self._fail(
                    RangeShiftState.OUTPUT_RANGE_INVALID,
                    "invalid class id %d" % class_id,
                    "invalid_class_id",
                    observations,
                )
            bbox = getattr(detection, "bbox", None)
            if bbox is None or len(bbox) != 4:
                return self._fail(
                    RangeShiftState.OUTPUT_RANGE_INVALID,
                    "detection has no valid bbox",
                    "bbox_invalid",
                    observations,
                )
            if not all(math.isfinite(float(value)) for value in bbox):
                return self._fail(
                    RangeShiftState.NAN_OR_INF,
                    "bbox contains NaN/Inf",
                    "bbox_nonfinite",
                    observations,
                )
            if float(bbox[0]) > float(bbox[2]) or float(bbox[1]) > float(bbox[3]):
                return self._fail(
                    RangeShiftState.OUTPUT_RANGE_INVALID,
                    "bbox is inverted",
                    "bbox_invalid",
                    observations,
                )
        return None

    def _check_timing(
        self, inference_ms: float, result_age_ms: float, observations: Dict[str, Any]
    ) -> Optional[TensorRTRangeResult]:
        if not math.isfinite(float(inference_ms)) or float(inference_ms) < 0.0:
            return self._fail(
                RangeShiftState.OUTPUT_RANGE_INVALID,
                "inference duration is invalid",
                "inference_timing_invalid",
                observations,
            )
        if float(inference_ms) > self.contract.max_inference_ms:
            return self._fail(
                RangeShiftState.OUTPUT_RANGE_INVALID,
                "inference %.3f ms exceeded budget %.3f ms"
                % (float(inference_ms), self.contract.max_inference_ms),
                "inference_timeout",
                observations,
            )
        if float(result_age_ms) < 0.0 or float(result_age_ms) > self.contract.max_result_age_ms:
            return self._fail(
                RangeShiftState.OUTPUT_RANGE_INVALID,
                "result age %.3f ms outside [0, %d]"
                % (float(result_age_ms), self.contract.max_result_age_ms),
                "result_stale",
                observations,
            )
        return None

    # ── bookkeeping ─────────────────────────────────────────────────────────

    def _fail(
        self,
        state: RangeShiftState,
        reason: str,
        classification: str,
        observations: Dict[str, Any],
    ) -> TensorRTRangeResult:
        self._consecutive_valid = 0
        self._ever_failed = True
        self.reject_count += 1
        self.reject_counts[classification] = self.reject_counts.get(classification, 0) + 1
        return TensorRTRangeResult(
            state=state,
            sample_valid=False,
            ai_result_valid=False,
            reason=reason,
            classification=classification,
            consecutive_valid_samples=0,
            recovered=False,
            observations=dict(observations),
        )

    def evidence(self) -> Dict[str, Any]:
        """Phase 13C required range-validation evidence fields."""

        return {
            "input_range_checked": True,
            "tensor_output_range_checked": True,
            "detection_schema_checked": True,
            "activation_range_checked": False,
            "quantization_saturation_checked": False,
            "int8_calibration_range_checked": False,
            "range_validation_scope": RANGE_VALIDATION_SCOPE,
            "range_evaluation_count": self.evaluation_count,
            "tensorrt_range_reject_count": self.reject_count,
            "range_reject_counts": dict(self.reject_counts),
            "range_contract": self.contract.to_dict(),
            "activation_evidence_claimed": False,
            "quantization_evidence_claimed": False,
            "internal_tensor_monitoring_claimed": False,
        }

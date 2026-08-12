"""Phase 13D INT8 input-envelope / output range contract, fail-closed.

Phase 13C gated the engine input tensor and the final decoded output. INT8 adds
one failure mode those checks cannot see: the engine's activation scales were
fixed at calibration time, so a frame drawn from outside the calibration
distribution is quantized with the wrong scales even though every value is
still a perfectly finite number inside ``[0, 1]``.

This monitor therefore adds a **calibration envelope** check on the source
frame, derived from the calibration split only, and keeps every Phase 13C rule:
any violation fails closed, and after any rejection three consecutive valid
results are required before AI authority may resume.

What is still *not* claimed, and is written into the evidence as false:

    activation_range_checked                    = false
    runtime_internal_activation_observed        = false
    quantization_saturation_checked_at_runtime  = false
    qat_verified                                = false

A serialized TensorRT plan does not expose its internal activations, so the
activation evidence in this phase is an **offline proxy** measured on the
source model — never a runtime observation of TensorRT's own tensors.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.int8_calibration_dataset import CalibrationEnvelopes
from workers.core.range_shift_monitor import RangeShiftState
from workers.core.tensorrt_range_monitor import (
    TensorRTRangeContract,
    TensorRTRangeMonitor,
    TensorRTRangeResult,
)

RANGE_VALIDATION_SCOPE_INT8 = "tensorrt_int8_input_envelope_and_final_output"


@dataclass(frozen=True)
class Int8RangeContract(TensorRTRangeContract):
    """Phase 13C bounds plus the INT8 calibration-envelope switch.

    ``authoritative`` defaults to **False** because of the Phase 13D-MP-RECOVERY
    freeze: a bounded PTQ mixed-precision sensitivity search did not recover
    INT8-vs-FP16 parity, so an INT8 result may be produced and recorded but may
    not grant AI authority. Turning it on is an explicit, deliberate act.
    """

    calibration_envelope_enforced: bool = True
    precision: str = "int8"
    authoritative: bool = False


def runtime_statistics(stats: Dict[str, Any]) -> Dict[str, Any]:
    """Project runtime preprocess statistics onto the dataset statistic names.

    The envelope was built from *source frame* statistics, so it must be
    evaluated against the source frame here too. Letterbox padding would shift
    every channel mean toward the pad grey and make the comparison meaningless.
    """

    means = stats.get("source_channel_means")
    if means is None:
        means = stats.get("channel_means")
    stds = stats.get("source_channel_stds")
    if stds is None:
        stds = stats.get("channel_stds")
    projected = {
        "channel_means": list(means) if isinstance(means, (list, tuple)) else [],
        "channel_stds": list(stds) if isinstance(stds, (list, tuple)) else [],
    }  # type: Dict[str, Any]
    for source_key, target_key in (
        ("source_input_min", "pixel_min"),
        ("source_input_max", "pixel_max"),
    ):
        value = stats.get(source_key)
        if value is not None:
            projected[target_key] = float(value)
    # Every channel has the same pixel count, so the mean over all pixels and
    # channels is exactly the mean of the per-channel means.
    finite_means = [
        float(value) for value in projected["channel_means"] if math.isfinite(float(value))
    ]
    if finite_means and len(finite_means) == len(projected["channel_means"]):
        projected["pixel_mean"] = sum(finite_means) / float(len(finite_means))
    return projected


class Int8RangeMonitor(TensorRTRangeMonitor):
    """Fail-closed INT8 gate: Phase 13C checks plus the calibration envelope."""

    def __init__(
        self,
        contract: Optional[TensorRTRangeContract] = None,
        *,
        envelopes: Optional[CalibrationEnvelopes] = None,
        activation_proxy: Optional[Dict[str, Any]] = None,
    ) -> None:
        super(Int8RangeMonitor, self).__init__(contract or Int8RangeContract())
        self.envelopes = envelopes
        self.activation_proxy = dict(activation_proxy or {})
        self.envelope_reject_count = 0
        self.envelope_violation_counts = {}  # type: Dict[str, int]
        self.envelope_evaluation_count = 0
        self.non_authoritative_suppression_count = 0

    @property
    def authoritative(self) -> bool:
        return bool(getattr(self.contract, "authoritative", False))

    def evaluate(self, **kwargs: Any) -> TensorRTRangeResult:
        """Every Phase 13C/13D check, then the authority policy on top.

        A non-authoritative backend still runs, still validates and still
        records — it simply cannot grant AI authority. The result is reported as
        ``RECOVERY_PENDING`` rather than as a fault, because nothing failed: the
        sample is valid and the refusal is a policy decision, not a rejection.
        Reject counters are therefore deliberately left untouched.
        """

        verdict = super(Int8RangeMonitor, self).evaluate(**kwargs)
        if self.authoritative or not verdict.ai_result_valid:
            return verdict
        self.non_authoritative_suppression_count += 1
        return TensorRTRangeResult(
            state=RangeShiftState.RECOVERY_PENDING,
            sample_valid=True,
            ai_result_valid=False,
            reason=(
                "INT8 backend is experimental_non_authoritative under the "
                "Phase 13D-MP-RECOVERY freeze; AI authority withheld"
            ),
            classification="int8_non_authoritative",
            consecutive_valid_samples=verdict.consecutive_valid_samples,
            recovered=False,
            observations=dict(verdict.observations),
        )

    # ── checks ──────────────────────────────────────────────────────────────

    def _check_input(
        self, stats: Dict[str, Any], observations: Dict[str, Any]
    ) -> Optional[TensorRTRangeResult]:
        verdict = super(Int8RangeMonitor, self)._check_input(stats, observations)
        if verdict is not None:
            return verdict
        return self._check_calibration_envelope(stats, observations)

    def _check_calibration_envelope(
        self, stats: Dict[str, Any], observations: Dict[str, Any]
    ) -> Optional[TensorRTRangeResult]:
        enforced = bool(getattr(self.contract, "calibration_envelope_enforced", True))
        if not enforced:
            return None
        if self.envelopes is None:
            # An INT8 engine without its envelope cannot be gated, and an
            # ungateable result must never be allowed to grant AI authority.
            return self._fail(
                RangeShiftState.INPUT_RANGE_SHIFT,
                "INT8 calibration envelope is required but was not loaded",
                "calibration_envelope_missing",
                observations,
            )
        projected = runtime_statistics(stats)
        observations["calibration_envelope_enforced"] = True
        observations["source_pixel_mean"] = (
            round(float(projected["pixel_mean"]), 6) if "pixel_mean" in projected else None
        )
        self.envelope_evaluation_count += 1
        violations = self.envelopes.violations(projected)
        if violations:
            observations["calibration_envelope_violations"] = list(violations)
            self.envelope_reject_count += 1
            for item in violations:
                self.envelope_violation_counts[item] = self.envelope_violation_counts.get(item, 0) + 1
            return self._fail(
                RangeShiftState.INPUT_RANGE_SHIFT,
                "source frame outside the INT8 calibration envelope: %s" % ", ".join(violations[:4]),
                "calibration_range_shift",
                observations,
            )
        return None

    # ── evidence ────────────────────────────────────────────────────────────

    def evidence(self) -> Dict[str, Any]:
        payload = super(Int8RangeMonitor, self).evidence()
        payload.update(
            {
                "precision": "int8",
                "range_validation_scope": RANGE_VALIDATION_SCOPE_INT8,
                "int8_calibration_range_checked": True,
                "calibration_envelope_loaded": self.envelopes is not None,
                "calibration_envelope_enforced": bool(
                    getattr(self.contract, "calibration_envelope_enforced", True)
                ),
                "calibration_envelope_evaluation_count": self.envelope_evaluation_count,
                "calibration_envelope_reject_count": self.envelope_reject_count,
                "calibration_envelope_violation_counts": dict(self.envelope_violation_counts),
                "calibration_envelope": self.envelopes.to_dict() if self.envelopes else None,
                # Phase 13D-MP-RECOVERY freeze policy, reported as measured.
                "int8_authoritative": self.authoritative,
                "int8_backend_role": (
                    "authoritative" if self.authoritative else "experimental_non_authoritative"
                ),
                "int8_may_grant_ai_active": self.authoritative,
                "int8_non_authoritative_suppression_count": self.non_authoritative_suppression_count,
                # Still not claimed at runtime, and never inferred from the plan.
                "activation_range_checked": False,
                "runtime_internal_activation_observed": False,
                "quantization_saturation_checked_at_runtime": False,
                "internal_tensor_monitoring_claimed": False,
                "qat_verified": False,
            }
        )
        if self.activation_proxy:
            payload["activation_proxy"] = dict(self.activation_proxy)
            payload["activation_proxy_available"] = True
            payload["activation_proxy_is_offline_source_model_only"] = True
        else:
            payload["activation_proxy_available"] = False
        return payload


def load_envelopes(path: Optional[str]) -> Optional[CalibrationEnvelopes]:
    """Load calibration envelopes from a JSON file, or ``None`` when absent."""

    if not path:
        return None
    import json

    candidate = Path(path)
    if not candidate.is_file():
        return None
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "calibration_envelope" in payload:
        payload = payload["calibration_envelope"]
    if not isinstance(payload, dict):
        return None
    return CalibrationEnvelopes.from_dict(payload)


def envelope_from_bounds(
    channel_mean_bounds: Sequence[Sequence[float]],
    channel_std_bounds: Sequence[Sequence[float]],
    *,
    pixel_min_bounds: Optional[Sequence[float]] = None,
    pixel_max_bounds: Optional[Sequence[float]] = None,
    pixel_mean_bounds: Optional[Sequence[float]] = None,
) -> CalibrationEnvelopes:
    """Small helper used by tests and fault injection to build an envelope."""

    return CalibrationEnvelopes(
        channel_mean_bounds=[[float(low), float(high)] for low, high in channel_mean_bounds],
        channel_std_bounds=[[float(low), float(high)] for low, high in channel_std_bounds],
        pixel_min_bounds=[float(value) for value in (pixel_min_bounds or [])],
        pixel_max_bounds=[float(value) for value in (pixel_max_bounds or [])],
        pixel_mean_bounds=[float(value) for value in (pixel_mean_bounds or [])],
    )


def envelope_violation_names(
    envelopes: CalibrationEnvelopes, statistics: Dict[str, Any]
) -> List[str]:
    return envelopes.violations(statistics)

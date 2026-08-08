"""模型輸入、activation 與輸出範圍契約監控。

此模組只做可重現的數值契約判定，不推斷模型準確率。任何異常都會
使目前 AI 結果失效；異常解除後，仍需連續有效樣本才能恢復 AI authority。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Mapping, Sequence

import numpy as np


class RangeShiftState(IntEnum):
    """寫入 embedded command packet 的範圍狀態碼。"""

    VALID = 0
    INPUT_RANGE_SHIFT = 1
    NORMALIZATION_MISMATCH = 2
    COLOR_ORDER_MISMATCH = 3
    NAN_OR_INF = 4
    ACTIVATION_RANGE_SHIFT = 5
    QUANTIZATION_SATURATION = 6
    OUTPUT_RANGE_INVALID = 7
    RECOVERY_PENDING = 8


@dataclass(frozen=True)
class RangeContract:
    """部署時必須由模型校正資料覆寫的 range contract。"""

    source_pixel_format: str = "BGR8"
    model_color_order: str = "RGB"
    input_dtype: str = "float32"
    input_layout: str = "NCHW"
    raw_input_min: float = 0.0
    raw_input_max: float = 255.0
    normalized_min: float = 0.0
    normalized_max: float = 1.0
    channel_mean_bounds: tuple[tuple[float, float], ...] = (
        (0.20, 0.80),
        (0.20, 0.80),
        (0.20, 0.80),
    )
    channel_std_bounds: tuple[tuple[float, float], ...] = (
        (0.05, 0.40),
        (0.05, 0.40),
        (0.05, 0.40),
    )
    selected_activation_percentile_bounds: Mapping[str, tuple[float, float]] = field(
        default_factory=lambda: {
            "p01": (-4.0, 0.0),
            "p99": (0.0, 4.0),
        }
    )
    max_saturation_ratio: float = 0.02
    max_result_age_ms: int = 150
    recovery_valid_samples: int = 3

    def __post_init__(self) -> None:
        if self.raw_input_min >= self.raw_input_max:
            raise ValueError("raw_input_min 必須小於 raw_input_max")
        if self.normalized_min >= self.normalized_max:
            raise ValueError("normalized_min 必須小於 normalized_max")
        if not 0.0 <= self.max_saturation_ratio <= 1.0:
            raise ValueError("max_saturation_ratio 必須介於 0 與 1")
        if self.max_result_age_ms <= 0 or self.recovery_valid_samples <= 0:
            raise ValueError("age 與 recovery 門檻必須大於 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_pixel_format": self.source_pixel_format,
            "model_color_order": self.model_color_order,
            "input_dtype": self.input_dtype,
            "input_layout": self.input_layout,
            "raw_input_min": self.raw_input_min,
            "raw_input_max": self.raw_input_max,
            "normalized_min": self.normalized_min,
            "normalized_max": self.normalized_max,
            "channel_mean_bounds": [list(item) for item in self.channel_mean_bounds],
            "channel_std_bounds": [list(item) for item in self.channel_std_bounds],
            "selected_activation_percentile_bounds": {
                key: list(value)
                for key, value in self.selected_activation_percentile_bounds.items()
            },
            "max_saturation_ratio": self.max_saturation_ratio,
            "max_result_age_ms": self.max_result_age_ms,
            "recovery_valid_samples": self.recovery_valid_samples,
        }


@dataclass(frozen=True)
class RangeShiftResult:
    """單次檢查結果與恢復門檻狀態。"""

    state: RangeShiftState
    sample_valid: bool
    ai_result_valid: bool
    reason: str
    consecutive_valid_samples: int
    recovered: bool
    observations: Mapping[str, Any]


class RangeShiftMonitor:
    """以 fail-closed 策略執行 range contract 與恢復閘門。"""

    def __init__(self, contract: RangeContract | None = None) -> None:
        self.contract = contract or RangeContract()
        self._consecutive_valid = 0
        self._ever_failed = False
        self._failure_counts: dict[str, int] = {
            state.name.lower(): 0
            for state in RangeShiftState
            if state not in (RangeShiftState.VALID, RangeShiftState.RECOVERY_PENDING)
        }
        self._range_shift_detection_count = 0

    @property
    def failure_counts(self) -> dict[str, int]:
        return dict(self._failure_counts)

    @property
    def range_shift_detection_count(self) -> int:
        return self._range_shift_detection_count

    def evaluate(
        self,
        *,
        raw_input: np.ndarray,
        normalized_input: np.ndarray,
        source_pixel_format: str,
        model_color_order: str,
        input_layout: str,
        activations: Mapping[str, np.ndarray] | None = None,
        quantized_activations: Mapping[str, tuple[np.ndarray, int, int]] | None = None,
        outputs: Mapping[str, float] | None = None,
        result_age_ms: float = 0.0,
    ) -> RangeShiftResult:
        """依固定優先序判定，使相同輸入永遠得到相同拒絕原因。"""

        observations: dict[str, Any] = {"result_age_ms": float(result_age_ms)}
        arrays = [raw_input, normalized_input]
        arrays.extend((activations or {}).values())
        arrays.extend(item[0] for item in (quantized_activations or {}).values())
        if any(not np.all(np.isfinite(array)) for array in arrays):
            return self._fail(RangeShiftState.NAN_OR_INF, "輸入或 activation 含 NaN/Inf", observations)

        if source_pixel_format != self.contract.source_pixel_format or model_color_order != self.contract.model_color_order:
            observations.update(
                {
                    "source_pixel_format": source_pixel_format,
                    "model_color_order": model_color_order,
                }
            )
            return self._fail(RangeShiftState.COLOR_ORDER_MISMATCH, "pixel format 或 model color order 不符", observations)

        if input_layout != self.contract.input_layout or normalized_input.dtype.name != self.contract.input_dtype:
            observations.update(
                {"input_layout": input_layout, "input_dtype": normalized_input.dtype.name}
            )
            return self._fail(RangeShiftState.NORMALIZATION_MISMATCH, "input dtype 或 layout 不符", observations)

        raw_min = float(np.min(raw_input))
        raw_max = float(np.max(raw_input))
        observations.update({"raw_input_min": raw_min, "raw_input_max": raw_max})
        if raw_min < self.contract.raw_input_min or raw_max > self.contract.raw_input_max:
            return self._fail(RangeShiftState.INPUT_RANGE_SHIFT, "raw input 超出校正範圍", observations)

        norm_min = float(np.min(normalized_input))
        norm_max = float(np.max(normalized_input))
        observations.update({"normalized_min": norm_min, "normalized_max": norm_max})
        epsilon = 1e-6
        if norm_min < self.contract.normalized_min - epsilon or norm_max > self.contract.normalized_max + epsilon:
            return self._fail(RangeShiftState.NORMALIZATION_MISMATCH, "normalized input 超出契約範圍", observations)

        channels = self._channels(normalized_input, input_layout)
        means = [float(np.mean(channel)) for channel in channels]
        stds = [float(np.std(channel)) for channel in channels]
        observations.update({"channel_means": means, "channel_stds": stds})
        if not self._within_channel_bounds(means, self.contract.channel_mean_bounds) or not self._within_channel_bounds(stds, self.contract.channel_std_bounds):
            return self._fail(RangeShiftState.INPUT_RANGE_SHIFT, "channel mean/std 超出校正範圍", observations)

        for name, values in (activations or {}).items():
            for percentile_name, bounds in self.contract.selected_activation_percentile_bounds.items():
                percentile = self._parse_percentile(percentile_name)
                value = float(np.percentile(values, percentile))
                observations[f"activation.{name}.{percentile_name}"] = value
                if value < bounds[0] or value > bounds[1]:
                    return self._fail(
                        RangeShiftState.ACTIVATION_RANGE_SHIFT,
                        f"activation {name} {percentile_name} 超出範圍",
                        observations,
                    )

        for name, (values, quant_min, quant_max) in (quantized_activations or {}).items():
            saturation_ratio = float(np.mean((values <= quant_min) | (values >= quant_max)))
            observations[f"quantization.{name}.saturation_ratio"] = saturation_ratio
            if saturation_ratio > self.contract.max_saturation_ratio:
                return self._fail(
                    RangeShiftState.QUANTIZATION_SATURATION,
                    f"quantized activation {name} 飽和比例過高",
                    observations,
                )

        if result_age_ms < 0.0 or result_age_ms > self.contract.max_result_age_ms:
            return self._fail(RangeShiftState.OUTPUT_RANGE_INVALID, "AI result age 超出範圍", observations)

        if not self._outputs_valid(outputs or {}):
            observations["outputs"] = dict(outputs or {})
            return self._fail(RangeShiftState.OUTPUT_RANGE_INVALID, "control/confidence output 超出範圍", observations)

        self._consecutive_valid += 1
        recovered = self._ever_failed and self._consecutive_valid >= self.contract.recovery_valid_samples
        if self._consecutive_valid < self.contract.recovery_valid_samples:
            return RangeShiftResult(
                state=RangeShiftState.RECOVERY_PENDING,
                sample_valid=True,
                ai_result_valid=False,
                reason="等待連續有效樣本完成恢復",
                consecutive_valid_samples=self._consecutive_valid,
                recovered=False,
                observations=observations,
            )
        return RangeShiftResult(
            state=RangeShiftState.VALID,
            sample_valid=True,
            ai_result_valid=True,
            reason="range contract valid",
            consecutive_valid_samples=self._consecutive_valid,
            recovered=recovered,
            observations=observations,
        )

    def _fail(
        self,
        state: RangeShiftState,
        reason: str,
        observations: Mapping[str, Any],
    ) -> RangeShiftResult:
        self._consecutive_valid = 0
        self._ever_failed = True
        self._range_shift_detection_count += 1
        self._failure_counts[state.name.lower()] += 1
        return RangeShiftResult(
            state=state,
            sample_valid=False,
            ai_result_valid=False,
            reason=reason,
            consecutive_valid_samples=0,
            recovered=False,
            observations=dict(observations),
        )

    @staticmethod
    def _channels(array: np.ndarray, layout: str) -> Sequence[np.ndarray]:
        if layout == "NCHW" and array.ndim == 4:
            return [array[:, index, :, :] for index in range(array.shape[1])]
        if layout == "CHW" and array.ndim == 3:
            return [array[index, :, :] for index in range(array.shape[0])]
        if layout == "NHWC" and array.ndim == 4:
            return [array[:, :, :, index] for index in range(array.shape[3])]
        if layout == "HWC" and array.ndim == 3:
            return [array[:, :, index] for index in range(array.shape[2])]
        return [array]

    @staticmethod
    def _within_channel_bounds(values: Sequence[float], bounds: Sequence[tuple[float, float]]) -> bool:
        return len(values) == len(bounds) and all(
            low <= value <= high for value, (low, high) in zip(values, bounds, strict=True)
        )

    @staticmethod
    def _parse_percentile(name: str) -> float:
        if not name.startswith("p"):
            raise ValueError(f"無效 percentile 名稱: {name}")
        value = float(name[1:])
        if not math.isfinite(value) or not 0.0 <= value <= 100.0:
            raise ValueError(f"無效 percentile: {name}")
        return value

    @staticmethod
    def _outputs_valid(outputs: Mapping[str, float]) -> bool:
        bounds = {
            "steering": (-1.0, 1.0),
            "throttle": (0.0, 1.0),
            "brake": (0.0, 1.0),
            "ai_confidence": (0.0, 1.0),
        }
        for name, (low, high) in bounds.items():
            value = outputs.get(name)
            if value is None or not math.isfinite(float(value)) or not low <= float(value) <= high:
                return False
        return True

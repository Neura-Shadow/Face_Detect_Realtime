"""Phase 13D offline activation proxy.

A serialized TensorRT plan does not expose the tensors flowing between its
layers, and Phase 13D neither patches TensorRT nor claims to watch them. What
it *can* do honestly is measure the activation distributions of the **source
model** on the same calibration frames, offline, on the simulation PC, and use
that as a proxy for where INT8 quantization is tight.

Every artefact this module writes therefore carries:

    activation_proxy_backend                 = "pytorch_forward_hooks_offline"
    runtime_tensorrt_internal_activations_observed = false
    internal_tensor_monitoring_claimed       = false

The statistics themselves are exact streaming aggregates (count, min, max,
mean, std, zero fraction) plus histogram-derived tail quantiles of ``|x|``.
The histogram is explicit about its own limits: values above the configured
cap are counted separately and reported, never silently clamped into the last
bin without trace.

Runtime compatibility: Jetson Python 3.8.10 (the collector itself only ever
runs on the PC, but the aggregation half must stay importable everywhere).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np

ACTIVATION_PROXY_BACKEND = "pytorch_forward_hooks_offline"
MIN_PROXY_LAYERS = 8
DEFAULT_HISTOGRAM_BINS = 2048
DEFAULT_HISTOGRAM_MAX = 512.0
INT8_SYMMETRIC_LEVELS = 127.0


class ActivationProxyError(RuntimeError):
    """Activation-proxy failure carrying a Phase 13D classification."""

    def __init__(self, classification: str, message: str) -> None:
        super().__init__("%s: %s" % (classification, message))
        self.classification = classification
        self.message = message


@dataclass
class LayerActivationSummary:
    """One observed layer's activation distribution."""

    name: str = ""
    layer_type: str = ""
    sample_count: int = 0
    observation_count: int = 0
    minimum: float = 0.0
    maximum: float = 0.0
    absmax: float = 0.0
    mean: float = 0.0
    std: float = 0.0
    zero_fraction: float = 0.0
    abs_p99: float = 0.0
    abs_p999: float = 0.0
    abs_p9999: float = 0.0
    histogram_overflow_count: int = 0
    histogram_overflow_fraction: float = 0.0
    int8_step_at_absmax: float = 0.0
    int8_step_at_p999: float = 0.0
    outlier_ratio_absmax_over_p999: float = 0.0
    relative_quantization_step: float = 0.0
    clipped_fraction_at_p999_scale: float = 0.0
    nonfinite_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class LayerActivationAccumulator:
    """Streaming aggregate for one layer; never stores the tensors."""

    def __init__(
        self,
        name: str,
        layer_type: str = "",
        *,
        histogram_bins: int = DEFAULT_HISTOGRAM_BINS,
        histogram_max: float = DEFAULT_HISTOGRAM_MAX,
    ) -> None:
        self.name = str(name)
        self.layer_type = str(layer_type)
        self.histogram_bins = int(histogram_bins)
        self.histogram_max = float(histogram_max)
        self.count = 0
        self.observation_count = 0
        self.minimum = None  # type: Optional[float]
        self.maximum = None  # type: Optional[float]
        self.absmax = 0.0
        self._sum = 0.0
        self._sum_squares = 0.0
        self.zero_count = 0
        self.nonfinite_count = 0
        self.overflow_count = 0
        self._histogram = np.zeros(self.histogram_bins, dtype=np.int64)

    def update(self, values: Any) -> None:
        array = np.asarray(values, dtype=np.float64).reshape(-1)
        if array.size == 0:
            return
        self.observation_count += 1
        finite_mask = np.isfinite(array)
        nonfinite = int(array.size - int(np.count_nonzero(finite_mask)))
        if nonfinite:
            self.nonfinite_count += nonfinite
            array = array[finite_mask]
            if array.size == 0:
                return
        self.count += int(array.size)
        self._sum += float(array.sum())
        self._sum_squares += float(np.square(array).sum())
        low = float(array.min())
        high = float(array.max())
        self.minimum = low if self.minimum is None else min(self.minimum, low)
        self.maximum = high if self.maximum is None else max(self.maximum, high)
        magnitudes = np.abs(array)
        self.absmax = max(self.absmax, float(magnitudes.max()))
        self.zero_count += int(np.count_nonzero(array == 0.0))

        over = magnitudes >= self.histogram_max
        self.overflow_count += int(np.count_nonzero(over))
        inside = magnitudes[~over]
        if inside.size:
            indices = np.minimum(
                (inside / self.histogram_max * self.histogram_bins).astype(np.int64),
                self.histogram_bins - 1,
            )
            self._histogram += np.bincount(indices, minlength=self.histogram_bins)

    def _abs_quantile(self, quantile: float) -> float:
        """Tail quantile of ``|x|`` from the histogram, overflow-aware."""

        total = self.count
        if total <= 0:
            return 0.0
        target = float(quantile) * total
        cumulative = np.cumsum(self._histogram)
        inside_total = int(cumulative[-1]) if cumulative.size else 0
        if target > inside_total:
            # The quantile lands in the overflow tail; the histogram cannot
            # resolve it, so report the true absolute maximum instead of a
            # fabricated bin edge.
            return float(self.absmax)
        index = int(np.searchsorted(cumulative, target, side="left"))
        index = max(0, min(self.histogram_bins - 1, index))
        return float((index + 1) * self.histogram_max / self.histogram_bins)

    def summary(self) -> LayerActivationSummary:
        if self.count <= 0:
            raise ActivationProxyError(
                "activation_proxy_empty", "layer %s observed no activations" % self.name
            )
        mean = self._sum / self.count
        variance = max(0.0, self._sum_squares / self.count - mean * mean)
        std = math.sqrt(variance)
        p99 = self._abs_quantile(0.99)
        p999 = self._abs_quantile(0.999)
        p9999 = self._abs_quantile(0.9999)
        step_absmax = self.absmax / INT8_SYMMETRIC_LEVELS if self.absmax else 0.0
        step_p999 = p999 / INT8_SYMMETRIC_LEVELS if p999 else 0.0
        clipped = 0.0
        if self.count:
            above = int(self.overflow_count)
            cumulative = np.cumsum(self._histogram)
            bin_index = int(min(self.histogram_bins - 1, max(0, round(p999 / self.histogram_max * self.histogram_bins) - 1)))
            inside_below = int(cumulative[bin_index]) if cumulative.size else 0
            above += max(0, int(cumulative[-1]) - inside_below) if cumulative.size else 0
            clipped = above / float(self.count)
        return LayerActivationSummary(
            name=self.name,
            layer_type=self.layer_type,
            sample_count=self.count,
            observation_count=self.observation_count,
            minimum=round(float(self.minimum if self.minimum is not None else 0.0), 6),
            maximum=round(float(self.maximum if self.maximum is not None else 0.0), 6),
            absmax=round(float(self.absmax), 6),
            mean=round(float(mean), 6),
            std=round(float(std), 6),
            zero_fraction=round(self.zero_count / float(self.count), 6),
            abs_p99=round(p99, 6),
            abs_p999=round(p999, 6),
            abs_p9999=round(p9999, 6),
            histogram_overflow_count=int(self.overflow_count),
            histogram_overflow_fraction=round(self.overflow_count / float(self.count), 8),
            int8_step_at_absmax=round(step_absmax, 8),
            int8_step_at_p999=round(step_p999, 8),
            outlier_ratio_absmax_over_p999=round(self.absmax / p999, 6) if p999 > 0 else 0.0,
            relative_quantization_step=round(step_p999 / std, 6) if std > 0 else 0.0,
            clipped_fraction_at_p999_scale=round(clipped, 8),
            nonfinite_count=int(self.nonfinite_count),
        )


class ActivationProxyCollector:
    """Aggregates several layers at once; TensorRT and torch free."""

    def __init__(
        self,
        *,
        histogram_bins: int = DEFAULT_HISTOGRAM_BINS,
        histogram_max: float = DEFAULT_HISTOGRAM_MAX,
    ) -> None:
        self.histogram_bins = int(histogram_bins)
        self.histogram_max = float(histogram_max)
        self._layers = {}  # type: Dict[str, LayerActivationAccumulator]
        self._order = []  # type: List[str]
        self.frames_observed = 0

    def observe(self, name: str, values: Any, *, layer_type: str = "") -> None:
        key = str(name)
        if key not in self._layers:
            self._layers[key] = LayerActivationAccumulator(
                key,
                layer_type,
                histogram_bins=self.histogram_bins,
                histogram_max=self.histogram_max,
            )
            self._order.append(key)
        self._layers[key].update(values)

    def mark_frame(self) -> None:
        self.frames_observed += 1

    @property
    def layer_count(self) -> int:
        return len(self._layers)

    def summaries(self) -> List[LayerActivationSummary]:
        return [self._layers[name].summary() for name in self._order]

    def report(self, *, min_layers: int = MIN_PROXY_LAYERS) -> Dict[str, Any]:
        summaries = self.summaries() if self._layers else []
        blockers = []  # type: List[str]
        if len(summaries) < int(min_layers):
            blockers.append("activation_proxy_layer_count_insufficient")
        if not self.frames_observed:
            blockers.append("activation_proxy_frames_missing")
        if any(item.nonfinite_count for item in summaries):
            blockers.append("activation_proxy_nonfinite")
        return {
            "activation_proxy_backend": ACTIVATION_PROXY_BACKEND,
            "activation_proxy_layer_count": len(summaries),
            "activation_proxy_min_layers_required": int(min_layers),
            "activation_proxy_frames_observed": self.frames_observed,
            "activation_proxy_histogram_bins": self.histogram_bins,
            "activation_proxy_histogram_max": self.histogram_max,
            "activation_proxy_layers": [item.to_dict() for item in summaries],
            "activation_proxy_passed": not blockers,
            "blockers": blockers,
            # Boundary: this is a source-model proxy, never a TensorRT probe.
            "runtime_tensorrt_internal_activations_observed": False,
            "internal_tensor_monitoring_claimed": False,
            "activation_range_checked_at_runtime": False,
            "quantization_saturation_measured_on_source_model_only": True,
            "qat_verified": False,
        }


# ── PyTorch collection (simulation PC only) ─────────────────────────────────


def select_proxy_modules(model: Any, *, limit: int = 12) -> List[Any]:
    """Pick real, evenly spread leaf modules with tensor outputs.

    Convolutions are chosen because they are the layers TensorRT actually
    quantizes; picking activations or the detect head would measure something
    the INT8 build does not decide.
    """

    try:
        import torch.nn as nn  # type: ignore[import-not-found]
    except Exception as exc:
        raise ActivationProxyError("activation_proxy_torch_unavailable", repr(exc)[:200])

    candidates = [
        (name, module)
        for name, module in model.named_modules()
        if isinstance(module, (nn.Conv2d,))
    ]
    if len(candidates) < int(limit):
        candidates = [
            (name, module)
            for name, module in model.named_modules()
            if isinstance(module, (nn.Conv2d, nn.BatchNorm2d, nn.SiLU, nn.ReLU))
        ]
    if not candidates:
        raise ActivationProxyError(
            "activation_proxy_layers_unavailable", "model exposes no convolution modules"
        )
    if len(candidates) <= int(limit):
        return candidates
    stride = len(candidates) / float(limit)
    picked = []  # type: List[Any]
    for index in range(int(limit)):
        picked.append(candidates[min(len(candidates) - 1, int(round(index * stride)))])
    # Deduplicate while preserving the spread.
    seen = set()  # type: set
    unique = []  # type: List[Any]
    for name, module in picked:
        if name in seen:
            continue
        seen.add(name)
        unique.append((name, module))
    return unique


def collect_torch_activations(
    model: Any,
    tensors: Iterable[Any],
    *,
    layer_limit: int = 12,
    histogram_bins: int = DEFAULT_HISTOGRAM_BINS,
    histogram_max: float = DEFAULT_HISTOGRAM_MAX,
) -> ActivationProxyCollector:
    """Run the source model over calibration tensors with forward hooks."""

    try:
        import torch  # type: ignore[import-not-found]
    except Exception as exc:
        raise ActivationProxyError("activation_proxy_torch_unavailable", repr(exc)[:200])

    collector = ActivationProxyCollector(
        histogram_bins=histogram_bins, histogram_max=histogram_max
    )
    selected = select_proxy_modules(model, limit=layer_limit)
    handles = []  # type: List[Any]

    def _make_hook(layer_name: str, layer_type: str) -> Any:
        def _hook(_module: Any, _inputs: Any, output: Any) -> None:
            tensor = output
            if isinstance(tensor, (tuple, list)):
                tensor = tensor[0] if tensor else None
            if tensor is None or not hasattr(tensor, "detach"):
                return
            collector.observe(
                layer_name, tensor.detach().cpu().numpy(), layer_type=layer_type
            )

        return _hook

    for name, module in selected:
        handles.append(module.register_forward_hook(_make_hook(name, type(module).__name__)))

    try:
        model.eval()
        with torch.no_grad():
            for tensor in tensors:
                array = np.asarray(tensor)
                model(torch.from_numpy(array))
                collector.mark_frame()
    finally:
        for handle in handles:
            try:
                handle.remove()
            except Exception:
                pass
    return collector


def evaluate_proxy_report(
    report: Dict[str, Any], *, min_layers: int = MIN_PROXY_LAYERS
) -> Dict[str, Any]:
    """Re-check a stored proxy report against the Phase 13D minimums."""

    blockers = []  # type: List[str]
    layers = report.get("activation_proxy_layers") or []
    if len(layers) < int(min_layers):
        blockers.append("activation_proxy_layer_count_insufficient")
    if report.get("runtime_tensorrt_internal_activations_observed"):
        blockers.append("activation_proxy_claims_runtime_observation")
    for layer in layers:
        for key in ("absmax", "abs_p999", "std"):
            value = layer.get(key)
            if value is None or not math.isfinite(float(value)):
                blockers.append("activation_proxy_nonfinite")
                break
    return {
        "activation_proxy_layer_count": len(layers),
        "activation_proxy_min_layers_required": int(min_layers),
        "activation_proxy_verified": not blockers,
        "blockers": sorted(set(blockers)),
    }


def summarize_proxy_layers(summaries: Sequence[LayerActivationSummary]) -> Dict[str, Any]:
    """Aggregate view used in the phase document and evidence summary."""

    if not summaries:
        return {"activation_proxy_layer_count": 0}
    ratios = [item.outlier_ratio_absmax_over_p999 for item in summaries]
    steps = [item.relative_quantization_step for item in summaries]
    return {
        "activation_proxy_layer_count": len(summaries),
        "activation_proxy_absmax_max": round(max(item.absmax for item in summaries), 6),
        "activation_proxy_outlier_ratio_max": round(max(ratios), 6),
        "activation_proxy_outlier_ratio_mean": round(sum(ratios) / len(ratios), 6),
        "activation_proxy_relative_step_max": round(max(steps), 6),
        "activation_proxy_relative_step_mean": round(sum(steps) / len(steps), 6),
        "activation_proxy_widest_layer": max(
            summaries, key=lambda item: item.outlier_ratio_absmax_over_p999
        ).name,
    }

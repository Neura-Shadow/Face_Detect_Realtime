"""Phase 13C TensorRT FP16 perception backend (preprocess + postprocess).

Preprocess mirrors the official YOLOv9 ``utils.augmentations.letterbox`` policy
that the existing repository backend already uses, so the reference and
candidate backends see the same pixels:

    BGR8 HWC uint8
      -> letterbox to 640x640 (ratio preserving, pad 114, stride 32)
      -> BGR to RGB
      -> float32 / 255.0
      -> NCHW, contiguous, batch 1

Postprocess decodes the **actual recorded** output contract rather than a
guessed generic YOLO layout, applies class-wise NMS in numpy (no torch on the
Jetson), maps boxes back through the recorded letterbox ratio/padding, and
validates every surviving detection.

This backend never falls back. Any failure raises, the caller emits SAFE_STOP.

Runtime compatibility: Jetson Python 3.8.10 + numpy 1.17.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.edge_perception import Detection
from workers.core.tensorrt_asset_contract import (
    InputContract,
    OutputContract,
    PostprocessProfile,
)

LETTERBOX_PAD_VALUE = 114
DEFAULT_STRIDE = 32


class TensorRTPerceptionError(RuntimeError):
    """Perception contract violation carrying a Phase 13C classification."""

    def __init__(self, classification: str, message: str) -> None:
        super().__init__("%s: %s" % (classification, message))
        self.classification = classification
        self.message = message


# ── Preprocess ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LetterboxResult:
    """Everything needed to map a detection back to source-image pixels."""

    original_width: int
    original_height: int
    letterbox_width: int
    letterbox_height: int
    scale_ratio: float
    pad_x: float
    pad_y: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_width": self.original_width,
            "original_height": self.original_height,
            "letterbox_width": self.letterbox_width,
            "letterbox_height": self.letterbox_height,
            "scale_ratio": round(self.scale_ratio, 6),
            "pad_x": round(self.pad_x, 4),
            "pad_y": round(self.pad_y, 4),
        }


def letterbox_bgr(
    frame: np.ndarray,
    *,
    width: int = 640,
    height: int = 640,
    pad_value: int = LETTERBOX_PAD_VALUE,
    scaleup: bool = True,
) -> Tuple[np.ndarray, LetterboxResult]:
    """Ratio-preserving resize with symmetric padding, matching YOLOv9."""

    if frame.ndim != 3 or frame.shape[2] != 3:
        raise TensorRTPerceptionError(
            "input_shape_mismatch", "expected HxWx3 BGR frame, got %s" % (frame.shape,)
        )
    original_height, original_width = int(frame.shape[0]), int(frame.shape[1])
    if original_height <= 0 or original_width <= 0:
        raise TensorRTPerceptionError("input_shape_mismatch", "frame has a zero dimension")

    ratio = min(float(width) / original_width, float(height) / original_height)
    if not scaleup:
        ratio = min(ratio, 1.0)
    new_width = int(round(original_width * ratio))
    new_height = int(round(original_height * ratio))
    new_width = max(1, min(width, new_width))
    new_height = max(1, min(height, new_height))

    if (new_width, new_height) != (original_width, original_height):
        resized = _resize_bgr(frame, new_width, new_height)
    else:
        resized = frame

    pad_w = (width - new_width) / 2.0
    pad_h = (height - new_height) / 2.0
    top = int(round(pad_h - 0.1))
    left = int(round(pad_w - 0.1))

    canvas = np.full((height, width, 3), pad_value, dtype=np.uint8)
    canvas[top : top + new_height, left : left + new_width] = resized
    return canvas, LetterboxResult(
        original_width=original_width,
        original_height=original_height,
        letterbox_width=width,
        letterbox_height=height,
        scale_ratio=ratio,
        pad_x=float(left),
        pad_y=float(top),
    )


def _resize_bgr(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    """Resize with cv2 when present, else a deterministic nearest-neighbour."""

    try:
        import cv2  # type: ignore[import-not-found]

        interpolation = cv2.INTER_LINEAR if (
            width > frame.shape[1] or height > frame.shape[0]
        ) else cv2.INTER_AREA
        return cv2.resize(frame, (width, height), interpolation=interpolation)
    except Exception:
        rows = (np.arange(height) * (frame.shape[0] / float(height))).astype(np.int32)
        cols = (np.arange(width) * (frame.shape[1] / float(width))).astype(np.int32)
        rows = np.clip(rows, 0, frame.shape[0] - 1)
        cols = np.clip(cols, 0, frame.shape[1] - 1)
        return frame[rows][:, cols]


def preprocess_bgr(
    frame: np.ndarray,
    contract: InputContract,
) -> Tuple[np.ndarray, LetterboxResult, Dict[str, Any]]:
    """BGR8 frame -> engine-ready NCHW tensor plus the recorded input stats."""

    if frame.dtype != np.uint8:
        raise TensorRTPerceptionError(
            "input_dtype_mismatch", "expected uint8 BGR frame, got %s" % frame.dtype
        )
    canvas, letterbox = letterbox_bgr(frame, width=contract.width, height=contract.height)

    if contract.input_color_order.upper() == "RGB":
        converted = canvas[:, :, ::-1]
    elif contract.input_color_order.upper() == "BGR":
        converted = canvas
    else:
        raise TensorRTPerceptionError(
            "input_contract_mismatch", "unsupported color order %r" % contract.input_color_order
        )

    scaled = converted.astype(np.float32) / float(contract.normalization_scale)
    tensor = np.ascontiguousarray(np.transpose(scaled, (2, 0, 1))[None, ...])
    if np.dtype(contract.input_dtype) != tensor.dtype:
        tensor = np.ascontiguousarray(tensor.astype(np.dtype(contract.input_dtype)))

    if not np.all(np.isfinite(tensor)):
        raise TensorRTPerceptionError("input_nonfinite", "preprocessed tensor contains NaN/Inf")

    stats = {
        "input_min": float(np.min(tensor)),
        "input_max": float(np.max(tensor)),
        "channel_means": [float(np.mean(tensor[0, index])) for index in range(tensor.shape[1])],
        "channel_stds": [float(np.std(tensor[0, index])) for index in range(tensor.shape[1])],
        "input_dtype": str(tensor.dtype),
        "input_contiguous": bool(tensor.flags["C_CONTIGUOUS"]),
        "input_color_order": contract.input_color_order,
        "source_pixel_format": contract.source_pixel_format,
        "normalization_scale": float(contract.normalization_scale),
    }
    stats.update(letterbox.to_dict())
    return tensor, letterbox, stats


# ── Output decoding ─────────────────────────────────────────────────────────


def infer_output_layout(
    shape: Sequence[int], declared_layout: Optional[str] = None
) -> Dict[str, Any]:
    """Derive the decode layout from a real output shape.

    ``(1, 4 + nc, anchors)`` is channels-first (the YOLOv9/v8 converted head);
    ``(1, anchors, 4 + nc)`` is anchors-first; ``(1, anchors, 5 + nc)`` is the
    legacy objectness encoding.

    An axis shorter than 5 elements cannot be the attribute axis, so it is
    excluded first. A naive "larger axis is the anchor axis" rule would
    misread a single-anchor tensor such as ``(1, 84, 1)``. When both readings
    remain possible the recorded contract decides, and only if there is no
    recorded contract does the larger anchor count break the tie.
    """

    dims = [int(value) for value in shape]
    if len(dims) != 3 or dims[0] != 1:
        raise TensorRTPerceptionError(
            "output_shape_mismatch", "expected a rank-3 batch-1 output, got %s" % dims
        )

    candidates = []  # type: List[Dict[str, Any]]
    if dims[2] >= 5:
        candidates.append({"layout": "anchors_first", "anchors": dims[1], "attributes": dims[2]})
    if dims[1] >= 5:
        candidates.append({"layout": "channels_first", "anchors": dims[2], "attributes": dims[1]})
    if not candidates:
        raise TensorRTPerceptionError(
            "output_shape_mismatch", "no axis of %s is wide enough to decode" % dims
        )

    chosen = None  # type: Optional[Dict[str, Any]]
    declared = (declared_layout or "").strip()
    if declared and declared != "unknown":
        for candidate in candidates:
            if candidate["layout"] == declared:
                chosen = candidate
                break
        if chosen is None:
            raise TensorRTPerceptionError(
                "output_shape_mismatch",
                "output shape %s cannot be read as the recorded layout %s" % (dims, declared),
            )
    elif len(candidates) == 1:
        chosen = candidates[0]
    else:
        chosen = max(candidates, key=lambda item: item["anchors"])

    result = dict(chosen)
    result["shape"] = dims
    return result


def _xywh_to_xyxy(boxes: np.ndarray) -> np.ndarray:
    converted = np.empty_like(boxes)
    half_w = boxes[:, 2] / 2.0
    half_h = boxes[:, 3] / 2.0
    converted[:, 0] = boxes[:, 0] - half_w
    converted[:, 1] = boxes[:, 1] - half_h
    converted[:, 2] = boxes[:, 0] + half_w
    converted[:, 3] = boxes[:, 1] + half_h
    return converted


def nms_numpy(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> List[int]:
    """Greedy IoU NMS in pure numpy (no torch on the Jetson)."""

    if boxes.size == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]
    keep = []  # type: List[int]
    while order.size > 0:
        current = int(order[0])
        keep.append(current)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[current], x1[rest])
        yy1 = np.maximum(y1[current], y1[rest])
        xx2 = np.minimum(x2[current], x2[rest])
        yy2 = np.minimum(y2[current], y2[rest])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        union = areas[current] + areas[rest] - inter
        iou = np.where(union > 0, inter / np.maximum(union, 1e-12), 0.0)
        order = rest[iou <= iou_threshold]
    return keep


def reverse_letterbox(boxes: np.ndarray, letterbox: LetterboxResult) -> np.ndarray:
    """Map letterbox-space xyxy boxes back to source pixels and clip them."""

    if boxes.size == 0:
        return boxes
    mapped = boxes.copy().astype(np.float32)
    mapped[:, [0, 2]] -= float(letterbox.pad_x)
    mapped[:, [1, 3]] -= float(letterbox.pad_y)
    ratio = max(letterbox.scale_ratio, 1e-9)
    mapped /= ratio
    mapped[:, [0, 2]] = np.clip(mapped[:, [0, 2]], 0.0, float(letterbox.original_width))
    mapped[:, [1, 3]] = np.clip(mapped[:, [1, 3]], 0.0, float(letterbox.original_height))
    return mapped


@dataclass
class DecodedDetections:
    """Validated detections plus the raw-tensor statistics used to gate them."""

    detections: List[Detection] = field(default_factory=list)
    raw_min: float = 0.0
    raw_max: float = 0.0
    raw_p99: float = 0.0
    candidate_count: int = 0
    kept_count: int = 0
    max_confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "detection_count": len(self.detections),
            "output_raw_min": round(self.raw_min, 6),
            "output_raw_max": round(self.raw_max, 6),
            "output_raw_p99": round(self.raw_p99, 6),
            "candidate_count": self.candidate_count,
            "kept_count": self.kept_count,
            "max_confidence": round(self.max_confidence, 6),
        }


def decode_detections(
    raw: np.ndarray,
    *,
    letterbox: LetterboxResult,
    output_contract: OutputContract,
    profile: PostprocessProfile,
    class_names: Optional[Sequence[str]] = None,
) -> DecodedDetections:
    """Decode one raw output tensor into validated source-space detections."""

    if not np.all(np.isfinite(raw)):
        raise TensorRTPerceptionError("output_nonfinite", "engine output contains NaN/Inf")

    layout_info = infer_output_layout(raw.shape, output_contract.layout)

    matrix = raw[0]
    if layout_info["layout"] == "channels_first":
        matrix = matrix.T  # -> (anchors, attributes)
    matrix = np.ascontiguousarray(matrix.astype(np.float32))

    attributes = int(layout_info["attributes"])
    if output_contract.has_objectness:
        if attributes < 6:
            raise TensorRTPerceptionError(
                "output_shape_mismatch", "objectness layout needs >= 6 attributes"
            )
        objectness = matrix[:, 4]
        class_scores = matrix[:, 5:]
        scores = objectness[:, None] * class_scores
    else:
        class_scores = matrix[:, 4:]
        scores = class_scores

    class_count = int(scores.shape[1])
    if output_contract.class_count and class_count != int(output_contract.class_count):
        raise TensorRTPerceptionError(
            "output_shape_mismatch",
            "decoded %d classes, contract declares %d" % (class_count, output_contract.class_count),
        )

    best_class = scores.argmax(axis=1)
    best_score = scores[np.arange(scores.shape[0]), best_class]
    keep_mask = best_score >= float(profile.confidence_threshold)
    candidate_count = int(np.count_nonzero(keep_mask))

    result = DecodedDetections(
        raw_min=float(np.min(raw)),
        raw_max=float(np.max(raw)),
        raw_p99=float(np.percentile(raw, 99.0)),
        candidate_count=candidate_count,
        max_confidence=float(best_score.max()) if best_score.size else 0.0,
    )
    if candidate_count == 0:
        return result

    boxes = _xywh_to_xyxy(matrix[keep_mask, :4])
    confidences = best_score[keep_mask]
    classes = best_class[keep_mask]

    kept_indices = []  # type: List[int]
    for class_id in np.unique(classes):
        selector = np.where(classes == class_id)[0]
        local = nms_numpy(boxes[selector], confidences[selector], float(profile.nms_iou_threshold))
        kept_indices.extend(int(selector[index]) for index in local)
    if not kept_indices:
        return result

    kept_indices.sort(key=lambda index: float(confidences[index]), reverse=True)
    kept_indices = kept_indices[: int(profile.max_detections)]
    result.kept_count = len(kept_indices)

    mapped = reverse_letterbox(boxes[kept_indices], letterbox)
    for position, index in enumerate(kept_indices):
        class_id = int(classes[index])
        confidence = float(confidences[index])
        x1, y1, x2, y2 = (float(value) for value in mapped[position])
        _validate_detection(
            class_id=class_id,
            confidence=confidence,
            box=(x1, y1, x2, y2),
            class_count=class_count,
            letterbox=letterbox,
        )
        label = (
            str(class_names[class_id])
            if class_names is not None and 0 <= class_id < len(class_names)
            else "class_%d" % class_id
        )
        result.detections.append(
            Detection(
                label=label,
                confidence=confidence,
                bbox=(x1, y1, x2, y2),
                class_id=class_id,
            )
        )
    if len(result.detections) > int(profile.max_detections):
        raise TensorRTPerceptionError(
            "detection_count_exceeded",
            "%d detections exceed max %d" % (len(result.detections), profile.max_detections),
        )
    return result


def _validate_detection(
    *,
    class_id: int,
    confidence: float,
    box: Tuple[float, float, float, float],
    class_count: int,
    letterbox: LetterboxResult,
) -> None:
    """Every surviving detection must satisfy the schema before it is returned."""

    if not 0 <= class_id < class_count:
        raise TensorRTPerceptionError(
            "invalid_class_id", "class id %d outside [0, %d)" % (class_id, class_count)
        )
    if not np.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise TensorRTPerceptionError(
            "confidence_out_of_range", "confidence %r outside [0, 1]" % (confidence,)
        )
    x1, y1, x2, y2 = box
    if not all(np.isfinite(value) for value in box):
        raise TensorRTPerceptionError("bbox_nonfinite", "bbox contains NaN/Inf")
    if x1 > x2 or y1 > y2:
        raise TensorRTPerceptionError("bbox_invalid", "bbox is inverted: %s" % (box,))
    if x1 < 0.0 or y1 < 0.0:
        raise TensorRTPerceptionError("bbox_out_of_bounds", "bbox has negative origin: %s" % (box,))
    if x2 > letterbox.original_width + 1e-3 or y2 > letterbox.original_height + 1e-3:
        raise TensorRTPerceptionError(
            "bbox_out_of_bounds", "bbox exceeds source bounds: %s" % (box,)
        )


def load_class_names(source: Optional[str]) -> Tuple[List[str], str]:
    """Load class names from the external source's data yaml, never from the repo."""

    if not source:
        return [], "none"
    path = Path(source)
    if not path.is_file():
        return [], "missing:%s" % source
    try:
        import yaml  # type: ignore[import-not-found]

        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return [], "unreadable:%s" % source
    names = payload.get("names") if isinstance(payload, dict) else None
    if isinstance(names, dict):
        ordered = [str(names[key]) for key in sorted(names, key=lambda item: int(item))]
        return ordered, str(path)
    if isinstance(names, list):
        return [str(item) for item in names], str(path)
    return [], "no_names_field:%s" % source


# ── Backend ─────────────────────────────────────────────────────────────────


class TensorRTPerceptionBackend:
    """PerceptionBackend implementation backed by a target-built FP16 engine.

    Satisfies the same ``detect(frame) -> (detections, inference_ms)`` protocol
    as ``DummyPerceptionBackend`` and ``YOLOv9PerceptionBackend``, so the Phase
    13B pipeline consumes it unchanged. It **never** falls back: on any contract
    violation it raises, and the caller emits SAFE_STOP.
    """

    def __init__(
        self,
        runner: Any,
        *,
        input_contract: InputContract,
        output_contract: OutputContract,
        profile: PostprocessProfile,
        class_names: Optional[Sequence[str]] = None,
        model_name: str = "yolov9-c",
    ) -> None:
        self._runner = runner
        self.input_contract = input_contract
        self.output_contract = output_contract
        self.profile = profile
        self.class_names = list(class_names or [])
        self._model_name = model_name
        self.fallback_used = False
        self.inference_count = 0
        self.failure_count = 0
        self.last_stats = {}  # type: Dict[str, Any]
        self.last_timing = {}  # type: Dict[str, Any]
        self.last_letterbox = None  # type: Optional[LetterboxResult]

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def backend_name(self) -> str:
        return "tensorrt"

    def detect(self, frame: np.ndarray) -> Tuple[List[Detection], int]:
        started = time.perf_counter_ns()
        try:
            tensor, letterbox, stats = preprocess_bgr(frame, self.input_contract)
            preprocess_ms = (time.perf_counter_ns() - started) / 1e6

            outputs, timing = self._runner.infer(tensor)
            primary_name = self.output_contract.output_names[0] if self.output_contract.output_names else None
            if primary_name not in outputs:
                primary_name = sorted(outputs)[0] if outputs else None
            if primary_name is None:
                raise TensorRTPerceptionError("output_shape_mismatch", "engine produced no output")

            postprocess_start = time.perf_counter_ns()
            decoded = decode_detections(
                outputs[primary_name],
                letterbox=letterbox,
                output_contract=self.output_contract,
                profile=self.profile,
                class_names=self.class_names,
            )
            postprocess_ms = (time.perf_counter_ns() - postprocess_start) / 1e6
        except TensorRTPerceptionError:
            self.failure_count += 1
            raise
        except Exception as exc:
            self.failure_count += 1
            raise TensorRTPerceptionError("engine_execute_failed", repr(exc)[:200])

        total_ms = (time.perf_counter_ns() - started) / 1e6
        self.inference_count += 1
        self.last_letterbox = letterbox
        self.last_stats = dict(stats)
        self.last_stats.update(decoded.to_dict())
        self.last_timing = dict(timing.to_dict())
        self.last_timing.update(
            {
                "preprocess_ms": round(preprocess_ms, 4),
                "postprocess_ms": round(postprocess_ms, 4),
                "frame_to_perception_ms": round(total_ms, 4),
            }
        )
        return decoded.detections, int(round(total_ms))

    def metadata(self) -> Dict[str, Any]:
        payload = {
            "backend": "tensorrt",
            "model_name": self._model_name,
            "fallback_used": False,
            "precision": "fp16",
            "input_contract": self.input_contract.to_dict(),
            "output_contract": self.output_contract.to_dict(),
            "postprocess_profile": self.profile.to_dict(),
            "class_count": len(self.class_names),
            "tensorrt_inference_count": self.inference_count,
            "tensorrt_inference_failure_count": self.failure_count,
        }
        if hasattr(self._runner, "metrics"):
            payload.update(self._runner.metrics())
        return payload

    def close(self) -> None:
        if hasattr(self._runner, "close"):
            self._runner.close()

"""
邊緣感知模組 — 執行物件偵測、目標追蹤、車道狀態與自由空間估計。

支援 Dummy, YOLO, YOLOv9, RT-DETR backends，並具有 graceful fallback 機制。
"""

from __future__ import annotations

import inspect
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from .config import AgentConfig

logger = logging.getLogger(__name__)

# ── 延遲匯入 optional detection backends ───────────────────────
try:
    from ultralytics import YOLO, RTDETR  # type: ignore[import-untyped]
    _HAS_ULTRALYTICS = True
except ImportError:
    _HAS_ULTRALYTICS = False
    logger.info("ultralytics 未安裝 — YOLO/RT-DETR 將不可用")

YOLOV9_REQUIRED_SOURCE_ENTRIES = ("detect.py", "detect_dual.py", "models", "utils")


# ════════════════════════════════════════════════════════════════
# 資料結構
# ════════════════════════════════════════════════════════════════

@dataclass
class Detection:
    """單一物件偵測結果（亦用於追蹤結果）。"""
    label: str
    confidence: float
    bbox: tuple[float, float, float, float]    # (x1, y1, x2, y2)
    class_id: int = 0
    track_id: int | None = None
    distance_estimate_m: float | None = None
    risk_level: str = "low"                    # low, medium, high, critical
    
    # 追蹤特定屬性
    status: str = "active"                     # active, tentative, lost
    age_frames: int = 0
    velocity_mps: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "confidence": self.confidence,
            "bbox": list(self.bbox),
            "class_id": self.class_id,
            "track_id": self.track_id,
            "distance_estimate_m": self.distance_estimate_m,
            "risk_level": self.risk_level,
            "status": self.status,
            "age_frames": self.age_frames,
            "velocity_mps": self.velocity_mps,
        }


@dataclass
class PerceptionResult:
    """
    完整的邊緣感知結果。
    """
    frame_id: int = 0
    timestamp: float = field(default_factory=time.time)
    detections: list[Detection] = field(default_factory=list)
    tracks: list[Detection] = field(default_factory=list)
    lane_state: str = "unknown"                # "clear" | "occupied" | "unknown"
    free_space: dict[str, Any] = field(default_factory=dict)
    raw_confidence: float = 0.0                # 整體感知信心（0~1）
    inference_ms: int = 0                      # 推理耗時
    backend: str = "dummy"                     # dummy | yolo | yolov9 | rtdetr
    model_name: str = "dummy"
    fallback_used: bool = False                # 是否觸發了 fallback
    backend_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class YOLOv9SourceStatus:
    """YOLOv9 官方 source-repo 外部合約檢查結果。"""

    source_root_env: str
    weights_env: str
    source_root_value: str | None
    weights_value: str | None
    source_root_path: str | None
    weights_path: str | None
    source_root_configured: bool
    weights_configured: bool
    source_root_ready: bool
    weights_ready: bool
    expected_source_files_ready: bool
    missing_source_entries: list[str]
    configured: bool
    blocked_reason: str | None

    @property
    def source_adapter_ready(self) -> bool:
        return self.source_root_ready and self.weights_ready and self.expected_source_files_ready

    def to_metadata(self) -> dict[str, Any]:
        return {
            "yolov9_source_root_env": self.source_root_env,
            "yolov9_weights_env": self.weights_env,
            "yolov9_source_root": self.source_root_path or "<missing>",
            "yolov9_weights": self.weights_path or "<missing>",
            "yolov9_source_root_configured": self.source_root_configured,
            "yolov9_weights_configured": self.weights_configured,
            "yolov9_source_ready": self.source_root_ready and self.expected_source_files_ready,
            "yolov9_source_root_ready": self.source_root_ready,
            "yolov9_weights_ready": self.weights_ready,
            "yolov9_expected_source_files_ready": self.expected_source_files_ready,
            "yolov9_missing_source_entries": self.missing_source_entries,
            "yolov9_source_adapter_ready": self.source_adapter_ready,
            "blocked_reason": self.blocked_reason,
        }


def inspect_yolov9_source_contract(
    *,
    source_root_env: str = "YOLOV9_ROOT",
    weights_env: str = "YOLOV9_WEIGHTS",
) -> YOLOv9SourceStatus:
    """檢查 operator 提供的 YOLOv9 source root 與 weights 是否符合外部合約。"""

    source_root_value = os.getenv(source_root_env)
    weights_value = os.getenv(weights_env)
    source_root_configured = bool(source_root_value)
    weights_configured = bool(weights_value)
    source_root = Path(source_root_value).expanduser() if source_root_value else None
    weights = Path(weights_value).expanduser() if weights_value else None
    source_root_ready = bool(source_root and source_root.exists() and source_root.is_dir())
    weights_ready = bool(weights and weights.exists() and weights.is_file())

    missing_source_entries: list[str] = []
    if source_root_ready and source_root is not None:
        for entry in YOLOV9_REQUIRED_SOURCE_ENTRIES:
            if not (source_root / entry).exists():
                missing_source_entries.append(entry)
    elif source_root_configured:
        missing_source_entries = list(YOLOV9_REQUIRED_SOURCE_ENTRIES)

    expected_source_files_ready = source_root_ready and not missing_source_entries
    configured = source_root_configured or weights_configured
    blocked_parts: list[str] = []
    if not source_root_configured:
        blocked_parts.append(f"{source_root_env} is not set")
    elif not source_root_ready:
        blocked_parts.append(f"{source_root_env} path is missing or not a directory")
    if source_root_ready and missing_source_entries:
        blocked_parts.append("missing YOLOv9 source entries: " + ", ".join(missing_source_entries))
    if not weights_configured:
        blocked_parts.append(f"{weights_env} is not set")
    elif not weights_ready:
        blocked_parts.append(f"{weights_env} path is missing or not a file")

    return YOLOv9SourceStatus(
        source_root_env=source_root_env,
        weights_env=weights_env,
        source_root_value=source_root_value,
        weights_value=weights_value,
        source_root_path=str(source_root.resolve()) if source_root and source_root.exists() else (str(source_root) if source_root else None),
        weights_path=str(weights.resolve()) if weights and weights.exists() else (str(weights) if weights else None),
        source_root_configured=source_root_configured,
        weights_configured=weights_configured,
        source_root_ready=source_root_ready,
        weights_ready=weights_ready,
        expected_source_files_ready=expected_source_files_ready,
        missing_source_entries=missing_source_entries,
        configured=configured,
        blocked_reason="; ".join(blocked_parts) if blocked_parts else None,
    )


# ════════════════════════════════════════════════════════════════
# Perception Backend 抽象
# ════════════════════════════════════════════════════════════════

class PerceptionBackend(Protocol):
    def detect(self, frame: np.ndarray) -> tuple[list[Detection], int]:
        ...
    @property
    def model_name(self) -> str:
        ...


class DummyPerceptionBackend:
    def __init__(self) -> None:
        self._rng = np.random.default_rng(42)
        self._model_name = "dummy-rng"

    @property
    def model_name(self) -> str:
        return self._model_name

    def detect(self, frame: np.ndarray) -> tuple[list[Detection], int]:
        start = time.monotonic()
        h, w = frame.shape[:2]
        n = int(self._rng.integers(0, 4))
        labels = ["car", "pedestrian", "truck", "bicycle", "traffic_light"]
        detections: list[Detection] = []
        for _ in range(n):
            x1 = float(self._rng.integers(0, w // 2))
            y1 = float(self._rng.integers(0, h // 2))
            x2 = float(self._rng.integers(int(x1) + 20, w))
            y2 = float(self._rng.integers(int(y1) + 20, h))
            detections.append(Detection(
                label=str(self._rng.choice(labels)),
                confidence=float(self._rng.uniform(0.2, 0.95)),
                bbox=(x1, y1, x2, y2),
                class_id=0,
            ))
        time.sleep(0.01) # simulate slight delay
        inf_ms = int((time.monotonic() - start) * 1000)
        return detections, inf_ms


class YOLOPerceptionBackend:
    def __init__(self, model_name: str, conf_threshold: float):
        if not _HAS_ULTRALYTICS:
            raise RuntimeError("ultralytics package is required for YOLO backend")
        self._model_name = model_name
        self._conf_threshold = conf_threshold
        self._model = YOLO(self._model_name)

    @property
    def model_name(self) -> str:
        return self._model_name

    def detect(self, frame: np.ndarray) -> tuple[list[Detection], int]:
        start = time.monotonic()
        results = self._model(frame, verbose=False)
        detections: list[Detection] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for i in range(len(boxes)):
                xyxy = boxes.xyxy[i].cpu().numpy()
                conf = float(boxes.conf[i].cpu().numpy())
                cls_id = int(boxes.cls[i].cpu().numpy())
                label = result.names.get(cls_id, f"class_{cls_id}")
                if conf >= self._conf_threshold:
                    detections.append(Detection(
                        label=label,
                        confidence=conf,
                        bbox=(float(xyxy[0]), float(xyxy[1]), float(xyxy[2]), float(xyxy[3])),
                        class_id=cls_id
                    ))
        inf_ms = int((time.monotonic() - start) * 1000)
        return detections, inf_ms


def _detections_from_yolo_like_results(raw_results: Any, conf_threshold: float) -> list[Detection]:
    detections: list[Detection] = []
    if not isinstance(raw_results, (list, tuple)):
        raw_results = [raw_results]
    for result in raw_results:
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            continue
        names = getattr(result, "names", {})
        for i in range(len(boxes)):
            xyxy = boxes.xyxy[i].cpu().numpy()
            conf = float(boxes.conf[i].cpu().numpy())
            cls_id = int(boxes.cls[i].cpu().numpy())
            label = names.get(cls_id, f"class_{cls_id}") if isinstance(names, dict) else f"class_{cls_id}"
            if conf >= conf_threshold:
                detections.append(Detection(
                    label=label,
                    confidence=conf,
                    bbox=(float(xyxy[0]), float(xyxy[1]), float(xyxy[2]), float(xyxy[3])),
                    class_id=cls_id,
                ))
    return detections


class YOLOv9PerceptionBackend:
    """YOLOv9 官方 source-repo backend adapter.

    此 adapter 不 vendor YOLOv9 source，也不要求本 repo 安裝假的
    `yolov9` pip package。operator 必須透過 YOLOV9_ROOT / YOLOV9_WEIGHTS
    指向外部官方 source repository 與選定 weights。
    """

    def __init__(
        self,
        model_name: str,
        conf_threshold: float,
        *,
        source_status: YOLOv9SourceStatus,
        img_size: int = 640,
        iou_threshold: float = 0.45,
        device: str = "auto",
    ):
        if not source_status.configured:
            raise RuntimeError("YOLOv9 external source is not configured: set YOLOV9_ROOT and YOLOV9_WEIGHTS")
        if not source_status.source_adapter_ready:
            raise RuntimeError(f"YOLOv9 external source is blocked: {source_status.blocked_reason}")
        self._source_status = source_status
        self._model_name = Path(source_status.weights_path or model_name).name
        self._conf_threshold = conf_threshold
        self._img_size = img_size
        self._iou_threshold = iou_threshold
        self._device_hint = device
        self._last_inference_timing: dict[str, Any] = {}
        self._model_loaded_once = False
        self._model, self._device = self._build_model(source_status)
        self._model_loaded_once = True

    @staticmethod
    def _add_source_root_to_path(source_root: str) -> None:
        if source_root not in sys.path:
            sys.path.insert(0, source_root)

    @staticmethod
    def _patch_torch_load_for_trusted_yolov9_checkpoint(torch_module: Any) -> Any:
        """相容 PyTorch 2.6+ 的安全載入預設，僅用於 operator 指定的 YOLOv9 checkpoint。"""

        original_load = torch_module.load
        try:
            accepts_weights_only = "weights_only" in inspect.signature(original_load).parameters
        except (TypeError, ValueError):
            accepts_weights_only = False

        if not accepts_weights_only:
            return original_load

        def trusted_load(*args: Any, **kwargs: Any) -> Any:
            kwargs.setdefault("weights_only", False)
            return original_load(*args, **kwargs)

        torch_module.load = trusted_load
        return original_load

    def _build_model(self, source_status: YOLOv9SourceStatus) -> tuple[Any, Any]:
        source_root = source_status.source_root_path
        weights = source_status.weights_path
        if source_root is None or weights is None:
            raise RuntimeError("YOLOv9 source root and weights must be resolved before model loading")
        self._add_source_root_to_path(source_root)
        try:
            import torch  # type: ignore[import-untyped]
            from models.common import DetectMultiBackend  # type: ignore[import-not-found]
            from utils.torch_utils import select_device  # type: ignore[import-not-found]
        except Exception as exc:
            raise RuntimeError(f"YOLOv9 source import failed: {exc}") from exc

        device_arg = "" if self._device_hint == "auto" else self._device_hint
        device_obj = select_device(device_arg)
        original_torch_load = self._patch_torch_load_for_trusted_yolov9_checkpoint(torch)
        try:
            model = DetectMultiBackend(weights, device=device_obj, fp16=False)
            if hasattr(model, "eval"):
                model.eval()
            else:
                getattr(model, "model", model).eval()
            # 觸發極輕量 smoke，確認 weights 可被 target runtime 載入。
            stride = int(getattr(model, "stride", 32) or 32)
            smoke_size = max(stride, int(self._img_size))
            dummy = torch.zeros(1, 3, smoke_size, smoke_size, device=device_obj)
            with torch.no_grad():
                if callable(model):
                    _ = model(dummy)
                elif hasattr(model, "model") and callable(model.model):
                    _ = model.model(dummy)
                else:
                    raise RuntimeError("YOLOv9 DetectMultiBackend has no callable inference path")
        except Exception as exc:
            raise RuntimeError(f"YOLOv9 weights/model smoke failed: {exc}") from exc
        finally:
            torch.load = original_torch_load
        return model, device_obj

    @staticmethod
    def _sync_device_if_needed(torch_module: Any, device: Any) -> None:
        """在 CUDA 類裝置上同步以取得較準確的分段耗時；CPU 會直接略過。"""
        try:
            device_text = str(device)
            if "cuda" in device_text and getattr(torch_module, "cuda", None) is not None:
                torch_module.cuda.synchronize()
        except Exception:
            return

    @property
    def model_name(self) -> str:
        return self._model_name

    def detect(self, frame: np.ndarray) -> tuple[list[Detection], int]:
        start = time.monotonic()
        try:
            import torch  # type: ignore[import-untyped]
            from utils.augmentations import letterbox  # type: ignore[import-not-found]
            from utils.general import non_max_suppression, scale_boxes  # type: ignore[import-not-found]
        except Exception as exc:
            raise RuntimeError(f"YOLOv9 inference dependencies unavailable: {exc}") from exc

        # 使用 YOLOv9 官方 letterbox 流程，避免非方形影像在特徵圖 concat 時尺寸不一致。
        stride = int(getattr(self._model, "stride", 32) or 32)
        preprocess_start = time.monotonic()
        image = letterbox(frame, new_shape=self._img_size, stride=stride, auto=True)[0]
        letterbox_shape = tuple(int(value) for value in image.shape[:2])
        image = image[:, :, ::-1].transpose(2, 0, 1)
        image = np.ascontiguousarray(image)
        tensor = torch.from_numpy(image).to(self._device).float() / 255.0
        if tensor.ndimension() == 3:
            tensor = tensor.unsqueeze(0)
        self._sync_device_if_needed(torch, self._device)
        preprocess_ms = (time.monotonic() - preprocess_start) * 1000.0

        forward_start = time.monotonic()
        with torch.no_grad():
            raw = self._model(tensor) if callable(self._model) else self._model.model(tensor)
        self._sync_device_if_needed(torch, self._device)
        model_forward_ms = (time.monotonic() - forward_start) * 1000.0

        prediction = raw[0] if isinstance(raw, (list, tuple)) else raw
        nms_start = time.monotonic()
        nms_results = non_max_suppression(
            prediction,
            self._conf_threshold,
            self._iou_threshold,
            classes=None,
            agnostic=False,
        )
        self._sync_device_if_needed(torch, self._device)
        nms_ms = (time.monotonic() - nms_start) * 1000.0

        postprocess_start = time.monotonic()
        detections: list[Detection] = []
        names = getattr(self._model, "names", {})
        if nms_results and len(nms_results[0]):
            det_batch = nms_results[0]
            det_batch[:, :4] = scale_boxes(tensor.shape[2:], det_batch[:, :4], frame.shape).round()
            for det in det_batch:
                x1, y1, x2, y2, conf, cls_id = det.tolist()
                class_id = int(cls_id)
                label = names.get(class_id, f"class_{class_id}") if isinstance(names, dict) else f"class_{class_id}"
                detections.append(
                    Detection(
                        label=label,
                        confidence=float(conf),
                        bbox=(float(x1), float(y1), float(x2), float(y2)),
                        class_id=class_id,
                    )
                )
        postprocess_ms = (time.monotonic() - postprocess_start) * 1000.0
        inf_ms = int((time.monotonic() - start) * 1000)
        self._last_inference_timing = {
            "yolov9_preprocess_ms": round(preprocess_ms, 3),
            "yolov9_model_forward_ms": round(model_forward_ms, 3),
            "yolov9_nms_ms": round(nms_ms, 3),
            "yolov9_postprocess_ms": round(postprocess_ms, 3),
            "yolov9_total_inference_ms": float(inf_ms),
            "input_frame_shape": [int(value) for value in frame.shape],
            "letterbox_shape": [int(value) for value in letterbox_shape],
            "device": str(self._device),
            "model_loaded_once": self._model_loaded_once,
        }
        return detections, inf_ms

    @property
    def source_status(self) -> YOLOv9SourceStatus:
        return self._source_status

    @property
    def last_inference_timing(self) -> dict[str, Any]:
        """回傳最近一次 YOLOv9 inference 分段耗時，供 runtime diagnosis 使用。"""
        return dict(self._last_inference_timing)


class RTDETRPerceptionBackend:
    def __init__(self, model_name: str, conf_threshold: float):
        if not _HAS_ULTRALYTICS:
            raise RuntimeError("ultralytics package is required for RT-DETR backend")
        self._model_name = model_name
        self._conf_threshold = conf_threshold
        self._model = RTDETR(self._model_name)

    @property
    def model_name(self) -> str:
        return self._model_name

    def detect(self, frame: np.ndarray) -> tuple[list[Detection], int]:
        start = time.monotonic()
        results = self._model(frame, verbose=False)
        detections: list[Detection] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for i in range(len(boxes)):
                xyxy = boxes.xyxy[i].cpu().numpy()
                conf = float(boxes.conf[i].cpu().numpy())
                cls_id = int(boxes.cls[i].cpu().numpy())
                label = result.names.get(cls_id, f"class_{cls_id}")
                if conf >= self._conf_threshold:
                    detections.append(Detection(
                        label=label,
                        confidence=conf,
                        bbox=(float(xyxy[0]), float(xyxy[1]), float(xyxy[2]), float(xyxy[3])),
                        class_id=cls_id
                    ))
        inf_ms = int((time.monotonic() - start) * 1000)
        return detections, inf_ms


# ════════════════════════════════════════════════════════════════
# ByteTrack 風格簡易追蹤器 stub
# ════════════════════════════════════════════════════════════════

class _SimpleTracker:
    def __init__(self, iou_threshold: float = 0.3, max_age: int = 30) -> None:
        self._iou_threshold = iou_threshold
        self._max_age = max_age
        self._next_id: int = 1
        self._tracks: list[dict[str, Any]] = []
        self._id_switch_count: int = 0

    @property
    def id_switch_count(self) -> int:
        return self._id_switch_count

    def reset_id_switch_count(self) -> None:
        self._id_switch_count = 0

    def update(self, detections: list[Detection], dt: float = 0.1) -> list[Detection]:
        tracked: list[Detection] = []
        used_track_indices: set[int] = set()

        for det in detections:
            best_iou = 0.0
            best_idx = -1
            for i, trk in enumerate(self._tracks):
                if i in used_track_indices:
                    continue
                iou = self._compute_iou(det.bbox, trk["bbox"])
                if iou > best_iou:
                    best_iou = iou
                    best_idx = i

            if best_iou >= self._iou_threshold and best_idx >= 0:
                track = self._tracks[best_idx]
                
                # estimate velocity
                old_cx = (track["bbox"][0] + track["bbox"][2]) / 2.0
                new_cx = (det.bbox[0] + det.bbox[2]) / 2.0
                vel = abs(new_cx - old_cx) / (dt + 1e-6) # naive pixel velocity mapped to mps stub
                track["velocity_mps"] = vel * 0.01 
                
                track["bbox"] = det.bbox
                track["age"] = 0
                track["age_frames"] += 1
                track["label"] = det.label
                track["status"] = "active" if track["age_frames"] > 3 else "tentative"
                
                used_track_indices.add(best_idx)
                
                det_copy = Detection(**det.__dict__)
                det_copy.track_id = track["id"]
                det_copy.status = track["status"]
                det_copy.age_frames = track["age_frames"]
                det_copy.velocity_mps = track["velocity_mps"]
                tracked.append(det_copy)
            else:
                new_id = self._next_id
                self._next_id += 1
                self._tracks.append({
                    "id": new_id,
                    "bbox": det.bbox,
                    "age": 0,
                    "age_frames": 1,
                    "label": det.label,
                    "status": "tentative",
                    "velocity_mps": 0.0,
                })
                
                det_copy = Detection(**det.__dict__)
                det_copy.track_id = new_id
                det_copy.status = "tentative"
                det_copy.age_frames = 1
                det_copy.velocity_mps = 0.0
                tracked.append(det_copy)

        survivors: list[dict[str, Any]] = []
        for i, trk in enumerate(self._tracks):
            if i not in used_track_indices:
                trk["age"] += 1
                trk["status"] = "lost"
                if trk["age"] >= self._max_age:
                    self._id_switch_count += 1
                    continue
                # Add lost track to output
                lost_det = Detection(
                    label=trk["label"],
                    confidence=0.0,
                    bbox=trk["bbox"],
                    track_id=trk["id"],
                    status="lost",
                    age_frames=trk["age_frames"],
                    velocity_mps=trk["velocity_mps"]
                )
                tracked.append(lost_det)
            survivors.append(trk)
        self._tracks = survivors

        return tracked

    @staticmethod
    def _compute_iou(box_a: tuple[float, float, float, float], box_b: tuple[float, float, float, float]) -> float:
        x1 = max(box_a[0], box_b[0])
        y1 = max(box_a[1], box_b[1])
        x2 = min(box_a[2], box_b[2])
        y2 = min(box_a[3], box_b[3])
        inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        area_a = max(0.0, box_a[2] - box_a[0]) * max(0.0, box_a[3] - box_a[1])
        area_b = max(0.0, box_b[2] - box_b[0]) * max(0.0, box_b[3] - box_b[1])
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0.0


# ════════════════════════════════════════════════════════════════
# 邊緣感知主類別
# ════════════════════════════════════════════════════════════════

class EdgePerception:
    def __init__(self, config: AgentConfig | None = None) -> None:
        cfg = config or AgentConfig.load()
        
        from .supervision_adapter import HAS_SUPERVISION
        self._has_supervision = HAS_SUPERVISION
        self._supervision_pipeline = None
        
        self._tracker = _SimpleTracker()
        
        backend_type = cfg.perception.backend.lower()
        model_name = cfg.perception.model_name
        conf = (
            cfg.perception.yolov9_confidence_threshold
            if backend_type == "yolov9"
            else cfg.perception.confidence_threshold
        )
        
        self._backend: PerceptionBackend
        self._fallback_used = False
        self._fallback_reason: str | None = None
        self._requested_backend = backend_type
        self._backend_metadata: dict[str, Any] = {}
        
        try:
            if backend_type == "yolo":
                self._backend = YOLOPerceptionBackend(model_name, conf)
            elif backend_type == "yolov9":
                source_status = inspect_yolov9_source_contract(
                    source_root_env=cfg.perception.yolov9_source_root_env,
                    weights_env=cfg.perception.yolov9_weights_env,
                )
                self._backend_metadata = source_status.to_metadata()
                self._backend = YOLOv9PerceptionBackend(
                    model_name,
                    conf,
                    source_status=source_status,
                    img_size=cfg.perception.yolov9_default_img_size,
                    iou_threshold=cfg.perception.yolov9_iou_threshold,
                    device=cfg.perception.yolov9_device,
                )
            elif backend_type == "rtdetr":
                self._backend = RTDETRPerceptionBackend(model_name, conf)
            else:
                self._backend = DummyPerceptionBackend()
        except Exception as e:
            logger.error("無法初始化 PerceptionBackend '%s': %s", backend_type, e)
            logger.info("Graceful fallback to DummyPerceptionBackend")
            self._fallback_reason = str(e)
            if backend_type == "yolov9":
                self._backend_metadata.setdefault("blocked_reason", str(e))
            self._backend = DummyPerceptionBackend()
            self._fallback_used = True
            
        logger.info("EdgePerception 初始化完成: backend=%s, model=%s", 
                    self._backend.__class__.__name__, self._backend.model_name)

    def process(self, frame: np.ndarray, frame_id: int = 0) -> PerceptionResult:
        # 1. 執行偵測
        detections, inf_ms = self._backend.detect(frame)
        h, w = frame.shape[:2]
        
        if self._has_supervision:
            if self._supervision_pipeline is None:
                from .supervision_adapter import SupervisionAnalyticsPipeline
                self._supervision_pipeline = SupervisionAnalyticsPipeline(frame_resolution=(w, h))
                
            bboxes = [d.bbox for d in detections]
            confs = [d.confidence for d in detections]
            cids = [d.class_id for d in detections]
            labels = [d.label for d in detections]
            
            sv_results = self._supervision_pipeline.process_raw(bboxes, confs, cids, labels)
            
            tracks = []
            for r in sv_results:
                det = Detection(
                    label=r["label"],
                    confidence=r["confidence"],
                    bbox=r["bbox"],
                    class_id=r["class_id"],
                    track_id=r["track_id"]
                )
                bbox_h = max(1.0, det.bbox[3] - det.bbox[1])
                dist = 2.0 / max(0.05, bbox_h / float(h))
                det.distance_estimate_m = round(dist, 1)
                
                if dist < 5.0:
                    det.risk_level = "critical"
                elif r["risk_level"] == "high":
                    det.risk_level = "high"
                elif dist < 20.0:
                    det.risk_level = "medium"
                else:
                    det.risk_level = "low"
                    
                tracks.append(det)
            
            detections = tracks
        else:
            # 2. 應用工程規則估算距離與危險等級 (Fallback)
            self._apply_engineering_rules(detections, h)
            # 3. 目標追蹤
            tracks = self._tracker.update(detections)
        
        # 4. 車道狀態與自由空間
        lane_state = self._estimate_lane_state(detections)
        free_space = self._estimate_free_space(detections, frame.shape)
        raw_confidence = self._compute_confidence(detections)
        backend_metadata = dict(self._backend_metadata)
        last_timing = getattr(self._backend, "last_inference_timing", None)
        if callable(last_timing):
            timing_payload = last_timing()
            if timing_payload:
                backend_metadata["yolov9_timing"] = timing_payload

        result = PerceptionResult(
            frame_id=frame_id,
            timestamp=time.time(),
            detections=detections,
            tracks=tracks,
            lane_state=lane_state,
            free_space=free_space,
            raw_confidence=raw_confidence,
            inference_ms=inf_ms,
            backend=self._backend.__class__.__name__,
            model_name=self._backend.model_name,
            fallback_used=self._fallback_used,
            backend_metadata=backend_metadata,
        )
        return result

    @property
    def fallback_reason(self) -> str | None:
        return self._fallback_reason

    @property
    def requested_backend(self) -> str:
        return self._requested_backend

    @property
    def backend_metadata(self) -> dict[str, Any]:
        return dict(self._backend_metadata)

    @property
    def tracker_id_switch_count(self) -> int:
        return self._tracker.id_switch_count

    def reset_tracker_stats(self) -> None:
        self._tracker.reset_id_switch_count()

    def _apply_engineering_rules(self, detections: list[Detection], frame_height: int) -> None:
        blocking_labels = {"car", "truck", "bus", "pedestrian", "person", "bicycle"}
        for det in detections:
            bbox_h = max(1.0, det.bbox[3] - det.bbox[1])
            height_ratio = bbox_h / float(frame_height)
            
            # 簡單距離估算 (假設目標佔畫面比例越大越近)
            dist = 2.0 / max(0.05, height_ratio)
            det.distance_estimate_m = round(dist, 1)
            
            if det.label in blocking_labels:
                if dist < 5.0:
                    det.risk_level = "critical"
                elif dist < 10.0:
                    det.risk_level = "high"
                elif dist < 20.0:
                    det.risk_level = "medium"
                else:
                    det.risk_level = "low"
            else:
                det.risk_level = "low"

    def _estimate_lane_state(self, detections: list[Detection]) -> str:
        for det in detections:
            if det.risk_level in ("high", "critical"):
                return "occupied"
        return "clear"

    def _estimate_free_space(self, detections: list[Detection], frame_shape: tuple[int, ...]) -> dict[str, Any]:
        h, w = frame_shape[:2]
        third = w / 3.0
        regions = {"left": True, "center": True, "right": True}
        for det in detections:
            cx = (det.bbox[0] + det.bbox[2]) / 2.0
            # 只有當距離較近時才視為佔用
            dist = det.distance_estimate_m or 100.0
            if dist < 20.0:
                if cx < third:
                    regions["left"] = False
                elif cx < 2 * third:
                    regions["center"] = False
                else:
                    regions["right"] = False
        return regions

    @staticmethod
    def _compute_confidence(detections: list[Detection]) -> float:
        if not detections:
            return 0.5
        return float(np.mean([d.confidence for d in detections]))


# ════════════════════════════════════════════════════════════════
# CLI Self-Test
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    
    parser = argparse.ArgumentParser(description="Edge Perception CLI Test")
    parser.add_argument("--test", type=str, choices=["dummy", "yolo", "yolov9", "rtdetr"], required=True)
    args = parser.parse_args()
    
    logger.info("開始測試 Perception Backend: %s", args.test)
    
    # 建立造假影像 (720p)
    dummy_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    
    from .config import PerceptionConfig
    
    cfg = AgentConfig()
    p_model = "dummy"
    if args.test == "yolo":
        p_model = "yolov8n.pt"
    elif args.test == "yolov9":
        p_model = os.getenv("YOLOV9_WEIGHTS", "yolov9")
    elif args.test == "rtdetr":
        p_model = "rtdetr-l.pt"
    
    # We must replace the perception field since it's frozen
    cfg.perception = PerceptionConfig(backend=args.test, model_name=p_model, confidence_threshold=0.5)
        
    try:
        perception = EdgePerception(cfg)
        result = perception.process(dummy_frame)
        
        logger.info("感知結果:")
        logger.info(f" - Backend: {result.backend}")
        logger.info(f" - Model: {result.model_name}")
        logger.info(f" - Inference time: {result.inference_ms} ms")
        logger.info(f" - Fallback used: {result.fallback_used}")
        logger.info(f" - Detections: {len(result.detections)}")
        for i, d in enumerate(result.detections):
            logger.info(f"   [{i}] {d.label} (conf={d.confidence:.2f}, dist={d.distance_estimate_m}m, risk={d.risk_level})")
            
        logger.info(f" - Tracks: {len(result.tracks)}")
        for i, t in enumerate(result.tracks):
            logger.info(f"   [{i}] id={t.track_id} status={t.status} age={t.age_frames}")

        if args.test == "yolov9":
            meta = perception.backend_metadata
            blocked_reason = perception.fallback_reason or meta.get("blocked_reason")
            no_fallback_verified = not result.fallback_used
            print("backend=yolov9")
            print(f"runtime_backend={result.backend}")
            print(f"yolov9_source_root={meta.get('yolov9_source_root', '<missing>')}")
            print(f"yolov9_weights={meta.get('yolov9_weights', '<missing>')}")
            print(f"yolov9_source_ready={str(bool(meta.get('yolov9_source_ready'))).lower()}")
            print(f"yolov9_source_root_ready={str(bool(meta.get('yolov9_source_root_ready'))).lower()}")
            print(f"yolov9_weights_ready={str(bool(meta.get('yolov9_weights_ready'))).lower()}")
            print(f"yolov9_expected_source_files_ready={str(bool(meta.get('yolov9_expected_source_files_ready'))).lower()}")
            print(f"edge_yolov9_command_passed=true")
            print(f"edge_yolov9_fallback_used={str(result.fallback_used).lower()}")
            print(f"edge_yolov9_no_fallback_verified={str(no_fallback_verified).lower()}")
            print(f"blocked_reason={blocked_reason or 'null'}")
            
        logger.info("[PASS] Edge Perception 測試成功！")
    except Exception as e:
        logger.error("[FAIL] Edge Perception 測試失敗: %s", e)
        raise

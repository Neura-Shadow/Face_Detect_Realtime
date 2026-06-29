"""
邊緣感知模組 — 執行物件偵測、目標追蹤、車道狀態與自由空間估計。

支援 Dummy, YOLO, YOLOv9, RT-DETR backends，並具有 graceful fallback 機制。
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
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

try:
    import yolov9 as _YOLOV9_MODULE  # type: ignore[import-untyped]
    _HAS_YOLOV9 = True
except ImportError:
    _YOLOV9_MODULE = None
    _HAS_YOLOV9 = False
    logger.info("YOLOv9 optional dependency 未安裝 — YOLOv9 backend 將不可用")


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
    """YOLOv9 optional backend adapter.

    此 adapter 先建立明確的 EdgePerception backend 入口；實際 YOLOv9
    package/repository 來源仍由 operator 在 Phase 12C-YOLOv9-U 解鎖。
    目前若缺少 dependency 或缺少相容推理 API，會讓 EdgePerception
    走既有 graceful fallback，不會讓主流程崩潰。
    """

    def __init__(self, model_name: str, conf_threshold: float):
        if not _HAS_YOLOV9 or _YOLOV9_MODULE is None:
            raise RuntimeError("YOLOv9 optional dependency is required for YOLOv9 backend")
        self._model_name = model_name
        self._conf_threshold = conf_threshold
        self._model = self._build_model(_YOLOV9_MODULE, model_name)

    @staticmethod
    def _build_model(module: Any, model_name: str) -> Any:
        for attr in ("YOLOv9", "YOLO"):
            factory = getattr(module, attr, None)
            if callable(factory):
                return factory(model_name)
        raise RuntimeError("YOLOv9 dependency is present but no supported YOLOv9/YOLO factory was found")

    @property
    def model_name(self) -> str:
        return self._model_name

    def detect(self, frame: np.ndarray) -> tuple[list[Detection], int]:
        start = time.monotonic()
        if callable(self._model):
            raw_results = self._model(frame)
        elif hasattr(self._model, "predict"):
            raw_results = self._model.predict(frame)
        else:
            raise RuntimeError("YOLOv9 model object has no callable or predict interface")
        detections = _detections_from_yolo_like_results(raw_results, self._conf_threshold)
        inf_ms = int((time.monotonic() - start) * 1000)
        return detections, inf_ms


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
        conf = cfg.perception.confidence_threshold
        
        self._backend: PerceptionBackend
        self._fallback_used = False
        
        try:
            if backend_type == "yolo":
                self._backend = YOLOPerceptionBackend(model_name, conf)
            elif backend_type == "yolov9":
                self._backend = YOLOv9PerceptionBackend(model_name, conf)
            elif backend_type == "rtdetr":
                self._backend = RTDETRPerceptionBackend(model_name, conf)
            else:
                self._backend = DummyPerceptionBackend()
        except Exception as e:
            logger.error("無法初始化 PerceptionBackend '%s': %s", backend_type, e)
            logger.info("Graceful fallback to DummyPerceptionBackend")
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
        )
        return result

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
        p_model = "yolov9"
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
            
        logger.info("[PASS] Edge Perception 測試成功！")
    except Exception as e:
        logger.error("[FAIL] Edge Perception 測試失敗: %s", e)
        raise

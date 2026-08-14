import logging
import numpy as np
from typing import Any, Tuple, List, Dict

logger = logging.getLogger(__name__)

try:
    import supervision as sv
    HAS_SUPERVISION = True
except ImportError:
    HAS_SUPERVISION = False

class SupervisionAnalyticsPipeline:
    """
    Optional perception utility layer using roboflow/supervision.
    Handles tracking (ByteTrack) and zone-aware risk assessment.
    """
    def __init__(self, frame_resolution: Tuple[int, int] = (640, 480)):
        if not HAS_SUPERVISION:
            raise RuntimeError("supervision package is required to use this pipeline")
        
        self.tracker = sv.ByteTrack()
        
        # 定義高風險區 (High Risk Zone): 畫面中下方梯形區域 (模擬車輛前方路徑)
        w, h = frame_resolution
        polygon = np.array([
            [int(w * 0.2), int(h * 0.5)],
            [int(w * 0.8), int(h * 0.5)],
            [int(w * 0.9), h],
            [int(w * 0.1), h]
        ])
        self.zone = sv.PolygonZone(polygon=polygon)
        logger.info(f"Initialized SupervisionAnalyticsPipeline with zone {polygon.tolist()}")

    def process_raw(
        self, 
        bboxes: List[Tuple[float, float, float, float]], 
        confidences: List[float], 
        class_ids: List[int], 
        labels: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Process raw detection inputs, run ByteTrack and Zone analysis, and return enriched dicts.
        """
        if not bboxes or not HAS_SUPERVISION:
            return []

        xyxy = np.array(bboxes)
        conf = np.array(confidences)
        cls_id = np.array(class_ids)

        # 建立 supervision Detections
        sv_dets = sv.Detections(
            xyxy=xyxy,
            confidence=conf,
            class_id=cls_id
        )
        
        # 建立 label map 以便後續還原標籤
        label_map = {cid: label for cid, label in zip(class_ids, labels)}
        
        # 執行 ByteTrack 追蹤
        tracked_dets = self.tracker.update_with_detections(sv_dets)
        
        if len(tracked_dets) == 0:
            return []

        # 執行 Zone-aware risk assessment
        in_zone = self.zone.trigger(detections=tracked_dets)

        results = []
        for i in range(len(tracked_dets)):
            box = tuple(float(x) for x in tracked_dets.xyxy[i])
            c = float(tracked_dets.confidence[i])
            cid = int(tracked_dets.class_id[i])
            tid = int(tracked_dets.tracker_id[i]) if tracked_dets.tracker_id is not None else -1
            is_high_risk = bool(in_zone[i])
            
            # 還原 label
            label = label_map.get(cid, f"class_{cid}")
            
            results.append({
                "bbox": box,
                "confidence": c,
                "class_id": cid,
                "track_id": tid,
                "label": label,
                "risk_level": "high" if is_high_risk else "normal"
            })
            
        return results

if __name__ == "__main__":
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="Supervision Adapter Self-Test")
    parser.add_argument("--test", action="store_true", help="Run self-test")
    args = parser.parse_args()
    
    if args.test:
        print("Running Supervision Adapter self-test...")
        if not HAS_SUPERVISION:
            print("[WARN] supervision package is not installed. Testing fallback state.")
            print("Fallback state OK: HAS_SUPERVISION is False.")
            sys.exit(0)
            
        print("supervision is installed. Testing pipeline initialization...")
        try:
            pipeline = SupervisionAnalyticsPipeline(frame_resolution=(640, 480))
            print("Pipeline initialized successfully.")
            
            # Dummy detections (inside and outside zone)
            bboxes = [
                (10.0, 10.0, 50.0, 50.0),      # Top-left (outside zone)
                (300.0, 300.0, 350.0, 350.0)   # Center-bottom (inside zone)
            ]
            confidences = [0.9, 0.85]
            class_ids = [0, 2]
            labels = ["person", "car"]
            
            print("Running process_raw with dummy detections...")
            results = pipeline.process_raw(bboxes, confidences, class_ids, labels)
            
            print(f"Processed {len(results)} detections.")
            for r in results:
                print(f"  - Label: {r['label']}, TrackID: {r['track_id']}, Risk: {r['risk_level']}")
                
            print("Self-test passed!")
            sys.exit(0)
        except Exception as e:
            print(f"Self-test failed with error: {e}")
            sys.exit(1)

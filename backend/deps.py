"""
MA-VLNA Backend — 依賴注入模組

提供 Supabase 客戶端的單例管理與 FastAPI 依賴注入函式，
所有設定從環境變數讀取。
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from supabase import Client, create_client

logger = logging.getLogger("ma_vlna.deps")

# ---- 載入 .env（向上搜尋 config/.env 或專案根目錄 .env）----
_env_candidates = [
    Path(__file__).resolve().parent.parent / "config" / ".env",
    Path(__file__).resolve().parent.parent / ".env",
    Path(__file__).resolve().parent / ".env",
]
for _env_path in _env_candidates:
    if _env_path.exists():
        load_dotenv(_env_path)
        logger.info("已載入環境變數：%s", _env_path)
        break
else:
    load_dotenv()  # 回退：預設搜尋路徑
    logger.warning("未找到明確的 .env 檔案，使用預設 dotenv 搜尋")


# ============================================================
# 環境變數常數（供其他模組引用）
# ============================================================

SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

# 資料表名稱
VEHICLE_STATUS_TABLE: str = os.getenv("VEHICLE_STATUS_TABLE", "vehicle_status")
SCENE_LOGS_TABLE: str = os.getenv("SCENE_LOGS_TABLE", "scene_logs")
TRAJECTORY_MEMORY_TABLE: str = os.getenv("TRAJECTORY_MEMORY_TABLE", "trajectory_memory")

# 預設車輛 ID
DEFAULT_VEHICLE_ID: str = os.getenv("VEHICLE_ID", "vehicle-001")

# API 設定
API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("API_PORT", "8080"))

# 記憶查詢預設值
MEMORY_TOP_K: int = int(os.getenv("MEMORY_TOP_K", "5"))
EMBEDDING_DIMENSION: int = int(os.getenv("EMBEDDING_DIMENSION", "768"))


# ============================================================
# Supabase 客戶端單例
# ============================================================

# ============================================================
# ============================================================
# ============================================================
# Mock Supabase 客戶端（用於無 Supabase 時提供測試數據）
# ============================================================

class MockResponse:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count

class MockNotFilter:
    def __init__(self, builder):
        self.builder = builder

    def is_(self, col, val):
        return self.builder

class MockTableBuilder:
    def __init__(self, table_name):
        self.table_name = table_name
        self._select_cols = "*"
        self._eq_col = None
        self._eq_val = None
        self._order_col = None
        self._desc = False
        self._limit_num = None
        self._range_start = None
        self._range_end = None
        self._insert_rows = None
        self._upsert_rows = None
        self._update_val = None

    @property
    def not_(self):
        return MockNotFilter(self)

    def select(self, cols="*", count=None):
        self._select_cols = cols
        return self

    def insert(self, rows):
        self._insert_rows = rows
        return self

    def upsert(self, rows):
        self._upsert_rows = rows
        return self

    def update(self, val):
        self._update_val = val
        return self

    def eq(self, col, val):
        self._eq_col = col
        self._eq_val = val
        return self

    def neq(self, col, val):
        return self

    def order(self, col, desc=False):
        self._order_col = col
        self._desc = desc
        return self

    def limit(self, num):
        self._limit_num = num
        return self

    def range(self, start, end):
        self._range_start = start
        self._range_end = end
        return self

    def execute(self):
        import uuid
        from datetime import datetime, timezone
        now_str = datetime.now(timezone.utc).isoformat()

        if self.table_name == "vehicle_status":
            if self._update_val:
                return MockResponse(data=[self._update_val])
            status_data = {
                "vehicle_id": self._eq_val or "vehicle-001",
                "planner_state": "navigating",
                "current_speed": 1.2,
                "position_x": 10.5,
                "position_y": 20.3,
                "position_z": 0.0,
                "heading_deg": 45.0,
                "safe_mode": False,
                "last_trigger_reason": "unknown_obstacle",
                "vlm_active": True,
                "current_action": "forward",
                "updated_at": now_str
            }
            return MockResponse(data=[status_data])

        elif self.table_name == "scene_logs":
            if self._update_val:
                return MockResponse(data=[{"scene_id": self._eq_val, **self._update_val}])
            if self._insert_rows:
                rows = self._insert_rows if isinstance(self._insert_rows, list) else [self._insert_rows]
                return MockResponse(data=rows)
            
            mock_scenes = []
            for i in range(5):
                scene_uuid = str(uuid.UUID(int=i+1))
                mock_scenes.append({
                    "scene_id": scene_uuid,
                    "vehicle_id": "vehicle-001",
                    "timestamp": now_str,
                    "frame_url": f"https://example.com/frames/{scene_uuid}.jpg",
                    "thumbnail_url": f"https://example.com/thumbnails/{scene_uuid}.jpg",
                    "detections": [{"label": "human", "confidence": 0.9, "bbox": [100, 150, 50, 120]}],
                    "tracks": [],
                    "lane_state": "clear",
                    "free_space": {},
                    "trigger_reason": "unknown_scene" if i % 2 == 0 else "low_confidence",
                    "trigger_details": {},
                    "embedding": [0.1] * 768,  # Add mock embedding
                    "vlm_output": {
                        "scene_summary": f"Front path is clear, index {i}",
                        "hazards": [{"label": "human", "severity": "low"}],
                        "navigable_regions": [{"region_id": "center", "description": "center lane"}],
                        "waypoint_hints": [{"hint": "keep straight", "direction": "forward"}],
                        "speed_hint": "normal",
                        "must_not_do": [],
                        "confidence": 0.85
                    },
                    "vlm_latency_ms": 250,
                    "planner_action": {
                        "plan_id": f"plan-{i}",
                        "action_sequence": [{"action": "forward", "duration_sec": 2.0}],
                        "waypoints": [{"x": 1.0, "y": 2.0}]
                    },
                    "planner_state": "navigating",
                    "success_flag": True,
                    "outcome": "arrived",
                    "metadata": {}
                })
            
            if self._eq_col == "scene_id":
                filtered = [s for s in mock_scenes if s["scene_id"] == self._eq_val]
                return MockResponse(data=filtered)
            
            return MockResponse(data=mock_scenes, count=100)

        elif self.table_name == "trajectory_memory":
            mock_trajectories = []
            for i in range(5):
                scene_uuid = str(uuid.UUID(int=i+1))
                traj_uuid = str(uuid.UUID(int=i+100))
                mock_trajectories.append({
                    "memory_id": traj_uuid,
                    "scene_id": scene_uuid,
                    "vehicle_id": "vehicle-001",
                    "timestamp": now_str,
                    "action_sequence": [{"action": "forward", "duration_sec": 2.0}],
                    "waypoints": [{"x": 1.0, "y": 2.0}],
                    "outcome": "arrived",
                    "success_flag": True,
                    "replay_count": 3,
                    "semantic_summary": "Front path is clear"
                })
            if self._eq_col == "scene_id":
                filtered = [t for t in mock_trajectories if t["scene_id"] == self._eq_val]
                return MockResponse(data=filtered)
            return MockResponse(data=mock_trajectories)

        return MockResponse(data=[])

class MockRpcBuilder:
    def __init__(self, func_name, params):
        self.func_name = func_name
        self.params = params

    def execute(self):
        import uuid
        from datetime import datetime, timezone
        now_str = datetime.now(timezone.utc).isoformat()

        # 讀取篩選參數
        try:
            match_threshold = float(self.params.get("match_threshold", 0.5))
        except (ValueError, TypeError):
            match_threshold = 0.5

        try:
            match_count = int(self.params.get("match_count", 5))
        except (ValueError, TypeError):
            match_count = 5

        if self.func_name in ("match_scene_memories", "match_scene_logs"):
            results = []
            for i in range(5):
                similarity = 0.95 - (i * 0.05)
                if similarity >= match_threshold:
                    scene_uuid = str(uuid.UUID(int=i+1))
                    results.append({
                        "scene_id": scene_uuid,
                        "memory_id": str(uuid.UUID(int=i+100)),
                        "vehicle_id": self.params.get("filter_vehicle_id", "vehicle-001"),
                        "timestamp": now_str,
                        "similarity": similarity,
                        "is_replay_candidate": True,
                        "success_flag": True,
                        "semantic_summary": f"Front path clear, memory {i}",
                        "thumbnail_url": f"https://example.com/thumbnails/{scene_uuid}.jpg",
                        "action_sequence": [{"action": "forward", "duration_sec": 2.0}],
                        "outcome": "arrived",
                        "replay_count": 3,
                        "source_scene_id": scene_uuid
                    })
            results = results[:match_count]
            return MockResponse(data=results)
            
        elif self.func_name in ("match_trajectory_memories", "match_trajectory_memory"):
            # Check only_success parameter
            only_success = self.params.get("only_success", True)
            if only_success is None:
                only_success = self.params.get("require_success", True)

            results = []
            for i in range(5):
                similarity = 0.95 - (i * 0.05)
                if similarity >= match_threshold:
                    scene_uuid = str(uuid.UUID(int=i+1))
                    results.append({
                        "scene_id": scene_uuid,
                        "memory_id": str(uuid.UUID(int=i+100)),
                        "vehicle_id": "vehicle-001",
                        "timestamp": now_str,
                        "similarity": similarity,
                        "is_replay_candidate": True,
                        "success_flag": True,
                        "semantic_summary": f"Front path clear, trajectory {i}",
                        "thumbnail_url": f"https://example.com/thumbnails/{scene_uuid}.jpg",
                        "action_sequence": [{"action": "forward", "duration_sec": 2.0}],
                        "outcome": "arrived",
                        "replay_count": 3,
                        "source_scene_id": scene_uuid
                    })
            results = results[:match_count]
            return MockResponse(data=results)

        return MockResponse(data=[])

class MockSupabaseClient:
    def table(self, table_name):
        return MockTableBuilder(table_name)

    def rpc(self, func_name, params=None):
        return MockRpcBuilder(func_name, params or {})


# ============================================================
# Supabase 客戶端單例
# ============================================================

@lru_cache(maxsize=1)
def _create_supabase_client() -> Client:
    """
    建立並快取 Supabase 客戶端。
    如果環境變數缺失或為預設占位符，則返回 MockSupabaseClient 以避免崩潰。
    """
    is_mock = (
        not SUPABASE_URL 
        or not SUPABASE_KEY 
        or "your-project" in SUPABASE_URL 
        or "your-anon" in SUPABASE_KEY
    )
    
    if is_mock:
        logger.warning("檢測到無效或預設 Supabase 設定 — 啟用 MockSupabaseClient 以便本地開發驗證")
        return MockSupabaseClient() # type: ignore
        
    logger.info("正在建立真實 Supabase 客戶端: %s", SUPABASE_URL)
    try:
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        return client
    except Exception as exc:
        logger.warning("建立 Supabase 連接失敗: %s — 降級至 MockSupabaseClient", exc)
        return MockSupabaseClient() # type: ignore

def get_supabase() -> Client:
    """
    FastAPI 依賴注入 — 取得 Supabase 客戶端。

    用法::

        @router.get("/example")
        async def example(db: Client = Depends(get_supabase)):
            ...
    """
    return _create_supabase_client()

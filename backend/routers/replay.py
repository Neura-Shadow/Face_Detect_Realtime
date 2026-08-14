"""
MA-VLNA Backend — 場景回放路由

提供場景回放資料包查詢端點，聚合場景日誌、軌跡記憶與相關場景，
供前端 Replay 面板完整重現場景。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Path
from supabase import Client

from backend.deps import SCENE_LOGS_TABLE, TRAJECTORY_MEMORY_TABLE, get_supabase
from backend.schemas import ApiResponse, ReplayData, SceneLog

logger = logging.getLogger("ma_vlna.routers.replay")

router = APIRouter(prefix="/api/replay", tags=["場景回放"])

# 場景日誌查詢欄位（排除 embedding 以節省頻寬）
_SCENE_SELECT = (
    "scene_id, vehicle_id, timestamp, frame_url, thumbnail_url, "
    "detections, tracks, lane_state, free_space, "
    "trigger_reason, trigger_details, vlm_output, vlm_latency_ms, "
    "planner_action, planner_state, success_flag, outcome, metadata"
)


@router.get("/{scene_id}", response_model=ApiResponse[ReplayData])
async def get_replay_data(
    scene_id: str = Path(..., description="場景識別碼 (UUID)"),
    db: Client = Depends(get_supabase),
) -> ApiResponse[ReplayData]:
    """
    取得場景回放資料包。

    聚合三種資料來源：
    1. **場景日誌**：完整的 scene_log 記錄
    2. **軌跡記憶**：與該場景關聯的 trajectory_memory 條目
    3. **相關場景**：同一車輛在相近時間窗口內的場景

    用於前端 Replay 面板完整重現場景上下文。
    """
    try:
        # ---- 1. 取得目標場景日誌 ----
        scene_result = (
            db.table(SCENE_LOGS_TABLE)
            .select(_SCENE_SELECT)
            .eq("scene_id", scene_id)
            .limit(1)
            .execute()
        )

        if not scene_result.data:
            return ApiResponse.error(
                error_code="SCENE_NOT_FOUND",
                error_message=f"找不到場景 '{scene_id}'",
                retryable=False,
            )

        scene_log = SceneLog(**scene_result.data[0])

        # ---- 2. 取得關聯軌跡記憶 ----
        traj_result = (
            db.table(TRAJECTORY_MEMORY_TABLE)
            .select(
                "memory_id, scene_id, vehicle_id, "
                "action_sequence, waypoints, outcome, success_flag, "
                "replay_count, semantic_summary, created_at"
            )
            .eq("scene_id", scene_id)
            .order("created_at", desc=True)
            .execute()
        )
        trajectory_memory = traj_result.data or []

        # ---- 3. 取得相關場景（同一車輛，時間前後 60 秒）----
        related_scenes: list[SceneLog] = []
        try:
            # 取得前後 5 筆場景做為上下文
            related_result = (
                db.table(SCENE_LOGS_TABLE)
                .select(_SCENE_SELECT)
                .eq("vehicle_id", scene_log.vehicle_id)
                .neq("scene_id", scene_id)
                .order("timestamp", desc=True)
                .limit(5)
                .execute()
            )
            related_scenes = [SceneLog(**row) for row in (related_result.data or [])]
        except Exception as exc:
            # 相關場景查詢失敗不應阻擋主要資料回傳
            logger.warning("查詢相關場景失敗（非致命錯誤）：%s", exc)

        replay_data = ReplayData(
            scene_log=scene_log,
            trajectory_memory=trajectory_memory,
            related_scenes=related_scenes,
        )
        return ApiResponse.success(data=replay_data)

    except Exception as exc:
        logger.exception("場景回放資料查詢失敗：scene_id=%s", scene_id)
        return ApiResponse.error(
            error_code="REPLAY_QUERY_ERROR",
            error_message=f"場景回放資料查詢時發生錯誤：{exc}",
            retryable=True,
        )

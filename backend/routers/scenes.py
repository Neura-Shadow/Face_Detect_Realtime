"""
MA-VLNA Backend — 場景日誌路由

提供場景日誌的分頁列表與單一場景詳細查詢端點，
資料來源為 scene_logs 資料表。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Path, Query
from supabase import Client

from backend.deps import DEFAULT_VEHICLE_ID, SCENE_LOGS_TABLE, get_supabase
from backend.schemas import ApiResponse, SceneLog

logger = logging.getLogger("ma_vlna.routers.scenes")

router = APIRouter(prefix="/api/scenes", tags=["場景日誌"])


# ---- 分頁回應模型 ----
from pydantic import BaseModel, Field


class PaginatedScenes(BaseModel):
    """分頁場景日誌回應"""
    items: list[SceneLog] = Field(default_factory=list, description="場景日誌列表")
    total: int = Field(default=0, description="總筆數")
    limit: int = Field(default=20, description="每頁筆數")
    offset: int = Field(default=0, description="偏移量")


@router.get("", response_model=ApiResponse[PaginatedScenes])
async def list_scenes(
    vehicle_id: str | None = Query(
        default=None, description="車輛識別碼篩選"
    ),
    limit: int = Query(default=20, ge=1, le=200, description="每頁筆數"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    db: Client = Depends(get_supabase),
) -> ApiResponse[PaginatedScenes]:
    """
    取得場景日誌分頁列表。

    支援依車輛識別碼篩選，按時間倒序排列。
    回傳不含 embedding 欄位以減少傳輸量。
    """
    vid = vehicle_id or DEFAULT_VEHICLE_ID
    try:
        # 查詢場景日誌（排除 embedding 欄位以節省頻寬）
        select_cols = (
            "scene_id, vehicle_id, timestamp, frame_url, thumbnail_url, "
            "detections, tracks, lane_state, free_space, "
            "trigger_reason, trigger_details, vlm_output, vlm_latency_ms, "
            "planner_action, planner_state, success_flag, outcome, metadata"
        )

        query = (
            db.table(SCENE_LOGS_TABLE)
            .select(select_cols, count="exact")
            .eq("vehicle_id", vid)
            .order("timestamp", desc=True)
            .range(offset, offset + limit - 1)
        )

        result = query.execute()
        items = [SceneLog(**row) for row in (result.data or [])]
        total = result.count if result.count is not None else len(items)

        return ApiResponse.success(
            data=PaginatedScenes(
                items=items,
                total=total,
                limit=limit,
                offset=offset,
            )
        )

    except Exception as exc:
        logger.exception("查詢場景日誌列表失敗")
        return ApiResponse.error(
            error_code="SCENE_LIST_QUERY_ERROR",
            error_message=f"查詢場景日誌列表時發生錯誤：{exc}",
            retryable=True,
        )


@router.get("/{scene_id}", response_model=ApiResponse[SceneLog])
async def get_scene(
    scene_id: str = Path(..., description="場景識別碼 (UUID)"),
    db: Client = Depends(get_supabase),
) -> ApiResponse[SceneLog]:
    """
    取得單一場景日誌的完整詳細資料。

    依場景識別碼查詢，回傳包含 VLM 輸出、規劃器動作等完整資訊。
    """
    try:
        select_cols = (
            "scene_id, vehicle_id, timestamp, frame_url, thumbnail_url, "
            "detections, tracks, lane_state, free_space, "
            "trigger_reason, trigger_details, vlm_output, vlm_latency_ms, "
            "planner_action, planner_state, success_flag, outcome, metadata"
        )

        result = (
            db.table(SCENE_LOGS_TABLE)
            .select(select_cols)
            .eq("scene_id", scene_id)
            .limit(1)
            .execute()
        )

        if not result.data:
            return ApiResponse.error(
                error_code="SCENE_NOT_FOUND",
                error_message=f"找不到場景 '{scene_id}'",
                retryable=False,
            )

        scene = SceneLog(**result.data[0])
        return ApiResponse.success(data=scene)

    except Exception as exc:
        logger.exception("查詢場景詳細資料失敗：scene_id=%s", scene_id)
        return ApiResponse.error(
            error_code="SCENE_DETAIL_QUERY_ERROR",
            error_message=f"查詢場景詳細資料時發生錯誤：{exc}",
            retryable=True,
        )

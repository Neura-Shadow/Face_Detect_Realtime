"""
MA-VLNA Backend — 規劃器狀態路由

提供當前規劃器狀態查詢端點，
聚合 scene_logs 最新規劃動作與 vehicle_status 的規劃器狀態。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from supabase import Client

from backend.deps import DEFAULT_VEHICLE_ID, SCENE_LOGS_TABLE, VEHICLE_STATUS_TABLE, get_supabase
from backend.schemas import ApiResponse

logger = logging.getLogger("ma_vlna.routers.planner")

router = APIRouter(prefix="/api/planner", tags=["規劃器"])


class PlannerStateResponse(BaseModel):
    """
    規劃器狀態回應。

    聚合 vehicle_status 的即時狀態與 scene_logs 的最新規劃動作，
    提供規劃器的完整上下文。
    """
    vehicle_id: str = Field(..., description="車輛識別碼")
    planner_state: str = Field(default="idle", description="規劃器狀態")
    current_action: str = Field(default="none", description="當前執行動作")
    safe_mode: bool = Field(default=False, description="安全模式狀態")
    vlm_active: bool = Field(default=False, description="VLM 是否介入中")
    latest_planner_action: dict[str, Any] | None = Field(
        default=None, description="最新規劃器動作（來自 scene_logs）"
    )
    latest_scene_id: str | None = Field(
        default=None, description="最新場景識別碼"
    )
    latest_scene_timestamp: str | None = Field(
        default=None, description="最新場景時間戳"
    )
    updated_at: str | None = Field(
        default=None, description="vehicle_status 最後更新時間"
    )


@router.get("/state", response_model=ApiResponse[PlannerStateResponse])
async def get_planner_state(
    vehicle_id: str | None = Query(
        default=None, description="車輛識別碼"
    ),
    db: Client = Depends(get_supabase),
) -> ApiResponse[PlannerStateResponse]:
    """
    取得當前規劃器狀態。

    聚合兩個資料來源：
    1. **vehicle_status**：即時規劃器狀態、安全模式、VLM 狀態
    2. **scene_logs**：最新的 planner_action 記錄

    提供規劃器的完整即時上下文。
    """
    vid = vehicle_id or DEFAULT_VEHICLE_ID

    try:
        # ---- 1. 從 vehicle_status 取得即時狀態 ----
        status_result = (
            db.table(VEHICLE_STATUS_TABLE)
            .select("*")
            .eq("vehicle_id", vid)
            .limit(1)
            .execute()
        )

        if not status_result.data:
            return ApiResponse.error(
                error_code="VEHICLE_NOT_FOUND",
                error_message=f"找不到車輛 '{vid}' 的狀態記錄",
                retryable=False,
            )

        status = status_result.data[0]

        # ---- 2. 從 scene_logs 取得最新規劃動作 ----
        scene_result = (
            db.table(SCENE_LOGS_TABLE)
            .select("scene_id, timestamp, planner_action, planner_state")
            .eq("vehicle_id", vid)
            .not_.is_("planner_action", "null")
            .order("timestamp", desc=True)
            .limit(1)
            .execute()
        )

        latest_action = None
        latest_scene_id = None
        latest_scene_ts = None

        if scene_result.data:
            row = scene_result.data[0]
            latest_action = row.get("planner_action")
            latest_scene_id = row.get("scene_id")
            latest_scene_ts = row.get("timestamp")

        response = PlannerStateResponse(
            vehicle_id=vid,
            planner_state=status.get("planner_state", "idle"),
            current_action=status.get("current_action", "none"),
            safe_mode=status.get("safe_mode", False),
            vlm_active=status.get("vlm_active", False),
            latest_planner_action=latest_action,
            latest_scene_id=latest_scene_id,
            latest_scene_timestamp=latest_scene_ts,
            updated_at=status.get("updated_at"),
        )
        return ApiResponse.success(data=response)

    except Exception as exc:
        logger.exception("查詢規劃器狀態失敗")
        return ApiResponse.error(
            error_code="PLANNER_STATE_QUERY_ERROR",
            error_message=f"查詢規劃器狀態時發生錯誤：{exc}",
            retryable=True,
        )

"""
MA-VLNA Backend — 觸發事件路由

提供近期觸發事件查詢端點，
篩選 scene_logs 中 trigger_reason 不為 NULL 的記錄。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from supabase import Client

from backend.deps import DEFAULT_VEHICLE_ID, SCENE_LOGS_TABLE, get_supabase
from backend.schemas import ApiResponse

logger = logging.getLogger("ma_vlna.routers.triggers")

router = APIRouter(prefix="/api/triggers", tags=["觸發事件"])


class TriggerEvent(BaseModel):
    """
    觸發事件摘要。

    從 scene_logs 中提取觸發相關欄位的精簡視圖。
    """
    scene_id: str = Field(..., description="場景識別碼")
    vehicle_id: str = Field(..., description="車輛識別碼")
    timestamp: str = Field(..., description="觸發時間")
    trigger_reason: str = Field(..., description="觸發原因")
    trigger_details: dict[str, Any] = Field(
        default_factory=dict, description="觸發細節"
    )
    vlm_latency_ms: int | None = Field(default=None, description="VLM 延遲（毫秒）")
    planner_state: str | None = Field(default=None, description="規劃器狀態")
    success_flag: bool | None = Field(default=None, description="場景結果")
    outcome: str | None = Field(default=None, description="結果描述")


@router.get("/recent", response_model=ApiResponse[list[TriggerEvent]])
async def get_recent_triggers(
    vehicle_id: str | None = Query(
        default=None, description="車輛識別碼篩選"
    ),
    limit: int = Query(
        default=20, ge=1, le=200, description="回傳筆數上限"
    ),
    trigger_reason: str | None = Query(
        default=None,
        description="觸發原因篩選（如 low_confidence、unknown_scene）",
    ),
    db: Client = Depends(get_supabase),
) -> ApiResponse[list[TriggerEvent]]:
    """
    查詢近期觸發事件。

    從 scene_logs 中篩選 trigger_reason 不為 NULL 的記錄，
    按時間倒序排列。可選依觸發原因進一步篩選。
    """
    vid = vehicle_id or DEFAULT_VEHICLE_ID

    try:
        query = (
            db.table(SCENE_LOGS_TABLE)
            .select(
                "scene_id, vehicle_id, timestamp, "
                "trigger_reason, trigger_details, "
                "vlm_latency_ms, planner_state, success_flag, outcome"
            )
            .eq("vehicle_id", vid)
            .not_.is_("trigger_reason", "null")
            .order("timestamp", desc=True)
            .limit(limit)
        )

        # 可選：依特定觸發原因篩選
        if trigger_reason:
            query = query.eq("trigger_reason", trigger_reason)

        result = query.execute()

        events = [TriggerEvent(**row) for row in (result.data or [])]
        return ApiResponse.success(data=events)

    except Exception as exc:
        logger.exception("查詢觸發事件失敗")
        return ApiResponse.error(
            error_code="TRIGGER_QUERY_ERROR",
            error_message=f"查詢觸發事件時發生錯誤：{exc}",
            retryable=True,
        )

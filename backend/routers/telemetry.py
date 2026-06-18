"""
MA-VLNA Backend — 遙測資料路由

提供近期遙測資料查詢端點，
支援依車輛識別碼與事件類型篩選。

注意：遙測資料由 Agent 主循環寫入 scene_logs + vehicle_status，
此路由僅負責讀取，不執行任何推理計算。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from supabase import Client

from backend.deps import DEFAULT_VEHICLE_ID, SCENE_LOGS_TABLE, VEHICLE_STATUS_TABLE, get_supabase
from backend.schemas import ApiResponse, TelemetryEntry

logger = logging.getLogger("ma_vlna.routers.telemetry")

router = APIRouter(prefix="/api/telemetry", tags=["遙測資料"])


@router.get("/recent", response_model=ApiResponse[list[TelemetryEntry]])
async def get_recent_telemetry(
    vehicle_id: str | None = Query(
        default=None, description="車輛識別碼篩選"
    ),
    limit: int = Query(
        default=50, ge=1, le=500, description="回傳筆數上限"
    ),
    event_type: str | None = Query(
        default=None,
        description="事件類型篩選（如 vlm_triggered、safe_stop）",
    ),
    db: Client = Depends(get_supabase),
) -> ApiResponse[list[TelemetryEntry]]:
    """
    查詢近期遙測資料。

    從 scene_logs 資料表提取遙測相關欄位並組合為 TelemetryEntry，
    支援依車輛識別碼與事件類型篩選，按時間倒序排列。
    """
    vid = vehicle_id or DEFAULT_VEHICLE_ID

    try:
        # ---- 從 scene_logs 組合遙測資料 ----
        query = (
            db.table(SCENE_LOGS_TABLE)
            .select(
                "scene_id, vehicle_id, timestamp, "
                "trigger_reason, trigger_details, "
                "planner_state, vlm_output, vlm_latency_ms, "
                "success_flag, outcome, metadata"
            )
            .eq("vehicle_id", vid)
            .order("timestamp", desc=True)
            .limit(limit)
        )

        # 如果指定事件類型，用 trigger_reason 或 metadata 篩選
        if event_type:
            query = query.eq("trigger_reason", event_type)

        result = query.execute()

        # ---- 從 vehicle_status 取得即時狀態做為補充 ----
        status_result = (
            db.table(VEHICLE_STATUS_TABLE)
            .select("*")
            .eq("vehicle_id", vid)
            .limit(1)
            .execute()
        )
        current_status = status_result.data[0] if status_result.data else {}

        # ---- 組合 TelemetryEntry ----
        entries: list[TelemetryEntry] = []
        for row in result.data or []:
            # 推斷事件類型
            inferred_event_type = _infer_event_type(row)

            entry = TelemetryEntry(
                vehicle_id=row.get("vehicle_id", vid),
                timestamp=row["timestamp"],
                event_type=inferred_event_type,
                planner_state=row.get("planner_state", current_status.get("planner_state")),
                current_speed=current_status.get("current_speed"),
                position={
                    "x": current_status.get("position_x", 0.0),
                    "y": current_status.get("position_y", 0.0),
                    "z": current_status.get("position_z", 0.0),
                } if current_status else None,
                heading_deg=current_status.get("heading_deg"),
                trigger_reason=row.get("trigger_reason"),
                vlm_active=current_status.get("vlm_active", False),
                safe_mode=current_status.get("safe_mode", False),
                current_action=current_status.get("current_action", "none"),
                details={
                    "scene_id": row.get("scene_id"),
                    "vlm_latency_ms": row.get("vlm_latency_ms"),
                    "success_flag": row.get("success_flag"),
                    "outcome": row.get("outcome"),
                    **(row.get("trigger_details") or {}),
                },
            )
            entries.append(entry)

        return ApiResponse.success(data=entries)

    except Exception as exc:
        logger.exception("查詢遙測資料失敗")
        return ApiResponse.error(
            error_code="TELEMETRY_QUERY_ERROR",
            error_message=f"查詢遙測資料時發生錯誤：{exc}",
            retryable=True,
        )


def _infer_event_type(row: dict) -> str:
    """
    從 scene_log 欄位推斷遙測事件類型。

    優先順序：
    1. trigger_reason 直接對應已知事件類型
    2. 有 vlm_output → vlm_response
    3. 有 planner_action → planner_update
    4. 預設為 status_update
    """
    trigger = row.get("trigger_reason")
    if trigger:
        # 已知觸發原因直接做為事件類型
        known_events = {
            "low_confidence", "tracker_unstable", "unknown_scene",
            "planner_deadlock", "safe_stop", "request_review",
        }
        if trigger in known_events:
            return "vlm_triggered"
        return trigger

    if row.get("vlm_output"):
        return "vlm_response"
    if row.get("planner_state"):
        return "planner_update"
    return "status_update"

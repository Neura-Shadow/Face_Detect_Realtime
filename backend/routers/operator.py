"""
MA-VLNA Backend — 操作員審查路由

提供操作員審查決策提交端點，
允許人類操作員對場景做出 approve / reject / override 決策。

決策會寫入 scene_logs.metadata 並更新 vehicle_status 狀態。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from supabase import Client

from backend.deps import SCENE_LOGS_TABLE, VEHICLE_STATUS_TABLE, get_supabase
from backend.schemas import ApiResponse, OperatorReviewRequest

logger = logging.getLogger("ma_vlna.routers.operator")

router = APIRouter(prefix="/api/operator", tags=["操作員審查"])


@router.post("/review", response_model=ApiResponse[dict])
async def submit_operator_review(
    request: OperatorReviewRequest,
    db: Client = Depends(get_supabase),
) -> ApiResponse[dict]:
    """
    提交操作員審查決策。

    處理流程：
    1. 驗證目標場景存在
    2. 將審查決策寫入 scene_logs.metadata
    3. 根據決策更新 vehicle_status：
       - approve → 恢復正常行駛狀態
       - reject → 進入安全模式
       - override → 更新 current_action 為指定覆寫動作
    4. 回傳更新確認

    此端點不執行任何推理，僅寫入決策記錄與狀態更新。
    """
    try:
        # ---- 1. 驗證場景存在 ----
        scene_result = (
            db.table(SCENE_LOGS_TABLE)
            .select("scene_id, vehicle_id, metadata")
            .eq("scene_id", request.scene_id)
            .limit(1)
            .execute()
        )

        if not scene_result.data:
            return ApiResponse.error(
                error_code="SCENE_NOT_FOUND",
                error_message=f"找不到場景 '{request.scene_id}'",
                retryable=False,
            )

        scene_row = scene_result.data[0]
        vehicle_id = scene_row["vehicle_id"]
        existing_metadata = scene_row.get("metadata") or {}

        # ---- 2. 更新 scene_logs.metadata（寫入審查決策）----
        review_record = {
            "operator_review": {
                "decision": request.decision.value,
                "operator_notes": request.operator_notes,
                "override_action": request.override_action,
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }
        }
        updated_metadata = {**existing_metadata, **review_record}

        db.table(SCENE_LOGS_TABLE).update(
            {"metadata": updated_metadata}
        ).eq("scene_id", request.scene_id).execute()

        logger.info(
            "操作員審查已寫入：scene_id=%s, decision=%s",
            request.scene_id,
            request.decision.value,
        )

        # ---- 3. 更新 vehicle_status ----
        status_update: dict = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        if request.decision == request.decision.approve:
            # 批准 → 恢復正常行駛狀態
            status_update.update({
                "planner_state": "navigating",
                "safe_mode": False,
                "last_trigger_reason": None,
            })
        elif request.decision == request.decision.reject:
            # 拒絕 → 安全停車
            status_update.update({
                "planner_state": "safe_stop",
                "safe_mode": True,
                "current_action": "stop",
            })
        elif request.decision == request.decision.override:
            # 覆寫 → 使用操作員指定動作
            status_update.update({
                "planner_state": "navigating",
                "safe_mode": False,
                "current_action": request.override_action or "stop",
                "last_trigger_reason": "operator_override",
            })

        db.table(VEHICLE_STATUS_TABLE).update(
            status_update
        ).eq("vehicle_id", vehicle_id).execute()

        logger.info(
            "vehicle_status 已更新：vehicle_id=%s, decision=%s",
            vehicle_id,
            request.decision.value,
        )

        return ApiResponse.success(
            data={
                "scene_id": request.scene_id,
                "vehicle_id": vehicle_id,
                "decision": request.decision.value,
                "status_updated": True,
                "reviewed_at": review_record["operator_review"]["reviewed_at"],
            }
        )

    except Exception as exc:
        logger.exception("提交操作員審查失敗：scene_id=%s", request.scene_id)
        return ApiResponse.error(
            error_code="OPERATOR_REVIEW_ERROR",
            error_message=f"提交操作員審查時發生錯誤：{exc}",
            retryable=True,
        )

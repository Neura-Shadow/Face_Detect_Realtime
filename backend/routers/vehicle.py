"""
MA-VLNA Backend — 車輛狀態路由

提供車輛 / Agent 即時狀態查詢端點，
資料來源為 vehicle_status 資料表。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from supabase import Client

from backend.deps import DEFAULT_VEHICLE_ID, VEHICLE_STATUS_TABLE, get_supabase
from backend.schemas import ApiResponse, VehicleStatus

logger = logging.getLogger("ma_vlna.routers.vehicle")

router = APIRouter(prefix="/api/vehicle", tags=["車輛狀態"])


@router.get("/status", response_model=ApiResponse[VehicleStatus])
async def get_vehicle_status(
    vehicle_id: str = Query(
        default=None,
        description="車輛識別碼，預設使用環境變數 VEHICLE_ID",
    ),
    db: Client = Depends(get_supabase),
) -> ApiResponse[VehicleStatus]:
    """
    取得車輛即時狀態。

    查詢 vehicle_status 資料表中指定車輛的最新狀態記錄，
    包含規劃器狀態、速度、位置、航向、安全模式等資訊。
    """
    vid = vehicle_id or DEFAULT_VEHICLE_ID
    try:
        result = (
            db.table(VEHICLE_STATUS_TABLE)
            .select("*")
            .eq("vehicle_id", vid)
            .limit(1)
            .execute()
        )

        if not result.data:
            return ApiResponse.error(
                error_code="VEHICLE_NOT_FOUND",
                error_message=f"找不到車輛 '{vid}' 的狀態記錄",
                retryable=False,
            )

        status = VehicleStatus(**result.data[0])
        return ApiResponse.success(data=status)

    except Exception as exc:
        logger.exception("查詢車輛狀態失敗：vehicle_id=%s", vid)
        return ApiResponse.error(
            error_code="VEHICLE_STATUS_QUERY_ERROR",
            error_message=f"查詢車輛狀態時發生錯誤：{exc}",
            retryable=True,
        )

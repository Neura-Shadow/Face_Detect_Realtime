"""
MA-VLNA Backend — 場景記憶路由

提供 top-k 相似場景向量記憶查詢端點，
透過 Supabase RPC 呼叫 pgvector 餘弦相似度搜尋。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import Client

from backend.deps import (
    DEFAULT_VEHICLE_ID,
    EMBEDDING_DIMENSION,
    MEMORY_TOP_K,
    SCENE_LOGS_TABLE,
    get_supabase,
)
from backend.schemas import ApiResponse, SceneMemoryEntry

logger = logging.getLogger("ma_vlna.routers.memory")

router = APIRouter(prefix="/api/memory", tags=["場景記憶"])


def _parse_embedding(raw: str) -> list[float]:
    """
    解析逗號分隔的浮點數字串為 embedding 向量。

    驗證維度是否符合設定值（預設 768 維）。
    """
    try:
        values = [float(v.strip()) for v in raw.split(",") if v.strip()]
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"embedding 格式錯誤，需為逗號分隔的浮點數：{exc}",
        )

    if len(values) != EMBEDDING_DIMENSION:
        raise HTTPException(
            status_code=400,
            detail=(
                f"embedding 維度不符：預期 {EMBEDDING_DIMENSION}，"
                f"實際 {len(values)}"
            ),
        )
    return values


@router.get("/top-k", response_model=ApiResponse[list[SceneMemoryEntry]])
async def get_top_k_memories(
    embedding: str | None = Query(
        default=None,
        description=(
            "查詢向量（逗號分隔的浮點數）；"
            "或留空並提供 scene_id 以使用該場景的 embedding"
        ),
    ),
    scene_id: str | None = Query(
        default=None,
        description="場景識別碼 — 使用該場景的 embedding 做為查詢向量",
    ),
    k: int = Query(
        default=None,
        ge=1,
        le=100,
        description="回傳的相似場景數量",
    ),
    vehicle_id: str | None = Query(
        default=None,
        description="車輛識別碼篩選",
    ),
    db: Client = Depends(get_supabase),
) -> ApiResponse[list[SceneMemoryEntry]]:
    """
    查詢 top-k 相似場景記憶。

    支援兩種查詢方式：
    1. 直接提供 embedding 向量（逗號分隔的浮點數）
    2. 提供 scene_id，系統自動擷取該場景的 embedding

    透過 Supabase RPC 呼叫 pgvector 的餘弦相似度搜尋函式。
    """
    top_k = k or MEMORY_TOP_K
    vid = vehicle_id or DEFAULT_VEHICLE_ID

    try:
        # ---- 取得查詢向量 ----
        query_embedding: list[float] | None = None

        if embedding:
            query_embedding = _parse_embedding(embedding)
        elif scene_id:
            # 從指定場景擷取 embedding
            scene_result = (
                db.table(SCENE_LOGS_TABLE)
                .select("embedding")
                .eq("scene_id", scene_id)
                .limit(1)
                .execute()
            )
            if not scene_result.data or not scene_result.data[0].get("embedding"):
                return ApiResponse.error(
                    error_code="SCENE_EMBEDDING_NOT_FOUND",
                    error_message=f"場景 '{scene_id}' 不存在或缺少 embedding",
                    retryable=False,
                )
            raw_emb = scene_result.data[0]["embedding"]
            # embedding 可能是字串（pgvector 格式）或已解析的 list
            if isinstance(raw_emb, str):
                raw_emb = raw_emb.strip("[]")
                query_embedding = [float(v) for v in raw_emb.split(",")]
            elif isinstance(raw_emb, list):
                query_embedding = [float(v) for v in raw_emb]
            else:
                return ApiResponse.error(
                    error_code="EMBEDDING_PARSE_ERROR",
                    error_message="無法解析場景 embedding 格式",
                    retryable=False,
                )
        else:
            return ApiResponse.error(
                error_code="MISSING_QUERY_VECTOR",
                error_message="必須提供 embedding 或 scene_id 參數",
                retryable=False,
            )

        # ---- 呼叫 Supabase RPC（pgvector 餘弦相似度搜尋）----
        rpc_result = db.rpc(
            "match_scene_memories",
            {
                "query_embedding": query_embedding,
                "match_count": top_k,
                "filter_vehicle_id": vid,
            },
        ).execute()

        entries = []
        for row in rpc_result.data or []:
            entry = SceneMemoryEntry(
                scene_id=row.get("scene_id", ""),
                memory_id=row.get("memory_id"),
                vehicle_id=row.get("vehicle_id", vid),
                timestamp=row.get("timestamp", row.get("created_at", "")),
                similarity_score=row.get("similarity", 0.0),
                is_replay_candidate=row.get("is_replay_candidate", False),
                success_flag=row.get("success_flag"),
                semantic_summary=row.get("semantic_summary"),
                thumbnail_url=row.get("thumbnail_url"),
                action_sequence=row.get("action_sequence"),
                outcome=row.get("outcome"),
                replay_count=row.get("replay_count", 0),
                source_scene_id=row.get("source_scene_id"),
            )
            entries.append(entry)

        return ApiResponse.success(data=entries)

    except HTTPException:
        raise  # 讓 FastAPI 原生處理 HTTP 異常
    except Exception as exc:
        logger.exception("top-k 記憶查詢失敗")
        return ApiResponse.error(
            error_code="MEMORY_QUERY_ERROR",
            error_message=f"向量記憶查詢時發生錯誤：{exc}",
            retryable=True,
        )

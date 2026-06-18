"""
MA-VLNA Backend — FastAPI 應用程式入口

負責：
  - 建立 FastAPI app 實例（含 lifespan 生命週期管理）
  - 掛載 CORS 中介軟體（研究用途，允許所有來源）
  - 註冊所有路由模組（/api 前綴）
  - 健康檢查端點 /api/health
  - 根路徑重導向至 /api/health
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from backend.deps import API_HOST, API_PORT, get_supabase
from backend.routers import memory, operator, planner, replay, scenes, telemetry, triggers, vehicle
from backend.schemas import ApiResponse

# ---- 日誌設定 ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-24s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ma_vlna.main")


# ============================================================
# 應用程式生命週期（lifespan）
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    FastAPI lifespan 管理器。

    啟動時驗證 Supabase 連線；關閉時清理資源。
    """
    logger.info("🚀 MA-VLNA Backend API 啟動中…")
    try:
        # 驗證 Supabase 連線
        _client = get_supabase()
        logger.info("✅ Supabase 連線驗證成功")
    except RuntimeError as exc:
        logger.error("❌ Supabase 連線失敗：%s", exc)
        # 仍然啟動（允許 health check 回報錯誤狀態）
    yield
    logger.info("🛑 MA-VLNA Backend API 正在關閉…")


# ============================================================
# FastAPI 實例
# ============================================================

app = FastAPI(
    title="MA-VLNA Backend API",
    description=(
        "Memory-Augmented Vision-Language Navigation Agent — "
        "後端 API 層，提供車輛狀態、場景日誌、向量記憶查詢、"
        "場景回放、遙測、觸發事件、規劃器狀態與操作員審查等端點。"
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# ---- CORS 中介軟體（研究用途，允許所有來源）----
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 註冊路由 ----
app.include_router(vehicle.router)
app.include_router(scenes.router)
app.include_router(memory.router)
app.include_router(replay.router)
app.include_router(telemetry.router)
app.include_router(triggers.router)
app.include_router(planner.router)
app.include_router(operator.router)


# ============================================================
# 根路徑與健康檢查
# ============================================================

@app.get("/", include_in_schema=False)
async def root_redirect():
    """根路徑重導向至健康檢查端點"""
    return RedirectResponse(url="/api/health")


@app.get("/api/health", tags=["系統"])
async def health_check() -> ApiResponse[dict]:
    """
    健康檢查端點。

    回傳 API 服務狀態與 Supabase 連線狀態。
    """
    supabase_ok = False
    try:
        _client = get_supabase()
        supabase_ok = True
    except Exception:
        pass

    return ApiResponse.success(
        data={
            "service": "ma-vlna-backend",
            "version": "0.1.0",
            "supabase_connected": supabase_ok,
        }
    )


# ============================================================
# 獨立執行入口
# ============================================================

if __name__ == "__main__":
    import uvicorn

    logger.info("以 uvicorn 啟動 — %s:%s", API_HOST, API_PORT)
    uvicorn.run(
        "backend.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=True,
        log_level="info",
    )

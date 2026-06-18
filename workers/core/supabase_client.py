"""
Supabase 客戶端管理模組 — 提供 Singleton 連線、畫面上傳與 URL 取得。

使用 supabase-py 官方函式庫，所有連線資訊由 AgentConfig 提供，
絕不在此寫死 URL 或 Key。
"""

from __future__ import annotations

import io
import logging
import uuid
from datetime import datetime, timezone
from threading import Lock
from typing import Any

import numpy as np

from .config import AgentConfig, SupabaseConfig

logger = logging.getLogger(__name__)

# ── 延遲匯入 supabase-py ──────────────────────────────────────
try:
    from supabase import Client as SupabaseClient
    from supabase import create_client

    _HAS_SUPABASE = True
except ImportError:  # pragma: no cover
    _HAS_SUPABASE = False
    logger.warning("supabase-py 未安裝 — SupabaseManager 將以 stub 模式執行")


class SupabaseManager:
    """
    Supabase 連線管理器（Thread-safe Singleton）。

    透過 get_client() 取得 supabase Client，
    upload_frame() 上傳影像至 Storage，
    get_frame_url() 取得公開 URL。
    """

    _instance: SupabaseManager | None = None
    _lock: Lock = Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> SupabaseManager:
        """確保全域唯一實例。"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, config: SupabaseConfig | None = None) -> None:
        """
        初始化 Supabase 客戶端。

        Args:
            config: Supabase 設定；若省略則使用 AgentConfig.load() 的子設定。
        """
        if self._initialized:  # type: ignore[has-type]
            return
        try:
            full_config = AgentConfig.load()
            self._config = config or full_config.supabase
            self._agent_id = full_config.agent_id
        except Exception:
            self._config = config or SupabaseConfig()
            self._agent_id = "vehicle-001"

        self._client: SupabaseClient | None = None

        if _HAS_SUPABASE and self._config.url and self._config.key:
            try:
                self._client = create_client(self._config.url, self._config.key)
                logger.info("Supabase 客戶端已連線: %s", self._config.url)
            except Exception:
                logger.exception("Supabase 客戶端初始化失敗")
        else:
            logger.warning(
                "Supabase 無法初始化 — url=%s, has_lib=%s",
                bool(self._config.url),
                _HAS_SUPABASE,
            )
        self._initialized = True

    # ── 公開介面 ────────────────────────────────────────────────

    def get_client(self) -> SupabaseClient | None:
        """
        回傳 supabase Client 實例；若無法連線則回傳 None。
        """
        if self._client is None:
            logger.warning("Supabase 客戶端不可用 — 呼叫端應處理 None 情境")
        return self._client

    def upload_frame(
        self,
        frame: np.ndarray,
        vehicle_id: str | None = None,
        *,
        bucket: str | None = None,
        quality: int = 85,
    ) -> str | None:
        """
        將 numpy 影像陣列編碼為 JPEG 並上傳至 Supabase Storage。

        Args:
            frame: BGR 格式的 numpy 影像。
            vehicle_id: 車輛識別碼，用於組合儲存路徑；若省略則使用設定中的 agent_id。
            bucket: 儲存桶名稱；預設使用設定值。
            quality: JPEG 壓縮品質 (0-100)。

        Returns:
            上傳後的檔案路徑，失敗則回傳 None。
        """
        if self._client is None:
            logger.warning("upload_frame 失敗 — 客戶端不可用")
            return None

        try:
            import cv2  # 延遲匯入，避免無 OpenCV 時整個模組爆炸

            success, encoded = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality]
            )
            if not success:
                logger.error("cv2.imencode 失敗")
                return None

            vid = vehicle_id or self._agent_id or "vehicle-001"
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            uid = uuid.uuid4().hex[:8]
            file_path = f"{vid}/{ts}_{uid}.jpg"
            target_bucket = bucket or self._config.storage_bucket

            self._client.storage.from_(target_bucket).upload(
                path=file_path,
                file=io.BytesIO(encoded.tobytes()),
                file_options={"content-type": "image/jpeg"},
            )
            logger.info("影像已上傳: bucket=%s, path=%s", target_bucket, file_path)
            return file_path

        except Exception:
            logger.exception("upload_frame 發生例外")
            return None

    def get_frame_url(
        self,
        file_path: str,
        *,
        bucket: str | None = None,
        expires_in: int = 3600,
    ) -> str | None:
        """
        取得已上傳影像的簽署 URL。

        Args:
            file_path: Storage 中的檔案路徑。
            bucket: 儲存桶名稱；預設使用設定值。
            expires_in: 簽署 URL 有效秒數。

        Returns:
            簽署 URL 字串，失敗則回傳 None。
        """
        if self._client is None:
            logger.warning("get_frame_url 失敗 — 客戶端不可用")
            return None

        try:
            target_bucket = bucket or self._config.storage_bucket
            result = self._client.storage.from_(target_bucket).create_signed_url(
                path=file_path,
                expires_in=expires_in,
            )
            
            url = None
            if isinstance(result, dict):
                url = result.get("signedURL") or result.get("signed_url")
            elif result is not None:
                if hasattr(result, "signed_url"):
                    url = result.signed_url
                elif hasattr(result, "signedURL"):
                    url = getattr(result, "signedURL")

            if url:
                logger.debug("取得簽署 URL: %s", url[:80])
            return url
        except Exception:
            logger.exception("get_frame_url 發生例外")
            return None

    def health_check(self) -> bool:
        """驗證與 Supabase 的連線與憑證是否正常。"""
        if self._client is None:
            return False
        try:
            # 呼叫 list_buckets() 測試 API 連通性與 Key 是否有效
            self._client.storage.list_buckets()
            return True
        except Exception:
            return False

    # ── 重置（測試用）──────────────────────────────────────────
    @classmethod
    def reset(cls) -> None:
        """重置 Singleton 實例，僅供測試使用。"""
        with cls._lock:
            cls._instance = None

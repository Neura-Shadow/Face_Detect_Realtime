"""
Supabase 初始化模組 — 對應原始 AddtoDatabase.py。

功能：
  - 讀取並記錄 SQL Migration（001_init.sql）
  - 建立 Supabase Storage bucket（scene-frames）
  - 初始化預設車輛狀態
  - 提供 CRUD 操作供其他模組呼叫

原始 AddtoDatabase.py 使用 Firebase Realtime Database；
此模組已遷移至 Supabase（PostgreSQL + pgvector）。

所有連線資訊從 .env 讀取，絕不寫死。
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core.config import AgentConfig
from .core.supabase_client import SupabaseManager

logger = logging.getLogger(__name__)

# ── 專案路徑 ────────────────────────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent          # workers/
_PROJECT_ROOT = _THIS_DIR.parent                      # 專案根目錄
_MIGRATION_DIR = _PROJECT_ROOT / "migrations"


# ════════════════════════════════════════════════════════════════
# Supabase 初始化器
# ════════════════════════════════════════════════════════════════

class SupabaseInitializer:
    """
    Supabase 初始化器 — 對應原始 AddtoDatabase.py 的角色。

    包含 migration 記錄、Storage bucket 建立、預設狀態寫入與
    基本 CRUD 操作。

    使用方式：
        initializer = SupabaseInitializer()
        initializer.run_migrations()
        initializer.create_storage_bucket()
        initializer.seed_vehicle_status()
    """

    def __init__(self, config: AgentConfig | None = None) -> None:
        self._config = config or AgentConfig.load()
        self._manager = SupabaseManager(self._config.supabase)
        self._vehicle_id = self._config.agent_id
        logger.info(
            "SupabaseInitializer 初始化: vehicle_id=%s",
            self._vehicle_id,
        )

    # ── Migration ───────────────────────────────────────────────

    def run_migrations(self) -> None:
        """
        讀取 migrations/001_init.sql 並記錄 SQL 內容。

        注意：Supabase 的 SQL 通常透過 Dashboard 或 CLI 手動執行，
        此方法僅讀取並記錄 SQL，便於開發者確認要執行的內容。
        """
        migration_file = _MIGRATION_DIR / "001_init.sql"
        if not migration_file.exists():
            logger.error("Migration 檔案不存在: %s", migration_file)
            return

        try:
            sql_content = migration_file.read_text(encoding="utf-8")
            logger.info(
                "═══ Migration SQL (001_init.sql) — %d 字元 ═══",
                len(sql_content),
            )
            # 逐段記錄（避免單條日誌過長）
            for i, chunk in enumerate(sql_content.split("\n\n")):
                stripped = chunk.strip()
                if stripped:
                    logger.info(
                        "Migration 區塊 %d:\n%s",
                        i + 1,
                        stripped[:500],
                    )
            logger.info(
                "═══ 請透過 Supabase Dashboard 或 supabase db push "
                "執行上述 SQL ═══"
            )
        except Exception:
            logger.exception("讀取 migration 檔案失敗")

    # ── Storage Bucket ──────────────────────────────────────────

    def create_storage_bucket(self) -> bool:
        """
        在 Supabase Storage 中建立 scene-frames bucket。

        若 bucket 已存在則跳過。

        Returns:
            True 表示成功（或已存在），False 表示失敗。
        """
        client = self._manager.get_client()
        if client is None:
            logger.warning("create_storage_bucket: Supabase 不可用")
            return False

        bucket_name = self._config.supabase.storage_bucket
        try:
            # 檢查是否已存在
            existing = client.storage.list_buckets()
            bucket_names = [
                b.name if hasattr(b, "name") else b.get("name", "")
                for b in (existing or [])
            ]
            if bucket_name in bucket_names:
                logger.info(
                    "Storage bucket '%s' 已存在 — 跳過建立",
                    bucket_name,
                )
                return True

            # 建立 bucket
            client.storage.create_bucket(
                bucket_name,
                options={"public": False},
            )
            logger.info("Storage bucket '%s' 已建立", bucket_name)
            return True

        except Exception:
            logger.exception(
                "建立 Storage bucket '%s' 失敗",
                bucket_name,
            )
            return False

    # ── 車輛狀態初始化 ──────────────────────────────────────────

    def seed_vehicle_status(self) -> bool:
        """
        寫入預設車輛狀態 — 對應 AddtoDatabase.py 的 seed data。

        Returns:
            True 表示成功，False 表示失敗。
        """
        default_status = {
            "vehicle_id": self._vehicle_id,
            "planner_state": "idle",
            "current_speed": 0.0,
            "position_x": 0.0,
            "position_y": 0.0,
            "position_z": 0.0,
            "heading_deg": 0.0,
            "safe_mode": False,
            "last_trigger_reason": None,
            "vlm_active": False,
            "current_action": "none",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        return self.upsert_vehicle_status(self._vehicle_id, default_status)

    # ── CRUD 操作 ───────────────────────────────────────────────

    def upsert_vehicle_status(
        self,
        vehicle_id: str,
        data: dict[str, Any],
    ) -> bool:
        """
        更新或插入車輛狀態。

        Args:
            vehicle_id: 車輛識別碼。
            data: 狀態資料字典。

        Returns:
            True 表示成功，False 表示失敗。
        """
        client = self._manager.get_client()
        if client is None:
            logger.warning("upsert_vehicle_status: Supabase 不可用")
            return False

        try:
            table_name = self._config.supabase.vehicle_status_table
            payload = {"vehicle_id": vehicle_id, **data}
            client.table(table_name).upsert(payload).execute()
            logger.info(
                "車輛狀態已更新: vehicle_id=%s",
                vehicle_id,
            )
            return True
        except Exception:
            logger.exception("upsert_vehicle_status 失敗")
            return False

    def write_scene_log(self, scene_log_data: dict[str, Any]) -> bool:
        """
        寫入場景日誌。

        Args:
            scene_log_data: 場景日誌字典（需包含 vehicle_id）。

        Returns:
            True 表示成功，False 表示失敗。
        """
        client = self._manager.get_client()
        if client is None:
            logger.warning("write_scene_log: Supabase 不可用")
            return False

        try:
            table_name = self._config.supabase.scene_logs_table
            payload = {
                "vehicle_id": scene_log_data.get(
                    "vehicle_id", self._vehicle_id
                ),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **scene_log_data,
            }
            client.table(table_name).insert(payload).execute()
            logger.info("場景日誌已寫入")
            return True
        except Exception:
            logger.exception("write_scene_log 失敗")
            return False

    def write_trajectory_memory(
        self, memory_data: dict[str, Any]
    ) -> bool:
        """
        寫入軌跡記憶。

        Args:
            memory_data: 軌跡記憶字典。

        Returns:
            True 表示成功，False 表示失敗。
        """
        client = self._manager.get_client()
        if client is None:
            logger.warning("write_trajectory_memory: Supabase 不可用")
            return False

        try:
            table_name = self._config.supabase.trajectory_memory_table
            payload = {
                "vehicle_id": memory_data.get(
                    "vehicle_id", self._vehicle_id
                ),
                **memory_data,
            }
            client.table(table_name).insert(payload).execute()
            logger.info("軌跡記憶已寫入")
            return True
        except Exception:
            logger.exception("write_trajectory_memory 失敗")
            return False

    def fetch_recent_vehicle_status(
        self, vehicle_id: str | None = None
    ) -> dict[str, Any]:
        """
        取得指定車輛的最新狀態。

        Args:
            vehicle_id: 車輛識別碼；預設使用設定中的 agent_id。

        Returns:
            車輛狀態字典，若失敗則回傳空字典。
        """
        vid = vehicle_id or self._vehicle_id
        client = self._manager.get_client()
        if client is None:
            logger.warning("fetch_recent_vehicle_status: Supabase 不可用")
            return {}

        try:
            table_name = self._config.supabase.vehicle_status_table
            result = (
                client.table(table_name)
                .select("*")
                .eq("vehicle_id", vid)
                .limit(1)
                .execute()
            )
            if result.data:
                logger.debug("取得車輛狀態: vehicle_id=%s", vid)
                return dict(result.data[0])
            logger.info("未找到車輛狀態: vehicle_id=%s", vid)
            return {}
        except Exception:
            logger.exception("fetch_recent_vehicle_status 失敗")
            return {}

    # ── 擴充驗證與維護功能 ──────────────────────────────────────────

    def check_tables(self) -> bool:
        """檢查所有核心資料表是否存在於 Supabase 中。"""
        client = self._manager.get_client()
        if client is None:
            logger.warning("check_tables: Supabase 連線不可用")
            return False

        tables = [
            self._config.supabase.vehicle_status_table,
            self._config.supabase.scene_logs_table,
            self._config.supabase.trajectory_memory_table,
            "telemetry_entries",
            "trigger_events",
            "operator_reviews",
        ]

        all_exist = True
        for table in tables:
            try:
                # 執行 SELECT 1 LIMIT 0 快速偵測資料表是否存在
                client.table(table).select("*").limit(0).execute()
                logger.info("  [OK] 資料表 '%s' 存在且可讀取", table)
            except Exception as exc:
                logger.error("  [FAIL] 資料表 '%s' 異常或不存在: %s", table, exc)
                all_exist = False
        return all_exist

    def check_rpcs(self) -> bool:
        """檢查 pgvector 相似度 RPC 檢索函式是否存在與可用。"""
        client = self._manager.get_client()
        if client is None:
            logger.warning("check_rpcs: Supabase 連線不可用")
            return False

        import numpy as np
        zero_vector = np.zeros(768).tolist()
        all_ok = True

        # 1. 檢測 match_scene_memories
        try:
            client.rpc(
                "match_scene_memories",
                {
                    "query_embedding": zero_vector,
                    "match_count": 1,
                    "match_threshold": 0.0,
                }
            ).execute()
            logger.info("  [OK] RPC 'match_scene_memories' 呼叫正常")
        except Exception as exc:
            logger.error("  [FAIL] RPC 'match_scene_memories' 異常: %s", exc)
            all_ok = False

        # 2. 檢測 match_trajectory_memories
        try:
            client.rpc(
                "match_trajectory_memories",
                {
                    "query_embedding": zero_vector,
                    "match_count": 1,
                    "match_threshold": 0.0,
                    "only_success": True
                }
            ).execute()
            logger.info("  [OK] RPC 'match_trajectory_memories' 呼叫正常")
        except Exception as exc:
            logger.error("  [FAIL] RPC 'match_trajectory_memories' 異常: %s", exc)
            all_ok = False

        return all_ok

    def seed_sample_data(self, dry_run: bool = False) -> bool:
        """寫入測試用的種子資料 (vehicle_status, scene_logs, trajectory_memory)。"""
        if dry_run:
            logger.info("[DRY-RUN] 將寫入預設車輛狀態與範例場景/軌跡資料")
            return True

        # 1. 寫入車輛狀態
        ok = self.seed_vehicle_status()
        if not ok:
            logger.error("寫入車輛狀態失敗")
            return False

        # 2. 寫入範例場景日誌 (包含 768 維 zero-embedding)
        import numpy as np
        zero_embedding = np.zeros(768).tolist()
        sample_scene_id = "99999999-9999-9999-9999-999999999999"

        scene_data = {
            "scene_id": sample_scene_id,
            "vehicle_id": self._vehicle_id,
            "embedding": zero_embedding,
            "frame_url": "https://example.com/seed_frame.jpg",
            "thumbnail_url": "https://example.com/seed_thumb.jpg",
            "lane_state": "clear",
            "trigger_reason": "seed_sample",
            "success_flag": True,
            "outcome": "arrived",
            "metadata": {"semantic_summary": "初始化種子場景：前車道暢通"}
        }

        # 清除舊種子資料以防止主鍵衝突
        client = self._manager.get_client()
        if client is not None:
            try:
                client.table(self._config.supabase.trajectory_memory_table).delete().eq("scene_id", sample_scene_id).execute()
                client.table(self._config.supabase.scene_logs_table).delete().eq("scene_id", sample_scene_id).execute()
            except Exception:
                pass

        scene_ok = self.write_scene_log(scene_data)
        if not scene_ok:
            logger.error("寫入種子場景日誌失敗")
            return False

        # 3. 寫入一個軌跡記憶
        sample_memory_id = "88888888-8888-8888-8888-888888888888"
        traj_data = {
            "memory_id": sample_memory_id,
            "scene_id": sample_scene_id,
            "vehicle_id": self._vehicle_id,
            "embedding": zero_embedding,
            "action_sequence": [{"action": "forward", "duration_sec": 2.0}],
            "waypoints": [{"x": 0.0, "y": 0.0, "z": 0.0}],
            "outcome": "arrived",
            "success_flag": True,
            "replay_count": 1,
            "semantic_summary": "初始化種子軌跡：前進兩秒"
        }

        traj_ok = self.write_trajectory_memory(traj_data)
        if not traj_ok:
            logger.error("寫入種子軌跡記憶失敗")
            return False

        logger.info("種子資料寫入成功 (vehicle_id=%s, scene_id=%s, memory_id=%s)", 
                    self._vehicle_id, sample_scene_id, sample_memory_id)
        return True

    def verify_all(self) -> bool:
        """執行完整系統驗證，包括連線、資料表、RPC 與種子資料。"""
        logger.info("=== 開始執行全面功能驗證 ===")
        
        # 1. 檢查連線
        conn_ok = self._manager.health_check()
        logger.info("1. Supabase 連線測試: %s", "成功" if conn_ok else "失敗")
        if not conn_ok:
            logger.error("無法建立 Supabase 連線，終止其餘驗證步驟")
            logger.info("====================================")
            logger.info("系統驗證總結: 【未通過 (連線失敗)】")
            logger.info("====================================")
            return False

        # 2. 檢查資料表
        logger.info("2. 檢查核心資料表:")
        tables_ok = self.check_tables()
        logger.info("  資料表完整性: %s", "通過" if tables_ok else "未通過")

        # 3. 檢查 RPC
        logger.info("3. 檢查 RPC 向量檢索函式:")
        rpcs_ok = self.check_rpcs()
        logger.info("  RPC 向量函式功能: %s", "通過" if rpcs_ok else "未通過")

        # 4. 檢查種子資料存在性
        logger.info("4. 檢查種子資料存在性:")
        client = self._manager.get_client()
        seed_verified = False
        if client is not None:
            try:
                res_status = client.table(self._config.supabase.vehicle_status_table).select("*").eq("vehicle_id", self._vehicle_id).execute()
                sample_scene_id = "99999999-9999-9999-9999-999999999999"
                res_scene = client.table(self._config.supabase.scene_logs_table).select("*").eq("scene_id", sample_scene_id).execute()
                
                if res_status.data and res_scene.data:
                    logger.info("  [OK] 預設車輛狀態與種子場景已正確寫入資料庫")
                    seed_verified = True
                else:
                    logger.warning("  [WARNING] 未在資料庫中檢測到完整的種子資料，可能需要執行 --seed")
            except Exception as exc:
                logger.error("  [FAIL] 查詢種子資料失敗: %s", exc)

        overall_ok = conn_ok and tables_ok and rpcs_ok and seed_verified
        logger.info("====================================")
        logger.info("系統驗證總結: %s", "【完美通過】" if overall_ok else "【有項目未通過，請檢查日誌】")
        logger.info("====================================")
        return overall_ok


# ════════════════════════════════════════════════════════════════
# CLI 入口
# ════════════════════════════════════════════════════════════════

def _main() -> None:
    """Supabase 初始化與驗證 CLI 入口。"""
    import argparse

    parser = argparse.ArgumentParser(description="MA-VLNA Supabase 初始化與維護工具")
    parser.add_argument("--check", action="store_true", help="僅檢查 Supabase 連線與資料表是否存在")
    parser.add_argument("--seed", action="store_true", help="寫入預設車輛狀態與範例場景/軌跡種子資料")
    parser.add_argument("--verify", action="store_true", help="執行全面系統功能驗證 (連線、資料表、RPC、種子資料)")
    parser.add_argument("--dry-run", action="store_true", help="模擬執行，不進行任何資料庫與儲存桶寫入")
    parser.add_argument("--all", action="store_true", help="執行完整初始化流程 (建立儲存桶、寫入種子資料與執行驗證)")

    args = parser.parse_args()

    # 設定日誌
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)-30s | %(levelname)-7s | %(message)s",
    )
    logger.info("═══ MA-VLNA Supabase 初始化與維護工具 ═══")

    # 若無指定特定操作，預設為 --all
    if not (args.check or args.seed or args.verify or args.all):
        logger.info("未指定特定操作，預設執行 --all")
        args.all = True

    initializer = SupabaseInitializer()
    dry_run = args.dry_run

    if args.check:
        logger.info("▶ 模式: 檢查連線與資料表...")
        conn = initializer._manager.health_check()
        logger.info("連線狀態: %s", "成功" if conn else "失敗 (或為 Mock 模式)")
        if conn:
            initializer.check_tables()
            initializer.check_rpcs()

    elif args.seed:
        logger.info("▶ 模式: 寫入測試與車輛狀態種子資料...")
        initializer.seed_sample_data(dry_run=dry_run)

    elif args.verify:
        logger.info("▶ 模式: 執行全面功能驗證...")
        initializer.verify_all()

    elif args.all:
        logger.info("▶ 模式: 執行完整初始化與驗證...")
        
        # 1. 記錄 Migration SQL
        logger.info("步驟 1/4: 讀取 Migration SQL...")
        initializer.run_migrations()

        # 2. 建立 Storage Bucket
        logger.info("步驟 2/4: 建立 Storage Bucket...")
        if dry_run:
            logger.info("[DRY-RUN] 跳過 Storage Bucket 建立")
        else:
            bucket_ok = initializer.create_storage_bucket()
            logger.info("Storage Bucket: %s", "成功" if bucket_ok else "失敗")

        # 3. 寫入種子資料
        logger.info("步驟 3/4: 寫入種子資料...")
        initializer.seed_sample_data(dry_run=dry_run)

        # 4. 驗證
        logger.info("步驟 4/4: 執行全面功能驗證...")
        initializer.verify_all()

    logger.info("═══ 結束 Supabase 初始化與維護工具 ═══")


if __name__ == "__main__":
    _main()

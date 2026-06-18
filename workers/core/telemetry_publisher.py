"""
遙測發佈模組 — 透過非阻塞 asyncio 佇列將遙測資料批次寫入 Supabase。

功能：
  - publish_status: 發佈車輛狀態
  - publish_scene_log: 發佈場景日誌
  - publish_trigger_event: 發佈觸發事件
  - publish_telemetry: 發佈通用遙測條目
  - flush: 強制寫入待處理批次
  - start / stop: 生命週期管理
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Literal

from .config import AgentConfig, TelemetryConfig, TelemetryEntry
from .supabase_client import SupabaseManager

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# 遙測發佈器
# ════════════════════════════════════════════════════════════════

class TelemetryPublisher:
    """
    遙測發佈器 — 非同步批次寫入 Supabase。

    使用 asyncio.Queue 收集遙測條目，由背景協程定期批次寫入，
    避免阻塞主迴圈。

    生命週期：
        publisher = TelemetryPublisher()
        await publisher.start()
        ...
        await publisher.stop()
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        supabase_manager: SupabaseManager | None = None,
    ) -> None:
        cfg = config or AgentConfig.load()
        self._telemetry_cfg: TelemetryConfig = cfg.telemetry
        self._supabase_cfg = cfg.supabase
        self._vehicle_id: str = cfg.agent_id
        self._manager = supabase_manager or SupabaseManager(cfg.supabase)

        # 非同步佇列（加上限，預設為 batch_size * 100，最低 1000）
        max_size = max(1000, self._telemetry_cfg.batch_size * 100)
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_size)

        # 背景寫入任務
        self._writer_task: asyncio.Task[None] | None = None
        self._running: bool = False

        logger.info(
            "TelemetryPublisher 初始化: interval=%.1fs, batch_size=%d, "
            "async_writes=%s",
            self._telemetry_cfg.publish_interval_sec,
            self._telemetry_cfg.batch_size,
            self._telemetry_cfg.async_writes,
        )

    # ── 生命週期 ────────────────────────────────────────────────

    async def start(self) -> None:
        """啟動背景批次寫入協程。"""
        if self._running:
            logger.warning("TelemetryPublisher 已經在執行中")
            return
        self._running = True
        self._writer_task = asyncio.create_task(
            self._batch_writer(), name="telemetry-batch-writer"
        )
        logger.info("TelemetryPublisher 背景寫入已啟動")

    async def stop(self) -> None:
        """停止背景協程並寫入剩餘資料。"""
        self._running = False

        # 寫入佇列中剩餘資料
        await self.flush()

        if self._writer_task is not None:
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass
            self._writer_task = None

        logger.info("TelemetryPublisher 已停止")

    # ── 發佈介面 ────────────────────────────────────────────────

    def publish_status(self, vehicle_status: dict[str, Any]) -> None:
        """
        發佈車輛狀態更新。

        Args:
            vehicle_status: 車輛狀態字典，將寫入 vehicle_status 資料表。
        """
        entry = {
            "_target_table": self._supabase_cfg.vehicle_status_table,
            "_operation": "upsert",
            "vehicle_id": vehicle_status.get("vehicle_id", self._vehicle_id),
            **vehicle_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._enqueue(entry)
        logger.debug("已排入狀態更新: vehicle_id=%s", entry["vehicle_id"])

    def publish_scene_log(self, scene_log_data: dict[str, Any]) -> None:
        """
        發佈場景日誌。

        Args:
            scene_log_data: 場景日誌字典，將寫入 scene_logs 資料表。
        """
        entry = {
            "_target_table": self._supabase_cfg.scene_logs_table,
            "_operation": "insert",
            "vehicle_id": scene_log_data.get("vehicle_id", self._vehicle_id),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **scene_log_data,
        }
        self._enqueue(entry)
        logger.debug("已排入場景日誌")

    def publish_trigger_event(self, trigger_data: dict[str, Any]) -> None:
        """
        發佈觸發事件（寫入 scene_logs 並標記觸發原因）。

        Args:
            trigger_data: 包含 trigger_reason, trigger_details 等的字典。
        """
        entry = {
            "_target_table": "trigger_events",
            "_operation": "insert",
            "vehicle_id": trigger_data.get("vehicle_id", self._vehicle_id),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "trigger_reason": trigger_data.get("trigger_reason"),
            "trigger_details": trigger_data.get("trigger_details", {}),
        }
        if "scene_id" in trigger_data:
            entry["scene_id"] = trigger_data["scene_id"]
        if "trigger_score" in trigger_data:
            entry["trigger_score"] = trigger_data["trigger_score"]
            
        self._enqueue(entry)
        logger.debug(
            "已排入觸發事件: reason=%s",
            trigger_data.get("trigger_reason"),
        )

    def publish_telemetry(self, entry: TelemetryEntry) -> None:
        """
        發佈通用遙測條目。

        Args:
            entry: Pydantic TelemetryEntry 模型實例。
        """
        raw_data = entry.model_dump(exclude_none=True)
        payload_data = {k: v for k, v in raw_data.items() if k not in ("vehicle_id", "event_type", "timestamp")}
        
        data = {
            "_target_table": "telemetry_entries",
            "_operation": "insert",
            "vehicle_id": raw_data["vehicle_id"],
            "event_type": raw_data["event_type"],
            "created_at": raw_data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            "payload": payload_data,
        }
        self._enqueue(data)
        logger.debug(
            "已排入遙測: event_type=%s, vehicle_id=%s",
            entry.event_type,
            entry.vehicle_id,
        )

    # ── 強制寫入 ────────────────────────────────────────────────

    async def flush(self) -> None:
        """強制將佇列中所有待處理資料立即寫入。"""
        batch = self._drain_queue()
        if batch:
            await self._write_batch(batch)
            logger.info("flush: 已寫入 %d 筆遙測資料", len(batch))

    # ── 背景協程 ────────────────────────────────────────────────

    async def _batch_writer(self) -> None:
        """
        背景批次寫入協程 — 定期從佇列取出資料並寫入 Supabase。

        此協程在 start() 時啟動，stop() 時取消。
        """
        logger.info("背景批次寫入協程已啟動")
        while self._running:
            try:
                # 等待一個發佈間隔
                await asyncio.sleep(self._telemetry_cfg.publish_interval_sec)

                # 批次取出
                batch = self._drain_queue(
                    max_items=self._telemetry_cfg.batch_size
                )
                if batch:
                    await self._write_batch(batch)

            except asyncio.CancelledError:
                logger.debug("批次寫入協程收到取消信號")
                break
            except Exception:
                logger.exception("批次寫入協程發生例外 — 將繼續執行")
                await asyncio.sleep(1.0)  # 避免緊密迴圈

    # ── 內部輔助 ────────────────────────────────────────────────

    def _enqueue(self, data: dict[str, Any]) -> None:
        """將資料放入非同步佇列。"""
        try:
            self._queue.put_nowait(data)
        except asyncio.QueueFull:
            logger.warning("遙測佇列已滿 — 將最舊的條目寫入 fallback 並丟棄")
            # 移除最舊的一筆並寫入 fallback 後重試
            try:
                dropped = self._queue.get_nowait()
                self._write_to_fallback([dropped])
                self._queue.put_nowait(data)
            except asyncio.QueueEmpty:
                pass

    def _drain_queue(self, max_items: int | None = None) -> list[dict[str, Any]]:
        """從佇列取出資料（非阻塞）。"""
        items: list[dict[str, Any]] = []
        limit = max_items or self._telemetry_cfg.batch_size * 10
        while len(items) < limit:
            try:
                items.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return items

    async def _write_batch(self, batch: list[dict[str, Any]]) -> None:
        """
        將批次資料寫入 Supabase。

        依目標資料表分組後個別寫入，包含重試邏輯。
        """
        client = self._manager.get_client()
        if client is None:
            logger.warning(
                "Supabase 不可用 — 轉為寫入 fallback 本地檔案"
            )
            self._write_to_fallback(batch)
            return

        # 依資料表分組
        by_table: dict[str, list[dict[str, Any]]] = {}
        for item in batch:
            table = item.get("_target_table", "scene_logs")
            operation = item.get("_operation", "insert")
            key = f"{table}:{operation}"
            by_table.setdefault(key, []).append(item)

        # 逐組寫入
        for key, rows in by_table.items():
            table_name, operation = key.split(":", 1)
            
            # 建立要發送給 Supabase 的 payload，排除 _ 開頭的 metadata 欄位
            payload = []
            for r in rows:
                clean_row = {k: v for k, v in r.items() if not k.startswith("_")}
                payload.append(clean_row)

            retries = 2
            success = False
            for attempt in range(1, retries + 1):
                try:
                    if operation == "upsert":
                        # Deduplicate by vehicle_id, keeping the latest update in the batch
                        deduped = {}
                        for row in payload:
                            vid = row.get("vehicle_id")
                            if vid:
                                deduped[vid] = row
                            else:
                                # Fallback if no vehicle_id
                                deduped[str(id(row))] = row
                        upsert_payload = list(deduped.values())
                        client.table(table_name).upsert(upsert_payload).execute()
                    else:
                        client.table(table_name).insert(payload).execute()
                    logger.debug(
                        "已寫入 %d 筆至 %s (%s)",
                        len(rows),
                        table_name,
                        operation,
                    )
                    success = True
                    break
                except Exception:
                    logger.exception(
                        "寫入 %s 失敗 (嘗試 %d/%d)",
                        table_name,
                        attempt,
                        retries,
                    )
                    if attempt < retries:
                        await asyncio.sleep(0.5 * attempt)
            
            if not success:
                logger.warning("批次寫入 %s 失敗，改寫入 fallback 本地檔案", table_name)
                self._write_to_fallback(rows)

    def _write_to_fallback(self, batch: list[dict[str, Any]]) -> None:
        """將寫入失敗的遙測資料備份至本地 JSONL 檔案，防止資料遺失。"""
        import json
        from pathlib import Path

        # 用戶明確要求路徑為 runtime_logs/telemetry_fallback.jsonl
        fallback_dir = Path("runtime_logs")
        try:
            fallback_dir.mkdir(parents=True, exist_ok=True)
            fallback_file = fallback_dir / "telemetry_fallback.jsonl"
            
            with open(fallback_file, "a", encoding="utf-8") as f:
                for item in batch:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
            logger.info("已將 %d 筆遙測資料備份至 %s", len(batch), fallback_file)
        except Exception:
            logger.exception("無法寫入 fallback 遙測檔案")

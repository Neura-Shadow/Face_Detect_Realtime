"""
場景記憶檢索模組 — 透過 pgvector 餘弦相似度在 Supabase 中查詢
top-k 相似場景、判斷未知場景、取得 replay 候選並檢查感知衝突。

所有查詢使用 Supabase RPC 或原生 SQL（pgvector cosine similarity）。
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from .config import AgentConfig, MemoryConfig, SceneMemoryEntry
from .supabase_client import SupabaseManager

logger = logging.getLogger(__name__)


class SceneMemoryRetriever:
    """
    場景記憶檢索器 — 查詢 Supabase 中的 pgvector 場景向量，
    用於相似場景檢索、未知場景判定與記憶 replay。
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        supabase_manager: SupabaseManager | None = None,
    ) -> None:
        cfg = config or AgentConfig.load()
        self._memory_cfg: MemoryConfig = cfg.memory
        self._supabase_cfg = cfg.supabase
        self._manager = supabase_manager or SupabaseManager(cfg.supabase)
        self._vehicle_id = cfg.agent_id
        logger.info(
            "SceneMemoryRetriever 初始化: top_k=%d, threshold=%.2f",
            self._memory_cfg.top_k,
            self._memory_cfg.similarity_threshold,
        )

    # ── 公開介面 ────────────────────────────────────────────────

    def query_top_k(
        self,
        embedding: np.ndarray,
        k: int | None = None,
    ) -> list[SceneMemoryEntry]:
        """
        查詢與指定 embedding 最相似的前 k 筆場景記憶。

        使用 pgvector 的 cosine distance 排序。

        Args:
            embedding: 查詢向量 (768,)。
            k: 回傳筆數，預設使用 memory_cfg.top_k。

        Returns:
            依相似度降序排列的 SceneMemoryEntry 列表。
        """
        k = k or self._memory_cfg.top_k
        client = self._manager.get_client()
        if client is None:
            logger.warning("query_top_k: Supabase 不可用 — 回傳空列表")
            return []

        try:
            # 使用 Supabase RPC 呼叫 pgvector 查詢
            # 預期已在 Supabase 中建立 match_scene_memories RPC
            result = client.rpc(
                "match_scene_memories",
                {
                    "query_embedding": embedding.tolist(),
                    "match_count": k,
                    "match_threshold": 0.0,  # 回傳所有結果，由呼叫端篩選
                },
            ).execute()

            entries: list[SceneMemoryEntry] = []
            for row in (result.data or []):
                entries.append(self._row_to_entry(row))

            logger.debug("query_top_k: 回傳 %d 筆結果", len(entries))
            return entries

        except Exception:
            logger.exception("query_top_k 查詢失敗")
            return []

    def is_unknown_scene(
        self,
        embedding: np.ndarray,
        threshold: float | None = None,
    ) -> bool:
        """
        判斷當前場景是否為「未知場景」。

        策略：若 top-1 相似度低於閾值，則視為未知場景。

        Args:
            embedding: 當前場景 embedding (768,)。
            threshold: 未知場景閾值；預設使用設定值。

        Returns:
            True 表示此場景在記憶中無足夠相似的已知案例。
        """
        threshold = threshold or self._memory_cfg.similarity_threshold
        top_results = self.query_top_k(embedding, k=1)
        if not top_results:
            logger.info("is_unknown_scene: 記憶庫為空 — 視為未知場景")
            return True
        best_score = top_results[0].similarity_score
        is_unknown = best_score < threshold
        logger.debug(
            "is_unknown_scene: best_score=%.4f, threshold=%.4f → %s",
            best_score,
            threshold,
            is_unknown,
        )
        return is_unknown

    def get_replay_candidates(
        self,
        embedding: np.ndarray,
        k: int | None = None,
    ) -> list[SceneMemoryEntry]:
        """
        取得可供 replay 的記憶候選（僅限 success_flag=True 的案例）。

        Args:
            embedding: 查詢向量 (768,)。
            k: 回傳筆數。

        Returns:
            符合 replay 條件的 SceneMemoryEntry 列表。
        """
        k = k or self._memory_cfg.top_k
        client = self._manager.get_client()
        if client is None:
            logger.warning("get_replay_candidates: Supabase 不可用")
            return []

        try:
            # 呼叫專用 RPC（僅查詢 success_flag=True 的軌跡記憶）
            result = client.rpc(
                "match_trajectory_memories",
                {
                    "query_embedding": embedding.tolist(),
                    "match_count": k,
                    "match_threshold": self._memory_cfg.replay_min_similarity,
                    "only_success": self._memory_cfg.replay_require_success,
                },
            ).execute()

            entries: list[SceneMemoryEntry] = []
            for row in (result.data or []):
                entries.append(self._row_to_entry(row, is_replay=True))

            logger.debug("get_replay_candidates: 回傳 %d 筆候選", len(entries))
            return entries

        except Exception:
            logger.exception("get_replay_candidates 查詢失敗")
            return []

    def check_replay_conflict(
        self,
        replay_candidate: SceneMemoryEntry,
        current_perception: dict[str, Any],
    ) -> bool:
        """
        檢查 replay 候選與當前感知結果是否存在衝突。

        衝突定義：
          - replay 記憶中的車道狀態與目前不一致
          - replay 記憶中無障礙物但目前偵測到障礙物
          - 障礙物數量差異顯著

        Args:
            replay_candidate: replay 候選的場景記憶。
            current_perception: 當前感知結果（至少包含 lane_state, detections）。

        Returns:
            True 表示有衝突，應阻止 replay。
        """
        if not self._memory_cfg.conflict_check_enabled:
            return False

        # 取得 replay 記憶中的環境描述
        replay_summary = (replay_candidate.semantic_summary or "").lower()
        current_lane = current_perception.get("lane_state", "unknown")
        current_det_count = len(current_perception.get("detections", []))

        # 衝突規則 1：車道狀態不一致
        if current_lane == "occupied" and "clear" in replay_summary:
            logger.info(
                "replay 衝突: 記憶顯示車道暢通但目前被佔據 (scene_id=%s)",
                replay_candidate.scene_id,
            )
            return True

        # 衝突規則 2：目前偵測到大量障礙物但記憶中沒有
        if current_det_count > 5 and "no obstacle" in replay_summary:
            logger.info(
                "replay 衝突: 目前 %d 個偵測但記憶顯示無障礙物 (scene_id=%s)",
                current_det_count,
                replay_candidate.scene_id,
            )
            return True

        # 衝突規則 3：replay 行動序列包含高速前進但目前車道被佔
        if current_lane == "occupied" and replay_candidate.action_sequence:
            for step in replay_candidate.action_sequence:
                if step.action == "forward":
                    logger.info(
                        "replay 衝突: 記憶要求前進但車道被佔據 (scene_id=%s)",
                        replay_candidate.scene_id,
                    )
                    return True

        logger.debug(
            "replay 衝突檢查通過 (scene_id=%s)",
            replay_candidate.scene_id,
        )
        return False

    # ── 內部輔助 ────────────────────────────────────────────────

    @staticmethod
    def _row_to_entry(
        row: dict[str, Any],
        *,
        is_replay: bool = False,
    ) -> SceneMemoryEntry:
        """將 Supabase 查詢結果列轉為 SceneMemoryEntry。"""
        from .config import SceneActionStep

        action_seq = None
        raw_actions = row.get("action_sequence")
        if raw_actions and isinstance(raw_actions, list):
            action_seq = [
                SceneActionStep(
                    action=a.get("action", ""),
                    duration_sec=float(a.get("duration_sec", 0.0)),
                )
                for a in raw_actions
            ]

        return SceneMemoryEntry(
            scene_id=str(row.get("scene_id", row.get("memory_id", ""))),
            memory_id=str(row.get("memory_id", "")) if row.get("memory_id") else None,
            vehicle_id=str(row.get("vehicle_id", "")),
            timestamp=str(row.get("timestamp", row.get("created_at", ""))),
            similarity_score=float(row.get("similarity", row.get("similarity_score", 0.0))),
            is_replay_candidate=is_replay,
            success_flag=row.get("success_flag"),
            semantic_summary=row.get("semantic_summary"),
            thumbnail_url=row.get("thumbnail_url"),
            action_sequence=action_seq,
            outcome=row.get("outcome"),
            replay_count=int(row.get("replay_count", 0)),
            source_scene_id=str(row.get("scene_id", "")) if is_replay else None,
        )

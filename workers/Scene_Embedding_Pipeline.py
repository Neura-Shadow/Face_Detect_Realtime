"""
場景嵌入管線模組 — 對應原始 Encodeing.py。

功能：
  - 批次處理資料夾中所有影像，產生 768 維 embedding
  - 單張影像 embedding 產生
  - 將 embedding + metadata 寫入 Supabase scene_logs
  - pgvector 餘弦相似度查詢（top-k）
  - 未知場景判定
  - Replay 候選取得

原始 Encodeing.py 使用 face_recognition 產生臉部 encoding；
此模組已遷移至 CLIP / EmbeddingBackend 產生場景 embedding。

所有模型名稱、URL、Key 均從設定讀取，絕不寫死。
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .core.config import AgentConfig, SceneMemoryEntry
from .core.embedding_backend import CLIPEmbeddingBackend, EMBEDDING_DIM
from .core.supabase_client import SupabaseManager

logger = logging.getLogger(__name__)

_THIS_DIR = Path(__file__).resolve().parent



# ════════════════════════════════════════════════════════════════
# 場景嵌入管線
# ════════════════════════════════════════════════════════════════

class SceneEmbeddingPipeline:
    """
    場景嵌入管線 — 對應原始 Encodeing.py 的角色。

    整合 EmbeddingBackend（CLIP/stub）與 Supabase pgvector，
    支援批次處理、單張處理、向量寫入與相似度查詢。

    使用方式：
        pipeline = SceneEmbeddingPipeline()
        pipeline.process_folder("./images")
    """

    def __init__(self, config: AgentConfig | None = None) -> None:
        self._config = config or AgentConfig.load()
        self._backend = CLIPEmbeddingBackend(self._config.embedding)
        self._manager = SupabaseManager(self._config.supabase)
        self._vehicle_id = self._config.agent_id
        self._similarity_threshold = self._config.memory.similarity_threshold

        logger.info(
            "SceneEmbeddingPipeline 初始化: embedding_dim=%d, "
            "vehicle_id=%s",
            EMBEDDING_DIM,
            self._vehicle_id,
        )

    # ── 批次處理 ────────────────────────────────────────────────

    def process_folder(self, folder_path: str | Path, limit: int = 0, dry_run: bool = False) -> list[np.ndarray]:
        """
        批次處理資料夾中所有影像檔案。

        遍歷資料夾中的 .jpg/.jpeg/.png/.bmp 影像，
        產生 embedding 並選擇性寫入 Supabase。

        對應原始 Encodeing.py 的批次 encoding 流程。

        Args:
            folder_path: 影像資料夾路徑。
            limit: 最大處理數量 (0 表示不限制)。
            dry_run: 若為 True 則不寫入 Supabase。

        Returns:
            所有影像的 embedding 列表。
        """
        folder = Path(folder_path)
        if not folder.is_dir():
            logger.error("資料夾不存在: %s", folder)
            return []

        valid_ext = {".jpg", ".jpeg", ".png", ".bmp"}
        image_paths = sorted(
            p for p in folder.iterdir()
            if p.suffix.lower() in valid_ext
        )
        
        if limit > 0:
            image_paths = image_paths[:limit]

        if not image_paths:
            logger.warning("資料夾中無有效影像檔案: %s", folder)
            return []

        logger.info("開始批次處理: %d 張影像 ← %s", len(image_paths), folder)

        # 讀取影像
        images: list[np.ndarray] = []
        names: list[str] = []
        for img_path in image_paths:
            img = self._load_image(img_path)
            if img is not None:
                images.append(img)
                names.append(img_path.stem)
            else:
                logger.warning("影像讀取失敗，跳過: %s", img_path)

        if not images:
            logger.warning("無成功載入的影像")
            return []

        # 批次產生 embedding
        try:
            embeddings = self._backend.process_batch(images)
        except Exception:
            logger.exception("批次 embedding 產生失敗 — 改為逐張處理")
            embeddings = []
            for img in images:
                try:
                    embeddings.append(self._backend.process_single(img))
                except Exception:
                    logger.exception("單張 embedding 失敗 — 使用零向量")
                    embeddings.append(np.zeros(EMBEDDING_DIM, dtype=np.float32))

        # 寫入 Supabase（可選）
        if not dry_run:
            for name, emb in zip(names, embeddings):
                try:
                    self.write_to_supabase(
                        embedding=emb,
                        metadata={
                            "source": "batch_process",
                            "image_name": name,
                            "semantic_summary": f"批次處理影像: {name}",
                        },
                    )
                except Exception:
                    logger.exception(
                        "寫入 Supabase 失敗 (image=%s) — 繼續處理其餘影像",
                        name,
                    )
        else:
            logger.info("Dry-run 模式：跳過 Supabase 寫入")

        logger.info(
            "批次處理完成: %d/%d 張影像已產生 embedding",
            len(embeddings),
            len(image_paths),
        )
        return embeddings

    # ── 單張處理 ────────────────────────────────────────────────

    def process_single(
        self,
        image_or_path: np.ndarray | str | Path,
    ) -> np.ndarray:
        """
        計算單張影像的 embedding。

        Args:
            image_or_path: BGR numpy 影像或影像檔案路徑。

        Returns:
            shape=(768,) 的 float32 向量。
        """
        if isinstance(image_or_path, (str, Path)):
            img = self._load_image(Path(image_or_path))
            if img is None:
                logger.error("影像載入失敗: %s", image_or_path)
                return np.zeros(EMBEDDING_DIM, dtype=np.float32)
        else:
            img = image_or_path

        try:
            embedding = self._backend.process_single(img)
            logger.debug(
                "Embedding 產生完成: shape=%s, norm=%.4f",
                embedding.shape,
                float(np.linalg.norm(embedding)),
            )
            return embedding
        except Exception:
            logger.exception("Embedding 產生失敗 — 回傳零向量")
            return np.zeros(EMBEDDING_DIM, dtype=np.float32)

    # ── Supabase 寫入 ──────────────────────────────────────────

    def write_to_supabase(
        self,
        embedding: np.ndarray,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        將場景 embedding 與 metadata 寫入 Supabase scene_logs。

        Args:
            embedding: 768 維場景 embedding。
            metadata: 附加的 metadata 字典。

        Returns:
            True 表示成功，False 表示失敗。
        """
        client = self._manager.get_client()
        if client is None:
            logger.warning("write_to_supabase: Supabase 不可用")
            return False

        try:
            table_name = self._config.supabase.scene_logs_table
            payload: dict[str, Any] = {
                "vehicle_id": self._vehicle_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "embedding": embedding.tolist(),
                "metadata": metadata or {},
            }
            client.table(table_name).insert(payload).execute()
            logger.debug("Embedding 已寫入 %s", table_name)
            return True
        except Exception:
            logger.exception("write_to_supabase 失敗")
            return False

    # ── 相似度查詢 ──────────────────────────────────────────────

    def query_top_k(
        self,
        query_embedding: np.ndarray,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        查詢與指定 embedding 最相似的前 k 筆場景。

        使用 Supabase RPC 呼叫 pgvector cosine similarity 查詢。

        Args:
            query_embedding: 查詢向量 (768,)。
            k: 回傳筆數。

        Returns:
            相似度降序排列的結果列表。
        """
        client = self._manager.get_client()
        if client is None:
            logger.warning("query_top_k: Supabase 不可用")
            return []

        try:
            result = client.rpc(
                "match_scene_memories",
                {
                    "query_embedding": query_embedding.tolist(),
                    "match_count": k,
                    "match_threshold": 0.0,
                },
            ).execute()
            rows = result.data or []
            logger.debug("query_top_k: 回傳 %d 筆結果", len(rows))
            return [dict(r) for r in rows]
        except Exception:
            logger.exception("query_top_k 查詢失敗")
            return []

    # ── 未知場景判定 ────────────────────────────────────────────

    def is_unknown_scene(
        self,
        embedding: np.ndarray,
        threshold: float | None = None,
    ) -> bool:
        """
        判斷指定 embedding 是否代表未知場景。

        策略：若 top-1 相似度低於閾值，則視為未知場景。

        Args:
            embedding: 場景 embedding (768,)。
            threshold: 未知場景閾值；預設使用設定值。

        Returns:
            True 表示此場景在記憶中無足夠相似的已知案例。
        """
        thresh = threshold or self._similarity_threshold
        results = self.query_top_k(embedding, k=1)
        if not results:
            logger.info("is_unknown_scene: 記憶庫為空 — 視為未知場景")
            return True
        best_score = float(results[0].get("similarity", 0.0))
        is_unknown = best_score < thresh
        logger.debug(
            "is_unknown_scene: best_score=%.4f, threshold=%.4f → %s",
            best_score,
            thresh,
            is_unknown,
        )
        return is_unknown

    # ── Replay 候選 ─────────────────────────────────────────────

    def get_replay_candidates(
        self,
        embedding: np.ndarray,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        取得可供 replay 的記憶候選。

        使用 match_trajectory_memory RPC 查詢成功案例。

        Args:
            embedding: 查詢向量 (768,)。
            k: 回傳筆數。

        Returns:
            replay 候選列表。
        """
        client = self._manager.get_client()
        if client is None:
            logger.warning("get_replay_candidates: Supabase 不可用")
            return []

        try:
            result = client.rpc(
                "match_trajectory_memories",
                {
                    "query_embedding": embedding.tolist(),
                    "match_count": k,
                    "match_threshold": self._config.memory.replay_min_similarity,
                    "only_success": self._config.memory.replay_require_success,
                },
            ).execute()
            rows = result.data or []
            logger.debug(
                "get_replay_candidates: 回傳 %d 筆候選",
                len(rows),
            )
            return [dict(r) for r in rows]
        except Exception:
            logger.exception("get_replay_candidates 查詢失敗")
            return []

    # ── 內部輔助 ────────────────────────────────────────────────

    @staticmethod
    def _load_image(path: Path) -> np.ndarray | None:
        """載入影像檔案為 BGR numpy 陣列。"""
        try:
            import cv2
            img = cv2.imread(str(path))
            if img is None:
                return None
            return img
        except ImportError:
            # 無 OpenCV 時使用 PIL
            try:
                from PIL import Image as PILImage
                pil_img = PILImage.open(path).convert("RGB")
                rgb = np.array(pil_img)
                # RGB → BGR
                return rgb[:, :, ::-1].copy()
            except Exception:
                logger.exception("影像載入失敗 (PIL fallback): %s", path)
                return None
        except Exception:
            logger.exception("影像載入失敗: %s", path)
            return None


# ════════════════════════════════════════════════════════════════
# CLI 入口
# ════════════════════════════════════════════════════════════════

def _main() -> None:
    """從命令列引數讀取資料夾路徑，批次處理所有影像。"""
    import argparse
    parser = argparse.ArgumentParser(description="MA-VLNA Scene Embedding Pipeline")
    parser.add_argument("--folder", type=str, default="images", help="Folder containing images")
    parser.add_argument("--backend", type=str, default="clip", choices=["clip", "dummy"], help="Embedding backend type")
    parser.add_argument("--dry-run", action="store_true", help="Process without writing to database")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of images to process")
    parser.add_argument("--query-test", action="store_true", help="Test top-k query after processing")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)-30s | %(levelname)-7s | %(message)s",
    )

    folder = Path(args.folder)
    if not folder.is_absolute():
        folder = _THIS_DIR.parent / args.folder
        
    logger.info("輸入參數: folder=%s, backend=%s, dry_run=%s, limit=%d, query_test=%s",
                folder, args.backend, args.dry_run, args.limit, args.query_test)

    # 動態設定 backend
    config = AgentConfig.load()
    import dataclasses
    if args.backend == "dummy":
        config.embedding = dataclasses.replace(config.embedding, model_name="")

    pipeline = SceneEmbeddingPipeline(config=config)
    embeddings = pipeline.process_folder(folder, limit=args.limit, dry_run=args.dry_run)
    
    if args.query_test and embeddings:
        logger.info("執行 Query 測試 (使用第一張影像的 embedding)...")
        results = pipeline.query_top_k(embeddings[0], k=3)
        for i, res in enumerate(results):
            logger.info("  Rank %d: scene_id=%s, score=%.4f", i+1, res.get("scene_id"), res.get("similarity", 0.0))

    logger.info(
        "═══ 場景嵌入管線完成: %d 張影像已處理 ═══",
        len(embeddings),
    )


if __name__ == "__main__":
    _main()

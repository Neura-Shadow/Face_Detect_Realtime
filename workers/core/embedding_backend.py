"""
Embedding 後端模組 — 透過 Protocol 抽象化 embedding 提取，
支援 CLIP（open-clip-torch）與隨機 stub。

Embedding 維度固定為 768。
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

import numpy as np

from .config import AgentConfig, EmbeddingConfig

logger = logging.getLogger(__name__)

# 固定維度
EMBEDDING_DIM: int = 768

# ── 延遲匯入 open_clip ───────────────────────────────────────
try:
    import open_clip  # type: ignore[import-untyped]
    import torch
    from PIL import Image as PILImage

    _HAS_CLIP = True
except ImportError:
    _HAS_CLIP = False
    logger.info("open-clip-torch / torch 未安裝 — EmbeddingBackend 將使用隨機 stub")


# ════════════════════════════════════════════════════════════════
# Protocol 定義
# ════════════════════════════════════════════════════════════════

@runtime_checkable
class EmbeddingBackend(Protocol):
    """Embedding 後端協定 — 所有實作必須提供 process_single 與 process_batch。"""

    def process_single(self, image: np.ndarray) -> np.ndarray:
        """
        將單張影像轉為 embedding 向量。

        Args:
            image: BGR 格式 numpy 影像。

        Returns:
            shape=(768,) 的 float32 向量。
        """
        ...

    def process_batch(self, images: list[np.ndarray]) -> list[np.ndarray]:
        """
        批次處理多張影像。

        Args:
            images: BGR 格式 numpy 影像列表。

        Returns:
            每張影像對應一個 shape=(768,) 的 float32 向量。
        """
        ...


# ════════════════════════════════════════════════════════════════
# CLIP Embedding 後端
# ════════════════════════════════════════════════════════════════

class CLIPEmbeddingBackend:
    """
    使用 open-clip-torch 提取 CLIP 影像 embedding。

    模型名稱從 .env 的 EMBEDDING_MODEL_NAME 讀取，絕不寫死。
    若 open-clip-torch 未安裝，自動回退至隨機 768 維向量 stub。
    """

    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        cfg = config or AgentConfig.load().embedding
        self._dimension = cfg.dimension or EMBEDDING_DIM
        self._model_name = cfg.model_name
        self._model: object | None = None
        self._preprocess: object | None = None
        self._tokenizer: object | None = None
        self._device: str = "cpu"
        self._use_stub = True

        if _HAS_CLIP and self._model_name:
            try:
                # open_clip 格式：'ViT-L-14' + pretrained='openai'
                # 使用者可自訂，此處解析常見格式
                model_name, pretrained = self._parse_model_name(self._model_name)
                self._model, _, self._preprocess = open_clip.create_model_and_transforms(
                    model_name, pretrained=pretrained
                )
                self._device = "cuda" if torch.cuda.is_available() else "cpu"
                self._model.to(self._device)  # type: ignore[union-attr]
                self._model.eval()  # type: ignore[union-attr]
                self._use_stub = False
                logger.info(
                    "CLIP 模型已載入: %s (pretrained=%s), device=%s",
                    model_name,
                    pretrained,
                    self._device,
                )
            except Exception:
                logger.exception("CLIP 模型載入失敗 — 回退至隨機 stub")

        if self._use_stub:
            logger.info(
                "EmbeddingBackend 以 stub 模式執行（dimension=%d）",
                self._dimension,
            )

        self._rng = np.random.default_rng(42)

    # ── 公開介面 ────────────────────────────────────────────────

    def process_single(self, image: np.ndarray) -> np.ndarray:
        """
        將單張 BGR 影像轉為 768 維 embedding。

        Args:
            image: BGR 格式 numpy 影像。

        Returns:
            L2 正規化後的 float32 向量 (768,)。
        """
        if self._use_stub:
            return self._stub_embedding()

        try:
            pil_image = self._bgr_to_pil(image)
            tensor = self._preprocess(pil_image).unsqueeze(0).to(self._device)  # type: ignore
            with torch.no_grad():  # type: ignore[no-untyped-call]
                features = self._model.encode_image(tensor)  # type: ignore[union-attr]
            embedding = features.cpu().numpy().flatten().astype(np.float32)
            # L2 正規化
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
            # 確保維度正確（截斷或補零）
            return self._ensure_dimension(embedding)
        except Exception:
            logger.exception("CLIP embedding 提取失敗 — 回退至 stub")
            return self._stub_embedding()

    def process_batch(self, images: list[np.ndarray]) -> list[np.ndarray]:
        """
        批次處理多張 BGR 影像。

        Args:
            images: BGR 影像列表。

        Returns:
            embedding 向量列表。
        """
        if not images:
            return []

        if self._use_stub:
            return [self._stub_embedding() for _ in images]

        try:
            pil_images = [self._bgr_to_pil(img) for img in images]
            tensors = torch.stack(  # type: ignore[no-untyped-call]
                [self._preprocess(img) for img in pil_images]  # type: ignore
            ).to(self._device)
            with torch.no_grad():  # type: ignore[no-untyped-call]
                features = self._model.encode_image(tensors)  # type: ignore[union-attr]
            embeddings_np = features.cpu().numpy().astype(np.float32)
            result: list[np.ndarray] = []
            for emb in embeddings_np:
                norm = np.linalg.norm(emb)
                if norm > 0:
                    emb = emb / norm
                result.append(self._ensure_dimension(emb))
            return result
        except Exception:
            logger.exception("CLIP 批次 embedding 失敗 — 回退至 stub")
            return [self._stub_embedding() for _ in images]

    # ── 內部輔助 ────────────────────────────────────────────────

    def _stub_embedding(self) -> np.ndarray:
        """產生隨機 768 維向量（L2 正規化）作為 stub。"""
        vec = self._rng.standard_normal(self._dimension).astype(np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    def _ensure_dimension(self, embedding: np.ndarray) -> np.ndarray:
        """確保 embedding 維度為 self._dimension（截斷或零填充）。"""
        if embedding.shape[0] == self._dimension:
            return embedding
        if embedding.shape[0] > self._dimension:
            return embedding[: self._dimension]
        padded = np.zeros(self._dimension, dtype=np.float32)
        padded[: embedding.shape[0]] = embedding
        return padded

    @staticmethod
    def _bgr_to_pil(image: np.ndarray) -> "PILImage.Image":
        """BGR numpy 影像轉 PIL RGB Image。"""
        import cv2
        from PIL import Image as PILImage

        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        return PILImage.fromarray(rgb)

    @staticmethod
    def _parse_model_name(name: str) -> tuple[str, str]:
        """
        解析 EMBEDDING_MODEL_NAME 字串。

        支援格式：
          - "openai/clip-vit-large-patch14" → ("ViT-L-14", "openai")
          - "ViT-L-14::openai"             → ("ViT-L-14", "openai")
          - "ViT-L-14"                     → ("ViT-L-14", "openai")
        """
        # 格式 1：HuggingFace 風格 → 映射
        hf_map: dict[str, tuple[str, str]] = {
            "openai/clip-vit-large-patch14": ("ViT-L-14", "openai"),
            "openai/clip-vit-base-patch32": ("ViT-B-32", "openai"),
            "openai/clip-vit-base-patch16": ("ViT-B-16", "openai"),
        }
        if name.lower() in hf_map:
            return hf_map[name.lower()]

        # 格式 2：以 "::" 分隔
        if "::" in name:
            parts = name.split("::", 1)
            return parts[0], parts[1]

        # 預設
        return name, "openai"

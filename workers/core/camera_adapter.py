"""
攝影機適配器模組 — 透過 Protocol / ABC 抽象化影像來源，
支援 OpenCV 攝影機、影片檔案與模擬器（Isaac Sim / ROS2）。

此設計對應原始 main.py 中 ``cv2.VideoCapture(0)`` 的角色，
但提供可置換的介面以適配不同影像來源。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

import numpy as np

from .config import CameraConfig

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# Protocol 定義 — 所有攝影機適配器必須實作
# ════════════════════════════════════════════════════════════════

@runtime_checkable
class CameraAdapter(Protocol):
    """攝影機適配器協定 — 定義統一的影像擷取介面。"""

    def open(self) -> bool:
        """開啟攝影機 / 影像來源。"""
        ...

    def read(self) -> tuple[bool, np.ndarray | None]:
        """
        讀取一張影像。

        Returns:
            (成功旗標, BGR 格式影像 或 None)
        """
        ...

    def release(self) -> None:
        """釋放攝影機資源。"""
        ...

    @property
    def is_opened(self) -> bool:
        """攝影機是否已開啟。"""
        ...


# ════════════════════════════════════════════════════════════════
# OpenCV 攝影機適配器 — 對應原始 main.py 的 cv2.VideoCapture(0)
# ════════════════════════════════════════════════════════════════

class OpenCVCameraAdapter:
    """
    使用 OpenCV VideoCapture 從實體攝影機擷取影像。

    對應原始 main.py::
        cap = cv2.VideoCapture(0)
        cap.set(3, 1280)
        cap.set(4, 720)
    """

    def __init__(self, config: CameraConfig | None = None) -> None:
        self._config = config or CameraConfig()
        self._cap: "cv2.VideoCapture | None" = None  # type: ignore[name-defined]
        self._opened: bool = False

    def open(self) -> bool:
        """開啟攝影機，設定解析度。"""
        try:
            import cv2

            source = self._config.source
            # 嘗試將 source 轉為整數索引（如 "0"）
            try:
                source_int = int(source)
                self._cap = cv2.VideoCapture(source_int)
            except ValueError:
                self._cap = cv2.VideoCapture(source)

            if self._cap is not None and self._cap.isOpened():
                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._config.width)
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._config.height)
                self._opened = True
                logger.info(
                    "OpenCV 攝影機已開啟: source=%s, %dx%d",
                    self._config.source,
                    self._config.width,
                    self._config.height,
                )
            else:
                logger.error("無法開啟攝影機: source=%s", self._config.source)
                self._opened = False
        except ImportError:
            logger.error("opencv-python 未安裝 — OpenCVCameraAdapter 無法使用")
            self._opened = False
        except Exception:
            logger.exception("開啟攝影機時發生例外")
            self._opened = False
        return self._opened

    def read(self) -> tuple[bool, np.ndarray | None]:
        """讀取一張影像。"""
        if self._cap is None or not self._opened:
            return False, None
        success, frame = self._cap.read()
        if not success:
            logger.warning("攝影機讀取失敗")
            return False, None
        return True, frame

    def release(self) -> None:
        """釋放攝影機資源。"""
        if self._cap is not None:
            self._cap.release()
            self._opened = False
            logger.info("OpenCV 攝影機已釋放")

    @property
    def is_opened(self) -> bool:
        return self._opened


# ════════════════════════════════════════════════════════════════
# 影片檔案適配器
# ════════════════════════════════════════════════════════════════

class VideoCameraAdapter:
    """
    從影片檔案逐幀讀取影像，用於離線測試或 replay 驗證。
    """

    def __init__(self, video_path: str) -> None:
        self._video_path = video_path
        self._cap: "cv2.VideoCapture | None" = None  # type: ignore[name-defined]
        self._opened: bool = False

    def open(self) -> bool:
        """開啟影片檔案。"""
        try:
            import cv2

            self._cap = cv2.VideoCapture(self._video_path)
            if self._cap.isOpened():
                self._opened = True
                logger.info("影片已開啟: %s", self._video_path)
            else:
                logger.error("無法開啟影片: %s", self._video_path)
                self._opened = False
        except ImportError:
            logger.error("opencv-python 未安裝")
            self._opened = False
        except Exception:
            logger.exception("開啟影片時發生例外")
            self._opened = False
        return self._opened

    def read(self) -> tuple[bool, np.ndarray | None]:
        """讀取下一幀影像。"""
        if self._cap is None or not self._opened:
            return False, None
        success, frame = self._cap.read()
        if not success:
            logger.info("影片讀取完畢或失敗")
            return False, None
        return True, frame

    def release(self) -> None:
        """釋放影片資源。"""
        if self._cap is not None:
            self._cap.release()
            self._opened = False
            logger.info("影片資源已釋放")

    @property
    def is_opened(self) -> bool:
        return self._opened


# ════════════════════════════════════════════════════════════════
# 模擬器適配器（Isaac Sim / ROS2 stub）
# ════════════════════════════════════════════════════════════════

class SimulatorCameraAdapter:
    """
    模擬器攝影機 stub — 用於 Isaac Sim / ROS2 整合。

    目前回傳隨機雜訊影像以供管線整合測試。
    TODO: 接入 Isaac Sim Camera Sensor API 或 ROS2 image_transport。
    """

    def __init__(
        self,
        width: int = 1280,
        height: int = 720,
        *,
        seed: int | None = None,
    ) -> None:
        self._width = width
        self._height = height
        self._opened = False
        self._rng = np.random.default_rng(seed)

    def open(self) -> bool:
        """模擬開啟模擬器攝影機。"""
        self._opened = True
        logger.info(
            "SimulatorCameraAdapter 已開啟（stub 模式, %dx%d）",
            self._width,
            self._height,
        )
        return True

    def read(self) -> tuple[bool, np.ndarray]:
        """回傳隨機雜訊影像（stub）。"""
        if not self._opened:
            return False, np.empty(0, dtype=np.uint8)
        frame = self._rng.integers(
            0, 256, size=(self._height, self._width, 3), dtype=np.uint8
        )
        return True, frame

    def release(self) -> None:
        """釋放模擬器資源。"""
        self._opened = False
        logger.info("SimulatorCameraAdapter 已釋放")

    @property
    def is_opened(self) -> bool:
        return self._opened

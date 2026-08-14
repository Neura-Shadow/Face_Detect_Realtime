"""
模擬器適配器模組 — 透過 Protocol / ABC 抽象化動作執行目標，
支援 Dummy（日誌輸出）、ROS2 與 Isaac Sim。

使用方式：
    adapter = DummySimulatorAdapter()
    success = await adapter.execute(planner_action)
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from .config import PlannerAction

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# Protocol 定義
# ════════════════════════════════════════════════════════════════

@runtime_checkable
class SimulatorAdapter(Protocol):
    """
    模擬器適配器協定 — 所有模擬器後端必須實作 execute()。

    execute() 接收 PlannerAction 並在模擬環境中執行，
    回傳 True 表示成功，False 表示執行失敗。
    """

    async def execute(self, action: PlannerAction) -> bool:
        """
        在模擬環境中執行規劃動作。

        Args:
            action: 規劃器產生並已通過安全閘門的動作。

        Returns:
            True 表示動作成功執行，False 表示失敗。
        """
        ...


# ════════════════════════════════════════════════════════════════
# Dummy 適配器（日誌輸出，用於測試與離線開發）
# ════════════════════════════════════════════════════════════════

class DummySimulatorAdapter:
    """
    虛擬模擬器適配器 — 將動作寫入日誌並回傳成功。

    不進行任何實際動作執行，適合：
      - 管線整合測試
      - 離線開發與除錯
      - CI/CD 管道驗證
    """

    def __init__(self) -> None:
        self._execution_count: int = 0
        logger.info("DummySimulatorAdapter 初始化（stub 模式）")

    async def execute(self, action: PlannerAction) -> bool:
        """
        模擬執行動作 — 僅記錄日誌。

        Args:
            action: 規劃器動作。

        Returns:
            永遠回傳 True。
        """
        self._execution_count += 1
        logger.info(
            "[Dummy] 執行動作 #%d: plan_id=%s, source=%s, "
            "waypoints=%d, actions=%d",
            self._execution_count,
            action.plan_id,
            action.source,
            len(action.waypoints),
            len(action.action_sequence),
        )

        # 逐步記錄動作序列
        for i, step in enumerate(action.action_sequence):
            logger.info(
                "[Dummy]   step %d: action=%s, duration=%.2fs, speed=%.2f m/s",
                i,
                step.action,
                step.duration_sec,
                step.speed_mps or 0.0,
            )

        # 模擬非同步延遲（極短，僅讓出控制權）
        await asyncio.sleep(0.01)

        logger.info("[Dummy] 動作執行完成: plan_id=%s", action.plan_id)
        return True

    @property
    def execution_count(self) -> int:
        """累計已執行動作數量。"""
        return self._execution_count


# ════════════════════════════════════════════════════════════════
# ROS2 模擬器適配器 stub
# ════════════════════════════════════════════════════════════════

class ROS2SimulatorAdapter:
    """
    ROS2 模擬器適配器 — 透過 ROS2 topic / action 發布規劃動作。

    TODO: 實作 rclpy Publisher，將 PlannerAction 轉為
          geometry_msgs/Twist 或 nav2_msgs/NavigateToPose。
    """

    def __init__(self) -> None:
        logger.warning(
            "ROS2SimulatorAdapter 尚未實作 — 請整合 rclpy 後替換"
        )

    async def execute(self, action: PlannerAction) -> bool:
        """
        透過 ROS2 發布動作。

        Raises:
            NotImplementedError: 此適配器尚未實作。
        """
        raise NotImplementedError(
            "ROS2SimulatorAdapter.execute() 尚未實作 — "
            "請安裝 rclpy 並實作 topic publisher。"
            f" (plan_id={action.plan_id})"
        )


# ════════════════════════════════════════════════════════════════
# Isaac Sim 模擬器適配器 stub
# ════════════════════════════════════════════════════════════════

class IsaacSimAdapter:
    """
    NVIDIA Isaac Sim 適配器 — 透過 Isaac Sim Python API 執行動作。

    TODO: 實作 omni.isaac.core API 呼叫，將 PlannerAction 轉為
          Articulation Controller 指令。
    """

    def __init__(self) -> None:
        logger.warning(
            "IsaacSimAdapter 尚未實作 — 請整合 omni.isaac.core 後替換"
        )

    async def execute(self, action: PlannerAction) -> bool:
        """
        透過 Isaac Sim API 執行動作。

        Raises:
            NotImplementedError: 此適配器尚未實作。
        """
        raise NotImplementedError(
            "IsaacSimAdapter.execute() 尚未實作 — "
            "請安裝 Isaac Sim Python 套件並實作 Articulation 控制。"
            f" (plan_id={action.plan_id})"
        )

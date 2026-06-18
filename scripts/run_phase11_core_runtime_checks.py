"""
Phase 11 Core Runtime Verification.

此檢查不需要真實 CARLA server，但會使用 fake CARLA adapter 跑過
`CarlaClosedLoopAgent` 的核心 runtime path：

1. fake CARLA tick -> RGB frame
2. EdgePerception
3. TriggerPolicy
4. local planner 或 LocalStub VLM
5. SafetyGate
6. PlannerAction -> fake CARLA control execution
7. TelemetryPublisher flush / fallback

目標是把狀態從：
  "Phase 11 Partial Pass — CARLA integration path prepared; fallback verified"
推進到：
  "Phase 11 Core Runtime Pass — closed-loop orchestration verified with fake CARLA runtime"
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.CARLA_Closed_Loop_Agent import CarlaClosedLoopAgent
from workers.core.carla_adapter import CarlaFrame
from workers.core.config import AgentConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("Phase11CoreRuntimeVerifier")


class FakeCarlaClientAdapter:
    """不依賴 CARLA server 的 minimal CARLA client fake。"""

    def __init__(self, width: int = 320, height: int = 180) -> None:
        self.width = width
        self.height = height
        self.setup_called = False
        self.close_called = False
        self.tick_count = 0

    def setup(self) -> None:
        self.setup_called = True

    def tick(self) -> CarlaFrame:
        self.tick_count += 1
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        # 讓每個 frame 有一點可見差異，避免全程固定畫面。
        frame[:, :, 1] = (self.tick_count * 25) % 255
        ego_x = float(self.tick_count) * 0.5
        return CarlaFrame(
            frame_id=self.tick_count,
            timestamp=float(self.tick_count) * 0.05,
            image_bgr=frame,
            ego_state={
                "location": {"x": ego_x, "y": 0.0, "z": 0.0},
                "rotation": {"pitch": 0.0, "yaw": 0.0, "roll": 0.0},
                "speed_mps": 1.0,
                "control": {"throttle": 0.1, "steer": 0.0, "brake": 0.0, "reverse": False},
            },
        )

    def close(self) -> None:
        self.close_called = True


class RecordingControlAdapter:
    """記錄 PlannerAction，模擬 CARLA VehicleControl 成功執行。"""

    def __init__(self) -> None:
        self.executed_actions: list[Any] = []

    async def execute(self, action: Any) -> bool:
        self.executed_actions.append(action)
        await asyncio.sleep(0)
        return True


def _base_test_config() -> AgentConfig:
    config = AgentConfig.load()
    perception = dataclasses.replace(config.perception, backend="dummy", model_name="dummy")
    supabase = dataclasses.replace(config.supabase, url="", key="")
    telemetry = dataclasses.replace(config.telemetry, publish_interval_sec=0.1, batch_size=4)
    vlm = dataclasses.replace(
        config.vlm,
        provider="local_stub",
        timeout_sec=2.0,
        confidence_threshold=0.4,
    )
    return dataclasses.replace(
        config,
        mode="carla",
        agent_id="phase11-runtime-test",
        main_loop_hz=20,
        supabase=supabase,
        perception=perception,
        telemetry=telemetry,
        vlm=vlm,
    )


async def _run_local_planner_path() -> None:
    """驗證不啟用 VLM 時，closed-loop 仍會完成感知、規劃、控制。"""
    base = _base_test_config()
    config = dataclasses.replace(
        base,
        trigger=dataclasses.replace(base.trigger, force_interval_frames=0),
    )
    fake_carla = FakeCarlaClientAdapter()
    fake_control = RecordingControlAdapter()
    agent = CarlaClosedLoopAgent(
        config=config,
        enable_vlm=False,
        carla_adapter=fake_carla,
        control_adapter=fake_control,
    )

    await agent.run(max_steps=3)

    assert fake_carla.setup_called, "fake CARLA setup() was not called"
    assert fake_carla.close_called, "fake CARLA close() was not called"
    assert fake_carla.tick_count == 3, f"expected 3 ticks, got {fake_carla.tick_count}"
    assert len(fake_control.executed_actions) == 3, "expected one control action per tick"
    assert all(a.validated for a in fake_control.executed_actions), "all planner actions should be validated"
    logger.info("Local planner runtime path passed")


async def _run_vlm_semantic_path() -> None:
    """驗證啟用 VLM 時，LocalStub VLM 可被 TriggerPolicy 觸發並產生 action。"""
    base = _base_test_config()
    config = dataclasses.replace(
        base,
        trigger=dataclasses.replace(
            base.trigger,
            force_interval_frames=1,
            cooldown_sec=0.0,
        ),
    )
    fake_carla = FakeCarlaClientAdapter()
    fake_control = RecordingControlAdapter()
    agent = CarlaClosedLoopAgent(
        config=config,
        enable_vlm=True,
        carla_adapter=fake_carla,
        control_adapter=fake_control,
    )

    await agent.run(max_steps=2)

    assert fake_carla.tick_count == 2, f"expected 2 ticks, got {fake_carla.tick_count}"
    assert len(fake_control.executed_actions) == 2, "expected VLM-path control actions"
    sources = {a.source for a in fake_control.executed_actions}
    assert (
        "semantic_planner" in sources or "safe_stop" in sources
    ), f"expected semantic planner or safe stop action, got {sources}"
    logger.info("VLM semantic runtime path passed: sources=%s", sorted(sources))


async def _async_main() -> None:
    await _run_local_planner_path()
    await _run_vlm_semantic_path()
    logger.info("Phase 11 core runtime verification passed")
    print("phase11 core runtime verification passed")


def main() -> int:
    asyncio.run(_async_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

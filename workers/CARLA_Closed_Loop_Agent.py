"""
Phase 11 — CARLA closed-loop integration runner.

目標管線：
    CARLA server
    -> CARLA client adapter
    -> ego vehicle spawn
    -> RGB camera sensor
    -> MA-VLNA EdgePerception
    -> TriggerPolicy / VLMReasoner optional
    -> SafetyGate
    -> PlannerAction
    -> CARLA VehicleControl
    -> world.tick()
    -> telemetry / replay logs

此 runner 不追求 CARLA Leaderboard；它是 v0.5 架構進入 closed-loop
simulation 的第一個穩定原型。
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import logging
import signal
from datetime import datetime, timezone
from typing import Any

from .core.carla_adapter import (
    CarlaClientAdapter,
    CarlaDependencyError,
    CarlaFrame,
    CarlaVehicleControlAdapter,
)
from .core.carla_metrics import CarlaRuntimeMetrics
from .core.carla_route_metrics import CarlaRouteProgressTracker
from .core.config import AgentConfig, PlannerAction, TelemetryEntry, VLMOutput
from .core.edge_perception import EdgePerception, PerceptionResult
from .core.safety_gate import GateResult, SafetyGate
from .core.semantic_planner import SemanticPlanner
from .core.telemetry_publisher import TelemetryPublisher
from .core.trigger_policy import TriggerPolicy, TriggerResult
from .core.vlm_reasoner import (
    GemmaReasoner,
    LocalStubVLMReasoner,
    OpenAICompatibleVLMReasoner,
    VLMReasoner,
)

logger = logging.getLogger(__name__)


class CarlaClosedLoopAgent:
    """
    CARLA closed-loop orchestrator.

    與 `AutonomousDrivingAgent` 相比，這裡的 camera / actuator 都來自 CARLA；
    但 EdgePerception、TriggerPolicy、VLMReasoner、SafetyGate、SemanticPlanner、
    TelemetryPublisher 仍沿用 v0.5 核心模組。
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        *,
        enable_vlm: bool = False,
        carla_adapter: Any | None = None,
        control_adapter: Any | None = None,
        telemetry_publisher: TelemetryPublisher | None = None,
        runtime_metrics: CarlaRuntimeMetrics | None = None,
        route_tracker: CarlaRouteProgressTracker | None = None,
        enable_metric_sensors: bool = False,
        require_sensors: bool = False,
    ) -> None:
        self._config = config or AgentConfig.load()
        self._enable_vlm = enable_vlm
        self._running = False
        self._frame_count = 0
        self._runtime_metrics = runtime_metrics
        self._route_tracker = route_tracker
        self._enable_metric_sensors = enable_metric_sensors
        self._require_sensors = require_sensors

        self._carla = carla_adapter or CarlaClientAdapter(self._config.carla)
        self._control_adapter = control_adapter or CarlaVehicleControlAdapter(
            self._carla,
            self._config.carla,
        )
        self._perception = EdgePerception(self._config)
        self._trigger_policy = TriggerPolicy(self._config)
        self._safety_gate = SafetyGate(self._config)
        self._planner = SemanticPlanner(self._config)
        self._telemetry = telemetry_publisher or TelemetryPublisher(self._config)
        self._vlm_reasoner = self._build_reasoner()

    async def run(self, max_steps: int | None = None) -> None:
        """連線 CARLA 並執行 closed-loop simulation。"""
        logger.info("Phase 11 CARLA closed-loop runner starting...")
        self._running = True

        try:
            if self._runtime_metrics is not None:
                self._runtime_metrics.steps_requested = int(max_steps or 0)
                self._runtime_metrics.record_event("setup_started", None)
                self._carla.setup(
                    metrics=self._runtime_metrics,
                    enable_metric_sensors=self._enable_metric_sensors,
                    require_sensors=self._require_sensors,
                )
            else:
                self._carla.setup()
            if self._route_tracker is not None:
                self._route_tracker.load_from_adapter(self._carla)
        except CarlaDependencyError as exc:
            logger.error("%s", exc)
            raise

        await self._telemetry.start()

        steps_run = 0
        try:
            while self._running:
                if max_steps is not None and steps_run >= max_steps:
                    logger.info("達到指定 CARLA closed-loop 步數: %d", max_steps)
                    break

                await self._execute_cycle()
                steps_run += 1

        except asyncio.CancelledError:
            logger.info("CARLA closed-loop runner cancelled")
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """釋放 CARLA actors 並 flush telemetry。"""
        if not self._running:
            return
        self._running = False
        try:
            await self._telemetry.stop()
        finally:
            self._carla.close()
            if self._runtime_metrics is not None:
                self._runtime_metrics.mark_cleanup_completed()
        logger.info("Phase 11 CARLA closed-loop runner stopped")

    async def _execute_cycle(self) -> None:
        """
        單一 closed-loop tick。

        注意：CARLA control 會在本輪尾端套用，實際物理效果會在下一次
        world.tick() 被反映，這是 CARLA synchronous mode 的正常節奏。
        """
        self._frame_count += 1

        carla_frame = self._carla.tick()
        if self._runtime_metrics is not None:
            self._runtime_metrics.record_rgb_frame(self._frame_count, frame_id=carla_frame.frame_id)
            self._runtime_metrics.record_world_tick(self._frame_count, frame_id=carla_frame.frame_id)
        perception = self._perception.process(
            carla_frame.image_bgr,
            frame_id=carla_frame.frame_id,
        )

        trigger_result = self._evaluate_trigger(perception)
        if trigger_result.should_trigger:
            self._publish_trigger(trigger_result)

        if trigger_result.should_trigger and self._enable_vlm:
            action, vlm_output, gate_result = await self._plan_with_optional_vlm(
                carla_frame,
                perception,
                trigger_result,
            )
        else:
            if trigger_result.should_trigger and not self._enable_vlm:
                logger.info(
                    "VLM trigger suppressed because --enable-vlm is not set: reason=%s",
                    trigger_result.reason,
                )
            vlm_output = None
            gate_result = None
            ego_pos = self._ego_position(carla_frame)
            action = self._planner.plan_local(perception, ego_pos)
            action = self._validate_planner_action(action)

        success = await self._control_adapter.execute(action)
        if not success:
            action = self._safety_gate.emergency_stop()
            await self._control_adapter.execute(action)

        if self._runtime_metrics is not None:
            first_step = action.action_sequence[0] if action.action_sequence else None
            planner_action = first_step.action if first_step else "none"
            self._runtime_metrics.record_control_applied(
                self._frame_count,
                planner_action=planner_action,
                plan_id=action.plan_id,
                control_success=success,
            )
            vehicle = getattr(self._carla, "ego_vehicle", None)
            self._runtime_metrics.record_vehicle_state(vehicle, self._frame_count)
            if self._route_tracker is not None:
                self._route_tracker.record_vehicle_state(vehicle, self._frame_count)

        self._publish_cycle_logs(
            carla_frame=carla_frame,
            perception=perception,
            trigger_result=trigger_result,
            action=action,
            vlm_output=vlm_output,
            gate_result=gate_result,
        )

    def _evaluate_trigger(self, perception: PerceptionResult) -> TriggerResult:
        perception_dict = {
            "raw_confidence": perception.raw_confidence,
            "tracker_id_switches": self._perception.tracker_id_switch_count,
            "detections": [d.to_dict() for d in perception.detections],
        }

        # Phase 11 先不把 Supabase memory 放進 CARLA critical path。
        # 這裡用「已知場景」預設值，避免 CARLA server 測試被資料庫狀態阻塞。
        memory_dict = {
            "is_unknown": False,
            "top_similarity": 1.0,
        }
        planner_dict = {
            "can_plan": self._planner.can_plan,
            "deadlock_count": self._planner.deadlock_count,
            "oscillation_detected": self._planner.oscillation_detected,
        }
        return self._trigger_policy.evaluate(
            perception=perception_dict,
            memory_result=memory_dict,
            planner_state=planner_dict,
            frame_count=self._frame_count,
        )

    async def _plan_with_optional_vlm(
        self,
        carla_frame: CarlaFrame,
        perception: PerceptionResult,
        trigger_result: TriggerResult,
    ) -> tuple[PlannerAction, VLMOutput | None, GateResult | None]:
        self._trigger_policy.notify_pending_start()
        try:
            context = {
                "runtime": "carla",
                "frame_id": carla_frame.frame_id,
                "ego_state": carla_frame.ego_state,
                "trigger_reason": trigger_result.reason,
                "trigger_details": trigger_result.details,
                "lane_state": perception.lane_state,
                "free_space": perception.free_space,
                "detections": [d.to_dict() for d in perception.detections],
            }
            try:
                vlm_output = await asyncio.wait_for(
                    self._vlm_reasoner.reason(carla_frame.image_bgr, context),
                    timeout=self._config.vlm.timeout_sec,
                )
            except Exception as exc:
                logger.warning("CARLA VLM path failed, using safe stop: %s", exc)
                action = self._safety_gate.emergency_stop()
                return action, None, None

            gate_result = self._safety_gate.validate_vlm_output(vlm_output)
            if gate_result.modified_action is not None:
                return gate_result.modified_action, vlm_output, gate_result
            if not gate_result.approved:
                action = self._safety_gate.emergency_stop()
                action.rejection_reason = gate_result.rejection_reason
                return action, vlm_output, gate_result

            action = self._planner.plan_with_vlm(vlm_output, perception)
            action = self._validate_planner_action(action)
            return action, vlm_output, gate_result
        finally:
            self._trigger_policy.notify_pending_end()

    def _validate_planner_action(self, action: PlannerAction) -> PlannerAction:
        gate_result = self._safety_gate.validate_planner_action(action)
        if gate_result.modified_action is not None:
            return gate_result.modified_action
        if not gate_result.approved:
            safe = self._safety_gate.emergency_stop()
            safe.rejection_reason = gate_result.rejection_reason
            return safe
        action.validated = True
        return action

    def _publish_trigger(self, trigger_result: TriggerResult) -> None:
        self._telemetry.publish_trigger_event({
            "vehicle_id": self._config.agent_id,
            "trigger_reason": trigger_result.reason,
            "trigger_details": trigger_result.details,
            "trigger_score": 1.0,
        })

    def _publish_cycle_logs(
        self,
        *,
        carla_frame: CarlaFrame,
        perception: PerceptionResult,
        trigger_result: TriggerResult,
        action: PlannerAction,
        vlm_output: VLMOutput | None,
        gate_result: GateResult | None,
    ) -> None:
        ego = carla_frame.ego_state
        location = ego.get("location", {})
        rotation = ego.get("rotation", {})

        first_step = action.action_sequence[0] if action.action_sequence else None
        self._telemetry.publish_status({
            "vehicle_id": self._config.agent_id,
            "planner_state": action.source,
            "current_speed": float(ego.get("speed_mps", 0.0)),
            "position_x": float(location.get("x", 0.0)),
            "position_y": float(location.get("y", 0.0)),
            "position_z": float(location.get("z", 0.0)),
            "heading_deg": float(rotation.get("yaw", 0.0)),
            "safe_mode": action.source == "safe_stop",
            "vlm_active": bool(vlm_output is not None),
            "current_action": first_step.action if first_step else "none",
            "last_trigger_reason": (
                trigger_result.reason if trigger_result.should_trigger else None
            ),
        })

        scene_log = {
            "vehicle_id": self._config.agent_id,
            "lane_state": perception.lane_state,
            "detections": [d.to_dict() for d in perception.detections],
            "tracks": [t.to_dict() for t in perception.tracks],
            "free_space": perception.free_space,
            "trigger_reason": trigger_result.reason if trigger_result.should_trigger else None,
            "trigger_details": trigger_result.details,
            "vlm_output": vlm_output.model_dump(exclude_none=True) if vlm_output else None,
            "planner_action": action.model_dump(exclude_none=True),
            "planner_state": action.source,
            "metadata": {
                "runtime": "carla",
                "carla_frame_id": carla_frame.frame_id,
                "carla_timestamp": carla_frame.timestamp,
                "ego_state": ego,
                "perception_backend": perception.backend,
                "perception_inference_ms": perception.inference_ms,
                "safety_gate_approved": gate_result.approved if gate_result else None,
                "safety_gate_rejection_reason": (
                    gate_result.rejection_reason if gate_result else None
                ),
            },
        }
        self._telemetry.publish_scene_log(scene_log)

        self._telemetry.publish_telemetry(TelemetryEntry(
            vehicle_id=self._config.agent_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type="planner_update",
            planner_state=action.source,
            current_speed=float(ego.get("speed_mps", 0.0)),
            heading_deg=float(rotation.get("yaw", 0.0)),
            trigger_reason=trigger_result.reason if trigger_result.should_trigger else None,
            vlm_active=bool(vlm_output is not None),
            safe_mode=action.source == "safe_stop",
            current_action=first_step.action if first_step else "none",
            details={
                "runtime": "carla",
                "frame_id": carla_frame.frame_id,
                "plan_id": action.plan_id,
            },
        ))

    def _build_reasoner(self) -> VLMReasoner:
        provider = self._config.vlm.provider.lower()
        if provider == "gemma":
            return GemmaReasoner(self._config.vlm)
        if provider == "openai_compatible":
            return OpenAICompatibleVLMReasoner(self._config.vlm)
        return LocalStubVLMReasoner()

    @staticmethod
    def _ego_position(carla_frame: CarlaFrame) -> tuple[float, float]:
        location = carla_frame.ego_state.get("location", {})
        return (
            float(location.get("x", 0.0)),
            float(location.get("y", 0.0)),
        )


def _build_config_from_args(args: argparse.Namespace) -> AgentConfig:
    config = AgentConfig.load()
    carla_cfg = dataclasses.replace(
        config.carla,
        host=args.host or config.carla.host,
        port=args.port or config.carla.port,
        town=args.town if args.town is not None else config.carla.town,
        spawn_point_index=args.spawn_point_index,
        synchronous_mode=not args.async_world,
    )
    trigger_cfg = dataclasses.replace(
        config.trigger,
        force_interval_frames=args.force_vlm_every or config.trigger.force_interval_frames,
    )
    perception_cfg = config.perception
    if args.perception_backend:
        perception_cfg = dataclasses.replace(
            perception_cfg,
            backend=args.perception_backend,
        )
    vlm_cfg = config.vlm
    if args.vlm_provider:
        vlm_cfg = dataclasses.replace(vlm_cfg, provider=args.vlm_provider)

    return dataclasses.replace(
        config,
        mode="carla",
        carla=carla_cfg,
        trigger=trigger_cfg,
        perception=perception_cfg,
        vlm=vlm_cfg,
    )


async def _async_main() -> None:
    parser = argparse.ArgumentParser(description="MA-VLNA Phase 11 CARLA closed-loop runner")
    parser.add_argument("--host", default=None, help="CARLA server host")
    parser.add_argument("--port", type=int, default=None, help="CARLA server port")
    parser.add_argument("--town", default=None, help="CARLA town/map; empty means current map")
    parser.add_argument("--spawn-point-index", type=int, default=0)
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--async-world", action="store_true", help="Disable CARLA synchronous_mode")
    parser.add_argument("--enable-vlm", action="store_true", help="Allow TriggerPolicy to call VLMReasoner")
    parser.add_argument("--force-vlm-every", type=int, default=0)
    parser.add_argument("--perception-backend", default=None, choices=["dummy", "yolo", "rtdetr"])
    parser.add_argument("--vlm-provider", default=None, choices=["local_stub", "openai_compatible", "gemma"])
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)-32s | %(levelname)-7s | %(message)s",
    )
    config = _build_config_from_args(args)
    agent = CarlaClosedLoopAgent(config=config, enable_vlm=args.enable_vlm)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(agent.shutdown()))
        except NotImplementedError:
            pass

    await agent.run(max_steps=args.steps)


def _main() -> None:
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    _main()

"""
CARLA closed-loop adapter — Phase 11 simulation bridge.

此模組把 CARLA Python API 包裝成 MA-VLNA 可使用的 optional runtime：
  - 連線 CARLA server
  - 載入 / 使用目前 world
  - spawn ego vehicle
  - 掛載 RGB camera sensor
  - 以 world.tick() 取得同步影格
  - 將 PlannerAction 轉成 CARLA VehicleControl

設計重點：
  1. CARLA 不是一般 mock/webcam 開發的硬依賴；未安裝 carla 時仍可 import。
  2. PlannerAction 只轉為低階 VehicleControl，不讓 VLM 直接控制車輛。
  3. closed-loop runner 每個 tick 都重新感知與規劃，避免一次 replay 長動作。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import queue
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .carla_metrics import CarlaRuntimeMetrics
from .config import AgentConfig, CarlaConfig, PlannerAction

logger = logging.getLogger(__name__)

try:
    import carla  # type: ignore[import-not-found]

    _HAS_CARLA = True
except ImportError:
    carla = None  # type: ignore[assignment]
    _HAS_CARLA = False


@dataclass
class CarlaFrame:
    """CARLA RGB camera 單幀資料。"""

    frame_id: int
    timestamp: float
    image_bgr: np.ndarray
    ego_state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CarlaControlCommand:
    """
    PlannerAction 轉換後的 CARLA 控制命令。

    使用 dict-like primitive fields，讓沒有 carla 套件的環境也能測試 mapping。
    """

    throttle: float = 0.0
    steer: float = 0.0
    brake: float = 0.0
    reverse: bool = False
    hand_brake: bool = False
    source_action: str = "stop"
    source_plan_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "throttle": self.throttle,
            "steer": self.steer,
            "brake": self.brake,
            "reverse": self.reverse,
            "hand_brake": self.hand_brake,
            "source_action": self.source_action,
            "source_plan_id": self.source_plan_id,
        }


class CarlaDependencyError(RuntimeError):
    """CARLA Python API 不可用時的明確錯誤。"""


class PlannerActionToCarlaControl:
    """
    將 MA-VLNA PlannerAction 映射為 CARLA VehicleControl。

    Phase 11 只執行 action_sequence 的第一步，因為 closed-loop 原型
    應在每個 world.tick() 重新感知、重新規劃，而不是一次把長序列
    blindly replay 到車輛。
    """

    def __init__(self, config: CarlaConfig | None = None) -> None:
        self._config = config or AgentConfig.load().carla

    def map_action(self, action: PlannerAction) -> CarlaControlCommand:
        """把 PlannerAction 的第一個 ActionStep 轉成低階控制命令。"""
        if not action.action_sequence:
            return CarlaControlCommand(
                brake=1.0,
                source_action="stop",
                source_plan_id=action.plan_id,
            )

        step = action.action_sequence[0]
        action_name = step.action
        speed_mps = max(0.0, float(step.speed_mps or 0.0))
        normalized_speed = min(
            1.0,
            speed_mps / max(0.1, self._config.max_control_speed_mps),
        )

        # CARLA steer: -1.0 = left, +1.0 = right.
        steer = self._steer_from_step(action_name, step.steering_deg)

        if action_name in {"stop", "wait"} or speed_mps <= 0.01:
            return CarlaControlCommand(
                throttle=0.0,
                steer=0.0,
                brake=min(1.0, self._config.brake_gain),
                reverse=False,
                source_action=action_name,
                source_plan_id=action.plan_id,
            )

        reverse = action_name == "reverse"
        throttle = min(1.0, max(0.05, normalized_speed * self._config.throttle_gain))
        return CarlaControlCommand(
            throttle=throttle,
            steer=steer,
            brake=0.0,
            reverse=reverse,
            source_action=action_name,
            source_plan_id=action.plan_id,
        )

    def _steer_from_step(self, action_name: str, steering_deg: float | None) -> float:
        if steering_deg is not None:
            raw = float(steering_deg) / 45.0
        elif action_name == "turn_left":
            raw = -0.35
        elif action_name == "turn_right":
            raw = 0.35
        else:
            raw = 0.0
        return float(max(-1.0, min(1.0, raw * self._config.steer_gain)))


class CarlaClientAdapter:
    """
    CARLA server/client adapter。

    典型 closed-loop 使用順序：
        adapter = CarlaClientAdapter()
        adapter.setup()
        frame = adapter.tick()
        adapter.apply_control(command)
        adapter.close()
    """

    def __init__(self, config: CarlaConfig | None = None) -> None:
        self._config = config or AgentConfig.load().carla
        self._client: Any | None = None
        self._world: Any | None = None
        self._original_settings: Any | None = None
        self._ego_vehicle: Any | None = None
        self._camera_sensor: Any | None = None
        self._collision_sensor: Any | None = None
        self._lane_invasion_sensor: Any | None = None
        self._metrics: CarlaRuntimeMetrics | None = None
        self._image_queue: queue.Queue[Any] = queue.Queue(maxsize=8)
        self._actors: list[Any] = []
        self._is_setup = False

    @property
    def has_carla(self) -> bool:
        return _HAS_CARLA

    @property
    def ego_vehicle(self) -> Any | None:
        """提供 metrics helper 讀取真實 CARLA vehicle state。"""
        return self._ego_vehicle

    def get_map_name(self) -> str | None:
        """讀取目前 CARLA map 名稱；僅供 runtime evidence 使用。"""
        if self._world is None:
            return None
        carla_map = self._world.get_map()
        return str(getattr(carla_map, "name", "") or "")

    def get_spawn_point_count(self) -> int:
        """回傳目前 map 的 spawn point 數量。"""
        return len(self._get_spawn_points())

    def resolve_spawn_transform(self, spawn_point_index: int) -> dict[str, Any]:
        """
        以 modulo-safe 方式解析 spawn point transform。

        Phase 11K 使用這個 read-only helper 建立固定 spawn-pair smoke route；
        不會改變 ego vehicle 或 world 狀態。
        """
        spawn_points = self._get_spawn_points()
        resolved_index = int(spawn_point_index) % len(spawn_points)
        payload = self._transform_to_dict(spawn_points[resolved_index])
        payload.update({
            "requested_index": int(spawn_point_index),
            "resolved_index": resolved_index,
            "spawn_point_count": len(spawn_points),
        })
        return payload

    def setup(
        self,
        *,
        metrics: CarlaRuntimeMetrics | None = None,
        enable_metric_sensors: bool = False,
        require_sensors: bool = False,
    ) -> None:
        """連線 CARLA、設定 world、spawn ego vehicle 與 RGB camera。"""
        if not _HAS_CARLA:
            raise CarlaDependencyError(
                "找不到 carla Python package。請先安裝與 CARLA server 版本相容的 carla wheel，"
                "或只執行不需 CARLA 的 phase11 smoke checks。"
            )

        self._metrics = metrics
        self._connect()
        self._configure_world()
        self._spawn_ego_vehicle()
        self._attach_rgb_camera()
        if enable_metric_sensors and metrics is not None:
            self.attach_metric_sensors(metrics, require_sensors=require_sensors)
        self._is_setup = True
        if metrics is not None:
            metrics.mark_setup_completed()
        logger.info("CARLA adapter setup 完成")

    def tick(self) -> CarlaFrame:
        """推進 world.tick() 並回傳 ego RGB camera frame。"""
        if not self._is_setup or self._world is None:
            raise RuntimeError("CARLA adapter 尚未 setup()")

        if self._config.synchronous_mode:
            target_frame = int(self._world.tick())
        else:
            snapshot = self._world.wait_for_tick(self._config.timeout_sec)
            target_frame = int(snapshot.frame)

        image = self._wait_for_image(target_frame)
        return CarlaFrame(
            frame_id=int(getattr(image, "frame", target_frame)),
            timestamp=float(getattr(image, "timestamp", 0.0)),
            image_bgr=self._image_to_bgr(image),
            ego_state=self.get_ego_state(),
        )

    def apply_control(self, command: CarlaControlCommand) -> None:
        """套用低階控制命令至 ego vehicle。"""
        if self._ego_vehicle is None:
            raise RuntimeError("ego vehicle 尚未建立")
        control = self._to_vehicle_control(command)
        self._ego_vehicle.apply_control(control)

    def get_ego_state(self) -> dict[str, Any]:
        """取得 ego vehicle 位置、速度、姿態與目前控制命令。"""
        if self._ego_vehicle is None:
            return {}

        transform = self._ego_vehicle.get_transform()
        velocity = self._ego_vehicle.get_velocity()
        speed_mps = math.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2)
        control = self._ego_vehicle.get_control()
        return {
            "location": {
                "x": float(transform.location.x),
                "y": float(transform.location.y),
                "z": float(transform.location.z),
            },
            "rotation": {
                "pitch": float(transform.rotation.pitch),
                "yaw": float(transform.rotation.yaw),
                "roll": float(transform.rotation.roll),
            },
            "speed_mps": float(speed_mps),
            "control": {
                "throttle": float(control.throttle),
                "steer": float(control.steer),
                "brake": float(control.brake),
                "reverse": bool(control.reverse),
            },
        }

    def close(self) -> None:
        """釋放 sensor、vehicle 並恢復 world settings。"""
        logger.info("關閉 CARLA adapter...")
        for actor in reversed(self._actors):
            try:
                if actor is not None and hasattr(actor, "stop"):
                    actor.stop()
                if actor is not None and actor.is_alive:
                    actor.destroy()
            except Exception:
                logger.exception("CARLA actor destroy 失敗")
        self._actors.clear()
        self._ego_vehicle = None
        self._camera_sensor = None
        self._collision_sensor = None
        self._lane_invasion_sensor = None

        if self._world is not None and self._original_settings is not None:
            try:
                self._world.apply_settings(self._original_settings)
            except Exception:
                logger.exception("恢復 CARLA world settings 失敗")
        self._is_setup = False

    def _connect(self) -> None:
        assert carla is not None
        self._client = carla.Client(self._config.host, self._config.port)
        self._client.set_timeout(self._config.timeout_sec)

        if self._config.town:
            current_world = self._client.get_world()
            current_map_name = str(getattr(current_world.get_map(), "name", "") or "")
            if self._map_matches_town(current_map_name, self._config.town):
                logger.info("使用目前 CARLA town: %s", current_map_name)
                self._world = current_world
            else:
                logger.info("載入 CARLA town: %s", self._config.town)
                self._world = self._client.load_world(self._config.town)
        else:
            self._world = self._client.get_world()
        logger.info("已連線 CARLA server: %s:%d", self._config.host, self._config.port)
        if self._metrics is not None:
            self._metrics.server_reachable = True
            self._metrics.record_event("carla_connected", None)

    def _configure_world(self) -> None:
        if self._world is None:
            raise RuntimeError("CARLA world 尚未初始化")
        self._original_settings = self._world.get_settings()
        settings = self._world.get_settings()
        settings.synchronous_mode = self._config.synchronous_mode
        settings.fixed_delta_seconds = self._config.fixed_delta_seconds
        settings.substepping = True
        settings.max_substep_delta_time = self._config.max_substep_delta_time
        settings.max_substeps = self._config.max_substeps
        self._world.apply_settings(settings)
        logger.info(
            "CARLA world settings: sync=%s, fixed_delta=%.3f",
            self._config.synchronous_mode,
            self._config.fixed_delta_seconds,
        )

    def _spawn_ego_vehicle(self) -> None:
        assert carla is not None
        if self._world is None:
            raise RuntimeError("CARLA world 尚未初始化")

        blueprints = self._world.get_blueprint_library()
        try:
            vehicle_bp = blueprints.find(self._config.ego_blueprint)
        except Exception:
            candidates = blueprints.filter("vehicle.*")
            if not candidates:
                raise RuntimeError("CARLA blueprint library 找不到任何 vehicle.*")
            vehicle_bp = candidates[0]
            logger.warning(
                "找不到 ego blueprint %s，改用 %s",
                self._config.ego_blueprint,
                vehicle_bp.id,
            )

        spawn_points = self._get_spawn_points()

        spawn_idx = self._config.spawn_point_index % len(spawn_points)
        spawn_point = spawn_points[spawn_idx]
        vehicle = self._world.try_spawn_actor(vehicle_bp, spawn_point)
        if vehicle is None:
            raise RuntimeError(f"ego vehicle spawn 失敗: spawn_point_index={spawn_idx}")
        vehicle.set_autopilot(False)
        self._ego_vehicle = vehicle
        self._actors.append(vehicle)
        if self._metrics is not None:
            self._metrics.ego_spawned = True
            self._metrics.record_event("ego_spawned", None, blueprint=vehicle_bp.id, spawn_index=spawn_idx)
        logger.info("ego vehicle spawned: blueprint=%s, spawn_index=%d", vehicle_bp.id, spawn_idx)

    def _attach_rgb_camera(self) -> None:
        assert carla is not None
        if self._world is None or self._ego_vehicle is None:
            raise RuntimeError("ego vehicle 尚未建立，無法掛載 camera")

        camera_bp = self._world.get_blueprint_library().find("sensor.camera.rgb")
        camera_bp.set_attribute("image_size_x", str(self._config.camera_width))
        camera_bp.set_attribute("image_size_y", str(self._config.camera_height))
        camera_bp.set_attribute("fov", str(self._config.camera_fov))

        camera_transform = carla.Transform(
            carla.Location(
                x=self._config.camera_x,
                y=self._config.camera_y,
                z=self._config.camera_z,
            ),
            carla.Rotation(pitch=self._config.camera_pitch),
        )
        sensor = self._world.spawn_actor(
            camera_bp,
            camera_transform,
            attach_to=self._ego_vehicle,
        )
        sensor.listen(self._on_camera_image)
        self._camera_sensor = sensor
        self._actors.append(sensor)
        if self._metrics is not None:
            self._metrics.record_event(
                "rgb_camera_attached",
                None,
                width=self._config.camera_width,
                height=self._config.camera_height,
                fov=self._config.camera_fov,
            )
        logger.info(
            "RGB camera attached: %dx%d fov=%.1f",
            self._config.camera_width,
            self._config.camera_height,
            self._config.camera_fov,
        )

    def attach_metric_sensors(
        self,
        metrics: CarlaRuntimeMetrics,
        *,
        require_sensors: bool = False,
    ) -> None:
        """掛載 collision / lane invasion sensors；失敗時依 require_sensors 決定是否中止。"""
        assert carla is not None
        if self._world is None or self._ego_vehicle is None:
            raise RuntimeError("ego vehicle 尚未建立，無法掛載 metric sensors")

        sensor_specs = [
            (
                "sensor.other.collision",
                "collision",
                metrics.record_collision,
                metrics.mark_collision_sensor_attached,
            ),
            (
                "sensor.other.lane_invasion",
                "lane_invasion",
                metrics.record_lane_invasion,
                metrics.mark_lane_invasion_sensor_attached,
            ),
        ]

        for blueprint_id, label, callback, mark_attached in sensor_specs:
            try:
                blueprint = self._world.get_blueprint_library().find(blueprint_id)
                sensor = self._world.spawn_actor(
                    blueprint,
                    carla.Transform(),
                    attach_to=self._ego_vehicle,
                )
                sensor.listen(callback)
                self._actors.append(sensor)
                if label == "collision":
                    self._collision_sensor = sensor
                else:
                    self._lane_invasion_sensor = sensor
                mark_attached(True)
                logger.info("CARLA metric sensor attached: %s", blueprint_id)
            except Exception as exc:
                mark_attached(False, str(exc))
                logger.warning("CARLA metric sensor attach failed: %s (%s)", blueprint_id, exc)
                if require_sensors:
                    raise RuntimeError(
                        "Phase 11J Sensor Blocked — required CARLA metric sensors could not be attached."
                    ) from exc

    def _on_camera_image(self, image: Any) -> None:
        try:
            self._image_queue.put_nowait(image)
        except queue.Full:
            try:
                _ = self._image_queue.get_nowait()
                self._image_queue.put_nowait(image)
            except queue.Empty:
                pass

    def _wait_for_image(self, target_frame: int) -> Any:
        timeout = self._config.timeout_sec
        latest_image: Any | None = None
        while True:
            image = self._image_queue.get(timeout=timeout)
            latest_image = image
            image_frame = int(getattr(image, "frame", target_frame))
            if not self._config.synchronous_mode or image_frame >= target_frame:
                return image
            logger.debug(
                "丟棄過期 camera frame: image_frame=%d, target_frame=%d",
                image_frame,
                target_frame,
            )
            if latest_image is not None and self._image_queue.empty():
                return latest_image

    def _get_spawn_points(self) -> list[Any]:
        if self._world is None:
            raise RuntimeError("CARLA world 尚未初始化")
        spawn_points = list(self._world.get_map().get_spawn_points())
        if not spawn_points:
            raise RuntimeError("目前 CARLA map 沒有 spawn points")
        return spawn_points

    @staticmethod
    def _image_to_bgr(image: Any) -> np.ndarray:
        """CARLA sensor.camera.rgb raw BGRA -> OpenCV BGR ndarray。"""
        array = np.frombuffer(image.raw_data, dtype=np.uint8)
        array = array.reshape((image.height, image.width, 4))
        return array[:, :, :3].copy()

    @staticmethod
    def _transform_to_dict(transform: Any) -> dict[str, Any]:
        location = transform.location
        rotation = transform.rotation
        return {
            "location": {
                "x": float(location.x),
                "y": float(location.y),
                "z": float(location.z),
            },
            "rotation": {
                "pitch": float(rotation.pitch),
                "yaw": float(rotation.yaw),
                "roll": float(rotation.roll),
            },
        }

    @staticmethod
    def _map_matches_town(map_name: str, town: str) -> bool:
        leaf = map_name.replace("\\", "/").split("/")[-1].lower()
        requested = town.lower()
        return leaf == requested or leaf.startswith(f"{requested}_")

    @staticmethod
    def _to_vehicle_control(command: CarlaControlCommand) -> Any:
        if carla is None:
            raise CarlaDependencyError("carla Python package 不可用")
        return carla.VehicleControl(
            throttle=float(command.throttle),
            steer=float(command.steer),
            brake=float(command.brake),
            hand_brake=bool(command.hand_brake),
            reverse=bool(command.reverse),
        )


class CarlaVehicleControlAdapter:
    """
    MA-VLNA SimulatorAdapter implementation for CARLA.

    execute() 只套用單一 VehicleControl；closed-loop runner 會在下一個 tick
    重新感知與規劃。
    """

    def __init__(
        self,
        client_adapter: CarlaClientAdapter,
        config: CarlaConfig | None = None,
    ) -> None:
        self._client_adapter = client_adapter
        self._mapper = PlannerActionToCarlaControl(config)
        self._execution_count = 0

    async def execute(self, action: PlannerAction) -> bool:
        command = self._mapper.map_action(action)
        self._client_adapter.apply_control(command)
        self._execution_count += 1
        logger.info(
            "[CARLA] control #%d: plan_id=%s action=%s throttle=%.2f steer=%.2f brake=%.2f reverse=%s",
            self._execution_count,
            command.source_plan_id,
            command.source_action,
            command.throttle,
            command.steer,
            command.brake,
            command.reverse,
        )
        await asyncio.sleep(0)
        return True


def _self_test_control_mapping() -> int:
    """不需要 carla 套件的本地 mapping smoke test。"""
    from datetime import datetime, timezone

    from .config import ActionStep

    mapper = PlannerActionToCarlaControl()
    plan = PlannerAction(
        plan_id="phase11-self-test",
        timestamp=datetime.now(timezone.utc).isoformat(),
        source="local_planner",
        action_sequence=[
            ActionStep(action="turn_left", duration_sec=1.0, speed_mps=2.0, steering_deg=-20.0),
        ],
        validated=True,
    )
    command = mapper.map_action(plan)
    assert command.throttle > 0.0
    assert command.brake == 0.0
    assert command.steer < 0.0

    stop_plan = PlannerAction(
        plan_id="phase11-stop-test",
        timestamp=datetime.now(timezone.utc).isoformat(),
        source="safe_stop",
        action_sequence=[ActionStep(action="stop", duration_sec=1.0, speed_mps=0.0)],
        validated=True,
    )
    stop = mapper.map_action(stop_plan)
    assert stop.throttle == 0.0
    assert stop.brake > 0.0
    print("CARLA control mapping self-test passed")
    return 0


def _main() -> int:
    parser = argparse.ArgumentParser(description="CARLA adapter smoke utilities")
    parser.add_argument("--self-test-control", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    if args.self_test_control:
        return _self_test_control_mapping()
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

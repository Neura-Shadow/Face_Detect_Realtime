"""
CARLA runtime smoke metrics helper.

此模組只記錄真實 CARLA runtime 的觀測資料，不做決策、不評分路線，
也不把 smoke test 解讀為 Leaderboard 或 infraction benchmark。
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CarlaRuntimeMetrics:
    """Phase 11J 真實 CARLA smoke instrumentation 狀態。"""

    steps_requested: int = 0
    steps_completed: int = 0
    setup_completed: bool = False
    cleanup_completed: bool = False
    carla_import_ok: bool = False
    server_reachable: bool = False
    ego_spawned: bool = False
    rgb_frame_received: bool = False
    control_applied: bool = False
    world_tick_advanced: bool = False

    collision_sensor_attached: bool = False
    lane_invasion_sensor_attached: bool = False
    collision_count: int = 0
    lane_invasion_count: int = 0
    speed_samples_kmh: list[float] = field(default_factory=list)
    distance_traveled_m: float = 0.0
    events: list[dict[str, Any]] = field(default_factory=list)

    _last_location: tuple[float, float, float] | None = None
    _vehicle_state_available: bool = False
    _current_step: int | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def record_event(self, event: str, step: int | None = None, **payload: Any) -> None:
        """寫入一筆 JSON-serializable event。"""
        item = {
            "timestamp_utc": _now_utc(),
            "event": event,
            "step": step,
        }
        item.update(payload)
        with self._lock:
            self.events.append(item)

    def mark_collision_sensor_attached(self, attached: bool, error: str | None = None) -> None:
        self.collision_sensor_attached = attached
        event = "collision_sensor_attached" if attached else "collision_sensor_attach_failed"
        payload = {"error": error} if error else {}
        self.record_event(event, None, **payload)

    def mark_lane_invasion_sensor_attached(self, attached: bool, error: str | None = None) -> None:
        self.lane_invasion_sensor_attached = attached
        event = "lane_invasion_sensor_attached" if attached else "lane_invasion_sensor_attach_failed"
        payload = {"error": error} if error else {}
        self.record_event(event, None, **payload)

    def record_collision(self, event: Any) -> None:
        """CARLA collision sensor callback。"""
        other_actor = getattr(event, "other_actor", None)
        other_actor_label = None
        if other_actor is not None:
            other_actor_label = getattr(other_actor, "type_id", None) or str(other_actor)
        impulse = getattr(event, "normal_impulse", None)
        impulse_norm = None
        if impulse is not None:
            impulse_norm = math.sqrt(float(impulse.x) ** 2 + float(impulse.y) ** 2 + float(impulse.z) ** 2)

        with self._lock:
            self.collision_count += 1
            step = self._current_step
        self.record_event(
            "collision",
            step,
            other_actor=other_actor_label,
            impulse_norm=impulse_norm,
        )

    def record_lane_invasion(self, event: Any) -> None:
        """CARLA lane invasion sensor callback。"""
        markings = []
        for marking in getattr(event, "crossed_lane_markings", []) or []:
            marking_type = getattr(marking, "type", None)
            markings.append(str(marking_type if marking_type is not None else marking))

        with self._lock:
            self.lane_invasion_count += 1
            step = self._current_step
        self.record_event("lane_invasion", step, lane_markings=markings)

    def record_rgb_frame(self, step: int, frame_id: int | None = None) -> None:
        self.rgb_frame_received = True
        self.record_event("rgb_frame_received", step, frame_id=frame_id)

    def record_world_tick(self, step: int, frame_id: int | None = None) -> None:
        self.world_tick_advanced = True
        self.record_event("world_tick", step, frame_id=frame_id)

    def record_control_applied(
        self,
        step: int,
        *,
        planner_action: str,
        plan_id: str,
        control_success: bool,
    ) -> None:
        self.control_applied = self.control_applied or control_success
        self.record_event(
            "control_applied",
            step,
            planner_action=planner_action,
            plan_id=plan_id,
            control_success=control_success,
        )

    def record_vehicle_state(self, vehicle: Any, step: int) -> None:
        """從 CARLA vehicle state 計算 speed 與累積距離。"""
        self._current_step = step
        try:
            transform = vehicle.get_transform()
            velocity = vehicle.get_velocity()
            location = transform.location
            current_location = (float(location.x), float(location.y), float(location.z))
            speed_mps = math.sqrt(float(velocity.x) ** 2 + float(velocity.y) ** 2 + float(velocity.z) ** 2)
            speed_kmh = speed_mps * 3.6
        except Exception as exc:
            self.record_event("vehicle_state_unavailable", step, error=str(exc))
            return

        with self._lock:
            if self._last_location is not None:
                dx = current_location[0] - self._last_location[0]
                dy = current_location[1] - self._last_location[1]
                dz = current_location[2] - self._last_location[2]
                self.distance_traveled_m += math.sqrt(dx * dx + dy * dy + dz * dz)
            self._last_location = current_location
            self.speed_samples_kmh.append(speed_kmh)
            self._vehicle_state_available = True
            self.steps_completed = max(self.steps_completed, step)

        self.record_event(
            "vehicle_state",
            step,
            speed_kmh=round(speed_kmh, 6),
            distance_traveled_m=round(self.distance_traveled_m, 6),
            location={
                "x": current_location[0],
                "y": current_location[1],
                "z": current_location[2],
            },
        )

    def mark_setup_completed(self) -> None:
        self.setup_completed = True
        self.record_event("setup_completed", None)

    def mark_cleanup_completed(self) -> None:
        self.cleanup_completed = True
        self.record_event("cleanup_completed", None)

    def to_metrics_dict(
        self,
        *,
        perception_backend: str,
        vlm_enabled: bool,
        fallback_used: bool,
        result: str,
    ) -> dict[str, Any]:
        """輸出 Phase 11J metrics.json 內容。"""
        avg_speed = None
        max_speed = None
        if self.speed_samples_kmh:
            avg_speed = sum(self.speed_samples_kmh) / len(self.speed_samples_kmh)
            max_speed = max(self.speed_samples_kmh)

        return {
            "phase": "Phase 11J",
            "metrics_scope": "real_carla_sensor_smoke_only_not_benchmark",
            "steps_requested": self.steps_requested,
            "steps_completed": self.steps_completed,
            "setup_completed": self.setup_completed,
            "cleanup_completed": self.cleanup_completed,
            "carla_import_ok": self.carla_import_ok,
            "server_reachable": self.server_reachable,
            "ego_spawned": self.ego_spawned,
            "rgb_frame_received": self.rgb_frame_received,
            "control_applied": self.control_applied,
            "world_tick_advanced": self.world_tick_advanced,
            "perception_backend": perception_backend,
            "vlm_enabled": vlm_enabled,
            "collision_sensor_attached": self.collision_sensor_attached,
            "lane_invasion_sensor_attached": self.lane_invasion_sensor_attached,
            "collision_count": self.collision_count if self.collision_sensor_attached else None,
            "lane_invasion_count": (
                self.lane_invasion_count if self.lane_invasion_sensor_attached else None
            ),
            "avg_speed_kmh": round(avg_speed, 6) if avg_speed is not None else None,
            "max_speed_kmh": round(max_speed, 6) if max_speed is not None else None,
            "distance_traveled_m": (
                round(self.distance_traveled_m, 6) if self._vehicle_state_available else None
            ),
            "fallback_used": fallback_used,
            "route_completion_verified": False,
            "infraction_benchmark_verified": False,
            "leaderboard_evaluated": False,
            "result": result,
        }

    def to_events(self, result: str) -> list[dict[str, Any]]:
        """輸出 events.jsonl 內容。"""
        events = list(self.events)
        terminal = "run_passed" if result == "passed" else "run_failed"
        events.append(
            {
                "timestamp_utc": _now_utc(),
                "event": terminal,
                "step": self.steps_completed,
            }
        )
        return events

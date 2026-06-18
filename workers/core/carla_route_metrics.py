"""
CARLA fixed-route smoke progress helper.

此模組只負責 Phase 11K-11M 的固定 spawn-pair route instrumentation。
它不控制車輛，也不把 smoke 結果解讀為 CARLA Leaderboard、
infraction benchmark 或正式 route-completion 評測。Phase 11M 只會記錄
GlobalRoutePlanner route-following evidence，實際控制仍由 runner-only adapter 執行。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .carla_metrics import CarlaRuntimeMetrics


@dataclass(frozen=True)
class RoutePoint:
    """固定 route 端點座標。"""

    x: float
    y: float
    z: float

    @classmethod
    def from_transform_dict(cls, transform: dict[str, Any]) -> "RoutePoint":
        location = transform.get("location", {})
        return cls(
            x=float(location.get("x", 0.0)),
            y=float(location.get("y", 0.0)),
            z=float(location.get("z", 0.0)),
        )

    def as_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}


class CarlaRouteProgressTracker:
    """
    以 CARLA spawn pair 建立固定 smoke route，並從 ego transform 計算進度。

    這裡的 progress 是 start -> goal 線段上的幾何投影進度，只作為
    smoke instrumentation gate；正式路網追蹤、交通規則與 Leaderboard
    評測需要後續 phase 另行定義。
    """

    def __init__(
        self,
        *,
        metrics: CarlaRuntimeMetrics,
        route_town: str,
        start_spawn_index: int,
        end_spawn_index: int,
        min_progress_m: float = 0.5,
        goal_tolerance_m: float = 3.0,
    ) -> None:
        self._metrics = metrics
        self.route_town = route_town
        self.start_spawn_index = int(start_spawn_index)
        self.end_spawn_index = int(end_spawn_index)
        self.min_progress_m = float(min_progress_m)
        self.goal_tolerance_m = float(goal_tolerance_m)

        self.route_scenario_enabled = True
        self.route_scope = "spawn_pair_linear_smoke_only_not_benchmark"
        self.map_name: str | None = None
        self.spawn_point_count: int | None = None
        self.resolved_start_spawn_index: int | None = None
        self.resolved_end_spawn_index: int | None = None
        self.start_point: RoutePoint | None = None
        self.end_point: RoutePoint | None = None
        self.route_distance_m: float | None = None
        self.route_progress_m: float | None = None
        self.route_progress_pct: float | None = None
        self.route_remaining_m: float | None = None
        self.distance_to_goal_m: float | None = None
        self.route_progress_verified = False
        self.route_goal_reached = False
        self.route_completion_verified = False
        self.goal_tolerance_m = float(goal_tolerance_m)
        self.route_goal_reach_required = False
        self.best_distance_to_goal_m: float | None = None
        self.final_distance_to_goal_m: float | None = None
        self.goal_reach_step: int | None = None
        self.route_completion_attempted = False
        self.fixed_route_goal_reached = False
        self.fixed_route_completion_verified = False
        self.route_completion_scope = "progress_smoke_only_not_completion_benchmark"
        self.route_benchmark_verified = False

        self.grp_route_required = False
        self.grp_route_available = False
        self.grp_route_source: str | None = None
        self.grp_dependency_networkx_available = False
        self.grp_route_waypoint_count = 0
        self.grp_route_distance_m: float | None = None
        self.grp_route_progress_m: float | None = None
        self.grp_route_progress_pct: float | None = None
        self.grp_current_waypoint_index: int | None = None
        self.grp_remaining_waypoints: int | None = None
        self.grp_road_options_seen: list[str] = []
        self.grp_controller_strategy: str | None = None
        self.grp_fallback_used = False
        self.grp_route_following_verified = False
        self._grp_points: list[RoutePoint] = []
        self._grp_cumulative_m: list[float] = []
        self._loaded = False

    def enable_goal_reach_gate(self, *, required: bool = True) -> None:
        """啟用 Phase 11L strict goal-reach gate。"""
        self.route_goal_reach_required = required
        self.route_completion_attempted = True
        self.route_completion_scope = "fixed_spawn_pair_goal_reach_smoke_only_not_benchmark"
        self._metrics.record_event(
            "route_goal_reach_gate_enabled",
            None,
            goal_tolerance_m=round(self.goal_tolerance_m, 6),
            route_goal_reach_required=required,
            route_completion_scope=self.route_completion_scope,
        )

    def enable_grp_route_gate(self, *, required: bool = True) -> None:
        """啟用 Phase 11M strict GRP route-following gate。"""
        self.grp_route_required = required
        self.route_scope = "grp_fixed_spawn_pair_smoke_only_not_benchmark"
        self.route_completion_attempted = True
        self.route_completion_scope = "grp_fixed_spawn_pair_goal_reach_smoke_only_not_benchmark"
        self._metrics.record_event(
            "grp_route_gate_enabled",
            None,
            grp_route_required=required,
            route_scope=self.route_scope,
            route_completion_scope=self.route_completion_scope,
        )

    def record_grp_dependency_checked(self, *, networkx_available: bool, error: str | None = None) -> None:
        """記錄 GRP runner 所需 dependency 是否可用。"""
        self.grp_dependency_networkx_available = bool(networkx_available)
        payload: dict[str, Any] = {
            "grp_dependency_networkx_available": self.grp_dependency_networkx_available,
        }
        if error:
            payload["error"] = error
        self._metrics.record_event("grp_dependency_checked", None, **payload)

    def mark_grp_route_blocked(self, *, reason: str, error: str | None = None) -> None:
        """記錄 strict GRP route 無法建立或不可使用。"""
        self.grp_route_available = False
        payload: dict[str, Any] = {
            "reason": reason,
            "grp_route_required": self.grp_route_required,
            "grp_fallback_used": self.grp_fallback_used,
        }
        if error:
            payload["error"] = error
        self._metrics.record_event("grp_route_blocked", None, **payload)

    def load_grp_route(
        self,
        *,
        points: list[RoutePoint],
        road_options: list[str],
        source: str,
        controller_strategy: str,
        sampling_resolution_m: float,
    ) -> None:
        """寫入 CARLA GlobalRoutePlanner 產生的 route evidence。"""
        if len(points) < 2:
            raise RuntimeError("Phase 11M GRP route blocked: fewer than two route waypoints")

        cumulative = [0.0]
        for previous, current in zip(points, points[1:]):
            cumulative.append(cumulative[-1] + self._distance_2d(previous, current))
        route_distance_m = cumulative[-1]
        if route_distance_m <= 0.01:
            raise RuntimeError("Phase 11M GRP route blocked: route distance is zero")

        self._grp_points = list(points)
        self._grp_cumulative_m = cumulative
        self.grp_route_available = True
        self.grp_route_source = source
        self.grp_route_waypoint_count = len(points)
        self.grp_route_distance_m = route_distance_m
        self.grp_route_progress_m = 0.0
        self.grp_route_progress_pct = 0.0
        self.grp_current_waypoint_index = 0
        self.grp_remaining_waypoints = max(0, len(points) - 1)
        self.grp_road_options_seen = sorted({str(option) for option in road_options if str(option)})
        self.grp_controller_strategy = controller_strategy
        self.grp_fallback_used = False

        self._metrics.record_event(
            "grp_route_loaded",
            None,
            grp_route_source=source,
            grp_controller_strategy=controller_strategy,
            grp_route_waypoint_count=len(points),
            grp_route_distance_m=round(route_distance_m, 6),
            grp_road_options_seen=self.grp_road_options_seen,
            route_sampling_resolution_m=round(float(sampling_resolution_m), 6),
        )

    def record_grp_route_following_started(self, *, step: int | None = None) -> None:
        """記錄 GRP route-following control 已開始套用。"""
        self._metrics.record_event(
            "grp_route_following_started",
            step,
            grp_controller_strategy=self.grp_controller_strategy,
            grp_route_waypoint_count=self.grp_route_waypoint_count,
        )

    def record_grp_route_progress(self, *, waypoint_index: int, step: int) -> None:
        """依 runner 回報的 GRP waypoint index 記錄 route-following 進度。"""
        if not self.grp_route_available or not self._grp_cumulative_m:
            return

        previous_idx = int(self.grp_current_waypoint_index or 0)
        index = max(previous_idx, min(int(waypoint_index), len(self._grp_cumulative_m) - 1))
        progress_m = self._grp_cumulative_m[index]
        assert self.grp_route_distance_m is not None
        progress_pct = min(100.0, max(0.0, (progress_m / self.grp_route_distance_m) * 100.0))

        self.grp_current_waypoint_index = index
        self.grp_remaining_waypoints = max(0, self.grp_route_waypoint_count - 1 - index)
        self.grp_route_progress_m = progress_m
        self.grp_route_progress_pct = progress_pct

        self._metrics.record_event(
            "grp_route_progress",
            step,
            grp_current_waypoint_index=index,
            grp_remaining_waypoints=self.grp_remaining_waypoints,
            grp_route_progress_m=round(progress_m, 6),
            grp_route_progress_pct=round(progress_pct, 6),
        )

        if not self.grp_route_following_verified and (index > 0 or progress_m >= self.min_progress_m):
            self.grp_route_following_verified = True
            self._metrics.record_event(
                "grp_route_following_verified",
                step,
                grp_route_progress_m=round(progress_m, 6),
                grp_current_waypoint_index=index,
            )

    def load_from_adapter(self, adapter: Any) -> None:
        """從 CARLA adapter 讀取目前 map 與 spawn points，建立固定 route。"""
        start_transform = adapter.resolve_spawn_transform(self.start_spawn_index)
        end_transform = adapter.resolve_spawn_transform(self.end_spawn_index)
        self.map_name = adapter.get_map_name()
        self.spawn_point_count = int(start_transform["spawn_point_count"])
        self.resolved_start_spawn_index = int(start_transform["resolved_index"])
        self.resolved_end_spawn_index = int(end_transform["resolved_index"])
        self.start_point = RoutePoint.from_transform_dict(start_transform)
        self.end_point = RoutePoint.from_transform_dict(end_transform)
        self.route_distance_m = self._distance_2d(self.start_point, self.end_point)
        if self.route_distance_m <= 0.01:
            raise RuntimeError("Phase 11K route blocked: start/end spawn points are identical")

        self.route_progress_m = 0.0
        self.route_progress_pct = 0.0
        self.route_remaining_m = self.route_distance_m
        self.distance_to_goal_m = self.route_distance_m
        self.best_distance_to_goal_m = self.route_distance_m
        self.final_distance_to_goal_m = self.route_distance_m
        self._loaded = True
        self._metrics.record_event(
            "route_scenario_loaded",
            None,
            route_scope=self.route_scope,
            route_town=self.route_town,
            map_name=self.map_name,
            spawn_point_count=self.spawn_point_count,
            route_start_spawn_index=self.start_spawn_index,
            route_end_spawn_index=self.end_spawn_index,
            resolved_start_spawn_index=self.resolved_start_spawn_index,
            resolved_end_spawn_index=self.resolved_end_spawn_index,
            route_distance_m=round(self.route_distance_m, 6),
            start_location=self.start_point.as_dict(),
            end_location=self.end_point.as_dict(),
        )

    def record_vehicle_state(self, vehicle: Any, step: int) -> None:
        """從 ego transform 計算固定 route 進度。"""
        if not self._loaded or self.start_point is None or self.end_point is None:
            return
        try:
            transform = vehicle.get_transform()
            location = transform.location
            current = RoutePoint(
                x=float(location.x),
                y=float(location.y),
                z=float(location.z),
            )
        except Exception as exc:
            self._metrics.record_event("route_progress_unavailable", step, error=str(exc))
            return

        assert self.route_distance_m is not None
        projected_m = self._project_to_route_m(current)
        progress_m = max(float(self.route_progress_m or 0.0), projected_m)
        remaining_m = max(0.0, self.route_distance_m - progress_m)
        distance_to_goal_m = self._distance_2d(current, self.end_point)
        progress_pct = min(100.0, max(0.0, (progress_m / self.route_distance_m) * 100.0))

        self.route_progress_m = progress_m
        self.route_progress_pct = progress_pct
        self.route_remaining_m = remaining_m
        self.distance_to_goal_m = distance_to_goal_m
        self.final_distance_to_goal_m = distance_to_goal_m
        if self.best_distance_to_goal_m is None:
            self.best_distance_to_goal_m = distance_to_goal_m
        else:
            self.best_distance_to_goal_m = min(self.best_distance_to_goal_m, distance_to_goal_m)

        self._metrics.record_event(
            "route_progress",
            step,
            route_progress_m=round(progress_m, 6),
            route_progress_pct=round(progress_pct, 6),
            route_remaining_m=round(remaining_m, 6),
            distance_to_goal_m=round(distance_to_goal_m, 6),
            current_location=current.as_dict(),
        )

        if not self.route_progress_verified and progress_m >= self.min_progress_m:
            self.route_progress_verified = True
            self._metrics.record_event(
                "route_progress_verified",
                step,
                route_progress_m=round(progress_m, 6),
                min_route_progress_m=round(self.min_progress_m, 6),
            )

        if not self.route_goal_reached and distance_to_goal_m <= self.goal_tolerance_m:
            self.route_goal_reached = True
            self.fixed_route_goal_reached = True
            self.goal_reach_step = step
            if self.route_completion_attempted:
                self.fixed_route_completion_verified = True
            self._metrics.record_event(
                "route_goal_reached",
                step,
                distance_to_goal_m=round(distance_to_goal_m, 6),
                goal_tolerance_m=round(self.goal_tolerance_m, 6),
                fixed_route_completion_verified=self.fixed_route_completion_verified,
            )

    def to_metrics_dict(self) -> dict[str, Any]:
        """輸出 Phase 11K route progress metrics 欄位。"""
        return {
            "route_scenario_enabled": self.route_scenario_enabled,
            "route_scope": self.route_scope,
            "route_town": self.route_town,
            "route_map_name": self.map_name,
            "route_spawn_point_count": self.spawn_point_count,
            "route_start_spawn_index": self.start_spawn_index,
            "route_end_spawn_index": self.end_spawn_index,
            "resolved_route_start_spawn_index": self.resolved_start_spawn_index,
            "resolved_route_end_spawn_index": self.resolved_end_spawn_index,
            "route_distance_m": self._round_optional(self.route_distance_m),
            "route_progress_m": self._round_optional(self.route_progress_m),
            "route_progress_pct": self._round_optional(self.route_progress_pct),
            "route_remaining_m": self._round_optional(self.route_remaining_m),
            "distance_to_goal_m": self._round_optional(self.distance_to_goal_m),
            "route_progress_verified": self.route_progress_verified,
            "route_goal_reached": self.route_goal_reached,
            "route_completion_verified": self.route_completion_verified,
            "goal_tolerance_m": self._round_optional(self.goal_tolerance_m),
            "route_goal_reach_required": self.route_goal_reach_required,
            "best_distance_to_goal_m": self._round_optional(self.best_distance_to_goal_m),
            "final_distance_to_goal_m": self._round_optional(self.final_distance_to_goal_m),
            "goal_reach_step": self.goal_reach_step,
            "route_completion_attempted": self.route_completion_attempted,
            "fixed_route_goal_reached": self.fixed_route_goal_reached,
            "fixed_route_completion_verified": self.fixed_route_completion_verified,
            "route_completion_scope": self.route_completion_scope,
            "route_benchmark_verified": self.route_benchmark_verified,
            "grp_route_required": self.grp_route_required,
            "grp_route_available": self.grp_route_available,
            "grp_route_source": self.grp_route_source,
            "grp_dependency_networkx_available": self.grp_dependency_networkx_available,
            "grp_route_waypoint_count": self.grp_route_waypoint_count,
            "grp_route_distance_m": self._round_optional(self.grp_route_distance_m),
            "grp_route_progress_m": self._round_optional(self.grp_route_progress_m),
            "grp_route_progress_pct": self._round_optional(self.grp_route_progress_pct),
            "grp_current_waypoint_index": self.grp_current_waypoint_index,
            "grp_remaining_waypoints": self.grp_remaining_waypoints,
            "grp_road_options_seen": self.grp_road_options_seen,
            "grp_controller_strategy": self.grp_controller_strategy,
            "grp_fallback_used": self.grp_fallback_used,
            "grp_route_following_verified": self.grp_route_following_verified,
        }

    def _project_to_route_m(self, point: RoutePoint) -> float:
        assert self.start_point is not None
        assert self.end_point is not None
        assert self.route_distance_m is not None
        route_dx = self.end_point.x - self.start_point.x
        route_dy = self.end_point.y - self.start_point.y
        ego_dx = point.x - self.start_point.x
        ego_dy = point.y - self.start_point.y
        projected = ((ego_dx * route_dx) + (ego_dy * route_dy)) / self.route_distance_m
        return max(0.0, min(self.route_distance_m, projected))

    @staticmethod
    def _distance_2d(a: RoutePoint, b: RoutePoint) -> float:
        return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)

    @staticmethod
    def _round_optional(value: float | None) -> float | None:
        return round(value, 6) if value is not None else None

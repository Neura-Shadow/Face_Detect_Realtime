"""
Phase 11M GRP-backed fixed-route following runner.

此 runner 在真實 CARLA runtime 中使用 CARLA GlobalRoutePlanner 產生 road
waypoint route，並用 runner-only controller 嘗試完成固定 spawn-pair goal
reach gate。它不是 CARLA Leaderboard、不是正式 route benchmark，也不是
infraction benchmark。
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import io
import json
import logging
import math
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_phase11j_carla_sensor_metrics import (
    CommandResult,
    _build_text_report,
    _environment_commands,
    _find_carla_wheel,
    _read_pip_show_version,
    _run_command,
    _tcp_reachable,
    _timestamped_run_dir,
    _utc_now,
    _write_json,
    _write_jsonl,
    _write_raw_outputs,
)
from scripts.run_phase11k_fixed_route_smoke import _runtime_town
from workers.CARLA_Closed_Loop_Agent import CarlaClosedLoopAgent
from workers.core.carla_adapter import CarlaClientAdapter
from workers.core.carla_metrics import CarlaRuntimeMetrics
from workers.core.carla_route_metrics import CarlaRouteProgressTracker, RoutePoint
from workers.core.config import AgentConfig

DEFAULT_CARLA_ROOT = Path(os.environ.get("CARLA_ROOT", r"D:\CARLA\packages\CARLA_0.9.16"))
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runtime_logs" / "carla_runs"
BENCHMARK_BOUNDARY_SCOPE = "structured_evidence_only_not_carla_leaderboard"


def _build_config(args: argparse.Namespace) -> AgentConfig:
    config = AgentConfig.load()
    carla_cfg = dataclasses.replace(
        config.carla,
        host=args.host,
        port=args.port,
        timeout_sec=args.timeout_sec,
        town=_runtime_town(args.town),
        spawn_point_index=args.start_spawn_index,
        synchronous_mode=not args.async_world,
        camera_width=args.camera_width,
        camera_height=args.camera_height,
    )
    perception_cfg = dataclasses.replace(
        config.perception,
        backend=args.perception_backend,
        model_name=args.perception_model,
    )
    trigger_cfg = dataclasses.replace(
        config.trigger,
        cooldown_sec=0.0 if args.enable_vlm else config.trigger.cooldown_sec,
        force_interval_frames=args.force_vlm_every,
    )
    telemetry_cfg = dataclasses.replace(
        config.telemetry,
        publish_interval_sec=0.1,
        batch_size=4,
    )
    supabase_cfg = config.supabase
    if not args.publish_telemetry:
        supabase_cfg = dataclasses.replace(config.supabase, url="", key="")

    return dataclasses.replace(
        config,
        agent_id="phase11m-grp-route-following",
        mode="carla",
        main_loop_hz=args.loop_hz,
        carla=carla_cfg,
        perception=perception_cfg,
        trigger=trigger_cfg,
        telemetry=telemetry_cfg,
        supabase=supabase_cfg,
    )


class GRPRouteFollowingControlAdapter:
    """
    Phase 11M runner-only GRP route-following controller。

    此控制器只在 11M runner 中使用；它不修改 MA-VLNA baseline planner、
    SafetyGate、VLMReasoner 或 CARLA baseline control mapper。
    """

    def __init__(
        self,
        *,
        client_adapter: CarlaClientAdapter,
        route_tracker: CarlaRouteProgressTracker,
        metrics: CarlaRuntimeMetrics,
        carla_root: Path,
        target_speed_kmh: float,
        route_sampling_resolution_m: float,
        lookahead_waypoints: int,
        require_grp: bool,
    ) -> None:
        self._client_adapter = client_adapter
        self._route_tracker = route_tracker
        self._metrics = metrics
        self._carla_root = carla_root
        self._target_speed_kmh = float(target_speed_kmh)
        self._route_sampling_resolution_m = float(route_sampling_resolution_m)
        self._lookahead_waypoints = int(lookahead_waypoints)
        self._require_grp = bool(require_grp)
        self._strategy = "uninitialized"
        self._route_waypoints: list[Any] = []
        self._road_options: list[str] = []
        self._route_index = 0
        self._execution_count = 0
        self._initialized = False
        self._following_started = False

    async def execute(self, action: Any) -> bool:
        self._execution_count += 1
        vehicle = getattr(self._client_adapter, "ego_vehicle", None)
        if vehicle is None:
            return False
        if not self._initialized:
            self._initialize_strategy(vehicle)

        control = self._build_control(vehicle)
        vehicle.apply_control(control)
        self._metrics.record_event(
            "grp_route_control_applied",
            self._execution_count,
            strategy=self._strategy,
            throttle=float(control.throttle),
            steer=float(control.steer),
            brake=float(control.brake),
            reverse=bool(control.reverse),
            target_speed_kmh=round(self._target_speed_kmh, 6),
            grp_route_waypoint_count=len(self._route_waypoints),
            grp_current_waypoint_index=self._route_index,
            source_plan_id=getattr(action, "plan_id", ""),
        )
        await asyncio.sleep(0)
        return True

    def _initialize_strategy(self, vehicle: Any) -> None:
        self._initialized = True
        self._strategy = "global_route_planner_waypoint_follower"
        try:
            self._add_carla_agents_path()
            import networkx  # type: ignore[import-not-found]  # noqa: F401
            import carla  # type: ignore[import-not-found]
            from agents.navigation.global_route_planner import GlobalRoutePlanner  # type: ignore[import-not-found]

            self._route_tracker.record_grp_dependency_checked(networkx_available=True)
            end_point = self._route_tracker.end_point
            if end_point is None:
                raise RuntimeError("route endpoint is not loaded")

            world = vehicle.get_world()
            origin = vehicle.get_transform().location
            destination = carla.Location(x=end_point.x, y=end_point.y, z=end_point.z)
            planner = GlobalRoutePlanner(world.get_map(), self._route_sampling_resolution_m)
            route = planner.trace_route(origin, destination)
            if len(route) < 2:
                raise RuntimeError("GlobalRoutePlanner returned fewer than two waypoints")

            self._route_waypoints = [waypoint for waypoint, _road_option in route]
            self._road_options = [_road_option_name(road_option) for _waypoint, road_option in route]
            points = [
                RoutePoint(
                    x=float(waypoint.transform.location.x),
                    y=float(waypoint.transform.location.y),
                    z=float(waypoint.transform.location.z),
                )
                for waypoint in self._route_waypoints
            ]
            self._route_tracker.load_grp_route(
                points=points,
                road_options=self._road_options,
                source="carla_global_route_planner",
                controller_strategy=self._strategy,
                sampling_resolution_m=self._route_sampling_resolution_m,
            )
        except Exception as exc:
            self._route_tracker.mark_grp_route_blocked(
                reason="global_route_planner_unavailable_or_failed",
                error=str(exc),
            )
            self._metrics.record_event(
                "grp_route_controller_blocked",
                None,
                strategy=self._strategy,
                require_grp=self._require_grp,
                error=str(exc),
            )
            if self._require_grp:
                raise RuntimeError(f"Phase 11M GRP route blocked: {exc}") from exc

    def _build_control(self, vehicle: Any) -> Any:
        import carla  # type: ignore[import-not-found]

        if self._route_tracker.fixed_route_goal_reached:
            return carla.VehicleControl(throttle=0.0, steer=0.0, brake=1.0, reverse=False)

        target = self._target_location(vehicle)
        transform = vehicle.get_transform()
        velocity = vehicle.get_velocity()
        current_speed_kmh = math.sqrt(
            float(velocity.x) ** 2 + float(velocity.y) ** 2 + float(velocity.z) ** 2
        ) * 3.6
        current_x = float(transform.location.x)
        current_y = float(transform.location.y)
        ego_yaw = float(transform.rotation.yaw)
        target_yaw = math.degrees(math.atan2(target.y - current_y, target.x - current_x))
        forward_error = _angle_delta_deg(target_yaw, ego_yaw)
        reverse = abs(forward_error) > 100.0
        control_yaw = target_yaw + 180.0 if reverse else target_yaw
        control_error = _angle_delta_deg(control_yaw, ego_yaw)
        distance_to_goal = float(self._route_tracker.distance_to_goal_m or 999.0)

        desired_speed = self._target_speed_kmh
        if distance_to_goal < 6.0:
            desired_speed = min(desired_speed, 8.0)
        if distance_to_goal < 3.5:
            desired_speed = min(desired_speed, 4.0)

        speed_error = desired_speed - current_speed_kmh
        throttle = 0.0
        brake = 0.0
        if speed_error > 0.5:
            throttle = min(0.85, max(0.25, speed_error / max(5.0, desired_speed * 0.45)))
        elif speed_error < -1.0:
            brake = min(0.45, abs(speed_error) / 15.0)

        steer = max(-0.75, min(0.75, control_error / 65.0))
        return carla.VehicleControl(
            throttle=float(throttle),
            steer=float(steer),
            brake=float(brake),
            reverse=bool(reverse),
            hand_brake=False,
        )

    def _target_location(self, vehicle: Any) -> Any:
        end_point = self._route_tracker.end_point
        if end_point is None:
            raise RuntimeError("route endpoint is not loaded")
        if not self._route_waypoints:
            raise RuntimeError("Phase 11M requires a GRP route; no route waypoints are available")

        if not self._following_started:
            self._following_started = True
            self._route_tracker.record_grp_route_following_started(step=self._execution_count)

        location = vehicle.get_transform().location
        start = max(0, self._route_index - 10)
        stop = min(len(self._route_waypoints), self._route_index + 100)
        closest_idx = self._route_index
        closest_dist = float("inf")
        for idx in range(start, stop):
            waypoint_location = self._route_waypoints[idx].transform.location
            distance = location.distance(waypoint_location)
            if distance < closest_dist:
                closest_dist = distance
                closest_idx = idx

        self._route_index = max(self._route_index, closest_idx)
        self._route_tracker.record_grp_route_progress(
            waypoint_index=self._route_index,
            step=self._execution_count,
        )

        target_idx = min(len(self._route_waypoints) - 1, self._route_index + self._lookahead_waypoints)
        if float(self._route_tracker.distance_to_goal_m or 999.0) < 20.0:
            return _route_point_to_carla_location(end_point)
        return self._route_waypoints[target_idx].transform.location

    def _add_carla_agents_path(self) -> None:
        agents_path = self._agents_path()
        if not agents_path.exists():
            raise RuntimeError(f"CARLA agents path not found: {agents_path}")
        path_text = str(agents_path)
        if path_text not in sys.path:
            sys.path.insert(0, path_text)

    def _agents_path(self) -> Path:
        return self._carla_root / "PythonAPI" / "carla"


def _route_point_to_carla_location(point: RoutePoint) -> Any:
    import carla  # type: ignore[import-not-found]

    return carla.Location(x=point.x, y=point.y, z=point.z)


def _angle_delta_deg(target: float, current: float) -> float:
    """回傳 [-180, 180] 範圍內的角度差。"""
    return (target - current + 180.0) % 360.0 - 180.0


def _road_option_name(road_option: Any) -> str:
    name = getattr(road_option, "name", None)
    if name:
        return str(name)
    text = str(road_option)
    return text.rsplit(".", 1)[-1]


async def _run_grp_route_following(
    args: argparse.Namespace,
    metrics: CarlaRuntimeMetrics,
    route_tracker: CarlaRouteProgressTracker,
) -> None:
    config = _build_config(args)
    carla_adapter = CarlaClientAdapter(config.carla)
    control_adapter = GRPRouteFollowingControlAdapter(
        client_adapter=carla_adapter,
        route_tracker=route_tracker,
        metrics=metrics,
        carla_root=args.carla_root,
        target_speed_kmh=args.target_speed_kmh,
        route_sampling_resolution_m=args.route_sampling_resolution_m,
        lookahead_waypoints=args.lookahead_waypoints,
        require_grp=args.require_grp,
    )
    agent = CarlaClosedLoopAgent(
        config=config,
        enable_vlm=args.enable_vlm,
        carla_adapter=carla_adapter,
        control_adapter=control_adapter,
        runtime_metrics=metrics,
        route_tracker=route_tracker,
        enable_metric_sensors=args.enable_metric_sensors,
        require_sensors=args.require_sensors,
    )
    route_tracker.enable_goal_reach_gate(required=args.require_goal_reach)
    route_tracker.enable_grp_route_gate(required=args.require_grp)
    await agent.run(max_steps=args.steps)


def _capture_grp_route_following(
    args: argparse.Namespace,
    metrics: CarlaRuntimeMetrics,
    route_tracker: CarlaRouteProgressTracker,
) -> CommandResult:
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
    root = logging.getLogger()
    previous_level = root.level
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    started = time.perf_counter()
    try:
        asyncio.run(_run_grp_route_following(args, metrics, route_tracker))
        returncode = 0
        stderr = ""
    except Exception as exc:
        returncode = 1
        stderr = str(exc)
        logging.getLogger(__name__).exception("Phase 11M GRP route following failed")
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)

    return CommandResult(
        name="phase11m_grp_route_following",
        command=[sys.executable, *sys.argv],
        returncode=returncode,
        stdout=log_stream.getvalue().strip(),
        stderr=stderr,
        duration_sec=round(time.perf_counter() - started, 3),
    )


def _grp_dependency_check(args: argparse.Namespace, env: dict[str, str]) -> CommandResult:
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(args.carla_root / 'PythonAPI' / 'carla')!r}); "
        "import networkx; "
        "from agents.navigation.global_route_planner import GlobalRoutePlanner; "
        "print('grp dependency import passed'); "
        "print('networkx_version=' + getattr(networkx, '__version__', 'unknown')); "
        "print('GlobalRoutePlanner=' + GlobalRoutePlanner.__name__)"
    )
    return _run_command(
        "grp_dependency_check",
        [sys.executable, "-c", code],
        env=env,
        timeout_sec=30,
    )


def _short_error(result: CommandResult) -> str:
    text = (result.stderr or result.stdout or "").strip()
    if not text:
        return f"{result.name} exit={result.returncode}"
    return "\n".join(text.splitlines()[-5:])


def _build_manifest(
    args: argparse.Namespace,
    *,
    run_dir: Path,
    carla_version: str | None,
    wheel: Path | None,
    result: str,
    regression_passed: bool | None,
    route_metrics: dict[str, Any],
) -> dict[str, Any]:
    server_executable = args.carla_root / "CarlaUE4.exe"
    status_map = {
        "passed": "grp_route_following_goal_reach_pass",
        "blocked": "grp_route_following_server_blocked",
        "grp_blocked": "grp_route_following_blocked",
        "sensor_blocked": "grp_route_sensor_blocked",
        "goal_reach_blocked": "grp_route_goal_reach_blocked",
    }
    return {
        "phase": "Phase 11M",
        "status": status_map.get(result, "grp_route_following_failed"),
        "created_at_utc": _utc_now(),
        "run_dir": str(run_dir),
        "carla_root": str(args.carla_root),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "carla_version": carla_version,
        "carla_wheel": wheel.name if wheel else None,
        "host": args.host,
        "port": args.port,
        "steps_requested": args.steps,
        "target_speed_kmh": args.target_speed_kmh,
        "goal_tolerance_m": args.goal_tolerance_m,
        "route_sampling_resolution_m": args.route_sampling_resolution_m,
        "lookahead_waypoints": args.lookahead_waypoints,
        "perception_backend": args.perception_backend,
        "require_server": args.require_server,
        "server_executable": str(server_executable) if server_executable.exists() else None,
        "sensor_metrics_enabled": args.enable_metric_sensors,
        "require_sensors": args.require_sensors,
        "require_goal_reach": args.require_goal_reach,
        "require_grp": args.require_grp,
        "route_scope": route_metrics.get("route_scope"),
        "route_completion_scope": route_metrics.get("route_completion_scope"),
        "route_town": route_metrics.get("route_town"),
        "carla_runtime_town": _runtime_town(args.town),
        "route_start_spawn_index": route_metrics.get("route_start_spawn_index"),
        "route_end_spawn_index": route_metrics.get("route_end_spawn_index"),
        "grp_route_required": route_metrics.get("grp_route_required"),
        "grp_route_available": route_metrics.get("grp_route_available"),
        "grp_route_source": route_metrics.get("grp_route_source"),
        "grp_route_waypoint_count": route_metrics.get("grp_route_waypoint_count"),
        "benchmark_scope": "fixed_spawn_pair_smoke_only",
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        "leaderboard_routes_exported": False,
        "leaderboard_route_criteria_evaluated": False,
        "route_benchmark_verified": False,
        "infraction_benchmark_verified": False,
        "leaderboard_evaluated": False,
        "result": result,
        "regression_passed": regression_passed,
    }


def _build_commands_text(args: argparse.Namespace, results: list[CommandResult]) -> str:
    lines = [
        "$env:CARLA_ROOT = " + json.dumps(str(args.carla_root), ensure_ascii=False),
        "",
        "# Manual dependency unlock, if grp_dependency_check is blocked:",
        subprocess.list2cmdline([sys.executable, "-m", "pip", "install", "networkx>=3,<4"]),
        "",
        subprocess.list2cmdline([sys.executable, *sys.argv]),
        "",
    ]
    for result in results:
        lines.append(result.command_text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MA-VLNA Phase 11M GRP-backed fixed route runner")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--timeout-sec", type=float, default=60.0)
    parser.add_argument("--steps", type=int, default=2500)
    parser.add_argument("--loop-hz", type=int, default=20)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--start-spawn-index", type=int, default=3)
    parser.add_argument("--end-spawn-index", type=int, default=30)
    parser.add_argument("--target-speed-kmh", type=float, default=18.0)
    parser.add_argument("--goal-tolerance-m", type=float, default=3.0)
    parser.add_argument("--route-sampling-resolution-m", type=float, default=2.0)
    parser.add_argument("--lookahead-waypoints", type=int, default=8)
    parser.add_argument("--camera-width", type=int, default=320)
    parser.add_argument("--camera-height", type=int, default=180)
    parser.add_argument("--async-world", action="store_true")
    parser.add_argument("--perception-backend", default="dummy", choices=["dummy", "yolo", "rtdetr"])
    parser.add_argument("--perception-model", default="dummy")
    parser.add_argument("--enable-vlm", action="store_true")
    parser.add_argument("--force-vlm-every", type=int, default=0)
    parser.add_argument("--publish-telemetry", action="store_true")
    parser.add_argument("--require-server", action="store_true")
    parser.add_argument("--enable-metric-sensors", action="store_true")
    parser.add_argument("--require-sensors", action="store_true")
    parser.add_argument("--require-goal-reach", action="store_true")
    parser.add_argument("--require-grp", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--run-regressions", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.carla_root = args.carla_root.resolve()
    run_dir = _timestamped_run_dir(args.output_dir)

    env = os.environ.copy()
    env["CARLA_ROOT"] = str(args.carla_root)
    env["PYTHONIOENCODING"] = "utf-8"

    environment_results = _environment_commands(args, env)
    metrics = CarlaRuntimeMetrics()
    metrics.carla_import_ok = next((item.ok for item in environment_results if item.name == "carla_import"), False)
    metrics.server_reachable = _tcp_reachable(args.host, args.port)
    metrics.steps_requested = args.steps
    metrics.record_event(
        "benchmark_boundary_prepared",
        None,
        benchmark_boundary_scope=BENCHMARK_BOUNDARY_SCOPE,
        leaderboard_routes_exported=False,
        leaderboard_route_criteria_evaluated=False,
        route_benchmark_verified=False,
        infraction_benchmark_verified=False,
        leaderboard_evaluated=False,
    )
    route_tracker = CarlaRouteProgressTracker(
        metrics=metrics,
        route_town=args.town,
        start_spawn_index=args.start_spawn_index,
        end_spawn_index=args.end_spawn_index,
        min_progress_m=args.goal_tolerance_m,
        goal_tolerance_m=args.goal_tolerance_m,
    )
    route_tracker.enable_grp_route_gate(required=args.require_grp)

    grp_dependency_result = _grp_dependency_check(args, env)
    route_tracker.record_grp_dependency_checked(
        networkx_available=grp_dependency_result.ok,
        error=None if grp_dependency_result.ok else _short_error(grp_dependency_result),
    )

    phase11d_result = _run_command(
        "phase11d_require_ready",
        [
            sys.executable,
            "scripts\\run_phase11d_carla_provisioning_gate.py",
            "--carla-root",
            str(args.carla_root),
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--steps",
            str(args.steps),
            "--require-ready",
        ],
        env=env,
        timeout_sec=60,
    )

    command_results: list[CommandResult] = [grp_dependency_result, phase11d_result]
    smoke_result: CommandResult | None = None
    regression_results: list[CommandResult] = []

    if grp_dependency_result.ok and phase11d_result.ok:
        smoke_result = _capture_grp_route_following(args, metrics, route_tracker)
        command_results.append(smoke_result)

    if args.require_server and not phase11d_result.ok:
        result = "blocked"
    elif args.require_grp and not grp_dependency_result.ok:
        result = "grp_blocked"
        route_tracker.mark_grp_route_blocked(
            reason="global_route_planner_dependency_unavailable",
            error=_short_error(grp_dependency_result),
        )
    else:
        result = "failed"

    if smoke_result is not None:
        if not smoke_result.ok:
            result = "grp_blocked" if args.require_grp and not route_tracker.grp_route_available else "failed"
        elif metrics.steps_completed > 0:
            sensors_ok = (
                not args.require_sensors
                or (metrics.collision_sensor_attached and metrics.lane_invasion_sensor_attached)
            )
            grp_ok = (
                route_tracker.grp_route_available
                and not route_tracker.grp_fallback_used
                and route_tracker.grp_route_following_verified
            )
            goal_ok = route_tracker.fixed_route_completion_verified
            if not sensors_ok:
                result = "sensor_blocked"
            elif not grp_ok:
                result = "grp_blocked"
            elif not goal_ok:
                result = "goal_reach_blocked"
            else:
                result = "passed"

    if result == "passed" and args.run_regressions:
        regression_results.extend(
            [
                _run_command(
                    "base_phase11_carla_checks",
                    [args.base_python, "scripts\\run_phase11_carla_checks.py"],
                    env=env,
                    timeout_sec=180,
                ),
                _run_command(
                    "base_demo_checks",
                    [args.base_python, "scripts\\run_demo_checks.py"],
                    env=env,
                    timeout_sec=300,
                ),
                _run_command(
                    "py312_phase11_carla_checks",
                    [sys.executable, "scripts\\run_phase11_carla_checks.py"],
                    env=env,
                    timeout_sec=180,
                ),
                _run_command(
                    "py312_phase11d_require_ready",
                    [
                        sys.executable,
                        "scripts\\run_phase11d_carla_provisioning_gate.py",
                        "--carla-root",
                        str(args.carla_root),
                        "--host",
                        args.host,
                        "--port",
                        str(args.port),
                        "--steps",
                        str(args.steps),
                        "--require-ready",
                    ],
                    env=env,
                    timeout_sec=60,
                ),
                _run_command(
                    "py312_py_compile",
                    [
                        sys.executable,
                        "-m",
                        "py_compile",
                        "scripts\\run_phase11b_real_carla_smoke.py",
                        "scripts\\run_phase11d_carla_provisioning_gate.py",
                        "scripts\\run_phase11i_carla_evidence_pack.py",
                        "scripts\\run_phase11j_carla_sensor_metrics.py",
                        "scripts\\run_phase11k_fixed_route_smoke.py",
                        "scripts\\run_phase11l_fixed_route_completion.py",
                        "scripts\\run_phase11m_grp_route_following.py",
                        "workers\\core\\carla_metrics.py",
                        "workers\\core\\carla_route_metrics.py",
                        "workers\\core\\carla_adapter.py",
                        "workers\\CARLA_Closed_Loop_Agent.py",
                    ],
                    env=env,
                    timeout_sec=60,
                ),
            ]
        )
        if not all(item.ok for item in regression_results):
            result = "failed"

    regression_passed = bool(regression_results) and all(item.ok for item in regression_results)
    metrics_dict = metrics.to_metrics_dict(
        perception_backend=args.perception_backend,
        vlm_enabled=args.enable_vlm,
        fallback_used=route_tracker.grp_fallback_used,
        result=result,
    )
    metrics_dict.update(
        {
            "phase": "Phase 11M",
            "metrics_scope": "grp_route_following_smoke_only_not_benchmark",
            "target_speed_kmh": args.target_speed_kmh,
            "benchmark_boundary_prepared": True,
            "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
            "leaderboard_routes_exported": False,
            "leaderboard_route_criteria_evaluated": False,
        }
    )
    metrics_dict.update(route_tracker.to_metrics_dict())
    metrics_dict["route_benchmark_verified"] = False
    metrics_dict["infraction_benchmark_verified"] = False
    metrics_dict["leaderboard_evaluated"] = False
    if args.run_regressions:
        metrics_dict["regression_passed"] = regression_passed

    carla_version = _read_pip_show_version(
        next((item.stdout for item in environment_results if item.name == "pip_show_carla"), "")
    )
    route_metrics = route_tracker.to_metrics_dict()
    manifest = _build_manifest(
        args,
        run_dir=run_dir,
        carla_version=carla_version,
        wheel=_find_carla_wheel(args.carla_root),
        result=result,
        regression_passed=regression_passed if args.run_regressions else None,
        route_metrics=route_metrics,
    )

    all_results = environment_results + command_results + regression_results
    _write_raw_outputs(run_dir, all_results)
    _write_json(run_dir / "manifest.json", manifest)
    _write_json(run_dir / "metrics.json", metrics_dict)
    _write_jsonl(run_dir / "events.jsonl", metrics.to_events("passed" if result == "passed" else "failed"))
    (run_dir / "commands.txt").write_text(
        _build_commands_text(args, command_results + regression_results),
        encoding="utf-8",
    )
    (run_dir / "environment.txt").write_text(
        _build_text_report("# Phase 11M environment snapshot", environment_results),
        encoding="utf-8",
    )
    (run_dir / "regression.txt").write_text(
        _build_text_report("# Phase 11M regression proof", command_results + regression_results),
        encoding="utf-8",
    )

    if result == "passed":
        print(
            "Phase 11M GRP Route Following Pass — strict GRP-backed fixed-route goal-reach gate passed."
        )
        print(f"evidence_dir={run_dir}")
        return 0

    if result == "blocked":
        print("Phase 11M Blocked — real CARLA GRP route following requires CARLA package and reachable CARLA server.")
    elif result == "grp_blocked":
        print("Phase 11M GRP Blocked — GlobalRoutePlanner dependency unavailable or GRP route following was not verified.")
    elif result == "sensor_blocked":
        print("Phase 11M Sensor Blocked — required CARLA metric sensors could not be attached.")
    elif result == "goal_reach_blocked":
        print("Phase 11M Goal-Reach Blocked — strict goal tolerance was not reached before the step budget expired.")
    else:
        failing = next((item for item in command_results + regression_results if not item.ok), None)
        reason = f"{failing.name} exit={failing.returncode}" if failing else "unknown"
        print(f"Phase 11M Runtime Failed — GRP route following failed: {reason}")
    print(f"evidence_dir={run_dir}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

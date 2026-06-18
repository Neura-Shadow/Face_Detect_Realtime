"""
Phase 11K fixed-route CARLA smoke runner.

此 runner 在真實 CARLA runtime 中使用固定 spawn pair 建立 smoke route，
並記錄 route progress metrics。它不做 CARLA Leaderboard、不做 infraction
benchmark，也不宣稱正式 route completion。
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
from workers.CARLA_Closed_Loop_Agent import CarlaClosedLoopAgent
from workers.core.carla_adapter import CarlaClientAdapter, CarlaControlCommand
from workers.core.carla_metrics import CarlaRuntimeMetrics
from workers.core.carla_route_metrics import CarlaRouteProgressTracker
from workers.core.config import AgentConfig

DEFAULT_CARLA_ROOT = Path(os.environ.get("CARLA_ROOT", r"D:\CARLA\packages\CARLA_0.9.16"))
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runtime_logs" / "carla_runs"
DEFAULT_GOAL_TOLERANCE_M = 3.0


def _runtime_town(town: str) -> str:
    """CARLA 0.9.16 Windows package 下，Town03 smoke 使用 Opt map 較穩定。"""
    if town.lower() == "town03":
        return "Town03_Opt"
    return town


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
        agent_id="phase11k-fixed-route-smoke",
        mode="carla",
        main_loop_hz=args.loop_hz,
        carla=carla_cfg,
        perception=perception_cfg,
        trigger=trigger_cfg,
        telemetry=telemetry_cfg,
        supabase=supabase_cfg,
    )


class FixedRouteSmokeControlAdapter:
    """
    Phase 11K 專用 route smoke actuator。

    它只在 11K runner 中使用，讓車輛沿固定 spawn-pair 方向產生可量測位移；
    不修改 VLM、SafetyGate 或 SemanticPlanner 的決策邏輯，也不宣稱路線品質。
    """

    def __init__(
        self,
        client_adapter: CarlaClientAdapter,
        route_tracker: CarlaRouteProgressTracker,
        metrics: CarlaRuntimeMetrics,
    ) -> None:
        self._client_adapter = client_adapter
        self._route_tracker = route_tracker
        self._metrics = metrics
        self._execution_count = 0

    async def execute(self, action: Any) -> bool:
        self._execution_count += 1
        command = self._build_route_command()
        self._client_adapter.apply_control(command)
        self._metrics.record_event(
            "route_smoke_control_applied",
            self._execution_count,
            throttle=command.throttle,
            steer=command.steer,
            brake=command.brake,
            reverse=command.reverse,
            source_plan_id=getattr(action, "plan_id", ""),
        )
        await asyncio.sleep(0)
        return True

    def _build_route_command(self) -> CarlaControlCommand:
        if self._route_tracker.route_goal_reached:
            return CarlaControlCommand(
                throttle=0.0,
                steer=0.0,
                brake=1.0,
                reverse=False,
                source_action="route_smoke_stop",
                source_plan_id="phase11k-route-smoke",
            )
        end_point = self._route_tracker.end_point
        if end_point is None:
            return CarlaControlCommand(
                throttle=0.0,
                steer=0.0,
                brake=1.0,
                reverse=False,
                source_action="route_smoke_wait",
                source_plan_id="phase11k-route-smoke",
            )

        ego_state = self._client_adapter.get_ego_state()
        location = ego_state.get("location", {})
        rotation = ego_state.get("rotation", {})
        current_x = float(location.get("x", 0.0))
        current_y = float(location.get("y", 0.0))
        ego_yaw = float(rotation.get("yaw", 0.0))
        target_yaw = math.degrees(math.atan2(end_point.y - current_y, end_point.x - current_x))
        forward_error = _angle_delta_deg(target_yaw, ego_yaw)

        reverse = abs(forward_error) > 90.0
        control_yaw = target_yaw + 180.0 if reverse else target_yaw
        control_error = _angle_delta_deg(control_yaw, ego_yaw)
        steer = max(-0.45, min(0.45, control_error / 90.0))
        return CarlaControlCommand(
            throttle=0.45,
            steer=steer,
            brake=0.0,
            reverse=reverse,
            source_action="route_smoke_reverse" if reverse else "route_smoke_forward",
            source_plan_id="phase11k-route-smoke",
        )


def _angle_delta_deg(target: float, current: float) -> float:
    """回傳 [-180, 180] 範圍內的角度差。"""
    return (target - current + 180.0) % 360.0 - 180.0


async def _run_route_smoke(
    args: argparse.Namespace,
    metrics: CarlaRuntimeMetrics,
    route_tracker: CarlaRouteProgressTracker,
) -> None:
    config = _build_config(args)
    carla_adapter = CarlaClientAdapter(config.carla)
    control_adapter = FixedRouteSmokeControlAdapter(carla_adapter, route_tracker, metrics)
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
    await agent.run(max_steps=args.steps)


def _capture_route_smoke(
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
        asyncio.run(_run_route_smoke(args, metrics, route_tracker))
        returncode = 0
        stderr = ""
    except Exception as exc:
        returncode = 1
        stderr = str(exc)
        logging.getLogger(__name__).exception("Phase 11K fixed-route smoke failed")
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)

    return CommandResult(
        name="phase11k_fixed_route_smoke",
        command=[sys.executable, *sys.argv],
        returncode=returncode,
        stdout=log_stream.getvalue().strip(),
        stderr=stderr,
        duration_sec=round(time.perf_counter() - started, 3),
    )


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
        "passed": "fixed_route_smoke_pass",
        "blocked": "fixed_route_smoke_blocked",
        "sensor_blocked": "fixed_route_sensor_blocked",
        "route_progress_blocked": "fixed_route_progress_blocked",
    }
    return {
        "phase": "Phase 11K",
        "status": status_map.get(result, "fixed_route_smoke_failed"),
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
        "perception_backend": args.perception_backend,
        "require_server": args.require_server,
        "server_executable": str(server_executable) if server_executable.exists() else None,
        "sensor_metrics_enabled": args.enable_metric_sensors,
        "require_sensors": args.require_sensors,
        "require_route_progress": args.require_route_progress,
        "min_route_progress_m": args.min_route_progress_m,
        "route_scope": route_metrics.get("route_scope"),
        "route_town": route_metrics.get("route_town"),
        "carla_runtime_town": _runtime_town(args.town),
        "route_start_spawn_index": route_metrics.get("route_start_spawn_index"),
        "route_end_spawn_index": route_metrics.get("route_end_spawn_index"),
        "benchmark_scope": "smoke_only",
        "route_completion_verified": False,
        "infraction_benchmark_verified": False,
        "leaderboard_evaluated": False,
        "result": result,
        "regression_passed": regression_passed,
    }


def _build_commands_text(args: argparse.Namespace, results: list[CommandResult]) -> str:
    lines = [
        "$env:CARLA_ROOT = " + json.dumps(str(args.carla_root), ensure_ascii=False),
        "",
        subprocess.list2cmdline([sys.executable, *sys.argv]),
        "",
    ]
    for result in results:
        lines.append(result.command_text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MA-VLNA Phase 11K fixed route CARLA smoke runner")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--timeout-sec", type=float, default=30.0)
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--loop-hz", type=int, default=20)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--start-spawn-index", type=int, default=3)
    parser.add_argument("--end-spawn-index", type=int, default=30)
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
    parser.add_argument("--require-route-progress", action="store_true")
    parser.add_argument("--min-route-progress-m", type=float, default=0.5)
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
    route_tracker = CarlaRouteProgressTracker(
        metrics=metrics,
        route_town=args.town,
        start_spawn_index=args.start_spawn_index,
        end_spawn_index=args.end_spawn_index,
        min_progress_m=args.min_route_progress_m,
        goal_tolerance_m=DEFAULT_GOAL_TOLERANCE_M,
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

    command_results: list[CommandResult] = [phase11d_result]
    smoke_result: CommandResult | None = None
    regression_results: list[CommandResult] = []

    if phase11d_result.ok:
        smoke_result = _capture_route_smoke(args, metrics, route_tracker)
        command_results.append(smoke_result)

    result = "blocked" if args.require_server and not phase11d_result.ok else "failed"
    if smoke_result and smoke_result.ok and metrics.steps_completed >= args.steps:
        sensors_ok = (
            not args.require_sensors
            or (metrics.collision_sensor_attached and metrics.lane_invasion_sensor_attached)
        )
        route_ok = not args.require_route_progress or route_tracker.route_progress_verified
        if not sensors_ok:
            result = "sensor_blocked"
        elif not route_ok:
            result = "route_progress_blocked"
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
        fallback_used=False,
        result=result,
    )
    metrics_dict.update({
        "phase": "Phase 11K",
        "metrics_scope": "fixed_route_spawn_pair_smoke_only_not_benchmark",
        "min_route_progress_m": args.min_route_progress_m,
    })
    metrics_dict.update(route_tracker.to_metrics_dict())
    metrics_dict["infraction_benchmark_verified"] = False
    metrics_dict["leaderboard_evaluated"] = False
    if args.run_regressions:
        metrics_dict["regression_passed"] = regression_passed

    carla_version = _read_pip_show_version(next((item.stdout for item in environment_results if item.name == "pip_show_carla"), ""))
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
    (run_dir / "commands.txt").write_text(_build_commands_text(args, command_results + regression_results), encoding="utf-8")
    (run_dir / "environment.txt").write_text(_build_text_report("# Phase 11K environment snapshot", environment_results), encoding="utf-8")
    (run_dir / "regression.txt").write_text(_build_text_report("# Phase 11K regression proof", command_results + regression_results), encoding="utf-8")

    if result == "passed":
        print(
            "Phase 11K Fixed Route Scenario Smoke Pass — route progress metrics generated for real CARLA spawn-pair smoke."
        )
        print(f"evidence_dir={run_dir}")
        return 0

    if result == "blocked":
        print("Phase 11K Blocked — real CARLA fixed-route smoke requires CARLA package and reachable CARLA server.")
    elif result == "sensor_blocked":
        print("Phase 11K Sensor Blocked — required CARLA metric sensors could not be attached.")
    elif result == "route_progress_blocked":
        print("Phase 11K Route Progress Blocked — route progress did not reach the required smoke threshold.")
    else:
        failing = next((item for item in command_results + regression_results if not item.ok), None)
        reason = f"{failing.name} exit={failing.returncode}" if failing else "unknown"
        print(f"Phase 11K Runtime Failed — fixed route smoke failed: {reason}")
    print(f"evidence_dir={run_dir}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

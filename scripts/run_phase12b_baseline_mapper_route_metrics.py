"""
Phase 12B-BASE-M baseline PlannerAction mapper route-metric runner.

This runner exercises the existing MA-VLNA closed-loop path:

    SemanticPlanner -> PlannerAction -> PlannerActionToCarlaControl -> CARLA VehicleControl

It adds structured route-progress evidence around that baseline mapper without
changing VLM, SafetyGate, SemanticPlanner, or the CARLA control mapper itself.
The result is smoke instrumentation only, not CARLA Leaderboard, not a formal
route benchmark, and not an infraction benchmark.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import io
import json
import logging
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
from workers.core.carla_metrics import CarlaRuntimeMetrics
from workers.core.carla_route_metrics import CarlaRouteProgressTracker
from workers.core.config import AgentConfig

DEFAULT_CARLA_ROOT = Path(os.environ.get("CARLA_ROOT", r"D:\CARLA\packages\CARLA_0.9.16"))
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runtime_logs" / "carla_runs"
BENCHMARK_BOUNDARY_SCOPE = "baseline_mapper_route_metrics_only_not_carla_leaderboard"


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
        agent_id="phase12b-baseline-planner-action-mapper",
        mode="carla",
        main_loop_hz=args.loop_hz,
        carla=carla_cfg,
        perception=perception_cfg,
        trigger=trigger_cfg,
        telemetry=telemetry_cfg,
        supabase=supabase_cfg,
    )


def _configure_baseline_route_scope(route_tracker: CarlaRouteProgressTracker) -> None:
    route_tracker.route_scope = "baseline_planner_action_mapper_spawn_pair_smoke_only_not_benchmark"
    route_tracker.route_completion_scope = (
        "baseline_planner_action_mapper_route_progress_only_not_completion_benchmark"
    )
    route_tracker.route_goal_reach_required = False
    route_tracker.route_completion_attempted = False


async def _run_baseline_mapper(
    args: argparse.Namespace,
    metrics: CarlaRuntimeMetrics,
    route_tracker: CarlaRouteProgressTracker,
) -> None:
    config = _build_config(args)
    agent = CarlaClosedLoopAgent(
        config=config,
        enable_vlm=args.enable_vlm,
        runtime_metrics=metrics,
        route_tracker=route_tracker,
        enable_metric_sensors=args.enable_metric_sensors,
        require_sensors=args.require_sensors,
    )
    await agent.run(max_steps=args.steps)


def _capture_baseline_mapper(
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
        asyncio.run(_run_baseline_mapper(args, metrics, route_tracker))
        returncode = 0
        stderr = ""
    except Exception as exc:
        returncode = 1
        stderr = str(exc)
        logging.getLogger(__name__).exception("Phase 12B-BASE-M baseline mapper route metrics failed")
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)

    return CommandResult(
        name="phase12b_baseline_mapper_route_metrics",
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
        "passed": "baseline_mapper_route_metrics_pass",
        "blocked": "baseline_mapper_route_metrics_server_blocked",
        "sensor_blocked": "baseline_mapper_route_metrics_sensor_blocked",
        "route_progress_blocked": "baseline_mapper_route_metrics_progress_blocked",
    }
    return {
        "phase": "Phase 12B-BASE-M",
        "status": status_map.get(result, "baseline_mapper_route_metrics_failed"),
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
        "route_completion_scope": route_metrics.get("route_completion_scope"),
        "route_town": route_metrics.get("route_town"),
        "carla_runtime_town": _runtime_town(args.town),
        "route_start_spawn_index": route_metrics.get("route_start_spawn_index"),
        "route_end_spawn_index": route_metrics.get("route_end_spawn_index"),
        "controller_mode": "baseline_planner_action_mapper",
        "controller_scope": "existing_planner_action_to_vehicle_control_mapper",
        "planner_mapper_modified": False,
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
        subprocess.list2cmdline([sys.executable, *sys.argv]),
        "",
    ]
    for result in results:
        lines.append(result.command_text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MA-VLNA Phase 12B-BASE-M baseline PlannerAction mapper route metrics"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--timeout-sec", type=float, default=30.0)
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--loop-hz", type=int, default=20)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--start-spawn-index", type=int, default=3)
    parser.add_argument("--end-spawn-index", type=int, default=30)
    parser.add_argument("--goal-tolerance-m", type=float, default=3.0)
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
    metrics.record_event(
        "baseline_mapper_route_metrics_enabled",
        None,
        controller_mode="baseline_planner_action_mapper",
        planner_mapper_modified=False,
        benchmark_boundary_scope=BENCHMARK_BOUNDARY_SCOPE,
        route_benchmark_verified=False,
        infraction_benchmark_verified=False,
        leaderboard_evaluated=False,
    )

    route_tracker = CarlaRouteProgressTracker(
        metrics=metrics,
        route_town=args.town,
        start_spawn_index=args.start_spawn_index,
        end_spawn_index=args.end_spawn_index,
        min_progress_m=args.min_route_progress_m,
        goal_tolerance_m=args.goal_tolerance_m,
    )
    _configure_baseline_route_scope(route_tracker)

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
        smoke_result = _capture_baseline_mapper(args, metrics, route_tracker)
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
                        "scripts\\run_phase12b_baseline_mapper_route_metrics.py",
                        "scripts\\run_phase12b_controller_ablation_experiment.py",
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
    metrics_dict.update(
        {
            "phase": "Phase 12B-BASE-M",
            "metrics_scope": "baseline_planner_action_mapper_route_metrics_only_not_benchmark",
            "controller_mode": "baseline_planner_action_mapper",
            "controller_scope": "existing_planner_action_to_vehicle_control_mapper",
            "planner_mapper_modified": False,
            "min_route_progress_m": args.min_route_progress_m,
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
        _build_text_report("# Phase 12B-BASE-M environment snapshot", environment_results),
        encoding="utf-8",
    )
    (run_dir / "regression.txt").write_text(
        _build_text_report("# Phase 12B-BASE-M regression proof", command_results + regression_results),
        encoding="utf-8",
    )

    if result == "passed":
        print(
            "Phase 12B-BASE-M Baseline Mapper Route-Metric Pass - structured route metrics generated for the baseline PlannerAction mapper."
        )
        print(f"evidence_dir={run_dir}")
        return 0

    if result == "blocked":
        print("Phase 12B-BASE-M Blocked - baseline mapper route metrics require CARLA package and reachable CARLA server.")
    elif result == "sensor_blocked":
        print("Phase 12B-BASE-M Sensor Blocked - required CARLA metric sensors could not be attached.")
    elif result == "route_progress_blocked":
        print("Phase 12B-BASE-M Route Progress Blocked - baseline mapper did not reach the required smoke progress threshold.")
    else:
        failing = next((item for item in command_results + regression_results if not item.ok), None)
        reason = f"{failing.name} exit={failing.returncode}" if failing else "unknown"
        print(f"Phase 12B-BASE-M Runtime Failed - baseline mapper route metrics failed: {reason}")
    print(f"evidence_dir={run_dir}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

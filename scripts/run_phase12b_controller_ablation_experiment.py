"""
Phase 12B controller ablation scaffold.

This runner prepares a 5-route x 3-controller command matrix for later CARLA
runtime work. Phase 12B is intentionally scaffold-only: the runner does not
import ``carla`` and does not launch any child CARLA runtime process.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "phase12"
DEFAULT_CARLA_ROOT = Path(os.environ.get("CARLA_ROOT", r"D:\CARLA\packages\CARLA_0.9.16"))
DEFAULT_CARLA_PYTHON = os.environ.get(
    "CARLA_PYTHON",
    r"D:\CARLA\envs\ma-vlna-carla312\python.exe",
)

PHASE = "Phase 12B"
STATUS_PREPARED = "controller_ablation_prepared"
BENCHMARK_BOUNDARY_SCOPE = "controller_ablation_scaffold_only_not_carla_leaderboard"

BOUNDARY_FIELDS = {
    "route_benchmark_verified": False,
    "infraction_benchmark_verified": False,
    "leaderboard_evaluated": False,
    "leaderboard_routes_exported": False,
    "leaderboard_route_criteria_evaluated": False,
}

SUMMARY_COLUMNS = (
    "route_id",
    "town",
    "start_spawn_index",
    "end_spawn_index",
    "controller_mode",
    "horizon_steps",
    "target_speed_kmh",
    "route_sampling_resolution_m",
    "lookahead_waypoints",
    "command",
    "runtime_command_status",
    "result",
    "exit_code",
    "fixed_route_goal_reached",
    "distance_to_goal_m",
    "route_progress_pct",
    "grp_route_progress_pct",
    "collision_count",
    "lane_invasion_count",
    "evidence_dir",
    "notes",
)


@dataclass(frozen=True)
class RouteSpec:
    route_id: str
    start_spawn_index: int
    end_spawn_index: int
    horizon_steps: int
    target_speed_kmh: float
    route_sampling_resolution_m: float
    lookahead_waypoints: int


@dataclass(frozen=True)
class ControllerSpec:
    mode: str
    source: str
    runtime_command_status: str
    notes: str


ROUTE_MATRIX = (
    RouteSpec("route_01", 3, 30, 2500, 18.0, 2.0, 8),
    RouteSpec("route_02", 8, 52, 2800, 18.0, 2.0, 8),
    RouteSpec("route_03", 12, 74, 2500, 18.0, 2.0, 8),
    RouteSpec("route_04", 25, 101, 2500, 18.0, 2.0, 8),
    RouteSpec("route_05", 40, 126, 5400, 8.0, 1.0, 3),
)

CONTROLLER_MATRIX = (
    ControllerSpec(
        mode="linear_spawn_pair_follower",
        source="scripts/run_phase11k_fixed_route_smoke.py",
        runtime_command_status="wired_route_progress_smoke_only",
        notes="Existing Phase 11K spawn-pair follower records route-progress smoke metrics; it is not a formal completion benchmark.",
    ),
    ControllerSpec(
        mode="grp_follower",
        source="scripts/run_phase11m_grp_route_following.py",
        runtime_command_status="wired_goal_reach_smoke",
        notes="Existing Phase 11M GRP-backed route follower is the calibrated goal-reach smoke path.",
    ),
    ControllerSpec(
        mode="baseline_planner_action_mapper",
        source="workers.CARLA_Closed_Loop_Agent",
        runtime_command_status="wired_closed_loop_mapper_only",
        notes="Existing closed-loop agent exercises PlannerAction-to-VehicleControl mapping, but has no fixed end-spawn route gate yet.",
    ),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def _resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _next_run_dir(output_dir: Path, timestamp: str) -> Path:
    candidate = output_dir / timestamp
    suffix = 1
    while candidate.exists():
        candidate = output_dir / f"{timestamp}-{suffix}"
        suffix += 1
    return candidate


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in SUMMARY_COLUMNS})


def _command_text(command: list[str]) -> str:
    return subprocess.list2cmdline(command)


def _route_output_dir(run_dir: Path, route: RouteSpec, controller: ControllerSpec) -> Path:
    return run_dir / "runs" / route.route_id / controller.mode


def _build_grp_command(args: argparse.Namespace, route: RouteSpec, output_dir: Path) -> list[str]:
    return [
        args.python_executable,
        str(REPO_ROOT / "scripts" / "run_phase11m_grp_route_following.py"),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--town",
        args.town,
        "--start-spawn-index",
        str(route.start_spawn_index),
        "--end-spawn-index",
        str(route.end_spawn_index),
        "--steps",
        str(route.horizon_steps),
        "--target-speed-kmh",
        str(route.target_speed_kmh),
        "--goal-tolerance-m",
        str(args.goal_tolerance_m),
        "--route-sampling-resolution-m",
        str(route.route_sampling_resolution_m),
        "--lookahead-waypoints",
        str(route.lookahead_waypoints),
        "--perception-backend",
        args.perception_backend,
        "--require-server",
        "--enable-metric-sensors",
        "--require-sensors",
        "--require-goal-reach",
        "--require-grp",
        "--output-dir",
        str(output_dir),
        "--carla-root",
        str(args.carla_root),
        "--base-python",
        args.base_python,
    ]


def _build_linear_command(args: argparse.Namespace, route: RouteSpec, output_dir: Path) -> list[str]:
    return [
        args.python_executable,
        str(REPO_ROOT / "scripts" / "run_phase11k_fixed_route_smoke.py"),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--town",
        args.town,
        "--start-spawn-index",
        str(route.start_spawn_index),
        "--end-spawn-index",
        str(route.end_spawn_index),
        "--steps",
        str(route.horizon_steps),
        "--perception-backend",
        args.perception_backend,
        "--require-server",
        "--enable-metric-sensors",
        "--require-sensors",
        "--require-route-progress",
        "--min-route-progress-m",
        str(args.min_route_progress_m),
        "--output-dir",
        str(output_dir),
        "--carla-root",
        str(args.carla_root),
        "--base-python",
        args.base_python,
    ]


def _build_baseline_mapper_command(args: argparse.Namespace, route: RouteSpec) -> list[str]:
    return [
        args.python_executable,
        "-m",
        "workers.CARLA_Closed_Loop_Agent",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--town",
        args.town,
        "--spawn-point-index",
        str(route.start_spawn_index),
        "--steps",
        str(route.horizon_steps),
        "--perception-backend",
        args.perception_backend,
    ]


def _build_controller_command(
    args: argparse.Namespace,
    route: RouteSpec,
    controller: ControllerSpec,
    output_dir: Path,
) -> list[str]:
    if controller.mode == "grp_follower":
        return _build_grp_command(args, route, output_dir)
    if controller.mode == "linear_spawn_pair_follower":
        return _build_linear_command(args, route, output_dir)
    if controller.mode == "baseline_planner_action_mapper":
        return _build_baseline_mapper_command(args, route)
    raise ValueError(f"unknown controller mode: {controller.mode}")


def _row_from_spec(
    args: argparse.Namespace,
    *,
    route: RouteSpec,
    controller: ControllerSpec,
    run_dir: Path,
) -> dict[str, Any]:
    output_dir = _route_output_dir(run_dir, route, controller)
    command = _build_controller_command(args, route, controller, output_dir)
    result = "dry_run" if args.dry_run else "not_executed"
    return {
        "route_id": route.route_id,
        "town": args.town,
        "start_spawn_index": route.start_spawn_index,
        "end_spawn_index": route.end_spawn_index,
        "controller_mode": controller.mode,
        "horizon_steps": route.horizon_steps,
        "target_speed_kmh": route.target_speed_kmh,
        "route_sampling_resolution_m": route.route_sampling_resolution_m,
        "lookahead_waypoints": route.lookahead_waypoints,
        "command": _command_text(command),
        "runtime_command_status": controller.runtime_command_status,
        "result": result,
        "exit_code": None,
        "fixed_route_goal_reached": None,
        "distance_to_goal_m": None,
        "route_progress_pct": None,
        "grp_route_progress_pct": None,
        "collision_count": None,
        "lane_invasion_count": None,
        "evidence_dir": None,
        "notes": controller.notes,
    }


def _build_rows(args: argparse.Namespace, run_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for route in ROUTE_MATRIX:
        for controller in CONTROLLER_MATRIX:
            rows.append(_row_from_spec(args, route=route, controller=controller, run_dir=run_dir))
    return rows


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(row["runtime_command_status"]) for row in rows))


def _summary_payload(args: argparse.Namespace, rows: list[dict[str, Any]]) -> dict[str, Any]:
    route_ids = sorted({str(row["route_id"]) for row in rows})
    controller_modes = sorted({str(row["controller_mode"]) for row in rows})
    dry_run_assertions = {
        "row_count_is_15": len(rows) == 15,
        "route_count_is_5": len(route_ids) == 5,
        "controller_count_is_3": len(controller_modes) == 3,
        "all_rows_are_dry_run": all(row["result"] == "dry_run" for row in rows),
        "all_boundary_fields_false": all(value is False for value in BOUNDARY_FIELDS.values()),
        "carla_import_required": False,
        "carla_server_required": False,
        "python312_required_for_dry_run": False,
    }
    return {
        "phase": PHASE,
        "status": STATUS_PREPARED if args.dry_run else "runtime_deferred",
        "dry_run": args.dry_run,
        "row_count": len(rows),
        "route_count": len(route_ids),
        "controller_count": len(controller_modes),
        "route_ids": route_ids,
        "controller_modes": controller_modes,
        "runtime_command_status_counts": _status_counts(rows),
        "continue_all_policy": True,
        "results": rows,
        "dry_run_assertions": dry_run_assertions,
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        **BOUNDARY_FIELDS,
        "benchmark_boundaries": dict(BOUNDARY_FIELDS),
    }


def _manifest_payload(
    args: argparse.Namespace,
    *,
    run_dir: Path,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = _summary_payload(args, rows)
    return {
        "phase": PHASE,
        "status": summary["status"],
        "created_at_utc": _utc_now().isoformat(),
        "run_dir": str(run_dir),
        "dry_run": args.dry_run,
        "output_files": [
            "manifest.json",
            "summary.csv",
            "summary.json",
            "commands.txt",
            "README.md",
        ],
        "town": args.town,
        "host": args.host,
        "port": args.port,
        "python_executable": args.python_executable,
        "base_python": args.base_python,
        "carla_root": str(args.carla_root),
        "route_matrix": [asdict(route) for route in ROUTE_MATRIX],
        "controller_matrix": [asdict(controller) for controller in CONTROLLER_MATRIX],
        "summary": {
            "row_count": summary["row_count"],
            "route_count": summary["route_count"],
            "controller_count": summary["controller_count"],
            "runtime_command_status_counts": summary["runtime_command_status_counts"],
        },
        "scaffold_only": True,
        "child_processes_launched": False,
        "carla_import_required": False,
        "carla_server_required_for_dry_run": False,
        "python312_required_for_dry_run": False,
        "raw_runtime_evidence_committed": False,
        "continue_all_policy": True,
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        **BOUNDARY_FIELDS,
    }


def _write_commands(path: Path, parent_command: list[str], rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Phase 12B parent command",
        _command_text(parent_command),
        "",
        "# Controller ablation child commands (not executed by Phase 12B dry-run)",
    ]
    for row in rows:
        lines.append(f"# {row['route_id']} / {row['controller_mode']} / {row['runtime_command_status']}")
        lines.append(str(row["command"]))
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_readme(path: Path, *, run_dir: Path, rows: list[dict[str, Any]], args: argparse.Namespace) -> None:
    summary = _summary_payload(args, rows)
    body = f"""# Phase 12B Controller Ablation Scaffold

Status:

```text
Phase 12B Controller Ablation Prepared - controller ablation matrix, dry-run scaffold, and summary aggregation are implemented.
```

This directory contains dry-run scaffold output only. No CARLA server was required,
no `carla` import was required, and no child CARLA runtime command was launched.

```text
dry_run={str(args.dry_run).lower()}
row_count={summary["row_count"]}
route_count={summary["route_count"]}
controller_count={summary["controller_count"]}
```

Boundary:

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Path:

```text
{run_dir.relative_to(REPO_ROOT).as_posix()}
```
"""
    path.write_text(body, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MA-VLNA Phase 12B controller ablation scaffold")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--goal-tolerance-m", type=float, default=3.0)
    parser.add_argument("--min-route-progress-m", type=float, default=0.5)
    parser.add_argument("--perception-backend", default="dummy", choices=["dummy", "yolo", "rtdetr"])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--python-executable", default=DEFAULT_CARLA_PYTHON)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.output_dir = _resolve_repo_path(args.output_dir)
    args.carla_root = _resolve_repo_path(args.carla_root)

    run_dir = _next_run_dir(args.output_dir, args.timestamp or _timestamp(_utc_now()))
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "runs").mkdir(exist_ok=True)

    rows = _build_rows(args, run_dir)
    _write_summary_csv(run_dir / "summary.csv", rows)
    _write_json(run_dir / "summary.json", _summary_payload(args, rows))
    _write_json(run_dir / "manifest.json", _manifest_payload(args, run_dir=run_dir, rows=rows))
    _write_commands(run_dir / "commands.txt", [sys.executable, *sys.argv], rows)
    _write_readme(run_dir / "README.md", run_dir=run_dir, rows=rows, args=args)

    if args.dry_run:
        print("Phase 12B Controller Ablation Prepared - dry-run scaffold written without launching CARLA.")
        print(f"experiment_dir={run_dir}")
        return 0

    print("Phase 12B Runtime Deferred - this phase is scaffold-only; rerun with --dry-run for the prepared matrix.")
    print(f"experiment_dir={run_dir}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

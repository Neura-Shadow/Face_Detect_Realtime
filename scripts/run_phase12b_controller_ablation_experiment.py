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
import time
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
    "steps_completed",
    "route_progress_verified",
    "fixed_route_goal_reached",
    "distance_to_goal_m",
    "route_progress_pct",
    "grp_route_progress_pct",
    "collision_count",
    "lane_invasion_count",
    "avg_speed_kmh",
    "max_speed_kmh",
    "distance_traveled_m",
    "evidence_dir",
    "runtime_execution_status",
    "duration_sec",
    "metrics_read_status",
    "stdout_path",
    "stderr_path",
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


@dataclass(frozen=True)
class MatrixEntry:
    route: RouteSpec
    controller: ControllerSpec
    command: list[str]
    output_dir: Path


@dataclass(frozen=True)
class RuntimeResult:
    entry: MatrixEntry
    exit_code: int | None
    duration_sec: float
    timed_out: bool
    stdout: str
    stderr: str
    evidence_dir: str | None
    metrics: dict[str, Any]
    stdout_path: str | None
    stderr_path: str | None


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
        source="scripts/run_phase12b_baseline_mapper_route_metrics.py",
        runtime_command_status="wired_baseline_mapper_route_metrics_smoke",
        notes="Phase 12B-BASE-M child runner exercises the existing PlannerAction-to-VehicleControl mapper and records fixed spawn-pair route metrics without modifying the mapper.",
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


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"json_read_error": f"file not found: {path}"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"json_read_error": str(exc)}


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


def _build_baseline_mapper_command(args: argparse.Namespace, route: RouteSpec, output_dir: Path) -> list[str]:
    return [
        args.python_executable,
        str(REPO_ROOT / "scripts" / "run_phase12b_baseline_mapper_route_metrics.py"),
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
        return _build_baseline_mapper_command(args, route, output_dir)
    raise ValueError(f"unknown controller mode: {controller.mode}")


def _matrix_entries(args: argparse.Namespace, run_dir: Path) -> list[MatrixEntry]:
    entries: list[MatrixEntry] = []
    for route in ROUTE_MATRIX:
        if args.route_id and route.route_id not in args.route_id:
            continue
        for controller in CONTROLLER_MATRIX:
            if args.controller_mode and controller.mode not in args.controller_mode:
                continue
            output_dir = _route_output_dir(run_dir, route, controller)
            command = _build_controller_command(args, route, controller, output_dir)
            entries.append(MatrixEntry(route=route, controller=controller, command=command, output_dir=output_dir))
    if args.runtime_row_limit and args.runtime_row_limit > 0:
        return entries[: args.runtime_row_limit]
    return entries


def _row_from_entry(args: argparse.Namespace, entry: MatrixEntry) -> dict[str, Any]:
    result = "dry_run" if args.dry_run else "not_executed"
    return {
        "route_id": entry.route.route_id,
        "town": args.town,
        "start_spawn_index": entry.route.start_spawn_index,
        "end_spawn_index": entry.route.end_spawn_index,
        "controller_mode": entry.controller.mode,
        "horizon_steps": entry.route.horizon_steps,
        "target_speed_kmh": entry.route.target_speed_kmh,
        "route_sampling_resolution_m": entry.route.route_sampling_resolution_m,
        "lookahead_waypoints": entry.route.lookahead_waypoints,
        "command": _command_text(entry.command),
        "runtime_command_status": entry.controller.runtime_command_status,
        "result": result,
        "exit_code": None,
        "steps_completed": None,
        "route_progress_verified": None,
        "fixed_route_goal_reached": None,
        "distance_to_goal_m": None,
        "route_progress_pct": None,
        "grp_route_progress_pct": None,
        "collision_count": None,
        "lane_invasion_count": None,
        "avg_speed_kmh": None,
        "max_speed_kmh": None,
        "distance_traveled_m": None,
        "evidence_dir": None,
        "runtime_execution_status": "not_started",
        "duration_sec": None,
        "metrics_read_status": None,
        "stdout_path": None,
        "stderr_path": None,
        "notes": entry.controller.notes,
    }


def _build_rows(args: argparse.Namespace, run_dir: Path) -> list[dict[str, Any]]:
    return [_row_from_entry(args, entry) for entry in _matrix_entries(args, run_dir)]


def _parse_evidence_dir(stdout: str, stderr: str) -> str | None:
    for line in (stdout + "\n" + stderr).splitlines():
        line = line.strip()
        if line.startswith("evidence_dir=") or line.startswith("experiment_dir="):
            return line.split("=", 1)[1].strip()
    return None


def _read_metrics(evidence_dir: str | None) -> dict[str, Any]:
    if not evidence_dir:
        return {}
    metrics_path = Path(evidence_dir) / "metrics.json"
    if metrics_path.exists():
        return _read_json(metrics_path)
    summary_path = Path(evidence_dir) / "summary.json"
    if summary_path.exists():
        return _read_json(summary_path)
    return {"json_read_error": f"no metrics.json or summary.json in {evidence_dir}"}


def _raw_output_stem(entry: MatrixEntry) -> str:
    return f"{entry.route.route_id}__{entry.controller.mode}"


def _write_raw_output(raw_dir: Path, entry: MatrixEntry, stdout: str, stderr: str) -> tuple[str, str]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    stem = _raw_output_stem(entry)
    stdout_path = raw_dir / f"{stem}.stdout.txt"
    stderr_path = raw_dir / f"{stem}.stderr.txt"
    stdout_path.write_text(stdout, encoding="utf-8", errors="replace")
    stderr_path.write_text(stderr, encoding="utf-8", errors="replace")
    return str(stdout_path), str(stderr_path)


def _run_child(entry: MatrixEntry, *, args: argparse.Namespace, raw_dir: Path, env: dict[str, str]) -> RuntimeResult:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            entry.command,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.child_timeout_sec,
            check=False,
        )
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        evidence_dir = _parse_evidence_dir(stdout, stderr)
        stdout_path, stderr_path = _write_raw_output(raw_dir, entry, stdout, stderr)
        return RuntimeResult(
            entry=entry,
            exit_code=completed.returncode,
            duration_sec=round(time.perf_counter() - started, 3),
            timed_out=False,
            stdout=stdout,
            stderr=stderr,
            evidence_dir=evidence_dir,
            metrics=_read_metrics(evidence_dir),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        evidence_dir = _parse_evidence_dir(stdout, stderr)
        stdout_path, stderr_path = _write_raw_output(raw_dir, entry, stdout.strip(), stderr.strip())
        return RuntimeResult(
            entry=entry,
            exit_code=124,
            duration_sec=round(time.perf_counter() - started, 3),
            timed_out=True,
            stdout=stdout.strip(),
            stderr=(stderr.strip() or f"timeout after {args.child_timeout_sec}s"),
            evidence_dir=evidence_dir,
            metrics=_read_metrics(evidence_dir),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
    except OSError as exc:
        stderr = str(exc)
        stdout_path, stderr_path = _write_raw_output(raw_dir, entry, "", stderr)
        return RuntimeResult(
            entry=entry,
            exit_code=127,
            duration_sec=round(time.perf_counter() - started, 3),
            timed_out=False,
            stdout="",
            stderr=stderr,
            evidence_dir=None,
            metrics={},
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )


def _runtime_result_name(result: RuntimeResult) -> str:
    metrics_result = result.metrics.get("result")
    if isinstance(metrics_result, str) and metrics_result:
        return metrics_result
    if result.timed_out:
        return "timeout"
    if result.exit_code == 0:
        return "passed_without_structured_metrics"
    if result.evidence_dir:
        return "blocked"
    return "failed"


def _row_from_runtime_result(args: argparse.Namespace, result: RuntimeResult) -> dict[str, Any]:
    row = _row_from_entry(args, result.entry)
    metrics = result.metrics
    metrics_read_status = "not_available"
    notes = result.entry.controller.notes
    if result.evidence_dir and metrics:
        metrics_read_status = "error" if metrics.get("json_read_error") else "loaded"
    if metrics.get("json_read_error"):
        notes = f"{notes} metrics_read_error={metrics['json_read_error']}"
    if result.timed_out:
        notes = f"{notes} child_timeout=true"
    elif result.exit_code not in (0, None) and not result.evidence_dir:
        notes = f"{notes} child_failed_without_evidence=true"

    row.update(
        {
            "result": _runtime_result_name(result),
            "exit_code": result.exit_code,
            "steps_completed": metrics.get("steps_completed"),
            "route_progress_verified": metrics.get("route_progress_verified"),
            "fixed_route_goal_reached": metrics.get("fixed_route_goal_reached"),
            "distance_to_goal_m": metrics.get("distance_to_goal_m"),
            "route_progress_pct": metrics.get("route_progress_pct"),
            "grp_route_progress_pct": metrics.get("grp_route_progress_pct"),
            "collision_count": metrics.get("collision_count"),
            "lane_invasion_count": metrics.get("lane_invasion_count"),
            "avg_speed_kmh": metrics.get("avg_speed_kmh"),
            "max_speed_kmh": metrics.get("max_speed_kmh"),
            "distance_traveled_m": metrics.get("distance_traveled_m"),
            "evidence_dir": result.evidence_dir,
            "runtime_execution_status": "timeout" if result.timed_out else "completed",
            "duration_sec": result.duration_sec,
            "metrics_read_status": metrics_read_status,
            "stdout_path": result.stdout_path,
            "stderr_path": result.stderr_path,
            "notes": notes,
        }
    )
    return row


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(row["runtime_command_status"]) for row in rows))


def _summary_payload(args: argparse.Namespace, rows: list[dict[str, Any]]) -> dict[str, Any]:
    route_ids = sorted({str(row["route_id"]) for row in rows})
    controller_modes = sorted({str(row["controller_mode"]) for row in rows})
    passed_count = sum(1 for row in rows if row.get("result") in {"passed", "passed_without_structured_metrics"} and row.get("exit_code") == 0)
    blocked_count = sum(1 for row in rows if row.get("result") in {"blocked", "goal_reach_blocked", "sensor_blocked", "grp_blocked", "route_progress_blocked"})
    failed_count = sum(1 for row in rows if row.get("result") in {"failed", "timeout"})
    executed_count = sum(1 for row in rows if row.get("runtime_execution_status") in {"completed", "timeout"})
    all_runtime_rows_passed = bool(args.execute_runtime) and len(rows) > 0 and passed_count == len(rows)
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
        "status": (
            STATUS_PREPARED
            if args.dry_run
            else "controller_ablation_runtime_passed"
            if all_runtime_rows_passed
            else "controller_ablation_runtime_blocked"
            if args.execute_runtime
            else "runtime_deferred"
        ),
        "dry_run": args.dry_run,
        "execute_runtime": args.execute_runtime,
        "row_count": len(rows),
        "route_count": len(route_ids),
        "controller_count": len(controller_modes),
        "route_ids": route_ids,
        "controller_modes": controller_modes,
        "runtime_command_status_counts": _status_counts(rows),
        "executed_row_count": executed_count,
        "passed_count": passed_count,
        "blocked_count": blocked_count,
        "failed_count": failed_count,
        "all_runtime_rows_passed": all_runtime_rows_passed,
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
        "execute_runtime": args.execute_runtime,
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
            "executed_row_count": summary["executed_row_count"],
            "passed_count": summary["passed_count"],
            "blocked_count": summary["blocked_count"],
            "failed_count": summary["failed_count"],
            "all_runtime_rows_passed": summary["all_runtime_rows_passed"],
        },
        "scaffold_only": not bool(args.execute_runtime),
        "runtime_wiring_enabled": bool(args.execute_runtime),
        "child_processes_launched": bool(args.execute_runtime),
        "child_timeout_sec": args.child_timeout_sec,
        "runtime_row_limit": args.runtime_row_limit,
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
    mode_text = (
        "This directory contains dry-run scaffold output only. No CARLA server was required, "
        "no `carla` import was required, and no child CARLA runtime command was launched."
        if args.dry_run
        else "This directory contains Phase 12B-R runtime wiring output. The parent runner did not import `carla`; "
        "child command stdout/stderr is stored under `raw_outputs/` and remains local by default."
    )
    body = f"""# Phase 12B Controller Ablation Scaffold

Status:

```text
Phase 12B Controller Ablation Prepared - controller ablation matrix, dry-run scaffold, and summary aggregation are implemented.
```

{mode_text}

```text
dry_run={str(args.dry_run).lower()}
execute_runtime={str(args.execute_runtime).lower()}
row_count={summary["row_count"]}
route_count={summary["route_count"]}
controller_count={summary["controller_count"]}
executed_row_count={summary["executed_row_count"]}
passed_count={summary["passed_count"]}
blocked_count={summary["blocked_count"]}
failed_count={summary["failed_count"]}
all_runtime_rows_passed={str(summary["all_runtime_rows_passed"]).lower()}
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
    parser.add_argument("--perception-backend", default="dummy", choices=["dummy", "yolo", "yolov9", "rtdetr"])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--python-executable", default=DEFAULT_CARLA_PYTHON)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute-runtime", action="store_true")
    parser.add_argument("--runtime-row-limit", type=int, default=0)
    parser.add_argument("--child-timeout-sec", type=float, default=900.0)
    parser.add_argument("--route-id", action="append", choices=[route.route_id for route in ROUTE_MATRIX])
    parser.add_argument("--controller-mode", action="append", choices=[controller.mode for controller in CONTROLLER_MATRIX])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.dry_run and args.execute_runtime:
        print("Phase 12B argument error - choose either --dry-run or --execute-runtime, not both.")
        return 2

    args.output_dir = _resolve_repo_path(args.output_dir)
    args.carla_root = _resolve_repo_path(args.carla_root)

    run_dir = _next_run_dir(args.output_dir, args.timestamp or _timestamp(_utc_now()))
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "runs").mkdir(exist_ok=True)

    if args.execute_runtime:
        raw_dir = run_dir / "raw_outputs"
        env = os.environ.copy()
        env["CARLA_ROOT"] = str(args.carla_root)
        env["PYTHONIOENCODING"] = "utf-8"
        rows = []
        for entry in _matrix_entries(args, run_dir):
            entry.output_dir.mkdir(parents=True, exist_ok=True)
            print(f"{entry.route.route_id}/{entry.controller.mode}: {_command_text(entry.command)}")
            result = _run_child(entry, args=args, raw_dir=raw_dir, env=env)
            rows.append(_row_from_runtime_result(args, result))
    else:
        rows = _build_rows(args, run_dir)

    _write_summary_csv(run_dir / "summary.csv", rows)
    summary = _summary_payload(args, rows)
    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "manifest.json", _manifest_payload(args, run_dir=run_dir, rows=rows))
    _write_commands(run_dir / "commands.txt", [sys.executable, *sys.argv], rows)
    _write_readme(run_dir / "README.md", run_dir=run_dir, rows=rows, args=args)

    if args.dry_run:
        print("Phase 12B Controller Ablation Prepared - dry-run scaffold written without launching CARLA.")
        print(f"experiment_dir={run_dir}")
        return 0

    if args.execute_runtime:
        if summary["all_runtime_rows_passed"]:
            print("Phase 12B-R Controller Ablation Runtime Pass - all requested controller rows passed.")
            print(f"experiment_dir={run_dir}")
            return 0
        print("Phase 12B-R Controller Ablation Runtime Blocked - one or more requested controller rows failed or were blocked.")
        print(f"experiment_dir={run_dir}")
        return 1

    print("Phase 12B Runtime Deferred - this phase is scaffold-only; rerun with --dry-run for the prepared matrix.")
    print(f"experiment_dir={run_dir}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

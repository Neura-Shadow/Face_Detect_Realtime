"""
Phase 12A CARLA route scaling experiment orchestrator.

此 runner 只負責批次呼叫既有 Phase 11M GRP route-following runner，
彙整 per-route metrics，並寫出 Phase 12A summary。它本身不 import carla、
不修改控制器、不宣稱 CARLA Leaderboard、正式 route benchmark 或
infraction benchmark。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "phase12"
DEFAULT_CARLA_ROOT = Path(os.environ.get("CARLA_ROOT", r"D:\CARLA\packages\CARLA_0.9.16"))
CHILD_RUNNER = REPO_ROOT / "scripts" / "run_phase11m_grp_route_following.py"
BENCHMARK_BOUNDARY_SCOPE = "phase12a_route_scaling_smoke_only_not_carla_leaderboard"

SUMMARY_COLUMNS = (
    "experiment_line",
    "route_id",
    "town",
    "start_spawn_index",
    "end_spawn_index",
    "controller",
    "perception_backend",
    "vlm_mode",
    "steps",
    "fixed_route_goal_reached",
    "distance_to_goal_m",
    "route_progress_pct",
    "grp_route_progress_pct",
    "collision_count",
    "lane_invasion_count",
    "avg_speed_kmh",
    "max_speed_kmh",
    "distance_traveled_m",
    "steps_completed",
    "timeout",
    "result",
    "exit_code",
    "evidence_dir",
    "notes",
)


@dataclass(frozen=True)
class RouteSpec:
    """Phase 12A 固定 spawn-pair route。"""

    route_id: str
    start_spawn_index: int
    end_spawn_index: int


@dataclass(frozen=True)
class ChildRunResult:
    """單一路線子程序執行結果。"""

    route: RouteSpec
    command: list[str]
    exit_code: int
    duration_sec: float
    timed_out: bool
    stdout: str
    stderr: str
    evidence_dir: str | None
    metrics: dict[str, Any]

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and self.metrics.get("result") == "passed"


ROUTE_MATRIX = (
    RouteSpec("route_01", 3, 30),
    RouteSpec("route_02", 8, 52),
    RouteSpec("route_03", 12, 74),
    RouteSpec("route_04", 25, 101),
    RouteSpec("route_05", 40, 126),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def _resolve_output_dir(path: Path) -> Path:
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


def _parse_evidence_dir(stdout: str, stderr: str) -> str | None:
    for line in (stdout + "\n" + stderr).splitlines():
        line = line.strip()
        if line.startswith("evidence_dir="):
            return line.split("=", 1)[1].strip()
    return None


def _read_metrics(evidence_dir: str | None) -> dict[str, Any]:
    if not evidence_dir:
        return {}
    metrics_path = Path(evidence_dir) / "metrics.json"
    if not metrics_path.exists():
        return {}
    try:
        return json.loads(metrics_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"metrics_read_error": str(exc)}


def _build_child_command(args: argparse.Namespace, route: RouteSpec, route_output_dir: Path) -> list[str]:
    command = [
        args.python_executable,
        str(CHILD_RUNNER),
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
        str(args.steps),
        "--target-speed-kmh",
        str(args.target_speed_kmh),
        "--goal-tolerance-m",
        str(args.goal_tolerance_m),
        "--route-sampling-resolution-m",
        str(args.route_sampling_resolution_m),
        "--lookahead-waypoints",
        str(args.lookahead_waypoints),
        "--perception-backend",
        args.perception_backend,
        "--require-server",
        "--enable-metric-sensors",
        "--require-sensors",
        "--require-goal-reach",
        "--require-grp",
        "--output-dir",
        str(route_output_dir),
        "--carla-root",
        str(args.carla_root),
        "--base-python",
        args.base_python,
    ]
    return command


def _run_child(command: list[str], route: RouteSpec, *, timeout_sec: float, env: dict[str, str]) -> ChildRunResult:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        evidence_dir = _parse_evidence_dir(stdout, stderr)
        return ChildRunResult(
            route=route,
            command=command,
            exit_code=completed.returncode,
            duration_sec=round(time.perf_counter() - started, 3),
            timed_out=False,
            stdout=stdout,
            stderr=stderr,
            evidence_dir=evidence_dir,
            metrics=_read_metrics(evidence_dir),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return ChildRunResult(
            route=route,
            command=command,
            exit_code=124,
            duration_sec=round(time.perf_counter() - started, 3),
            timed_out=True,
            stdout=stdout.strip(),
            stderr=(stderr.strip() or f"timeout after {timeout_sec}s"),
            evidence_dir=_parse_evidence_dir(stdout, stderr),
            metrics={},
        )


def _dry_run_result(route: RouteSpec, command: list[str]) -> ChildRunResult:
    return ChildRunResult(
        route=route,
        command=command,
        exit_code=0,
        duration_sec=0.0,
        timed_out=False,
        stdout="dry run; command not executed",
        stderr="",
        evidence_dir=None,
        metrics={
            "result": "dry_run",
            "fixed_route_goal_reached": None,
            "distance_to_goal_m": None,
            "route_progress_pct": None,
            "grp_route_progress_pct": None,
            "collision_count": None,
            "lane_invasion_count": None,
            "avg_speed_kmh": None,
            "max_speed_kmh": None,
            "distance_traveled_m": None,
            "steps_completed": 0,
        },
    )


def _row_from_result(result: ChildRunResult, args: argparse.Namespace) -> dict[str, Any]:
    metrics = result.metrics
    status = metrics.get("result") or ("timeout" if result.timed_out else "failed")
    notes = ""
    if metrics.get("metrics_read_error"):
        notes = f"metrics_read_error={metrics['metrics_read_error']}"
    elif result.timed_out:
        notes = "child runner timed out"
    elif result.exit_code != 0 and not result.evidence_dir:
        notes = "child runner failed before evidence_dir was reported"

    return {
        "experiment_line": "A",
        "route_id": result.route.route_id,
        "town": args.town,
        "start_spawn_index": result.route.start_spawn_index,
        "end_spawn_index": result.route.end_spawn_index,
        "controller": "grp_follower",
        "perception_backend": args.perception_backend,
        "vlm_mode": "disabled",
        "steps": args.steps,
        "fixed_route_goal_reached": metrics.get("fixed_route_goal_reached"),
        "distance_to_goal_m": metrics.get("distance_to_goal_m"),
        "route_progress_pct": metrics.get("route_progress_pct"),
        "grp_route_progress_pct": metrics.get("grp_route_progress_pct"),
        "collision_count": metrics.get("collision_count"),
        "lane_invasion_count": metrics.get("lane_invasion_count"),
        "avg_speed_kmh": metrics.get("avg_speed_kmh"),
        "max_speed_kmh": metrics.get("max_speed_kmh"),
        "distance_traveled_m": metrics.get("distance_traveled_m"),
        "steps_completed": metrics.get("steps_completed"),
        "timeout": result.timed_out,
        "result": status,
        "exit_code": result.exit_code,
        "evidence_dir": result.evidence_dir,
        "notes": notes,
    }


def _build_manifest(
    args: argparse.Namespace,
    *,
    run_dir: Path,
    rows: list[dict[str, Any]],
    all_routes_passed: bool,
) -> dict[str, Any]:
    return {
        "phase": "Phase 12A",
        "status": "route_scaling_passed" if all_routes_passed else "route_scaling_blocked",
        "created_at_utc": _utc_now().isoformat(),
        "run_dir": str(run_dir),
        "dry_run": args.dry_run,
        "child_runner": str(CHILD_RUNNER),
        "python_executable": args.python_executable,
        "host": args.host,
        "port": args.port,
        "town": args.town,
        "route_count": len(ROUTE_MATRIX),
        "routes": [asdict(route) for route in ROUTE_MATRIX],
        "default_settings": {
            "steps": args.steps,
            "target_speed_kmh": args.target_speed_kmh,
            "goal_tolerance_m": args.goal_tolerance_m,
            "route_sampling_resolution_m": args.route_sampling_resolution_m,
            "lookahead_waypoints": args.lookahead_waypoints,
            "perception_backend": args.perception_backend,
            "require_server": True,
            "require_sensors": True,
            "require_goal_reach": True,
            "require_grp": True,
        },
        "summary": {
            "row_count": len(rows),
            "passed_count": sum(1 for row in rows if row["result"] == "passed" and row["exit_code"] == 0),
            "blocked_or_failed_count": sum(1 for row in rows if not (row["result"] == "passed" and row["exit_code"] == 0)),
            "all_routes_passed": all_routes_passed,
        },
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        "leaderboard_routes_exported": False,
        "leaderboard_route_criteria_evaluated": False,
        "route_benchmark_verified": False,
        "infraction_benchmark_verified": False,
        "leaderboard_evaluated": False,
    }


def _build_summary_json(rows: list[dict[str, Any]], *, all_routes_passed: bool, dry_run: bool) -> dict[str, Any]:
    return {
        "phase": "Phase 12A",
        "experiment_line": "A",
        "dry_run": dry_run,
        "row_count": len(rows),
        "all_routes_passed": all_routes_passed,
        "passed_count": sum(1 for row in rows if row["result"] == "passed" and row["exit_code"] == 0),
        "results": rows,
        "benchmark_boundaries": {
            "route_benchmark_verified": False,
            "infraction_benchmark_verified": False,
            "leaderboard_evaluated": False,
            "leaderboard_routes_exported": False,
            "leaderboard_route_criteria_evaluated": False,
        },
    }


def _write_commands(path: Path, parent_command: list[str], child_results: list[ChildRunResult]) -> None:
    lines = [
        "# Phase 12A parent command",
        subprocess.list2cmdline(parent_command),
        "",
        "# Phase 11M child commands",
    ]
    for result in child_results:
        lines.append(f"# {result.route.route_id}")
        lines.append(subprocess.list2cmdline(result.command))
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_readme(path: Path, *, run_dir: Path, rows: list[dict[str, Any]], dry_run: bool) -> None:
    passed_count = sum(1 for row in rows if row["result"] == "passed" and row["exit_code"] == 0)
    body = f"""# Phase 12A Route Scaling Experiment

This directory contains the Phase 12A route-scaling summary.

## Status

```text
dry_run={str(dry_run).lower()}
route_count={len(rows)}
passed_count={passed_count}
```

## Boundary

This is controlled multi-route smoke evidence only. It is not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

## Files

- `manifest.json`: route matrix, runtime settings, and benchmark boundary fields.
- `summary.csv`: per-route summary table.
- `summary.json`: per-route summary payload.
- `commands.txt`: parent and child commands.
- `runs/`: per-route Phase 11M evidence directories.

Path:

```text
{run_dir.relative_to(REPO_ROOT).as_posix()}
```
"""
    path.write_text(body, encoding="utf-8")


def _prepare_run_dir(args: argparse.Namespace) -> Path:
    output_dir = _resolve_output_dir(args.output_dir)
    return _next_run_dir(output_dir, args.timestamp or _timestamp(_utc_now()))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MA-VLNA Phase 12A CARLA route scaling experiment")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--steps", type=int, default=2500)
    parser.add_argument("--target-speed-kmh", type=float, default=18.0)
    parser.add_argument("--goal-tolerance-m", type=float, default=3.0)
    parser.add_argument("--route-sampling-resolution-m", type=float, default=2.0)
    parser.add_argument("--lookahead-waypoints", type=int, default=8)
    parser.add_argument("--perception-backend", default="dummy", choices=["dummy", "yolo", "yolov9", "rtdetr"])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--route-timeout-sec", type=float, default=1800.0)
    parser.add_argument("--run-regressions-once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.carla_root = args.carla_root.resolve()
    run_dir = _prepare_run_dir(args)
    run_dir.mkdir(parents=True, exist_ok=False)
    runs_dir = run_dir / "runs"
    runs_dir.mkdir()

    env = os.environ.copy()
    env["CARLA_ROOT"] = str(args.carla_root)
    env["PYTHONIOENCODING"] = "utf-8"

    child_results: list[ChildRunResult] = []
    for index, route in enumerate(ROUTE_MATRIX):
        route_output_dir = runs_dir / route.route_id
        route_output_dir.mkdir(parents=True, exist_ok=True)
        command = _build_child_command(args, route, route_output_dir)
        if args.run_regressions_once and index == 0:
            command.append("--run-regressions")

        print(f"{route.route_id}: {subprocess.list2cmdline(command)}")
        if args.dry_run:
            child_results.append(_dry_run_result(route, command))
            continue

        child_results.append(
            _run_child(
                command,
                route,
                timeout_sec=args.route_timeout_sec,
                env=env,
            )
        )

    rows = [_row_from_result(result, args) for result in child_results]
    all_routes_passed = (not args.dry_run) and len(rows) == len(ROUTE_MATRIX) and all(
        row["result"] == "passed" and row["exit_code"] == 0 for row in rows
    )

    _write_summary_csv(run_dir / "summary.csv", rows)
    _write_json(run_dir / "summary.json", _build_summary_json(rows, all_routes_passed=all_routes_passed, dry_run=args.dry_run))
    _write_json(run_dir / "manifest.json", _build_manifest(args, run_dir=run_dir, rows=rows, all_routes_passed=all_routes_passed))
    _write_commands(run_dir / "commands.txt", [sys.executable, *sys.argv], child_results)
    _write_readme(run_dir / "README.md", run_dir=run_dir, rows=rows, dry_run=args.dry_run)

    if args.dry_run:
        print("Phase 12A Route Scaling Dry Run — child commands written without launching CARLA.")
        print(f"experiment_dir={run_dir}")
        return 0

    if all_routes_passed:
        print("Phase 12A Route Scaling Pass — all fixed spawn-pair smoke routes passed.")
        print(f"experiment_dir={run_dir}")
        return 0

    print("Phase 12A Route Scaling Blocked — one or more fixed spawn-pair smoke routes failed or were blocked.")
    print(f"experiment_dir={run_dir}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

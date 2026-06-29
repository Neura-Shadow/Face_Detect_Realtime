"""
Phase 12A-C calibrated 5-route runtime confirmation.

此 runner 讀取 Phase 12A-H horizon calibration summary，逐條呼叫既有
Phase 11M GRP route-following runner，以 calibrated per-route horizon
確認五條固定 Town03 routes。它本身不 import carla、不修改控制器、
不宣稱 CARLA Leaderboard、正式 route benchmark 或 infraction benchmark。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "phase12"
DEFAULT_CALIBRATION_SUMMARY_PATH = REPO_ROOT / "experiments" / "phase12" / "20260620T140648Z" / "summary.json"
DEFAULT_CARLA_ROOT = Path(os.environ.get("CARLA_ROOT", r"D:\CARLA\packages\CARLA_0.9.16"))
CHILD_RUNNER = REPO_ROOT / "scripts" / "run_phase11m_grp_route_following.py"
BENCHMARK_BOUNDARY_SCOPE = "phase12a_c_calibrated_route_confirmation_smoke_only_not_carla_leaderboard"

SUMMARY_COLUMNS = (
    "route_id",
    "town",
    "start_spawn_index",
    "end_spawn_index",
    "calibration_source",
    "calibration_goal_reach_step",
    "calibrated_horizon_steps",
    "target_speed_kmh",
    "route_sampling_resolution_m",
    "lookahead_waypoints",
    "steps_completed",
    "result",
    "exit_code",
    "fixed_route_goal_reached",
    "goal_reach_step",
    "distance_to_goal_m",
    "route_progress_pct",
    "grp_route_progress_pct",
    "collision_count",
    "lane_invasion_count",
    "avg_speed_kmh",
    "max_speed_kmh",
    "distance_traveled_m",
    "confirmation_status",
    "timeout",
    "duration_sec",
    "evidence_dir",
    "notes",
)


@dataclass(frozen=True)
class CalibratedRoute:
    """由 Phase 12A-H 產生的單一路線確認設定。"""

    route_id: str
    start_spawn_index: int
    end_spawn_index: int
    horizon_steps: int
    target_speed_kmh: float
    route_sampling_resolution_m: float
    lookahead_waypoints: int
    calibration_source: str
    calibration_goal_reach_step: int | None


@dataclass(frozen=True)
class ChildRunResult:
    """單一路線 Phase 11M 子程序結果。"""

    route: CalibratedRoute
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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def _resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _next_run_dir(output_dir: Path, timestamp: str) -> Path:
    candidate = output_dir / timestamp
    suffix = 1
    while candidate.exists():
        candidate = output_dir / f"{timestamp}-{suffix}"
        suffix += 1
    return candidate


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"json_read_error": f"file not found: {path}"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"json_read_error": str(exc)}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in SUMMARY_COLUMNS})


def _safe_int(value: Any, *, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, *, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_calibrated_routes(path: Path) -> list[CalibratedRoute]:
    payload = _read_json(path)
    if payload.get("json_read_error"):
        raise RuntimeError(str(payload["json_read_error"]))

    routes: list[CalibratedRoute] = []
    for row in payload.get("results", []) or []:
        if row.get("calibration_status") != "calibrated":
            continue
        route_id = str(row["route_id"])
        horizon = _safe_int(row.get("recommended_horizon_steps"))
        start = _safe_int(row.get("start_spawn_index"))
        end = _safe_int(row.get("end_spawn_index"))
        target_speed = _safe_float(row.get("target_speed_kmh"))
        sampling = _safe_float(row.get("route_sampling_resolution_m"))
        lookahead = _safe_int(row.get("lookahead_waypoints"))
        if None in (horizon, start, end, target_speed, sampling, lookahead):
            raise RuntimeError(f"calibration row is incomplete for {route_id}")
        routes.append(
            CalibratedRoute(
                route_id=route_id,
                start_spawn_index=int(start),
                end_spawn_index=int(end),
                horizon_steps=int(horizon),
                target_speed_kmh=float(target_speed),
                route_sampling_resolution_m=float(sampling),
                lookahead_waypoints=int(lookahead),
                calibration_source=str(row.get("calibration_source") or "unknown"),
                calibration_goal_reach_step=_safe_int(row.get("goal_reach_step")),
            )
        )

    routes.sort(key=lambda item: item.route_id)
    if len(routes) != 5:
        raise RuntimeError(f"expected 5 calibrated routes, found {len(routes)}")
    return routes


def _parse_evidence_dir(stdout: str, stderr: str) -> str | None:
    for line in (stdout + "\n" + stderr).splitlines():
        line = line.strip()
        if line.startswith("evidence_dir="):
            return line.split("=", 1)[1].strip()
    return None


def _read_metrics(evidence_dir: str | None) -> dict[str, Any]:
    if not evidence_dir:
        return {}
    return _read_json(Path(evidence_dir) / "metrics.json")


def _build_child_command(args: argparse.Namespace, route: CalibratedRoute, route_output_dir: Path) -> list[str]:
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
        str(route_output_dir),
        "--carla-root",
        str(args.carla_root),
        "--base-python",
        args.base_python,
    ]
    return command


def _run_child(command: list[str], route: CalibratedRoute, *, timeout_sec: float, env: dict[str, str]) -> ChildRunResult:
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
        evidence_dir = _parse_evidence_dir(stdout, stderr)
        return ChildRunResult(
            route=route,
            command=command,
            exit_code=124,
            duration_sec=round(time.perf_counter() - started, 3),
            timed_out=True,
            stdout=stdout.strip(),
            stderr=(stderr.strip() or f"timeout after {timeout_sec}s"),
            evidence_dir=evidence_dir,
            metrics=_read_metrics(evidence_dir),
        )


def _dry_run_result(route: CalibratedRoute, command: list[str]) -> ChildRunResult:
    return ChildRunResult(
        route=route,
        command=command,
        exit_code=0,
        duration_sec=0.0,
        timed_out=False,
        stdout="dry run; command not executed",
        stderr="",
        evidence_dir=None,
        metrics={"result": "dry_run", "steps_requested": route.horizon_steps},
    )


def _row_from_result(result: ChildRunResult, args: argparse.Namespace) -> dict[str, Any]:
    metrics = result.metrics
    status = metrics.get("result") or ("timeout" if result.timed_out else "failed")
    fixed_route_goal_reached = metrics.get("fixed_route_goal_reached")
    confirmation_ok = result.exit_code == 0 and status == "passed" and fixed_route_goal_reached is True
    notes = ""
    if metrics.get("json_read_error"):
        notes = f"metrics_read_error={metrics['json_read_error']}"
    elif result.timed_out:
        notes = "child runner timed out"
    elif result.exit_code != 0 and not result.evidence_dir:
        notes = "child runner failed before evidence_dir was reported"

    return {
        "route_id": result.route.route_id,
        "town": args.town,
        "start_spawn_index": result.route.start_spawn_index,
        "end_spawn_index": result.route.end_spawn_index,
        "calibration_source": result.route.calibration_source,
        "calibration_goal_reach_step": result.route.calibration_goal_reach_step,
        "calibrated_horizon_steps": result.route.horizon_steps,
        "target_speed_kmh": result.route.target_speed_kmh,
        "route_sampling_resolution_m": result.route.route_sampling_resolution_m,
        "lookahead_waypoints": result.route.lookahead_waypoints,
        "steps_completed": metrics.get("steps_completed"),
        "result": status,
        "exit_code": result.exit_code,
        "fixed_route_goal_reached": fixed_route_goal_reached,
        "goal_reach_step": metrics.get("goal_reach_step"),
        "distance_to_goal_m": metrics.get("distance_to_goal_m"),
        "route_progress_pct": metrics.get("route_progress_pct"),
        "grp_route_progress_pct": metrics.get("grp_route_progress_pct"),
        "collision_count": metrics.get("collision_count"),
        "lane_invasion_count": metrics.get("lane_invasion_count"),
        "avg_speed_kmh": metrics.get("avg_speed_kmh"),
        "max_speed_kmh": metrics.get("max_speed_kmh"),
        "distance_traveled_m": metrics.get("distance_traveled_m"),
        "confirmation_status": "confirmed" if confirmation_ok else status,
        "timeout": result.timed_out,
        "duration_sec": result.duration_sec,
        "evidence_dir": result.evidence_dir,
        "notes": notes,
    }


def _summary_payload(rows: list[dict[str, Any]], *, dry_run: bool) -> dict[str, Any]:
    confirmed = [
        row
        for row in rows
        if row.get("confirmation_status") == "confirmed"
        and row.get("exit_code") == 0
        and row.get("fixed_route_goal_reached") is True
    ]
    all_routes_confirmed = (not dry_run) and len(rows) == 5 and len(confirmed) == 5
    return {
        "phase": "Phase 12A-C",
        "experiment_line": "C",
        "dry_run": dry_run,
        "row_count": len(rows),
        "confirmed_route_count": len(confirmed),
        "all_routes_confirmed": all_routes_confirmed,
        "results": rows,
        "benchmark_boundaries": {
            "route_benchmark_verified": False,
            "infraction_benchmark_verified": False,
            "leaderboard_evaluated": False,
            "leaderboard_routes_exported": False,
            "leaderboard_route_criteria_evaluated": False,
        },
    }


def _manifest_payload(
    args: argparse.Namespace,
    *,
    run_dir: Path,
    routes: list[CalibratedRoute],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = _summary_payload(rows, dry_run=args.dry_run)
    return {
        "phase": "Phase 12A-C",
        "status": "calibrated_route_confirmation_pass"
        if summary["all_routes_confirmed"]
        else "calibrated_route_confirmation_blocked",
        "created_at_utc": _utc_now().isoformat(),
        "run_dir": str(run_dir),
        "dry_run": args.dry_run,
        "calibration_summary_path": str(args.calibration_summary_path),
        "child_runner": str(CHILD_RUNNER),
        "python_executable": args.python_executable,
        "host": args.host,
        "port": args.port,
        "town": args.town,
        "routes": [route.__dict__ for route in routes],
        "summary": {
            "row_count": summary["row_count"],
            "confirmed_route_count": summary["confirmed_route_count"],
            "all_routes_confirmed": summary["all_routes_confirmed"],
        },
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        "leaderboard_routes_exported": False,
        "leaderboard_route_criteria_evaluated": False,
        "route_benchmark_verified": False,
        "infraction_benchmark_verified": False,
        "leaderboard_evaluated": False,
    }


def _write_commands(path: Path, parent_command: list[str], child_results: list[ChildRunResult]) -> None:
    lines = ["# Phase 12A-C parent command", subprocess.list2cmdline(parent_command), ""]
    lines.append("# Phase 11M calibrated child commands")
    for result in child_results:
        lines.append(f"# {result.route.route_id}")
        lines.append(subprocess.list2cmdline(result.command))
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_readme(path: Path, *, run_dir: Path, rows: list[dict[str, Any]], dry_run: bool) -> None:
    summary = _summary_payload(rows, dry_run=dry_run)
    body = f"""# Phase 12A-C Calibrated Route Confirmation

This directory contains calibrated 5-route runtime confirmation output.

```text
dry_run={str(dry_run).lower()}
row_count={summary["row_count"]}
confirmed_route_count={summary["confirmed_route_count"]}
all_routes_confirmed={str(summary["all_routes_confirmed"]).lower()}
```

This is calibrated smoke confirmation only. It is not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

Path:

```text
{run_dir.relative_to(REPO_ROOT).as_posix()}
```
"""
    path.write_text(body, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MA-VLNA Phase 12A-C calibrated 5-route confirmation")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--goal-tolerance-m", type=float, default=3.0)
    parser.add_argument("--perception-backend", default="dummy", choices=["dummy", "yolo", "yolov9", "rtdetr"])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--calibration-summary-path", type=Path, default=DEFAULT_CALIBRATION_SUMMARY_PATH)
    parser.add_argument("--route-timeout-sec", type=float, default=2400.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.carla_root = _resolve_path(args.carla_root).resolve()
    args.calibration_summary_path = _resolve_path(args.calibration_summary_path)
    output_dir = _resolve_path(args.output_dir)
    run_dir = _next_run_dir(output_dir, args.timestamp or _timestamp(_utc_now()))
    run_dir.mkdir(parents=True, exist_ok=False)
    runs_dir = run_dir / "runs"
    runs_dir.mkdir()

    routes = _load_calibrated_routes(args.calibration_summary_path)
    env = os.environ.copy()
    env["CARLA_ROOT"] = str(args.carla_root)
    env["PYTHONIOENCODING"] = "utf-8"

    child_results: list[ChildRunResult] = []
    for route in routes:
        route_output_dir = runs_dir / route.route_id
        route_output_dir.mkdir(parents=True, exist_ok=True)
        command = _build_child_command(args, route, route_output_dir)
        print(f"{route.route_id}: {subprocess.list2cmdline(command)}")
        if args.dry_run:
            child_results.append(_dry_run_result(route, command))
            continue
        child_results.append(
            _run_child(command, route, timeout_sec=args.route_timeout_sec, env=env)
        )

    rows = [_row_from_result(result, args) for result in child_results]
    summary = _summary_payload(rows, dry_run=args.dry_run)
    _write_summary_csv(run_dir / "summary.csv", rows)
    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "manifest.json", _manifest_payload(args, run_dir=run_dir, routes=routes, rows=rows))
    _write_commands(run_dir / "commands.txt", [sys.executable, *sys.argv], child_results)
    _write_readme(run_dir / "README.md", run_dir=run_dir, rows=rows, dry_run=args.dry_run)

    if args.dry_run:
        print("Phase 12A-C Calibrated Route Confirmation Dry Run — child commands written without launching CARLA.")
        print(f"experiment_dir={run_dir}")
        return 0

    if summary["all_routes_confirmed"]:
        print("Phase 12A-C Calibrated Route Confirmation Pass — all five calibrated fixed routes reached the goal.")
        print(f"experiment_dir={run_dir}")
        return 0

    print("Phase 12A-C Calibrated Route Confirmation Blocked — one or more calibrated routes failed or were blocked.")
    print(f"experiment_dir={run_dir}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

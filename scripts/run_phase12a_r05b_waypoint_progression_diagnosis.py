"""
Phase 12A-R05B late-route waypoint progression diagnosis.

此 runner 只做診斷與 evidence 聚合：它讀取 Phase 12A-R05 最佳
`r05_slow_short_lookahead` evidence，量化 late-route waypoint progression，
並可選擇呼叫既有 Phase 11M GRP runner 執行 extended-step 驗證。它本身
不 import carla、不修改 GRP controller、不宣稱 CARLA Leaderboard、
正式 route benchmark 或 infraction benchmark。
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
DEFAULT_CARLA_ROOT = Path(os.environ.get("CARLA_ROOT", r"D:\CARLA\packages\CARLA_0.9.16"))
DEFAULT_SOURCE_EVIDENCE_DIR = (
    REPO_ROOT
    / "experiments"
    / "phase12"
    / "20260620T110904Z"
    / "runs"
    / "r05_slow_short_lookahead"
    / "20260620T111202Z"
)
CHILD_RUNNER = REPO_ROOT / "scripts" / "run_phase11m_grp_route_following.py"
BENCHMARK_BOUNDARY_SCOPE = "phase12a_r05b_waypoint_progression_smoke_only_not_carla_leaderboard"

SUMMARY_COLUMNS = (
    "run_id",
    "source",
    "town",
    "start_spawn_index",
    "end_spawn_index",
    "target_speed_kmh",
    "route_sampling_resolution_m",
    "lookahead_waypoints",
    "steps_requested",
    "steps_completed",
    "result",
    "exit_code",
    "fixed_route_goal_reached",
    "distance_to_goal_m",
    "route_progress_pct",
    "grp_route_progress_pct",
    "grp_current_waypoint_index",
    "grp_remaining_waypoints",
    "collision_count",
    "lane_invasion_count",
    "final_window_steps",
    "final_window_grp_index_delta",
    "final_window_grp_progress_m_delta",
    "final_window_route_progress_m_delta",
    "final_window_distance_to_goal_m_delta",
    "final_window_avg_speed_kmh",
    "last_waypoint_change_step",
    "longest_waypoint_stagnation_steps",
    "estimated_extra_steps_to_goal",
    "estimated_total_steps_to_goal",
    "waypoint_progression_status",
    "late_route_progression_diagnosed",
    "step_budget_limited_likely",
    "evidence_dir",
    "notes",
)


@dataclass(frozen=True)
class ChildRunResult:
    """Phase 11M 子程序執行結果。"""

    command: list[str]
    exit_code: int
    duration_sec: float
    timed_out: bool
    stdout: str
    stderr: str
    evidence_dir: str | None


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
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"json_read_error": str(exc)}


def _read_events(evidence_dir: Path) -> tuple[list[dict[str, Any]], str | None]:
    events_path = evidence_dir / "events.jsonl"
    if not events_path.exists():
        return [], f"events not found: {events_path}"

    events: list[dict[str, Any]] = []
    try:
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
    except Exception as exc:
        return events, str(exc)
    return events, None


def _events_of(events: list[dict[str, Any]], event_name: str) -> list[dict[str, Any]]:
    return [event for event in events if event.get("event") == event_name and event.get("step") is not None]


def _final_window(items: list[dict[str, Any]], *, final_step: int, window_steps: int) -> list[dict[str, Any]]:
    first_step = max(0, final_step - window_steps + 1)
    return [item for item in items if int(item.get("step", -1)) >= first_step]


def _last_waypoint_change(grp_events: list[dict[str, Any]]) -> tuple[int | None, int]:
    if not grp_events:
        return None, 0

    last_change_step: int | None = None
    previous_index = int(grp_events[0].get("grp_current_waypoint_index", 0))
    longest_span = 1
    current_span = 1
    for event in grp_events[1:]:
        index = int(event.get("grp_current_waypoint_index", previous_index))
        if index != previous_index:
            last_change_step = int(event["step"])
            previous_index = index
            longest_span = max(longest_span, current_span)
            current_span = 1
        else:
            current_span += 1
    longest_span = max(longest_span, current_span)
    return last_change_step, longest_span


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _delta(first: dict[str, Any], last: dict[str, Any], key: str) -> float | None:
    start = _safe_float(first.get(key))
    end = _safe_float(last.get(key))
    if start is None or end is None:
        return None
    return end - start


def _distance_to_goal_delta(first: dict[str, Any], last: dict[str, Any]) -> float | None:
    start = _safe_float(first.get("distance_to_goal_m"))
    end = _safe_float(last.get("distance_to_goal_m"))
    if start is None or end is None:
        return None
    return start - end


def _estimate_extra_steps_to_goal(
    route_window: list[dict[str, Any]],
    *,
    final_distance_to_goal_m: float | None,
) -> tuple[float | None, float | None]:
    if len(route_window) < 2 or final_distance_to_goal_m is None:
        return None, None

    first = route_window[0]
    last = route_window[-1]
    first_step = int(first["step"])
    last_step = int(last["step"])
    step_delta = max(1, last_step - first_step)
    goal_delta = _distance_to_goal_delta(first, last)
    if goal_delta is None or goal_delta <= 0.0:
        return None, None

    meters_per_step = goal_delta / step_delta
    extra_steps = final_distance_to_goal_m / meters_per_step
    return round(extra_steps, 3), round(last_step + extra_steps, 3)


def _analyze_evidence(
    *,
    evidence_dir: Path,
    run_id: str,
    source: str,
    args: argparse.Namespace,
    exit_code: int,
    notes: str = "",
) -> dict[str, Any]:
    metrics = _read_json(evidence_dir / "metrics.json")
    events, events_error = _read_events(evidence_dir)

    grp_events = _events_of(events, "grp_route_progress")
    route_events = _events_of(events, "route_progress")
    vehicle_events = _events_of(events, "vehicle_state")
    collision_events = _events_of(events, "collision")
    lane_events = _events_of(events, "lane_invasion")

    steps_completed = int(metrics.get("steps_completed") or 0)
    final_step = steps_completed
    if route_events:
        final_step = max(final_step, int(route_events[-1]["step"]))
    if grp_events:
        final_step = max(final_step, int(grp_events[-1]["step"]))

    grp_window = _final_window(grp_events, final_step=final_step, window_steps=args.final_window_steps)
    route_window = _final_window(route_events, final_step=final_step, window_steps=args.final_window_steps)
    vehicle_window = _final_window(vehicle_events, final_step=final_step, window_steps=args.final_window_steps)

    last_grp = grp_events[-1] if grp_events else {}
    last_route = route_events[-1] if route_events else {}
    first_grp_window = grp_window[0] if grp_window else {}
    last_grp_window = grp_window[-1] if grp_window else {}
    first_route_window = route_window[0] if route_window else {}
    last_route_window = route_window[-1] if route_window else {}

    grp_index_delta: int | None = None
    if first_grp_window and last_grp_window:
        grp_index_delta = int(last_grp_window.get("grp_current_waypoint_index", 0)) - int(
            first_grp_window.get("grp_current_waypoint_index", 0)
        )

    final_window_avg_speed = None
    if vehicle_window:
        speeds = [_safe_float(item.get("speed_kmh")) for item in vehicle_window]
        usable = [speed for speed in speeds if speed is not None]
        if usable:
            final_window_avg_speed = round(sum(usable) / len(usable), 6)

    last_change_step, longest_stagnation = _last_waypoint_change(grp_events)
    final_distance_to_goal = _safe_float(metrics.get("distance_to_goal_m") or last_route.get("distance_to_goal_m"))
    estimated_extra_steps, estimated_total_steps = _estimate_extra_steps_to_goal(
        route_window,
        final_distance_to_goal_m=final_distance_to_goal,
    )

    route_delta = _delta(first_route_window, last_route_window, "route_progress_m") if route_window else None
    grp_delta = _delta(first_grp_window, last_grp_window, "grp_route_progress_m") if grp_window else None
    goal_delta = _distance_to_goal_delta(first_route_window, last_route_window) if route_window else None

    fixed_route_goal_reached = bool(metrics.get("fixed_route_goal_reached"))
    collision_count = int(metrics.get("collision_count") or len(collision_events))
    late_route_progression_diagnosed = bool(grp_events and route_events)
    waypoint_index_stalled = bool(
        late_route_progression_diagnosed
        and not fixed_route_goal_reached
        and (grp_index_delta or 0) < args.min_final_window_grp_index_delta
        and (goal_delta or 0.0) < args.min_final_window_goal_delta_m
    )
    step_budget_limited_likely = bool(
        late_route_progression_diagnosed
        and not fixed_route_goal_reached
        and collision_count == 0
        and not waypoint_index_stalled
        and (grp_index_delta or 0) >= args.min_final_window_grp_index_delta
        and (goal_delta or 0.0) >= args.min_final_window_goal_delta_m
        and estimated_extra_steps is not None
    )

    if fixed_route_goal_reached:
        status = "goal_reached"
    elif collision_count > 0:
        status = "collision_or_obstacle_blocked"
    elif waypoint_index_stalled:
        status = "waypoint_index_stalled"
    elif step_budget_limited_likely:
        status = "progressing_step_budget_limited"
    elif late_route_progression_diagnosed:
        status = "progressing_but_inconclusive"
    else:
        status = "insufficient_events"

    if events_error:
        notes = f"{notes}; events_read_error={events_error}".strip("; ")
    if metrics.get("json_read_error"):
        notes = f"{notes}; metrics_read_error={metrics['json_read_error']}".strip("; ")

    return {
        "run_id": run_id,
        "source": source,
        "town": args.town,
        "start_spawn_index": args.start_spawn_index,
        "end_spawn_index": args.end_spawn_index,
        "target_speed_kmh": args.target_speed_kmh,
        "route_sampling_resolution_m": args.route_sampling_resolution_m,
        "lookahead_waypoints": args.lookahead_waypoints,
        "steps_requested": metrics.get("steps_requested") or args.extended_steps,
        "steps_completed": steps_completed,
        "result": metrics.get("result") or "missing_metrics",
        "exit_code": exit_code,
        "fixed_route_goal_reached": fixed_route_goal_reached,
        "distance_to_goal_m": metrics.get("distance_to_goal_m"),
        "route_progress_pct": metrics.get("route_progress_pct"),
        "grp_route_progress_pct": metrics.get("grp_route_progress_pct"),
        "grp_current_waypoint_index": metrics.get("grp_current_waypoint_index") or last_grp.get("grp_current_waypoint_index"),
        "grp_remaining_waypoints": metrics.get("grp_remaining_waypoints") or last_grp.get("grp_remaining_waypoints"),
        "collision_count": collision_count,
        "lane_invasion_count": metrics.get("lane_invasion_count") or len(lane_events),
        "final_window_steps": args.final_window_steps,
        "final_window_grp_index_delta": grp_index_delta,
        "final_window_grp_progress_m_delta": round(grp_delta, 6) if grp_delta is not None else None,
        "final_window_route_progress_m_delta": round(route_delta, 6) if route_delta is not None else None,
        "final_window_distance_to_goal_m_delta": round(goal_delta, 6) if goal_delta is not None else None,
        "final_window_avg_speed_kmh": final_window_avg_speed,
        "last_waypoint_change_step": last_change_step,
        "longest_waypoint_stagnation_steps": longest_stagnation,
        "estimated_extra_steps_to_goal": estimated_extra_steps,
        "estimated_total_steps_to_goal": estimated_total_steps,
        "waypoint_progression_status": status,
        "late_route_progression_diagnosed": late_route_progression_diagnosed,
        "step_budget_limited_likely": step_budget_limited_likely,
        "evidence_dir": str(evidence_dir),
        "notes": notes,
    }


def _parse_evidence_dir(stdout: str, stderr: str) -> str | None:
    for line in (stdout + "\n" + stderr).splitlines():
        line = line.strip()
        if line.startswith("evidence_dir="):
            return line.split("=", 1)[1].strip()
    return None


def _build_child_command(args: argparse.Namespace, run_output_dir: Path) -> list[str]:
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
        str(args.start_spawn_index),
        "--end-spawn-index",
        str(args.end_spawn_index),
        "--steps",
        str(args.extended_steps),
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
        str(run_output_dir),
        "--carla-root",
        str(args.carla_root),
        "--base-python",
        args.base_python,
    ]
    if args.run_regressions:
        command.append("--run-regressions")
    return command


def _run_child(command: list[str], *, timeout_sec: float, env: dict[str, str]) -> ChildRunResult:
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
        return ChildRunResult(
            command=command,
            exit_code=completed.returncode,
            duration_sec=round(time.perf_counter() - started, 3),
            timed_out=False,
            stdout=stdout,
            stderr=stderr,
            evidence_dir=_parse_evidence_dir(stdout, stderr),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return ChildRunResult(
            command=command,
            exit_code=124,
            duration_sec=round(time.perf_counter() - started, 3),
            timed_out=True,
            stdout=stdout.strip(),
            stderr=(stderr.strip() or f"timeout after {timeout_sec}s"),
            evidence_dir=_parse_evidence_dir(stdout, stderr),
        )


def _dry_run_child_result(command: list[str]) -> ChildRunResult:
    return ChildRunResult(
        command=command,
        exit_code=0,
        duration_sec=0.0,
        timed_out=False,
        stdout="dry run; child command not executed",
        stderr="",
        evidence_dir=None,
    )


def _summary_payload(rows: list[dict[str, Any]], *, dry_run: bool, run_extended: bool) -> dict[str, Any]:
    source_row = next((row for row in rows if row["source"] == "source_reference"), None)
    extended_row = next((row for row in rows if row["source"] == "extended_run"), None)
    extended_goal_reached = bool(extended_row and extended_row.get("fixed_route_goal_reached") is True)
    return {
        "phase": "Phase 12A-R05B",
        "dry_run": dry_run,
        "run_extended": run_extended,
        "row_count": len(rows),
        "late_route_progression_diagnosed": any(row.get("late_route_progression_diagnosed") for row in rows),
        "source_waypoint_progression_status": source_row.get("waypoint_progression_status") if source_row else None,
        "source_step_budget_limited_likely": source_row.get("step_budget_limited_likely") if source_row else None,
        "source_estimated_total_steps_to_goal": source_row.get("estimated_total_steps_to_goal") if source_row else None,
        "extended_goal_reached": extended_goal_reached,
        "extended_result": extended_row.get("result") if extended_row else None,
        "extended_steps_completed": extended_row.get("steps_completed") if extended_row else None,
        "extended_distance_to_goal_m": extended_row.get("distance_to_goal_m") if extended_row else None,
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
    rows: list[dict[str, Any]],
    child_result: ChildRunResult | None,
) -> dict[str, Any]:
    summary = _summary_payload(rows, dry_run=args.dry_run, run_extended=args.run_extended)
    if args.dry_run:
        status = "waypoint_progression_dry_run"
    elif args.run_extended and summary["extended_goal_reached"]:
        status = "late_route_step_budget_confirmed"
    elif args.run_extended:
        status = "late_route_waypoint_progression_blocked"
    else:
        status = "offline_waypoint_progression_diagnosed"

    return {
        "phase": "Phase 12A-R05B",
        "status": status,
        "created_at_utc": _utc_now().isoformat(),
        "run_dir": str(run_dir),
        "dry_run": args.dry_run,
        "run_extended": args.run_extended,
        "child_runner": str(CHILD_RUNNER),
        "python_executable": args.python_executable,
        "host": args.host,
        "port": args.port,
        "town": args.town,
        "start_spawn_index": args.start_spawn_index,
        "end_spawn_index": args.end_spawn_index,
        "target_speed_kmh": args.target_speed_kmh,
        "route_sampling_resolution_m": args.route_sampling_resolution_m,
        "lookahead_waypoints": args.lookahead_waypoints,
        "source_evidence_dir": str(args.source_evidence_dir),
        "extended_evidence_dir": child_result.evidence_dir if child_result else None,
        "summary": {
            "row_count": summary["row_count"],
            "late_route_progression_diagnosed": summary["late_route_progression_diagnosed"],
            "source_waypoint_progression_status": summary["source_waypoint_progression_status"],
            "source_step_budget_limited_likely": summary["source_step_budget_limited_likely"],
            "extended_goal_reached": summary["extended_goal_reached"],
        },
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        "leaderboard_routes_exported": False,
        "leaderboard_route_criteria_evaluated": False,
        "route_benchmark_verified": False,
        "infraction_benchmark_verified": False,
        "leaderboard_evaluated": False,
    }


def _write_commands(path: Path, parent_command: list[str], child_result: ChildRunResult | None) -> None:
    lines = ["# Phase 12A-R05B parent command", subprocess.list2cmdline(parent_command), ""]
    lines.append("# Phase 11M extended child command")
    if child_result:
        lines.append(subprocess.list2cmdline(child_result.command))
    else:
        lines.append("# extended run not requested")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_readme(path: Path, *, run_dir: Path, rows: list[dict[str, Any]], dry_run: bool) -> None:
    summary = _summary_payload(rows, dry_run=dry_run, run_extended=any(row["source"] == "extended_run" for row in rows))
    body = f"""# Phase 12A-R05B Waypoint Progression Diagnosis

This directory contains late-route waypoint progression diagnosis for Route 05.

```text
dry_run={str(dry_run).lower()}
row_count={len(rows)}
late_route_progression_diagnosed={str(summary["late_route_progression_diagnosed"]).lower()}
extended_goal_reached={str(summary["extended_goal_reached"]).lower()}
```

This is diagnostic smoke evidence only. It is not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

Path:

```text
{run_dir.relative_to(REPO_ROOT).as_posix()}
```
"""
    path.write_text(body, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MA-VLNA Phase 12A-R05B waypoint progression diagnosis")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--start-spawn-index", type=int, default=40)
    parser.add_argument("--end-spawn-index", type=int, default=126)
    parser.add_argument("--extended-steps", type=int, default=5200)
    parser.add_argument("--target-speed-kmh", type=float, default=8.0)
    parser.add_argument("--goal-tolerance-m", type=float, default=3.0)
    parser.add_argument("--route-sampling-resolution-m", type=float, default=1.0)
    parser.add_argument("--lookahead-waypoints", type=int, default=3)
    parser.add_argument("--perception-backend", default="dummy", choices=["dummy", "yolo", "rtdetr"])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--source-evidence-dir", type=Path, default=DEFAULT_SOURCE_EVIDENCE_DIR)
    parser.add_argument("--final-window-steps", type=int, default=200)
    parser.add_argument("--min-final-window-grp-index-delta", type=int, default=2)
    parser.add_argument("--min-final-window-goal-delta-m", type=float, default=5.0)
    parser.add_argument("--route-timeout-sec", type=float, default=1800.0)
    parser.add_argument("--run-extended", action="store_true")
    parser.add_argument("--run-regressions", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.carla_root = _resolve_path(args.carla_root).resolve()
    args.source_evidence_dir = _resolve_path(args.source_evidence_dir)
    output_dir = _resolve_path(args.output_dir)
    run_dir = _next_run_dir(output_dir, args.timestamp or _timestamp(_utc_now()))
    run_dir.mkdir(parents=True, exist_ok=False)
    runs_dir = run_dir / "runs"
    runs_dir.mkdir()

    rows: list[dict[str, Any]] = []
    source_notes = "Phase 12A-R05 best recovery variant reference evidence."
    if not args.source_evidence_dir.exists():
        source_notes = f"source evidence missing: {args.source_evidence_dir}"
    rows.append(
        _analyze_evidence(
            evidence_dir=args.source_evidence_dir,
            run_id="r05b_source_slow_short_reference",
            source="source_reference",
            args=args,
            exit_code=1,
            notes=source_notes,
        )
    )

    child_result: ChildRunResult | None = None
    if args.run_extended:
        extended_output_dir = runs_dir / "r05b_extended_slow_short"
        extended_output_dir.mkdir(parents=True, exist_ok=True)
        command = _build_child_command(args, extended_output_dir)
        print(f"r05b_extended_slow_short: {subprocess.list2cmdline(command)}")
        if args.dry_run:
            child_result = _dry_run_child_result(command)
        else:
            env = os.environ.copy()
            env["CARLA_ROOT"] = str(args.carla_root)
            env["PYTHONIOENCODING"] = "utf-8"
            child_result = _run_child(command, timeout_sec=args.route_timeout_sec, env=env)

        if child_result.evidence_dir:
            rows.append(
                _analyze_evidence(
                    evidence_dir=Path(child_result.evidence_dir),
                    run_id="r05b_extended_slow_short",
                    source="extended_run",
                    args=args,
                    exit_code=child_result.exit_code,
                    notes="Extended-step validation using unchanged Phase 11M GRP runner.",
                )
            )
        else:
            rows.append(
                {
                    "run_id": "r05b_extended_slow_short",
                    "source": "extended_run",
                    "town": args.town,
                    "start_spawn_index": args.start_spawn_index,
                    "end_spawn_index": args.end_spawn_index,
                    "target_speed_kmh": args.target_speed_kmh,
                    "route_sampling_resolution_m": args.route_sampling_resolution_m,
                    "lookahead_waypoints": args.lookahead_waypoints,
                    "steps_requested": args.extended_steps,
                    "steps_completed": 0,
                    "result": "dry_run" if args.dry_run else "child_failed_without_evidence",
                    "exit_code": child_result.exit_code,
                    "fixed_route_goal_reached": None,
                    "distance_to_goal_m": None,
                    "route_progress_pct": None,
                    "grp_route_progress_pct": None,
                    "grp_current_waypoint_index": None,
                    "grp_remaining_waypoints": None,
                    "collision_count": None,
                    "lane_invasion_count": None,
                    "final_window_steps": args.final_window_steps,
                    "final_window_grp_index_delta": None,
                    "final_window_grp_progress_m_delta": None,
                    "final_window_route_progress_m_delta": None,
                    "final_window_distance_to_goal_m_delta": None,
                    "final_window_avg_speed_kmh": None,
                    "last_waypoint_change_step": None,
                    "longest_waypoint_stagnation_steps": None,
                    "estimated_extra_steps_to_goal": None,
                    "estimated_total_steps_to_goal": None,
                    "waypoint_progression_status": "dry_run" if args.dry_run else "missing_child_evidence",
                    "late_route_progression_diagnosed": False,
                    "step_budget_limited_likely": None,
                    "evidence_dir": None,
                    "notes": child_result.stderr or child_result.stdout,
                }
            )

    _write_summary_csv(run_dir / "summary.csv", rows)
    _write_json(
        run_dir / "summary.json",
        _summary_payload(rows, dry_run=args.dry_run, run_extended=args.run_extended),
    )
    _write_json(run_dir / "manifest.json", _manifest_payload(args, run_dir=run_dir, rows=rows, child_result=child_result))
    _write_commands(run_dir / "commands.txt", [sys.executable, *sys.argv], child_result)
    _write_readme(run_dir / "README.md", run_dir=run_dir, rows=rows, dry_run=args.dry_run)

    summary = _summary_payload(rows, dry_run=args.dry_run, run_extended=args.run_extended)
    if args.dry_run:
        print("Phase 12A-R05B Dry Run — waypoint progression diagnosis commands written without launching CARLA.")
        print(f"experiment_dir={run_dir}")
        return 0
    if args.run_extended and summary["extended_goal_reached"]:
        print("Phase 12A-R05B Pass — extended-step run reached the goal, confirming the 2500-step horizon diagnosis.")
        print(f"experiment_dir={run_dir}")
        return 0
    if summary["late_route_progression_diagnosed"] and not args.run_extended:
        print("Phase 12A-R05B Offline Diagnosis Pass — source evidence confirms late-route waypoint progression.")
        print(f"experiment_dir={run_dir}")
        return 0

    print("Phase 12A-R05B Blocked — late-route waypoint progression diagnosis did not reach the extended goal gate.")
    print(f"experiment_dir={run_dir}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

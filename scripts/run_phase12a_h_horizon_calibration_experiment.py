"""
Phase 12A-H horizon calibration experiment.

此 runner 以既有 real CARLA evidence 作為資料來源，校準 Phase 12A
固定 route matrix 的 per-route step horizon。它不 import carla、不啟動
CARLA、不修改 11M GRP controller，也不把校準結果宣稱為 CARLA
Leaderboard、正式 route benchmark 或 infraction benchmark。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "phase12"
DEFAULT_PHASE12A_SUMMARY_PATH = REPO_ROOT / "experiments" / "phase12" / "20260619T113705Z" / "summary.json"
DEFAULT_R05B_SUMMARY_PATH = REPO_ROOT / "experiments" / "phase12" / "20260620T115855Z" / "summary.json"
BENCHMARK_BOUNDARY_SCOPE = "phase12a_h_horizon_calibration_smoke_only_not_carla_leaderboard"

SUMMARY_COLUMNS = (
    "route_id",
    "town",
    "start_spawn_index",
    "end_spawn_index",
    "base_result",
    "base_steps_requested",
    "base_goal_reach_step",
    "base_distance_to_goal_m",
    "calibration_source",
    "calibration_result",
    "calibration_evidence_dir",
    "calibration_steps_requested",
    "goal_reach_step",
    "target_speed_kmh",
    "route_sampling_resolution_m",
    "lookahead_waypoints",
    "recommended_horizon_steps",
    "headroom_factor",
    "round_to_steps",
    "min_horizon_steps",
    "horizon_margin_steps",
    "horizon_ratio_vs_base_steps",
    "collision_count",
    "lane_invasion_count",
    "calibration_status",
    "route_benchmark_verified",
    "infraction_benchmark_verified",
    "leaderboard_evaluated",
    "notes",
)


@dataclass(frozen=True)
class RouteSpec:
    """Phase 12A 固定路線定義。"""

    route_id: str
    start_spawn_index: int
    end_spawn_index: int


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


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_metrics_from_evidence(evidence_dir: str | None) -> dict[str, Any]:
    if not evidence_dir:
        return {}
    return _read_json(Path(evidence_dir) / "metrics.json")


def _phase12a_rows(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in summary.get("results", []) or []:
        route_id = str(row.get("route_id") or "")
        if route_id:
            rows[route_id] = row
    return rows


def _r05b_extended_row(summary: dict[str, Any]) -> dict[str, Any] | None:
    for row in summary.get("results", []) or []:
        if row.get("run_id") == "r05b_extended_slow_short" and row.get("source") == "extended_run":
            return row
    return None


def _round_horizon(*, goal_reach_step: int, headroom_factor: float, round_to_steps: int, min_horizon_steps: int) -> int:
    raw = goal_reach_step * headroom_factor
    rounded = int(math.ceil(raw / round_to_steps) * round_to_steps)
    return max(min_horizon_steps, rounded)


def _calibrate_route(
    route: RouteSpec,
    *,
    phase12a_row: dict[str, Any] | None,
    r05b_row: dict[str, Any] | None,
    args: argparse.Namespace,
) -> dict[str, Any]:
    base_metrics = _read_metrics_from_evidence(phase12a_row.get("evidence_dir") if phase12a_row else None)
    base_goal_step = _safe_int(base_metrics.get("goal_reach_step"))
    base_result = str((phase12a_row or {}).get("result") or base_metrics.get("result") or "missing")
    base_steps = _safe_int(base_metrics.get("steps_requested") or (phase12a_row or {}).get("steps")) or args.original_steps
    base_distance_to_goal = _safe_float(base_metrics.get("distance_to_goal_m") or (phase12a_row or {}).get("distance_to_goal_m"))

    calibration_source = "missing"
    calibration_row: dict[str, Any] = {}
    calibration_metrics: dict[str, Any] = {}
    notes = ""

    if base_result == "passed" and base_goal_step is not None:
        calibration_source = "phase12a_2500_pass"
        calibration_row = phase12a_row or {}
        calibration_metrics = base_metrics
    elif route.route_id == "route_05" and r05b_row:
        calibration_source = "phase12a_r05b_extended_pass"
        calibration_row = r05b_row
        calibration_metrics = _read_metrics_from_evidence(r05b_row.get("evidence_dir"))
        notes = "Route 05 uses R05B slow-short-lookahead extended evidence because original 2500-step route was blocked."
    elif phase12a_row:
        calibration_source = "phase12a_unresolved_blocked_route"
        calibration_row = phase12a_row
        calibration_metrics = base_metrics
        notes = "No goal-reaching calibration evidence found."
    else:
        notes = "Route missing from Phase 12A summary."

    goal_reach_step = _safe_int(calibration_metrics.get("goal_reach_step") or calibration_row.get("goal_reach_step"))
    calibration_result = str(calibration_metrics.get("result") or calibration_row.get("result") or "missing")
    calibration_steps = _safe_int(calibration_metrics.get("steps_requested") or calibration_row.get("steps_requested"))
    recommended_horizon = None
    horizon_margin = None
    horizon_ratio = None
    calibration_status = "missing_goal_reach_evidence"
    if calibration_result == "passed" and goal_reach_step is not None:
        recommended_horizon = _round_horizon(
            goal_reach_step=goal_reach_step,
            headroom_factor=args.headroom_factor,
            round_to_steps=args.round_to_steps,
            min_horizon_steps=args.min_horizon_steps,
        )
        horizon_margin = recommended_horizon - goal_reach_step
        horizon_ratio = round(recommended_horizon / base_steps, 6) if base_steps else None
        calibration_status = "calibrated"

    target_speed_kmh = _safe_float(calibration_metrics.get("target_speed_kmh") or calibration_row.get("target_speed_kmh"))
    route_sampling_resolution_m = _safe_float(
        calibration_metrics.get("route_sampling_resolution_m") or calibration_row.get("route_sampling_resolution_m")
    )
    lookahead_waypoints = _safe_int(calibration_metrics.get("lookahead_waypoints") or calibration_row.get("lookahead_waypoints"))
    if calibration_source == "phase12a_2500_pass":
        target_speed_kmh = target_speed_kmh if target_speed_kmh is not None else 18.0
        route_sampling_resolution_m = route_sampling_resolution_m if route_sampling_resolution_m is not None else 2.0
        lookahead_waypoints = lookahead_waypoints if lookahead_waypoints is not None else 8
    elif calibration_source == "phase12a_r05b_extended_pass":
        target_speed_kmh = target_speed_kmh if target_speed_kmh is not None else 8.0
        route_sampling_resolution_m = route_sampling_resolution_m if route_sampling_resolution_m is not None else 1.0
        lookahead_waypoints = lookahead_waypoints if lookahead_waypoints is not None else 3

    return {
        "route_id": route.route_id,
        "town": args.town,
        "start_spawn_index": route.start_spawn_index,
        "end_spawn_index": route.end_spawn_index,
        "base_result": base_result,
        "base_steps_requested": base_steps,
        "base_goal_reach_step": base_goal_step,
        "base_distance_to_goal_m": base_distance_to_goal,
        "calibration_source": calibration_source,
        "calibration_result": calibration_result,
        "calibration_evidence_dir": calibration_row.get("evidence_dir") or (phase12a_row or {}).get("evidence_dir"),
        "calibration_steps_requested": calibration_steps,
        "goal_reach_step": goal_reach_step,
        "target_speed_kmh": target_speed_kmh,
        "route_sampling_resolution_m": route_sampling_resolution_m,
        "lookahead_waypoints": lookahead_waypoints,
        "recommended_horizon_steps": recommended_horizon,
        "headroom_factor": args.headroom_factor,
        "round_to_steps": args.round_to_steps,
        "min_horizon_steps": args.min_horizon_steps,
        "horizon_margin_steps": horizon_margin,
        "horizon_ratio_vs_base_steps": horizon_ratio,
        "collision_count": _safe_int(calibration_metrics.get("collision_count")),
        "lane_invasion_count": _safe_int(calibration_metrics.get("lane_invasion_count")),
        "calibration_status": calibration_status,
        "route_benchmark_verified": False,
        "infraction_benchmark_verified": False,
        "leaderboard_evaluated": False,
        "notes": notes,
    }


def _horizon_matrix(rows: list[dict[str, Any]]) -> dict[str, int]:
    matrix: dict[str, int] = {}
    for row in rows:
        horizon = _safe_int(row.get("recommended_horizon_steps"))
        if horizon is not None:
            matrix[str(row["route_id"])] = horizon
    return matrix


def _summary_payload(args: argparse.Namespace, rows: list[dict[str, Any]]) -> dict[str, Any]:
    calibrated_count = sum(1 for row in rows if row.get("calibration_status") == "calibrated")
    all_routes_calibrated = calibrated_count == len(ROUTE_MATRIX)
    horizons = _horizon_matrix(rows)
    max_horizon = max(horizons.values()) if horizons else None
    return {
        "phase": "Phase 12A-H",
        "experiment_line": "H",
        "row_count": len(rows),
        "calibrated_route_count": calibrated_count,
        "all_routes_calibrated": all_routes_calibrated,
        "headroom_factor": args.headroom_factor,
        "round_to_steps": args.round_to_steps,
        "min_horizon_steps": args.min_horizon_steps,
        "original_steps": args.original_steps,
        "recommended_horizon_by_route": horizons,
        "max_recommended_horizon_steps": max_horizon,
        "route05_calibration_source": next(
            (row.get("calibration_source") for row in rows if row.get("route_id") == "route_05"),
            None,
        ),
        "route05_recommended_horizon_steps": horizons.get("route_05"),
        "results": rows,
        "benchmark_boundaries": {
            "route_benchmark_verified": False,
            "infraction_benchmark_verified": False,
            "leaderboard_evaluated": False,
            "leaderboard_routes_exported": False,
            "leaderboard_route_criteria_evaluated": False,
        },
    }


def _manifest_payload(args: argparse.Namespace, *, run_dir: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _summary_payload(args, rows)
    return {
        "phase": "Phase 12A-H",
        "status": "horizon_calibration_pass" if summary["all_routes_calibrated"] else "horizon_calibration_blocked",
        "created_at_utc": _utc_now().isoformat(),
        "run_dir": str(run_dir),
        "phase12a_summary_path": str(args.phase12a_summary_path),
        "r05b_summary_path": str(args.r05b_summary_path),
        "town": args.town,
        "routes": [asdict(route) for route in ROUTE_MATRIX],
        "summary": {
            "row_count": summary["row_count"],
            "calibrated_route_count": summary["calibrated_route_count"],
            "all_routes_calibrated": summary["all_routes_calibrated"],
            "max_recommended_horizon_steps": summary["max_recommended_horizon_steps"],
            "route05_recommended_horizon_steps": summary["route05_recommended_horizon_steps"],
        },
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        "leaderboard_routes_exported": False,
        "leaderboard_route_criteria_evaluated": False,
        "route_benchmark_verified": False,
        "infraction_benchmark_verified": False,
        "leaderboard_evaluated": False,
    }


def _write_commands(path: Path) -> None:
    lines = [
        "# Phase 12A-H horizon calibration command",
        subprocess.list2cmdline([sys.executable, *sys.argv]),
    ]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_readme(path: Path, *, run_dir: Path, summary: dict[str, Any]) -> None:
    body = f"""# Phase 12A-H Horizon Calibration Experiment

This directory contains evidence-backed horizon calibration output for the Phase 12A route matrix.

```text
row_count={summary["row_count"]}
calibrated_route_count={summary["calibrated_route_count"]}
all_routes_calibrated={str(summary["all_routes_calibrated"]).lower()}
max_recommended_horizon_steps={summary["max_recommended_horizon_steps"]}
```

This is calibration smoke evidence only. It is not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

Path:

```text
{run_dir.relative_to(REPO_ROOT).as_posix()}
```
"""
    path.write_text(body, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MA-VLNA Phase 12A-H horizon calibration experiment")
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--phase12a-summary-path", type=Path, default=DEFAULT_PHASE12A_SUMMARY_PATH)
    parser.add_argument("--r05b-summary-path", type=Path, default=DEFAULT_R05B_SUMMARY_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--headroom-factor", type=float, default=1.2)
    parser.add_argument("--round-to-steps", type=int, default=100)
    parser.add_argument("--min-horizon-steps", type=int, default=2500)
    parser.add_argument("--original-steps", type=int, default=2500)
    parser.add_argument("--require-complete-calibration", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.phase12a_summary_path = _resolve_path(args.phase12a_summary_path)
    args.r05b_summary_path = _resolve_path(args.r05b_summary_path)
    output_dir = _resolve_path(args.output_dir)
    run_dir = _next_run_dir(output_dir, args.timestamp or _timestamp(_utc_now()))
    run_dir.mkdir(parents=True, exist_ok=False)

    phase12a_summary = _read_json(args.phase12a_summary_path)
    r05b_summary = _read_json(args.r05b_summary_path)
    phase12a_by_route = _phase12a_rows(phase12a_summary)
    r05b_row = _r05b_extended_row(r05b_summary)

    rows = [
        _calibrate_route(
            route,
            phase12a_row=phase12a_by_route.get(route.route_id),
            r05b_row=r05b_row if route.route_id == "route_05" else None,
            args=args,
        )
        for route in ROUTE_MATRIX
    ]
    summary = _summary_payload(args, rows)

    _write_summary_csv(run_dir / "summary.csv", rows)
    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "horizon_matrix.json", summary["recommended_horizon_by_route"])
    _write_json(run_dir / "manifest.json", _manifest_payload(args, run_dir=run_dir, rows=rows))
    _write_commands(run_dir / "commands.txt")
    _write_readme(run_dir / "README.md", run_dir=run_dir, summary=summary)

    if summary["all_routes_calibrated"]:
        print("Phase 12A-H Horizon Calibration Pass — calibrated horizons generated for all fixed routes.")
        print(f"experiment_dir={run_dir}")
        return 0

    print("Phase 12A-H Horizon Calibration Blocked — at least one route lacks goal-reaching calibration evidence.")
    print(f"experiment_dir={run_dir}")
    return 1 if args.require_complete_calibration else 0


if __name__ == "__main__":
    raise SystemExit(main())

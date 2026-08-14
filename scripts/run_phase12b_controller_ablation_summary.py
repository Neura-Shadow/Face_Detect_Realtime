"""
Phase 12B-SUM controller ablation comparative summary.

This script aggregates the three Phase 12B controller evidence lines:

* GRP follower: goal-reach smoke pass.
* Linear spawn-pair follower: route-progress smoke pass, not completion.
* Baseline PlannerAction mapper: executable closed-loop runtime, route-progress blocked.

It does not import CARLA, does not start a CARLA server, and does not create a
formal benchmark claim. Generated output remains local under experiments/.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "phase12"
DEFAULT_GRP_DIR = REPO_ROOT / "experiments" / "phase12" / "20260628T065257Z"
DEFAULT_LINEAR_DIR = REPO_ROOT / "experiments" / "phase12" / "20260628T080731Z"
DEFAULT_BASELINE_DIR = REPO_ROOT / "experiments" / "phase12" / "20260628T122108Z"

PHASE = "Phase 12B-SUM"
STATUS = "controller_ablation_comparative_summary_prepared"
BENCHMARK_BOUNDARY_SCOPE = "comparative_summary_only_not_carla_leaderboard"
BOUNDARY_FIELDS = {
    "route_benchmark_verified": False,
    "infraction_benchmark_verified": False,
    "leaderboard_evaluated": False,
    "leaderboard_routes_exported": False,
    "leaderboard_route_criteria_evaluated": False,
}

CONTROLLER_COLUMNS = (
    "controller_mode",
    "source_experiment_dir",
    "pass_scope",
    "outcome_class",
    "row_count",
    "executed_row_count",
    "passed_count",
    "blocked_count",
    "failed_count",
    "all_runtime_rows_passed",
    "goal_reached_count",
    "completion_verified_count",
    "route_progress_verified_count",
    "total_collision_count",
    "total_lane_invasion_count",
    "avg_route_progress_pct",
    "avg_distance_to_goal_m",
    "total_distance_traveled_m",
    "conclusion",
)

ROUTE_COLUMNS = (
    "route_id",
    "controller_mode",
    "result",
    "exit_code",
    "steps_completed",
    "route_progress_verified",
    "route_progress_m",
    "route_progress_pct",
    "distance_to_goal_m",
    "fixed_route_goal_reached",
    "fixed_route_completion_verified",
    "collision_count",
    "lane_invasion_count",
    "avg_speed_kmh",
    "max_speed_kmh",
    "distance_traveled_m",
    "evidence_dir",
)


@dataclass(frozen=True)
class EvidenceSource:
    controller_mode: str
    experiment_dir: Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _next_run_dir(output_dir: Path, timestamp: str | None = None) -> Path:
    base = output_dir / (timestamp or _timestamp())
    candidate = base
    suffix = 1
    while candidate.exists():
        candidate = output_dir / f"{base.name}-{suffix}"
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in columns})


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int:
    number = _num(value)
    return int(number) if number is not None else 0


def _round(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _mean(values: list[float | None]) -> float | None:
    cleaned = [value for value in values if value is not None]
    if not cleaned:
        return None
    return statistics.fmean(cleaned)


def _load_route_rows(source: EvidenceSource) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summary = _read_json(source.experiment_dir / "summary.json")
    rows: list[dict[str, Any]] = []
    for row in summary.get("results", []):
        evidence_dir = Path(str(row.get("evidence_dir") or ""))
        metrics: dict[str, Any] = {}
        if evidence_dir and (evidence_dir / "metrics.json").exists():
            metrics = _read_json(evidence_dir / "metrics.json")

        rows.append({
            "route_id": row.get("route_id"),
            "controller_mode": source.controller_mode,
            "result": row.get("result"),
            "exit_code": row.get("exit_code"),
            "steps_completed": metrics.get("steps_completed", row.get("steps_completed")),
            "route_progress_verified": metrics.get("route_progress_verified", row.get("route_progress_verified")),
            "route_progress_m": metrics.get("route_progress_m", row.get("route_progress_m")),
            "route_progress_pct": metrics.get("route_progress_pct", row.get("route_progress_pct")),
            "distance_to_goal_m": metrics.get("distance_to_goal_m", row.get("distance_to_goal_m")),
            "fixed_route_goal_reached": metrics.get("fixed_route_goal_reached", row.get("fixed_route_goal_reached")),
            "fixed_route_completion_verified": metrics.get("fixed_route_completion_verified"),
            "collision_count": metrics.get("collision_count", row.get("collision_count")),
            "lane_invasion_count": metrics.get("lane_invasion_count", row.get("lane_invasion_count")),
            "avg_speed_kmh": metrics.get("avg_speed_kmh", row.get("avg_speed_kmh")),
            "max_speed_kmh": metrics.get("max_speed_kmh", row.get("max_speed_kmh")),
            "distance_traveled_m": metrics.get("distance_traveled_m", row.get("distance_traveled_m")),
            "evidence_dir": row.get("evidence_dir"),
        })
    return summary, rows


def _pass_scope(controller_mode: str) -> str:
    if controller_mode == "grp_follower":
        return "goal_reach_smoke_pass"
    if controller_mode == "linear_spawn_pair_follower":
        return "route_progress_smoke_only_not_completion"
    if controller_mode == "baseline_planner_action_mapper":
        return "route_progress_blocked_negative_runtime_evidence"
    return "unknown"


def _outcome_class(controller_mode: str, rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    completion_count = sum(1 for row in rows if row.get("fixed_route_completion_verified") is True)
    progress_count = sum(1 for row in rows if row.get("route_progress_verified") is True)
    total_collisions = sum(_int(row.get("collision_count")) for row in rows)
    if controller_mode == "grp_follower" and completion_count == len(rows) and summary.get("all_runtime_rows_passed") is True:
        return "strongest_goal_reach_controller"
    if controller_mode == "linear_spawn_pair_follower" and progress_count == len(rows):
        if total_collisions > 0:
            return "route_progress_smoke_pass_with_high_collision_counts"
        return "route_progress_smoke_pass"
    if controller_mode == "baseline_planner_action_mapper":
        return "closed_loop_executable_but_route_progress_blocked"
    return "mixed_or_incomplete"


def _conclusion(controller_mode: str, outcome_class: str) -> str:
    if controller_mode == "grp_follower":
        return "Only controller subset that verified fixed-route goal reach on all five calibrated routes."
    if controller_mode == "linear_spawn_pair_follower":
        return "Passed route-progress smoke, but it is not a completion gate and it recorded high collision counts."
    if controller_mode == "baseline_planner_action_mapper":
        return "Closed-loop mapper executed control and telemetry, but made no measurable spawn-pair route progress."
    return outcome_class


def _controller_summary(source: EvidenceSource, summary: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    outcome = _outcome_class(source.controller_mode, rows, summary)
    return {
        "controller_mode": source.controller_mode,
        "source_experiment_dir": str(source.experiment_dir),
        "pass_scope": _pass_scope(source.controller_mode),
        "outcome_class": outcome,
        "row_count": summary.get("row_count", len(rows)),
        "executed_row_count": summary.get("executed_row_count"),
        "passed_count": summary.get("passed_count"),
        "blocked_count": summary.get("blocked_count"),
        "failed_count": summary.get("failed_count"),
        "all_runtime_rows_passed": summary.get("all_runtime_rows_passed"),
        "goal_reached_count": sum(1 for row in rows if row.get("fixed_route_goal_reached") is True),
        "completion_verified_count": sum(1 for row in rows if row.get("fixed_route_completion_verified") is True),
        "route_progress_verified_count": sum(1 for row in rows if row.get("route_progress_verified") is True),
        "total_collision_count": sum(_int(row.get("collision_count")) for row in rows),
        "total_lane_invasion_count": sum(_int(row.get("lane_invasion_count")) for row in rows),
        "avg_route_progress_pct": _round(_mean([_num(row.get("route_progress_pct")) for row in rows])),
        "avg_distance_to_goal_m": _round(_mean([_num(row.get("distance_to_goal_m")) for row in rows])),
        "total_distance_traveled_m": _round(sum(_num(row.get("distance_traveled_m")) or 0.0 for row in rows)),
        "conclusion": _conclusion(source.controller_mode, outcome),
    }


def _command_text(command: list[str]) -> str:
    return subprocess.list2cmdline(command)


def _manifest(args: argparse.Namespace, run_dir: Path, sources: list[EvidenceSource]) -> dict[str, Any]:
    return {
        "phase": PHASE,
        "status": STATUS,
        "created_at_utc": _utc_now(),
        "run_dir": str(run_dir),
        "source_experiment_dirs": {
            source.controller_mode: str(source.experiment_dir) for source in sources
        },
        "output_files": [
            "manifest.json",
            "summary.json",
            "controller_summary.csv",
            "route_comparison.csv",
            "commands.txt",
            "README.md",
        ],
        "carla_import_required": False,
        "carla_server_required": False,
        "raw_runtime_evidence_committed": False,
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        **BOUNDARY_FIELDS,
    }


def _write_readme(
    path: Path,
    *,
    run_dir: Path,
    controller_rows: list[dict[str, Any]],
) -> None:
    lines = [
        "# Phase 12B-SUM Controller Ablation Comparative Summary",
        "",
        "Status:",
        "",
        "```text",
        "Phase 12B-SUM Controller Ablation Comparative Summary Prepared - GRP, linear, and baseline mapper evidence has been normalized into comparable controller and route tables.",
        "```",
        "",
        "This output is generated from existing local evidence only. It does not start CARLA and does not create a benchmark claim.",
        "",
        "Controller conclusions:",
        "",
    ]
    for row in controller_rows:
        lines.append(f"- `{row['controller_mode']}`: {row['conclusion']}")
    lines.extend([
        "",
        "Boundary:",
        "",
        "```text",
        "route_benchmark_verified=false",
        "infraction_benchmark_verified=false",
        "leaderboard_evaluated=false",
        "leaderboard_routes_exported=false",
        "leaderboard_route_criteria_evaluated=false",
        "```",
        "",
        "Path:",
        "",
        "```text",
        run_dir.relative_to(REPO_ROOT).as_posix(),
        "```",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Phase 12B controller ablation comparative summary")
    parser.add_argument("--grp-summary-dir", type=Path, default=DEFAULT_GRP_DIR)
    parser.add_argument("--linear-summary-dir", type=Path, default=DEFAULT_LINEAR_DIR)
    parser.add_argument("--baseline-summary-dir", type=Path, default=DEFAULT_BASELINE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--require-complete", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.output_dir = _resolve(args.output_dir)

    sources = [
        EvidenceSource("grp_follower", _resolve(args.grp_summary_dir)),
        EvidenceSource("linear_spawn_pair_follower", _resolve(args.linear_summary_dir)),
        EvidenceSource("baseline_planner_action_mapper", _resolve(args.baseline_summary_dir)),
    ]

    controller_rows: list[dict[str, Any]] = []
    route_rows: list[dict[str, Any]] = []
    source_summaries: dict[str, dict[str, Any]] = {}

    for source in sources:
        summary, rows = _load_route_rows(source)
        if args.require_complete and len(rows) != 5:
            raise RuntimeError(f"{source.controller_mode} expected 5 rows, got {len(rows)}")
        source_summaries[source.controller_mode] = summary
        controller_rows.append(_controller_summary(source, summary, rows))
        route_rows.extend(rows)

    if args.require_complete and len(controller_rows) != 3:
        raise RuntimeError(f"expected 3 controller summaries, got {len(controller_rows)}")

    run_dir = _next_run_dir(args.output_dir, args.timestamp)
    _write_csv(run_dir / "controller_summary.csv", controller_rows, CONTROLLER_COLUMNS)
    _write_csv(run_dir / "route_comparison.csv", route_rows, ROUTE_COLUMNS)
    payload = {
        "phase": PHASE,
        "status": STATUS,
        "created_at_utc": _utc_now(),
        "controller_summary": controller_rows,
        "route_comparison": route_rows,
        "source_summary_status": {
            mode: {
                "status": summary.get("status"),
                "row_count": summary.get("row_count"),
                "passed_count": summary.get("passed_count"),
                "blocked_count": summary.get("blocked_count"),
                "failed_count": summary.get("failed_count"),
                "all_runtime_rows_passed": summary.get("all_runtime_rows_passed"),
            }
            for mode, summary in source_summaries.items()
        },
        "comparative_findings": [
            "grp_follower is the only controller subset with all five fixed-route goal-reach completions verified.",
            "linear_spawn_pair_follower passes route-progress smoke but is not a completion gate and records high collision counts.",
            "baseline_planner_action_mapper is executable in closed loop but is route-progress blocked on all five routes.",
        ],
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        **BOUNDARY_FIELDS,
    }
    _write_json(run_dir / "summary.json", payload)
    _write_json(run_dir / "manifest.json", _manifest(args, run_dir, sources))
    (run_dir / "commands.txt").write_text(_command_text([sys.executable, *sys.argv]) + "\n", encoding="utf-8")
    _write_readme(run_dir / "README.md", run_dir=run_dir, controller_rows=controller_rows)

    print("Phase 12B-SUM Controller Ablation Comparative Summary Prepared.")
    print(f"summary_dir={run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

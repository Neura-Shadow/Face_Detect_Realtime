"""
Phase 12A-R05 route 05 failure diagnosis and recovery experiment.

此 runner 專注於 Phase 12A 的 `route_05` 失敗案例。它保留 Phase 11M
GRP route-following runner 作為唯一執行器，不修改 VLM、SafetyGate、
SemanticPlanner、GRP controller 或 baseline requirements。此處只調整
runner 參數並聚合診斷 evidence；結果仍不是 CARLA Leaderboard、正式
route benchmark 或 infraction benchmark。
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
DEFAULT_BASELINE_EVIDENCE_DIR = (
    REPO_ROOT
    / "experiments"
    / "phase12"
    / "20260619T113705Z"
    / "runs"
    / "route_05"
    / "20260619T114950Z"
)
CHILD_RUNNER = REPO_ROOT / "scripts" / "run_phase11m_grp_route_following.py"
BENCHMARK_BOUNDARY_SCOPE = "phase12a_r05_recovery_smoke_only_not_carla_leaderboard"

SUMMARY_COLUMNS = (
    "variant_id",
    "source",
    "town",
    "start_spawn_index",
    "end_spawn_index",
    "target_speed_kmh",
    "route_sampling_resolution_m",
    "lookahead_waypoints",
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
    "first_collision_step",
    "first_collision_actor",
    "first_collision_impulse_norm",
    "collision_actor_top",
    "stuck_after_collision",
    "timeout",
    "result",
    "exit_code",
    "evidence_dir",
    "notes",
)


@dataclass(frozen=True)
class RecoveryVariant:
    """Route 05 recovery parameter variant。"""

    variant_id: str
    target_speed_kmh: float
    route_sampling_resolution_m: float
    lookahead_waypoints: int
    notes: str


@dataclass(frozen=True)
class VariantResult:
    """單一 variant 的執行或 baseline reference 結果。"""

    variant: RecoveryVariant
    source: str
    command: list[str]
    exit_code: int
    duration_sec: float
    timed_out: bool
    stdout: str
    stderr: str
    evidence_dir: str | None
    metrics: dict[str, Any]
    diagnostics: dict[str, Any]

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and self.metrics.get("result") == "passed"


VARIANTS = (
    RecoveryVariant(
        variant_id="r05_slow_wide_lookahead",
        target_speed_kmh=8.0,
        route_sampling_resolution_m=2.0,
        lookahead_waypoints=12,
        notes="降低速度並增加 lookahead，測試是否能避免早期 steering spike 撞上 traffic light。",
    ),
    RecoveryVariant(
        variant_id="r05_slow_short_lookahead",
        target_speed_kmh=8.0,
        route_sampling_resolution_m=1.0,
        lookahead_waypoints=3,
        notes="降低速度、縮短 lookahead 並提高 route sampling 密度，測試近場跟隨是否能繞開障礙。",
    ),
    RecoveryVariant(
        variant_id="r05_creep_short_lookahead",
        target_speed_kmh=5.0,
        route_sampling_resolution_m=1.0,
        lookahead_waypoints=3,
        notes="以 creep speed 重跑短 lookahead，測試低速是否足以通過起點附近 traffic light 幾何。",
    ),
    RecoveryVariant(
        variant_id="r05_creep_wide_lookahead",
        target_speed_kmh=5.0,
        route_sampling_resolution_m=2.0,
        lookahead_waypoints=12,
        notes="低速加寬 lookahead，測試較平滑 steering 是否能恢復。",
    ),
)

BASELINE_VARIANT = RecoveryVariant(
    variant_id="r05_baseline_reference",
    target_speed_kmh=18.0,
    route_sampling_resolution_m=2.0,
    lookahead_waypoints=8,
    notes="Phase 12A route_05 failure evidence reference，不重新執行。",
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


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"json_read_error": str(exc)}


def _read_metrics(evidence_dir: str | None) -> dict[str, Any]:
    if not evidence_dir:
        return {}
    return _read_json(Path(evidence_dir) / "metrics.json")


def _diagnose_events(evidence_dir: str | None) -> dict[str, Any]:
    if not evidence_dir:
        return {}
    events_path = Path(evidence_dir) / "events.jsonl"
    if not events_path.exists():
        return {}

    first_collision: dict[str, Any] | None = None
    collision_actor_counts: dict[str, int] = {}
    route_progress_at_first_collision: float | None = None
    final_route_progress: float | None = None
    final_distance_to_goal: float | None = None

    try:
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            event_type = event.get("event")
            if event_type == "collision":
                actor = str(event.get("other_actor") or "unknown")
                collision_actor_counts[actor] = collision_actor_counts.get(actor, 0) + 1
                if first_collision is None:
                    first_collision = event
            elif event_type == "route_progress":
                final_route_progress = event.get("route_progress_pct")
                final_distance_to_goal = event.get("distance_to_goal_m")
                if first_collision is not None and route_progress_at_first_collision is None:
                    route_progress_at_first_collision = event.get("route_progress_pct")
    except Exception as exc:
        return {"events_read_error": str(exc)}

    top_actor = None
    if collision_actor_counts:
        top_actor = max(collision_actor_counts.items(), key=lambda item: item[1])[0]

    first_collision_step = first_collision.get("step") if first_collision else None
    stuck_after_collision = bool(
        first_collision_step is not None
        and final_route_progress is not None
        and final_route_progress < 10.0
        and final_distance_to_goal is not None
        and final_distance_to_goal > 50.0
    )
    return {
        "first_collision_step": first_collision_step,
        "first_collision_actor": first_collision.get("other_actor") if first_collision else None,
        "first_collision_impulse_norm": first_collision.get("impulse_norm") if first_collision else None,
        "collision_actor_top": top_actor,
        "collision_actor_counts": collision_actor_counts,
        "route_progress_at_first_collision_pct": route_progress_at_first_collision,
        "stuck_after_collision": stuck_after_collision,
    }


def _build_child_command(args: argparse.Namespace, variant: RecoveryVariant, route_output_dir: Path) -> list[str]:
    return [
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
        str(args.steps),
        "--target-speed-kmh",
        str(variant.target_speed_kmh),
        "--goal-tolerance-m",
        str(args.goal_tolerance_m),
        "--route-sampling-resolution-m",
        str(variant.route_sampling_resolution_m),
        "--lookahead-waypoints",
        str(variant.lookahead_waypoints),
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


def _run_child(command: list[str], variant: RecoveryVariant, *, timeout_sec: float, env: dict[str, str]) -> VariantResult:
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
        return VariantResult(
            variant=variant,
            source="recovery_run",
            command=command,
            exit_code=completed.returncode,
            duration_sec=round(time.perf_counter() - started, 3),
            timed_out=False,
            stdout=stdout,
            stderr=stderr,
            evidence_dir=evidence_dir,
            metrics=_read_metrics(evidence_dir),
            diagnostics=_diagnose_events(evidence_dir),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        evidence_dir = _parse_evidence_dir(stdout, stderr)
        return VariantResult(
            variant=variant,
            source="recovery_run",
            command=command,
            exit_code=124,
            duration_sec=round(time.perf_counter() - started, 3),
            timed_out=True,
            stdout=stdout.strip(),
            stderr=(stderr.strip() or f"timeout after {timeout_sec}s"),
            evidence_dir=evidence_dir,
            metrics=_read_metrics(evidence_dir),
            diagnostics=_diagnose_events(evidence_dir),
        )


def _baseline_reference(args: argparse.Namespace) -> VariantResult | None:
    if not args.baseline_evidence_dir or not args.baseline_evidence_dir.exists():
        return None
    evidence_dir = str(args.baseline_evidence_dir)
    return VariantResult(
        variant=BASELINE_VARIANT,
        source="baseline_reference",
        command=[],
        exit_code=1,
        duration_sec=0.0,
        timed_out=False,
        stdout="baseline reference loaded from existing evidence",
        stderr="",
        evidence_dir=evidence_dir,
        metrics=_read_metrics(evidence_dir),
        diagnostics=_diagnose_events(evidence_dir),
    )


def _dry_run_result(variant: RecoveryVariant, command: list[str]) -> VariantResult:
    return VariantResult(
        variant=variant,
        source="dry_run",
        command=command,
        exit_code=0,
        duration_sec=0.0,
        timed_out=False,
        stdout="dry run; command not executed",
        stderr="",
        evidence_dir=None,
        metrics={"result": "dry_run"},
        diagnostics={},
    )


def _row_from_result(result: VariantResult, args: argparse.Namespace) -> dict[str, Any]:
    metrics = result.metrics
    diagnostics = result.diagnostics
    notes = result.variant.notes
    if metrics.get("json_read_error"):
        notes = f"{notes}; metrics_read_error={metrics['json_read_error']}"
    if diagnostics.get("events_read_error"):
        notes = f"{notes}; events_read_error={diagnostics['events_read_error']}"
    if result.timed_out:
        notes = f"{notes}; child runner timed out"

    return {
        "variant_id": result.variant.variant_id,
        "source": result.source,
        "town": args.town,
        "start_spawn_index": args.start_spawn_index,
        "end_spawn_index": args.end_spawn_index,
        "target_speed_kmh": result.variant.target_speed_kmh,
        "route_sampling_resolution_m": result.variant.route_sampling_resolution_m,
        "lookahead_waypoints": result.variant.lookahead_waypoints,
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
        "first_collision_step": diagnostics.get("first_collision_step"),
        "first_collision_actor": diagnostics.get("first_collision_actor"),
        "first_collision_impulse_norm": diagnostics.get("first_collision_impulse_norm"),
        "collision_actor_top": diagnostics.get("collision_actor_top"),
        "stuck_after_collision": diagnostics.get("stuck_after_collision"),
        "timeout": result.timed_out,
        "result": metrics.get("result") or ("timeout" if result.timed_out else "failed"),
        "exit_code": result.exit_code,
        "evidence_dir": result.evidence_dir,
        "notes": notes,
    }


def _build_summary_json(rows: list[dict[str, Any]], *, dry_run: bool) -> dict[str, Any]:
    recovery_rows = [row for row in rows if row["source"] == "recovery_run"]
    recovered_rows = [row for row in recovery_rows if row["result"] == "passed" and row["exit_code"] == 0]
    baseline = next((row for row in rows if row["source"] == "baseline_reference"), None)
    return {
        "phase": "Phase 12A-R05",
        "dry_run": dry_run,
        "row_count": len(rows),
        "recovery_attempt_count": len(recovery_rows),
        "recovered_count": len(recovered_rows),
        "recovery_passed": bool(recovered_rows),
        "best_variant_id": recovered_rows[0]["variant_id"] if recovered_rows else None,
        "baseline_failure_signature": {
            "result": baseline.get("result") if baseline else None,
            "collision_actor_top": baseline.get("collision_actor_top") if baseline else None,
            "first_collision_step": baseline.get("first_collision_step") if baseline else None,
            "route_progress_pct": baseline.get("route_progress_pct") if baseline else None,
            "distance_to_goal_m": baseline.get("distance_to_goal_m") if baseline else None,
        },
        "results": rows,
        "benchmark_boundaries": {
            "route_benchmark_verified": False,
            "infraction_benchmark_verified": False,
            "leaderboard_evaluated": False,
            "leaderboard_routes_exported": False,
            "leaderboard_route_criteria_evaluated": False,
        },
    }


def _build_manifest(args: argparse.Namespace, *, run_dir: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _build_summary_json(rows, dry_run=args.dry_run)
    return {
        "phase": "Phase 12A-R05",
        "status": "recovery_passed" if summary["recovery_passed"] else "recovery_blocked",
        "created_at_utc": _utc_now().isoformat(),
        "run_dir": str(run_dir),
        "dry_run": args.dry_run,
        "child_runner": str(CHILD_RUNNER),
        "python_executable": args.python_executable,
        "host": args.host,
        "port": args.port,
        "town": args.town,
        "start_spawn_index": args.start_spawn_index,
        "end_spawn_index": args.end_spawn_index,
        "baseline_evidence_dir": str(args.baseline_evidence_dir) if args.baseline_evidence_dir else None,
        "variants": [asdict(variant) for variant in VARIANTS],
        "summary": {
            "row_count": summary["row_count"],
            "recovery_attempt_count": summary["recovery_attempt_count"],
            "recovered_count": summary["recovered_count"],
            "recovery_passed": summary["recovery_passed"],
            "best_variant_id": summary["best_variant_id"],
        },
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        "leaderboard_routes_exported": False,
        "leaderboard_route_criteria_evaluated": False,
        "route_benchmark_verified": False,
        "infraction_benchmark_verified": False,
        "leaderboard_evaluated": False,
    }


def _write_commands(path: Path, parent_command: list[str], results: list[VariantResult]) -> None:
    lines = ["# Phase 12A-R05 parent command", subprocess.list2cmdline(parent_command), ""]
    lines.append("# Phase 11M child commands")
    for result in results:
        lines.append(f"# {result.variant.variant_id} ({result.source})")
        if result.command:
            lines.append(subprocess.list2cmdline(result.command))
        else:
            lines.append(f"# baseline_evidence_dir={result.evidence_dir}")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_readme(path: Path, *, run_dir: Path, rows: list[dict[str, Any]], dry_run: bool) -> None:
    recovered = [row for row in rows if row["source"] == "recovery_run" and row["result"] == "passed" and row["exit_code"] == 0]
    body = f"""# Phase 12A-R05 Route 05 Recovery Experiment

This directory contains Route 05 diagnosis and recovery evidence.

```text
dry_run={str(dry_run).lower()}
row_count={len(rows)}
recovered_count={len(recovered)}
```

This is a targeted recovery smoke experiment. It is not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

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
    parser = argparse.ArgumentParser(description="MA-VLNA Phase 12A-R05 route 05 recovery experiment")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--start-spawn-index", type=int, default=40)
    parser.add_argument("--end-spawn-index", type=int, default=126)
    parser.add_argument("--steps", type=int, default=2500)
    parser.add_argument("--goal-tolerance-m", type=float, default=3.0)
    parser.add_argument("--perception-backend", default="dummy", choices=["dummy", "yolo", "yolov9", "rtdetr"])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--baseline-evidence-dir", type=Path, default=DEFAULT_BASELINE_EVIDENCE_DIR)
    parser.add_argument("--route-timeout-sec", type=float, default=1800.0)
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

    results: list[VariantResult] = []
    baseline = _baseline_reference(args)
    if baseline:
        results.append(baseline)

    for variant in VARIANTS:
        variant_output_dir = runs_dir / variant.variant_id
        variant_output_dir.mkdir(parents=True, exist_ok=True)
        command = _build_child_command(args, variant, variant_output_dir)
        print(f"{variant.variant_id}: {subprocess.list2cmdline(command)}")
        if args.dry_run:
            results.append(_dry_run_result(variant, command))
            continue
        results.append(_run_child(command, variant, timeout_sec=args.route_timeout_sec, env=env))

    rows = [_row_from_result(result, args) for result in results]
    summary = _build_summary_json(rows, dry_run=args.dry_run)
    _write_summary_csv(run_dir / "summary.csv", rows)
    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "manifest.json", _build_manifest(args, run_dir=run_dir, rows=rows))
    _write_commands(run_dir / "commands.txt", [sys.executable, *sys.argv], results)
    _write_readme(run_dir / "README.md", run_dir=run_dir, rows=rows, dry_run=args.dry_run)

    if args.dry_run:
        print("Phase 12A-R05 Recovery Dry Run — child commands written without launching CARLA.")
        print(f"experiment_dir={run_dir}")
        return 0

    if summary["recovery_passed"]:
        print("Phase 12A-R05 Recovery Pass — at least one Route 05 recovery variant reached the goal.")
        print(f"experiment_dir={run_dir}")
        return 0

    print("Phase 12A-R05 Recovery Blocked — no Route 05 recovery variant reached the goal.")
    print(f"experiment_dir={run_dir}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

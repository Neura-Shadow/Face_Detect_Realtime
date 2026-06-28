"""
Phase 12C-DUMMY dummy perception backend runtime confirmation.

This wrapper intentionally does not import CARLA. It delegates real simulator
execution to the existing Phase 12B runtime parent with:

    controller_mode=grp_follower
    perception_backend=dummy

The wrapper exists to give Phase 12C a narrow runtime confirmation artifact for
the dummy perception backend without changing the Phase 12C scaffold-only
contract or widening the benchmark claim.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "phase12"
DEFAULT_CARLA_ROOT = Path(r"D:\CARLA\packages\CARLA_0.9.16")
DEFAULT_CARLA_PYTHON = r"D:\CARLA\envs\ma-vlna-carla312\python.exe"

PHASE = "Phase 12C-DUMMY"
STATUS_PASS = "dummy_runtime_confirmed"
STATUS_BLOCKED = "dummy_runtime_blocked"
STATUS_FAILED = "dummy_runtime_failed"
STATUS_DRY_RUN = "dummy_runtime_command_prepared"
BENCHMARK_BOUNDARY_SCOPE = "dummy_perception_backend_runtime_confirmation_not_carla_leaderboard"

ROUTE_IDS = ("route_01", "route_02", "route_03", "route_04", "route_05")
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
    "result",
    "exit_code",
    "steps_completed",
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
    "metrics_read_status",
    "notes",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def _resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _next_run_dir(output_dir: Path, timestamp: str | None) -> Path:
    base = timestamp or _timestamp(_utc_now())
    candidate = output_dir / base
    suffix = 1
    while candidate.exists():
        candidate = output_dir / f"{base}-{suffix}"
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
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


def _parse_experiment_dir(stdout: str, stderr: str) -> str | None:
    for line in (stdout + "\n" + stderr).splitlines():
        line = line.strip()
        if line.startswith("experiment_dir="):
            return line.split("=", 1)[1].strip()
    return None


def _selected_route_ids(args: argparse.Namespace) -> list[str]:
    return list(args.route_id or ROUTE_IDS)


def _build_child_command(args: argparse.Namespace, child_output_root: Path) -> list[str]:
    command = [
        args.base_python if args.dry_run else args.python_executable,
        str(REPO_ROOT / "scripts" / "run_phase12b_controller_ablation_experiment.py"),
        "--controller-mode",
        "grp_follower",
        "--perception-backend",
        "dummy",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--town",
        args.town,
        "--python-executable",
        args.python_executable,
        "--base-python",
        args.base_python,
        "--child-timeout-sec",
        str(args.child_timeout_sec),
        "--output-dir",
        str(child_output_root),
        "--carla-root",
        str(args.carla_root),
    ]
    command.append("--dry-run" if args.dry_run else "--execute-runtime")
    for route_id in _selected_route_ids(args):
        command.extend(["--route-id", route_id])
    return command


def _run_child(command: list[str], *, args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    raw_dir = run_dir / "raw_outputs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = raw_dir / "phase12b_parent.stdout.txt"
    stderr_path = raw_dir / "phase12b_parent.stderr.txt"
    started = time.perf_counter()
    env = os.environ.copy()
    env["CARLA_ROOT"] = str(args.carla_root)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.parent_timeout_sec,
            check=False,
        )
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        stdout_path.write_text(stdout, encoding="utf-8", errors="replace")
        stderr_path.write_text(stderr, encoding="utf-8", errors="replace")
        return {
            "exit_code": completed.returncode,
            "timed_out": False,
            "duration_sec": round(time.perf_counter() - started, 3),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "experiment_dir": _parse_experiment_dir(stdout, stderr),
            "stdout_tail": "\n".join(stdout.splitlines()[-10:]),
            "stderr_tail": "\n".join(stderr.splitlines()[-10:]),
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        stdout_path.write_text(stdout.strip(), encoding="utf-8", errors="replace")
        timeout_stderr = (stderr.strip() or f"timeout after {args.parent_timeout_sec}s")
        stderr_path.write_text(timeout_stderr, encoding="utf-8", errors="replace")
        return {
            "exit_code": 124,
            "timed_out": True,
            "duration_sec": round(time.perf_counter() - started, 3),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "experiment_dir": _parse_experiment_dir(stdout, stderr),
            "stdout_tail": "\n".join(stdout.splitlines()[-10:]),
            "stderr_tail": timeout_stderr,
        }
    except OSError as exc:
        stderr_path.write_text(str(exc), encoding="utf-8", errors="replace")
        stdout_path.write_text("", encoding="utf-8")
        return {
            "exit_code": 127,
            "timed_out": False,
            "duration_sec": round(time.perf_counter() - started, 3),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "experiment_dir": None,
            "stdout_tail": "",
            "stderr_tail": str(exc),
        }


def _rows_from_child_summary(child_summary: dict[str, Any]) -> list[dict[str, Any]]:
    results = child_summary.get("results")
    if not isinstance(results, list):
        return []
    rows = []
    for item in results:
        if isinstance(item, dict):
            row = {column: item.get(column) for column in SUMMARY_COLUMNS}
            row["notes"] = item.get("notes")
            rows.append(row)
    return rows


def _all_boundary_fields_false(child_summary: dict[str, Any]) -> bool:
    for key, expected in BOUNDARY_FIELDS.items():
        if child_summary.get(key, expected) is not False:
            return False
    nested = child_summary.get("benchmark_boundaries")
    if isinstance(nested, dict):
        return all(nested.get(key, expected) is False for key, expected in BOUNDARY_FIELDS.items())
    return True


def _confirmation_assertions(
    *,
    args: argparse.Namespace,
    child: dict[str, Any],
    child_summary: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_count = len(_selected_route_ids(args))
    return {
        "child_exit_zero": child["exit_code"] == 0,
        "child_summary_loaded": bool(child_summary) and not child_summary.get("json_read_error"),
        "row_count_matches_requested_routes": len(rows) == expected_count,
        "all_rows_grp_follower": all(row.get("controller_mode") == "grp_follower" for row in rows),
        "all_rows_goal_reached": bool(rows) and all(row.get("fixed_route_goal_reached") is True for row in rows),
        "all_rows_runtime_passed": bool(rows) and all(row.get("result") in {"passed", "passed_without_structured_metrics"} for row in rows),
        "phase12b_all_runtime_rows_passed": child_summary.get("all_runtime_rows_passed") is True,
        "perception_backend": "dummy",
        "all_boundary_fields_false": _all_boundary_fields_false(child_summary),
        "carla_imported_by_wrapper": False,
        "raw_runtime_evidence_committed": False,
    }


def _is_confirmed(assertions: dict[str, Any]) -> bool:
    required_keys = (
        "child_exit_zero",
        "child_summary_loaded",
        "row_count_matches_requested_routes",
        "all_rows_grp_follower",
        "all_rows_goal_reached",
        "all_rows_runtime_passed",
        "phase12b_all_runtime_rows_passed",
        "all_boundary_fields_false",
    )
    return all(assertions.get(key) is True for key in required_keys)


def _build_summary(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    child_command: list[str],
    child: dict[str, Any],
) -> dict[str, Any]:
    child_summary_path = Path(child["experiment_dir"]) / "summary.json" if child.get("experiment_dir") else None
    child_summary = _read_json(child_summary_path) if child_summary_path else {}
    rows = _rows_from_child_summary(child_summary)
    assertions = _confirmation_assertions(args=args, child=child, child_summary=child_summary, rows=rows)
    confirmed = (not args.dry_run) and _is_confirmed(assertions)
    status = STATUS_DRY_RUN if args.dry_run else STATUS_PASS if confirmed else STATUS_BLOCKED if child.get("experiment_dir") else STATUS_FAILED
    collision_total = sum(int(row.get("collision_count") or 0) for row in rows)
    lane_invasion_total = sum(int(row.get("lane_invasion_count") or 0) for row in rows)
    return {
        "phase": PHASE,
        "status": status,
        "dry_run": args.dry_run,
        "confirmed": confirmed,
        "run_dir": str(run_dir),
        "child_command": _command_text(child_command),
        "child_result": child,
        "child_experiment_dir": child.get("experiment_dir"),
        "child_summary_path": str(child_summary_path) if child_summary_path else None,
        "perception_backend": "dummy",
        "controller_mode": "grp_follower",
        "town": args.town,
        "route_ids": _selected_route_ids(args),
        "requested_route_count": len(_selected_route_ids(args)),
        "row_count": len(rows),
        "passed_count": child_summary.get("passed_count"),
        "blocked_count": child_summary.get("blocked_count"),
        "failed_count": child_summary.get("failed_count"),
        "executed_row_count": child_summary.get("executed_row_count"),
        "all_dummy_routes_confirmed": confirmed,
        "collision_count_total": collision_total,
        "lane_invasion_count_total": lane_invasion_total,
        "results": rows,
        "assertions": assertions,
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        **BOUNDARY_FIELDS,
        "benchmark_boundaries": dict(BOUNDARY_FIELDS),
    }


def _write_commands(path: Path, command: list[str]) -> None:
    lines = [
        "# Phase 12C-DUMMY parent command",
        _command_text([sys.executable, *sys.argv]),
        "",
        "# Delegated Phase 12B runtime command",
        _command_text(command),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_environment(path: Path, args: argparse.Namespace) -> None:
    payload = {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "host": args.host,
        "port": args.port,
        "carla_root": str(args.carla_root),
        "carla_root_exists": args.carla_root.exists(),
        "carla_python": args.python_executable,
        "carla_python_exists": Path(args.python_executable).exists(),
        "base_python": args.base_python,
    }
    _write_json(path, payload)


def _write_readme(path: Path, summary: dict[str, Any]) -> None:
    body = f"""# Phase 12C-DUMMY Dummy Backend Runtime Confirmation

Status:

```text
{summary["status"]}
```

```text
perception_backend=dummy
controller_mode=grp_follower
requested_route_count={summary["requested_route_count"]}
row_count={summary["row_count"]}
passed_count={summary["passed_count"]}
blocked_count={summary["blocked_count"]}
failed_count={summary["failed_count"]}
all_dummy_routes_confirmed={str(summary["all_dummy_routes_confirmed"]).lower()}
```

Boundary:

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```
"""
    path.write_text(body, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Confirm Phase 12C dummy perception backend runtime")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--python-executable", default=DEFAULT_CARLA_PYTHON)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--child-timeout-sec", type=float, default=2400.0)
    parser.add_argument("--parent-timeout-sec", type=float, default=14400.0)
    parser.add_argument("--route-id", action="append", choices=list(ROUTE_IDS))
    parser.add_argument("--dry-run", action="store_true", help="Write the delegated command without launching runtime rows")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.output_dir = _resolve_repo_path(args.output_dir)
    args.carla_root = _resolve_repo_path(args.carla_root)

    run_dir = _next_run_dir(args.output_dir, args.timestamp)
    child_output_root = run_dir / "runs"
    child_output_root.mkdir(parents=True, exist_ok=True)
    child_command = _build_child_command(args, child_output_root)
    _write_commands(run_dir / "commands.txt", child_command)
    _write_environment(run_dir / "environment.json", args)
    child = _run_child(child_command, args=args, run_dir=run_dir)
    summary = _build_summary(args=args, run_dir=run_dir, child_command=child_command, child=child)
    _write_json(run_dir / "summary.json", summary)
    _write_json(
        run_dir / "manifest.json",
        {
            "phase": PHASE,
            "status": summary["status"],
            "created_at_utc": _utc_now().isoformat(),
            "run_dir": str(run_dir),
            "output_files": [
                "manifest.json",
                "summary.json",
                "summary.csv",
                "commands.txt",
                "environment.json",
                "README.md",
                "raw_outputs/phase12b_parent.stdout.txt",
                "raw_outputs/phase12b_parent.stderr.txt",
            ],
            "child_experiment_dir": summary["child_experiment_dir"],
            "raw_runtime_evidence_committed": False,
            "benchmark_boundary_prepared": True,
            "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
            **BOUNDARY_FIELDS,
        },
    )
    _write_csv(run_dir / "summary.csv", summary["results"])
    _write_readme(run_dir / "README.md", summary)

    print(f"experiment_dir={run_dir}")
    if summary["confirmed"]:
        print("Phase 12C-DUMMY Runtime Confirmation Pass - dummy backend rows confirmed in real CARLA runtime.")
        return 0
    if args.dry_run:
        print("Phase 12C-DUMMY Runtime Command Prepared - dry-run command scaffold written without launching CARLA.")
        return 0
    print("Phase 12C-DUMMY Runtime Blocked - dummy backend runtime confirmation did not pass; evidence preserved.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""
Phase 12C perception backend ablation scaffold.

This runner prepares a controlled 5-route x 3-perception-backend matrix for
later CARLA runtime work. It intentionally does not import CARLA and does not
start a CARLA server. Optional backends are preflighted at import level only;
when YOLO or RT-DETR dependencies are missing, rows are marked
``backend_unavailable`` instead of failing the whole scaffold.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "phase12"
DEFAULT_CARLA_ROOT = Path(r"D:\CARLA\packages\CARLA_0.9.16")
DEFAULT_CARLA_PYTHON = r"D:\CARLA\envs\ma-vlna-carla312\python.exe"

PHASE = "Phase 12C"
STATUS = "perception_backend_ablation_prepared"
BENCHMARK_BOUNDARY_SCOPE = "perception_backend_ablation_scaffold_only_not_carla_leaderboard"

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
    "horizon_steps",
    "controller_mode",
    "perception_backend_mode",
    "perception_backend",
    "perception_model",
    "backend_optional",
    "backend_available",
    "backend_status",
    "runtime_command_status",
    "result",
    "command",
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
class BackendSpec:
    mode: str
    backend: str
    model_name: str
    optional: bool
    dependency_name: str | None
    notes: str


ROUTE_MATRIX = (
    RouteSpec("route_01", 3, 30, 2500, 18.0, 2.0, 8),
    RouteSpec("route_02", 8, 52, 2800, 18.0, 2.0, 8),
    RouteSpec("route_03", 12, 74, 2500, 18.0, 2.0, 8),
    RouteSpec("route_04", 25, 101, 2500, 18.0, 2.0, 8),
    RouteSpec("route_05", 40, 126, 5400, 8.0, 1.0, 3),
)

BACKEND_MATRIX = (
    BackendSpec(
        mode="dummy",
        backend="dummy",
        model_name="dummy",
        optional=False,
        dependency_name=None,
        notes="Always available deterministic scaffold backend.",
    ),
    BackendSpec(
        mode="yolo_optional",
        backend="yolo",
        model_name="yolov8n.pt",
        optional=True,
        dependency_name="ultralytics",
        notes="Optional YOLO backend; mark backend_unavailable when ultralytics is not installed.",
    ),
    BackendSpec(
        mode="rt_detr_optional",
        backend="rtdetr",
        model_name="rtdetr-l.pt",
        optional=True,
        dependency_name="ultralytics",
        notes="Optional RT-DETR backend; mark backend_unavailable when ultralytics is not installed.",
    ),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _next_run_dir(output_dir: Path, timestamp: str | None) -> Path:
    candidate = output_dir / (timestamp or _timestamp(_utc_now()))
    suffix = 1
    while candidate.exists():
        candidate = output_dir / f"{candidate.name}-{suffix}"
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


def _command_text(command: list[str]) -> str:
    return subprocess.list2cmdline(command)


def _dependency_available(spec: BackendSpec) -> bool:
    if spec.dependency_name is None:
        return True
    return importlib.util.find_spec(spec.dependency_name) is not None


def _build_runtime_command(args: argparse.Namespace, route: RouteSpec, backend: BackendSpec) -> list[str]:
    return [
        args.python_executable,
        str(REPO_ROOT / "scripts" / "run_phase12b_controller_ablation_experiment.py"),
        "--execute-runtime",
        "--route-id",
        route.route_id,
        "--controller-mode",
        args.controller_mode,
        "--runtime-row-limit",
        "1",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--town",
        args.town,
        "--perception-backend",
        backend.backend,
        "--python-executable",
        args.python_executable,
        "--base-python",
        args.base_python,
        "--child-timeout-sec",
        str(args.child_timeout_sec),
        "--output-dir",
        str(args.output_dir),
        "--carla-root",
        str(args.carla_root),
    ]


def _row_from_matrix(
    args: argparse.Namespace,
    route: RouteSpec,
    backend: BackendSpec,
    *,
    backend_available: bool,
) -> dict[str, Any]:
    backend_status = "available" if backend_available else "backend_unavailable"
    runtime_status = (
        "wired_runtime_command"
        if backend_available
        else "blocked_optional_backend_unavailable"
    )
    result = "dry_run" if backend_available else "backend_unavailable"
    command = _build_runtime_command(args, route, backend) if backend_available else []
    notes = backend.notes
    if not backend_available:
        notes = f"{notes} dependency_missing={backend.dependency_name}"
    return {
        "route_id": route.route_id,
        "town": args.town,
        "start_spawn_index": route.start_spawn_index,
        "end_spawn_index": route.end_spawn_index,
        "horizon_steps": route.horizon_steps,
        "controller_mode": args.controller_mode,
        "perception_backend_mode": backend.mode,
        "perception_backend": backend.backend,
        "perception_model": backend.model_name,
        "backend_optional": backend.optional,
        "backend_available": backend_available,
        "backend_status": backend_status,
        "runtime_command_status": runtime_status,
        "result": result,
        "command": _command_text(command) if command else "",
        "notes": notes,
    }


def _build_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    availability = {backend.mode: _dependency_available(backend) for backend in BACKEND_MATRIX}
    for route in ROUTE_MATRIX:
        if args.route_id and route.route_id not in args.route_id:
            continue
        for backend in BACKEND_MATRIX:
            if args.perception_backend_mode and backend.mode not in args.perception_backend_mode:
                continue
            rows.append(
                _row_from_matrix(
                    args,
                    route,
                    backend,
                    backend_available=availability[backend.mode],
                )
            )
    return rows


def _summary_payload(args: argparse.Namespace, rows: list[dict[str, Any]]) -> dict[str, Any]:
    route_ids = sorted({str(row["route_id"]) for row in rows})
    backend_modes = sorted({str(row["perception_backend_mode"]) for row in rows})
    available_count = sum(1 for row in rows if row["backend_available"] is True)
    unavailable_count = sum(1 for row in rows if row["result"] == "backend_unavailable")
    return {
        "phase": PHASE,
        "status": STATUS,
        "dry_run": True,
        "row_count": len(rows),
        "route_count": len(route_ids),
        "backend_count": len(backend_modes),
        "route_ids": route_ids,
        "perception_backend_modes": backend_modes,
        "controller_mode": args.controller_mode,
        "available_row_count": available_count,
        "backend_unavailable_count": unavailable_count,
        "continue_all_policy": True,
        "results": rows,
        "assertions": {
            "expected_full_row_count": len(rows) == 15 if not args.route_id and not args.perception_backend_mode else None,
            "dummy_rows_available": all(
                row["backend_available"] is True
                for row in rows
                if row["perception_backend_mode"] == "dummy"
            ),
            "optional_unavailable_rows_do_not_fail_scaffold": True,
            "all_boundary_fields_false": all(value is False for value in BOUNDARY_FIELDS.values()),
            "carla_import_required": False,
            "carla_server_required": False,
        },
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        **BOUNDARY_FIELDS,
    }


def _manifest_payload(args: argparse.Namespace, run_dir: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _summary_payload(args, rows)
    return {
        "phase": PHASE,
        "status": summary["status"],
        "created_at_utc": _utc_now().isoformat(),
        "run_dir": str(run_dir),
        "output_files": [
            "manifest.json",
            "summary.csv",
            "summary.json",
            "commands.txt",
            "README.md",
        ],
        "route_matrix": [asdict(route) for route in ROUTE_MATRIX],
        "backend_matrix": [asdict(backend) for backend in BACKEND_MATRIX],
        "controller_mode": args.controller_mode,
        "host": args.host,
        "port": args.port,
        "town": args.town,
        "python_executable": args.python_executable,
        "base_python": args.base_python,
        "carla_root": str(args.carla_root),
        "carla_import_required": False,
        "carla_server_required": False,
        "child_processes_launched": False,
        "raw_runtime_evidence_committed": False,
        "row_count": summary["row_count"],
        "available_row_count": summary["available_row_count"],
        "backend_unavailable_count": summary["backend_unavailable_count"],
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        **BOUNDARY_FIELDS,
    }


def _write_commands(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Phase 12C perception backend ablation child commands",
        "# Commands are scaffolded only; Phase 12C Prepared does not launch CARLA.",
        "",
    ]
    for row in rows:
        lines.append(
            f"# {row['route_id']} / {row['perception_backend_mode']} / {row['result']}"
        )
        lines.append(str(row["command"]) if row["command"] else "# backend_unavailable")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_readme(path: Path, run_dir: Path, summary: dict[str, Any]) -> None:
    body = f"""# Phase 12C Perception Backend Ablation Prepared

Status:

```text
Phase 12C Perception Backend Ablation Prepared - backend matrix, optional dependency preflight, and command scaffold are implemented.
```

This scaffold reads no CARLA runtime state, imports no `carla` package, and
does not start a CARLA server.

```text
row_count={summary["row_count"]}
route_count={summary["route_count"]}
backend_count={summary["backend_count"]}
available_row_count={summary["available_row_count"]}
backend_unavailable_count={summary["backend_unavailable_count"]}
controller_mode={summary["controller_mode"]}
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
    parser = argparse.ArgumentParser(description="Prepare Phase 12C perception backend ablation scaffold")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--controller-mode", default="grp_follower", choices=["grp_follower"])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--python-executable", default=DEFAULT_CARLA_PYTHON)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--child-timeout-sec", type=float, default=2400.0)
    parser.add_argument("--route-id", action="append", choices=[route.route_id for route in ROUTE_MATRIX])
    parser.add_argument("--perception-backend-mode", action="append", choices=[backend.mode for backend in BACKEND_MATRIX])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.output_dir = _resolve(args.output_dir)
    args.carla_root = _resolve(args.carla_root)

    rows = _build_rows(args)
    run_dir = _next_run_dir(args.output_dir, args.timestamp)
    _write_csv(run_dir / "summary.csv", rows)
    summary = _summary_payload(args, rows)
    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "manifest.json", _manifest_payload(args, run_dir, rows))
    _write_commands(run_dir / "commands.txt", rows)
    _write_readme(run_dir / "README.md", run_dir, summary)

    print("Phase 12C Perception Backend Ablation Prepared - scaffold written without launching CARLA.")
    print(f"experiment_dir={run_dir}")
    if summary["backend_unavailable_count"]:
        print(f"backend_unavailable_count={summary['backend_unavailable_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

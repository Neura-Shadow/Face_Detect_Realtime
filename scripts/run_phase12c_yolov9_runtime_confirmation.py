"""
Phase 12C-YOLOv9-R1 selected YOLOv9 backend runtime confirmation.

This parent wrapper intentionally does not import CARLA. It verifies the
official external YOLOv9 source-adapter readiness contract, checks CARLA server
TCP reachability, and delegates the selected runtime row to the existing
Phase 12B controller-ablation runtime path.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "phase12"
DEFAULT_CARLA_ROOT = Path(r"D:\CARLA\packages\CARLA_0.9.16")
DEFAULT_CARLA_PYTHON = r"D:\CARLA\envs\ma-vlna-carla312\python.exe"
DEFAULT_YOLOV9_ROOT = Path(r"D:\AIModels\yolov9")
DEFAULT_YOLOV9_WEIGHTS = Path(r"D:\AIModels\yolov9\yolov9-c-converted.pt")
DEFAULT_SOURCE_ADAPTER_EVIDENCE_DIR = Path(r"experiments\phase12\20260630T060621Z")
DEFAULT_POST_UNLOCK_EVIDENCE_DIR = Path(r"experiments\phase12\20260630T061015Z")
DEFAULT_ROWS_REFRESH_DIR = Path(r"experiments\phase12\20260630T060823Z")

PHASE = "Phase 12C-YOLOv9-R1"
STATUS_PASS = (
    "Phase 12C-YOLOv9-R1 Runtime Confirmation Pass - selected YOLOv9 backend row "
    "executed in real CARLA runtime."
)
STATUS_BLOCKED = (
    "Phase 12C-YOLOv9-R1 Runtime Confirmation Blocked - selected YOLOv9 backend row "
    "did not complete or did not satisfy the selected runtime smoke gate."
)
STATUS_DRY_RUN = "Phase 12C-YOLOv9-R1 Runtime Command Prepared - dry-run evidence written."
BENCHMARK_BOUNDARY_SCOPE = "selected_yolov9_single_route_runtime_confirmation_not_benchmark"

BOUNDARY_FIELDS = {
    "full_phase12c_perception_ablation_runtime_pass": False,
    "rt_detr_runtime_verified": False,
    "route_benchmark_verified": False,
    "infraction_benchmark_verified": False,
    "leaderboard_evaluated": False,
    "leaderboard_routes_exported": False,
    "leaderboard_route_criteria_evaluated": False,
}

SUMMARY_COLUMNS = (
    "phase",
    "status",
    "route_id",
    "controller_mode",
    "perception_backend",
    "runtime_scope",
    "target_python",
    "carla_root",
    "carla_server_host",
    "carla_server_port",
    "source_adapter_verified",
    "post_unlock_verified",
    "yolov9_source_adapter_verified",
    "edge_yolov9_fallback_used",
    "edge_yolov9_no_fallback_verified",
    "phase12c_yolov9_rows_available",
    "backend_unavailable_count",
    "runtime_confirmation_executed",
    "carla_route_runtime_executed",
    "row_count",
    "executed_row_count",
    "passed_count",
    "blocked_count",
    "failed_count",
    "goal_reached",
    "distance_to_goal_m",
    "route_progress_pct",
    "grp_route_progress_pct",
    "collision_count",
    "lane_invasion_count",
    "avg_speed_kmh",
    "max_speed_kmh",
    "child_exit_code",
    "metrics_read_status",
    "yolo_runtime_row_verified",
)


@dataclass(frozen=True)
class RouteSpec:
    route_id: str = "route_01"
    start_spawn_index: int = 3
    end_spawn_index: int = 30
    horizon_steps: int = 2500
    target_speed_kmh: float = 18.0
    route_sampling_resolution_m: float = 2.0
    lookahead_waypoints: int = 8


ROUTES = {"route_01": RouteSpec()}


@dataclass(frozen=True)
class CommandResult:
    name: str
    command: list[str]
    exit_code: int
    duration_sec: float
    stdout_path: str
    stderr_path: str
    stdout_tail: str
    stderr_tail: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(now: datetime | None = None) -> str:
    return (now or _utc_now()).strftime("%Y%m%dT%H%M%SZ")


def _resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _next_run_dir(output_dir: Path, timestamp: str | None) -> Path:
    base = timestamp or _timestamp()
    candidate = output_dir / base
    suffix = 1
    while candidate.exists():
        candidate = output_dir / f"{base}-{suffix}"
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=False)
    (candidate / "raw_outputs").mkdir(exist_ok=True)
    return candidate


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"json_read_error": f"file not found: {path}"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"json_read_error": str(exc)}


def _write_csv(path: Path, summary: dict[str, Any]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerow({column: summary.get(column) for column in SUMMARY_COLUMNS})


def _tail(text: str, max_lines: int = 14) -> str:
    return "\n".join((text or "").splitlines()[-max_lines:])


def _command_text(command: list[str]) -> str:
    return subprocess.list2cmdline([str(part) for part in command])


def _run_command(
    *,
    name: str,
    command: list[str],
    raw_dir: Path,
    env: dict[str, str],
    timeout_sec: float,
) -> CommandResult:
    stdout_path = raw_dir / f"{name}.stdout.txt"
    stderr_path = raw_dir / f"{name}.stderr.txt"
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
        stdout = completed.stdout
        stderr = completed.stderr
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        stderr = (stderr + f"\nTIMEOUT after {timeout_sec}s").strip()
        exit_code = 124
    except OSError as exc:
        stdout = ""
        stderr = f"OSERROR: {exc}"
        exit_code = 127
    stdout_path.write_text(stdout, encoding="utf-8", errors="replace")
    stderr_path.write_text(stderr, encoding="utf-8", errors="replace")
    return CommandResult(
        name=name,
        command=command,
        exit_code=exit_code,
        duration_sec=round(time.perf_counter() - started, 3),
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        stdout_tail=_tail(stdout),
        stderr_tail=_tail(stderr),
    )


def _parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key and all(ch.isalnum() or ch == "_" for ch in key):
            values[key] = value.strip()
    return values


def _parse_experiment_dir(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("experiment_dir="):
            return stripped.split("=", 1)[1].strip()
    return None


def _tcp_reachable(host: str, port: int, timeout_sec: float = 5.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except OSError:
        return False


def _env_with_runtime_paths(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    env["CARLA_ROOT"] = str(args.carla_root)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _source_adapter_evidence_ok(path: Path) -> bool:
    summary = _read_json(path / "summary.json")
    return (
        summary.get("source_adapter_verified") is True
        and summary.get("edge_yolov9_fallback_used") is False
        and summary.get("edge_yolov9_no_fallback_verified") is True
    )


def _post_unlock_evidence_ok(path: Path) -> bool:
    summary = _read_json(path / "summary.json")
    return (
        summary.get("post_unlock_verified") is True
        and summary.get("source_adapter_verified") is True
        and summary.get("edge_yolov9_fallback_used") is False
        and summary.get("edge_yolov9_no_fallback_verified") is True
    )


def _rows_refresh_evidence_ok(path: Path) -> bool:
    summary = _read_json(path / "summary.json")
    return (
        summary.get("phase12c_yolov9_rows_available") is True
        or (
            summary.get("yolov9_source_adapter_verified") is True
            and summary.get("backend_unavailable_count") == 0
        )
    )


def _yolov9_env_status(args: argparse.Namespace) -> dict[str, Any]:
    root_value = os.environ.get("YOLOV9_ROOT")
    weights_value = os.environ.get("YOLOV9_WEIGHTS")
    root = Path(root_value) if root_value else DEFAULT_YOLOV9_ROOT
    weights = Path(weights_value) if weights_value else DEFAULT_YOLOV9_WEIGHTS
    return {
        "YOLOV9_ROOT_configured": bool(root_value),
        "YOLOV9_WEIGHTS_configured": bool(weights_value),
        "yolov9_source_root": str(root),
        "yolov9_weights": str(weights),
        "yolov9_source_root_ready": root.exists() and root.is_dir(),
        "yolov9_weights_ready": weights.exists() and weights.is_file(),
        "effective_yolov9_source_root": str(root),
        "effective_yolov9_weights": str(weights),
    }


def _edge_probe(args: argparse.Namespace, raw_dir: Path, env: dict[str, str]) -> tuple[CommandResult, dict[str, str]]:
    timeout_sec = float(getattr(args, "edge_probe_timeout_sec", 240.0))
    result = _run_command(
        name="edge_yolov9_no_fallback_probe",
        command=[args.python_executable, "-m", "workers.core.edge_perception", "--test", "yolov9"],
        raw_dir=raw_dir,
        env=env,
        timeout_sec=timeout_sec,
    )
    stdout = Path(result.stdout_path).read_text(encoding="utf-8", errors="replace")
    stderr = Path(result.stderr_path).read_text(encoding="utf-8", errors="replace")
    return result, _parse_key_values(stdout + "\n" + stderr)


def _build_child_command(args: argparse.Namespace, child_output_root: Path) -> list[str]:
    route = ROUTES[args.route_id]
    return [
        args.python_executable,
        str(REPO_ROOT / "scripts" / "run_phase12b_controller_ablation_experiment.py"),
        "--execute-runtime",
        "--route-id",
        args.route_id,
        "--controller-mode",
        "grp_follower",
        "--runtime-row-limit",
        "1",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--town",
        args.town,
        "--perception-backend",
        "yolov9",
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


def _dry_run_child_command(args: argparse.Namespace, child_output_root: Path) -> list[str]:
    command = _build_child_command(args, child_output_root)
    command[1:3] = [str(REPO_ROOT / "scripts" / "run_phase12b_controller_ablation_experiment.py"), "--dry-run"]
    return command


def _run_runtime_child(
    args: argparse.Namespace,
    *,
    raw_dir: Path,
    env: dict[str, str],
    child_command: list[str],
) -> tuple[CommandResult, str | None]:
    result = _run_command(
        name="phase12b_yolov9_selected_runtime",
        command=child_command,
        raw_dir=raw_dir,
        env=env,
        timeout_sec=args.parent_timeout_sec,
    )
    stdout = Path(result.stdout_path).read_text(encoding="utf-8", errors="replace")
    stderr = Path(result.stderr_path).read_text(encoding="utf-8", errors="replace")
    return result, _parse_experiment_dir(stdout + "\n" + stderr)


def _load_child_row(child_experiment_dir: str | None) -> tuple[dict[str, Any], dict[str, Any], str]:
    if not child_experiment_dir:
        return {}, {}, "not_run"
    child_summary = _read_json(Path(child_experiment_dir) / "summary.json")
    if child_summary.get("json_read_error"):
        return child_summary, {}, "missing"
    rows = child_summary.get("results")
    if not isinstance(rows, list) or not rows:
        return child_summary, {}, "missing"
    row = rows[0] if isinstance(rows[0], dict) else {}
    return child_summary, row, "loaded" if row else "missing"


def _num_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    number = _num_or_none(value)
    return int(number) if number is not None else None


def _build_summary(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    child_command: list[str],
    preflight: dict[str, Any],
    edge_values: dict[str, str],
    child_result: CommandResult | None,
    child_experiment_dir: str | None,
    blocked_reason: str | None,
) -> dict[str, Any]:
    child_summary, child_row, metrics_read_status = _load_child_row(child_experiment_dir)
    edge_fallback = edge_values.get("edge_yolov9_fallback_used", "").lower() == "true"
    edge_no_fallback = edge_values.get("edge_yolov9_no_fallback_verified", "").lower() == "true"
    edge_passed = edge_values.get("edge_yolov9_command_passed", "").lower() == "true"
    source_adapter_verified = preflight.get("yolov9_source_adapter_verified") is True
    post_unlock_verified = preflight.get("post_unlock_verified") is True
    child_exit_code = child_result.exit_code if child_result else None
    goal_reached = child_row.get("fixed_route_goal_reached") if child_row else None
    yolo_runtime_row_verified = (
        (not args.dry_run)
        and blocked_reason is None
        and child_exit_code == 0
        and metrics_read_status == "loaded"
        and edge_passed
        and not edge_fallback
        and edge_no_fallback
        and child_summary.get("all_runtime_rows_passed") is True
        and child_row.get("result") in {"passed", "passed_without_structured_metrics"}
        and child_row.get("fixed_route_goal_reached") is True
    )
    status = STATUS_DRY_RUN if args.dry_run else STATUS_PASS if yolo_runtime_row_verified else STATUS_BLOCKED
    row_count = 1
    executed_row_count = int(bool(child_result and not args.dry_run))
    passed_count = 1 if yolo_runtime_row_verified else 0
    blocked_count = 0 if args.dry_run or yolo_runtime_row_verified else 1
    failed_count = 0
    return {
        "phase": PHASE,
        "status": status,
        "blocked_reason": blocked_reason,
        "dry_run": args.dry_run,
        "run_dir": str(run_dir),
        "route_id": args.route_id,
        "controller_mode": "grp_follower",
        "perception_backend": "yolov9",
        "runtime_scope": "selected_single_route",
        "target_python": args.python_executable,
        "carla_root": str(args.carla_root),
        "carla_server_host": args.host,
        "carla_server_port": args.port,
        "carla_server_reachable": preflight.get("carla_server_reachable"),
        "source_adapter_verified": source_adapter_verified,
        "post_unlock_verified": post_unlock_verified,
        "yolov9_source_adapter_verified": source_adapter_verified,
        "edge_yolov9_command_passed": edge_passed,
        "edge_yolov9_fallback_used": edge_fallback,
        "edge_yolov9_no_fallback_verified": edge_no_fallback,
        "source_adapter_verified_evidence_dir": _display_path(args.source_adapter_verified_evidence_dir),
        "post_unlock_external_source_verified_dir": _display_path(args.post_unlock_external_source_verified_dir),
        "yolov9_rows_refresh_dir": _display_path(args.yolov9_rows_refresh_dir),
        "phase12c_yolov9_rows_available": preflight.get("phase12c_yolov9_rows_available") is True,
        "backend_unavailable_count": 0 if preflight.get("phase12c_yolov9_rows_available") is True else None,
        "runtime_confirmation_executed": executed_row_count == 1,
        "carla_route_runtime_executed": executed_row_count == 1,
        "row_count": row_count,
        "executed_row_count": executed_row_count,
        "passed_count": passed_count,
        "blocked_count": blocked_count,
        "failed_count": failed_count,
        "goal_reached": goal_reached,
        "distance_to_goal_m": _num_or_none(child_row.get("distance_to_goal_m")),
        "route_progress_pct": _num_or_none(child_row.get("route_progress_pct")),
        "grp_route_progress_pct": _num_or_none(child_row.get("grp_route_progress_pct")),
        "collision_count": _int_or_none(child_row.get("collision_count")),
        "lane_invasion_count": _int_or_none(child_row.get("lane_invasion_count")),
        "avg_speed_kmh": _num_or_none(child_row.get("avg_speed_kmh")),
        "max_speed_kmh": _num_or_none(child_row.get("max_speed_kmh")),
        "child_exit_code": child_exit_code,
        "child_experiment_dir": child_experiment_dir,
        "metrics_read_status": metrics_read_status,
        "yolo_runtime_row_verified": yolo_runtime_row_verified,
        "child_command": _command_text(child_command),
        "child_summary_status": child_summary.get("status"),
        "child_row_result": child_row.get("result"),
        "preflight": preflight,
        "edge_probe_values": edge_values,
        "assertions": {
            "selected_route_only": args.route_id == "route_01",
            "controller_is_grp_follower": True,
            "perception_backend_is_yolov9": True,
            "source_adapter_verified": preflight.get("yolov9_source_adapter_verified") is True,
            "edge_yolov9_no_fallback_verified": edge_no_fallback,
            "carla_server_reachable": preflight.get("carla_server_reachable") is True,
            "child_metrics_loaded": metrics_read_status == "loaded",
            "child_exit_zero": child_exit_code == 0,
            "goal_reached": goal_reached is True,
            "all_boundary_fields_false": True,
        },
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        **BOUNDARY_FIELDS,
        "benchmark_boundaries": dict(BOUNDARY_FIELDS),
    }


def _write_manifest(path: Path, summary: dict[str, Any]) -> None:
    _write_json(
        path,
        {
            "phase": PHASE,
            "status": summary["status"],
            "created_at_utc": _utc_now().isoformat(),
            "run_dir": summary["run_dir"],
            "output_files": [
                "manifest.json",
                "summary.json",
                "summary.csv",
                "commands.txt",
                "environment.json",
                "README.md",
                "raw_outputs/",
            ],
            "child_experiment_dir": summary.get("child_experiment_dir"),
            "raw_runtime_evidence_committed": False,
            "benchmark_boundary_prepared": True,
            "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
            **BOUNDARY_FIELDS,
        },
    )


def _write_environment(path: Path, args: argparse.Namespace, preflight: dict[str, Any]) -> None:
    _write_json(
        path,
        {
            "python": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "target_python": args.python_executable,
            "target_python_exists": Path(args.python_executable).exists(),
            "base_python": args.base_python,
            "carla_root": str(args.carla_root),
            "carla_root_exists": args.carla_root.exists(),
            "carla_server_host": args.host,
            "carla_server_port": args.port,
            "YOLOV9_ROOT_configured": preflight.get("YOLOV9_ROOT_configured"),
            "YOLOV9_WEIGHTS_configured": preflight.get("YOLOV9_WEIGHTS_configured"),
            "yolov9_source_root_ready": preflight.get("yolov9_source_root_ready"),
            "yolov9_weights_ready": preflight.get("yolov9_weights_ready"),
        },
    )


def _write_commands(path: Path, args: argparse.Namespace, child_command: list[str]) -> None:
    lines = [
        "# Phase 12C-YOLOv9-R1 parent command",
        _command_text([sys.executable, *sys.argv]),
        "",
        "# Required operator environment",
        '$env:CARLA_ROOT = "D:\\CARLA\\packages\\CARLA_0.9.16"',
        '$env:YOLOV9_ROOT = "D:\\AIModels\\yolov9"',
        '$env:YOLOV9_WEIGHTS = "D:\\AIModels\\yolov9\\yolov9-c-converted.pt"',
        "",
        "# Delegated Phase 12B selected runtime command",
        _command_text(child_command),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_readme(path: Path, summary: dict[str, Any]) -> None:
    body = f"""# Phase 12C-YOLOv9-R1 Selected Runtime Confirmation

Status:

```text
{summary["status"]}
```

```text
route_id={summary["route_id"]}
controller_mode={summary["controller_mode"]}
perception_backend={summary["perception_backend"]}
runtime_scope={summary["runtime_scope"]}
source_adapter_verified={str(summary["yolov9_source_adapter_verified"]).lower()}
edge_yolov9_fallback_used={str(summary["edge_yolov9_fallback_used"]).lower()}
edge_yolov9_no_fallback_verified={str(summary["edge_yolov9_no_fallback_verified"]).lower()}
runtime_confirmation_executed={str(summary["runtime_confirmation_executed"]).lower()}
carla_route_runtime_executed={str(summary["carla_route_runtime_executed"]).lower()}
yolo_runtime_row_verified={str(summary["yolo_runtime_row_verified"]).lower()}
```

Boundary:

```text
full_phase12c_perception_ablation_runtime_pass=false
rt_detr_runtime_verified=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```
"""
    path.write_text(body, encoding="utf-8")


def _preflight(args: argparse.Namespace, raw_dir: Path, env: dict[str, str]) -> tuple[dict[str, Any], dict[str, str], str | None]:
    env_status = _yolov9_env_status(args)
    evidence_ok = True
    if args.require_yolov9_ready and not args.skip_source_adapter_evidence_check:
        evidence_ok = (
            _source_adapter_evidence_ok(args.source_adapter_verified_evidence_dir)
            and _post_unlock_evidence_ok(args.post_unlock_external_source_verified_dir)
            and _rows_refresh_evidence_ok(args.yolov9_rows_refresh_dir)
        )
    edge_result, edge_values = _edge_probe(args, raw_dir, env) if not args.dry_run else (
        CommandResult(
            name="edge_yolov9_no_fallback_probe",
            command=[],
            exit_code=0,
            duration_sec=0,
            stdout_path="",
            stderr_path="",
            stdout_tail="",
            stderr_tail="",
        ),
        {
            "edge_yolov9_command_passed": "true",
            "edge_yolov9_fallback_used": "false",
            "edge_yolov9_no_fallback_verified": "true",
        },
    )
    edge_ok = (
        edge_result.ok
        and edge_values.get("edge_yolov9_command_passed", "").lower() == "true"
        and edge_values.get("edge_yolov9_fallback_used", "").lower() == "false"
        and edge_values.get("edge_yolov9_no_fallback_verified", "").lower() == "true"
    )
    server_reachable = True if args.dry_run else _tcp_reachable(args.host, args.port)
    preflight = {
        **env_status,
        "source_adapter_evidence_verified": evidence_ok,
        "post_unlock_verified": _post_unlock_evidence_ok(args.post_unlock_external_source_verified_dir),
        "yolov9_source_adapter_verified": evidence_ok and edge_ok,
        "edge_probe_exit_code": edge_result.exit_code,
        "edge_yolov9_command_passed": edge_values.get("edge_yolov9_command_passed", "").lower() == "true",
        "edge_yolov9_fallback_used": edge_values.get("edge_yolov9_fallback_used", "").lower() == "true",
        "edge_yolov9_no_fallback_verified": edge_values.get("edge_yolov9_no_fallback_verified", "").lower() == "true",
        "phase12c_yolov9_rows_available": _rows_refresh_evidence_ok(args.yolov9_rows_refresh_dir),
        "carla_server_reachable": server_reachable,
        "target_python_exists": Path(args.python_executable).exists(),
        "carla_root_exists": args.carla_root.exists(),
    }
    blocked_reasons: list[str] = []
    if args.require_yolov9_ready and not evidence_ok:
        blocked_reasons.append("source adapter verified evidence unavailable")
    if args.require_yolov9_ready and not edge_ok:
        blocked_reasons.append("edge yolov9 no-fallback probe failed")
    if not preflight["target_python_exists"]:
        blocked_reasons.append("target python missing")
    if not preflight["carla_root_exists"]:
        blocked_reasons.append("carla root missing")
    if not env_status["YOLOV9_ROOT_configured"]:
        blocked_reasons.append("YOLOV9_ROOT is not set")
    if not env_status["YOLOV9_WEIGHTS_configured"]:
        blocked_reasons.append("YOLOV9_WEIGHTS is not set")
    if not env_status["yolov9_source_root_ready"]:
        blocked_reasons.append("YOLOv9 source root missing")
    if not env_status["yolov9_weights_ready"]:
        blocked_reasons.append("YOLOv9 weights missing")
    if not server_reachable:
        blocked_reasons.append("CARLA server is not reachable")
    return preflight, edge_values, "; ".join(blocked_reasons) if blocked_reasons else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Confirm selected Phase 12C YOLOv9 runtime row")
    parser.add_argument("--route-id", default="route_01", choices=sorted(ROUTES))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--python-executable", default=DEFAULT_CARLA_PYTHON)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--child-timeout-sec", type=float, default=2400.0)
    parser.add_argument("--parent-timeout-sec", type=float, default=7200.0)
    parser.add_argument("--require-yolov9-ready", action="store_true")
    parser.add_argument("--skip-source-adapter-evidence-check", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--source-adapter-verified-evidence-dir", type=Path, default=DEFAULT_SOURCE_ADAPTER_EVIDENCE_DIR)
    parser.add_argument("--post-unlock-external-source-verified-dir", type=Path, default=DEFAULT_POST_UNLOCK_EVIDENCE_DIR)
    parser.add_argument("--yolov9-rows-refresh-dir", type=Path, default=DEFAULT_ROWS_REFRESH_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.output_dir = _resolve_repo_path(args.output_dir)
    args.carla_root = _resolve_repo_path(args.carla_root)
    args.source_adapter_verified_evidence_dir = _resolve_repo_path(args.source_adapter_verified_evidence_dir)
    args.post_unlock_external_source_verified_dir = _resolve_repo_path(args.post_unlock_external_source_verified_dir)
    args.yolov9_rows_refresh_dir = _resolve_repo_path(args.yolov9_rows_refresh_dir)

    run_dir = _next_run_dir(args.output_dir, args.timestamp)
    raw_dir = run_dir / "raw_outputs"
    child_output_root = run_dir / "runs"
    child_output_root.mkdir(parents=True, exist_ok=True)
    env = _env_with_runtime_paths(args)

    child_command = _dry_run_child_command(args, child_output_root) if args.dry_run else _build_child_command(args, child_output_root)
    preflight, edge_values, blocked_reason = _preflight(args, raw_dir, env)
    if args.dry_run:
        blocked_reason = None

    child_result: CommandResult | None = None
    child_experiment_dir: str | None = None
    if not args.dry_run and blocked_reason is None:
        child_result, child_experiment_dir = _run_runtime_child(
            args,
            raw_dir=raw_dir,
            env=env,
            child_command=child_command,
        )

    summary = _build_summary(
        args=args,
        run_dir=run_dir,
        child_command=child_command,
        preflight=preflight,
        edge_values=edge_values,
        child_result=child_result,
        child_experiment_dir=child_experiment_dir,
        blocked_reason=blocked_reason,
    )

    _write_json(run_dir / "summary.json", summary)
    _write_csv(run_dir / "summary.csv", summary)
    _write_manifest(run_dir / "manifest.json", summary)
    _write_environment(run_dir / "environment.json", args, preflight)
    _write_commands(run_dir / "commands.txt", args, child_command)
    _write_readme(run_dir / "README.md", summary)

    print(f"experiment_dir={run_dir}")
    if args.dry_run:
        print(STATUS_DRY_RUN)
        return 0
    if summary["yolo_runtime_row_verified"]:
        print(STATUS_PASS)
        return 0
    print(STATUS_BLOCKED)
    if summary.get("blocked_reason"):
        print(f"blocked_reason={summary['blocked_reason']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

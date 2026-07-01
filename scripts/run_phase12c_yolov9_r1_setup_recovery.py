"""
Phase 12C-YOLOv9-R1-SETUP parent setup recovery probe.

The parent wrapper intentionally does not import CARLA. It verifies YOLOv9
source-adapter no-fallback readiness, checks CARLA TCP reachability, delegates
map-load/spawn/RGB/GRP setup probing to the CARLA Python child process, and
writes a source-reviewable evidence pack.
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
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import run_phase12c_yolov9_runtime_confirmation as r1

DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "phase12"
DEFAULT_CARLA_ROOT = Path(r"D:\CARLA\packages\CARLA_0.9.16")
DEFAULT_CARLA_PYTHON = r"D:\CARLA\envs\ma-vlna-carla312\python.exe"
DEFAULT_SOURCE_ADAPTER_EVIDENCE_DIR = Path(r"experiments\phase12\20260630T060621Z")
DEFAULT_POST_UNLOCK_EVIDENCE_DIR = Path(r"experiments\phase12\20260630T061015Z")
DEFAULT_ROWS_REFRESH_DIR = Path(r"experiments\phase12\20260630T060823Z")
DIAGNOSTIC_EVIDENCE_DIR = Path(r"experiments\phase12\20260630T150500Z")
PREVIOUS_RUNTIME_EVIDENCE_DIR = Path(r"experiments\phase12\20260630T134322Z")

PHASE = "Phase 12C-YOLOv9-R1-SETUP"
STATUS_PREPARED = (
    "Phase 12C-YOLOv9-R1-SETUP Prepared - CARLA setup/spawn-stage recovery "
    "probe and bounded setup diagnostics are implemented."
)
STATUS_PASS = (
    "Phase 12C-YOLOv9-R1-SETUP Probe Pass - selected route setup reached map "
    "ready, ego spawn, RGB sensor attach, first RGB frame, GRP route generation, "
    "and warm-up ticks."
)
STATUS_BLOCKED = (
    "Phase 12C-YOLOv9-R1-SETUP Blocked - selected route setup still failed "
    "before closed-loop route ticks."
)

BOUNDARY_FIELDS = {
    "runtime_confirmation_executed": False,
    "carla_route_runtime_executed": False,
    "yolo_runtime_row_verified": False,
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
    "diagnostic_evidence_dir",
    "previous_runtime_evidence_dir",
    "route_id",
    "controller_mode",
    "perception_backend",
    "target_town",
    "target_map_name",
    "start_spawn_index",
    "end_spawn_index",
    "source_adapter_verified",
    "edge_yolov9_fallback_used",
    "edge_yolov9_no_fallback_verified",
    "carla_server_reachable",
    "map_load_mode",
    "current_map_name",
    "client_connect_ok",
    "world_ready",
    "town_ready",
    "spawn_point_count",
    "ego_spawned",
    "rgb_sensor_attached",
    "first_rgb_frame_received",
    "grp_route_generated",
    "warmup_ticks_completed",
    "setup_probe_passed",
    "setup_blocker_classification",
    "setup_stage_failed",
    "setup_probe_duration_sec",
    "runtime_confirmation_executed",
    "carla_route_runtime_executed",
    "yolo_runtime_row_verified",
    "full_phase12c_perception_ablation_runtime_pass",
    "rt_detr_runtime_verified",
    "route_benchmark_verified",
    "infraction_benchmark_verified",
    "leaderboard_evaluated",
    "leaderboard_routes_exported",
    "leaderboard_route_criteria_evaluated",
)


def _resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _display_path(path: Path | str | None) -> str | None:
    if path is None:
        return None
    path_obj = Path(path)
    try:
        return str(path_obj.relative_to(REPO_ROOT))
    except ValueError:
        return str(path_obj)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"json_read_error": f"file not found: {path}"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"json_read_error": str(exc)}


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _write_csv(path: Path, summary: dict[str, Any]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerow({column: summary.get(column) for column in SUMMARY_COLUMNS})


def _command_text(command: list[str]) -> str:
    return subprocess.list2cmdline([str(part) for part in command])


def _tail(text: str, max_lines: int = 16) -> str:
    return "\n".join((text or "").splitlines()[-max_lines:])


def _env_with_runtime_paths(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    env["CARLA_ROOT"] = str(args.carla_root)
    env["PYTHONIOENCODING"] = "utf-8"
    carla_python_api = args.carla_root / "PythonAPI" / "carla"
    if carla_python_api.exists():
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(carla_python_api) + (os.pathsep + existing if existing else "")
    return env


def _preflight(args: argparse.Namespace, raw_dir: Path, env: dict[str, str]) -> tuple[dict[str, Any], dict[str, str], str | None]:
    return r1._preflight(args, raw_dir, env)


def _build_child_command(args: argparse.Namespace, child_output_root: Path) -> list[str]:
    command = [
        args.python_executable,
        str(REPO_ROOT / "scripts" / "run_phase12c_carla_setup_spawn_probe.py"),
        "--route-id",
        args.route_id,
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
        "--map-load-mode",
        args.map_load_mode,
        "--cleanup-role-name",
        args.cleanup_role_name,
        "--setup-timeout-sec",
        str(args.setup_timeout_sec),
        "--map-load-timeout-sec",
        str(args.map_load_timeout_sec),
        "--spawn-timeout-sec",
        str(args.spawn_timeout_sec),
        "--sensor-timeout-sec",
        str(args.sensor_timeout_sec),
        "--warmup-ticks",
        str(args.warmup_ticks),
        "--warmup-timeout-sec",
        str(args.warmup_timeout_sec),
        "--fixed-delta-seconds",
        str(args.fixed_delta_seconds),
        "--carla-root",
        str(args.carla_root),
        "--output-dir",
        str(child_output_root),
    ]
    if args.cleanup_existing_actors:
        command.append("--cleanup-existing-actors")
    if args.sync_mode:
        command.append("--sync-mode")
    return command


def _dry_run_child_command(args: argparse.Namespace, child_output_root: Path) -> list[str]:
    return _build_child_command(args, child_output_root)


def _run_child(
    *,
    args: argparse.Namespace,
    raw_dir: Path,
    env: dict[str, str],
    child_command: list[str],
) -> tuple[r1.CommandResult, str | None]:
    result = r1._run_command(
        name="phase12c_yolov9_r1_setup_recovery_child",
        command=child_command,
        raw_dir=raw_dir,
        env=env,
        timeout_sec=args.setup_timeout_sec + 120.0,
    )
    stdout = Path(result.stdout_path).read_text(encoding="utf-8", errors="replace")
    stderr = Path(result.stderr_path).read_text(encoding="utf-8", errors="replace")
    return result, r1._parse_experiment_dir(stdout + "\n" + stderr)


def _load_child_summary(child_experiment_dir: str | None) -> dict[str, Any]:
    if not child_experiment_dir:
        return {}
    return _read_json(Path(child_experiment_dir) / "summary.json")


def _load_child_events(child_experiment_dir: str | None) -> list[dict[str, Any]]:
    if not child_experiment_dir:
        return []
    events_path = Path(child_experiment_dir) / "events.jsonl"
    if not events_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def _summary_from_child(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    child_command: list[str],
    child_result: r1.CommandResult | None,
    child_experiment_dir: str | None,
    child_summary: dict[str, Any],
    preflight: dict[str, Any],
    edge_values: dict[str, str],
    blocked_reason: str | None,
) -> dict[str, Any]:
    edge_fallback = edge_values.get("edge_yolov9_fallback_used", "").lower() == "true"
    edge_no_fallback = edge_values.get("edge_yolov9_no_fallback_verified", "").lower() == "true"
    source_adapter_verified = preflight.get("yolov9_source_adapter_verified") is True
    child_passed = child_summary.get("setup_probe_passed") is True

    if args.dry_run:
        status = STATUS_PREPARED
        classification = None
    elif child_passed:
        status = STATUS_PASS
        classification = child_summary.get("setup_blocker_classification") or "setup_probe_passed"
    else:
        status = STATUS_BLOCKED
        if blocked_reason == "carla_server_unreachable":
            classification = "carla_server_unreachable"
        elif blocked_reason:
            classification = "setup_probe_unknown_blocker"
        else:
            classification = child_summary.get("setup_blocker_classification") or "setup_probe_unknown_blocker"

    return {
        "phase": PHASE,
        "status": status,
        "blocked_reason": blocked_reason,
        "dry_run": args.dry_run,
        "run_dir": str(run_dir),
        "diagnostic_evidence_dir": _display_path(args.diagnostic_evidence_dir),
        "previous_runtime_evidence_dir": _display_path(args.previous_runtime_evidence_dir),
        "route_id": args.route_id,
        "controller_mode": "grp_follower",
        "perception_backend": "yolov9",
        "target_town": args.town,
        "target_map_name": args.town,
        "start_spawn_index": args.start_spawn_index,
        "end_spawn_index": args.end_spawn_index,
        "source_adapter_verified": source_adapter_verified,
        "post_unlock_verified": preflight.get("post_unlock_verified") is True,
        "edge_yolov9_command_passed": edge_values.get("edge_yolov9_command_passed", "").lower() == "true",
        "edge_yolov9_fallback_used": edge_fallback,
        "edge_yolov9_no_fallback_verified": edge_no_fallback,
        "carla_server_reachable": preflight.get("carla_server_reachable"),
        "map_load_mode": args.map_load_mode,
        "current_map_name": child_summary.get("current_map_name"),
        "client_connect_ok": child_summary.get("client_connect_ok", False),
        "world_ready": child_summary.get("world_ready", False),
        "town_ready": child_summary.get("town_ready", False),
        "spawn_point_count": child_summary.get("spawn_point_count"),
        "start_spawn_available": child_summary.get("start_spawn_available", False),
        "end_spawn_available": child_summary.get("end_spawn_available", False),
        "ego_spawned": child_summary.get("ego_spawned", False),
        "ego_actor_id": child_summary.get("ego_actor_id"),
        "rgb_sensor_attached": child_summary.get("rgb_sensor_attached", False),
        "rgb_sensor_actor_id": child_summary.get("rgb_sensor_actor_id"),
        "first_rgb_frame_received": child_summary.get("first_rgb_frame_received", False),
        "first_rgb_frame_width": child_summary.get("first_rgb_frame_width"),
        "first_rgb_frame_height": child_summary.get("first_rgb_frame_height"),
        "first_rgb_frame_latency_sec": child_summary.get("first_rgb_frame_latency_sec"),
        "grp_route_generated": child_summary.get("grp_route_generated", False),
        "grp_route_waypoint_count": child_summary.get("grp_route_waypoint_count"),
        "grp_route_distance_m": child_summary.get("grp_route_distance_m"),
        "warmup_ticks_requested": args.warmup_ticks,
        "warmup_ticks_completed": child_summary.get("warmup_ticks_completed", 0),
        "cleanup_completed": child_summary.get("cleanup_completed", False),
        "setup_probe_passed": child_passed,
        "setup_blocker_classification": classification,
        "setup_stage_failed": child_summary.get("setup_stage_failed"),
        "setup_probe_duration_sec": child_summary.get("setup_probe_duration_sec"),
        "child_exit_code": child_result.exit_code if child_result else None,
        "child_experiment_dir": child_experiment_dir,
        "child_command": _command_text(child_command),
        "child_stdout_tail": child_result.stdout_tail if child_result else None,
        "child_stderr_tail": child_result.stderr_tail if child_result else None,
        "preflight": preflight,
        "edge_probe_values": edge_values,
        "child_summary": child_summary,
        "assertions": {
            "selected_route_only": args.route_id == "route_01",
            "controller_is_grp_follower": True,
            "perception_backend_is_yolov9": True,
            "setup_probe_does_not_claim_runtime_pass": True,
            "source_adapter_verified": source_adapter_verified,
            "edge_yolov9_no_fallback_verified": edge_no_fallback,
            "all_boundary_fields_false": True,
        },
        **BOUNDARY_FIELDS,
        "benchmark_boundaries": dict(BOUNDARY_FIELDS),
    }


def _write_manifest(path: Path, summary: dict[str, Any]) -> None:
    _write_json(
        path,
        {
            "phase": PHASE,
            "status": summary["status"],
            "run_dir": summary["run_dir"],
            "output_files": [
                "manifest.json",
                "summary.json",
                "summary.csv",
                "commands.txt",
                "environment.json",
                "README.md",
                "events.jsonl",
                "raw_outputs/",
            ],
            "child_experiment_dir": summary.get("child_experiment_dir"),
            "raw_runtime_evidence_committed": False,
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
    optional_retry = [
        args.python_executable,
        str(REPO_ROOT / "scripts" / "run_phase12c_yolov9_runtime_timeout_diagnosis.py"),
        "--route-id",
        args.route_id,
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--python-executable",
        args.python_executable,
        "--base-python",
        args.base_python,
        "--carla-root",
        str(args.carla_root),
        "--output-dir",
        str(args.output_dir),
        "--diagnostic-steps",
        "50",
        "--diagnostic-timeout-sec",
        "300",
        "--child-timeout-sec",
        "300",
        "--parent-timeout-sec",
        "900",
        "--require-yolov9-ready",
        "--emit-heartbeat-every",
        "5",
        "--emit-partial-metrics-every",
        "10",
    ]
    lines = [
        "# Phase 12C-YOLOv9-R1-SETUP parent command",
        _command_text([sys.executable, *sys.argv]),
        "",
        "# Required operator environment",
        '$env:CARLA_ROOT = "D:\\CARLA\\packages\\CARLA_0.9.16"',
        '$env:YOLOV9_ROOT = "D:\\AIModels\\yolov9"',
        '$env:YOLOV9_WEIGHTS = "D:\\AIModels\\yolov9\\yolov9-c-converted.pt"',
        "",
        "# CARLA server command",
        r"D:\CARLA\packages\CARLA_0.9.16\CarlaUE4.exe -carla-rpc-port=2000 -RenderOffScreen -nosound",
        "",
        "# Delegated setup child command",
        _command_text(child_command),
        "",
        "# Optional short runtime retry command after setup_probe_passed=true only",
        _command_text(optional_retry),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_readme(path: Path, summary: dict[str, Any]) -> None:
    body = f"""# Phase 12C-YOLOv9-R1-SETUP

Status:

```text
{summary["status"]}
```

```text
diagnostic_evidence_dir={summary["diagnostic_evidence_dir"]}
previous_runtime_evidence_dir={summary["previous_runtime_evidence_dir"]}
route_id={summary["route_id"]}
controller_mode={summary["controller_mode"]}
perception_backend={summary["perception_backend"]}
map_load_mode={summary["map_load_mode"]}
carla_server_reachable={str(summary["carla_server_reachable"]).lower()}
town_ready={str(summary["town_ready"]).lower()}
ego_spawned={str(summary["ego_spawned"]).lower()}
rgb_sensor_attached={str(summary["rgb_sensor_attached"]).lower()}
first_rgb_frame_received={str(summary["first_rgb_frame_received"]).lower()}
grp_route_generated={str(summary["grp_route_generated"]).lower()}
warmup_ticks_completed={summary["warmup_ticks_completed"]}
setup_probe_passed={str(summary["setup_probe_passed"]).lower()}
setup_blocker_classification={summary["setup_blocker_classification"]}
```

Boundary:

```text
runtime_confirmation_executed=false
carla_route_runtime_executed=false
yolo_runtime_row_verified=false
full_phase12c_perception_ablation_runtime_pass=false
rt_detr_runtime_verified=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
```
"""
    path.write_text(body, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare/run Phase 12C-YOLOv9-R1 CARLA setup recovery probe")
    parser.add_argument("--route-id", default="route_01", choices=["route_01"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--start-spawn-index", type=int, default=3)
    parser.add_argument("--end-spawn-index", type=int, default=30)
    parser.add_argument("--python-executable", default=DEFAULT_CARLA_PYTHON)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--map-load-mode", choices=["reuse_or_load", "force_load", "reuse_existing"], default="reuse_or_load")
    parser.add_argument("--cleanup-existing-actors", action="store_true")
    parser.add_argument("--cleanup-role-name", default="hero")
    parser.add_argument("--setup-timeout-sec", type=float, default=300.0)
    parser.add_argument("--map-load-timeout-sec", type=float, default=180.0)
    parser.add_argument("--spawn-timeout-sec", type=float, default=120.0)
    parser.add_argument("--sensor-timeout-sec", type=float, default=120.0)
    parser.add_argument("--warmup-ticks", type=int, default=20)
    parser.add_argument("--warmup-timeout-sec", type=float, default=120.0)
    parser.add_argument("--sync-mode", action="store_true")
    parser.add_argument("--fixed-delta-seconds", type=float, default=0.05)
    parser.add_argument("--require-yolov9-ready", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-source-adapter-evidence-check", action="store_true")
    parser.add_argument("--source-adapter-verified-evidence-dir", type=Path, default=DEFAULT_SOURCE_ADAPTER_EVIDENCE_DIR)
    parser.add_argument("--post-unlock-external-source-verified-dir", type=Path, default=DEFAULT_POST_UNLOCK_EVIDENCE_DIR)
    parser.add_argument("--yolov9-rows-refresh-dir", type=Path, default=DEFAULT_ROWS_REFRESH_DIR)
    parser.add_argument("--diagnostic-evidence-dir", type=Path, default=DIAGNOSTIC_EVIDENCE_DIR)
    parser.add_argument("--previous-runtime-evidence-dir", type=Path, default=PREVIOUS_RUNTIME_EVIDENCE_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.output_dir = _resolve_repo_path(args.output_dir)
    args.carla_root = _resolve_repo_path(args.carla_root)
    args.source_adapter_verified_evidence_dir = _resolve_repo_path(args.source_adapter_verified_evidence_dir)
    args.post_unlock_external_source_verified_dir = _resolve_repo_path(args.post_unlock_external_source_verified_dir)
    args.yolov9_rows_refresh_dir = _resolve_repo_path(args.yolov9_rows_refresh_dir)
    args.diagnostic_evidence_dir = _resolve_repo_path(args.diagnostic_evidence_dir)
    args.previous_runtime_evidence_dir = _resolve_repo_path(args.previous_runtime_evidence_dir)

    run_dir = r1._next_run_dir(args.output_dir, args.timestamp)
    raw_dir = run_dir / "raw_outputs"
    raw_dir.mkdir(exist_ok=True)
    child_output_root = run_dir / "runs"
    child_output_root.mkdir(parents=True, exist_ok=True)
    env = _env_with_runtime_paths(args)
    child_command = _dry_run_child_command(args, child_output_root) if args.dry_run else _build_child_command(args, child_output_root)

    started = time.perf_counter()
    preflight, edge_values, blocked_reason = _preflight(args, raw_dir, env)
    if args.dry_run:
        blocked_reason = None

    child_result: r1.CommandResult | None = None
    child_experiment_dir: str | None = None
    child_summary: dict[str, Any] = {}
    child_events: list[dict[str, Any]] = []

    if not args.dry_run and blocked_reason is None:
        child_result, child_experiment_dir = _run_child(
            args=args,
            raw_dir=raw_dir,
            env=env,
            child_command=child_command,
        )
        child_summary = _load_child_summary(child_experiment_dir)
        child_events = _load_child_events(child_experiment_dir)

    summary = _summary_from_child(
        args=args,
        run_dir=run_dir,
        child_command=child_command,
        child_result=child_result,
        child_experiment_dir=child_experiment_dir,
        child_summary=child_summary,
        preflight=preflight,
        edge_values=edge_values,
        blocked_reason=blocked_reason,
    )
    summary["setup_probe_duration_sec"] = summary.get("setup_probe_duration_sec") or round(time.perf_counter() - started, 3)

    _write_json(run_dir / "summary.json", summary)
    _write_csv(run_dir / "summary.csv", summary)
    _write_manifest(run_dir / "manifest.json", summary)
    _write_environment(run_dir / "environment.json", args, preflight)
    _write_commands(run_dir / "commands.txt", args, child_command)
    _write_readme(run_dir / "README.md", summary)
    _write_jsonl(run_dir / "events.jsonl", child_events)

    print(f"experiment_dir={run_dir}")
    print(summary["status"])
    print(f"setup_blocker_classification={summary['setup_blocker_classification']}")
    if args.dry_run:
        return 0
    return 0 if summary.get("setup_probe_passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())

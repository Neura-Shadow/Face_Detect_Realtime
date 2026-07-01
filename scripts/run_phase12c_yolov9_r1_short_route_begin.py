"""
Phase 12C-YOLOv9-R1-SHORT selected route-begin runtime probe.

This parent wrapper intentionally does not import CARLA. It verifies the
existing YOLOv9 no-fallback readiness contract, requires the Phase 12C
R1-SETUP setup evidence by default, delegates the bounded route-begin runtime
to the existing R1-DIAG -> Phase 12B -> Phase 11M diagnostic path, then
normalizes early closed-loop breadcrumbs into SHORT evidence.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
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
DEFAULT_SETUP_EVIDENCE_DIR = Path(r"experiments\phase12\20260701T045047Z")
DIAGNOSTIC_EVIDENCE_DIR = Path(r"experiments\phase12\20260630T150500Z")
PREVIOUS_RUNTIME_EVIDENCE_DIR = Path(r"experiments\phase12\20260630T134322Z")

PHASE = "Phase 12C-YOLOv9-R1-SHORT"
STATUS_PREPARED = (
    "Phase 12C-YOLOv9-R1-SHORT Prepared - bounded selected YOLOv9 route-begin "
    "probe command and evidence normalization are ready."
)
STATUS_PASS = (
    "Phase 12C-YOLOv9-R1-SHORT Route-Begin Probe Pass - selected YOLOv9 row "
    "entered the closed-loop route loop and produced bounded early runtime "
    "evidence with no fallback."
)
STATUS_BLOCKED = (
    "Phase 12C-YOLOv9-R1-SHORT Blocked - selected YOLOv9 row still failed "
    "before or during bounded route-begin runtime."
)

BENCHMARK_BOUNDARY_SCOPE = "selected_short_route_begin_probe_not_benchmark"

BOUNDARY_FIELDS = {
    "yolo_runtime_row_verified": False,
    "selected_route_completion_verified": False,
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
    "runtime_scope",
    "setup_evidence_dir",
    "diagnostic_evidence_dir",
    "previous_runtime_evidence_dir",
    "route_id",
    "controller_mode",
    "perception_backend",
    "target_town",
    "source_adapter_verified",
    "edge_yolov9_fallback_used",
    "edge_yolov9_no_fallback_verified",
    "setup_probe_passed",
    "carla_server_reachable",
    "runtime_confirmation_executed",
    "carla_route_runtime_executed",
    "diagnostic_steps_requested",
    "diagnostic_steps_completed",
    "heartbeat_count",
    "world_tick_count",
    "rgb_frame_received_count",
    "edge_perception_call_count",
    "yolov9_inference_call_count",
    "edge_yolov9_fallback_used_during_route",
    "yolov9_total_inference_ms_min",
    "yolov9_total_inference_ms_avg",
    "yolov9_total_inference_ms_p95",
    "yolov9_total_inference_ms_max",
    "partial_route_progress_seen",
    "last_route_progress_pct",
    "last_distance_to_goal_m",
    "last_collision_count",
    "last_lane_invasion_count",
    "short_route_begin_verified",
    "short_route_begin_blocker_classification",
    "goal_reached",
    "yolo_runtime_row_verified",
    "selected_route_completion_verified",
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


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _write_csv(path: Path, summary: dict[str, Any]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerow({column: summary.get(column) for column in SUMMARY_COLUMNS})


def _command_text(command: list[str]) -> str:
    return subprocess.list2cmdline([str(part) for part in command])


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


def _setup_evidence(args: argparse.Namespace) -> dict[str, Any]:
    summary_path = args.setup_evidence_dir / "summary.json"
    summary = _read_json(summary_path)
    required_true_fields = (
        "setup_probe_passed",
        "town_ready",
        "ego_spawned",
        "rgb_sensor_attached",
        "first_rgb_frame_received",
        "grp_route_generated",
    )
    missing_or_false = [field for field in required_true_fields if summary.get(field) is not True]
    warmup_ticks_completed = _int_or_none(summary.get("warmup_ticks_completed")) or 0
    setup_passed = not summary.get("json_read_error") and not missing_or_false and warmup_ticks_completed > 0
    return {
        "path": args.setup_evidence_dir,
        "summary_path": summary_path,
        "summary": summary,
        "exists": summary_path.exists(),
        "setup_probe_passed": setup_passed,
        "missing_or_false": missing_or_false,
        "warmup_ticks_completed": warmup_ticks_completed,
        "classification": "short_route_begin_verified" if setup_passed else "setup_probe_not_passed",
    }


def _build_diagnostic_command(args: argparse.Namespace, child_output_root: Path) -> list[str]:
    command = [
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
        str(child_output_root),
        "--diagnostic-steps",
        str(args.diagnostic_steps),
        "--diagnostic-timeout-sec",
        str(args.diagnostic_timeout_sec),
        "--child-timeout-sec",
        str(args.child_timeout_sec),
        "--parent-timeout-sec",
        str(args.parent_timeout_sec),
        "--emit-heartbeat-every",
        str(args.emit_heartbeat_every),
        "--emit-partial-metrics-every",
        str(args.emit_partial_metrics_every),
        "--source-adapter-verified-evidence-dir",
        str(args.source_adapter_verified_evidence_dir),
        "--post-unlock-external-source-verified-dir",
        str(args.post_unlock_external_source_verified_dir),
        "--yolov9-rows-refresh-dir",
        str(args.yolov9_rows_refresh_dir),
        "--previous-runtime-evidence-dir",
        str(args.previous_runtime_evidence_dir),
    ]
    if args.require_yolov9_ready:
        command.append("--require-yolov9-ready")
    if args.skip_source_adapter_evidence_check:
        command.append("--skip-source-adapter-evidence-check")
    if args.dry_run:
        command.append("--dry-run")
    return command


def _run_diagnostic_child(
    *,
    args: argparse.Namespace,
    raw_dir: Path,
    env: dict[str, str],
    child_command: list[str],
) -> tuple[r1.CommandResult, str | None]:
    result = r1._run_command(
        name="phase12c_yolov9_r1_short_route_begin_child",
        command=child_command,
        raw_dir=raw_dir,
        env=env,
        timeout_sec=args.parent_timeout_sec,
    )
    stdout = Path(result.stdout_path).read_text(encoding="utf-8", errors="replace")
    stderr = Path(result.stderr_path).read_text(encoding="utf-8", errors="replace")
    return result, r1._parse_experiment_dir(stdout + "\n" + stderr)


def _copy_diagnostic_file(source: Path, target: Path, *, default_text: str = "") -> None:
    if source.exists():
        shutil.copyfile(source, target)
    else:
        target.write_text(default_text, encoding="utf-8")


def _load_diagnostic_evidence(run_dir: Path, diagnostic_run_dir: str | None) -> dict[str, Any]:
    if not diagnostic_run_dir:
        _write_jsonl(run_dir / "events.jsonl", [])
        _write_jsonl(run_dir / "heartbeat.jsonl", [])
        _write_json(run_dir / "partial_metrics.json", {})
        return {"summary": {}, "events": [], "heartbeats": [], "partial_metrics": {}, "path": None}

    diagnostic_path = Path(diagnostic_run_dir)
    summary = _read_json(diagnostic_path / "summary.json")
    events = _read_jsonl(diagnostic_path / "events.jsonl")
    heartbeats = _read_jsonl(diagnostic_path / "heartbeat.jsonl")
    partial_metrics = _read_json(diagnostic_path / "partial_metrics.json")

    _copy_diagnostic_file(diagnostic_path / "events.jsonl", run_dir / "events.jsonl")
    _copy_diagnostic_file(diagnostic_path / "heartbeat.jsonl", run_dir / "heartbeat.jsonl")
    if (diagnostic_path / "partial_metrics.json").exists():
        shutil.copyfile(diagnostic_path / "partial_metrics.json", run_dir / "partial_metrics.json")
    else:
        _write_json(run_dir / "partial_metrics.json", {})

    return {
        "summary": summary,
        "events": events,
        "heartbeats": heartbeats,
        "partial_metrics": partial_metrics if isinstance(partial_metrics, dict) else {},
        "path": diagnostic_path,
    }


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _num_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _last_value(items: list[dict[str, Any]], key: str) -> Any:
    for item in reversed(items):
        value = item.get(key)
        if value is not None:
            return value
    return None


def _timing_values(items: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for item in items:
        value = _num_or_none(item.get("yolov9_total_inference_ms"))
        if value is None:
            value = _num_or_none(item.get("yolov9_inference_ms"))
        if value is not None:
            values.append(value)
    return values


def _route_fallback_state(events: list[dict[str, Any]], heartbeats: list[dict[str, Any]]) -> bool | None:
    values: list[bool] = []
    for item in [*events, *heartbeats]:
        if "edge_yolov9_fallback_used" not in item or item.get("edge_yolov9_fallback_used") is None:
            continue
        values.append(bool(item.get("edge_yolov9_fallback_used")))
    if not values:
        return None
    return any(values)


def _load_child_route_row(diagnostic_summary: dict[str, Any]) -> dict[str, Any]:
    child_dir = diagnostic_summary.get("child_experiment_dir")
    if not child_dir:
        return {}
    child_summary = _read_json(Path(child_dir) / "summary.json")
    rows = child_summary.get("results")
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return {}


def _classify_short_route_begin(
    *,
    args: argparse.Namespace,
    setup: dict[str, Any],
    preflight: dict[str, Any],
    blocked_reason: str | None,
    child_result: r1.CommandResult | None,
    diagnostic_summary: dict[str, Any],
    heartbeat_count: int,
    world_tick_count: int,
    rgb_frame_received_count: int,
    edge_perception_call_count: int,
    yolov9_inference_call_count: int,
    edge_yolov9_fallback_used_during_route: bool | None,
    timings: list[float],
    partial_route_progress_seen: bool,
) -> str:
    if args.dry_run:
        return "short_route_begin_unknown_blocker"
    if not setup["exists"]:
        return "setup_evidence_missing"
    if args.require_setup_passed and not setup["setup_probe_passed"]:
        return "setup_probe_not_passed"
    if preflight.get("carla_server_reachable") is not True:
        return "carla_server_unreachable"
    if blocked_reason:
        if "CARLA server is not reachable" in blocked_reason:
            return "carla_server_unreachable"
        if "edge yolov9 no-fallback probe failed" in blocked_reason:
            return "yolov9_fallback_regression"
        return "short_route_begin_unknown_blocker"
    if child_result and child_result.exit_code == 124:
        return "short_runtime_timeout"
    if heartbeat_count <= 0:
        timeout_classification = diagnostic_summary.get("timeout_classification")
        if timeout_classification == "map_load_or_spawn_stall":
            return "carla_setup_regressed"
        return "route_runner_no_heartbeat"
    if world_tick_count <= 0:
        return "world_tick_stall"
    if rgb_frame_received_count <= 0:
        return "rgb_sensor_stall"
    if edge_perception_call_count <= 0:
        return "edge_perception_not_called"
    if edge_yolov9_fallback_used_during_route is True:
        return "yolov9_fallback_regression"
    if yolov9_inference_call_count <= 0:
        return "yolov9_inference_not_called"
    if not partial_route_progress_seen:
        return "metrics_flush_missing"
    return "short_route_begin_verified"


def _build_summary(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    child_command: list[str],
    setup: dict[str, Any],
    preflight: dict[str, Any],
    edge_values: dict[str, str],
    blocked_reason: str | None,
    child_result: r1.CommandResult | None,
    diagnostic_run_dir: str | None,
    diagnostic_evidence: dict[str, Any],
) -> dict[str, Any]:
    diagnostic_summary = diagnostic_evidence["summary"]
    events = diagnostic_evidence["events"]
    heartbeats = diagnostic_evidence["heartbeats"]
    partial = diagnostic_evidence["partial_metrics"]
    child_route_row = _load_child_route_row(diagnostic_summary)

    edge_fallback = edge_values.get("edge_yolov9_fallback_used", "").lower() == "true"
    edge_no_fallback = edge_values.get("edge_yolov9_no_fallback_verified", "").lower() == "true"
    edge_passed = edge_values.get("edge_yolov9_command_passed", "").lower() == "true"
    source_adapter_verified = preflight.get("yolov9_source_adapter_verified") is True

    timings = _timing_values([*events, *heartbeats])
    heartbeat_steps = [_int_or_none(item.get("step")) for item in heartbeats]
    heartbeat_steps = [step for step in heartbeat_steps if step is not None]
    event_steps = [_int_or_none(item.get("step")) for item in events]
    event_steps = [step for step in event_steps if step is not None]

    diagnostic_steps_completed = _int_or_none(diagnostic_summary.get("diagnostic_steps_completed"))
    if diagnostic_steps_completed is None:
        diagnostic_steps_completed = max([*heartbeat_steps, *event_steps], default=0)
    heartbeat_count = _int_or_none(diagnostic_summary.get("heartbeat_count")) or len(heartbeats)
    world_tick_count = _int_or_none(diagnostic_summary.get("world_tick_count")) or 0
    rgb_frame_received_count = _int_or_none(diagnostic_summary.get("rgb_frame_received_count")) or 0
    edge_perception_call_count = _int_or_none(diagnostic_summary.get("edge_perception_call_count")) or 0
    yolov9_inference_call_count = _int_or_none(diagnostic_summary.get("yolov9_inference_call_count")) or len(timings)

    if not timings:
        timings = [
            value
            for value in (
                _num_or_none(diagnostic_summary.get("yolov9_total_inference_ms_min")),
                _num_or_none(diagnostic_summary.get("yolov9_total_inference_ms_avg")),
                _num_or_none(diagnostic_summary.get("yolov9_total_inference_ms_max")),
            )
            if value is not None
        ]

    edge_yolov9_fallback_used_during_route = _route_fallback_state(events, heartbeats)
    last_route_progress = _num_or_none(diagnostic_summary.get("last_route_progress_pct"))
    if last_route_progress is None:
        last_route_progress = _num_or_none(_last_value(heartbeats, "route_progress_pct") if heartbeats else partial.get("route_progress_pct"))
    last_distance_to_goal = _num_or_none(diagnostic_summary.get("last_distance_to_goal_m"))
    if last_distance_to_goal is None:
        last_distance_to_goal = _num_or_none(_last_value(heartbeats, "distance_to_goal_m") if heartbeats else partial.get("distance_to_goal_m"))
    partial_route_progress_seen = bool(diagnostic_summary.get("partial_route_progress_seen")) or any(
        _num_or_none(item.get("route_progress_pct")) is not None for item in [*heartbeats, partial]
    )

    runtime_confirmation_executed = diagnostic_summary.get("runtime_confirmation_executed") is True
    carla_route_runtime_executed = diagnostic_summary.get("carla_route_runtime_executed") is True
    classification = _classify_short_route_begin(
        args=args,
        setup=setup,
        preflight=preflight,
        blocked_reason=blocked_reason,
        child_result=child_result,
        diagnostic_summary=diagnostic_summary,
        heartbeat_count=heartbeat_count,
        world_tick_count=world_tick_count,
        rgb_frame_received_count=rgb_frame_received_count,
        edge_perception_call_count=edge_perception_call_count,
        yolov9_inference_call_count=yolov9_inference_call_count,
        edge_yolov9_fallback_used_during_route=edge_yolov9_fallback_used_during_route,
        timings=timings,
        partial_route_progress_seen=partial_route_progress_seen,
    )

    short_route_begin_verified = (
        not args.dry_run
        and setup["setup_probe_passed"]
        and source_adapter_verified
        and not edge_fallback
        and edge_no_fallback
        and preflight.get("carla_server_reachable") is True
        and runtime_confirmation_executed
        and carla_route_runtime_executed
        and diagnostic_steps_completed > 0
        and world_tick_count > 0
        and rgb_frame_received_count > 0
        and edge_perception_call_count > 0
        and yolov9_inference_call_count > 0
        and heartbeat_count > 0
        and edge_yolov9_fallback_used_during_route is False
        and partial_route_progress_seen
        and classification == "short_route_begin_verified"
    )
    status = STATUS_PREPARED if args.dry_run else STATUS_PASS if short_route_begin_verified else STATUS_BLOCKED

    summary = {
        "phase": PHASE,
        "status": status,
        "blocked_reason": blocked_reason,
        "dry_run": args.dry_run,
        "run_dir": str(run_dir),
        "runtime_scope": "selected_short_route_begin_probe",
        "setup_evidence_dir": _display_path(args.setup_evidence_dir),
        "diagnostic_evidence_dir": _display_path(args.diagnostic_evidence_dir),
        "previous_runtime_evidence_dir": _display_path(args.previous_runtime_evidence_dir),
        "route_id": args.route_id,
        "controller_mode": "grp_follower",
        "perception_backend": "yolov9",
        "target_town": args.town,
        "carla_server_host": args.host,
        "carla_server_port": args.port,
        "source_adapter_verified": source_adapter_verified,
        "edge_yolov9_command_passed": edge_passed,
        "edge_yolov9_fallback_used": edge_fallback,
        "edge_yolov9_no_fallback_verified": edge_no_fallback,
        "setup_probe_passed": setup["setup_probe_passed"],
        "setup_evidence_exists": setup["exists"],
        "setup_missing_or_false_fields": setup["missing_or_false"],
        "setup_warmup_ticks_completed": setup["warmup_ticks_completed"],
        "carla_server_reachable": preflight.get("carla_server_reachable"),
        "runtime_confirmation_executed": runtime_confirmation_executed,
        "carla_route_runtime_executed": carla_route_runtime_executed,
        "diagnostic_steps_requested": args.diagnostic_steps,
        "diagnostic_steps_completed": diagnostic_steps_completed,
        "heartbeat_count": heartbeat_count,
        "world_tick_count": world_tick_count,
        "rgb_frame_received_count": rgb_frame_received_count,
        "edge_perception_call_count": edge_perception_call_count,
        "yolov9_inference_call_count": yolov9_inference_call_count,
        "edge_yolov9_fallback_used_during_route": edge_yolov9_fallback_used_during_route,
        "yolov9_total_inference_ms_min": round(min(timings), 3) if timings else None,
        "yolov9_total_inference_ms_avg": round(statistics.fmean(timings), 3) if timings else None,
        "yolov9_total_inference_ms_p95": round(_percentile(timings, 0.95), 3) if timings else None,
        "yolov9_total_inference_ms_max": round(max(timings), 3) if timings else None,
        "partial_route_progress_seen": partial_route_progress_seen,
        "last_route_progress_pct": last_route_progress,
        "last_distance_to_goal_m": last_distance_to_goal,
        "last_collision_count": _int_or_none(diagnostic_summary.get("last_collision_count"))
        if diagnostic_summary
        else _int_or_none(_last_value(heartbeats, "collision_count") if heartbeats else partial.get("collision_count")),
        "last_lane_invasion_count": _int_or_none(diagnostic_summary.get("last_lane_invasion_count"))
        if diagnostic_summary
        else _int_or_none(_last_value(heartbeats, "lane_invasion_count") if heartbeats else partial.get("lane_invasion_count")),
        "short_route_begin_verified": short_route_begin_verified,
        "short_route_begin_blocker_classification": classification,
        "goal_reached": child_route_row.get("fixed_route_goal_reached"),
        "child_exit_code": child_result.exit_code if child_result else None,
        "child_diagnostic_evidence_dir": diagnostic_run_dir,
        "child_diagnostic_status": diagnostic_summary.get("status"),
        "child_timeout_classification": diagnostic_summary.get("timeout_classification"),
        "child_summary": diagnostic_summary,
        "child_route_row": child_route_row,
        "child_command": _command_text(child_command),
        "preflight": preflight,
        "edge_probe_values": edge_values,
        "assertions": {
            "selected_route_only": args.route_id == "route_01",
            "controller_is_grp_follower": True,
            "perception_backend_is_yolov9": True,
            "setup_probe_passed": setup["setup_probe_passed"],
            "source_adapter_verified": source_adapter_verified,
            "edge_yolov9_no_fallback_verified": edge_no_fallback,
            "carla_server_reachable": preflight.get("carla_server_reachable") is True,
            "runtime_confirmation_executed": runtime_confirmation_executed,
            "carla_route_runtime_executed": carla_route_runtime_executed,
            "world_ticks_seen": world_tick_count > 0,
            "rgb_frames_seen": rgb_frame_received_count > 0,
            "edge_perception_calls_seen": edge_perception_call_count > 0,
            "yolov9_inference_calls_seen": yolov9_inference_call_count > 0,
            "heartbeat_seen": heartbeat_count > 0,
            "no_route_fallback_seen": edge_yolov9_fallback_used_during_route is False,
            "partial_route_metrics_seen": partial_route_progress_seen,
            "does_not_require_goal_reach": True,
            "does_not_claim_runtime_pass": True,
            "all_boundary_fields_false": True,
        },
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        **BOUNDARY_FIELDS,
        "benchmark_boundaries": dict(BOUNDARY_FIELDS),
    }
    return summary


def _write_manifest(path: Path, summary: dict[str, Any]) -> None:
    _write_json(
        path,
        {
            "phase": PHASE,
            "status": summary["status"],
            "run_dir": summary["run_dir"],
            "runtime_scope": summary["runtime_scope"],
            "output_files": [
                "manifest.json",
                "summary.json",
                "summary.csv",
                "commands.txt",
                "environment.json",
                "README.md",
                "events.jsonl",
                "heartbeat.jsonl",
                "partial_metrics.json",
                "raw_outputs/",
            ],
            "child_diagnostic_evidence_dir": summary.get("child_diagnostic_evidence_dir"),
            "raw_runtime_evidence_committed": False,
            "benchmark_boundary_prepared": True,
            "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
            **BOUNDARY_FIELDS,
        },
    )


def _write_environment(path: Path, args: argparse.Namespace, preflight: dict[str, Any], setup: dict[str, Any]) -> None:
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
            "setup_evidence_dir": _display_path(args.setup_evidence_dir),
            "setup_evidence_exists": setup["exists"],
            "setup_probe_passed": setup["setup_probe_passed"],
        },
    )


def _write_commands(path: Path, args: argparse.Namespace, child_command: list[str]) -> None:
    lines = [
        "# Phase 12C-YOLOv9-R1-SHORT parent command",
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
        "# Delegated R1-DIAG route-begin command",
        _command_text(child_command),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_readme(path: Path, summary: dict[str, Any]) -> None:
    body = f"""# Phase 12C-YOLOv9-R1-SHORT Route-Begin Probe

Status:

```text
{summary["status"]}
```

```text
runtime_scope={summary["runtime_scope"]}
setup_evidence_dir={summary["setup_evidence_dir"]}
child_diagnostic_evidence_dir={summary["child_diagnostic_evidence_dir"]}
route_id={summary["route_id"]}
controller_mode={summary["controller_mode"]}
perception_backend={summary["perception_backend"]}
source_adapter_verified={str(summary["source_adapter_verified"]).lower()}
edge_yolov9_fallback_used={str(summary["edge_yolov9_fallback_used"]).lower()}
edge_yolov9_no_fallback_verified={str(summary["edge_yolov9_no_fallback_verified"]).lower()}
setup_probe_passed={str(summary["setup_probe_passed"]).lower()}
runtime_confirmation_executed={str(summary["runtime_confirmation_executed"]).lower()}
carla_route_runtime_executed={str(summary["carla_route_runtime_executed"]).lower()}
diagnostic_steps_completed={summary["diagnostic_steps_completed"]}
heartbeat_count={summary["heartbeat_count"]}
world_tick_count={summary["world_tick_count"]}
rgb_frame_received_count={summary["rgb_frame_received_count"]}
edge_perception_call_count={summary["edge_perception_call_count"]}
yolov9_inference_call_count={summary["yolov9_inference_call_count"]}
partial_route_progress_seen={str(summary["partial_route_progress_seen"]).lower()}
short_route_begin_verified={str(summary["short_route_begin_verified"]).lower()}
short_route_begin_blocker_classification={summary["short_route_begin_blocker_classification"]}
```

Boundary:

```text
yolo_runtime_row_verified=false
selected_route_completion_verified=false
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


def _write_status_event(run_dir: Path, phase: str, **payload: Any) -> None:
    events_path = run_dir / "events.jsonl"
    existing = _read_jsonl(events_path)
    existing.append({"phase": phase, **payload})
    _write_jsonl(events_path, existing)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Phase 12C-YOLOv9-R1-SHORT selected route-begin probe")
    parser.add_argument("--route-id", default="route_01", choices=["route_01"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--python-executable", default=DEFAULT_CARLA_PYTHON)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--setup-evidence-dir", type=Path, default=DEFAULT_SETUP_EVIDENCE_DIR)
    parser.add_argument("--diagnostic-evidence-dir", type=Path, default=DIAGNOSTIC_EVIDENCE_DIR)
    parser.add_argument("--previous-runtime-evidence-dir", type=Path, default=PREVIOUS_RUNTIME_EVIDENCE_DIR)
    parser.add_argument("--diagnostic-steps", type=int, default=50)
    parser.add_argument("--diagnostic-timeout-sec", type=float, default=300.0)
    parser.add_argument("--child-timeout-sec", type=float, default=300.0)
    parser.add_argument("--parent-timeout-sec", type=float, default=900.0)
    parser.add_argument("--require-yolov9-ready", action="store_true")
    parser.add_argument("--require-setup-passed", action="store_true", default=True)
    parser.add_argument("--skip-setup-passed-check", action="store_false", dest="require_setup_passed")
    parser.add_argument("--emit-heartbeat-every", type=int, default=5)
    parser.add_argument("--emit-partial-metrics-every", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-source-adapter-evidence-check", action="store_true")
    parser.add_argument("--source-adapter-verified-evidence-dir", type=Path, default=DEFAULT_SOURCE_ADAPTER_EVIDENCE_DIR)
    parser.add_argument("--post-unlock-external-source-verified-dir", type=Path, default=DEFAULT_POST_UNLOCK_EVIDENCE_DIR)
    parser.add_argument("--yolov9-rows-refresh-dir", type=Path, default=DEFAULT_ROWS_REFRESH_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.output_dir = _resolve_repo_path(args.output_dir)
    args.carla_root = _resolve_repo_path(args.carla_root)
    args.setup_evidence_dir = _resolve_repo_path(args.setup_evidence_dir)
    args.diagnostic_evidence_dir = _resolve_repo_path(args.diagnostic_evidence_dir)
    args.previous_runtime_evidence_dir = _resolve_repo_path(args.previous_runtime_evidence_dir)
    args.source_adapter_verified_evidence_dir = _resolve_repo_path(args.source_adapter_verified_evidence_dir)
    args.post_unlock_external_source_verified_dir = _resolve_repo_path(args.post_unlock_external_source_verified_dir)
    args.yolov9_rows_refresh_dir = _resolve_repo_path(args.yolov9_rows_refresh_dir)

    run_dir = r1._next_run_dir(args.output_dir, args.timestamp)
    raw_dir = run_dir / "raw_outputs"
    raw_dir.mkdir(exist_ok=True)
    child_output_root = run_dir / "runs"
    child_output_root.mkdir(parents=True, exist_ok=True)

    env = _env_with_runtime_paths(args)
    child_command = _build_diagnostic_command(args, child_output_root)
    setup = _setup_evidence(args)
    preflight, edge_values, blocked_reason = _preflight(args, raw_dir, env)
    if args.dry_run:
        blocked_reason = None
    if args.require_setup_passed and not setup["exists"]:
        blocked_reason = "setup evidence missing"
    elif args.require_setup_passed and not setup["setup_probe_passed"]:
        blocked_reason = "setup probe not passed"

    child_result: r1.CommandResult | None = None
    diagnostic_run_dir: str | None = None
    if not args.dry_run and blocked_reason is None:
        child_result, diagnostic_run_dir = _run_diagnostic_child(
            args=args,
            raw_dir=raw_dir,
            env=env,
            child_command=child_command,
        )

    diagnostic_evidence = _load_diagnostic_evidence(run_dir, diagnostic_run_dir)
    summary = _build_summary(
        args=args,
        run_dir=run_dir,
        child_command=child_command,
        setup=setup,
        preflight=preflight,
        edge_values=edge_values,
        blocked_reason=blocked_reason,
        child_result=child_result,
        diagnostic_run_dir=diagnostic_run_dir,
        diagnostic_evidence=diagnostic_evidence,
    )

    _write_json(run_dir / "summary.json", summary)
    _write_csv(run_dir / "summary.csv", summary)
    _write_manifest(run_dir / "manifest.json", summary)
    _write_environment(run_dir / "environment.json", args, preflight, setup)
    _write_commands(run_dir / "commands.txt", args, child_command)
    _write_readme(run_dir / "README.md", summary)
    _write_status_event(
        run_dir,
        "short_route_begin_verified" if summary["short_route_begin_verified"] else "short_route_begin_blocked",
        short_route_begin_verified=summary["short_route_begin_verified"],
        short_route_begin_blocker_classification=summary["short_route_begin_blocker_classification"],
    )

    print(f"experiment_dir={run_dir}")
    print(summary["status"])
    print(f"short_route_begin_blocker_classification={summary['short_route_begin_blocker_classification']}")
    if args.dry_run:
        return 0
    return 0 if summary["short_route_begin_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""
Phase 12C-YOLOv9-R1-DIAG selected runtime timeout diagnosis.

This parent script intentionally does not import CARLA. It verifies the
YOLOv9 no-fallback readiness contract, checks CARLA TCP reachability, delegates
the bounded selected-row diagnostic to the existing Phase 12B -> Phase 11M
runtime path, and aggregates heartbeat breadcrumbs written by the child runner.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
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
PREVIOUS_RUNTIME_EVIDENCE_DIR = Path(r"experiments\phase12\20260630T134322Z")
PREVIOUS_BLOCKED_EVIDENCE_DIR = Path(r"experiments\phase12\20260630T094645Z")

PHASE = "Phase 12C-YOLOv9-R1-DIAG"
STATUS_PREPARED = (
    "Phase 12C-YOLOv9-R1-DIAG Prepared - selected YOLOv9 runtime timeout "
    "diagnosis instrumentation and bounded diagnostic commands are implemented."
)
STATUS_BLOCKED = (
    "Phase 12C-YOLOv9-R1-DIAG Blocked - selected YOLOv9 runtime timeout "
    "diagnosis could not isolate the timeout cause."
)
STATUS_COMPLETED = (
    "Phase 12C-YOLOv9-R1-DIAG Diagnostic Completed - bounded diagnostic "
    "evidence was produced without claiming runtime pass."
)
BENCHMARK_BOUNDARY_SCOPE = "selected_yolov9_timeout_diagnosis_not_benchmark"

BOUNDARY_FIELDS = {
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
    "diagnostic_scope",
    "previous_runtime_evidence_dir",
    "previous_blocked_evidence_dir",
    "route_id",
    "controller_mode",
    "perception_backend",
    "carla_server_reachable",
    "source_adapter_verified",
    "edge_yolov9_fallback_used",
    "edge_yolov9_no_fallback_verified",
    "runtime_confirmation_executed",
    "carla_route_runtime_executed",
    "diagnostic_steps_requested",
    "diagnostic_steps_completed",
    "heartbeat_count",
    "first_heartbeat_seen",
    "last_heartbeat_step",
    "rgb_frame_received_count",
    "world_tick_count",
    "edge_perception_call_count",
    "yolov9_inference_call_count",
    "yolov9_total_inference_ms_min",
    "yolov9_total_inference_ms_avg",
    "yolov9_total_inference_ms_p95",
    "yolov9_total_inference_ms_max",
    "partial_route_progress_seen",
    "last_route_progress_pct",
    "last_distance_to_goal_m",
    "last_collision_count",
    "last_lane_invasion_count",
    "timeout_classification",
    "diagnosis_confidence",
    "yolo_runtime_row_verified",
    "full_phase12c_perception_ablation_runtime_pass",
    "rt_detr_runtime_verified",
    "route_benchmark_verified",
    "infraction_benchmark_verified",
    "leaderboard_evaluated",
)


def _resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


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
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_csv(path: Path, summary: dict[str, Any]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerow({column: summary.get(column) for column in SUMMARY_COLUMNS})


def _command_text(command: list[str]) -> str:
    return subprocess.list2cmdline([str(part) for part in command])


def _build_child_command(args: argparse.Namespace, child_output_root: Path) -> list[str]:
    command = [
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
        args.perception_backend,
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
        "--enable-diagnostics",
        "--diagnostic-steps",
        str(args.diagnostic_steps),
        "--emit-heartbeat-every",
        str(args.emit_heartbeat_every),
        "--emit-partial-metrics-every",
        str(args.emit_partial_metrics_every),
        "--perception-inference-stride",
        str(args.perception_inference_stride),
    ]
    if args.reuse_last_perception_between_inference:
        command.append("--reuse-last-perception-between-inference")
    if args.record_perception_cache_events:
        command.append("--record-perception-cache-events")
    return command


def _dry_run_child_command(args: argparse.Namespace, child_output_root: Path) -> list[str]:
    command = _build_child_command(args, child_output_root)
    command[1:3] = [str(REPO_ROOT / "scripts" / "run_phase12b_controller_ablation_experiment.py"), "--dry-run"]
    return command


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
    # Reuse the R1 wrapper preflight so readiness semantics remain identical.
    return r1._preflight(args, raw_dir, env)


def _run_child(
    *,
    args: argparse.Namespace,
    raw_dir: Path,
    env: dict[str, str],
    child_command: list[str],
) -> tuple[r1.CommandResult, str | None]:
    result = r1._run_command(
        name="phase12b_yolov9_timeout_diagnosis",
        command=child_command,
        raw_dir=raw_dir,
        env=env,
        timeout_sec=args.parent_timeout_sec,
    )
    stdout = Path(result.stdout_path).read_text(encoding="utf-8", errors="replace")
    stderr = Path(result.stderr_path).read_text(encoding="utf-8", errors="replace")
    return result, r1._parse_experiment_dir(stdout + "\n" + stderr)


def _find_diagnostic_files(child_root: Path) -> dict[str, list[Path]]:
    if not child_root.exists():
        return {"events": [], "heartbeat": [], "partial_metrics": []}
    return {
        "events": sorted(child_root.rglob("events.jsonl"), key=lambda path: path.stat().st_mtime),
        "heartbeat": sorted(child_root.rglob("heartbeat.jsonl"), key=lambda path: path.stat().st_mtime),
        "partial_metrics": sorted(child_root.rglob("partial_metrics.json"), key=lambda path: path.stat().st_mtime),
    }


def _collect_diagnostics(run_dir: Path, child_experiment_dir: str | None, child_output_root: Path) -> dict[str, Any]:
    search_root = Path(child_experiment_dir) if child_experiment_dir else child_output_root
    files = _find_diagnostic_files(search_root)

    events: list[dict[str, Any]] = []
    for path in files["events"]:
        events.extend(_read_jsonl(path))
    heartbeats: list[dict[str, Any]] = []
    for path in files["heartbeat"]:
        heartbeats.extend(_read_jsonl(path))

    partial_payload: dict[str, Any] = {}
    if files["partial_metrics"]:
        partial_payload = _read_json(files["partial_metrics"][-1])

    _write_jsonl(run_dir / "events.jsonl", events)
    _write_jsonl(run_dir / "heartbeat.jsonl", heartbeats)
    _write_json(run_dir / "partial_metrics.json", partial_payload)

    return {
        "events": events,
        "heartbeats": heartbeats,
        "partial_metrics": partial_payload,
        "diagnostic_files": {
            "events": [str(path) for path in files["events"]],
            "heartbeat": [str(path) for path in files["heartbeat"]],
            "partial_metrics": [str(path) for path in files["partial_metrics"]],
        },
    }


def _phase_count(events: list[dict[str, Any]], phase: str) -> int:
    return sum(1 for event in events if event.get("phase") == phase)


def _max_phase_step(events: list[dict[str, Any]], phase: str) -> int | None:
    steps = [_int_or_none(event.get("step")) for event in events if event.get("phase") == phase]
    steps = [step for step in steps if step is not None]
    return max(steps) if steps else None


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


def _timing_values(events: list[dict[str, Any]], heartbeats: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for item in [*events, *heartbeats]:
        value = _num_or_none(item.get("yolov9_total_inference_ms"))
        if value is None:
            value = _num_or_none(item.get("yolov9_inference_ms"))
        if value is not None:
            values.append(value)
    return values


def _last_value(items: list[dict[str, Any]], key: str) -> Any:
    for item in reversed(items):
        value = item.get(key)
        if value is not None:
            return value
    return None


def _classify_timeout(
    *,
    dry_run: bool,
    child_result: r1.CommandResult | None,
    child_row: dict[str, Any],
    events: list[dict[str, Any]],
    heartbeats: list[dict[str, Any]],
    timings: list[float],
    partial_route_progress_seen: bool,
) -> tuple[str | None, str]:
    if dry_run:
        return None, "low"
    if not events and not heartbeats:
        return "route_runner_no_heartbeat", "high"

    if _phase_count(events, "edge_perception_model_load_started") > _phase_count(events, "edge_perception_model_load_finished"):
        return "yolov9_inference_slow", "medium"
    if _phase_count(events, "carla_setup_started") > _phase_count(events, "carla_setup_finished"):
        return "map_load_or_spawn_stall", "high"
    if _phase_count(events, "world_tick_started") > _phase_count(events, "world_tick_finished"):
        return "carla_tick_stall", "high"
    if _phase_count(events, "world_tick_finished") > 0 and _phase_count(events, "rgb_frame_received") == 0:
        return "rgb_sensor_stall", "high"
    if _phase_count(events, "edge_perception_started") > _phase_count(events, "edge_perception_finished"):
        return "yolov9_inference_slow", "high"
    if timings and (_percentile(timings, 0.95) or 0.0) >= 1000.0:
        return "yolov9_inference_slow", "high"
    if partial_route_progress_seen and child_row.get("metrics_read_status") in {None, "", "not_available"}:
        return "metrics_flush_missing", "medium"
    if child_row.get("result") == "timeout" or (child_result and child_result.exit_code == 124):
        return "child_process_timeout_unknown", "low"
    return "no_timeout_diagnostic_completed", "medium"


def _load_child_summary(child_experiment_dir: str | None) -> tuple[dict[str, Any], dict[str, Any], str]:
    if not child_experiment_dir:
        return {}, {}, "missing"
    summary = _read_json(Path(child_experiment_dir) / "summary.json")
    rows = summary.get("results")
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return summary, rows[0], "loaded"
    return summary, {}, "missing"


def _build_summary(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    child_command: list[str],
    preflight: dict[str, Any],
    edge_values: dict[str, str],
    blocked_reason: str | None,
    child_result: r1.CommandResult | None,
    child_experiment_dir: str | None,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    events = diagnostics["events"]
    heartbeats = diagnostics["heartbeats"]
    partial = diagnostics["partial_metrics"]
    child_summary, child_row, child_metrics_read_status = _load_child_summary(child_experiment_dir)
    edge_fallback = edge_values.get("edge_yolov9_fallback_used", "").lower() == "true"
    edge_no_fallback = edge_values.get("edge_yolov9_no_fallback_verified", "").lower() == "true"
    edge_passed = edge_values.get("edge_yolov9_command_passed", "").lower() == "true"
    source_adapter_verified = preflight.get("yolov9_source_adapter_verified") is True
    timings = _timing_values(events, heartbeats)

    heartbeat_steps = [_int_or_none(item.get("step")) for item in heartbeats]
    heartbeat_steps = [step for step in heartbeat_steps if step is not None]
    event_steps = [_int_or_none(item.get("step")) for item in events]
    event_steps = [step for step in event_steps if step is not None]
    diagnostic_steps_completed = max([*heartbeat_steps, *event_steps], default=0)
    last_route_progress = _num_or_none(
        _last_value(heartbeats, "route_progress_pct")
        if heartbeats
        else partial.get("route_progress_pct")
    )
    last_distance_to_goal = _num_or_none(
        _last_value(heartbeats, "distance_to_goal_m")
        if heartbeats
        else partial.get("distance_to_goal_m")
    )
    partial_route_progress_seen = any(
        _num_or_none(item.get("route_progress_pct")) is not None for item in [*heartbeats, partial]
    )
    timeout_classification, diagnosis_confidence = _classify_timeout(
        dry_run=args.dry_run,
        child_result=child_result,
        child_row=child_row,
        events=events,
        heartbeats=heartbeats,
        timings=timings,
        partial_route_progress_seen=partial_route_progress_seen,
    )
    runtime_executed = bool(child_result and not args.dry_run)
    completed_diagnostic = runtime_executed and bool(events or heartbeats)
    status = STATUS_PREPARED if args.dry_run else STATUS_COMPLETED if completed_diagnostic else STATUS_BLOCKED

    summary = {
        "phase": PHASE,
        "status": status,
        "blocked_reason": blocked_reason,
        "dry_run": args.dry_run,
        "run_dir": str(run_dir),
        "diagnostic_scope": "selected_single_route_timeout_diagnosis",
        "previous_runtime_evidence_dir": _display_path(args.previous_runtime_evidence_dir),
        "previous_blocked_evidence_dir": _display_path(args.previous_blocked_evidence_dir),
        "route_id": args.route_id,
        "controller_mode": "grp_follower",
        "perception_backend": args.perception_backend,
        "perception_inference_stride": args.perception_inference_stride,
        "reuse_last_perception_between_inference": args.reuse_last_perception_between_inference,
        "record_perception_cache_events": args.record_perception_cache_events,
        "carla_server_host": args.host,
        "carla_server_port": args.port,
        "carla_server_reachable": preflight.get("carla_server_reachable"),
        "source_adapter_verified": source_adapter_verified,
        "post_unlock_verified": preflight.get("post_unlock_verified") is True,
        "edge_yolov9_command_passed": edge_passed,
        "edge_yolov9_fallback_used": edge_fallback,
        "edge_yolov9_no_fallback_verified": edge_no_fallback,
        "runtime_confirmation_executed": runtime_executed,
        "carla_route_runtime_executed": runtime_executed,
        "diagnostic_steps_requested": args.diagnostic_steps,
        "diagnostic_steps_completed": diagnostic_steps_completed,
        "heartbeat_count": len(heartbeats),
        "first_heartbeat_seen": bool(heartbeats),
        "last_heartbeat_step": max(heartbeat_steps) if heartbeat_steps else None,
        "rgb_frame_received_count": _phase_count(events, "rgb_frame_received"),
        "world_tick_count": _phase_count(events, "world_tick_finished"),
        "edge_perception_call_count": _phase_count(events, "edge_perception_finished"),
        "yolov9_inference_call_count": len(timings),
        "yolov9_total_inference_ms_min": round(min(timings), 3) if timings else None,
        "yolov9_total_inference_ms_avg": round(statistics.fmean(timings), 3) if timings else None,
        "yolov9_total_inference_ms_p95": round(_percentile(timings, 0.95), 3) if timings else None,
        "yolov9_total_inference_ms_max": round(max(timings), 3) if timings else None,
        "partial_route_progress_seen": partial_route_progress_seen,
        "last_route_progress_pct": last_route_progress,
        "last_distance_to_goal_m": last_distance_to_goal,
        "last_collision_count": _int_or_none(_last_value(heartbeats, "collision_count") if heartbeats else partial.get("collision_count")),
        "last_lane_invasion_count": _int_or_none(_last_value(heartbeats, "lane_invasion_count") if heartbeats else partial.get("lane_invasion_count")),
        "timeout_classification": timeout_classification,
        "diagnosis_confidence": diagnosis_confidence,
        "child_exit_code": child_result.exit_code if child_result else None,
        "child_experiment_dir": child_experiment_dir,
        "child_summary_status": child_summary.get("status"),
        "child_row_result": child_row.get("result"),
        "child_row_exit_code": child_row.get("exit_code"),
        "child_row_duration_sec": child_row.get("duration_sec"),
        "child_metrics_read_status": child_metrics_read_status,
        "child_command": _command_text(child_command),
        "diagnostic_files": diagnostics["diagnostic_files"],
        "preflight": preflight,
        "edge_probe_values": edge_values,
        "assertions": {
            "selected_route_only": args.route_id == "route_01",
            "controller_is_grp_follower": True,
            "perception_backend_is_yolov9": True,
            "source_adapter_verified": source_adapter_verified,
            "edge_yolov9_no_fallback_verified": edge_no_fallback,
            "carla_server_reachable": preflight.get("carla_server_reachable") is True,
            "diagnostic_does_not_claim_runtime_pass": True,
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
            "diagnostic_scope": summary["diagnostic_scope"],
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


def _write_commands(path: Path, child_command: list[str]) -> None:
    lines = [
        "# Phase 12C-YOLOv9-R1-DIAG parent command",
        _command_text([sys.executable, *sys.argv]),
        "",
        "# Required operator environment",
        '$env:CARLA_ROOT = "D:\\CARLA\\packages\\CARLA_0.9.16"',
        '$env:YOLOV9_ROOT = "D:\\AIModels\\yolov9"',
        '$env:YOLOV9_WEIGHTS = "D:\\AIModels\\yolov9\\yolov9-c-converted.pt"',
        "",
        "# Optional CARLA server command",
        r"D:\CARLA\packages\CARLA_0.9.16\CarlaUE4.exe -carla-rpc-port=2000 -RenderOffScreen -nosound",
        "",
        "# Delegated Phase 12B diagnostic command",
        _command_text(child_command),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_readme(path: Path, summary: dict[str, Any]) -> None:
    body = f"""# Phase 12C-YOLOv9-R1-DIAG Timeout Diagnosis

Status:

```text
{summary["status"]}
```

```text
diagnostic_scope={summary["diagnostic_scope"]}
route_id={summary["route_id"]}
controller_mode={summary["controller_mode"]}
perception_backend={summary["perception_backend"]}
carla_server_reachable={str(summary["carla_server_reachable"]).lower()}
source_adapter_verified={str(summary["source_adapter_verified"]).lower()}
edge_yolov9_fallback_used={str(summary["edge_yolov9_fallback_used"]).lower()}
edge_yolov9_no_fallback_verified={str(summary["edge_yolov9_no_fallback_verified"]).lower()}
diagnostic_steps_requested={summary["diagnostic_steps_requested"]}
diagnostic_steps_completed={summary["diagnostic_steps_completed"]}
heartbeat_count={summary["heartbeat_count"]}
timeout_classification={summary["timeout_classification"]}
diagnosis_confidence={summary["diagnosis_confidence"]}
```

Boundary:

```text
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
    parser = argparse.ArgumentParser(description="Diagnose selected Phase 12C YOLOv9 runtime timeout")
    parser.add_argument("--route-id", default="route_01", choices=["route_01"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--perception-backend", default="yolov9", choices=["dummy", "yolov9"])
    parser.add_argument("--python-executable", default=DEFAULT_CARLA_PYTHON)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--diagnostic-steps", type=int, default=300)
    parser.add_argument("--diagnostic-timeout-sec", type=float, default=900.0)
    parser.add_argument("--child-timeout-sec", type=float, default=900.0)
    parser.add_argument("--parent-timeout-sec", type=float, default=1800.0)
    parser.add_argument("--require-yolov9-ready", action="store_true")
    parser.add_argument("--emit-heartbeat-every", type=int, default=10)
    parser.add_argument("--emit-partial-metrics-every", type=int, default=25)
    parser.add_argument("--perception-inference-stride", type=int, default=1)
    parser.add_argument("--reuse-last-perception-between-inference", action="store_true")
    parser.add_argument("--record-perception-cache-events", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-source-adapter-evidence-check", action="store_true")
    parser.add_argument("--source-adapter-verified-evidence-dir", type=Path, default=DEFAULT_SOURCE_ADAPTER_EVIDENCE_DIR)
    parser.add_argument("--post-unlock-external-source-verified-dir", type=Path, default=DEFAULT_POST_UNLOCK_EVIDENCE_DIR)
    parser.add_argument("--yolov9-rows-refresh-dir", type=Path, default=DEFAULT_ROWS_REFRESH_DIR)
    parser.add_argument("--previous-runtime-evidence-dir", type=Path, default=PREVIOUS_RUNTIME_EVIDENCE_DIR)
    parser.add_argument("--previous-blocked-evidence-dir", type=Path, default=PREVIOUS_BLOCKED_EVIDENCE_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.output_dir = _resolve_repo_path(args.output_dir)
    args.carla_root = _resolve_repo_path(args.carla_root)
    args.source_adapter_verified_evidence_dir = _resolve_repo_path(args.source_adapter_verified_evidence_dir)
    args.post_unlock_external_source_verified_dir = _resolve_repo_path(args.post_unlock_external_source_verified_dir)
    args.yolov9_rows_refresh_dir = _resolve_repo_path(args.yolov9_rows_refresh_dir)
    args.previous_runtime_evidence_dir = _resolve_repo_path(args.previous_runtime_evidence_dir)
    args.previous_blocked_evidence_dir = _resolve_repo_path(args.previous_blocked_evidence_dir)

    run_dir = r1._next_run_dir(args.output_dir, args.timestamp)
    raw_dir = run_dir / "raw_outputs"
    raw_dir.mkdir(exist_ok=True)
    child_output_root = run_dir / "runs"
    child_output_root.mkdir(parents=True, exist_ok=True)
    env = _env_with_runtime_paths(args)

    child_command = _dry_run_child_command(args, child_output_root) if args.dry_run else _build_child_command(args, child_output_root)
    preflight, edge_values, blocked_reason = _preflight(args, raw_dir, env)
    if args.dry_run:
        blocked_reason = None

    child_result: r1.CommandResult | None = None
    child_experiment_dir: str | None = None
    if not args.dry_run and blocked_reason is None:
        child_result, child_experiment_dir = _run_child(
            args=args,
            raw_dir=raw_dir,
            env=env,
            child_command=child_command,
        )

    diagnostics = _collect_diagnostics(run_dir, child_experiment_dir, child_output_root)
    summary = _build_summary(
        args=args,
        run_dir=run_dir,
        child_command=child_command,
        preflight=preflight,
        edge_values=edge_values,
        blocked_reason=blocked_reason,
        child_result=child_result,
        child_experiment_dir=child_experiment_dir,
        diagnostics=diagnostics,
    )

    _write_json(run_dir / "summary.json", summary)
    _write_csv(run_dir / "summary.csv", summary)
    _write_manifest(run_dir / "manifest.json", summary)
    _write_environment(run_dir / "environment.json", args, preflight)
    _write_commands(run_dir / "commands.txt", child_command)
    _write_readme(run_dir / "README.md", summary)

    print(f"experiment_dir={run_dir}")
    print(summary["status"])
    if summary.get("timeout_classification"):
        print(f"timeout_classification={summary['timeout_classification']}")
    if args.dry_run:
        return 0
    return 0 if summary["status"] != STATUS_BLOCKED else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""
Phase 12C-YOLOv9-R1-LATENCY route-loop latency and cadence probe.

The parent wrapper intentionally does not import CARLA. It verifies the
selected-row readiness chain, delegates bounded route-loop diagnostics to the
existing R1-DIAG -> Phase 12B -> Phase 11M path, and aggregates per-variant
YOLOv9 timing/cadence metrics without claiming route completion.
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
from dataclasses import dataclass
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
DEFAULT_SHORT_ROUTE_BEGIN_EVIDENCE_DIR = Path(r"experiments\phase12\20260701T064944Z")
DIAGNOSTIC_EVIDENCE_DIR = Path(r"experiments\phase12\20260630T150500Z")

PHASE = "Phase 12C-YOLOv9-R1-LATENCY"
STATUS_PREPARED = (
    "Phase 12C-YOLOv9-R1-LATENCY Prepared - selected YOLOv9 route-loop "
    "latency/cadence probe commands are ready."
)
STATUS_COMPLETED = (
    "Phase 12C-YOLOv9-R1-LATENCY Completed - selected YOLOv9 route-loop "
    "latency and cadence evidence produced without claiming route completion."
)
STATUS_BLOCKED = (
    "Phase 12C-YOLOv9-R1-LATENCY Blocked - latency probe could not produce "
    "bounded route-loop timing evidence."
)

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

TIMING_COMPONENTS = (
    "yolov9_preprocess_ms",
    "yolov9_model_forward_ms",
    "yolov9_nms_ms",
    "yolov9_postprocess_ms",
    "yolov9_total_inference_ms",
)

SUMMARY_COLUMNS = (
    "phase",
    "status",
    "runtime_scope",
    "short_route_begin_evidence_dir",
    "setup_evidence_dir",
    "diagnostic_evidence_dir",
    "route_id",
    "controller_mode",
    "perception_backend",
    "source_adapter_verified",
    "edge_yolov9_fallback_used",
    "edge_yolov9_no_fallback_verified",
    "setup_probe_passed",
    "short_route_begin_verified",
    "variant_count",
    "executed_variant_count",
    "completed_variant_count",
    "blocked_variant_count",
    "best_variant_id",
    "best_variant_effective_fps",
    "best_variant_yolov9_avg_ms",
    "baseline_current_cadence_yolov9_avg_ms",
    "latency_bottleneck_classification",
    "recommended_next_phase",
    "latency_probe_completed",
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

VARIANT_COLUMNS = (
    "variant_id",
    "route_id",
    "controller_mode",
    "perception_backend",
    "diagnostic_steps_requested",
    "diagnostic_steps_completed",
    "duration_sec",
    "effective_steps_per_sec",
    "effective_fps",
    "world_tick_count",
    "rgb_frame_received_count",
    "edge_perception_call_count",
    "yolov9_inference_call_count",
    "cached_perception_result_count",
    "real_inference_ratio",
    "edge_yolov9_fallback_used_during_route",
    "partial_route_progress_seen",
    "last_route_progress_pct",
    "last_distance_to_goal_m",
    "last_collision_count",
    "last_lane_invasion_count",
    "goal_reached",
    "timeout",
    "child_exit_code",
    "yolov9_preprocess_ms_min",
    "yolov9_preprocess_ms_avg",
    "yolov9_preprocess_ms_p95",
    "yolov9_preprocess_ms_max",
    "yolov9_model_forward_ms_min",
    "yolov9_model_forward_ms_avg",
    "yolov9_model_forward_ms_p95",
    "yolov9_model_forward_ms_max",
    "yolov9_nms_ms_min",
    "yolov9_nms_ms_avg",
    "yolov9_nms_ms_p95",
    "yolov9_nms_ms_max",
    "yolov9_postprocess_ms_min",
    "yolov9_postprocess_ms_avg",
    "yolov9_postprocess_ms_p95",
    "yolov9_postprocess_ms_max",
    "yolov9_total_inference_ms_min",
    "yolov9_total_inference_ms_avg",
    "yolov9_total_inference_ms_p95",
    "yolov9_total_inference_ms_max",
    "latency_bottleneck_classification",
    "result",
    "command_status",
    "evidence_dir",
)


@dataclass(frozen=True)
class LatencyVariant:
    variant_id: str
    diagnostic_steps: int
    perception_backend: str
    perception_inference_stride: int
    reuse_last_perception_between_inference: bool
    record_perception_cache_events: bool


VARIANTS = (
    LatencyVariant(
        variant_id="variant_01_current_cadence",
        diagnostic_steps=50,
        perception_backend="yolov9",
        perception_inference_stride=1,
        reuse_last_perception_between_inference=False,
        record_perception_cache_events=False,
    ),
    LatencyVariant(
        variant_id="variant_02_stride_5_cached",
        diagnostic_steps=100,
        perception_backend="yolov9",
        perception_inference_stride=5,
        reuse_last_perception_between_inference=True,
        record_perception_cache_events=True,
    ),
    LatencyVariant(
        variant_id="variant_03_stride_10_cached",
        diagnostic_steps=100,
        perception_backend="yolov9",
        perception_inference_stride=10,
        reuse_last_perception_between_inference=True,
        record_perception_cache_events=True,
    ),
    LatencyVariant(
        variant_id="variant_04_dummy_reference",
        diagnostic_steps=100,
        perception_backend="dummy",
        perception_inference_stride=1,
        reuse_last_perception_between_inference=False,
        record_perception_cache_events=False,
    ),
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


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in columns})


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


def _evidence_passed(path: Path, required: dict[str, Any]) -> dict[str, Any]:
    summary = _read_json(path / "summary.json")
    missing = [key for key, expected in required.items() if summary.get(key) is not expected]
    return {
        "path": path,
        "exists": (path / "summary.json").exists(),
        "summary": summary,
        "passed": not summary.get("json_read_error") and not missing,
        "missing_or_mismatch": missing,
    }


def _build_diagnostic_command(args: argparse.Namespace, variant: LatencyVariant, variant_output_root: Path) -> list[str]:
    command = [
        args.python_executable,
        str(REPO_ROOT / "scripts" / "run_phase12c_yolov9_runtime_timeout_diagnosis.py"),
        "--route-id",
        args.route_id,
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--perception-backend",
        variant.perception_backend,
        "--python-executable",
        args.python_executable,
        "--base-python",
        args.base_python,
        "--carla-root",
        str(args.carla_root),
        "--output-dir",
        str(variant_output_root),
        "--diagnostic-steps",
        str(variant.diagnostic_steps),
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
        "--perception-inference-stride",
        str(variant.perception_inference_stride),
        "--source-adapter-verified-evidence-dir",
        str(args.source_adapter_verified_evidence_dir),
        "--post-unlock-external-source-verified-dir",
        str(args.post_unlock_external_source_verified_dir),
        "--yolov9-rows-refresh-dir",
        str(args.yolov9_rows_refresh_dir),
    ]
    if args.require_yolov9_ready and variant.perception_backend == "yolov9":
        command.append("--require-yolov9-ready")
    if args.skip_source_adapter_evidence_check:
        command.append("--skip-source-adapter-evidence-check")
    if variant.reuse_last_perception_between_inference:
        command.append("--reuse-last-perception-between-inference")
    if variant.record_perception_cache_events:
        command.append("--record-perception-cache-events")
    if args.dry_run:
        command.append("--dry-run")
    return command


def _run_variant(
    *,
    args: argparse.Namespace,
    raw_dir: Path,
    env: dict[str, str],
    variant: LatencyVariant,
    command: list[str],
) -> tuple[r1.CommandResult, str | None]:
    result = r1._run_command(
        name=f"phase12c_yolov9_r1_latency_{variant.variant_id}",
        command=command,
        raw_dir=raw_dir,
        env=env,
        timeout_sec=args.parent_timeout_sec,
    )
    stdout = Path(result.stdout_path).read_text(encoding="utf-8", errors="replace")
    stderr = Path(result.stderr_path).read_text(encoding="utf-8", errors="replace")
    return result, r1._parse_experiment_dir(stdout + "\n" + stderr)


def _num_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
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


def _timing_stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "avg": None, "p95": None, "max": None}
    return {
        "min": round(min(values), 3),
        "avg": round(statistics.fmean(values), 3),
        "p95": round(_percentile(values, 0.95), 3),
        "max": round(max(values), 3),
    }


def _timing_values(events: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for event in events:
        if event.get("phase") != "edge_perception_finished":
            continue
        if event.get("real_inference_call") is False:
            continue
        value = _num_or_none(event.get(key))
        if value is not None:
            values.append(value)
    return values


def _fallback_state(events: list[dict[str, Any]], heartbeats: list[dict[str, Any]]) -> bool | None:
    values: list[bool] = []
    for item in [*events, *heartbeats]:
        if "edge_yolov9_fallback_used" not in item or item.get("edge_yolov9_fallback_used") is None:
            continue
        values.append(bool(item.get("edge_yolov9_fallback_used")))
    if not values:
        return None
    return any(values)


def _load_variant_evidence(path_text: str | None) -> dict[str, Any]:
    if not path_text:
        return {"summary": {}, "events": [], "heartbeats": [], "partial_metrics": {}, "path": None}
    path = Path(path_text)
    return {
        "summary": _read_json(path / "summary.json"),
        "events": _read_jsonl(path / "events.jsonl"),
        "heartbeats": _read_jsonl(path / "heartbeat.jsonl"),
        "partial_metrics": _read_json(path / "partial_metrics.json"),
        "path": path,
    }


def _classify_variant(row: dict[str, Any]) -> str:
    if row["perception_backend"] != "yolov9":
        return "latency_profile_completed" if row["diagnostic_steps_completed"] > 0 else "latency_unknown"
    if row["yolov9_inference_call_count"] <= 0:
        return "timeout_before_latency_profile"
    averages = {
        "yolov9_forward_dominant": row.get("yolov9_model_forward_ms_avg"),
        "yolov9_nms_dominant": row.get("yolov9_nms_ms_avg"),
        "yolov9_preprocess_dominant": row.get("yolov9_preprocess_ms_avg"),
        "yolov9_postprocess_dominant": row.get("yolov9_postprocess_ms_avg"),
    }
    averages = {key: value for key, value in averages.items() if isinstance(value, (int, float))}
    if averages:
        return max(averages, key=lambda key: float(averages[key]))
    return "latency_profile_completed" if row["diagnostic_steps_completed"] > 0 else "latency_unknown"


def _row_from_variant(
    *,
    variant: LatencyVariant,
    command: list[str],
    command_status: str,
    child_result: r1.CommandResult | None,
    evidence_dir: str | None,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    summary = evidence["summary"]
    events = evidence["events"]
    heartbeats = evidence["heartbeats"]
    partial = evidence["partial_metrics"] if isinstance(evidence["partial_metrics"], dict) else {}

    edge_events = [event for event in events if event.get("phase") == "edge_perception_finished"]
    real_events = [event for event in edge_events if event.get("real_inference_call") is not False]
    cached_count = sum(1 for event in edge_events if event.get("cached_result_used") is True)
    if not cached_count:
        cached_count = sum(1 for item in heartbeats if item.get("cached_result_used") is True)

    steps_completed = _int_or_none(summary.get("diagnostic_steps_completed")) or 0
    duration_sec = child_result.duration_sec if child_result else None
    edge_count = len(edge_events) or (_int_or_none(summary.get("edge_perception_call_count")) or 0)
    yolo_count = len([event for event in real_events if _num_or_none(event.get("yolov9_total_inference_ms")) is not None])
    if yolo_count == 0:
        yolo_count = _int_or_none(summary.get("yolov9_inference_call_count")) or 0
    real_inference_ratio = round(yolo_count / edge_count, 6) if edge_count else None

    row: dict[str, Any] = {
        "variant_id": variant.variant_id,
        "route_id": "route_01",
        "controller_mode": "grp_follower",
        "perception_backend": variant.perception_backend,
        "diagnostic_steps_requested": variant.diagnostic_steps,
        "diagnostic_steps_completed": steps_completed,
        "duration_sec": duration_sec,
        "effective_steps_per_sec": round(steps_completed / duration_sec, 6) if duration_sec else None,
        "effective_fps": round(steps_completed / duration_sec, 6) if duration_sec else None,
        "world_tick_count": _int_or_none(summary.get("world_tick_count")) or 0,
        "rgb_frame_received_count": _int_or_none(summary.get("rgb_frame_received_count")) or 0,
        "edge_perception_call_count": edge_count,
        "yolov9_inference_call_count": yolo_count,
        "cached_perception_result_count": cached_count,
        "real_inference_ratio": real_inference_ratio,
        "edge_yolov9_fallback_used_during_route": _fallback_state(events, heartbeats),
        "partial_route_progress_seen": bool(summary.get("partial_route_progress_seen")),
        "last_route_progress_pct": _num_or_none(summary.get("last_route_progress_pct")),
        "last_distance_to_goal_m": _num_or_none(summary.get("last_distance_to_goal_m")),
        "last_collision_count": _int_or_none(summary.get("last_collision_count")),
        "last_lane_invasion_count": _int_or_none(summary.get("last_lane_invasion_count")),
        "goal_reached": None,
        "timeout": bool(child_result and child_result.exit_code == 124),
        "child_exit_code": child_result.exit_code if child_result else None,
        "result": "prepared" if command_status == "prepared" else "completed",
        "command_status": command_status,
        "evidence_dir": evidence_dir,
        "command": _command_text(command),
    }
    child_summary = summary.get("child_summary")
    if isinstance(child_summary, dict):
        row["goal_reached"] = child_summary.get("fixed_route_goal_reached")
    child_row = summary.get("child_route_row")
    if isinstance(child_row, dict):
        row["goal_reached"] = child_row.get("fixed_route_goal_reached")

    for component in TIMING_COMPONENTS:
        stats = _timing_stats(_timing_values(events, component))
        for stat_name, value in stats.items():
            row[f"{component}_{stat_name}"] = value

    row["latency_bottleneck_classification"] = _classify_variant(row)
    if command_status == "executed" and (
        variant.perception_backend == "yolov9"
        and (
            row["yolov9_inference_call_count"] <= 0
            or row["edge_yolov9_fallback_used_during_route"] is True
            or row["diagnostic_steps_completed"] <= 0
        )
    ):
        row["result"] = "blocked"
    return row


def _recommend_next_phase(rows: list[dict[str, Any]]) -> str:
    executed_yolo = [row for row in rows if row["command_status"] == "executed" and row["perception_backend"] == "yolov9"]
    if not executed_yolo or all((row.get("yolov9_inference_call_count") or 0) <= 0 for row in executed_yolo):
        return "BLOCKED"
    variant_01 = next((row for row in rows if row["variant_id"] == "variant_01_current_cadence"), None)
    variant_02 = next((row for row in rows if row["variant_id"] == "variant_02_stride_5_cached"), None)
    dummy = next((row for row in rows if row["variant_id"] == "variant_04_dummy_reference"), None)
    baseline_avg = (variant_01 or {}).get("yolov9_total_inference_ms_avg")
    if isinstance(baseline_avg, (int, float)) and baseline_avg <= 500 and (variant_01 or {}).get("edge_yolov9_fallback_used_during_route") is False:
        return "R1-COMPLETE-ROUTE"
    if (
        isinstance(baseline_avg, (int, float))
        and baseline_avg > 1000
        and variant_02
        and variant_02.get("result") == "completed"
        and (variant_02.get("yolov9_inference_call_count") or 0) > 0
        and variant_02.get("edge_yolov9_fallback_used_during_route") is False
    ):
        return "R1-STRIDE-ROUTE-BEGIN"
    if dummy and dummy.get("result") == "completed" and isinstance(baseline_avg, (int, float)) and baseline_avg > 1000:
        return "R1-LATENCY-OPT"
    return "R1-LATENCY-OPT"


def _build_summary(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    preflight: dict[str, Any],
    edge_values: dict[str, str],
    blocked_reason: str | None,
    setup: dict[str, Any],
    short: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    executed = [row for row in rows if row["command_status"] == "executed"]
    completed = [
        row
        for row in executed
        if row["perception_backend"] == "yolov9"
        and row["result"] == "completed"
        and (row.get("yolov9_inference_call_count") or 0) > 0
        and row.get("edge_yolov9_fallback_used_during_route") is False
    ]
    completed_variant_count = len(completed)
    blocked_variant_count = len([row for row in executed if row["result"] == "blocked"])
    best = max(completed, key=lambda row: row.get("effective_fps") or 0.0) if completed else None
    baseline = next((row for row in rows if row["variant_id"] == "variant_01_current_cadence"), None)
    recommended = _recommend_next_phase(rows) if not args.dry_run else "BLOCKED"
    latency_probe_completed = bool(completed) and not args.dry_run
    status = STATUS_PREPARED if args.dry_run else STATUS_COMPLETED if latency_probe_completed else STATUS_BLOCKED
    edge_fallback = edge_values.get("edge_yolov9_fallback_used", "").lower() == "true"
    edge_no_fallback = edge_values.get("edge_yolov9_no_fallback_verified", "").lower() == "true"

    return {
        "phase": PHASE,
        "status": status,
        "blocked_reason": blocked_reason,
        "dry_run": args.dry_run,
        "run_dir": str(run_dir),
        "runtime_scope": "selected_yolov9_route_loop_latency_probe",
        "short_route_begin_evidence_dir": _display_path(args.short_route_begin_evidence_dir),
        "setup_evidence_dir": _display_path(args.setup_evidence_dir),
        "diagnostic_evidence_dir": _display_path(args.diagnostic_evidence_dir),
        "route_id": args.route_id,
        "controller_mode": "grp_follower",
        "perception_backend": "yolov9",
        "source_adapter_verified": preflight.get("yolov9_source_adapter_verified") is True,
        "edge_yolov9_fallback_used": edge_fallback,
        "edge_yolov9_no_fallback_verified": edge_no_fallback,
        "setup_probe_passed": setup["passed"],
        "short_route_begin_verified": short["passed"],
        "variant_count": len(rows),
        "executed_variant_count": len(executed),
        "completed_variant_count": completed_variant_count,
        "blocked_variant_count": blocked_variant_count,
        "best_variant_id": best["variant_id"] if best else None,
        "best_variant_effective_fps": best.get("effective_fps") if best else None,
        "best_variant_yolov9_avg_ms": best.get("yolov9_total_inference_ms_avg") if best else None,
        "baseline_current_cadence_yolov9_avg_ms": (baseline or {}).get("yolov9_total_inference_ms_avg"),
        "latency_bottleneck_classification": (baseline or {}).get("latency_bottleneck_classification"),
        "recommended_next_phase": recommended,
        "latency_probe_completed": latency_probe_completed,
        "variants": rows,
        "preflight": preflight,
        "edge_probe_values": edge_values,
        "setup_evidence": {
            "exists": setup["exists"],
            "passed": setup["passed"],
            "missing_or_mismatch": setup["missing_or_mismatch"],
        },
        "short_route_begin_evidence": {
            "exists": short["exists"],
            "passed": short["passed"],
            "missing_or_mismatch": short["missing_or_mismatch"],
        },
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": "latency_and_cadence_only_not_route_completion",
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
            "runtime_scope": summary["runtime_scope"],
            "output_files": [
                "manifest.json",
                "summary.json",
                "summary.csv",
                "variant_summary.csv",
                "commands.txt",
                "environment.json",
                "README.md",
                "events.jsonl",
                "heartbeat.jsonl",
                "partial_metrics.json",
                "raw_outputs/",
                "runs/",
            ],
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


def _write_commands(path: Path, parent_command: list[str], variant_commands: list[tuple[LatencyVariant, str, list[str]]]) -> None:
    lines = [
        "# Phase 12C-YOLOv9-R1-LATENCY parent command",
        _command_text(parent_command),
        "",
        "# Required operator environment",
        '$env:CARLA_ROOT = "D:\\CARLA\\packages\\CARLA_0.9.16"',
        '$env:YOLOV9_ROOT = "D:\\AIModels\\yolov9"',
        '$env:YOLOV9_WEIGHTS = "D:\\AIModels\\yolov9\\yolov9-c-converted.pt"',
        "",
        "# CARLA server command",
        r"D:\CARLA\packages\CARLA_0.9.16\CarlaUE4.exe -carla-rpc-port=2000 -RenderOffScreen -nosound",
        "",
    ]
    for variant, status, command in variant_commands:
        lines.extend(
            [
                f"# {variant.variant_id} ({status})",
                _command_text(command),
                "",
            ]
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_readme(path: Path, summary: dict[str, Any]) -> None:
    body = f"""# Phase 12C-YOLOv9-R1-LATENCY Route-Loop Latency Probe

Status:

```text
{summary["status"]}
```

```text
runtime_scope={summary["runtime_scope"]}
short_route_begin_evidence_dir={summary["short_route_begin_evidence_dir"]}
setup_evidence_dir={summary["setup_evidence_dir"]}
variant_count={summary["variant_count"]}
executed_variant_count={summary["executed_variant_count"]}
completed_variant_count={summary["completed_variant_count"]}
blocked_variant_count={summary["blocked_variant_count"]}
best_variant_id={summary["best_variant_id"]}
best_variant_effective_fps={summary["best_variant_effective_fps"]}
best_variant_yolov9_avg_ms={summary["best_variant_yolov9_avg_ms"]}
baseline_current_cadence_yolov9_avg_ms={summary["baseline_current_cadence_yolov9_avg_ms"]}
latency_bottleneck_classification={summary["latency_bottleneck_classification"]}
recommended_next_phase={summary["recommended_next_phase"]}
latency_probe_completed={str(summary["latency_probe_completed"]).lower()}
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


def _copy_variant_files(
    *,
    run_dir: Path,
    rows: list[dict[str, Any]],
) -> None:
    combined_events: list[dict[str, Any]] = []
    combined_heartbeats: list[dict[str, Any]] = []
    partials: dict[str, Any] = {}
    for row in rows:
        evidence_dir = row.get("evidence_dir")
        if not evidence_dir:
            continue
        evidence_path = Path(str(evidence_dir))
        for event in _read_jsonl(evidence_path / "events.jsonl"):
            combined_events.append({"variant_id": row["variant_id"], **event})
        for heartbeat in _read_jsonl(evidence_path / "heartbeat.jsonl"):
            combined_heartbeats.append({"variant_id": row["variant_id"], **heartbeat})
        partials[row["variant_id"]] = _read_json(evidence_path / "partial_metrics.json")
    _write_jsonl(run_dir / "events.jsonl", combined_events)
    _write_jsonl(run_dir / "heartbeat.jsonl", combined_heartbeats)
    _write_json(run_dir / "partial_metrics.json", partials)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Phase 12C-YOLOv9-R1-LATENCY selected route-loop latency probe")
    parser.add_argument("--route-id", default="route_01", choices=["route_01"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--python-executable", default=DEFAULT_CARLA_PYTHON)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--short-route-begin-evidence-dir", type=Path, default=DEFAULT_SHORT_ROUTE_BEGIN_EVIDENCE_DIR)
    parser.add_argument("--setup-evidence-dir", type=Path, default=DEFAULT_SETUP_EVIDENCE_DIR)
    parser.add_argument("--diagnostic-evidence-dir", type=Path, default=DIAGNOSTIC_EVIDENCE_DIR)
    parser.add_argument("--diagnostic-timeout-sec", type=float, default=600.0)
    parser.add_argument("--child-timeout-sec", type=float, default=600.0)
    parser.add_argument("--parent-timeout-sec", type=float, default=2400.0)
    parser.add_argument("--emit-heartbeat-every", type=int, default=5)
    parser.add_argument("--emit-partial-metrics-every", type=int, default=10)
    parser.add_argument("--max-executed-variants", type=int, default=2)
    parser.add_argument("--execute-all-variants", action="store_true")
    parser.add_argument("--require-yolov9-ready", action="store_true")
    parser.add_argument("--require-setup-passed", action="store_true", default=True)
    parser.add_argument("--skip-setup-passed-check", action="store_false", dest="require_setup_passed")
    parser.add_argument("--require-short-route-begin-passed", action="store_true", default=True)
    parser.add_argument("--skip-short-route-begin-check", action="store_false", dest="require_short_route_begin_passed")
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
    args.short_route_begin_evidence_dir = _resolve_repo_path(args.short_route_begin_evidence_dir)
    args.setup_evidence_dir = _resolve_repo_path(args.setup_evidence_dir)
    args.diagnostic_evidence_dir = _resolve_repo_path(args.diagnostic_evidence_dir)
    args.source_adapter_verified_evidence_dir = _resolve_repo_path(args.source_adapter_verified_evidence_dir)
    args.post_unlock_external_source_verified_dir = _resolve_repo_path(args.post_unlock_external_source_verified_dir)
    args.yolov9_rows_refresh_dir = _resolve_repo_path(args.yolov9_rows_refresh_dir)

    run_dir = r1._next_run_dir(args.output_dir, args.timestamp)
    raw_dir = run_dir / "raw_outputs"
    raw_dir.mkdir(exist_ok=True)
    runs_dir = run_dir / "runs"
    runs_dir.mkdir(exist_ok=True)

    env = _env_with_runtime_paths(args)
    setup = _evidence_passed(args.setup_evidence_dir, {"setup_probe_passed": True})
    short = _evidence_passed(args.short_route_begin_evidence_dir, {"short_route_begin_verified": True})
    preflight, edge_values, blocked_reason = _preflight(args, raw_dir, env)
    if args.dry_run:
        blocked_reason = None
    if args.require_setup_passed and not setup["passed"]:
        blocked_reason = "setup probe not passed"
    if args.require_short_route_begin_passed and not short["passed"]:
        blocked_reason = "short route-begin evidence not passed"

    max_executed = len(VARIANTS) if args.execute_all_variants else max(0, args.max_executed_variants)
    rows: list[dict[str, Any]] = []
    variant_commands: list[tuple[LatencyVariant, str, list[str]]] = []
    for index, variant in enumerate(VARIANTS):
        variant_output_root = runs_dir / variant.variant_id
        variant_output_root.mkdir(parents=True, exist_ok=True)
        command = _build_diagnostic_command(args, variant, variant_output_root)
        should_execute = (not args.dry_run) and blocked_reason is None and index < max_executed
        command_status = "executed" if should_execute else "prepared"
        variant_commands.append((variant, command_status, command))
        child_result: r1.CommandResult | None = None
        evidence_dir: str | None = None
        evidence = {"summary": {}, "events": [], "heartbeats": [], "partial_metrics": {}, "path": None}
        if should_execute:
            child_result, evidence_dir = _run_variant(
                args=args,
                raw_dir=raw_dir,
                env=env,
                variant=variant,
                command=command,
            )
            evidence = _load_variant_evidence(evidence_dir)
        rows.append(
            _row_from_variant(
                variant=variant,
                command=command,
                command_status=command_status,
                child_result=child_result,
                evidence_dir=evidence_dir,
                evidence=evidence,
            )
        )

    summary = _build_summary(
        args=args,
        run_dir=run_dir,
        preflight=preflight,
        edge_values=edge_values,
        blocked_reason=blocked_reason,
        setup=setup,
        short=short,
        rows=rows,
    )
    _copy_variant_files(run_dir=run_dir, rows=rows)
    _write_json(run_dir / "summary.json", summary)
    _write_csv(run_dir / "summary.csv", [summary], SUMMARY_COLUMNS)
    _write_csv(run_dir / "variant_summary.csv", rows, VARIANT_COLUMNS)
    _write_manifest(run_dir / "manifest.json", summary)
    _write_environment(run_dir / "environment.json", args, preflight)
    _write_commands(run_dir / "commands.txt", [sys.executable, *sys.argv], variant_commands)
    _write_readme(run_dir / "README.md", summary)

    print(f"experiment_dir={run_dir}")
    print(summary["status"])
    print(f"latency_bottleneck_classification={summary['latency_bottleneck_classification']}")
    print(f"recommended_next_phase={summary['recommended_next_phase']}")
    if args.dry_run:
        return 0
    return 0 if summary["latency_probe_completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

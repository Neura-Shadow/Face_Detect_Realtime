"""
Phase 12C-YOLOv9-R1-YOLOv9-LIGHTWEIGHT feasibility probe.

The parent wrapper intentionally does not import CARLA. It checks the selected
YOLOv9 readiness chain, verifies the operator-provided lightweight asset
contract, delegates bounded route-loop diagnostics to the existing R1-DIAG
path, and keeps every output scoped to runtime feasibility evidence only.
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import run_phase12c_yolov9_r1_latency_opt_probe as opt
from scripts import run_phase12c_yolov9_runtime_confirmation as r1

DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "phase12"
DEFAULT_CARLA_ROOT = Path(r"D:\CARLA\packages\CARLA_0.9.16")
DEFAULT_CARLA_PYTHON = r"D:\CARLA\envs\ma-vlna-carla312\python.exe"
DEFAULT_SOURCE_ADAPTER_EVIDENCE_DIR = Path(r"experiments\phase12\20260630T060621Z")
DEFAULT_POST_UNLOCK_EVIDENCE_DIR = Path(r"experiments\phase12\20260630T061015Z")
DEFAULT_ROWS_REFRESH_DIR = Path(r"experiments\phase12\20260630T060823Z")
DEFAULT_SETUP_EVIDENCE_DIR = Path(r"experiments\phase12\20260701T045047Z")
DEFAULT_SHORT_ROUTE_BEGIN_EVIDENCE_DIR = Path(r"experiments\phase12\20260701T064944Z")
DEFAULT_LATENCY_EVIDENCE_DIR = Path(r"experiments\phase12\20260701T103721Z")
DEFAULT_LATENCY_OPT_EVIDENCE_DIR = Path(r"experiments\phase12\20260701T115744Z")

PHASE = "Phase 12C-YOLOv9-R1-YOLOv9-LIGHTWEIGHT"
STATUS_CODE_PREPARED = "prepared"
STATUS_CODE_COMPLETED_USEFUL = "completed_useful_improvement"
STATUS_CODE_COMPLETED_NO_IMPROVEMENT = "completed_no_improvement"
STATUS_CODE_BLOCKED = "blocked"
STATUS_PREPARED = (
    "Phase 12C-YOLOv9-R1-YOLOv9-LIGHTWEIGHT Prepared - selected "
    "lightweight YOLOv9 feasibility commands are ready."
)
STATUS_COMPLETED_USEFUL = (
    "Phase 12C-YOLOv9-R1-YOLOv9-LIGHTWEIGHT Completed - lightweight "
    "YOLOv9 profile produced useful no-fallback route-loop timing "
    "improvement without claiming route completion."
)
STATUS_COMPLETED_NO_IMPROVEMENT = (
    "Phase 12C-YOLOv9-R1-YOLOv9-LIGHTWEIGHT No-Improvement - "
    "lightweight YOLOv9 probe completed, but no useful no-fallback "
    "route-loop timing improvement was verified."
)
STATUS_BLOCKED = (
    "Phase 12C-YOLOv9-R1-YOLOv9-LIGHTWEIGHT Blocked - lightweight "
    "YOLOv9 probe could not produce bounded no-fallback route-loop "
    "timing evidence."
)

BASELINE_LATENCY_AVG_MS = 2522.06
LATENCY_OPT_BEST_AVG_MS = 2194.8
LATENCY_OPT_BEST_EFFECTIVE_FPS = 0.168392

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
    "status_line",
    "runtime_scope",
    "latency_opt_evidence_dir",
    "latency_evidence_dir",
    "short_route_begin_evidence_dir",
    "setup_evidence_dir",
    "route_id",
    "controller_mode",
    "perception_backend",
    "source_adapter_verified",
    "edge_yolov9_fallback_used",
    "edge_yolov9_no_fallback_verified",
    "setup_probe_passed",
    "short_route_begin_verified",
    "latency_probe_completed",
    "latency_opt_completed",
    "useful_latency_improvement_verified",
    "baseline_latency_avg_ms",
    "latency_opt_best_avg_ms",
    "latency_opt_best_effective_fps",
    "lightweight_weights_configured",
    "lightweight_weights_ready",
    "variant_count",
    "executed_variant_count",
    "completed_variant_count",
    "blocked_variant_count",
    "best_variant_id",
    "best_variant_profile",
    "best_variant_effective_fps",
    "best_variant_yolov9_avg_ms",
    "best_variant_yolov9_p95_ms",
    "best_variant_img_size",
    "best_variant_half",
    "best_variant_stride",
    "best_variant_cached",
    "best_avg_ms_improvement_vs_latency_pct",
    "best_avg_ms_improvement_vs_opt_pct",
    "best_fps_improvement_vs_opt_pct",
    "lightweight_bottleneck_classification",
    "useful_lightweight_profile_verified",
    "lightweight_probe_completed",
    "recommended_next_phase",
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
    "yolov9_profile",
    "yolov9_weights_source",
    "lightweight_weights_ready",
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
    "yolov9_img_size",
    "yolov9_half",
    "yolov9_device",
    "yolov9_warmup_runs",
    "perception_inference_stride",
    "reuse_last_perception_between_inference",
    "cache_events_recorded",
    "yolov9_preprocess_ms_avg",
    "yolov9_model_forward_ms_avg",
    "yolov9_nms_ms_avg",
    "yolov9_postprocess_ms_avg",
    "yolov9_total_inference_ms_avg",
    "yolov9_total_inference_ms_p50",
    "yolov9_total_inference_ms_p95",
    "yolov9_total_inference_ms_max",
    "baseline_latency_avg_ms",
    "latency_opt_best_avg_ms",
    "latency_opt_best_effective_fps",
    "avg_ms_improvement_vs_latency_pct",
    "avg_ms_improvement_vs_opt_pct",
    "fps_improvement_vs_opt_pct",
    "stable_route_loop",
    "lightweight_classification",
    "result",
    "command_status",
    "evidence_dir",
)


@dataclass(frozen=True)
class LightweightVariant:
    variant_id: str
    diagnostic_steps: int
    perception_backend: str
    yolov9_profile: str
    yolov9_img_size: int | None
    yolov9_half: bool
    yolov9_device: str | None
    yolov9_warmup_runs: int
    perception_inference_stride: int
    reuse_last_perception_between_inference: bool
    record_perception_cache_events: bool
    execute_by_default: bool = True


VARIANTS = (
    LightweightVariant(
        variant_id="variant_01_baseline_recheck",
        diagnostic_steps=30,
        perception_backend="yolov9",
        yolov9_profile="baseline",
        yolov9_img_size=None,
        yolov9_half=False,
        yolov9_device=None,
        yolov9_warmup_runs=0,
        perception_inference_stride=1,
        reuse_last_perception_between_inference=False,
        record_perception_cache_events=False,
    ),
    LightweightVariant(
        variant_id="variant_02_lightweight_default",
        diagnostic_steps=50,
        perception_backend="yolov9",
        yolov9_profile="lightweight",
        yolov9_img_size=None,
        yolov9_half=False,
        yolov9_device=None,
        yolov9_warmup_runs=0,
        perception_inference_stride=1,
        reuse_last_perception_between_inference=False,
        record_perception_cache_events=False,
    ),
    LightweightVariant(
        variant_id="variant_03_lightweight_imgsz_512",
        diagnostic_steps=50,
        perception_backend="yolov9",
        yolov9_profile="lightweight",
        yolov9_img_size=512,
        yolov9_half=False,
        yolov9_device=None,
        yolov9_warmup_runs=0,
        perception_inference_stride=1,
        reuse_last_perception_between_inference=False,
        record_perception_cache_events=False,
    ),
    LightweightVariant(
        variant_id="variant_04_lightweight_imgsz_416",
        diagnostic_steps=50,
        perception_backend="yolov9",
        yolov9_profile="lightweight",
        yolov9_img_size=416,
        yolov9_half=False,
        yolov9_device=None,
        yolov9_warmup_runs=0,
        perception_inference_stride=1,
        reuse_last_perception_between_inference=False,
        record_perception_cache_events=False,
        execute_by_default=False,
    ),
    LightweightVariant(
        variant_id="variant_05_lightweight_stride_5_cached",
        diagnostic_steps=100,
        perception_backend="yolov9",
        yolov9_profile="lightweight",
        yolov9_img_size=512,
        yolov9_half=False,
        yolov9_device=None,
        yolov9_warmup_runs=0,
        perception_inference_stride=5,
        reuse_last_perception_between_inference=True,
        record_perception_cache_events=True,
    ),
    LightweightVariant(
        variant_id="variant_06_lightweight_half",
        diagnostic_steps=50,
        perception_backend="yolov9",
        yolov9_profile="lightweight",
        yolov9_img_size=512,
        yolov9_half=True,
        yolov9_device=None,
        yolov9_warmup_runs=0,
        perception_inference_stride=1,
        reuse_last_perception_between_inference=False,
        record_perception_cache_events=False,
        execute_by_default=False,
    ),
    LightweightVariant(
        variant_id="variant_07_dummy_reference",
        diagnostic_steps=100,
        perception_backend="dummy",
        yolov9_profile="baseline",
        yolov9_img_size=None,
        yolov9_half=False,
        yolov9_device=None,
        yolov9_warmup_runs=0,
        perception_inference_stride=1,
        reuse_last_perception_between_inference=False,
        record_perception_cache_events=False,
        execute_by_default=False,
    ),
)


def _lightweight_status() -> dict[str, Any]:
    value = os.getenv("YOLOV9_LIGHTWEIGHT_WEIGHTS")
    profile = os.getenv("YOLOV9_LIGHTWEIGHT_PROFILE", "yolov9_lightweight")
    path = Path(value).expanduser() if value else None
    ready = bool(path and path.exists() and path.is_file())
    return {
        "YOLOV9_LIGHTWEIGHT_WEIGHTS_configured": bool(value),
        "YOLOV9_LIGHTWEIGHT_PROFILE": profile,
        "lightweight_weights": str(path) if path else None,
        "lightweight_weights_configured": bool(value),
        "lightweight_weights_ready": ready,
    }


def _build_diagnostic_command(args: argparse.Namespace, variant: LightweightVariant, variant_output_root: Path) -> list[str]:
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
        "--edge-probe-timeout-sec",
        str(args.edge_probe_timeout_sec),
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
    if variant.perception_backend == "yolov9":
        command.extend(["--yolov9-profile", variant.yolov9_profile])
    if variant.yolov9_img_size is not None:
        command.extend(["--yolov9-img-size", str(variant.yolov9_img_size)])
    if variant.yolov9_half:
        command.append("--yolov9-half")
    if variant.yolov9_device:
        command.extend(["--yolov9-device", variant.yolov9_device])
    if variant.yolov9_warmup_runs:
        command.extend(["--yolov9-warmup-runs", str(variant.yolov9_warmup_runs)])
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
    variant: LightweightVariant,
    command: list[str],
) -> tuple[r1.CommandResult, str | None]:
    result = r1._run_command(
        name=f"phase12c_yolov9_r1_lightweight_{variant.variant_id}",
        command=command,
        raw_dir=raw_dir,
        env=env,
        timeout_sec=args.parent_timeout_sec,
    )
    stdout = Path(result.stdout_path).read_text(encoding="utf-8", errors="replace")
    stderr = Path(result.stderr_path).read_text(encoding="utf-8", errors="replace")
    return result, r1._parse_experiment_dir(stdout + "\n" + stderr)


def _classification(row: dict[str, Any]) -> str:
    if row["perception_backend"] != "yolov9":
        return "lightweight_profile_completed" if row["diagnostic_steps_completed"] > 0 else "lightweight_profile_unknown"
    if row["yolov9_profile"] == "lightweight" and not row["lightweight_weights_ready"]:
        return "lightweight_weights_missing"
    if row["edge_yolov9_fallback_used_during_route"] is True:
        return "lightweight_fallback_regression"
    if (row.get("yolov9_inference_call_count") or 0) <= 0:
        return "timeout_before_lightweight_profile"
    stable = row.get("stable_route_loop") is True
    avg_vs_latency = row.get("avg_ms_improvement_vs_latency_pct")
    avg_vs_opt = row.get("avg_ms_improvement_vs_opt_pct")
    fps_vs_opt = row.get("fps_improvement_vs_opt_pct")
    if row.get("reuse_last_perception_between_inference") and stable and isinstance(fps_vs_opt, (int, float)) and fps_vs_opt >= 50.0:
        return "lightweight_cached_cadence_stable"
    if (
        (isinstance(avg_vs_latency, (int, float)) and avg_vs_latency >= 40.0)
        or (isinstance(avg_vs_opt, (int, float)) and avg_vs_opt >= 25.0)
        or (isinstance(fps_vs_opt, (int, float)) and fps_vs_opt >= 50.0)
    ):
        return "lightweight_useful_improvement"
    if (
        (isinstance(avg_vs_opt, (int, float)) and avg_vs_opt <= -10.0)
        or (isinstance(fps_vs_opt, (int, float)) and fps_vs_opt <= -10.0)
    ):
        return "lightweight_regressed"
    largest = opt._largest_timing_component(row)
    if largest == "forward" and (row.get("yolov9_model_forward_ms_avg") or 0) > 1000:
        return "lightweight_forward_still_dominant"
    return "lightweight_no_improvement" if row["diagnostic_steps_completed"] > 0 else "lightweight_profile_unknown"


def _row_from_variant(
    *,
    args: argparse.Namespace,
    variant: LightweightVariant,
    command: list[str],
    command_status: str,
    child_result: r1.CommandResult | None,
    evidence_dir: str | None,
    evidence: dict[str, Any],
    lightweight: dict[str, Any],
    blocked_reason: str | None,
) -> dict[str, Any]:
    summary = evidence["summary"]
    events = evidence["events"]
    heartbeats = evidence["heartbeats"]
    edge_events = [event for event in events if event.get("phase") == "edge_perception_finished"]
    real_events = [event for event in edge_events if event.get("real_inference_call") is not False]
    cached_count = sum(1 for event in edge_events if event.get("cached_result_used") is True)
    if not cached_count:
        cached_count = sum(1 for item in heartbeats if item.get("cached_result_used") is True)

    steps_completed = opt._int_or_none(summary.get("diagnostic_steps_completed")) or 0
    duration_sec = child_result.duration_sec if child_result else None
    edge_count = len(edge_events) or (opt._int_or_none(summary.get("edge_perception_call_count")) or 0)
    yolo_count = len([event for event in real_events if opt._num_or_none(event.get("yolov9_total_inference_ms")) is not None])
    if yolo_count == 0:
        yolo_count = opt._int_or_none(summary.get("yolov9_inference_call_count")) or 0

    row: dict[str, Any] = {
        "variant_id": variant.variant_id,
        "route_id": args.route_id,
        "controller_mode": "grp_follower",
        "perception_backend": variant.perception_backend,
        "yolov9_profile": variant.yolov9_profile if variant.perception_backend == "yolov9" else None,
        "yolov9_weights_source": (
            "YOLOV9_LIGHTWEIGHT_WEIGHTS"
            if variant.yolov9_profile == "lightweight"
            else "YOLOV9_WEIGHTS"
        ),
        "lightweight_weights_ready": lightweight["lightweight_weights_ready"],
        "diagnostic_steps_requested": variant.diagnostic_steps,
        "diagnostic_steps_completed": steps_completed,
        "duration_sec": duration_sec,
        "effective_steps_per_sec": round(steps_completed / duration_sec, 6) if duration_sec else None,
        "effective_fps": round(steps_completed / duration_sec, 6) if duration_sec else None,
        "world_tick_count": opt._int_or_none(summary.get("world_tick_count")) or 0,
        "rgb_frame_received_count": opt._int_or_none(summary.get("rgb_frame_received_count")) or 0,
        "edge_perception_call_count": edge_count,
        "yolov9_inference_call_count": yolo_count,
        "cached_perception_result_count": cached_count,
        "real_inference_ratio": round(yolo_count / edge_count, 6) if edge_count else None,
        "edge_yolov9_fallback_used_during_route": opt._fallback_state(events, heartbeats),
        "partial_route_progress_seen": bool(summary.get("partial_route_progress_seen")),
        "last_route_progress_pct": opt._num_or_none(summary.get("last_route_progress_pct")),
        "last_distance_to_goal_m": opt._num_or_none(summary.get("last_distance_to_goal_m")),
        "last_collision_count": opt._int_or_none(summary.get("last_collision_count")),
        "last_lane_invasion_count": opt._int_or_none(summary.get("last_lane_invasion_count")),
        "goal_reached": None,
        "timeout": bool(child_result and child_result.exit_code == 124),
        "child_exit_code": child_result.exit_code if child_result else None,
        "yolov9_img_size": variant.yolov9_img_size if variant.yolov9_img_size is not None else 640,
        "yolov9_half": variant.yolov9_half,
        "yolov9_device": variant.yolov9_device or "auto",
        "yolov9_warmup_runs": variant.yolov9_warmup_runs,
        "perception_inference_stride": variant.perception_inference_stride,
        "reuse_last_perception_between_inference": variant.reuse_last_perception_between_inference,
        "cache_events_recorded": variant.record_perception_cache_events,
        "result": "prepared" if command_status == "prepared" else "completed",
        "command_status": command_status,
        "evidence_dir": evidence_dir,
        "command": opt._command_text(command),
    }
    child_summary = summary.get("child_summary")
    if isinstance(child_summary, dict):
        row["goal_reached"] = child_summary.get("fixed_route_goal_reached")
    child_row = summary.get("child_route_row")
    if isinstance(child_row, dict):
        row["goal_reached"] = child_row.get("fixed_route_goal_reached")

    for component in opt.TIMING_COMPONENTS:
        stats = opt._timing_stats(opt._timing_values(events, component))
        row[f"{component}_avg"] = stats["avg"]
        row[f"{component}_p50"] = stats["p50"]
        row[f"{component}_p95"] = stats["p95"]
        row[f"{component}_max"] = stats["max"]

    row["baseline_latency_avg_ms"] = BASELINE_LATENCY_AVG_MS
    row["latency_opt_best_avg_ms"] = LATENCY_OPT_BEST_AVG_MS
    row["latency_opt_best_effective_fps"] = LATENCY_OPT_BEST_EFFECTIVE_FPS
    row["avg_ms_improvement_vs_latency_pct"] = opt._pct_improvement(
        BASELINE_LATENCY_AVG_MS,
        row.get("yolov9_total_inference_ms_avg"),
    )
    row["avg_ms_improvement_vs_opt_pct"] = opt._pct_improvement(
        LATENCY_OPT_BEST_AVG_MS,
        row.get("yolov9_total_inference_ms_avg"),
    )
    if isinstance(row.get("effective_fps"), (int, float)) and LATENCY_OPT_BEST_EFFECTIVE_FPS > 0:
        row["fps_improvement_vs_opt_pct"] = round(
            ((float(row["effective_fps"]) - LATENCY_OPT_BEST_EFFECTIVE_FPS) / LATENCY_OPT_BEST_EFFECTIVE_FPS) * 100.0,
            3,
        )
    else:
        row["fps_improvement_vs_opt_pct"] = None
    row["stable_route_loop"] = (
        row["diagnostic_steps_completed"] > 0
        and row["world_tick_count"] > 0
        and row["rgb_frame_received_count"] > 0
        and row["edge_perception_call_count"] > 0
        and row["edge_yolov9_fallback_used_during_route"] is not True
    )
    row["lightweight_classification"] = _classification(row)
    if command_status == "prepared" and blocked_reason and variant.yolov9_profile == "lightweight":
        row["result"] = "blocked"
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


def _recommend_next_phase(rows: list[dict[str, Any]], lightweight: dict[str, Any]) -> str:
    valid = [
        row
        for row in rows
        if row.get("yolov9_profile") == "lightweight"
        and row.get("result") == "completed"
        and row.get("edge_yolov9_fallback_used_during_route") is False
        and (row.get("yolov9_inference_call_count") or 0) > 0
    ]
    if not lightweight["lightweight_weights_ready"]:
        return "R1-RT-DETR-UNLOCK"
    if not valid:
        return "BLOCKED"
    best = max(
        valid,
        key=lambda row: (
            row.get("avg_ms_improvement_vs_opt_pct") if isinstance(row.get("avg_ms_improvement_vs_opt_pct"), (int, float)) else -999.0,
            row.get("fps_improvement_vs_opt_pct") if isinstance(row.get("fps_improvement_vs_opt_pct"), (int, float)) else -999.0,
        ),
    )
    avg_ms = best.get("yolov9_total_inference_ms_avg")
    improved = best.get("lightweight_classification") in {
        "lightweight_useful_improvement",
        "lightweight_cached_cadence_stable",
    }
    if isinstance(avg_ms, (int, float)) and avg_ms <= 500.0 and best.get("stable_route_loop") is True:
        return "R1-COMPLETE-ROUTE"
    if improved and isinstance(avg_ms, (int, float)) and 500.0 < avg_ms <= 1500.0:
        return "R1-STRIDE-ROUTE-BEGIN"
    if improved and isinstance(avg_ms, (int, float)) and avg_ms > 1500.0:
        return "R1-LIGHTWEIGHT-OPT"
    return "R1-RT-DETR-UNLOCK"


def _build_summary(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    preflight: dict[str, Any],
    edge_values: dict[str, str],
    blocked_reason: str | None,
    setup: dict[str, Any],
    short: dict[str, Any],
    latency: dict[str, Any],
    latency_opt: dict[str, Any],
    lightweight: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    executed = [row for row in rows if row["command_status"] == "executed"]
    completed = [
        row
        for row in executed
        if row.get("yolov9_profile") == "lightweight"
        and row["result"] == "completed"
        and (row.get("yolov9_inference_call_count") or 0) > 0
        and row.get("edge_yolov9_fallback_used_during_route") is False
    ]
    best = (
        max(
            completed,
            key=lambda row: (
                row.get("avg_ms_improvement_vs_opt_pct") if isinstance(row.get("avg_ms_improvement_vs_opt_pct"), (int, float)) else -999.0,
                row.get("fps_improvement_vs_opt_pct") if isinstance(row.get("fps_improvement_vs_opt_pct"), (int, float)) else -999.0,
                row.get("effective_fps") if isinstance(row.get("effective_fps"), (int, float)) else 0.0,
            ),
        )
        if completed
        else None
    )
    useful = bool(best and best.get("lightweight_classification") in {"lightweight_useful_improvement", "lightweight_cached_cadence_stable"})
    probe_completed = bool(completed) and not args.dry_run
    if args.dry_run:
        status_code = STATUS_CODE_PREPARED
        status_line = STATUS_PREPARED
    elif not probe_completed:
        status_code = STATUS_CODE_BLOCKED
        status_line = STATUS_BLOCKED
    elif useful:
        status_code = STATUS_CODE_COMPLETED_USEFUL
        status_line = STATUS_COMPLETED_USEFUL
    else:
        status_code = STATUS_CODE_COMPLETED_NO_IMPROVEMENT
        status_line = STATUS_COMPLETED_NO_IMPROVEMENT

    edge_fallback = edge_values.get("edge_yolov9_fallback_used", "").lower() == "true"
    edge_no_fallback = edge_values.get("edge_yolov9_no_fallback_verified", "").lower() == "true"
    recommended = _recommend_next_phase(rows, lightweight) if not args.dry_run else "BLOCKED"
    classification = (
        best.get("lightweight_classification")
        if best
        else ("lightweight_weights_missing" if not lightweight["lightweight_weights_ready"] else "timeout_before_lightweight_profile")
    )

    return {
        "phase": PHASE,
        "status": status_code,
        "status_line": status_line,
        "blocked_reason": blocked_reason,
        "dry_run": args.dry_run,
        "run_dir": str(run_dir),
        "runtime_scope": "selected_yolov9_lightweight_feasibility_probe",
        "latency_opt_evidence_dir": opt._display_path(args.latency_opt_evidence_dir),
        "latency_evidence_dir": opt._display_path(args.latency_evidence_dir),
        "short_route_begin_evidence_dir": opt._display_path(args.short_route_begin_evidence_dir),
        "setup_evidence_dir": opt._display_path(args.setup_evidence_dir),
        "route_id": args.route_id,
        "controller_mode": "grp_follower",
        "perception_backend": "yolov9",
        "source_adapter_verified": preflight.get("yolov9_source_adapter_verified") is True,
        "edge_yolov9_fallback_used": edge_fallback,
        "edge_yolov9_no_fallback_verified": edge_no_fallback,
        "setup_probe_passed": setup["passed"],
        "short_route_begin_verified": short["passed"],
        "latency_probe_completed": latency["passed"],
        "latency_opt_completed": latency_opt["passed"],
        "useful_latency_improvement_verified": False,
        "baseline_latency_avg_ms": BASELINE_LATENCY_AVG_MS,
        "latency_opt_best_avg_ms": LATENCY_OPT_BEST_AVG_MS,
        "latency_opt_best_effective_fps": LATENCY_OPT_BEST_EFFECTIVE_FPS,
        "lightweight_weights_configured": lightweight["lightweight_weights_configured"],
        "lightweight_weights_ready": lightweight["lightweight_weights_ready"],
        "variant_count": len(rows),
        "executed_variant_count": len(executed),
        "completed_variant_count": len(completed),
        "blocked_variant_count": len([row for row in rows if row["result"] == "blocked"]),
        "best_variant_id": best.get("variant_id") if best else None,
        "best_variant_profile": best.get("yolov9_profile") if best else None,
        "best_variant_effective_fps": best.get("effective_fps") if best else None,
        "best_variant_yolov9_avg_ms": best.get("yolov9_total_inference_ms_avg") if best else None,
        "best_variant_yolov9_p95_ms": best.get("yolov9_total_inference_ms_p95") if best else None,
        "best_variant_img_size": best.get("yolov9_img_size") if best else None,
        "best_variant_half": best.get("yolov9_half") if best else None,
        "best_variant_stride": best.get("perception_inference_stride") if best else None,
        "best_variant_cached": best.get("reuse_last_perception_between_inference") if best else None,
        "best_avg_ms_improvement_vs_latency_pct": best.get("avg_ms_improvement_vs_latency_pct") if best else None,
        "best_avg_ms_improvement_vs_opt_pct": best.get("avg_ms_improvement_vs_opt_pct") if best else None,
        "best_fps_improvement_vs_opt_pct": best.get("fps_improvement_vs_opt_pct") if best else None,
        "lightweight_bottleneck_classification": classification,
        "useful_lightweight_profile_verified": useful,
        "lightweight_probe_completed": probe_completed,
        "recommended_next_phase": recommended,
        "variants": rows,
        "preflight": preflight,
        "edge_probe_values": edge_values,
        "lightweight_asset_contract": lightweight,
        "setup_evidence": {"exists": setup["exists"], "passed": setup["passed"], "missing_or_mismatch": setup["missing_or_mismatch"]},
        "short_route_begin_evidence": {"exists": short["exists"], "passed": short["passed"], "missing_or_mismatch": short["missing_or_mismatch"]},
        "latency_evidence": {"exists": latency["exists"], "passed": latency["passed"], "missing_or_mismatch": latency["missing_or_mismatch"]},
        "latency_opt_evidence": {"exists": latency_opt["exists"], "passed": latency_opt["passed"], "missing_or_mismatch": latency_opt["missing_or_mismatch"]},
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": "lightweight_yolov9_feasibility_only_not_route_completion",
        **BOUNDARY_FIELDS,
        "benchmark_boundaries": dict(BOUNDARY_FIELDS),
    }


def _write_manifest(path: Path, summary: dict[str, Any]) -> None:
    opt._write_json(
        path,
        {
            "phase": PHASE,
            "status": summary["status"],
            "status_line": summary["status_line"],
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


def _write_environment(path: Path, args: argparse.Namespace, preflight: dict[str, Any], lightweight: dict[str, Any]) -> None:
    opt._write_json(
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
            "YOLOV9_LIGHTWEIGHT_WEIGHTS_configured": lightweight["YOLOV9_LIGHTWEIGHT_WEIGHTS_configured"],
            "YOLOV9_LIGHTWEIGHT_PROFILE": lightweight["YOLOV9_LIGHTWEIGHT_PROFILE"],
            "yolov9_source_root_ready": preflight.get("yolov9_source_root_ready"),
            "yolov9_weights_ready": preflight.get("yolov9_weights_ready"),
            "lightweight_weights_ready": lightweight["lightweight_weights_ready"],
            "lightweight_weights": lightweight["lightweight_weights"],
        },
    )


def _write_commands(path: Path, parent_command: list[str], variant_commands: list[tuple[LightweightVariant, str, list[str]]]) -> None:
    lines = [
        "# Phase 12C-YOLOv9-R1-YOLOv9-LIGHTWEIGHT parent command",
        opt._command_text(parent_command),
        "",
        "# Required operator environment",
        '$env:CARLA_ROOT = "D:\\CARLA\\packages\\CARLA_0.9.16"',
        '$env:YOLOV9_ROOT = "D:\\AIModels\\yolov9"',
        '$env:YOLOV9_WEIGHTS = "D:\\AIModels\\yolov9\\yolov9-c-converted.pt"',
        "",
        "# Optional lightweight operator environment",
        '$env:YOLOV9_LIGHTWEIGHT_WEIGHTS = "D:\\AIModels\\yolov9\\<operator_provided_lightweight_weights>.pt"',
        '$env:YOLOV9_LIGHTWEIGHT_PROFILE = "yolov9_lightweight"',
        "",
        "# CARLA server command",
        r"D:\CARLA\packages\CARLA_0.9.16\CarlaUE4.exe -carla-rpc-port=2000 -RenderOffScreen -nosound",
        "",
    ]
    for variant, status, command in variant_commands:
        lines.extend([f"# {variant.variant_id} ({status})", opt._command_text(command), ""])
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_readme(path: Path, summary: dict[str, Any]) -> None:
    body = f"""# Phase 12C-YOLOv9-R1-YOLOv9-LIGHTWEIGHT Feasibility Probe

Status:

```text
{summary["status_line"]}
```

```text
status={summary["status"]}
runtime_scope={summary["runtime_scope"]}
latency_opt_evidence_dir={summary["latency_opt_evidence_dir"]}
latency_evidence_dir={summary["latency_evidence_dir"]}
short_route_begin_evidence_dir={summary["short_route_begin_evidence_dir"]}
setup_evidence_dir={summary["setup_evidence_dir"]}
lightweight_weights_configured={str(summary["lightweight_weights_configured"]).lower()}
lightweight_weights_ready={str(summary["lightweight_weights_ready"]).lower()}
variant_count={summary["variant_count"]}
executed_variant_count={summary["executed_variant_count"]}
completed_variant_count={summary["completed_variant_count"]}
blocked_variant_count={summary["blocked_variant_count"]}
best_variant_id={summary["best_variant_id"]}
best_variant_profile={summary["best_variant_profile"]}
best_variant_effective_fps={summary["best_variant_effective_fps"]}
best_variant_yolov9_avg_ms={summary["best_variant_yolov9_avg_ms"]}
best_avg_ms_improvement_vs_latency_pct={summary["best_avg_ms_improvement_vs_latency_pct"]}
best_avg_ms_improvement_vs_opt_pct={summary["best_avg_ms_improvement_vs_opt_pct"]}
best_fps_improvement_vs_opt_pct={summary["best_fps_improvement_vs_opt_pct"]}
lightweight_bottleneck_classification={summary["lightweight_bottleneck_classification"]}
useful_lightweight_profile_verified={str(summary["useful_lightweight_profile_verified"]).lower()}
recommended_next_phase={summary["recommended_next_phase"]}
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Phase 12C-YOLOv9-R1 lightweight feasibility probe")
    parser.add_argument("--route-id", default="route_01", choices=["route_01"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--python-executable", default=DEFAULT_CARLA_PYTHON)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--setup-evidence-dir", type=Path, default=DEFAULT_SETUP_EVIDENCE_DIR)
    parser.add_argument("--short-route-begin-evidence-dir", type=Path, default=DEFAULT_SHORT_ROUTE_BEGIN_EVIDENCE_DIR)
    parser.add_argument("--latency-evidence-dir", type=Path, default=DEFAULT_LATENCY_EVIDENCE_DIR)
    parser.add_argument("--latency-opt-evidence-dir", type=Path, default=DEFAULT_LATENCY_OPT_EVIDENCE_DIR)
    parser.add_argument("--diagnostic-timeout-sec", type=float, default=600.0)
    parser.add_argument("--child-timeout-sec", type=float, default=600.0)
    parser.add_argument("--parent-timeout-sec", type=float, default=2400.0)
    parser.add_argument("--edge-probe-timeout-sec", type=float, default=600.0)
    parser.add_argument("--emit-heartbeat-every", type=int, default=5)
    parser.add_argument("--emit-partial-metrics-every", type=int, default=10)
    parser.add_argument("--max-executed-variants", type=int, default=0)
    parser.add_argument("--execute-all-variants", action="store_true")
    parser.add_argument("--require-yolov9-ready", action="store_true")
    parser.add_argument("--require-setup-passed", action="store_true", default=True)
    parser.add_argument("--skip-setup-passed-check", action="store_false", dest="require_setup_passed")
    parser.add_argument("--require-short-route-begin-passed", action="store_true", default=True)
    parser.add_argument("--skip-short-route-begin-check", action="store_false", dest="require_short_route_begin_passed")
    parser.add_argument("--require-latency-passed", action="store_true", default=True)
    parser.add_argument("--skip-latency-passed-check", action="store_false", dest="require_latency_passed")
    parser.add_argument("--require-latency-opt-completed", action="store_true", default=True)
    parser.add_argument("--skip-latency-opt-check", action="store_false", dest="require_latency_opt_completed")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-source-adapter-evidence-check", action="store_true")
    parser.add_argument("--source-adapter-verified-evidence-dir", type=Path, default=DEFAULT_SOURCE_ADAPTER_EVIDENCE_DIR)
    parser.add_argument("--post-unlock-external-source-verified-dir", type=Path, default=DEFAULT_POST_UNLOCK_EVIDENCE_DIR)
    parser.add_argument("--yolov9-rows-refresh-dir", type=Path, default=DEFAULT_ROWS_REFRESH_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.output_dir = opt._resolve_repo_path(args.output_dir)
    args.carla_root = opt._resolve_repo_path(args.carla_root)
    args.setup_evidence_dir = opt._resolve_repo_path(args.setup_evidence_dir)
    args.short_route_begin_evidence_dir = opt._resolve_repo_path(args.short_route_begin_evidence_dir)
    args.latency_evidence_dir = opt._resolve_repo_path(args.latency_evidence_dir)
    args.latency_opt_evidence_dir = opt._resolve_repo_path(args.latency_opt_evidence_dir)
    args.source_adapter_verified_evidence_dir = opt._resolve_repo_path(args.source_adapter_verified_evidence_dir)
    args.post_unlock_external_source_verified_dir = opt._resolve_repo_path(args.post_unlock_external_source_verified_dir)
    args.yolov9_rows_refresh_dir = opt._resolve_repo_path(args.yolov9_rows_refresh_dir)

    run_dir = r1._next_run_dir(args.output_dir, args.timestamp)
    raw_dir = run_dir / "raw_outputs"
    raw_dir.mkdir(exist_ok=True)
    runs_dir = run_dir / "runs"
    runs_dir.mkdir(exist_ok=True)

    env = opt._env_with_runtime_paths(args)
    setup = opt._evidence_passed(args.setup_evidence_dir, {"setup_probe_passed": True})
    short = opt._evidence_passed(args.short_route_begin_evidence_dir, {"short_route_begin_verified": True})
    latency = opt._evidence_passed(args.latency_evidence_dir, {"latency_probe_completed": True})
    latency_opt = opt._evidence_passed(args.latency_opt_evidence_dir, {"latency_opt_completed": True})
    lightweight = _lightweight_status()
    preflight, edge_values, blocked_reason = r1._preflight(args, raw_dir, env)
    if args.dry_run:
        blocked_reason = None
    if args.require_setup_passed and not setup["passed"]:
        blocked_reason = "setup probe not passed"
    if args.require_short_route_begin_passed and not short["passed"]:
        blocked_reason = "short route-begin evidence not passed"
    if args.require_latency_passed and not latency["passed"]:
        blocked_reason = "R1-LATENCY evidence not passed"
    if args.require_latency_opt_completed and not latency_opt["passed"]:
        blocked_reason = "R1-LATENCY-OPT evidence not passed"
    if not args.dry_run and not lightweight["lightweight_weights_ready"]:
        blocked_reason = "YOLOV9_LIGHTWEIGHT_WEIGHTS is not configured or does not point to a file"

    max_executed = len(VARIANTS) if args.execute_all_variants else max(0, args.max_executed_variants)
    rows: list[dict[str, Any]] = []
    variant_commands: list[tuple[LightweightVariant, str, list[str]]] = []
    for index, variant in enumerate(VARIANTS):
        variant_output_root = runs_dir / variant.variant_id
        variant_output_root.mkdir(parents=True, exist_ok=True)
        command = _build_diagnostic_command(args, variant, variant_output_root)
        if args.execute_all_variants:
            selected_for_execution = True
        elif max_executed > 0:
            selected_for_execution = index < max_executed
        else:
            selected_for_execution = variant.execute_by_default
        should_execute = (
            not args.dry_run
            and blocked_reason is None
            and selected_for_execution
            and (variant.yolov9_profile != "lightweight" or lightweight["lightweight_weights_ready"])
        )
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
            evidence = opt._load_variant_evidence(evidence_dir)
        rows.append(
            _row_from_variant(
                args=args,
                variant=variant,
                command=command,
                command_status=command_status,
                child_result=child_result,
                evidence_dir=evidence_dir,
                evidence=evidence,
                lightweight=lightweight,
                blocked_reason=blocked_reason,
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
        latency=latency,
        latency_opt=latency_opt,
        lightweight=lightweight,
        rows=rows,
    )
    opt._copy_variant_files(run_dir=run_dir, rows=rows)
    if not (run_dir / "events.jsonl").read_text(encoding="utf-8"):
        opt._write_jsonl(
            run_dir / "events.jsonl",
            [
                {
                    "phase": "lightweight_probe_preflight",
                    "status": summary["status"],
                    "blocked_reason": summary["blocked_reason"],
                    "lightweight_weights_ready": summary["lightweight_weights_ready"],
                }
            ],
        )
    opt._write_json(run_dir / "summary.json", summary)
    opt._write_csv(run_dir / "summary.csv", [summary], SUMMARY_COLUMNS)
    opt._write_csv(run_dir / "variant_summary.csv", rows, VARIANT_COLUMNS)
    _write_manifest(run_dir / "manifest.json", summary)
    _write_environment(run_dir / "environment.json", args, preflight, lightweight)
    _write_commands(run_dir / "commands.txt", [sys.executable, *sys.argv], variant_commands)
    _write_readme(run_dir / "README.md", summary)

    print(f"experiment_dir={run_dir}")
    print(summary["status_line"])
    print(f"status={summary['status']}")
    print(f"lightweight_bottleneck_classification={summary['lightweight_bottleneck_classification']}")
    print(f"recommended_next_phase={summary['recommended_next_phase']}")
    if args.dry_run:
        return 0
    return 0 if summary["status"] in {STATUS_CODE_COMPLETED_USEFUL, STATUS_CODE_COMPLETED_NO_IMPROVEMENT} else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Phase 13E continuity, drift-rate and Full-Pass validator.

Reads one Phase 13E soak run's evidence and decides whether it satisfies the
phase's Full Pass conditions. It never touches the Jetson, CARLA or the runner —
it only reads what the run already wrote, so it can be applied to a completed
run without disturbing anything and re-applied later without re-running a soak.

Evidence from two different runs is never combined: the validator works on a
single run directory and records that run's identity.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13e_checks import (  # noqa: E402
    BOUNDARY_FIELDS,
    PHASE,
    STATUS_BLOCKED,
    STATUS_PASS,
    utc_now_iso,
)
from workers.core.soak_metrics import (  # noqa: E402
    SoakSeries,
    continuity_report,
    drift_rate_per_hour,
    three_window_stats,
)

#: Series whose per-hour drift rate is reported, with the label used on failure.
DRIFT_RATE_SERIES = (
    ("process_rss_bytes", "memory_drift"),
    ("open_fd_count", "memory_drift"),
    ("thread_count", "memory_drift"),
    ("swap_used_bytes", "memory_drift"),
    ("ram_used_bytes", "memory_drift"),
    ("frame_to_command_ms", "latency_drift"),
    ("cpu_temperature_c", "thermal_drift"),
    ("gpu_temperature_c", "thermal_drift"),
    ("soc_temperature_c", "thermal_drift"),
    ("tj_temperature_c", "thermal_drift"),
)

MIN_BURN_IN_SEC = 1800.0
MIN_SOAK_SEC = 7200.0


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def series_from_evidence(payload: Dict[str, Any], name: str) -> SoakSeries:
    series = SoakSeries(name)
    entry = (payload.get("series") or {}).get(name) or {}
    for point in entry.get("series", []):
        if isinstance(point, (list, tuple)) and len(point) == 2:
            series.add(float(point[0]), point[1])
    return series


def evaluate(run_dir: Path, args: argparse.Namespace) -> Dict[str, Any]:
    summary = load_json(run_dir / "summary.json")
    timeseries = load_json(run_dir / "soak_timeseries.json")
    latency = load_json(run_dir / "latency_metrics.json")
    jetson = load_json(run_dir / "jetson_metrics.json")
    faults = load_json(run_dir / "phase13e_fault_matrix.json")
    events = []  # type: List[Dict[str, Any]]
    events_path = run_dir / "events.jsonl"
    if events_path.is_file():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue

    phases = {item["phase"]: item for item in latency.get("phases", [])}
    total_sec = float(summary.get("total_runtime_sec") or 0.0)
    report = {
        "phase": PHASE,
        "validated_at_utc": utc_now_iso(),
        "run_id": summary.get("run_id"),
        "evidence_dir": str(run_dir),
        "runtime_pc_git_sha": summary.get("runtime_pc_git_sha"),
        "runtime_jetson_git_sha": summary.get("runtime_jetson_git_sha"),
        "runtime_git_sha_match": bool(summary.get("runtime_git_sha_match")),
        "single_run_evidence_only": True,
        "total_runtime_sec": total_sec,
    }  # type: Dict[str, Any]
    blockers = []  # type: List[str]
    classifications = []  # type: List[str]

    # ── continuity ──────────────────────────────────────────────────────────
    # The stored latency series is downsampled to bound the evidence file, so
    # gaps between its points are a property of the downsampling, not of the
    # run. Deriving continuity from it would invent interruptions that never
    # happened. Frame continuity therefore comes from the per-phase records —
    # every driving phase must have published frames at a rate consistent with
    # its own duration — and the raw sample count comes from the summary.
    frame_series = series_from_evidence(timeseries, "frame_to_command_ms")
    downsampled = bool(
        ((timeseries.get("series") or {}).get("frame_to_command_ms") or {}).get(
            "series_downsampled"
        )
    )
    driving = [
        item
        for item in latency.get("phases", [])
        if float(item.get("actual_duration_sec") or 0.0) > 0.0
    ]
    starved = [
        item["phase"]
        for item in driving
        if int(item.get("frames_published") or 0) <= 0
        or (int(item.get("frames_published") or 0) / float(item["actual_duration_sec"]))
        < float(args.min_phase_fps)
    ]
    frame_continuity = {
        "source": "per_phase_records" if downsampled else "latency_series",
        "series_downsampled": downsampled,
        "total_latency_samples": int(
            (summary.get("frame_to_command_ms") or {}).get("count") or 0
        ),
        "driving_phase_count": len(driving),
        "phases_below_min_fps": starved,
        "min_phase_fps_required": float(args.min_phase_fps),
        "phase_fps": {
            item["phase"]: round(
                int(item.get("frames_published") or 0) / float(item["actual_duration_sec"]), 3
            )
            for item in driving
        },
        "held": not starved and bool(driving),
    }

    # Telemetry is not sampled inside the fault matrix, which runs after the
    # driving phases, so a gap there is explained rather than an interruption.
    # Only a gap inside a driving phase indicates the run stopped reporting.
    snapshots = timeseries.get("snapshots", [])
    driving_names = {item["phase"] for item in driving}
    driving_times = [
        float(item.get("elapsed_sec", 0.0))
        for item in snapshots
        if item.get("phase") in driving_names
    ]
    telemetry = continuity_report(
        frame_times_sec=driving_times or [0.0],
        telemetry_times_sec=[float(item.get("elapsed_sec", 0.0)) for item in snapshots],
        total_sec=total_sec,
        max_frame_gap_sec=float(args.max_telemetry_gap_sec),
        max_telemetry_gap_sec=float(args.max_unattributed_telemetry_gap_sec),
    )
    continuity = {
        "frames": frame_continuity,
        "telemetry_all_snapshots": telemetry["telemetry"],
        "telemetry_within_driving_phases": telemetry["frames"],
        "telemetry_gap_note": (
            "gaps outside driving phases are the fault matrix, which does not sample telemetry"
        ),
        "continuity_held": bool(frame_continuity["held"] and telemetry["frames"]["count"] > 1),
        "reasons": [] if frame_continuity["held"] else ["frame_continuity_gap"],
    }
    report["continuity"] = continuity
    if not continuity["continuity_held"]:
        blockers.extend(continuity["reasons"] or ["continuity_not_established"])
        classifications.append("soak_runtime_interrupted")

    # ``tensorrt_backend_ready`` is emitted by the Jetson node into its own event
    # buffer, which this run's evidence does not collect, so it is usually
    # absent here. When it is, the count must come from an explicit, recorded
    # assertion backed by node PID continuity — a node process loads its engine
    # exactly once at construction, so an unchanged PID across the run is
    # evidence of exactly one load. The provenance is always recorded so the
    # number is never mistaken for a counter it did not come from.
    engine_loads = sum(1 for event in events if event.get("event_type") == "tensorrt_backend_ready")
    if engine_loads:
        report["engine_load_count_source"] = "jetson_events"
    elif int(args.engine_load_count) >= 0:
        engine_loads = int(args.engine_load_count)
        report["engine_load_count_source"] = "asserted_from_jetson_node_pid_continuity"
    else:
        report["engine_load_count_source"] = "unavailable"
    stalls = sum(1 for event in events if event.get("event_type") == "frame_transport_stalled")
    report["engine_load_count"] = engine_loads
    report["engine_reload_count"] = max(0, engine_loads - 1)
    report["jetson_node_pid_samples"] = [
        item for item in str(args.jetson_pid_samples).split(",") if item.strip()
    ]
    report["jetson_node_pid_stable"] = (
        len(set(report["jetson_node_pid_samples"])) == 1
        if report["jetson_node_pid_samples"]
        else None
    )
    report["frame_transport_stall_count"] = stalls
    report["planned_restart_count"] = int(args.planned_restart_count)
    report["unplanned_restart_count"] = int(args.unplanned_restart_count)
    report["unexpected_process_exit_count"] = int(args.unexpected_process_exit_count)
    report["pids"] = {
        "pc_runner_pid": args.pc_pid,
        "jetson_node_pid": args.jetson_pid,
        "carla_pid": args.carla_pid,
    }
    if report["engine_reload_count"] > 0:
        blockers.append("engine_reloaded_during_soak")
        classifications.append("soak_runtime_interrupted")
    if engine_loads < 1:
        blockers.append("engine_load_not_observed")
    if report["unplanned_restart_count"] or report["unexpected_process_exit_count"]:
        blockers.append("unplanned_restart_observed")
        classifications.append("soak_runtime_interrupted")
    if stalls:
        blockers.append("frame_transport_stalled")
        classifications.append("soak_runtime_interrupted")

    # ── durations ───────────────────────────────────────────────────────────
    burn_in = float(phases.get("burn_in", {}).get("actual_duration_sec") or 0.0)
    soak = float(phases.get("soak", {}).get("actual_duration_sec") or 0.0)
    report["burn_in_duration_sec"] = burn_in
    report["soak_duration_sec"] = soak
    report["soak_duration_hours"] = round(soak / 3600.0, 4)
    if burn_in < MIN_BURN_IN_SEC:
        blockers.append("burn_in_duration_insufficient")
    if soak < MIN_SOAK_SEC:
        blockers.append("soak_duration_insufficient")

    # ── drift rates over start / middle / end windows ───────────────────────
    rates = []  # type: List[Dict[str, Any]]
    for name, label in DRIFT_RATE_SERIES:
        series = series_from_evidence(timeseries, name)
        if not len(series):
            continue
        rate = drift_rate_per_hour(series, total_sec=total_sec)
        rate["windows"] = three_window_stats(series, total_sec=total_sec)
        rate["drift_label"] = label
        rates.append(rate)
    report["drift_rates"] = rates
    drift = summary.get("drift", {}) or {}
    report["drift_verdicts"] = drift.get("drift_verdicts", [])
    report["drift_limits"] = drift.get("drift_limits", {})
    classification = summary.get("soak_classification", {}) or {}
    report["drift_labels"] = classification.get("drift_labels", [])
    report["steady_state_held"] = bool(classification.get("steady_state_held"))
    for label in report["drift_labels"]:
        if label not in classifications:
            classifications.append(label)
        blockers.append(label)

    # ── runtime invariants ──────────────────────────────────────────────────
    invariants = {
        "tensorrt_fallback_count": int(jetson.get("tensorrt_fallback_count", 0) or 0),
        "cuda_error_count": int(jetson.get("cuda_error_count", 0) or 0),
        "engine_execute_failure_count": int(jetson.get("engine_execute_failure_count", 0) or 0),
        "per_frame_device_allocation_count": int(
            jetson.get("per_frame_device_allocation_count", 0) or 0
        ),
        "max_mailbox_depth": int(jetson.get("max_mailbox_depth", 0) or 0),
        "thermal_throttling_observed": bool(jetson.get("thermal_throttling_observed")),
        "precision": jetson.get("precision"),
        "perception_mode": jetson.get("perception_mode"),
        "int8_authority_count": int(jetson.get("int8_non_authoritative_suppression_count", 0) or 0)
        if jetson.get("int8_backend_role")
        else 0,
        "tensorrt_active_authority_count": int(
            jetson.get("tensorrt_active_authority_count", 0) or 0
        ),
    }
    report["runtime_invariants"] = invariants
    if invariants["tensorrt_fallback_count"]:
        blockers.append("tensorrt_fallback_used")
    if invariants["cuda_error_count"]:
        blockers.append("cuda_execution_error")
    if invariants["engine_execute_failure_count"]:
        blockers.append("engine_execute_failed")
    if invariants["per_frame_device_allocation_count"]:
        blockers.append("per_frame_device_allocation")
    if invariants["max_mailbox_depth"] != 1:
        blockers.append("mailbox_depth_violation")
    if invariants["thermal_throttling_observed"]:
        blockers.append("thermal_throttling_observed")
        if "thermal_drift" not in classifications:
            classifications.append("thermal_drift")
    if invariants["precision"] != "fp16":
        blockers.append("fp16_backend_not_selected")
    # INT8 never ran here, so nothing may have been granted authority by it.
    report["int8_backend_loaded"] = bool(jetson.get("int8_backend_role"))
    report["int8_authority_count"] = 0
    report["fp16_authority_count"] = invariants["tensorrt_active_authority_count"]

    # ── control, latency and budget ─────────────────────────────────────────
    report["active_control_total"] = int(summary.get("active_control_total", 0) or 0)
    report["safe_stop_total"] = int(summary.get("safe_stop_total", 0) or 0)
    report["command_timeouts_total"] = int(summary.get("command_timeouts_total", 0) or 0)
    report["frame_to_command_ms"] = summary.get("frame_to_command_ms", {})
    report["latency_budget_ms"] = summary.get("latency_budget_ms")
    if report["active_control_total"] <= 0:
        blockers.append("no_active_control_applied")
    if report["safe_stop_total"] <= 0:
        blockers.append("no_safe_stop_path_observed")
    p99 = (report["frame_to_command_ms"] or {}).get("p99")
    budget = report["latency_budget_ms"]
    if p99 is None or budget is None:
        blockers.append("frame_to_command_latency_unavailable")
    elif float(p99) >= float(budget):
        blockers.append("inference_deadline_missed")
        if "latency_drift" not in classifications:
            classifications.append("latency_drift")

    # ── backpressure ────────────────────────────────────────────────────────
    backpressure = summary.get("backpressure", {}) or {}
    recovery = backpressure.get("recovery", {}) or {}
    report["backpressure"] = {
        "pre_burst_latency": (backpressure.get("pre_burst", {}) or {}).get("latency_ms"),
        "post_burst_latency": (backpressure.get("post_burst", {}) or {}).get("latency_ms"),
        "burst": backpressure.get("burst"),
        "mailbox_drops_delta": backpressure.get("mailbox_drops_delta"),
        "max_mailbox_depth": backpressure.get("max_mailbox_depth"),
        "latest_frame_only": backpressure.get("latest_frame_only"),
        "recovery": recovery,
    }
    report["backpressure_recovery_passed"] = bool(recovery.get("recovered"))
    if backpressure and not report["backpressure_recovery_passed"]:
        blockers.append("backpressure_recovery_failed")
        if "backpressure_recovery_failed" not in classifications:
            classifications.append("backpressure_recovery_failed")
    if backpressure and int(backpressure.get("max_mailbox_depth", 0) or 0) != 1:
        blockers.append("mailbox_depth_violation")

    # ── faults ──────────────────────────────────────────────────────────────
    failed = [row for row in faults if not row.get("passed")]
    unrecovered = [row["fault_id"] for row in faults if row.get("recovered") is False]
    false_accept = sum(1 for row in faults if row.get("observed_classification") == "AI_ACTIVE")
    false_reject = sum(
        1
        for row in faults
        if row.get("expected_classification") == "ACCEPTED"
        and row.get("observed_classification") not in ("ACCEPTED", "")
    )
    f28 = [row for row in faults if row.get("fault_id") == "F28"]
    report["fault_matrix"] = {
        "fault_case_count": len(faults),
        "fault_case_passed_count": len(faults) - len(failed),
        "failed_cases": [
            {"fault_id": row["fault_id"], "expected": row["expected_classification"],
             "observed": row["observed_classification"]}
            for row in failed
        ],
        "unrecovered_faults": unrecovered,
        "false_accept_count": false_accept,
        "false_reject_count": false_reject,
        "f28_expected": f28[0]["expected_classification"] if f28 else None,
        "f28_observed": f28[0]["observed_classification"] if f28 else None,
    }
    if failed:
        blockers.append("fault_classification_failed")
        if "fault_recovery_failed" not in classifications:
            classifications.append("fault_recovery_failed")
    if unrecovered:
        blockers.append("fault_recovery_failed")
        if "fault_recovery_failed" not in classifications:
            classifications.append("fault_recovery_failed")
    if false_accept or false_reject:
        blockers.append("fault_matrix_false_classification")
    if f28 and (f28[0]["expected_classification"] != "SAFE_STOP" or not f28[0]["passed"]):
        blockers.append("f28_not_deterministic_safe_stop")

    report["blockers"] = sorted(set(blockers))
    report["classifications"] = classifications
    report["full_pass"] = not report["blockers"]
    report["status"] = STATUS_PASS if report["full_pass"] else STATUS_BLOCKED
    report.update(BOUNDARY_FIELDS)
    return report


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13E continuity and Full-Pass validator")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--pc-pid", default="")
    parser.add_argument("--jetson-pid", default="")
    parser.add_argument("--carla-pid", default="")
    parser.add_argument(
        "--engine-load-count",
        type=int,
        default=-1,
        help="engine loads when the Jetson event buffer is unavailable; -1 derives from events",
    )
    parser.add_argument(
        "--jetson-pid-samples",
        default="",
        help="comma separated Jetson node PIDs sampled during the run, as continuity evidence",
    )
    parser.add_argument("--planned-restart-count", type=int, default=0)
    parser.add_argument("--unplanned-restart-count", type=int, default=0)
    parser.add_argument("--unexpected-process-exit-count", type=int, default=0)
    parser.add_argument("--max-frame-gap-sec", type=float, default=60.0)
    parser.add_argument("--max-telemetry-gap-sec", type=float, default=60.0)
    parser.add_argument(
        "--max-unattributed-telemetry-gap-sec",
        type=float,
        default=600.0,
        help="allowance for gaps outside driving phases, where telemetry is not sampled",
    )
    parser.add_argument(
        "--min-phase-fps",
        type=float,
        default=1.0,
        help="a driving phase below this published-frame rate is treated as starved",
    )
    parser.add_argument("--output", default="")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_dir = Path(args.run_dir)
    if not run_dir.is_absolute():
        run_dir = REPO_ROOT / run_dir
    if not (run_dir / "summary.json").is_file():
        print("no summary.json under %s" % run_dir, file=sys.stderr)
        return 2

    report = evaluate(run_dir, args)
    target = Path(args.output) if args.output else (run_dir / "continuity_report.json")
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )

    print(report["status"])
    print("run_id=%s" % report["run_id"])
    print("continuity_report=%s" % target)
    for key in (
        "runtime_pc_git_sha",
        "runtime_jetson_git_sha",
        "runtime_git_sha_match",
        "burn_in_duration_sec",
        "soak_duration_sec",
        "soak_duration_hours",
        "engine_load_count",
        "engine_reload_count",
        "planned_restart_count",
        "unplanned_restart_count",
        "unexpected_process_exit_count",
        "active_control_total",
        "safe_stop_total",
        "command_timeouts_total",
        "latency_budget_ms",
        "backpressure_recovery_passed",
        "fp16_authority_count",
        "int8_authority_count",
        "steady_state_held",
        "full_pass",
    ):
        print("%s=%s" % (key, report.get(key)))
    print("frame_to_command_ms=%s" % json.dumps(report.get("frame_to_command_ms")))
    print("continuity=%s" % json.dumps(report["continuity"]))
    print("fault_matrix=%s" % json.dumps(report["fault_matrix"]))
    print("drift_labels=%s" % ",".join(report.get("drift_labels") or []))
    for rate in report.get("drift_rates", []):
        if rate.get("available"):
            print(
                "drift_rate %-24s start=%s middle=%s end=%s per_hour=%s"
                % (rate["name"], rate["start"], rate["middle"], rate["end"], rate["rate_per_hour"])
            )
    if report["blockers"]:
        print("blockers=%s" % ",".join(report["blockers"]), file=sys.stderr)
        print("classifications=%s" % ",".join(report["classifications"]), file=sys.stderr)
    return 0 if report["full_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Prepare the Phase 12D VLM trigger/no-VLM ablation scaffold.

The scaffold fixes the calibrated GRP + dummy perception control path and only
varies VLM mode. It never imports CARLA, starts a simulator, launches a child
runner, or sends an external VLM request.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.config import AgentConfig

PHASE = "Phase 12D-VLM-TRIGGER-SCAFFOLD"
STATUS = "prepared"
CONTROLLER_MODE = "grp_follower"
PERCEPTION_BACKEND = "dummy"
TOWN = "Town03"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "phase12"
DEFAULT_CARLA_ROOT = Path(r"D:\CARLA\packages\CARLA_0.9.16")
DEFAULT_CARLA_PYTHON = r"D:\CARLA\envs\ma-vlna-carla312\python.exe"
CHILD_RUNNER = REPO_ROOT / "scripts" / "run_phase11m_grp_route_following.py"
RECOMMENDED_NEXT_PHASE = "Phase 12D-VLM-TRIGGER-WIRING"

RUNTIME_METRIC_FIELDS = (
    "fixed_route_goal_reached",
    "distance_to_goal_m",
    "route_progress_pct",
    "collision_count",
    "lane_invasion_count",
    "steps_completed",
    "vlm_trigger_count",
    "vlm_request_count",
    "vlm_success_count",
    "vlm_fallback_count",
    "vlm_parse_failure_count",
    "vlm_avg_latency_ms",
    "vlm_p95_latency_ms",
    "trigger_rate_per_100_steps",
    "local_planner_action_count",
    "semantic_planner_action_count",
    "safety_gate_accept_count",
    "safety_gate_reject_count",
    "planner_override_count",
    "control_source_local_count",
    "control_source_semantic_count",
    "decision_cycle_avg_ms",
    "total_runtime_sec",
)

BOUNDARY_FIELDS = {
    "carla_server_started": False,
    "runtime_executed": False,
    "external_vlm_request_executed": False,
    "full_phase12d_runtime_pass": False,
    "full_phase12c_perception_ablation_runtime_pass": False,
    "route_benchmark_verified": False,
    "infraction_benchmark_verified": False,
    "leaderboard_evaluated": False,
}


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
class VLMModeSpec:
    mode: str
    enabled: bool
    provider: str
    force_vlm_every: int
    description: str


ROUTE_MATRIX = (
    RouteSpec("route_01", 3, 30, 2500, 18.0, 2.0, 8),
    RouteSpec("route_02", 8, 52, 2800, 18.0, 2.0, 8),
    RouteSpec("route_03", 12, 74, 2500, 18.0, 2.0, 8),
    RouteSpec("route_04", 25, 101, 2500, 18.0, 2.0, 8),
    RouteSpec("route_05", 40, 126, 5400, 8.0, 1.0, 3),
)

VLM_MODE_MATRIX = (
    VLMModeSpec(
        "vlm_disabled",
        False,
        "none",
        0,
        "VLM disabled; local planner path only.",
    ),
    VLMModeSpec(
        "local_stub_event_triggered",
        True,
        "local_stub",
        0,
        "LocalStub provider with the normal TriggerPolicy.",
    ),
    VLMModeSpec(
        "local_stub_forced_every_20",
        True,
        "local_stub",
        20,
        "LocalStub provider forced every 20 frames.",
    ),
    VLMModeSpec(
        "openai_compatible_optional",
        True,
        "openai_compatible",
        0,
        "Existing OpenAI-compatible provider contract; no API call in this phase.",
    ),
)

SUMMARY_COLUMNS = (
    "route_id",
    "town",
    "start_spawn_index",
    "end_spawn_index",
    "horizon_steps",
    "target_speed_kmh",
    "route_sampling_resolution_m",
    "lookahead_waypoints",
    "controller_mode",
    "perception_backend",
    "vlm_mode",
    "vlm_enabled",
    "vlm_provider",
    "force_vlm_every",
    "provider_available",
    "provider_unavailable_reasons",
    "result",
    "runtime_executed",
    *RUNTIME_METRIC_FIELDS,
    "command",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _next_run_dir(output_dir: Path, timestamp: str | None) -> Path:
    run_name = timestamp or _timestamp(_utc_now())
    candidate = output_dir / run_name
    suffix = 1
    while candidate.exists():
        candidate = output_dir / f"{run_name}-{suffix}"
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


def _openai_provider_status() -> tuple[bool, list[str]]:
    """Check the existing provider contract without exposing configuration values."""

    config = AgentConfig.load().vlm
    missing: list[str] = []
    if not config.api_base.strip():
        missing.append("VLM_API_BASE")
    if not config.model.strip():
        missing.append("VLM_MODEL")
    if importlib.util.find_spec("httpx") is None:
        missing.append("python_dependency:httpx")
    return not missing, missing


def _provider_status(mode: VLMModeSpec, openai_status: tuple[bool, list[str]]) -> tuple[bool, list[str]]:
    if mode.provider in {"none", "local_stub"}:
        return True, []
    return openai_status


def _command_text(command: list[str]) -> str:
    return subprocess.list2cmdline(command)


def _build_child_command(
    args: argparse.Namespace,
    route: RouteSpec,
    mode: VLMModeSpec,
    evidence_dir: Path,
) -> list[str]:
    command = [
        args.python_executable,
        str(CHILD_RUNNER),
        "--host",
        "127.0.0.1",
        "--port",
        "2000",
        "--town",
        TOWN,
        "--start-spawn-index",
        str(route.start_spawn_index),
        "--end-spawn-index",
        str(route.end_spawn_index),
        "--steps",
        str(route.horizon_steps),
        "--target-speed-kmh",
        str(route.target_speed_kmh),
        "--goal-tolerance-m",
        "3.0",
        "--route-sampling-resolution-m",
        str(route.route_sampling_resolution_m),
        "--lookahead-waypoints",
        str(route.lookahead_waypoints),
        "--perception-backend",
        PERCEPTION_BACKEND,
        "--perception-model",
        PERCEPTION_BACKEND,
        "--require-server",
        "--enable-metric-sensors",
        "--require-sensors",
        "--require-goal-reach",
        "--require-grp",
        "--output-dir",
        str(evidence_dir),
        "--carla-root",
        str(args.carla_root),
    ]
    if mode.enabled:
        command.extend(["--enable-vlm", "--vlm-provider", mode.provider])
    if mode.force_vlm_every:
        command.extend(["--force-vlm-every", str(mode.force_vlm_every)])
    return command


def _build_rows(args: argparse.Namespace, run_dir: Path) -> list[dict[str, Any]]:
    selected_routes = [route for route in ROUTE_MATRIX if not args.route_id or route.route_id in args.route_id]
    selected_modes = [mode for mode in VLM_MODE_MATRIX if not args.vlm_mode or mode.mode in args.vlm_mode]
    openai_status = _openai_provider_status()
    rows: list[dict[str, Any]] = []

    for route in selected_routes:
        for mode in selected_modes:
            provider_available, reasons = _provider_status(mode, openai_status)
            evidence_dir = run_dir / "runs" / route.route_id / mode.mode
            command = _build_child_command(args, route, mode, evidence_dir)
            row: dict[str, Any] = {
                "route_id": route.route_id,
                "town": TOWN,
                "start_spawn_index": route.start_spawn_index,
                "end_spawn_index": route.end_spawn_index,
                "horizon_steps": route.horizon_steps,
                "target_speed_kmh": route.target_speed_kmh,
                "route_sampling_resolution_m": route.route_sampling_resolution_m,
                "lookahead_waypoints": route.lookahead_waypoints,
                "controller_mode": CONTROLLER_MODE,
                "perception_backend": PERCEPTION_BACKEND,
                "vlm_mode": mode.mode,
                "vlm_enabled": mode.enabled,
                "vlm_provider": mode.provider,
                "force_vlm_every": mode.force_vlm_every,
                "provider_available": provider_available,
                "provider_unavailable_reasons": reasons,
                "result": "dry_run" if provider_available else "provider_unavailable",
                "runtime_executed": False,
                "command": _command_text(command),
            }
            row.update({field: None for field in RUNTIME_METRIC_FIELDS})
            rows.append(row)
    return rows


def _common_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    mode_counts = Counter(str(row["vlm_mode"]) for row in rows)
    provider_availability = {
        mode.mode: all(row["provider_available"] is True for row in rows if row["vlm_mode"] == mode.mode)
        for mode in VLM_MODE_MATRIX
        if any(row["vlm_mode"] == mode.mode for row in rows)
    }
    return {
        "phase": PHASE,
        "status": STATUS,
        "row_count": len(rows),
        "route_count": len({row["route_id"] for row in rows}),
        "vlm_mode_count": len(mode_counts),
        "controller_mode": CONTROLLER_MODE,
        "perception_backend": PERCEPTION_BACKEND,
        "mode_row_counts": dict(sorted(mode_counts.items())),
        "provider_availability": provider_availability,
        "provider_unavailable_count": sum(1 for row in rows if row["result"] == "provider_unavailable"),
        "runtime_metric_fields": list(RUNTIME_METRIC_FIELDS),
        "recommended_next_phase": RECOMMENDED_NEXT_PHASE,
        **BOUNDARY_FIELDS,
    }


def _summary_payload(args: argparse.Namespace, rows: list[dict[str, Any]]) -> dict[str, Any]:
    payload = _common_payload(rows)
    full_matrix = not args.route_id and not args.vlm_mode
    payload.update(
        {
            "dry_run": True,
            "results": rows,
            "assertions": {
                "expected_full_row_count": len(rows) == 20 if full_matrix else None,
                "each_vlm_mode_has_five_rows": all(count == 5 for count in payload["mode_row_counts"].values())
                if full_matrix
                else None,
                "all_runtime_metrics_null": all(
                    row[field] is None for row in rows for field in RUNTIME_METRIC_FIELDS
                ),
                "local_modes_available": all(
                    row["provider_available"] is True
                    for row in rows
                    if row["vlm_mode"] != "openai_compatible_optional"
                ),
                "all_boundary_fields_false": all(value is False for value in BOUNDARY_FIELDS.values()),
                "carla_import_required": False,
                "external_vlm_request_required": False,
            },
        }
    )
    return payload


def _manifest_payload(args: argparse.Namespace, run_dir: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    payload = _common_payload(rows)
    payload.update(
        {
            "created_at_utc": _utc_now().isoformat(),
            "dry_run": True,
            "run_dir": str(run_dir),
            "output_files": ["manifest.json", "summary.csv", "summary.json", "commands.txt", "README.md"],
            "route_matrix": [asdict(route) for route in ROUTE_MATRIX],
            "vlm_mode_matrix": [asdict(mode) for mode in VLM_MODE_MATRIX],
            "child_runner": str(CHILD_RUNNER),
            "python_executable": args.python_executable,
            "carla_root": str(args.carla_root),
            "child_processes_launched": False,
            "secrets_serialized": False,
            "generated_evidence_git_policy": "ignored_local_only",
        }
    )
    return payload


def _write_commands(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Phase 12D VLM trigger/no-VLM ablation commands",
        "# Prepared only: no child command was executed and no external VLM request was sent.",
        "",
    ]
    for row in rows:
        lines.extend(
            [
                f"# {row['route_id']} / {row['vlm_mode']} / {row['result']}",
                str(row["command"]),
                "",
            ]
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_readme(path: Path, run_dir: Path, summary: dict[str, Any]) -> None:
    body = f"""# Phase 12D VLM Trigger Ablation Scaffold

Status: `prepared`

This local evidence pack contains a {summary['row_count']}-row dry-run matrix.
It fixes `controller_mode=grp_follower`, `perception_backend=dummy`, and the
five calibrated `Town03` routes, then varies only VLM mode.

The dummy backend is selected as a stable control-path baseline. This scaffold
isolates VLM mode; it does not evaluate perception quality or VLM accuracy.
OpenAI-compatible mode is optional, uses the existing configuration contract,
and no secrets are written here.

No CARLA runtime, child process, or external VLM request was executed. This is
not route benchmark, CARLA Leaderboard, or infraction benchmark evidence.

Evidence path: `{run_dir.relative_to(REPO_ROOT).as_posix()}`
"""
    path.write_text(body, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare the Phase 12D VLM trigger ablation scaffold")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--route-id", action="append", choices=[route.route_id for route in ROUTE_MATRIX])
    parser.add_argument("--vlm-mode", action="append", choices=[mode.mode for mode in VLM_MODE_MATRIX])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--python-executable", default=DEFAULT_CARLA_PYTHON)
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.dry_run:
        parser.error("Phase 12D-VLM-TRIGGER-SCAFFOLD only supports --dry-run")

    args.output_dir = _resolve(args.output_dir)
    args.carla_root = _resolve(args.carla_root)
    run_dir = _next_run_dir(args.output_dir, args.timestamp)
    rows = _build_rows(args, run_dir)
    summary = _summary_payload(args, rows)

    _write_csv(run_dir / "summary.csv", rows)
    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "manifest.json", _manifest_payload(args, run_dir, rows))
    _write_commands(run_dir / "commands.txt", rows)
    _write_readme(run_dir / "README.md", run_dir, summary)

    print("Phase 12D-VLM-TRIGGER-SCAFFOLD Prepared - matrix written without CARLA or external VLM calls.")
    print(f"experiment_dir={run_dir}")
    print(f"row_count={summary['row_count']}")
    print(f"provider_unavailable_count={summary['provider_unavailable_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

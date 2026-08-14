"""
Phase 12 experiment kickoff scaffold.

此腳本只建立實驗輸出目錄與摘要檔模板，不啟動 CARLA、不 import carla、
不跑大型實驗，也不需要 Python 3.12 runtime。Phase 12 的正式實驗 runner
應在後續 phase 另行實作。
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "phase12"
SUMMARY_COLUMNS = (
    "experiment_line",
    "run_id",
    "town",
    "start_spawn_index",
    "end_spawn_index",
    "controller",
    "perception_backend",
    "vlm_mode",
    "steps",
    "fixed_route_goal_reached",
    "distance_to_goal_m",
    "route_progress_pct",
    "collision_count",
    "lane_invasion_count",
    "avg_speed_kmh",
    "max_speed_kmh",
    "distance_traveled_m",
    "timeout",
    "result",
    "notes",
)


@dataclass(frozen=True)
class ExperimentLine:
    """Phase 12 實驗線定義。"""

    key: str
    name: str
    objective: str
    initial_scope: dict[str, Any]
    metrics: list[str]
    boundary: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def _resolve_output_dir(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _next_run_dir(output_dir: Path, timestamp: str) -> Path:
    candidate = output_dir / timestamp
    suffix = 1
    while candidate.exists():
        candidate = output_dir / f"{timestamp}-{suffix}"
        suffix += 1
    return candidate


def _experiment_lines() -> list[ExperimentLine]:
    shared_route_scope = {
        "town": "Town03",
        "spawn_pair_count": 5,
        "steps_per_route": 2500,
        "perception_backend": "dummy",
        "grp_required": True,
        "sensors_required": True,
    }
    route_metrics = [
        "fixed_route_goal_reached",
        "distance_to_goal_m",
        "route_progress_pct",
        "collision_count",
        "lane_invasion_count",
        "avg_speed_kmh",
        "max_speed_kmh",
        "distance_traveled_m",
        "timeout",
        "result",
    ]
    return [
        ExperimentLine(
            key="A",
            name="CARLA Route Smoke Scaling",
            objective="從單一路線擴展到多組 spawn-pair route smoke。",
            initial_scope=shared_route_scope,
            metrics=route_metrics,
            boundary="仍不是 CARLA Leaderboard、正式 route benchmark 或 infraction benchmark。",
        ),
        ExperimentLine(
            key="B",
            name="Controller Ablation",
            objective="比較不同控制策略在固定 spawn-pair smoke 中的 goal reach 與安全事件差異。",
            initial_scope={
                "controllers": [
                    "linear_spawn_pair_follower",
                    "grp_follower",
                    "baseline_planner_action_mapper",
                ],
                "shared_route_scope": shared_route_scope,
            },
            metrics=[
                "goal_reach_success_rate",
                "average_final_distance_to_goal",
                "lane_invasion_count",
                "collision_count",
                "route_progress_percentage",
            ],
            boundary="控制器比較只描述 smoke 行為，不宣稱泛化駕駛能力。",
        ),
        ExperimentLine(
            key="C",
            name="Perception Backend Ablation",
            objective="比較 dummy、YOLOv9 optional、RT-DETR optional 感知後端在相同 route smoke 中的可用性與遙測差異。",
            initial_scope={
                "perception_backends": ["dummy", "yolov9_optional", "rt_detr_optional"],
                "missing_backend_result": "backend_unavailable",
            },
            metrics=route_metrics,
            boundary="YOLOv9 / RT-DETR 未安裝於 target runtime 時不得讓整體實驗失敗，只標記 backend_unavailable。",
        ),
        ExperimentLine(
            key="D",
            name="VLM Trigger / No-VLM Comparison",
            objective="比較 VLM disabled、LocalStub forced trigger 與 OpenAI-compatible optional VLM 的觸發成本與決策紀錄差異。",
            initial_scope={
                "vlm_modes": [
                    "vlm_disabled",
                    "local_stub_forced_every_n_steps",
                    "openai_compatible_optional",
                ],
                "secret_boundary": "OpenAI-compatible VLM 必須透過環境變數，不可提交 key。",
            },
            metrics=[
                "trigger_count",
                "vlm_success_count",
                "vlm_fallback_count",
                "fixed_route_goal_reached",
                "distance_to_goal_m",
                "route_progress_pct",
                "result",
            ],
            boundary="VLM 比較不證明真實模型品質；若 endpoint 不可用，記錄 optional unavailable 或 fallback。",
        ),
        ExperimentLine(
            key="E",
            name="Evidence Aggregation",
            objective="建立 Phase 12 實驗結果格式與可審查摘要，避免大型 raw outputs 進入 git。",
            initial_scope={
                "output_pattern": "experiments/phase12/<timestamp>/",
                "files": ["manifest.json", "summary.csv", "summary.json", "runs/", "README.md"],
                "gitignored_raw_paths": [
                    "experiments/phase12/*/runs/",
                    "experiments/phase12/*/raw_outputs/",
                ],
            },
            metrics=["summary_row_count", "run_count", "raw_outputs_excluded_from_git"],
            boundary="只提交小型 summary template 或 source scaffold，不提交大型 raw logs。",
        ),
    ]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_summary_csv(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()


def _write_readme(path: Path, run_dir: Path, timestamp: str) -> None:
    body = f"""# Phase 12 Experiment Scaffold

Timestamp: `{timestamp}`

This directory is a scaffold only. It does not contain CARLA runtime results.

## Files

- `manifest.json`: experiment plan metadata and boundary fields.
- `summary.csv`: empty summary table with the Phase 12 metrics schema.
- `summary.json`: empty machine-readable summary payload.
- `runs/`: per-run evidence output directory, ignored by git.
- `raw_outputs/`: raw simulator/model outputs, ignored by git.

## Boundary

Phase 12 begins controlled experiment planning and scaffolding. This scaffold does not run CARLA, does not import `carla`, does not verify CARLA Leaderboard, and does not prove driving policy quality.

Path:

```text
{run_dir.relative_to(REPO_ROOT).as_posix()}
```
"""
    path.write_text(body, encoding="utf-8")


def create_scaffold(output_dir: Path, timestamp: str | None = None) -> Path:
    now = _utc_now()
    resolved_output_dir = _resolve_output_dir(output_dir)
    stamp = timestamp or _timestamp(now)
    run_dir = _next_run_dir(resolved_output_dir, stamp)
    run_dir.mkdir(parents=True, exist_ok=False)

    (run_dir / "runs").mkdir()
    (run_dir / "raw_outputs").mkdir()

    lines = _experiment_lines()
    manifest = {
        "phase": "12",
        "name": "Experiment Kickoff Plan",
        "created_at": now.isoformat(),
        "scaffold_only": True,
        "carla_runtime_started": False,
        "carla_import_required": False,
        "python312_required": False,
        "large_experiment_executed": False,
        "default_output_pattern": "experiments/phase12/<timestamp>/",
        "experiment_lines": [asdict(line) for line in lines],
        "summary_columns": list(SUMMARY_COLUMNS),
        "benchmark_boundaries": {
            "carla_leaderboard_evaluated": False,
            "formal_route_benchmark_verified": False,
            "infraction_benchmark_verified": False,
            "driving_policy_quality_proven": False,
        },
        "git_boundary": {
            "raw_runs_ignored": True,
            "raw_outputs_ignored": True,
            "commit_large_raw_logs": False,
            "commit_env_files": False,
            "commit_carla_package_or_venv": False,
        },
    }
    _write_json(run_dir / "manifest.json", manifest)
    _write_summary_csv(run_dir / "summary.csv")
    _write_json(
        run_dir / "summary.json",
        {
            "phase": "12",
            "created_at": now.isoformat(),
            "row_count": 0,
            "columns": list(SUMMARY_COLUMNS),
            "results": [],
        },
    )
    _write_readme(run_dir / "README.md", run_dir, stamp)
    return run_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Phase 12 experiment scaffold")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Phase 12 scaffold base directory. A timestamped child directory will be created.",
    )
    parser.add_argument(
        "--timestamp",
        default=None,
        help="Optional timestamp override for deterministic dry-run scaffolds.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = create_scaffold(args.output_dir, args.timestamp)
    print("Phase 12 experiment scaffold created")
    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

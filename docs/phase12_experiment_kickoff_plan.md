# Phase 12 — Experiment Kickoff Plan

## Status

```text
Phase 12 Experiment Kickoff Pass — experiment planning and scaffold created without running large experiments.
```

Phase 12 不是繼續包裝，也不是再做 release。Phase 12 開始進入受控實驗設計與可重跑的實驗輸出格式。Phase 11 仍是 CARLA runtime verification、evidence pack、release artifact boundary 與 source commit boundary 的基礎。

## Boundary

Phase 12 kickoff 只建立計畫與 scaffold：

- 不啟動 CARLA server。
- 不 import `carla`。
- 不需要 Python 3.12。
- 不執行大型實驗。
- 不提交 `.env*`、CARLA package、Python venv、runtime logs 或大型 raw outputs。
- 不宣稱 CARLA Leaderboard、正式 route benchmark、infraction benchmark 或 driving policy quality。

## Experiment Line A — CARLA Route Smoke Scaling

目標：從單一路線擴展到多組 spawn-pair route smoke。

初始設定：

- Town: `Town03`
- Spawn pair: 5 組
- Steps: 每組 `2500`
- Perception backend: `dummy`
- GRP required: true
- Sensors required: true

輸出 metrics：

- `fixed_route_goal_reached`
- `distance_to_goal_m`
- `route_progress_pct`
- `collision_count`
- `lane_invasion_count`
- `avg_speed_kmh`
- `max_speed_kmh`
- `distance_traveled_m`
- `timeout`
- `result`

注意：這仍不是 CARLA Leaderboard，也不是正式 route benchmark。

Phase 12A implementation:

```text
scripts/run_phase12a_route_scaling_experiment.py
docs/phase12a_carla_route_scaling_experiment.md
```

Phase 12A 使用固定 5 組 `Town03` spawn-pair route，逐條呼叫 Phase 11M GRP runner，並把每條 route 的 `metrics.json` 聚合成 `summary.csv` 與 `summary.json`。Batch runner 採 continue-all policy；若任一路線失敗，仍跑完其餘路線後輸出 `Phase 12A Route Scaling Blocked`。

## Experiment Line B — Controller Ablation

比較：

```text
linear spawn-pair follower
GRP follower
baseline PlannerAction mapper
```

輸出：

- `goal_reach_success_rate`
- `average_final_distance_to_goal`
- `lane_invasion_count`
- `collision_count`
- `route_progress_percentage`

此線只比較 fixed spawn-pair smoke 行為，不宣稱泛化駕駛能力。

## Experiment Line C — Perception Backend Ablation

比較：

```text
dummy
YOLO optional
RT-DETR optional
```

若 YOLO / RT-DETR 未安裝，不讓整體實驗失敗，該 backend 的 run 標記為：

```text
backend_unavailable
```

## Experiment Line D — VLM Trigger / No-VLM Comparison

比較：

```text
VLM disabled
LocalStub VLM forced every N steps
OpenAI-compatible VLM optional
```

OpenAI-compatible VLM 必須透過環境變數設定，不可提交 API key、endpoint secret 或任何 `.env*` 檔案。

## Experiment Line E — Evidence Aggregation

每次實驗輸出：

```text
experiments/phase12/<timestamp>/
  manifest.json
  summary.csv
  summary.json
  runs/
  raw_outputs/
  README.md
```

`.gitignore` 必須排除：

```text
experiments/phase12/*/runs/
experiments/phase12/*/raw_outputs/
experiments/phase12/*/
```

只允許提交小型 summary template 或 source scaffold，不提交大型 raw logs、影像、CARLA recorder、VLM raw responses 或 simulator dump。

## Scaffold Command

```powershell
python scripts\run_phase12_experiment_plan.py --output-dir experiments\phase12
```

預期輸出：

```text
Phase 12 experiment scaffold created
```

## Validation

```powershell
python -m py_compile scripts\run_phase12_experiment_plan.py
python scripts\run_phase12_experiment_plan.py --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
```

通過條件：

- `py_compile` passed
- scaffold created
- Phase 11 checks 6/6 passed
- demo checks 6/6 passed

## Next Implementation Slice

Phase 12 後續應先實作輕量 orchestrator，讀取 route matrix 與 backend/controller/VLM mode matrix，逐 run 呼叫既有 Phase 11K/11L/11M runner。正式 CARLA runtime 仍應留在 dedicated Python 3.12 + CARLA 0.9.16 environment，不加入 baseline requirements。

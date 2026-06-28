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

Latest Phase 12A real runtime evidence:

```text
experiments\phase12\20260619T113705Z
passed_count=4
blocked_or_failed_count=1
all_routes_passed=false
```

Latest Phase 12A-R05 recovery evidence:

```text
experiments\phase12\20260620T110904Z
recovery_attempt_count=4
recovered_count=0
recovery_passed=false
best_observed_variant=r05_slow_short_lookahead
best_observed_route_progress_pct=71.067782
best_observed_distance_to_goal_m=99.482140
```

Latest Phase 12A-R05B waypoint progression diagnosis:

```text
experiments\phase12\20260620T115855Z
source_waypoint_progression_status=progressing_step_budget_limited
extended_goal_reached=true
extended_steps_requested=5200
goal_reach_step=4431
distance_to_goal_m=2.950533
route_progress_pct=100.0
grp_route_progress_pct=99.559155
```

Latest Phase 12A-H horizon calibration:

```text
experiments\phase12\20260620T140648Z
calibrated_route_count=5
all_routes_calibrated=true
recommended_horizon_by_route={"route_01":2500,"route_02":2800,"route_03":2500,"route_04":2500,"route_05":5400}
max_recommended_horizon_steps=5400
```

Latest Phase 12A-C calibrated route confirmation:

```text
experiments\phase12\20260621T074706Z
confirmed_route_count=5
all_routes_confirmed=true
route_01_goal_reach_step=2073
route_02_goal_reach_step=2264
route_03_goal_reach_step=1567
route_04_goal_reach_step=1320
route_05_goal_reach_step=4431
```

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

## Phase 12B Addendum - Controller Ablation Scaffold

```text
Phase 12B Controller Ablation Prepared - controller ablation matrix, dry-run scaffold, and summary aggregation are implemented.
```

Implementation:

```text
scripts/run_phase12b_controller_ablation_experiment.py
docs/phase12b_controller_ablation_experiment.md
```

Dry-run command:

```powershell
python scripts\run_phase12b_controller_ablation_experiment.py --dry-run --output-dir experiments\phase12
```

Prepared matrix:

```text
row_count=15
route_count=5
controller_count=3
controllers=linear_spawn_pair_follower,grp_follower,baseline_planner_action_mapper
runtime_scope=dry_run_scaffold_only
```

Boundary:

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

## Phase 12B-R Addendum - Controller Ablation Runtime Wiring

```text
Phase 12B-R Controller Ablation Runtime Wiring Prepared - execute-runtime child process wiring, blocked evidence handling, and summary aggregation are implemented.
```

Implementation:

```text
scripts/run_phase12b_controller_ablation_experiment.py
docs/phase12b_r_controller_ablation_runtime_wiring.md
```

Runtime wiring smoke:

```powershell
python scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --route-id route_01 --controller-mode linear_spawn_pair_follower --runtime-row-limit 1 --child-timeout-sec 120 --python-executable python --output-dir experiments\phase12
```

Local blocked evidence:

```text
experiments\phase12\20260627T131052Z
row_count=1
executed_row_count=1
result=blocked
metrics_read_status=loaded
boundary_fields_false=true
```

## Phase 12B-GRP Addendum - GRP Controller Ablation Runtime Pass

```text
Phase 12B-GRP GRP Controller Ablation Runtime Pass - all five calibrated Town03 routes passed with the grp_follower controller.
```

Implementation:

```text
scripts/run_phase12b_controller_ablation_experiment.py
docs/phase12b_grp_controller_ablation_runtime_pass.md
```

Runtime evidence:

```text
experiments\phase12\20260628T065257Z
row_count=5
executed_row_count=5
passed_count=5
all_runtime_rows_passed=true
controller_mode=grp_follower
```

Per-route goal reach:

```text
route_01_goal_reach_step=2073
route_02_goal_reach_step=2264
route_03_goal_reach_step=1567
route_04_goal_reach_step=1320
route_05_goal_reach_step=4431
all_collision_count=0
```

Boundary:

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

## Phase 12B-LIN Addendum - Linear Spawn-Pair Controller Runtime Pass / Blocked Evidence

```text
Phase 12B-LIN Linear Spawn-Pair Controller Runtime Pass - all five calibrated Town03 routes passed the linear spawn-pair route-progress smoke gate after CARLA warm-up.
```

Implementation:

```text
scripts/run_phase12b_controller_ablation_experiment.py
docs/phase12b_lin_controller_ablation_runtime_pass.md
```

Initial blocked evidence:

```text
experiments\phase12\20260628T074345Z
row_count=5
passed_count=4
failed_count=1
route_01=carla_load_world_timeout_before_setup
```

Warm-up retry evidence:

```text
experiments\phase12\20260628T080731Z
row_count=5
executed_row_count=5
passed_count=5
all_runtime_rows_passed=true
controller_mode=linear_spawn_pair_follower
```

Important interpretation:

```text
linear_scope=route_progress_smoke_only
fixed_route_goal_reach_not_verified=true
infraction_safe_not_verified=true
routes_02_to_05_collision_counts_high=true
```

## Phase 12B-BASE-M Addendum - Baseline PlannerAction Mapper Route-Metric Wiring

```text
Phase 12B-BASE-M Baseline PlannerAction Mapper Route-Metric Wiring Prepared - the baseline mapper controller row now emits structured fixed-route metrics through a dedicated child runner.
```

Implementation:

```text
scripts/run_phase12b_baseline_mapper_route_metrics.py
scripts/run_phase12b_controller_ablation_experiment.py
docs/phase12b_base_m_planner_action_mapper_route_metrics.md
```

Local blocked wiring evidence:

```text
experiments\phase12\20260628T091432Z
controller_mode=baseline_planner_action_mapper
row_count=1
result=blocked
metrics_read_status=loaded
route_fields_present=true
server_reachable=false
route_progress_verified=false
```

Important interpretation:

```text
baseline_mapper_route_metrics_wired=true
baseline_runtime_pass_not_verified=true
planner_action_mapper_modified=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
```

## Phase 12B-BASE Addendum - Baseline PlannerAction Mapper Runtime Evidence

```text
Phase 12B-BASE Runtime Evidence Blocked - all five baseline PlannerAction mapper rows executed in real CARLA, but every row failed the fixed spawn-pair route-progress gate.
```

Runtime evidence:

```text
initial_batch=experiments\phase12\20260628T120210Z
route_01_retry=experiments\phase12\20260628T121819Z
final_batch=experiments\phase12\20260628T122108Z
row_count=5
executed_row_count=5
passed_count=0
blocked_count=5
failed_count=0
all_runtime_rows_passed=false
```

Final row interpretation:

```text
all_rows_baseline=true
all_metrics_loaded=true
all_route_progress_blocked=true
all_rows_control_applied=true
all_rows_rgb_frame_received=true
all_route_progress_m=0.0
baseline_runtime_pass_not_verified=true
```

Boundary:

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

## Next Implementation Slice

Phase 12 後續應先實作輕量 orchestrator，讀取 route matrix 與 backend/controller/VLM mode matrix，逐 run 呼叫既有 Phase 11K/11L/11M runner。正式 CARLA runtime 仍應留在 dedicated Python 3.12 + CARLA 0.9.16 environment，不加入 baseline requirements。

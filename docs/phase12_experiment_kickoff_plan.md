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
YOLOv9 optional
RT-DETR optional
```

若 YOLOv9 / RT-DETR optional dependency 未安裝於 target runtime，不讓整體實驗失敗，該 backend 的 run 標記為：

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

## Phase 12B-SUM Addendum - Controller Ablation Comparative Summary

```text
Phase 12B-SUM Controller Ablation Comparative Summary Prepared - GRP, linear, and baseline mapper evidence has been normalized into comparable controller and route tables.
```

Generated summary:

```text
experiments\phase12\20260628T125344Z
controller_summary.csv
route_comparison.csv
summary.json
manifest.json
README.md
```

Controller comparison:

```text
grp_follower=5/5 goal-reach smoke pass, total_collision_count=0
linear_spawn_pair_follower=5/5 route-progress smoke pass, total_collision_count=15222, not completion
baseline_planner_action_mapper=0/5 pass, 5/5 route-progress blocked, closed-loop executable
```

Comparative conclusion:

```text
strongest_controller=grp_follower
linear_scope=route_progress_smoke_only_not_completion
baseline_scope=closed_loop_executable_but_route_progress_blocked
all_controller_runtime_pass=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
```

## Phase 12C Addendum - Perception Backend Ablation Prepared

```text
Phase 12C Perception Backend Ablation Prepared - backend matrix, optional dependency preflight, and command scaffold are implemented.
```

Generated scaffold:

```text
experiments\phase12\20260629T070603Z
manifest.json
summary.csv
summary.json
commands.txt
README.md
```

Matrix:

```text
routes=5 calibrated Town03 spawn-pair routes
controller_mode=grp_follower
perception_backend_modes=dummy,yolov9_optional,rt_detr_optional
row_count=15
historical_available_row_count=5
historical_backend_unavailable_count=10
latest_yolov9_rows_refresh_dir=experiments\phase12\20260630T060823Z
phase12c_yolov9_rows_available=true
backend_unavailable_count=0
```

本機目前在 target CARLA Python 3.12 runtime 中已完成 YOLOv9 source adapter no-fallback verification，因此 YOLOv9 optional rows 現在是 available / command-ready。這不是 full Phase 12C perception ablation runtime pass；它只代表 scaffold command readiness。RT-DETR optional rows 仍取決於 `ultralytics` dependency，未在本次驗證中宣稱 runtime pass。YOLOv9 preflight 使用 `--python-executable` 指向的 target runtime。

Boundary:

```text
carla_import_required=false
carla_server_required=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

## Phase 12C-DUMMY Addendum - Dummy Backend Runtime Confirmation

```text
Phase 12C-DUMMY Runtime Confirmation Pass - dummy backend rows confirmed in real CARLA runtime.
```

Generated runtime evidence:

```text
experiments\phase12\20260628T173019Z
child_experiment_dir=experiments\phase12\20260628T173019Z\runs\20260628T173021Z
```

Runtime scope:

```text
controller_mode=grp_follower
perception_backend=dummy
routes=5 calibrated Town03 spawn-pair routes
row_count=5
passed_count=5
blocked_count=0
failed_count=0
collision_count_total=0
lane_invasion_count_total=83
```

Assertions:

```text
all_rows_goal_reached=true
all_rows_runtime_passed=true
phase12b_all_runtime_rows_passed=true
all_boundary_fields_false=true
carla_imported_by_wrapper=false
raw_runtime_evidence_committed=false
```

Boundary:

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

`lane_invasion_count_total=83` 是 sensor metric record，不是 infraction benchmark score。Phase 12C-DUMMY 只確認 dummy backend 在 calibrated smoke runtime 中可完成五條 route。

## Phase 12C-YOLOv9-U Addendum - YOLOv9 Optional Dependency Unlock Prepared

```text
Phase 12C-YOLOv9-U Prepared — YOLOv9 optional dependency unlock commands and evidence were written.
```

Generated unlock-preparation evidence:

```text
experiments\phase12\20260629T063232Z
```

Preflight status:

```text
dependency_ready=false
dependency_missing=true
manual_unlock_required=true
target_python_exists=true
carla_root_exists=true
yolov9_import_ready=false
yolov9_pip_metadata_ready=false
edge_yolov9_command_supported=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=true
auto_install_performed=false
baseline_requirements_modified=false
runtime_confirmation_executed=false
```

Manual unlock commands:

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install <YOLOV9_PACKAGE_SPEC>
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install -r <YOLOV9_REQUIREMENTS_PATH>
```

Post-unlock condition:

```text
yolov9_import_ready=true
yolov9_pip_metadata_ready=true
edge_yolov9_command_supported=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
```

Boundary:

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Phase 12C-YOLO-U 是早期 generic YOLO unlock preparation 歷史紀錄；Phase 12C-YOLOv9-U 是修訂後的 YOLOv9-specific target。舊 evidence 不會被改寫成 YOLOv9 evidence。

Phase 12C-YOLOv9-U 只準備 dependency unlock；它沒有自動安裝 dependencies，也沒有執行 YOLOv9 runtime confirmation。

## Phase 12C-YOLOv9-B Addendum - EdgePerception YOLOv9 Backend Adapter Prepared

```text
Phase 12C-YOLOv9-B Prepared — EdgePerception YOLOv9 backend adapter path is registered.
```

Generated adapter evidence:

```text
experiments\phase12\20260629T063232Z-1-1
```

Adapter status:

```text
adapter_prepared=true
edge_yolov9_backend_registered=true
base_edge_yolov9_command_supported=true
carla312_edge_yolov9_command_supported=true
base_edge_yolov9_command_passed=true
carla312_edge_yolov9_command_passed=true
base_edge_yolov9_fallback_used=true
carla312_edge_yolov9_fallback_used=true
dependency_ready=false
dependency_missing=true
runtime_confirmation_executed=false
```

Phase 12C-YOLOv9-B 只證明 EdgePerception 已有 `backend=yolov9` / `--test yolov9` adapter path；缺少 YOLOv9 dependency 時仍保留 graceful fallback。它沒有啟動 CARLA，也沒有執行 YOLOv9 runtime confirmation。

## Phase 12C-YOLOv9-V Addendum - YOLOv9 Post-Unlock Verification

```text
Phase 12C-YOLOv9-SRC-V Passed — official YOLOv9 source adapter verified with no fallback in the CARLA Python 3.12 runtime.
```

Generated post-unlock verification evidence:

```text
source_adapter_verified_evidence_dir=experiments\phase12\20260630T060621Z
post_unlock_external_source_verified_dir=experiments\phase12\20260630T061015Z
```

Verification status:

```text
authoritative_evidence_dir=experiments\phase12\20260630T061015Z
post_unlock_verification_attempted=true
post_unlock_verified=true
require_verified_requested=true
strict_gate_exit_code=0
target_python_exists=true
carla_root_exists=true
yolov9_import_ready=false
yolov9_pip_metadata_ready=false
source_adapter_verified=true
YOLOV9_ROOT_configured=true
YOLOV9_WEIGHTS_configured=true
yolov9_source_root_ready=true
yolov9_weights_ready=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
phase12b_yolov9_dry_run_command_ready=true
phase11m_yolov9_cli_ready=true
phase11k_yolov9_cli_ready=true
phase12b_baseline_yolov9_cli_ready=true
phase12c_yolov9_rows_available=true
phase12c_yolov9_backend_unavailable_count=0
backend_unavailable_count=0
auto_install_performed=false
baseline_requirements_modified=false
carla_server_started=false
runtime_confirmation_executed=false
carla_route_runtime_executed=false
```

Phase 12C-YOLOv9-V also verifies that the runner command path accepts `--perception-backend yolov9` for Phase 12B / Phase 11M / Phase 11K / baseline mapper. This is command wiring and source-adapter no-fallback readiness only; it is not YOLOv9 runtime route validation.

## Next Implementation Slice

## Phase 12C-YOLOv9-SRC Addendum - Official YOLOv9 Source Adapter Prepared

```text
Phase 12C-YOLOv9-SRC-V Passed — official YOLOv9 source adapter verified with no fallback in the CARLA Python 3.12 runtime.
```

Phase 12C-YOLOv9-SRC 將官方 YOLOv9 路徑從 package-only readiness 改為 external source-root readiness。operator 必須提供：

```text
YOLOV9_ROOT=<path to official YOLOv9 source repository>
YOLOV9_WEIGHTS=<path to selected YOLOv9 weights>
```

Local source-adapter evidence:

```text
source_adapter_verified_evidence_dir=experiments\phase12\20260630T060621Z
yolov9_rows_refresh_dir=experiments\phase12\20260630T060823Z
post_unlock_external_source_verified_dir=experiments\phase12\20260630T061015Z
source_adapter_verified=true
YOLOV9_ROOT_configured=true
YOLOV9_WEIGHTS_configured=true
yolov9_source_root_ready=true
yolov9_weights_ready=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
post_unlock_verified=true
phase12c_yolov9_rows_available=true
backend_unavailable_count=0
runtime_confirmation_executed=false
carla_route_runtime_executed=false
auto_install_performed=false
baseline_requirements_modified=false
carla_server_started=false
```

Manual operator setup example:

```powershell
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install -r "$env:YOLOV9_ROOT\requirements.txt"
python scripts\run_phase12c_yolov9_source_adapter_verification.py --output-dir experiments\phase12 --require-verified
python scripts\run_phase12c_perception_backend_ablation.py --perception-backend-mode yolov9_optional --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --output-dir experiments\phase12
```

YOLOv9 source repo and weights are not committed, not vendored, and not packaged into MA-VLNA. This source-adapter slice remains no-fallback verification only; it does not start CARLA and does not claim YOLOv9 accuracy, CARLA Leaderboard, formal route benchmark, or infraction benchmark. The follow-up R1 selected-row runtime attempt is recorded below as blocked.

## Next Implementation Slice

## Phase 12C-YOLOv9-R1 Addendum - Selected YOLOv9 Runtime Confirmation

```text
Phase 12C-YOLOv9-R1 Runtime Confirmation Blocked - selected YOLOv9 backend row did not complete or did not satisfy the selected runtime smoke gate.
```

Phase 12C-YOLOv9-R1 是 source adapter no-fallback 通過後的單一路線 formal runtime attempt。R1-RERUN 已在 reachable CARLA server 下重跑同一條 selected row。它只選定：

```text
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
runtime_scope=selected_single_route
```

Latest formal runtime evidence:

```text
runtime_evidence_dir=experiments\phase12\20260630T134322Z
previous_blocked_evidence_dir=experiments\phase12\20260630T094645Z
carla_server_reachable=true
source_adapter_verified=true
post_unlock_verified=true
phase12c_yolov9_rows_available=true
backend_unavailable_count=0
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
runtime_confirmation_executed=true
carla_route_runtime_executed=true
row_count=1
executed_row_count=1
blocked_count=1
child_summary_status=controller_ablation_runtime_blocked
child_row_result=timeout
child_inner_exit_code=124
child_duration_sec=2400.311
goal_reached=null
distance_to_goal_m=null
route_progress_pct=null
collision_count=null
lane_invasion_count=null
metrics_read_status=loaded
```

## Phase 12C-YOLOv9-R1-DIAG Addendum - Runtime Timeout Diagnosis

```text
Phase 12C-YOLOv9-R1-DIAG Diagnostic Completed - bounded diagnostic evidence was produced without claiming runtime pass.
```

Phase 12C-YOLOv9-R1-DIAG adds selected-row timeout breadcrumbs on top of the R1-RERUN blocked evidence:

```text
diagnostic_evidence_dir=experiments\phase12\20260630T150500Z
dry_run_evidence_dir=experiments\phase12\20260630T150101Z
previous_runtime_evidence_dir=experiments\phase12\20260630T134322Z
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
timeout_classification=map_load_or_spawn_stall
diagnosis_confidence=high
diagnostic_steps_completed=0
heartbeat_count=0
world_tick_count=0
rgb_frame_received_count=0
edge_perception_call_count=0
yolov9_inference_call_count=0
yolo_runtime_row_verified=false
full_phase12c_perception_ablation_runtime_pass=false
```

The selected YOLOv9 row remains blocked, not passed. The diagnosis shows the run failed after YOLOv9 model-load completion and CARLA setup start, before CARLA setup finish, world ticks, RGB frames, heartbeat, or route metrics.

## Phase 12C-YOLOv9-R1-SETUP Addendum - Setup Recovery Probe

```text
Phase 12C-YOLOv9-R1-SETUP Probe Pass - selected route setup reached map ready, ego spawn, RGB sensor attach, first RGB frame, GRP route generation, and warm-up ticks.
```

Phase 12C-YOLOv9-R1-SETUP isolates the setup path that R1-DIAG classified as `map_load_or_spawn_stall`:

```text
setup_evidence_dir=experiments\phase12\20260701T045047Z
parent_wrapper=scripts\run_phase12c_yolov9_r1_setup_recovery.py
child_probe=scripts\run_phase12c_carla_setup_spawn_probe.py
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
target_town=Town03
start_spawn_index=3
end_spawn_index=30
map_load_mode=reuse_or_load
setup_scope=map_load_spawn_rgb_grp_warmup_only
town_ready=true
ego_spawned=true
rgb_sensor_attached=true
first_rgb_frame_received=true
grp_route_generated=true
warmup_ticks_completed=20
setup_probe_passed=true
setup_blocker_classification=setup_probe_passed
runtime_confirmation_executed=false
carla_route_runtime_executed=false
yolo_runtime_row_verified=false
full_phase12c_perception_ablation_runtime_pass=false
```

This phase is setup recovery only. It is not YOLOv9 runtime pass, not model accuracy evidence, not full Phase 12C ablation, and not Leaderboard / formal route / infraction benchmark evidence.

## Phase 12C-YOLOv9-R1-SHORT Addendum - Selected Route-Begin Probe

```text
Phase 12C-YOLOv9-R1-SHORT Route-Begin Probe Pass - selected YOLOv9 row entered the closed-loop route loop and produced bounded early runtime evidence with no fallback.
```

R1-SHORT uses the same selected row after R1-SETUP:

```text
short_route_begin_evidence_dir=experiments\phase12\20260701T064944Z
setup_evidence_dir=experiments\phase12\20260701T045047Z
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
diagnostic_steps_requested=50
diagnostic_steps_completed=50
heartbeat_count=11
world_tick_count=50
rgb_frame_received_count=50
edge_perception_call_count=50
yolov9_inference_call_count=11
edge_yolov9_fallback_used_during_route=false
partial_route_progress_seen=true
short_route_begin_verified=true
short_route_begin_blocker_classification=short_route_begin_verified
```

R1-SHORT is route-begin evidence only. It verifies early closed-loop route-loop breadcrumbs and no-fallback YOLOv9 inference calls; it does not claim route completion, YOLOv9 selected route runtime pass, model accuracy, full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark.

## Phase 12C-YOLOv9-R1-LATENCY Addendum - Route-Loop Latency and Cadence Probe

```text
Phase 12C-YOLOv9-R1-LATENCY Completed - selected YOLOv9 route-loop latency and cadence evidence produced without claiming route completion.
```

R1-LATENCY profiles the same selected row after R1-SHORT:

```text
latency_evidence_dir=experiments\phase12\20260701T103721Z
short_route_begin_evidence_dir=experiments\phase12\20260701T064944Z
variant_count=4
executed_variant_count=2
completed_variant_count=1
blocked_variant_count=1
best_variant_id=variant_01_current_cadence
best_variant_effective_fps=0.239313
baseline_current_cadence_yolov9_avg_ms=2522.06
latency_bottleneck_classification=yolov9_forward_dominant
recommended_next_phase=R1-LATENCY-OPT
```

The current cadence variant completed bounded profiling and shows YOLOv9 model-forward latency dominates route-loop speed. The stride-5 cached variant did not produce a valid route-loop profile in this run. Therefore the recommended next phase is latency optimization, not route completion or full ablation.

## Phase 12C-YOLOv9-R1-LATENCY-OPT Addendum - Forward-Latency Optimization Probe

```text
Phase 12C-YOLOv9-R1-LATENCY-OPT No-Improvement - optimization probe completed, but YOLOv9 forward latency remains too high for route completion.
```

R1-LATENCY-OPT profiles diagnostic-only optimization variants after R1-LATENCY identified YOLOv9 model-forward as the bottleneck:

```text
latency_opt_evidence_dir=experiments\phase12\20260701T115744Z
executed_variant_count=4
completed_variant_count=2
blocked_variant_count=2
best_variant_id=variant_01_baseline_recheck
best_variant_effective_fps=0.168392
best_variant_yolov9_avg_ms=2194.8
best_avg_ms_improvement_pct=12.976
best_fps_improvement_pct=-29.635
useful_latency_improvement_verified=false
recommended_next_phase=R1-YOLOv9-LIGHTWEIGHT
```

Image-size, half precision, forward-only profiling, stride, and cached perception behavior remain diagnostic-only unless a later phase promotes them. This phase does not claim route completion, YOLOv9 model accuracy, full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark.

R1 wrapper 已驗證 YOLOv9 source/weights 與 EdgePerception no-fallback readiness。R1-RERUN 已確認 `127.0.0.1:2000` 可達，並啟動 Phase 12B / Phase 11M child runtime；但 child 在 `2400.311s` 後 timeout，沒有產生 route metrics 或 goal-reach evidence。

詳細記錄請見 [phase12c_yolov9_runtime_confirmation.md](phase12c_yolov9_runtime_confirmation.md)。

Phase 12C-YOLOv9-R1 不代表 full Phase 12C perception ablation runtime pass，不代表 YOLOv9 accuracy，不代表 RT-DETR runtime verification，也不代表 CARLA Leaderboard、formal route benchmark 或 infraction benchmark。RT-DETR optional dependency unlock 仍應保持手動/顯式，不加入 baseline requirements，也不自動安裝套件。

## Phase 12C-YOLOv9-R1-YOLOv9-LIGHTWEIGHT Addendum

R1-YOLOv9-LIGHTWEIGHT produced blocked evidence at `experiments\phase12\20260701T165325Z`. Baseline no-fallback readiness remained true, but `YOLOV9_LIGHTWEIGHT_WEIGHTS` was not configured, so no lightweight route-loop timing profile was executed.

`lightweight_bottleneck_classification=lightweight_weights_missing`, `useful_lightweight_profile_verified=false`, and `recommended_next_phase=R1-RT-DETR-UNLOCK`. This phase does not download or commit YOLOv9 assets and does not claim route completion, model accuracy, full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark.

## Phase 12C-R1-RT-DETR-UNLOCK Addendum

After R1-YOLOv9-LIGHTWEIGHT ended blocked because no lightweight YOLOv9 weights were configured, Phase 12C moved to a separate RT-DETR optional backend readiness branch. Evidence `experiments\phase12\20260702T022636Z-1` records `ultralytics_import_ready=false`, `rtdetr_weights_configured=false`, `rtdetr_weights_ready=false`, `edge_rtdetr_command_supported=true`, `edge_rtdetr_command_passed=true`, `edge_rtdetr_fallback_used=true`, `edge_rtdetr_no_fallback_verified=false`, `phase12c_rtdetr_rows_available=false`, and `phase12c_rtdetr_backend_unavailable_count=5`.

The recommended next phase is `R1-RT-DETR-ASSET-SETUP`. This branch does not start CARLA route runtime, does not verify RT-DETR accuracy, does not claim RT-DETR runtime pass, and does not claim full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark.

## Phase 12C-R1-RT-DETR-ASSET-SETUP Addendum

Phase 12C-R1-RT-DETR-ASSET-SETUP produced command-ready evidence at `experiments\phase12\20260702T040554Z`. The wrapper writes explicit commands for the target CARLA Python 3.12 runtime, dependency install, local asset directory preparation, `RTDETR_WEIGHTS`, post-setup EdgePerception smoke, and optional RT-DETR-only row refresh.

```text
status=command_ready
ultralytics_import_ready_before=false
ultralytics_import_ready_after=false
dependency_install_requested=false
dependency_install_executed=false
rtdetr_weights_configured=false
rtdetr_weights_ready=false
edge_rtdetr_command_passed=null
edge_rtdetr_fallback_used=null
edge_rtdetr_no_fallback_verified=false
phase12c_rtdetr_rows_available=false
recommended_next_phase=R1-RT-DETR-ASSET-SETUP
```

This setup gate remains dependency/local asset setup only. It does not silently install dependencies, download or commit RT-DETR weights, modify baseline requirements, start CARLA route runtime, verify RT-DETR accuracy, claim RT-DETR runtime pass, or claim full Phase 12C ablation / Leaderboard / formal route / infraction benchmark evidence.

## Phase 12C-R1-RT-DETR-ASSET-EXEC Addendum

Phase 12C-R1-RT-DETR-ASSET-EXEC produced blocked evidence at `experiments\phase12\20260702T044516Z`. The explicit install was operator-requested and targeted only `D:\CARLA\envs\ma-vlna-carla312\python.exe`.

```text
status=blocked
ultralytics_import_ready_before=false
ultralytics_import_ready_after=true
ultralytics_version_after=8.4.84
dependency_install_requested=true
dependency_install_executed=true
dependency_install_exit_code=0
rtdetr_weights_configured=true
rtdetr_weights_ready=false
post_setup_smoke_executed=false
edge_rtdetr_command_passed=null
edge_rtdetr_fallback_used=null
edge_rtdetr_no_fallback_verified=false
phase12c_rtdetr_rows_available=false
recommended_next_phase=R1-RT-DETR-ASSET-SETUP
```

The dependency setup step succeeded, but RT-DETR remains blocked by missing local weights. No weights were downloaded or committed, baseline requirements were not modified, no CARLA route runtime was started, and no RT-DETR runtime pass / accuracy / full Phase 12C ablation / benchmark result is claimed.

## Phase 12C-R1-RT-DETR-WEIGHTS-LOCAL Addendum

Phase 12C-R1-RT-DETR-WEIGHTS-LOCAL-RERUN produced blocked evidence at `experiments\phase12\20260702T125105Z`. This gate verifies only the local operator-provided weight path and no-fallback smoke readiness.

```text
status=blocked
ultralytics_import_ready_after=true
ultralytics_version_after=8.4.84
rtdetr_weights_configured=true
rtdetr_weights_ready=false
rtdetr_weights_path=D:\AIModels\rtdetr\rtdetr-l.pt
missing_weight_path=D:\AIModels\rtdetr\rtdetr-l.pt
post_setup_smoke_executed=false
edge_rtdetr_command_passed=null
edge_rtdetr_fallback_used=null
edge_rtdetr_no_fallback_verified=false
phase12c_rtdetr_rows_available=false
recommended_next_phase=R1-RT-DETR-ASSET-SETUP
```

The target runtime dependency is ready, but local RT-DETR weights remain missing. No weights were downloaded or committed, no smoke was run, no CARLA route runtime was started, and no RT-DETR no-fallback / route / accuracy / benchmark result is claimed.

## Phase 12C-R1-RT-DETR-ASSET-BLOCKER-FREEZE Addendum

Phase 12C-R1-RT-DETR-ASSET-BLOCKER-FREEZE completed the docs-only branch freeze. The RT-DETR dependency side is ready after ASSET-EXEC, but local weights remain missing at `D:\AIModels\rtdetr\rtdetr-l.pt`, so the branch is frozen as an external asset blocker.

```text
Phase 12C-R1-RT-DETR-ASSET-BLOCKER-FREEZE Completed
rt_detr_branch_frozen_external_asset_blocker=true
rtdetr_dependency_ready=true
rtdetr_weights_ready=false
rtdetr_no_fallback_ready=false
phase12c_rtdetr_rows_available=false
recommended_next_phase_without_weights=Phase 12C-SUM
recommended_next_phase_if_weights_available=R1-RT-DETR-WEIGHTS-LOCAL-RERUN
post_setup_smoke_executed=false
carla_route_runtime_executed=false
rtdetr_runtime_verified=false
rtdetr_accuracy_verified=false
```

Phase 12C-SUM handoff:

| backend | status | key evidence | claim | boundary |
| --- | --- | --- | --- | --- |
| `dummy` | `runtime_confirmed` | `experiments\phase12\20260628T173019Z` | 5/5 calibrated dummy backend smoke rows reached goal | Not infraction benchmark, not Leaderboard |
| `yolov9` | `route_begin_and_latency_profiled_but_not_route_completion` | source adapter `experiments\phase12\20260630T060621Z`; setup `experiments\phase12\20260701T045047Z`; short route-begin `experiments\phase12\20260701T064944Z`; latency `experiments\phase12\20260701T103721Z`; latency opt `experiments\phase12\20260701T115744Z`; lightweight blocked `experiments\phase12\20260701T165325Z` | No-fallback source adapter verified, selected route loop entered, latency bottleneck characterized | No route completion, no model accuracy, no full ablation pass |
| `rtdetr` | `external_asset_blocked` | unlock `experiments\phase12\20260702T022636Z-1`; asset setup `experiments\phase12\20260702T040554Z`; asset exec `experiments\phase12\20260702T044516Z`; weights-local rerun `experiments\phase12\20260702T125105Z` | Dependency installed, local weights missing | No no-fallback readiness, no runtime, no accuracy |

## Phase 12C-SUM Addendum

```text
Phase 12C-SUM Completed
dummy_backend_runtime_confirmed=true
yolov9_route_begin_and_latency_profiled=true
yolov9_route_completion_verified=false
rtdetr_external_asset_blocked=true
rtdetr_no_fallback_ready=false
full_phase12c_perception_ablation_runtime_pass=false
recommended_next_phase=Phase 12D-VLM-TRIGGER-SCAFFOLD_OR_FINAL_REPORT_FREEZE
```

Phase 12C-SUM normalizes existing evidence into `docs/phase12c_perception_backend_ablation_summary.md` and `docs/phase12c_perception_backend_ablation_summary.json`. It is summary-only: it does not start CARLA, execute route runtime, run YOLOv9 route completion, run RT-DETR smoke, install dependencies, download weights, create fake weights, modify baseline requirements, or upgrade blocked/partial statuses into runtime passes.

## Phase 12C-YOLOv9-R1 Formal Gate Addendum

Phase 12C-YOLOv9-R1 was rerun as the selected single-route runtime confirmation gate. Evidence `experiments\phase12\20260713T190904Z` records `source_adapter_verified=true`, `edge_yolov9_fallback_used=false`, `edge_yolov9_no_fallback_verified=true`, `phase12c_yolov9_rows_available=true`, `backend_unavailable_count=0`, and `carla_server_reachable=true`. The existing Phase 12B -> Phase 11M child path executed, but Town03_Opt load exceeded the 60-second CARLA client setup timeout before route ticks: `runtime_confirmation_executed=true`, `carla_route_runtime_executed=true`, `child_row_result=grp_blocked`, `steps_completed=0`, `metrics_read_status=loaded`, and `yolo_runtime_row_verified=false`. The dry-run command evidence is `experiments\phase12\20260713T190811Z`.

This is the selected YOLOv9 runtime confirmation boundary only. It does not claim full Phase 12C perception ablation runtime pass, YOLOv9 model accuracy, RT-DETR runtime verification, CARLA Leaderboard, formal route benchmark, or infraction benchmark.

## Phase 12D-VLM-TRIGGER-SCAFFOLD Addendum

```text
Phase 12D-VLM-TRIGGER-SCAFFOLD Prepared
row_count=20
route_count=5
vlm_mode_count=4
controller_mode=grp_follower
perception_backend=dummy
carla_server_started=false
runtime_executed=false
external_vlm_request_executed=false
full_phase12d_runtime_pass=false
full_phase12c_perception_ablation_runtime_pass=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
recommended_next_phase=Phase 12D-VLM-TRIGGER-WIRING
```

Phase 12D fixes the calibrated Phase 12A-C route/controller/perception path and varies only `vlm_disabled`, `local_stub_event_triggered`, `local_stub_forced_every_20`, and `openai_compatible_optional`. Dummy is selected solely as the stable control-path baseline; this is not a perception-quality comparison. The OpenAI-compatible rows use the existing `VLM_API_BASE`, `VLM_MODEL`, and `VLM_API_KEY` contract, remain optional, and become `provider_unavailable` when configuration is absent. No secret values are written.

The scaffold writes `manifest.json`, `summary.csv`, `summary.json`, `commands.txt`, and `README.md` under ignored local experiment storage. Every runtime aggregation metric remains `null`. No CARLA child command or external API request ran, so this phase is not VLM accuracy, route benchmark, Leaderboard, or infraction benchmark evidence.

## Phase 13A Embedded Contract SIL Handoff

Phase 13A adds a separate embedded safety-contract verification line without
changing Phase 12D scaffold or experiment results.

```text
Phase 13A-EMBEDDED-CONTRACT-SIL Pass
protocol_version=1
packet_size_bytes=64
host_sil_tests=28/28
portable_c_ctest=1/1 passed
evidence_dir=experiments\phase13\20260808T065044Z
```

The host vertical slice connects Dummy EdgePerception, the existing SafetyGate,
a new range-shift authority monitor, a bounded binary command bridge, and a
Safety MCU software emulator. The portable C reference uses no dynamic
allocation and validates the same CRC, time, sequence, lease, control, range,
heartbeat, and FSM contract.

This handoff is host SIL only. It does not promote Phase 12D to runtime pass and
does not claim real MCU, HIL, actuator control, CARLA benchmark, model accuracy,
or OTA/security validation. Phase 13 generated evidence remains local and
ignored.

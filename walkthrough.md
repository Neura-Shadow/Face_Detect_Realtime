# Walkthrough - Phase 12B-BASE Baseline PlannerAction Mapper Runtime Evidence

1. Start from Phase 12B-BASE-M route-metric wiring.
2. Start external CARLA 0.9.16 server from `D:\CARLA\packages\CARLA_0.9.16`.
3. Verify Python 3.12 CARLA runtime readiness with Phase 11D `--require-ready`.
4. Run Phase 12B runtime execution filtered to `baseline_planner_action_mapper`.
5. Preserve initial blocked evidence if CARLA map load fails.
6. Retry route_01 after warm-up if the first failure is a simulator warm-up timeout.
7. Rerun the full five-route baseline subset after CARLA is warm.
8. Read every child `metrics.json`.
9. Assert closed-loop runtime fields: ego spawn, RGB frame, world tick, control, and sensors.
10. Assert fixed-route outcome fields: route progress, distance to goal, and boundary flags.
11. Keep generated evidence under `experiments\phase12` and out of git.
12. Stop CARLA and verify no CARLA process remains.

Current result:

```text
Phase 12B-BASE Runtime Evidence Blocked - all five baseline PlannerAction mapper rows executed in real CARLA, but every row failed the fixed spawn-pair route-progress gate.
```

Runtime command:

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --controller-mode baseline_planner_action_mapper --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --child-timeout-sec 2400 --output-dir experiments\phase12
```

Initial full batch:

```text
experiments\phase12\20260628T120210Z
row_count=5
executed_row_count=5
passed_count=0
blocked_count=4
failed_count=1
route_01=load_world_timeout_before_setup
routes_02_to_05=route_progress_blocked
```

Route 01 warm-up retry:

```text
experiments\phase12\20260628T121819Z
result=route_progress_blocked
steps_completed=2500
route_progress_verified=false
```

Final full batch:

```text
experiments\phase12\20260628T122108Z
row_count=5
executed_row_count=5
passed_count=0
blocked_count=5
failed_count=0
all_runtime_rows_passed=false
all_rows_baseline=true
all_metrics_loaded=true
all_route_progress_blocked=true
```

Per-route final result:

```text
route_01: route_progress_m=0.000000, distance_to_goal_m=307.662099, collision_count=0
route_02: route_progress_m=0.000000, distance_to_goal_m=415.869352, collision_count=0
route_03: route_progress_m=0.000000, distance_to_goal_m=183.052607, collision_count=0
route_04: route_progress_m=0.000000, distance_to_goal_m=178.796136, collision_count=0
route_05: route_progress_m=0.000000, distance_to_goal_m=335.484571, collision_count=0
```

Closed-loop fields verified on every final row:

```text
ego_spawned=true
control_applied=true
rgb_frame_received=true
world_tick_advanced=true
collision_sensor_attached=true
lane_invasion_sensor_attached=true
```

Boundary fields:

```text
benchmark_boundary_prepared=true
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Validation checklist:

```text
python -m py_compile scripts\run_phase12b_baseline_mapper_route_metrics.py scripts\run_phase12b_controller_ablation_experiment.py scripts\run_phase11_carla_checks.py
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

Phase 12B-BASE is negative runtime evidence. It proves the baseline mapper can execute closed-loop CARLA control and telemetry, but not fixed-route progress.

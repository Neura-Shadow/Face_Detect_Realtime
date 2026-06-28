# Walkthrough - Phase 12B-GRP GRP Controller Ablation Runtime Pass

1. Preserve Phase 12B-R runtime wiring.
2. Start external CARLA 0.9.16 server from `D:\CARLA\packages\CARLA_0.9.16`.
3. Verify Python 3.12 CARLA runtime readiness with Phase 11D `--require-ready`.
4. Run Phase 12B runtime execution filtered to `grp_follower`.
5. Execute the five calibrated Town03 routes:
   - `route_01`: `3 -> 30`, horizon `2500`
   - `route_02`: `8 -> 52`, horizon `2800`
   - `route_03`: `12 -> 74`, horizon `2500`
   - `route_04`: `25 -> 101`, horizon `2500`
   - `route_05`: `40 -> 126`, horizon `5400`
6. Require every requested row to pass.
7. Read every child `metrics.json`.
8. Assert fixed route goal reach and GRP route following for every row.
9. Keep generated evidence under `experiments\phase12` and out of git.
10. Stop CARLA and verify no CARLA process remains.

Current result:

```text
Phase 12B-GRP GRP Controller Ablation Runtime Pass - all five calibrated Town03 routes passed with the grp_follower controller.
```

Runtime command:

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --controller-mode grp_follower --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --child-timeout-sec 2400 --output-dir experiments\phase12
```

Evidence:

```text
experiments\phase12\20260628T065257Z
row_count=5
executed_row_count=5
passed_count=5
all_runtime_rows_passed=true
all_rows_grp=true
all_child_metrics_verified=true
boundary_fields_false=true
```

Per-route result:

```text
route_01: goal_reach_step=2073, distance_to_goal_m=2.284790, collision_count=0
route_02: goal_reach_step=2264, distance_to_goal_m=2.316571, collision_count=0
route_03: goal_reach_step=1567, distance_to_goal_m=2.374137, collision_count=0
route_04: goal_reach_step=1320, distance_to_goal_m=2.443187, collision_count=0
route_05: goal_reach_step=4431, distance_to_goal_m=2.952668, collision_count=0
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
python -m py_compile scripts\run_phase12b_controller_ablation_experiment.py
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

Phase 12B-GRP is not an all-controller ablation pass. It validates only the GRP-backed controller subset.

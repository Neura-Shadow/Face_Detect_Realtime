# Walkthrough - Phase 12B-LIN Linear Spawn-Pair Controller Runtime Pass / Blocked Evidence

1. Preserve Phase 12B-R runtime wiring.
2. Start external CARLA 0.9.16 server from `D:\CARLA\packages\CARLA_0.9.16`.
3. Verify Python 3.12 CARLA runtime readiness with Phase 11D `--require-ready`.
4. Run Phase 12B runtime execution filtered to `linear_spawn_pair_follower`.
5. Preserve the initial 5-row blocked batch if CARLA startup or map load fails.
6. If the first failure is transient CARLA warm-up rather than controller logic, retry after the world is ready.
7. Rerun the full five-route linear subset after warm-up.
8. Read every child `metrics.json`.
9. Assert route-progress smoke fields for every final pass row.
10. Record collision counts explicitly because this is not an infraction-safe pass.
11. Keep generated evidence under `experiments\phase12` and out of git.
12. Stop CARLA and verify no CARLA process remains.

Current result:

```text
Phase 12B-LIN Linear Spawn-Pair Controller Runtime Pass - all five calibrated Town03 routes passed the linear spawn-pair route-progress smoke gate after CARLA warm-up.
```

Runtime command:

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --controller-mode linear_spawn_pair_follower --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --child-timeout-sec 2400 --output-dir experiments\phase12
```

Initial blocked evidence:

```text
experiments\phase12\20260628T074345Z
row_count=5
passed_count=4
failed_count=1
route_01=carla_load_world_timeout_before_setup
```

Warm-up retry:

```text
experiments\phase12\20260628T080432Z
route_01=passed
```

Final pass evidence:

```text
experiments\phase12\20260628T080731Z
row_count=5
executed_row_count=5
passed_count=5
all_runtime_rows_passed=true
all_rows_linear=true
all_child_metrics_verified=true
boundary_fields_false=true
```

Per-route final result:

```text
route_01: route_progress_m=307.662099, distance_to_goal_m=6.914185, collision_count=0
route_02: route_progress_m=24.236822, distance_to_goal_m=391.652049, collision_count=2677
route_03: route_progress_m=10.515416, distance_to_goal_m=172.609764, collision_count=2428
route_04: route_progress_m=6.983494, distance_to_goal_m=171.816015, collision_count=2439
route_05: route_progress_m=10.109821, distance_to_goal_m=325.427040, collision_count=7678
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

Phase 12B-LIN is not a fixed-route goal-reach completion pass and not an infraction-safe controller pass.

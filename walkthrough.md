# Walkthrough - Phase 12C-DUMMY Dummy Backend Runtime Confirmation

1. Use Phase 12C scaffold as the perception backend matrix boundary.
2. Select only `perception_backend=dummy`.
3. Keep `controller_mode=grp_follower`, because Phase 12B-SUM identified it as the strongest fixed-route smoke controller.
4. Preserve the calibrated 5-route `Town03` matrix.
5. Start or verify the external CARLA 0.9.16 server.
6. Run 11D `--require-ready` from the dedicated Python 3.12 CARLA environment.
7. Run the 12C-DUMMY confirmation wrapper.
8. Let the wrapper delegate to Phase 12B runtime execution with `grp_follower + dummy`.
9. Read the child Phase 12B `summary.json`.
10. Mark 12C-DUMMY passed only when all requested dummy rows reach goal and all boundary fields remain false.

Runtime command:

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_dummy_runtime_confirmation.py --host 127.0.0.1 --port 2000 --output-dir experiments\phase12 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --child-timeout-sec 2400 --parent-timeout-sec 14400
```

Generated evidence:

```text
experiments\phase12\20260628T173019Z
child_experiment_dir=experiments\phase12\20260628T173019Z\runs\20260628T173021Z
```

Aggregate result:

```text
status=dummy_runtime_confirmed
row_count=5
passed_count=5
blocked_count=0
failed_count=0
collision_count_total=0
lane_invasion_count_total=83
all_dummy_routes_confirmed=true
```

Per-route result:

```text
route_01: passed, distance_to_goal_m=2.284790, collision_count=0, lane_invasion_count=27
route_02: passed, distance_to_goal_m=2.316571, collision_count=0, lane_invasion_count=28
route_03: passed, distance_to_goal_m=2.374137, collision_count=0, lane_invasion_count=10
route_04: passed, distance_to_goal_m=2.443187, collision_count=0, lane_invasion_count=10
route_05: passed, distance_to_goal_m=2.952668, collision_count=0, lane_invasion_count=8
```

Boundary fields:

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Validation checklist:

```text
python -m py_compile scripts\run_phase12c_dummy_runtime_confirmation.py
python scripts\run_phase12c_dummy_runtime_confirmation.py --dry-run --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

Phase 12C-DUMMY confirms the dummy backend runtime path only. It does not validate YOLO / RT-DETR and does not upgrade MA-VLNA to a formal CARLA benchmark.

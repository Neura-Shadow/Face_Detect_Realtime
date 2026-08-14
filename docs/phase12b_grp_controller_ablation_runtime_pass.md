# Phase 12B-GRP - GRP Controller Ablation Runtime Pass

## Status

```text
Phase 12B-GRP GRP Controller Ablation Runtime Pass - all five calibrated Town03 routes passed with the grp_follower controller.
```

Phase 12B-GRP is a controller-ablation subset runtime pass. It validates only
the `grp_follower` controller rows from the Phase 12B matrix. It does not claim
that `linear_spawn_pair_follower` or `baseline_planner_action_mapper` passed,
and it is not CARLA Leaderboard, not a formal route benchmark, and not an
infraction benchmark.

## Command

CARLA server was started from the external CARLA 0.9.16 package, then the 11D
ready gate was verified:

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11d_carla_provisioning_gate.py --carla-root D:\CARLA\packages\CARLA_0.9.16 --host 127.0.0.1 --port 2000 --steps 5 --require-ready
```

The GRP-only controller ablation runtime command was:

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --controller-mode grp_follower --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --child-timeout-sec 2400 --output-dir experiments\phase12
```

## Evidence

```text
experiments\phase12\20260628T065257Z
row_count=5
executed_row_count=5
passed_count=5
all_runtime_rows_passed=true
all_rows_grp=true
boundary_fields_false=true
```

Per-route result:

| route_id | goal_reach_step | distance_to_goal_m | collision_count | lane_invasion_count | grp_route_following_verified |
| --- | ---: | ---: | ---: | ---: | --- |
| `route_01` | 2073 | 2.284790 | 0 | 27 | true |
| `route_02` | 2264 | 2.316571 | 0 | 28 | true |
| `route_03` | 1567 | 2.374137 | 0 | 10 | true |
| `route_04` | 1320 | 2.443187 | 0 | 10 | true |
| `route_05` | 4431 | 2.952668 | 0 | 8 | true |

Required child evidence assertions passed for every row:

```text
result=passed
exit_code=0
controller_mode=grp_follower
metrics_read_status=loaded
fixed_route_goal_reached=true
fixed_route_completion_verified=true
grp_route_following_verified=true
grp_fallback_used=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
```

## Boundary

These fields remain false:

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Phase 12B-GRP does not claim:

- CARLA Leaderboard passed
- formal route benchmark passed
- infraction benchmark passed
- all controller modes passed
- `linear_spawn_pair_follower` runtime pass
- `baseline_planner_action_mapper` runtime pass
- real YOLO / RT-DETR verified
- real OpenAI-compatible VLM verified
- general driving policy quality proven

## Validation

```powershell
python -m py_compile scripts\run_phase12b_controller_ablation_experiment.py
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

CARLA was stopped after runtime verification, and `127.0.0.1:2000` was confirmed
unreachable with no CARLA/UE4/Unreal process remaining.

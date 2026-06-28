# Phase 12B-LIN - Linear Spawn-Pair Controller Runtime Pass / Blocked Evidence

## Status

```text
Phase 12B-LIN Linear Spawn-Pair Controller Runtime Pass - all five calibrated Town03 routes passed the linear spawn-pair route-progress smoke gate after CARLA warm-up.
```

Phase 12B-LIN validates only the `linear_spawn_pair_follower` controller rows
from the Phase 12B matrix. This is a route-progress smoke pass, not a
fixed-route goal-reach completion pass. It is not CARLA Leaderboard, not a
formal route benchmark, and not an infraction benchmark.

## Runtime Commands

CARLA server was started from the external CARLA 0.9.16 package, then the 11D
ready gate was verified:

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11d_carla_provisioning_gate.py --carla-root D:\CARLA\packages\CARLA_0.9.16 --host 127.0.0.1 --port 2000 --steps 5 --require-ready
```

The linear-only controller ablation runtime command was:

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --controller-mode linear_spawn_pair_follower --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --child-timeout-sec 2400 --output-dir experiments\phase12
```

## Initial Blocked Evidence

The first full 5-row linear batch preserved blocked evidence:

```text
experiments\phase12\20260628T074345Z
row_count=5
executed_row_count=5
passed_count=4
failed_count=1
all_runtime_rows_passed=false
route_01=result_failed
```

`route_01` failed before vehicle setup because the first child runtime hit a
CARLA `load_world(Town03_Opt)` timeout:

```text
steps_completed=0
ego_spawned=false
route_progress_verified=false
error=time-out of 30000ms while waiting for the simulator
```

After the CARLA world finished warming up, a single `route_01` retry passed:

```text
experiments\phase12\20260628T080432Z
row_count=1
passed_count=1
all_runtime_rows_passed=true
```

## Final Pass Evidence

The full linear subset was rerun after CARLA warm-up:

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

Per-route route-progress smoke result:

| route_id | route_progress_m | route_progress_pct | distance_to_goal_m | collision_count | lane_invasion_count | steps_completed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `route_01` | 307.662099 | 100.000000 | 6.914185 | 0 | 11 | 2500 |
| `route_02` | 24.236822 | 5.827989 | 391.652049 | 2677 | 11 | 2800 |
| `route_03` | 10.515416 | 5.744478 | 172.609764 | 2428 | 4 | 2500 |
| `route_04` | 6.983494 | 3.905891 | 171.816015 | 2439 | 1 | 2500 |
| `route_05` | 10.109821 | 3.013498 | 325.427040 | 7678 | 2 | 5400 |

Required child evidence assertions passed for every final-pass row:

```text
result=passed
exit_code=0
controller_mode=linear_spawn_pair_follower
metrics_read_status=loaded
route_progress_verified=true
steps_completed=steps_requested
collision_sensor_attached=true
lane_invasion_sensor_attached=true
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
```

## Interpretation

The linear spawn-pair controller can satisfy Phase 11K route-progress smoke on
all five calibrated routes after CARLA warm-up. It does not demonstrate safe
route completion: routes 02-05 have large collision counts and remain far from
the goal. This is intentionally recorded as a linear route-progress smoke pass,
not as an infraction-safe controller pass.

## Boundary

These fields remain false:

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Phase 12B-LIN does not claim:

- CARLA Leaderboard passed
- formal route benchmark passed
- infraction benchmark passed
- fixed-route goal-reach completion
- all controller modes passed
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

# Phase 11L — Fixed Route Completion Attempt & Goal-Reach Gate

Phase 11L extends Phase 11K from route progress smoke to a strict fixed-route goal-reach gate. It uses the same requested route: `Town03`, start spawn index `3`, and end spawn index `30`. In the local CARLA 0.9.16 Windows package this resolves to runtime map `Town03_Opt`.

This is fixed spawn-pair smoke completion only. It is not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

## Status

```text
Phase 11L Fixed Route Completion Pass — strict goal-reach gate passed for real CARLA spawn-pair smoke.
```

Evidence directory:

```text
runtime_logs\carla_runs\20260613T130532Z
```

## Command

```powershell
$env:CARLA_ROOT="D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11l_fixed_route_completion.py --host 127.0.0.1 --port 2000 --town Town03 --start-spawn-index 3 --end-spawn-index 30 --steps 2500 --target-speed-kmh 18 --goal-tolerance-m 3.0 --perception-backend dummy --require-server --enable-metric-sensors --require-sensors --require-goal-reach --output-dir runtime_logs\carla_runs --run-regressions
```

## Goal-Reach Gate

```text
route_town=Town03
carla_runtime_town=Town03_Opt
route_map_name=Carla/Maps/Town03_Opt
route_start_spawn_index=3
route_end_spawn_index=30
route_distance_m=307.662099
goal_tolerance_m=3.0
route_goal_reach_required=true
goal_reach_step=1731
fixed_route_goal_reached=true
fixed_route_completion_verified=true
```

The runner attempted to use CARLA `GlobalRoutePlanner` from `CARLA_ROOT\PythonAPI\carla`. The local Python 3.12 CARLA environment did not have `networkx`, so the runner recorded fallback evidence and used the runner-only spawn-pair linear follower:

```text
goal_reach_controller_fallback: No module named 'networkx'
```

This fallback is still scoped to the 11L runner and does not modify VLM, SafetyGate, SemanticPlanner, or the baseline CARLA control mapper.

## Measured Metrics

```text
steps_requested=2500
steps_completed=2500
collision_sensor_attached=true
lane_invasion_sensor_attached=true
collision_count=0
lane_invasion_count=14
avg_speed_kmh=8.861962
max_speed_kmh=14.517316
distance_traveled_m=307.368702
route_progress_m=304.756089
route_progress_pct=99.055454
route_remaining_m=2.906009
distance_to_goal_m=2.906011
best_distance_to_goal_m=2.906011
final_distance_to_goal_m=2.906011
route_completion_verified=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
```

## Evidence Files

```text
manifest.json
metrics.json
events.jsonl
commands.txt
environment.txt
regression.txt
raw_outputs\
```

Important events:

```text
route_goal_reach_gate_enabled
goal_reach_controller_fallback
route_goal_reached
run_passed
```

## Regression Gates

```text
Phase 11D --require-ready: passed
Phase 11L 2500-step fixed route completion: passed
Base Python 3.10 Phase 11 checks: 6/6 passed
Base Python 3.10 demo checks: 6/6 passed
Python 3.12 Phase 11 checks: 6/6 passed
Python 3.12 Phase 11D ready gate: passed
Python 3.12 py_compile: passed
```

## Explicit Boundary

- `fixed_route_completion_verified=true` means the fixed spawn-pair smoke goal was reached within `3.0m`.
- `route_completion_verified=false` remains reserved for a future formal route benchmark.
- `lane_invasion_count=14` is a sensor reading in smoke evidence, not an infraction benchmark result.
- CARLA Leaderboard, formal route benchmark, real YOLO/RT-DETR, and real OpenAI-compatible VLM remain unverified.

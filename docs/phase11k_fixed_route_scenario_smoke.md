# Phase 11K — Fixed Route Scenario Smoke & Route Progress Metrics

Phase 11K extends Phase 11J with a fixed spawn-pair route scenario and route progress instrumentation. It uses the requested route definition `Town03`, start spawn index `3`, and end spawn index `30`; on the local CARLA 0.9.16 Windows package this resolves to the runtime map `Town03_Opt`.

This remains a smoke-level instrumentation gate. It is not CARLA Leaderboard, not an infraction benchmark, and not formal route completion verification.

## Status

```text
Phase 11K Fixed Route Scenario Smoke Pass — route progress metrics generated for real CARLA spawn-pair smoke.
```

Evidence directory:

```text
runtime_logs\carla_runs\20260613T092548Z
```

## Command

```powershell
$env:CARLA_ROOT="D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11k_fixed_route_smoke.py --host 127.0.0.1 --port 2000 --town Town03 --start-spawn-index 3 --end-spawn-index 30 --steps 100 --perception-backend dummy --require-server --enable-metric-sensors --require-sensors --require-route-progress --min-route-progress-m 0.5 --output-dir runtime_logs\carla_runs --run-regressions
```

## Route Scenario

```text
route_town=Town03
carla_runtime_town=Town03_Opt
route_map_name=Carla/Maps/Town03_Opt
route_start_spawn_index=3
route_end_spawn_index=30
resolved_route_start_spawn_index=3
resolved_route_end_spawn_index=30
route_distance_m=307.662099
```

The runner uses a Phase 11K-only route smoke control adapter because spawn index `3` faces almost opposite the start-to-goal direction. This adapter is scoped to the smoke runner and does not modify VLM, SafetyGate, SemanticPlanner, or the baseline CARLA control mapper.

## Measured Metrics

```text
steps_requested=100
steps_completed=100
collision_sensor_attached=true
lane_invasion_sensor_attached=true
collision_count=0
lane_invasion_count=0
avg_speed_kmh=6.435514
max_speed_kmh=9.23508
distance_traveled_m=8.866535
route_progress_m=8.574274
route_progress_pct=2.786913
route_remaining_m=299.087825
distance_to_goal_m=299.087857
route_progress_verified=true
route_goal_reached=false
route_completion_verified=false
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
route_scenario_loaded
route_smoke_control_applied
route_progress
route_progress_verified
run_passed
```

## Regression Gates

```text
Phase 11D --require-ready: passed
Phase 11K 100-step fixed route smoke: passed
Base Python 3.10 Phase 11 checks: 6/6 passed
Base Python 3.10 demo checks: 6/6 passed
Python 3.12 Phase 11 checks: 6/6 passed
Python 3.12 Phase 11D ready gate: passed
Python 3.12 py_compile: passed
```

## Explicit Boundary

- Route progress was measured from CARLA ego transform against a fixed spawn-pair route.
- `route_progress_verified=true` only means the smoke threshold `0.5m` was exceeded.
- `route_completion_verified=false` remains intentional.
- `collision_count=0` and `lane_invasion_count=0` are smoke sensor readings, not an infraction benchmark.
- CARLA Leaderboard, route completion benchmark, real YOLO/RT-DETR, and real OpenAI-compatible VLM remain unverified.

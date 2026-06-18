# Phase 11M — GRP-backed Route Following & Benchmark Boundary Preparation

Phase 11M upgrades Phase 11L from a fallback-capable fixed spawn-pair goal gate to a strict CARLA `GlobalRoutePlanner` route-following gate. It uses the same requested route: `Town03`, start spawn index `3`, and end spawn index `30`; on the local CARLA 0.9.16 package this resolves to runtime map `Town03_Opt`.

This remains fixed spawn-pair smoke validation only. It is not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

## Final Status

```text
Phase 11M GRP Route Following Pass — strict GRP-backed fixed-route goal-reach gate passed.
```

## Evidence Directory

```text
runtime_logs\carla_runs\20260614T173740Z
```

The evidence pack contains:

- `manifest.json`
- `metrics.json`
- `events.jsonl`
- `commands.txt`
- `environment.txt`
- `regression.txt`
- `raw_outputs\*.txt`

## Command

```powershell
$env:CARLA_ROOT="D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11m_grp_route_following.py --host 127.0.0.1 --port 2000 --town Town03 --start-spawn-index 3 --end-spawn-index 30 --steps 2500 --target-speed-kmh 18 --goal-tolerance-m 3.0 --route-sampling-resolution-m 2.0 --lookahead-waypoints 8 --perception-backend dummy --require-server --enable-metric-sensors --require-sensors --require-goal-reach --require-grp --output-dir runtime_logs\carla_runs --run-regressions
```

## Dependency Boundary

The runner does not auto-install CARLA route-planner dependencies. The CARLA Python 3.12 environment was explicitly unlocked with:

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install "networkx>=3,<4"
```

The final evidence records:

```text
grp_dependency_networkx_available=true
grp_route_source=carla_global_route_planner
grp_fallback_used=false
```

## Metrics

```text
steps_completed=2500
grp_route_required=true
grp_route_available=true
grp_route_waypoint_count=267
grp_route_distance_m=525.559609
grp_route_progress_m=512.909608
grp_route_progress_pct=97.593042
grp_current_waypoint_index=263
grp_remaining_waypoints=3
grp_route_following_verified=true
goal_reach_step=2073
distance_to_goal_m=2.283447
best_distance_to_goal_m=2.283447
fixed_route_goal_reached=true
fixed_route_completion_verified=true
collision_count=0
lane_invasion_count=27
regression_passed=true
```

## Benchmark Boundary

The structured boundary fields remain explicit:

```text
benchmark_boundary_prepared=true
benchmark_boundary_scope=structured_evidence_only_not_carla_leaderboard
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
```

`lane_invasion_count=27` is a sensor reading in smoke evidence, not an infraction benchmark result.

## Regression Proof

```text
base_phase11_carla_checks: passed
base_demo_checks: passed
py312_phase11_carla_checks: passed
py312_phase11d_require_ready: passed
py312_py_compile: passed
evidence JSON assertions: passed
```

## Scope Notes

- 11M uses a runner-only `GRPRouteFollowingControlAdapter`.
- The baseline VLM, SafetyGate, SemanticPlanner, CARLA control mapper, and baseline requirements are unchanged.
- This does not claim CARLA Leaderboard readiness or route-benchmark compliance.

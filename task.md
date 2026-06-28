# Current Task - Phase 12B-BASE

## Status

```text
Phase 12B-BASE Runtime Evidence Blocked - all five baseline PlannerAction mapper rows executed in real CARLA, but every row failed the fixed spawn-pair route-progress gate.
```

Maintained boundary:

```text
Phase 12B-BASE is baseline mapper runtime evidence, not a Runtime Pass. It does not claim CARLA Leaderboard, formal route benchmark, infraction benchmark, fixed-route goal-reach completion, all-controller ablation pass, merge, git tag, GitHub Release, CARLA package commit, Python venv commit, .env commit, runtime_logs commit, or raw experiment evidence commit.
```

## Evidence

- Pre-flight Phase 11D `--require-ready`: passed.
- CARLA package: `D:\CARLA\packages\CARLA_0.9.16`.
- CARLA Python: `D:\CARLA\envs\ma-vlna-carla312\python.exe`.
- Initial full batch evidence dir: `experiments\phase12\20260628T120210Z`.
- Initial full batch: `row_count=5`, `executed_row_count=5`, `passed_count=0`, `blocked_count=4`, `failed_count=1`.
- Initial route_01 issue: CARLA `load_world(Town03_Opt)` timeout before setup.
- Route_01 warm-up retry evidence dir: `experiments\phase12\20260628T121819Z`.
- Route_01 retry result: `route_progress_blocked`, `steps_completed=2500`, `route_progress_verified=false`.
- Final full batch evidence dir: `experiments\phase12\20260628T122108Z`.
- Final full batch:
  - `row_count=5`
  - `executed_row_count=5`
  - `passed_count=0`
  - `blocked_count=5`
  - `failed_count=0`
  - `all_runtime_rows_passed=false`
  - `all_rows_baseline=true`
  - `all_metrics_loaded=true`
  - `all_route_progress_blocked=true`
- All final rows recorded:
  - `ego_spawned=true`
  - `control_applied=true`
  - `rgb_frame_received=true`
  - `world_tick_advanced=true`
  - `collision_sensor_attached=true`
  - `lane_invasion_sensor_attached=true`
- Boundary fields remain false:
  - `route_benchmark_verified=false`
  - `infraction_benchmark_verified=false`
  - `leaderboard_evaluated=false`
  - `leaderboard_routes_exported=false`
  - `leaderboard_route_criteria_evaluated=false`
- CARLA was stopped after runtime; `127.0.0.1:2000` is no longer reachable and no CARLA/UE4/Unreal process remains.

## Per-Route Final Result

| route_id | result | steps_completed | route_progress_m | route_progress_pct | distance_to_goal_m | collision_count | lane_invasion_count | distance_traveled_m |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `route_01` | `route_progress_blocked` | 2500 | 0.000000 | 0.000000 | 307.662099 | 0 | 0 | 0.310613 |
| `route_02` | `route_progress_blocked` | 2800 | 0.000000 | 0.000000 | 415.869352 | 0 | 0 | 0.310613 |
| `route_03` | `route_progress_blocked` | 2500 | 0.000000 | 0.000000 | 183.052607 | 0 | 0 | 0.310612 |
| `route_04` | `route_progress_blocked` | 2500 | 0.000000 | 0.000000 | 178.796136 | 0 | 0 | 0.521562 |
| `route_05` | `route_progress_blocked` | 5400 | 0.000000 | 0.000000 | 335.484571 | 0 | 0 | 0.310613 |

## Interpretation

The baseline PlannerAction mapper is executable in CARLA closed loop, but it is
not a fixed-route controller. It reaches the control/tick/sensor path, yet
does not make measurable progress along the calibrated spawn-pair routes.

## Validation

- Phase 12B-BASE runtime evidence assertions: passed.
- CARLA cleanup check: passed.

## Next Action

Run regression checks, source commit boundary gate, then stage source-only files, commit, push to `codex/phase-11o-source-commit-boundary`, and update PR #1 while keeping it Draft/open/unmerged.

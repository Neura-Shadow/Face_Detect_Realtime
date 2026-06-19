# Phase 12A — CARLA Route Scaling Experiment

## Status

```text
Phase 12A Route Scaling Prepared — batch runner, fixed route matrix, dry-run scaffold, and summary aggregation are implemented.
```

Phase 12A 是第一條真正的 Phase 12 實驗線。它把 Phase 11M 的單一路線 GRP smoke runner 擴展成 5 條固定 `Town03` spawn-pair route 的批次實驗。此階段仍是 controlled smoke experiment，不是 CARLA Leaderboard、正式 route benchmark 或 infraction benchmark。

## Route Matrix

| route_id | town | start_spawn_index | end_spawn_index |
|---|---:|---:|---:|
| `route_01` | `Town03` | 3 | 30 |
| `route_02` | `Town03` | 8 | 52 |
| `route_03` | `Town03` | 12 | 74 |
| `route_04` | `Town03` | 25 | 101 |
| `route_05` | `Town03` | 40 | 126 |

Default runtime settings:

```text
steps=2500
target_speed_kmh=18
goal_tolerance_m=3.0
route_sampling_resolution_m=2.0
lookahead_waypoints=8
perception_backend=dummy
require_server=true
enable_metric_sensors=true
require_sensors=true
require_goal_reach=true
require_grp=true
```

## Output Layout

```text
experiments/phase12/<timestamp>/
  manifest.json
  summary.csv
  summary.json
  commands.txt
  README.md
  runs/
    route_01/<phase11m_timestamp>/
    route_02/<phase11m_timestamp>/
    route_03/<phase11m_timestamp>/
    route_04/<phase11m_timestamp>/
    route_05/<phase11m_timestamp>/
```

`experiments/phase12/<timestamp>/` is ignored by git by default. Selected small summaries can be force-added in a later packaging phase, but raw CARLA evidence must remain local unless explicitly packaged.

## Metrics Schema

`summary.csv` and `summary.json` aggregate these fields from each Phase 11M `metrics.json`:

- `fixed_route_goal_reached`
- `distance_to_goal_m`
- `route_progress_pct`
- `grp_route_progress_pct`
- `collision_count`
- `lane_invasion_count`
- `avg_speed_kmh`
- `max_speed_kmh`
- `distance_traveled_m`
- `steps_completed`
- `timeout`
- `result`
- `exit_code`
- `evidence_dir`

## Dry Run

```powershell
python scripts\run_phase12a_route_scaling_experiment.py --dry-run --output-dir experiments\phase12
```

Dry run writes the parent manifest and five route rows with `result=dry_run`, but does not launch CARLA and does not run Phase 11M child processes.

## Real Runtime Command

```powershell
$env:CARLA_ROOT="D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12a_route_scaling_experiment.py --host 127.0.0.1 --port 2000 --output-dir experiments\phase12 --run-regressions-once
```

The batch runner continues through all five routes even when one route fails. The final exit code is `0` only when all five routes return `result=passed` with exit code `0`.

## Blocked Semantics

If any route fails, times out, lacks required sensors, lacks GRP, or misses the goal-reach gate, the batch prints:

```text
Phase 12A Route Scaling Blocked
```

The output directory is still preserved with all route rows, commands, and any Phase 11M evidence directories that were produced.

## Boundary

Structured boundary fields remain:

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Phase 12A does not modify VLM, SafetyGate, SemanticPlanner, GRP controller, or baseline requirements.

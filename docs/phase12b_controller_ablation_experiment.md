# Phase 12B - Controller Ablation Scaffold

## Status

```text
Phase 12B Controller Ablation Prepared - controller ablation matrix, dry-run scaffold, and summary aggregation are implemented.
```

Phase 12B is a dry-run scaffold only. It prepares the controller ablation
matrix for later CARLA runtime execution, but it does not launch CARLA, does
not import the `carla` package, and does not claim runtime pass.

## Scope

Phase 12B compares command coverage for three controller modes over the
calibrated five-route Town03 matrix:

| route_id | start_spawn_index | end_spawn_index | horizon_steps |
| --- | ---: | ---: | ---: |
| route_01 | 3 | 30 | 2500 |
| route_02 | 8 | 52 | 2800 |
| route_03 | 12 | 74 | 2500 |
| route_04 | 25 | 101 | 2500 |
| route_05 | 40 | 126 | 5400 |

Controller modes:

| controller_mode | Runtime command mapping | runtime_command_status |
| --- | --- | --- |
| `linear_spawn_pair_follower` | `scripts/run_phase11k_fixed_route_smoke.py` | `wired_route_progress_smoke_only` |
| `grp_follower` | `scripts/run_phase11m_grp_route_following.py` | `wired_goal_reach_smoke` |
| `baseline_planner_action_mapper` | `python -m workers.CARLA_Closed_Loop_Agent` | `wired_closed_loop_mapper_only` |

The linear path currently maps to the existing Phase 11K route-progress smoke
controller. The baseline mapper path exercises the existing
PlannerAction-to-VehicleControl bridge but does not yet provide fixed end-spawn
route metrics. Phase 12B keeps those rows in the matrix and does not fake pass.

## Command

```powershell
python scripts\run_phase12b_controller_ablation_experiment.py --dry-run --output-dir experiments\phase12
```

The runner writes a timestamped output directory under:

```text
experiments\phase12\<timestamp>\
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
```

`runs/` is reserved for later runtime evidence paths. In Phase 12B dry-run,
each summary row keeps `evidence_dir=null`.

## Summary Schema

Each dry-run row includes:

```text
route_id
town
start_spawn_index
end_spawn_index
controller_mode
horizon_steps
command
runtime_command_status
result=dry_run
exit_code=null
fixed_route_goal_reached=null
distance_to_goal_m=null
route_progress_pct=null
grp_route_progress_pct=null
collision_count=null
lane_invasion_count=null
evidence_dir=null
```

The aggregate summary records:

```text
row_count=15
route_count=5
controller_count=3
continue_all_policy=true
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

Phase 12B does not claim:

- CARLA Leaderboard passed
- formal route benchmark passed
- infraction benchmark passed
- general driving policy quality proven
- real YOLO / RT-DETR verified
- real OpenAI-compatible VLM verified

## Validation

```powershell
python -m py_compile scripts\run_phase12b_controller_ablation_experiment.py
python scripts\run_phase12b_controller_ablation_experiment.py --dry-run --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

Acceptance for this phase:

```text
row_count=15
route_count=5
controller_count=3
all rows result=dry_run
all benchmark boundary fields false
no CARLA server required
no carla import required
no raw runtime output committed
```

## Local Dry-Run Evidence

```text
experiments\phase12\20260627T124452Z
row_count=15
route_count=5
controller_count=3
all_rows_result=dry_run
boundary_fields_false=true
```

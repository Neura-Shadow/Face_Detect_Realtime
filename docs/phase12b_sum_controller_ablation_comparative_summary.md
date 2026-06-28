# Phase 12B-SUM - Controller Ablation Comparative Summary

## Status

```text
Phase 12B-SUM Controller Ablation Comparative Summary Prepared - GRP, linear, and baseline mapper evidence has been normalized into comparable controller and route tables.
```

Phase 12B-SUM compares the three Phase 12B controller evidence lines without
starting CARLA and without changing any controller logic. It reads existing
local evidence and produces normalized controller-level and route-level tables.

## Source Evidence

| controller_mode | final evidence dir | source status |
| --- | --- | --- |
| `grp_follower` | `experiments\phase12\20260628T065257Z` | goal-reach smoke pass |
| `linear_spawn_pair_follower` | `experiments\phase12\20260628T080731Z` | route-progress smoke pass |
| `baseline_planner_action_mapper` | `experiments\phase12\20260628T122108Z` | route-progress blocked |

Generated comparative summary:

```text
experiments\phase12\20260628T125344Z
controller_summary.csv
route_comparison.csv
summary.json
manifest.json
README.md
```

The generated files remain local under `experiments\phase12` and are not
committed as source.

## Command

```powershell
python scripts\run_phase12b_controller_ablation_summary.py --require-complete --output-dir experiments\phase12
```

The script:

- does not import `carla`;
- does not require a reachable CARLA server;
- reads parent `summary.json` plus each child `metrics.json`;
- writes normalized controller and route comparison tables;
- keeps benchmark boundary fields false.

## Controller Summary

| controller_mode | pass_scope | row_count | passed_count | blocked_count | total_collision_count | avg_route_progress_pct | avg_distance_to_goal_m | conclusion |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `grp_follower` | goal-reach smoke pass | 5 | 5 | 0 | 0 | 99.884826 | 2.474271 | Only controller subset that verified fixed-route goal reach on all five calibrated routes. |
| `linear_spawn_pair_follower` | route-progress smoke only, not completion | 5 | 5 | 0 | 15222 | 23.698371 | 213.683811 | Passed route-progress smoke, but it is not a completion gate and it recorded high collision counts. |
| `baseline_planner_action_mapper` | route-progress blocked negative runtime evidence | 5 | 0 | 5 | 0 | 0.000000 | 284.172953 | Closed-loop mapper executed control and telemetry, but made no measurable spawn-pair route progress. |

## Route-Level Interpretation

GRP:

```text
5/5 rows passed
5/5 fixed_route_completion_verified=true
collision_count_total=0
```

Linear:

```text
5/5 rows passed the 11K route-progress smoke gate
0/5 fixed_route_completion_verified=true
collision_count_total=15222
route_02_to_route_05 remained far from goal
```

Baseline:

```text
5/5 rows executed closed-loop CARLA runtime
5/5 rows route_progress_blocked
5/5 rows route_progress_m=0.0
0/5 rows fixed_route_goal_reached
```

## Comparative Finding

The comparative result separates three different meanings of "works":

- `grp_follower` works as the current fixed-route goal-reach smoke controller.
- `linear_spawn_pair_follower` works only as a movement/progress smoke controller and is not safe or completion-proven.
- `baseline_planner_action_mapper` works as an executable PlannerAction-to-VehicleControl bridge, but it does not solve the spawn-pair route task.

This is why Phase 12B-SUM does not promote Phase 12B to an all-controller pass.
It records a differentiated controller ablation outcome.

## Boundary

Phase 12B-SUM does not claim:

- CARLA Leaderboard evaluation
- formal route benchmark
- infraction benchmark
- all-controller runtime pass
- safe driving policy quality
- real YOLO / RT-DETR verification
- real OpenAI-compatible VLM verification

Boundary fields remain false:

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

## Validation

```powershell
python -m py_compile scripts\run_phase12b_controller_ablation_summary.py
python scripts\run_phase12b_controller_ablation_summary.py --require-complete --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

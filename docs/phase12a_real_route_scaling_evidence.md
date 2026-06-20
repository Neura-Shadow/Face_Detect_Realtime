# Phase 12A — Real CARLA Route Scaling Evidence

## Status

```text
Phase 12A Real Runtime Evidence Produced — real 5-route CARLA batch completed with aggregated evidence; strict all-route pass gate is blocked by route_05 goal-reach failure.
```

This is real CARLA runtime smoke evidence, not a dry run. It is still not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

## Evidence Directory

```text
experiments\phase12\20260619T113705Z
```

Top-level evidence:

```text
manifest.json
summary.csv
summary.json
commands.txt
README.md
runs\<route_id>\<phase11m_timestamp>\
```

`experiments/phase12/*` remains ignored by git. The raw runtime evidence is preserved locally and intentionally not committed.

## Aggregate Result

```text
dry_run=false
row_count=5
passed_count=4
blocked_or_failed_count=1
all_routes_passed=false
status=route_scaling_blocked
```

| route_id | spawn pair | result | fixed_route_goal_reached | distance_to_goal_m | collision_count | lane_invasion_count |
|---|---:|---|---:|---:|---:|---:|
| `route_01` | `3 -> 30` | `passed` | true | 2.284790 | 0 | 27 |
| `route_02` | `8 -> 52` | `passed` | true | 2.316571 | 0 | 28 |
| `route_03` | `12 -> 74` | `passed` | true | 2.374137 | 0 | 10 |
| `route_04` | `25 -> 101` | `passed` | true | 2.444964 | 0 | 10 |
| `route_05` | `40 -> 126` | `goal_reach_blocked` | false | 322.443754 | 2408 | 0 |

## Boundary Fields

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

## Interpretation

Phase 12A successfully produced aggregated real CARLA route-scaling evidence. The batch correctly used continue-all behavior and preserved evidence for every route. The strict all-route pass gate remains blocked because `route_05` did not reach the goal within 2500 steps and accumulated collision events.

Phase 12A-R05 has now run a targeted recovery matrix for `route_05`. The best variant, `r05_slow_short_lookahead`, removed the early collision and reached 71.07% route progress, but still did not reach the goal tolerance under the original 2500-step budget.

Phase 12A-R05B then diagnosed late-route waypoint progression: the source run was still advancing near step 2500, and a 5200-step extended diagnostic reached the goal at step 4431. This confirms a horizon-limited smoke setup for Route 05, not a waypoint-index stall. The original Phase 12A all-route result remains blocked because its strict 2500-step gate did not pass.

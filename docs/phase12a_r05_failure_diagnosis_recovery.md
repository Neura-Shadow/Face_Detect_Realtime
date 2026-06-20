# Phase 12A-R05 — Route 05 Failure Diagnosis & Recovery Experiment

## Status

```text
Phase 12A-R05 Recovery Blocked — 4 conservative Route 05 recovery variants executed; none reached the strict goal tolerance.
```

This phase targets the `route_05` failure from Phase 12A:

```text
route_05: Town03 spawn 40 -> 126
result=goal_reach_blocked
distance_to_goal_m=322.443754
collision_count=2408
collision_actor_top=traffic.traffic_light
first_collision_step=88
route_progress_pct=3.888812
```

The signature indicates early collision/stuck behavior against a traffic light, not a missing GRP route:

```text
grp_route_available=true
grp_route_following_verified=true
grp_fallback_used=false
```

## Recovery Variants

The runner keeps the Phase 11M GRP controller unchanged and only tests conservative runner parameters:

| variant_id | target_speed_kmh | route_sampling_resolution_m | lookahead_waypoints | intent |
|---|---:|---:|---:|---|
| `r05_slow_wide_lookahead` | 8 | 2.0 | 12 | Lower speed with smoother steering target |
| `r05_slow_short_lookahead` | 8 | 1.0 | 3 | Lower speed with near-field dense route following |
| `r05_creep_short_lookahead` | 5 | 1.0 | 3 | Creep-speed short-lookahead recovery |
| `r05_creep_wide_lookahead` | 5 | 2.0 | 12 | Creep-speed smoother steering recovery |

## Real Runtime Result

```text
experiments\phase12\20260620T110904Z
row_count=5
recovery_attempt_count=4
recovered_count=0
recovery_passed=false
status=recovery_blocked
```

| variant_id | result | distance_to_goal_m | route_progress_pct | grp_route_progress_pct | collision_count | lane_invasion_count |
|---|---|---:|---:|---:|---:|---:|
| `r05_baseline_reference` | `goal_reach_blocked` | 322.443754 | 3.888812 | 3.101478 | 2408 | 0 |
| `r05_slow_wide_lookahead` | `goal_reach_blocked` | 321.707552 | 4.107550 | 3.101478 | 3911 | 0 |
| `r05_slow_short_lookahead` | `goal_reach_blocked` | 99.482140 | 71.067782 | 55.588992 | 0 | 3 |
| `r05_creep_short_lookahead` | `goal_reach_blocked` | 193.328441 | 42.705440 | 34.036878 | 0 | 3 |
| `r05_creep_wide_lookahead` | `goal_reach_blocked` | 321.537522 | 4.158796 | 3.101478 | 3594 | 0 |

The best observed recovery signal is `r05_slow_short_lookahead`: it removed the early collision failure and improved route progress from 3.89% to 71.07%, but still expired before reaching the goal tolerance. The next engineering step should inspect late-route tracking and waypoint-index progression for this non-collision variant instead of treating the route as recovered.

Follow-up Phase 12A-R05B confirmed that this variant was still progressing at step 2500 rather than stuck. A 5200-step extended diagnostic reached the fixed Route 05 goal at step 4431; see [phase12a_r05b_late_route_waypoint_progression_diagnosis.md](phase12a_r05b_late_route_waypoint_progression_diagnosis.md).

## Commands

Dry run:

```powershell
python scripts\run_phase12a_r05_recovery_experiment.py --dry-run --output-dir experiments\phase12
```

Real runtime:

```powershell
$env:CARLA_ROOT="D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12a_r05_recovery_experiment.py --host 127.0.0.1 --port 2000 --output-dir experiments\phase12
```

## Output

```text
experiments\phase12\<timestamp>\
  manifest.json
  summary.csv
  summary.json
  commands.txt
  README.md
  runs\<variant_id>\<phase11m_timestamp>\
```

## Boundary

This is targeted recovery smoke evidence only. It is not CARLA Leaderboard, not a formal route benchmark, not an infraction benchmark, and not proof of general driving policy quality.

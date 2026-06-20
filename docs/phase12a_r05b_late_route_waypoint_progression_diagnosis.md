# Phase 12A-R05B — Late-route Waypoint Progression Diagnosis

## Status

```text
Phase 12A-R05B Pass — late-route waypoint progression diagnosed; extended 5200-step run reached the fixed Route 05 goal.
```

This phase diagnoses the best Phase 12A-R05 recovery variant:

```text
variant=r05_slow_short_lookahead
route=Town03 spawn 40 -> 126
target_speed_kmh=8
route_sampling_resolution_m=1.0
lookahead_waypoints=3
```

Phase 12A and Phase 12A-R05 remain historically correct: the original 2500-step route-scaling gate was blocked, and the 4-variant R05 recovery matrix did not recover the route under its strict step budget. R05B only adds late-route diagnosis and an extended-horizon verification.

## Source Diagnosis

Source evidence:

```text
experiments\phase12\20260620T110904Z\runs\r05_slow_short_lookahead\20260620T111202Z
```

The 2500-step source run did not stall near the end:

```text
steps_completed=2500
result=goal_reach_blocked
distance_to_goal_m=99.482140
route_progress_pct=71.067782
grp_route_progress_pct=55.588992
grp_current_waypoint_index=239
grp_remaining_waypoints=201
collision_count=0
```

Final 200-step window:

```text
final_window_grp_index_delta=21
final_window_grp_progress_m_delta=20.999997
final_window_route_progress_m_delta=20.358841
final_window_distance_to_goal_m_delta=19.420991
final_window_avg_speed_kmh=7.451788
last_waypoint_change_step=2496
waypoint_progression_status=progressing_step_budget_limited
```

The key observation is that waypoint index, GRP distance, straight-line route projection, and distance-to-goal all continued moving at the end of the 2500-step run. This contradicts a waypoint-index stall diagnosis.

## Extended-step Verification

R05B first tried a 4000-step extended run:

```text
experiments\phase12\20260620T115354Z
result=goal_reach_blocked
distance_to_goal_m=45.168395
route_progress_pct=98.562551
grp_route_progress_pct=89.800242
grp_current_waypoint_index=392
grp_remaining_waypoints=48
collision_count=0
waypoint_progression_status=progressing_step_budget_limited
```

The 4000-step run still did not reach the goal, but it again showed active waypoint progression and no collision. Therefore R05B increased the diagnostic horizon to 5200 steps.

Final R05B evidence:

```text
experiments\phase12\20260620T115855Z
extended_evidence_dir=experiments\phase12\20260620T115855Z\runs\r05b_extended_slow_short\20260620T115859Z
```

Final 5200-step result:

```text
result=passed
steps_requested=5200
steps_completed=5200
goal_reach_step=4431
fixed_route_goal_reached=true
fixed_route_completion_verified=true
distance_to_goal_m=2.950533
route_progress_pct=100.0
grp_route_progress_pct=99.559155
grp_current_waypoint_index=438
grp_remaining_waypoints=2
collision_count=0
lane_invasion_count=8
```

## Commands

Dry run:

```powershell
python scripts\run_phase12a_r05b_waypoint_progression_diagnosis.py --dry-run --run-extended --output-dir experiments\phase12
```

Real runtime:

```powershell
$env:CARLA_ROOT="D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12a_r05b_waypoint_progression_diagnosis.py --host 127.0.0.1 --port 2000 --run-extended --output-dir experiments\phase12
```

## Output

```text
experiments\phase12\<timestamp>\
  manifest.json
  summary.csv
  summary.json
  commands.txt
  README.md
  runs\r05b_extended_slow_short\<phase11m_timestamp>\
```

## Interpretation

R05B diagnoses Route 05 as horizon-limited under the original Phase 12A 2500-step smoke budget. The best R05 recovery variant was not stuck in late-route waypoint progression: it continued advancing GRP waypoint index and reducing distance-to-goal. A 5200-step run using the unchanged Phase 11M GRP runner reached the fixed Route 05 goal.

This does not retroactively convert the original Phase 12A all-route gate into a pass. It only proves that Route 05 can be completed by the same conservative controller parameters when the diagnostic step horizon is long enough.

## Boundary

This is targeted diagnostic smoke evidence only. It is not CARLA Leaderboard, not a formal route benchmark, not an infraction benchmark, and not proof of general driving policy quality.

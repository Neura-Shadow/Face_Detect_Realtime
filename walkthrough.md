# Walkthrough — Phase 12A-R05B Late-route Waypoint Progression Diagnosis

1. Preserve Phase 11M as the single-route GRP fixed-route smoke runner.
2. Preserve Phase 12A aggregate evidence as the baseline Route 05 failure.
3. Diagnose Route 05 events: first collision at step 88 against `traffic.traffic_light`, then route progress stalls near 3.89%.
4. Add `scripts\run_phase12a_r05_recovery_experiment.py`.
5. Add `docs\phase12a_r05_failure_diagnosis_recovery.md`.
6. Test conservative recovery variants by changing only target speed, route sampling resolution, and lookahead waypoints.
7. Identify `r05_slow_short_lookahead` as the best non-collision variant.
8. Add `scripts\run_phase12a_r05b_waypoint_progression_diagnosis.py`.
9. Add `docs\phase12a_r05b_late_route_waypoint_progression_diagnosis.md`.
10. Parse the last 200 source steps to separate waypoint-index stall from horizon limitation.
11. Run extended-step diagnostics with the unchanged Phase 11M GRP runner.
12. Keep generated `experiments\phase12\<timestamp>` output local by default.

Current result:

```text
Phase 12A-R05B Pass — late-route waypoint progression diagnosed; extended 5200-step run reached the fixed Route 05 goal.
```

Route matrix:

```text
route_01: Town03 3 -> 30
route_02: Town03 8 -> 52
route_03: Town03 12 -> 74
route_04: Town03 25 -> 101
route_05: Town03 40 -> 126
```

Phase 12A-R05 source:

```text
docs\phase12a_r05_failure_diagnosis_recovery.md
scripts\run_phase12a_r05_recovery_experiment.py
docs\phase12a_r05b_late_route_waypoint_progression_diagnosis.md
scripts\run_phase12a_r05b_waypoint_progression_diagnosis.py
```

Boundary fields:

```text
benchmark_boundary_prepared=true
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Regression result:

```text
Phase 12A py_compile: passed
Phase 12A dry-run: passed
Phase 12A dry-run summary assertions: passed
Phase 12A real CARLA run: completed, exit code 1 due strict all-route blocked gate
Phase 12A real evidence assertions: passed
Phase 12A-R05 dry-run: passed
Phase 11D ready gate before R05 recovery: passed
Phase 12A-R05 real CARLA recovery matrix: completed, exit code 1 because no variant reached the goal
Phase 12A-R05 py_compile: passed
Phase 12A-R05 evidence assertions: passed
Phase 12A-R05B dry-run: passed
Phase 12A-R05B 4000-step diagnostic: completed, exit code 1, still progressing but goal not reached
Phase 12A-R05B 5200-step diagnostic: passed, goal reached at step 4431
Phase 12A-R05B py_compile: passed
Phase 12A-R05B evidence assertions: passed
Base Python Phase 11 checks: 6/6 passed
Base Python demo checks: 6/6 passed
```

Dry-run output:

```text
experiments\phase12\20260619T110549Z
```

Real runtime output:

```text
experiments\phase12\20260619T113705Z
passed_count=4
blocked_or_failed_count=1
route_05=goal_reach_blocked
```

R05 recovery runtime output:

```text
experiments\phase12\20260620T110904Z
recovery_attempt_count=4
recovered_count=0
recovery_passed=false
best_observed_variant=r05_slow_short_lookahead
best_observed_route_progress_pct=71.067782
best_observed_distance_to_goal_m=99.482140
best_observed_collision_count=0
```

R05B waypoint progression output:

```text
experiments\phase12\20260620T115855Z
source_waypoint_progression_status=progressing_step_budget_limited
extended_goal_reached=true
goal_reach_step=4431
distance_to_goal_m=2.950533
grp_current_waypoint_index=438
collision_count=0
```

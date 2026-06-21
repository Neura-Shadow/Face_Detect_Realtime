# Walkthrough — Phase 12A-C Calibrated 5-Route Runtime Confirmation

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
12. Add `scripts\run_phase12a_h_horizon_calibration_experiment.py`.
13. Add `docs\phase12a_h_horizon_calibration_experiment.md`.
14. Convert Phase 12A / R05B real evidence into a calibrated per-route horizon matrix.
15. Add `scripts\run_phase12a_c_calibrated_route_confirmation.py`.
16. Add `docs\phase12a_c_calibrated_route_confirmation.md`.
17. Run the five calibrated route commands against real CARLA.
18. Keep generated `experiments\phase12\<timestamp>` output local by default.

Current result:

```text
Phase 12A-C Calibrated Route Confirmation Pass — all five calibrated fixed Town03 routes reached the goal.
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
docs\phase12a_h_horizon_calibration_experiment.md
scripts\run_phase12a_h_horizon_calibration_experiment.py
docs\phase12a_c_calibrated_route_confirmation.md
scripts\run_phase12a_c_calibrated_route_confirmation.py
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
Phase 12A-H py_compile: passed
Phase 12A-H calibration run: passed
Phase 12A-H evidence assertions: passed
Phase 12A-C py_compile: passed
Phase 12A-C dry-run: passed
Phase 12A-C real CARLA calibrated route confirmation: passed
Phase 12A-C evidence assertions: passed
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

Phase 12A-H horizon calibration output:

```text
experiments\phase12\20260620T140648Z
calibrated_route_count=5
all_routes_calibrated=true
route_01=2500
route_02=2800
route_03=2500
route_04=2500
route_05=5400
```

Phase 12A-C calibrated route confirmation output:

```text
experiments\phase12\20260621T074706Z
confirmed_route_count=5
all_routes_confirmed=true
route_01_goal_reach_step=2073
route_02_goal_reach_step=2264
route_03_goal_reach_step=1567
route_04_goal_reach_step=1320
route_05_goal_reach_step=4431
all_collision_count=0
```

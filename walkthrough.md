# Walkthrough — Phase 12A-R05 Route 05 Recovery Experiment

1. Preserve Phase 11M as the single-route GRP fixed-route smoke runner.
2. Preserve Phase 12A aggregate evidence as the baseline Route 05 failure.
3. Diagnose Route 05 events: first collision at step 88 against `traffic.traffic_light`, then route progress stalls near 3.89%.
4. Add `scripts\run_phase12a_r05_recovery_experiment.py`.
5. Add `docs\phase12a_r05_failure_diagnosis_recovery.md`.
6. Test conservative recovery variants by changing only target speed, route sampling resolution, and lookahead waypoints.
7. Keep the recovery runner free of direct `carla` imports.
8. Write `manifest.json`, `summary.csv`, `summary.json`, `commands.txt`, `README.md`, and per-variant `runs/<variant_id>/` evidence directories.
9. Return success only if at least one recovery variant reaches the goal.
10. Keep generated `experiments\phase12\<timestamp>` output local by default.
11. Record the real blocked recovery evidence without relabeling it as a pass.

Current result:

```text
Phase 12A-R05 Recovery Blocked — 4 conservative Route 05 recovery variants executed; none reached the strict goal tolerance.
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

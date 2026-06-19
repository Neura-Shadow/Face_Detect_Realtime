# Walkthrough — Phase 12A CARLA Route Scaling Experiment

1. Preserve Phase 11M as the single-route GRP fixed-route smoke runner.
2. Preserve Phase 12 kickoff as the experiment scaffold foundation.
3. Add `scripts\run_phase12a_route_scaling_experiment.py`.
4. Add `docs\phase12a_carla_route_scaling_experiment.md`.
5. Define fixed `Town03` route matrix: `3->30`, `8->52`, `12->74`, `25->101`, `40->126`.
6. Implement batch orchestration through subprocess calls to `scripts\run_phase11m_grp_route_following.py`.
7. Keep the batch runner free of direct `carla` imports.
8. Write `manifest.json`, `summary.csv`, `summary.json`, `commands.txt`, `README.md`, and per-route `runs/<route_id>/` evidence directories.
9. Continue all routes even if a route fails.
10. Return success only when all five child routes pass.
11. Keep generated `experiments\phase12\<timestamp>` output local by default.
12. Update README, Phase 12 docs, release checklist, final report, task, and walkthrough.

Current result:

```text
Phase 12A Route Scaling Prepared — batch runner, fixed route matrix, dry-run scaffold, and summary aggregation are implemented.
```

Route matrix:

```text
route_01: Town03 3 -> 30
route_02: Town03 8 -> 52
route_03: Town03 12 -> 74
route_04: Town03 25 -> 101
route_05: Town03 40 -> 126
```

Phase 12A source:

```text
docs\phase12a_carla_route_scaling_experiment.md
scripts\run_phase12a_route_scaling_experiment.py
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
Base Python Phase 11 checks: 6/6 passed
Base Python demo checks: 6/6 passed
```

Dry-run output:

```text
experiments\phase12\20260619T110549Z
```

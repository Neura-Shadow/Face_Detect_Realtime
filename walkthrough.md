# Walkthrough - Phase 12B Controller Ablation Scaffold

1. Preserve Phase 12A-C as the calibrated 5-route smoke confirmation baseline.
2. Keep the original 2500-step Phase 12A all-route gate as historical blocked evidence.
3. Add `scripts\run_phase12b_controller_ablation_experiment.py`.
4. Add `docs\phase12b_controller_ablation_experiment.md`.
5. Use the calibrated Town03 route matrix:
   - `route_01`: `3 -> 30`, horizon `2500`
   - `route_02`: `8 -> 52`, horizon `2800`
   - `route_03`: `12 -> 74`, horizon `2500`
   - `route_04`: `25 -> 101`, horizon `2500`
   - `route_05`: `40 -> 126`, horizon `5400`
6. Expand each route across three controller modes:
   - `linear_spawn_pair_follower`
   - `grp_follower`
   - `baseline_planner_action_mapper`
7. Write a 15-row dry-run matrix without importing `carla`.
8. Keep `result=dry_run` and null runtime metrics for every row.
9. Preserve benchmark boundary fields as false.
10. Keep generated `experiments\phase12\<timestamp>` output local by default.

Current result:

```text
Phase 12B Controller Ablation Prepared - controller ablation matrix, dry-run scaffold, and summary aggregation are implemented.
```

Command:

```powershell
python scripts\run_phase12b_controller_ablation_experiment.py --dry-run --output-dir experiments\phase12
```

Expected dry-run output:

```text
experiments\phase12\20260627T124452Z
row_count=15
route_count=5
controller_count=3
all_rows_result=dry_run
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

Validation checklist:

```text
python -m py_compile scripts\run_phase12b_controller_ablation_experiment.py
python scripts\run_phase12b_controller_ablation_experiment.py --dry-run --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

Phase 12B must not be marked as Runtime Pass until a later phase executes real CARLA runtime commands and verifies the resulting evidence.

# Walkthrough - Phase 12B-SUM Controller Ablation Comparative Summary

1. Use the current source tree as authoritative.
2. Preserve the Phase 12B-GRP, Phase 12B-LIN, and Phase 12B-BASE runtime boundaries.
3. Do not rerun CARLA for SUM.
4. Read the three final parent `summary.json` files.
5. For each route row, read the child `metrics.json`.
6. Normalize controller-level fields into `controller_summary.csv`.
7. Normalize route-level fields into `route_comparison.csv`.
8. Generate a local SUM evidence directory under `experiments\phase12`.
9. Record a source doc with the comparative interpretation.
10. Keep generated SUM output local and out of git.

Source evidence:

```text
grp_follower=experiments\phase12\20260628T065257Z
linear_spawn_pair_follower=experiments\phase12\20260628T080731Z
baseline_planner_action_mapper=experiments\phase12\20260628T122108Z
```

Generated summary:

```text
experiments\phase12\20260628T125344Z
controller_summary.csv
route_comparison.csv
summary.json
manifest.json
README.md
```

Command:

```powershell
python scripts\run_phase12b_controller_ablation_summary.py --require-complete --output-dir experiments\phase12
```

Controller comparison:

```text
grp_follower:
  passed_count=5
  completion_verified_count=5
  total_collision_count=0
  avg_route_progress_pct=99.884826
  outcome=strongest_goal_reach_controller

linear_spawn_pair_follower:
  passed_count=5
  completion_verified_count=0
  total_collision_count=15222
  avg_route_progress_pct=23.698371
  outcome=route_progress_smoke_pass_with_high_collision_counts

baseline_planner_action_mapper:
  passed_count=0
  blocked_count=5
  total_collision_count=0
  avg_route_progress_pct=0.000000
  outcome=closed_loop_executable_but_route_progress_blocked
```

Boundary fields:

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Validation checklist:

```text
python -m py_compile scripts\run_phase12b_controller_ablation_summary.py
python scripts\run_phase12b_controller_ablation_summary.py --require-complete --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

Phase 12B-SUM is a differentiated controller-ablation summary. It does not upgrade Phase 12B to an all-controller runtime pass.

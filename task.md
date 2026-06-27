# Current Task - Phase 12B

## Status

```text
Phase 12B Controller Ablation Prepared - controller ablation matrix, dry-run scaffold, and summary aggregation are implemented.
```

Maintained boundary:

```text
Phase 12B is dry-run scaffold only; no CARLA Leaderboard, formal route benchmark, infraction benchmark, Runtime Pass claim, merge, git tag, GitHub Release, CARLA package commit, Python venv commit, .env commit, runtime_logs commit, or raw experiment evidence commit is created.
```

## Evidence

- Added `scripts\run_phase12b_controller_ablation_experiment.py`.
- Added `docs\phase12b_controller_ablation_experiment.md`.
- Updated README, Phase 12 kickoff plan, release checklist, final report, task, and walkthrough.
- Route matrix: `route_01 3->30 horizon=2500`, `route_02 8->52 horizon=2800`, `route_03 12->74 horizon=2500`, `route_04 25->101 horizon=2500`, `route_05 40->126 horizon=5400`.
- Controller matrix: `linear_spawn_pair_follower`, `grp_follower`, `baseline_planner_action_mapper`.
- Dry-run matrix shape: 5 routes x 3 controllers = 15 rows.
- Dry-run output files: `manifest.json`, `summary.csv`, `summary.json`, `commands.txt`, `README.md`.
- Dry-run policy: write command matrix and summary aggregation without importing CARLA or launching child runtime processes.
- Runtime command mapping:
  - `grp_follower` -> `scripts\run_phase11m_grp_route_following.py`
  - `linear_spawn_pair_follower` -> `scripts\run_phase11k_fixed_route_smoke.py`
  - `baseline_planner_action_mapper` -> `python -m workers.CARLA_Closed_Loop_Agent`
- `runtime_command_status` records scoped readiness instead of fake pass.
- `result=dry_run` for all rows.
- `exit_code=null`, `fixed_route_goal_reached=null`, `distance_to_goal_m=null`, `route_progress_pct=null`, `grp_route_progress_pct=null`, `collision_count=null`, `lane_invasion_count=null`, and `evidence_dir=null` for dry-run rows.
- `route_benchmark_verified=false`.
- `infraction_benchmark_verified=false`.
- `leaderboard_evaluated=false`.
- `leaderboard_routes_exported=false`.
- `leaderboard_route_criteria_evaluated=false`.

## Validation

- Phase 12B py_compile: passed.
- Phase 12B dry-run: passed.
- Phase 12B dry-run output dir: `experiments\phase12\20260627T124452Z`.
- Phase 12B dry-run assertions: passed with `row_count=15`, `route_count=5`, `controller_count=3`.
- Base Python Phase 11 checks: 6/6 passed.
- Base Python demo checks: 6/6 passed.
- Source commit boundary gate: passed with 8 staged source/docs files and no blocked artifacts.

## Next Action

Run validation, stage source-only files, commit with `Phase 12B: scaffold controller ablation experiment`, push to `codex/phase-11o-source-commit-boundary`, and verify PR #1 remains Draft/open/unmerged.

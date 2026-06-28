# Current Task - Phase 12B-BASE-M

## Status

```text
Phase 12B-BASE-M Baseline PlannerAction Mapper Route-Metric Wiring Prepared - the baseline mapper controller row now emits structured fixed-route metrics through a dedicated child runner.
```

Maintained boundary:

```text
Phase 12B-BASE-M is route-metric wiring and blocked-evidence verification only. It does not claim baseline mapper runtime pass, CARLA Leaderboard, formal route benchmark, infraction benchmark, fixed-route goal-reach completion, all-controller ablation pass, merge, git tag, GitHub Release, CARLA package commit, Python venv commit, .env commit, runtime_logs commit, or raw experiment evidence commit.
```

## Implementation

- Added `scripts\run_phase12b_baseline_mapper_route_metrics.py`.
- Updated `scripts\run_phase12b_controller_ablation_experiment.py` so `baseline_planner_action_mapper` rows now launch the BASE-M child runner.
- The child runner uses the existing `CarlaClosedLoopAgent` default `CarlaVehicleControlAdapter`.
- The baseline `PlannerActionToCarlaControl` mapper is not modified.
- The child runner writes structured `manifest.json`, `metrics.json`, `events.jsonl`, `commands.txt`, `environment.txt`, `regression.txt`, and `raw_outputs/`.
- Parent summary aggregation now includes:
  - `steps_completed`
  - `route_progress_verified`
  - `avg_speed_kmh`
  - `max_speed_kmh`
  - `distance_traveled_m`

## Evidence

- Dry-run evidence dir: `experiments\phase12\20260628T091403Z`.
- Dry-run result: `row_count=15`, `controller_count=3`.
- Baseline rows now use `runtime_command_status=wired_baseline_mapper_route_metrics_smoke`.
- No-server blocked wiring evidence dir: `experiments\phase12\20260628T091432Z`.
- Child evidence dir: `experiments\phase12\20260628T091432Z\runs\route_01\baseline_planner_action_mapper\20260628T091433Z`.
- Blocked smoke command: `scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --route-id route_01 --controller-mode baseline_planner_action_mapper --runtime-row-limit 1`.
- Blocked smoke result: `row_count=1`, `result=blocked`, `exit_code=1`, `metrics_read_status=loaded`.
- Child metrics assert:
  - `phase=Phase 12B-BASE-M`
  - `controller_mode=baseline_planner_action_mapper`
  - `server_reachable=false`
  - `route_progress_verified=false`
  - route fields are present
- Boundary fields remain false:
  - `route_benchmark_verified=false`
  - `infraction_benchmark_verified=false`
  - `leaderboard_evaluated=false`
  - `leaderboard_routes_exported=false`
  - `leaderboard_route_criteria_evaluated=false`

## Validation

- BASE-M py_compile: passed.
- Phase 12B dry-run matrix check: passed.
- Phase 12B-BASE-M no-server blocked wiring smoke assertions: passed.

## Next Action

Run full regression checks, source commit boundary gate, then stage source-only files, commit, push to `codex/phase-11o-source-commit-boundary`, and update PR #1 while keeping it Draft/open/unmerged.

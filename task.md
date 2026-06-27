# Current Task - Phase 12B-R

## Status

```text
Phase 12B-R Controller Ablation Runtime Wiring Prepared - execute-runtime child process wiring, blocked evidence handling, and summary aggregation are implemented.
```

Maintained boundary:

```text
Phase 12B-R wires runtime execution but does not claim Runtime Pass unless every requested controller row passes with verified evidence. No CARLA Leaderboard, formal route benchmark, infraction benchmark, merge, git tag, GitHub Release, CARLA package commit, Python venv commit, .env commit, runtime_logs commit, or raw experiment evidence commit is created.
```

## Evidence

- Extended `scripts\run_phase12b_controller_ablation_experiment.py`.
- Added `docs\phase12b_r_controller_ablation_runtime_wiring.md`.
- Updated README, Phase 12 kickoff plan, release checklist, final report, task, walkthrough, and the Phase 12B scaffold doc.
- Added explicit `--execute-runtime` mode.
- Added route/controller filters:
  - `--route-id`
  - `--controller-mode`
  - `--runtime-row-limit`
  - `--child-timeout-sec`
- Runtime execution launches child commands with continue-all semantics.
- Runtime execution stores child stdout/stderr under `raw_outputs/`.
- Runtime execution parses `evidence_dir=` or `experiment_dir=` from child output.
- Runtime execution reads child `metrics.json` or `summary.json` when available.
- Summary aggregation now includes `executed_row_count`, `passed_count`, `blocked_count`, `failed_count`, and `all_runtime_rows_passed`.
- Dry-run behavior remains intact and still produces the 15-row controller matrix without importing CARLA.
- Parent Phase 12B runner still does not import `carla`.
- Runtime blocked evidence is preserved instead of fake pass.
- Boundary fields remain false:
  - `route_benchmark_verified=false`
  - `infraction_benchmark_verified=false`
  - `leaderboard_evaluated=false`
  - `leaderboard_routes_exported=false`
  - `leaderboard_route_criteria_evaluated=false`

## Local Evidence

Dry-run regression:

```text
experiments\phase12\20260627T131038Z
row_count=15
route_count=5
controller_count=3
all_rows_result=dry_run
boundary_fields_false=true
```

Runtime wiring smoke:

```text
experiments\phase12\20260627T131052Z
row_count=1
executed_row_count=1
result=blocked
exit_code=1
metrics_read_status=loaded
evidence_exists=true
raw_outputs_exist=true
boundary_fields_false=true
```

## Validation

- Phase 12B-R py_compile: passed.
- Phase 12B-R dry-run regression: passed.
- Phase 12B-R dry-run assertions: passed.
- Phase 12B-R runtime wiring smoke: blocked as expected with structured evidence.
- Phase 12B-R runtime wiring assertions: passed.
- Parent Phase 12B runner carla import scan: passed, no direct `import carla`.
- Base Python Phase 11 checks: 6/6 passed.
- Base Python demo checks: 6/6 passed.
- Source commit boundary gate: passed with 9 staged source/docs files and no blocked artifacts.

## Next Action

Run regressions and source-boundary verification, stage source-only files, commit, push to `codex/phase-11o-source-commit-boundary`, and update PR #1 while keeping it Draft/open/unmerged.

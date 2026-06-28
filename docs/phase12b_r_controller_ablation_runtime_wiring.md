# Phase 12B-R - Controller Ablation Runtime Wiring

## Status

```text
Phase 12B-R Controller Ablation Runtime Wiring Prepared - execute-runtime child process wiring, blocked evidence handling, and summary aggregation are implemented.
```

Phase 12B-R upgrades the Phase 12B controller ablation scaffold with an
explicit runtime execution path. It does not claim Runtime Pass by default. A
runtime pass requires a later full CARLA execution where every requested
controller row completes successfully with verified evidence.

## Runtime Wiring

The runner remains safe by default:

```powershell
python scripts\run_phase12b_controller_ablation_experiment.py --dry-run --output-dir experiments\phase12
```

Runtime execution is opt-in:

```powershell
python scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --output-dir experiments\phase12
```

Useful filters for wiring smoke:

```powershell
python scripts\run_phase12b_controller_ablation_experiment.py `
  --execute-runtime `
  --route-id route_01 `
  --controller-mode linear_spawn_pair_follower `
  --runtime-row-limit 1 `
  --child-timeout-sec 120 `
  --python-executable python `
  --output-dir experiments\phase12
```

The parent Phase 12B-R runner does not import `carla`. It launches existing
child runtime commands and then aggregates the resulting evidence.

## Controller Mapping

| controller_mode | Runtime command |
| --- | --- |
| `linear_spawn_pair_follower` | `scripts/run_phase11k_fixed_route_smoke.py` |
| `grp_follower` | `scripts/run_phase11m_grp_route_following.py` |
| `baseline_planner_action_mapper` | `python -m workers.CARLA_Closed_Loop_Agent` |

The baseline mapper path is command-wired, but it still has no fixed end-spawn
route metrics. It must not be treated as a route-completion benchmark row until
a later phase adds structured route evidence for that controller mode.

## Output Layout

```text
experiments/phase12/<timestamp>/
  manifest.json
  summary.csv
  summary.json
  commands.txt
  README.md
  runs/
  raw_outputs/
```

`raw_outputs/` stores child stdout/stderr for executed rows. These files remain
local by default and are not committed.

## Summary Fields

Phase 12B-R keeps the Phase 12B row schema and adds runtime aggregation fields:

```text
execute_runtime
executed_row_count
passed_count
blocked_count
failed_count
all_runtime_rows_passed
runtime_execution_status
duration_sec
metrics_read_status
stdout_path
stderr_path
```

`all_runtime_rows_passed=true` is the only condition that allows the runner to
exit 0 in `--execute-runtime` mode.

## Local Blocked Wiring Evidence

Local wiring smoke was executed without a reachable CARLA server:

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

This proves the runtime wiring can launch a child runner, collect blocked
evidence, read structured metrics, and preserve raw child output. It is not a
runtime pass.

## Follow-Up GRP Runtime Pass

The GRP-only controller subset was later executed successfully:

```text
experiments\phase12\20260628T065257Z
controller_mode=grp_follower
row_count=5
executed_row_count=5
passed_count=5
all_runtime_rows_passed=true
```

See [phase12b_grp_controller_ablation_runtime_pass.md](phase12b_grp_controller_ablation_runtime_pass.md).

## Boundary

These fields remain false:

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Phase 12B-R does not claim:

- CARLA Leaderboard passed
- formal route benchmark passed
- infraction benchmark passed
- Phase 12B runtime pass
- general driving policy quality proven
- real YOLO / RT-DETR verified
- real OpenAI-compatible VLM verified

## Validation

```powershell
python -m py_compile scripts\run_phase12b_controller_ablation_experiment.py
python scripts\run_phase12b_controller_ablation_experiment.py --dry-run --output-dir experiments\phase12
python scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --route-id route_01 --controller-mode linear_spawn_pair_follower --runtime-row-limit 1 --child-timeout-sec 120 --python-executable python --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

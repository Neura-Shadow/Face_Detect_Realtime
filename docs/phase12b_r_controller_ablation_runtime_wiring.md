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
| `baseline_planner_action_mapper` | `scripts/run_phase12b_baseline_mapper_route_metrics.py` |

The baseline mapper path is now command-wired through Phase 12B-BASE-M route
metrics. It exercises the existing PlannerAction-to-VehicleControl mapper and
records fixed end-spawn route metrics, but it must still not be treated as a
baseline runtime pass until the baseline subset is executed successfully in
real CARLA.

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
steps_completed
route_progress_verified
avg_speed_kmh
max_speed_kmh
distance_traveled_m
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

## Follow-Up Linear Runtime Pass / Blocked Evidence

The linear-only controller subset was later executed with both blocked and pass
evidence:

```text
initial_batch=experiments\phase12\20260628T074345Z
initial_batch_status=blocked_by_route_01_carla_load_world_timeout
final_batch=experiments\phase12\20260628T080731Z
final_batch_status=route_progress_smoke_pass
passed_count=5
all_runtime_rows_passed=true
```

See [phase12b_lin_controller_ablation_runtime_pass.md](phase12b_lin_controller_ablation_runtime_pass.md).

## Follow-Up Baseline Mapper Route-Metric Wiring

The baseline mapper controller row was later upgraded from command-only wiring
to structured route-metric child evidence:

```text
script=scripts/run_phase12b_baseline_mapper_route_metrics.py
local_smoke=experiments\phase12\20260628T091432Z
controller_mode=baseline_planner_action_mapper
result=blocked
metrics_read_status=loaded
route_fields_present=true
```

See [phase12b_base_m_planner_action_mapper_route_metrics.md](phase12b_base_m_planner_action_mapper_route_metrics.md).

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
python -m py_compile scripts\run_phase12b_baseline_mapper_route_metrics.py
python scripts\run_phase12b_controller_ablation_experiment.py --dry-run --output-dir experiments\phase12
python scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --route-id route_01 --controller-mode linear_spawn_pair_follower --runtime-row-limit 1 --child-timeout-sec 120 --python-executable python --output-dir experiments\phase12
python scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --route-id route_01 --controller-mode baseline_planner_action_mapper --runtime-row-limit 1 --child-timeout-sec 120 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

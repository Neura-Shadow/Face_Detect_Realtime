# Phase 12B-BASE-M - Baseline PlannerAction Mapper Route-Metric Wiring

## Status

```text
Phase 12B-BASE-M Baseline PlannerAction Mapper Route-Metric Wiring Prepared - the baseline mapper controller row now emits structured fixed-route metrics through a dedicated child runner.
```

Phase 12B-BASE-M wires the existing closed-loop baseline path into the Phase
12B controller-ablation evidence format:

```text
SemanticPlanner
-> PlannerAction
-> PlannerActionToCarlaControl
-> CARLA VehicleControl
-> CarlaRouteProgressTracker
-> metrics.json / summary.json aggregation
```

This phase does not modify VLM, SafetyGate, SemanticPlanner, or the baseline
CARLA `PlannerActionToCarlaControl` mapper. It only adds a route-metric child
runner and parent aggregation fields so the baseline mapper rows can be audited
with the same evidence shape as the GRP and linear controller rows.

## New Runtime Child

```text
scripts/run_phase12b_baseline_mapper_route_metrics.py
```

The child runner:

- runs Phase 11D `--require-ready` before touching CARLA runtime;
- starts `CarlaClosedLoopAgent` with the existing default `CarlaVehicleControlAdapter`;
- attaches optional collision and lane-invasion sensors;
- loads the fixed spawn-pair route through `CarlaRouteProgressTracker`;
- writes `manifest.json`, `metrics.json`, `events.jsonl`, `commands.txt`,
  `environment.txt`, `regression.txt`, and `raw_outputs/`;
- exits nonzero with structured blocked evidence if CARLA is unavailable or
  route progress is not verified.

## Parent Wiring

`scripts/run_phase12b_controller_ablation_experiment.py` now maps:

| controller_mode | Runtime command | runtime_command_status |
| --- | --- | --- |
| `baseline_planner_action_mapper` | `scripts/run_phase12b_baseline_mapper_route_metrics.py` | `wired_baseline_mapper_route_metrics_smoke` |

The parent summary also reads these child metrics when available:

```text
steps_completed
route_progress_verified
avg_speed_kmh
max_speed_kmh
distance_traveled_m
route_progress_pct
distance_to_goal_m
collision_count
lane_invasion_count
```

## Smoke Command

No-server blocked wiring smoke:

```powershell
python scripts\run_phase12b_controller_ablation_experiment.py `
  --execute-runtime `
  --route-id route_01 `
  --controller-mode baseline_planner_action_mapper `
  --runtime-row-limit 1 `
  --child-timeout-sec 120 `
  --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe `
  --base-python python `
  --output-dir experiments\phase12
```

Real CARLA baseline mapper subset command:

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12b_controller_ablation_experiment.py `
  --execute-runtime `
  --controller-mode baseline_planner_action_mapper `
  --host 127.0.0.1 `
  --port 2000 `
  --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe `
  --base-python python `
  --child-timeout-sec 2400 `
  --output-dir experiments\phase12
```

## Local Blocked Evidence

Local no-server wiring smoke produced structured blocked evidence:

```text
experiment_dir=experiments\phase12\20260628T091432Z
child_evidence_dir=experiments\phase12\20260628T091432Z\runs\route_01\baseline_planner_action_mapper\20260628T091433Z
row_count=1
controller_mode=baseline_planner_action_mapper
result=blocked
exit_code=1
metrics_read_status=loaded
server_reachable=false
route_progress_verified=false
```

Verified assertions:

```text
child_phase=Phase 12B-BASE-M
child_controller_mode=baseline_planner_action_mapper
route_fields_present=true
benchmark_boundary_scope=baseline_mapper_route_metrics_only_not_carla_leaderboard
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
```

This blocked result is expected without a reachable CARLA server. It proves
the route-metric wiring and evidence handling, not runtime driving success.

## Follow-Up Runtime Evidence

Phase 12B-BASE later executed the baseline mapper rows in real CARLA:

```text
final_batch=experiments\phase12\20260628T122108Z
controller_mode=baseline_planner_action_mapper
row_count=5
executed_row_count=5
passed_count=0
blocked_count=5
all_route_progress_blocked=true
```

See [phase12b_base_planner_action_mapper_runtime_evidence.md](phase12b_base_planner_action_mapper_runtime_evidence.md).

## Boundary

Phase 12B-BASE-M does not claim:

- baseline mapper runtime pass
- fixed-route goal completion
- CARLA Leaderboard evaluation
- formal route benchmark
- infraction benchmark
- safe driving policy quality
- GRP or linear controller behavior changes

The benchmark boundary fields remain:

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

## Validation

```powershell
python -m py_compile scripts\run_phase12b_baseline_mapper_route_metrics.py scripts\run_phase12b_controller_ablation_experiment.py
python scripts\run_phase12b_controller_ablation_experiment.py --dry-run --output-dir experiments\phase12
python scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --route-id route_01 --controller-mode baseline_planner_action_mapper --runtime-row-limit 1 --child-timeout-sec 120 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

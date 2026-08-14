# Phase 12B-BASE - Baseline PlannerAction Mapper Runtime Evidence

## Status

```text
Phase 12B-BASE Runtime Evidence Blocked - all five baseline PlannerAction mapper rows executed in real CARLA, but every row failed the fixed spawn-pair route-progress gate.
```

Phase 12B-BASE runs the `baseline_planner_action_mapper` controller subset in
the real CARLA Python 3.12 runtime. This is the follow-up to Phase 12B-BASE-M:
BASE-M proved structured route-metric wiring; BASE proves the baseline mapper's
real runtime outcome under the calibrated five-route matrix.

The baseline mapper path is intentionally the existing MA-VLNA chain:

```text
EdgePerception
-> SemanticPlanner local plan
-> SafetyGate planner validation
-> PlannerAction
-> PlannerActionToCarlaControl
-> CARLA VehicleControl
-> CarlaRouteProgressTracker
```

VLM, SafetyGate, SemanticPlanner, and `PlannerActionToCarlaControl` were not
modified for this evidence run.

## Runtime Command

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

Pre-flight gate:

```text
Phase 11D --require-ready passed
CARLA_ROOT=D:\CARLA\packages\CARLA_0.9.16
python=D:\CARLA\envs\ma-vlna-carla312\python.exe
host=127.0.0.1
port=2000
```

## Evidence

Initial full batch:

```text
experiments\phase12\20260628T120210Z
row_count=5
executed_row_count=5
passed_count=0
blocked_count=4
failed_count=1
route_01=load_world_timeout_before_setup
routes_02_to_05=route_progress_blocked
```

Route 01 warm-up retry:

```text
experiments\phase12\20260628T121819Z
row_count=1
controller_mode=baseline_planner_action_mapper
result=route_progress_blocked
steps_completed=2500
route_progress_verified=false
```

Final full batch:

```text
experiments\phase12\20260628T122108Z
row_count=5
executed_row_count=5
passed_count=0
blocked_count=5
failed_count=0
all_runtime_rows_passed=false
all_rows_baseline=true
all_metrics_loaded=true
all_route_progress_blocked=true
boundary_fields_false=true
```

## Final Per-Route Result

| route_id | result | steps_completed | route_progress_m | route_progress_pct | distance_to_goal_m | collision_count | lane_invasion_count | distance_traveled_m |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `route_01` | `route_progress_blocked` | 2500 | 0.000000 | 0.000000 | 307.662099 | 0 | 0 | 0.310613 |
| `route_02` | `route_progress_blocked` | 2800 | 0.000000 | 0.000000 | 415.869352 | 0 | 0 | 0.310613 |
| `route_03` | `route_progress_blocked` | 2500 | 0.000000 | 0.000000 | 183.052607 | 0 | 0 | 0.310612 |
| `route_04` | `route_progress_blocked` | 2500 | 0.000000 | 0.000000 | 178.796136 | 0 | 0 | 0.521562 |
| `route_05` | `route_progress_blocked` | 5400 | 0.000000 | 0.000000 | 335.484571 | 0 | 0 | 0.310613 |

All final rows also recorded:

```text
ego_spawned=true
control_applied=true
rgb_frame_received=true
world_tick_advanced=true
collision_sensor_attached=true
lane_invasion_sensor_attached=true
route_progress_verified=false
fixed_route_goal_reached=false
```

## Interpretation

The baseline PlannerAction mapper is runtime-capable: it connects, spawns ego,
receives RGB frames, emits PlannerAction-derived control, advances CARLA ticks,
and records sensors. It does not, however, solve the fixed spawn-pair route
task. In the calibrated five-route matrix, the baseline local planner plus
PlannerAction mapper produced negligible route displacement and failed the
minimum `0.5m` route-progress smoke gate on every route.

This is useful negative evidence: it separates "closed-loop control mapping is
wired and executable" from "route-following controller quality is proven."

## Boundary

Phase 12B-BASE does not claim:

- baseline mapper runtime pass
- fixed-route goal completion
- CARLA Leaderboard evaluation
- formal route benchmark
- infraction benchmark
- safe driving policy quality
- all-controller ablation pass

Boundary fields remain false:

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

## Cleanup

CARLA server was stopped after runtime:

```text
TcpTestSucceeded=false
CarlaProcesses=none
```

## Validation

```powershell
python -m py_compile scripts\run_phase12b_baseline_mapper_route_metrics.py scripts\run_phase12b_controller_ablation_experiment.py scripts\run_phase11_carla_checks.py
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

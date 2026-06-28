# Walkthrough - Phase 12B-BASE-M Baseline PlannerAction Mapper Route-Metric Wiring

1. Preserve Phase 12B-R runtime parent behavior.
2. Identify that `baseline_planner_action_mapper` was previously command-wired only.
3. Add a dedicated BASE-M child runner that produces the same evidence shape as 11K/11M child runs.
4. Run the existing `CarlaClosedLoopAgent` with its default `CarlaVehicleControlAdapter`.
5. Do not modify VLM, SafetyGate, SemanticPlanner, or `PlannerActionToCarlaControl`.
6. Attach `CarlaRuntimeMetrics` and `CarlaRouteProgressTracker` to the baseline mapper run.
7. Update Phase 12B parent command mapping for `baseline_planner_action_mapper`.
8. Extend parent summary rows with route/sensor metric fields.
9. Verify dry-run still emits 15 rows across 5 routes x 3 controllers.
10. Run one no-server baseline mapper runtime row and require structured blocked evidence.
11. Read the child `metrics.json` through the parent summary path.
12. Keep generated evidence under `experiments\phase12` and out of git.

Current result:

```text
Phase 12B-BASE-M Baseline PlannerAction Mapper Route-Metric Wiring Prepared - the baseline mapper controller row now emits structured fixed-route metrics through a dedicated child runner.
```

New child runner:

```text
scripts\run_phase12b_baseline_mapper_route_metrics.py
```

Parent dry-run evidence:

```text
experiments\phase12\20260628T091403Z
row_count=15
controller_count=3
baseline_runtime_command_status=wired_baseline_mapper_route_metrics_smoke
```

No-server blocked wiring evidence:

```text
experiments\phase12\20260628T091432Z
child_evidence_dir=experiments\phase12\20260628T091432Z\runs\route_01\baseline_planner_action_mapper\20260628T091433Z
row_count=1
controller_mode=baseline_planner_action_mapper
result=blocked
exit_code=1
metrics_read_status=loaded
server_reachable=false
route_progress_verified=false
```

Validated assertions:

```text
child_phase=Phase 12B-BASE-M
child_controller_mode=baseline_planner_action_mapper
route_fields_present=true
benchmark_boundary_scope=baseline_mapper_route_metrics_only_not_carla_leaderboard
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
```

Baseline mapper runtime command:

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --controller-mode baseline_planner_action_mapper --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --child-timeout-sec 2400 --output-dir experiments\phase12
```

Validation checklist:

```text
python -m py_compile scripts\run_phase12b_baseline_mapper_route_metrics.py scripts\run_phase12b_controller_ablation_experiment.py
python scripts\run_phase12b_controller_ablation_experiment.py --dry-run --output-dir experiments\phase12
python scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --route-id route_01 --controller-mode baseline_planner_action_mapper --runtime-row-limit 1 --child-timeout-sec 120 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

Phase 12B-BASE-M is not a baseline mapper runtime pass. It proves structured route-metric wiring and blocked evidence handling for the baseline mapper controller rows.

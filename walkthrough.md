# Walkthrough - Phase 12B-R Controller Ablation Runtime Wiring

1. Preserve Phase 12B dry-run scaffold behavior.
2. Keep `--dry-run` as the default safe validation path: no CARLA import, no CARLA server, no child runtime launch.
3. Add explicit `--execute-runtime` for runtime wiring.
4. Reuse the same 5-route x 3-controller matrix.
5. Build each child command from the existing controller mapping:
   - `linear_spawn_pair_follower` -> `scripts\run_phase11k_fixed_route_smoke.py`
   - `grp_follower` -> `scripts\run_phase11m_grp_route_following.py`
   - `baseline_planner_action_mapper` -> `python -m workers.CARLA_Closed_Loop_Agent`
6. Add filters for controlled smoke execution:
   - `--route-id`
   - `--controller-mode`
   - `--runtime-row-limit`
   - `--child-timeout-sec`
7. Run child commands with continue-all semantics.
8. Capture child stdout/stderr under `raw_outputs/`.
9. Parse child `evidence_dir=` or `experiment_dir=`.
10. Read child `metrics.json` or `summary.json` when available.
11. Aggregate pass/blocked/failed counts into `summary.json`.
12. Exit 0 in runtime mode only when every requested runtime row passes.
13. Preserve benchmark boundary fields as false.

Current result:

```text
Phase 12B-R Controller Ablation Runtime Wiring Prepared - execute-runtime child process wiring, blocked evidence handling, and summary aggregation are implemented.
```

Dry-run command:

```powershell
python scripts\run_phase12b_controller_ablation_experiment.py --dry-run --output-dir experiments\phase12
```

Runtime wiring smoke command:

```powershell
python scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --route-id route_01 --controller-mode linear_spawn_pair_follower --runtime-row-limit 1 --child-timeout-sec 120 --python-executable python --output-dir experiments\phase12
```

Dry-run regression output:

```text
experiments\phase12\20260627T131038Z
row_count=15
route_count=5
controller_count=3
all_rows_result=dry_run
```

Runtime wiring smoke output:

```text
experiments\phase12\20260627T131052Z
row_count=1
executed_row_count=1
result=blocked
exit_code=1
metrics_read_status=loaded
evidence_exists=true
raw_outputs_exist=true
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
python scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --route-id route_01 --controller-mode linear_spawn_pair_follower --runtime-row-limit 1 --child-timeout-sec 120 --python-executable python --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

Phase 12B-R must not be marked as Runtime Pass until a later full execution verifies every requested controller row against real CARLA evidence.

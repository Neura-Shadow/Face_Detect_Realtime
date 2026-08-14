# Phase 12C-DUMMY — Dummy Perception Backend Runtime Confirmation

## Status

```text
Phase 12C-DUMMY Runtime Confirmation Pass - dummy backend rows confirmed in real CARLA runtime.
```

Phase 12C-DUMMY 是 Phase 12C perception backend ablation 的第一個 runtime confirmation 子階段。它固定：

```text
controller_mode=grp_follower
perception_backend=dummy
town=Town03
route_matrix=calibrated 5-route spawn-pair matrix
```

此階段只確認 dummy perception backend 在既有 GRP route-following runtime path 上可完成五條 calibrated route。它不驗證 YOLO / RT-DETR runtime，也不宣稱 CARLA Leaderboard、正式 route benchmark 或 infraction benchmark。

## Runtime Command

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_dummy_runtime_confirmation.py --host 127.0.0.1 --port 2000 --output-dir experiments\phase12 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --child-timeout-sec 2400 --parent-timeout-sec 14400
```

Prerequisite gate：

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11d_carla_provisioning_gate.py --carla-root $env:CARLA_ROOT --host 127.0.0.1 --port 2000 --steps 5 --require-ready
```

## Evidence

```text
experiments\phase12\20260628T173019Z
child_experiment_dir=experiments\phase12\20260628T173019Z\runs\20260628T173021Z
```

Generated files：

- `manifest.json`
- `summary.json`
- `summary.csv`
- `commands.txt`
- `environment.json`
- `README.md`
- `raw_outputs/phase12b_parent.stdout.txt`
- `raw_outputs/phase12b_parent.stderr.txt`

## Aggregate Result

```text
status=dummy_runtime_confirmed
confirmed=true
row_count=5
passed_count=5
blocked_count=0
failed_count=0
collision_count_total=0
lane_invasion_count_total=83
all_dummy_routes_confirmed=true
```

Per-route result：

| route_id | result | steps_completed | goal_reached | distance_to_goal_m | grp_route_progress_pct | collision_count | lane_invasion_count |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: |
| `route_01` | `passed` | 2500 | true | 2.284790 | 97.593042 | 0 | 27 |
| `route_02` | `passed` | 2800 | true | 2.316571 | 100.000000 | 0 | 28 |
| `route_03` | `passed` | 2500 | true | 2.374137 | 100.000000 | 0 | 10 |
| `route_04` | `passed` | 2500 | true | 2.443187 | 100.000000 | 0 | 10 |
| `route_05` | `passed` | 5400 | true | 2.952668 | 99.559155 | 0 | 8 |

## Assertions

```text
child_exit_zero=true
child_summary_loaded=true
row_count_matches_requested_routes=true
all_rows_grp_follower=true
all_rows_goal_reached=true
all_rows_runtime_passed=true
phase12b_all_runtime_rows_passed=true
perception_backend=dummy
all_boundary_fields_false=true
carla_imported_by_wrapper=false
raw_runtime_evidence_committed=false
```

Benchmark boundary：

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

`lane_invasion_count_total=83` 是 sensor instrumentation record，不是 infraction benchmark score。Phase 12C-DUMMY 只證明 dummy backend + GRP route-following 在 calibrated smoke setting 中可完成五條 route。

## Validation

```powershell
python -m py_compile scripts\run_phase12c_dummy_runtime_confirmation.py
python scripts\run_phase12c_dummy_runtime_confirmation.py --dry-run --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

# Phase 12C-YOLO-U — YOLO Optional Dependency Unlock Prepared

## Status

```text
Phase 12C-YOLO-U Prepared - YOLO optional dependency unlock commands and evidence were written.
```

Phase 12C-YOLO-U 是 Phase 12C perception backend ablation 的 YOLO optional dependency unlock preparation。此階段只建立可審核的 dependency preflight、manual install command 與 post-install verification command，不自動安裝 `ultralytics`，也不把 YOLO 依賴加入 baseline requirements。

## Evidence

```text
experiments\phase12\20260629T030122Z
```

Generated files：

- `manifest.json`
- `summary.json`
- `commands.txt`
- `environment.json`
- `README.md`
- `raw_outputs/carla312_import_ultralytics.stdout.txt`
- `raw_outputs/carla312_import_ultralytics.stderr.txt`
- `raw_outputs/carla312_pip_show_ultralytics.stdout.txt`
- `raw_outputs/carla312_pip_show_ultralytics.stderr.txt`
- `raw_outputs/carla312_edge_yolo_smoke.stdout.txt`
- `raw_outputs/carla312_edge_yolo_smoke.stderr.txt`

## Preflight Result

```text
status=yolo_optional_dependency_unlock_prepared
dependency_ready=false
dependency_missing=true
manual_unlock_required=true
target_python_exists=true
carla_root_exists=true
auto_install_performed=false
baseline_requirements_modified=false
runtime_confirmation_executed=false
```

Target runtime：

```text
target_python=D:\CARLA\envs\ma-vlna-carla312\python.exe
carla_root=D:\CARLA\packages\CARLA_0.9.16
package_spec=ultralytics>=8,<9
```

Observed checks：

```text
ultralytics_import_ready=false
ultralytics_pip_metadata_ready=false
edge_yolo_command_passed=true
edge_yolo_fallback_used=true
```

Interpretation：CARLA Python 3.12 environment 目前尚未安裝 `ultralytics`。`EdgePerception --test yolo` 仍可執行，但會 graceful fallback 到 `DummyPerceptionBackend`；這保留了系統穩定性，但不是 YOLO runtime validation。

## Manual Unlock Command

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install "ultralytics>=8,<9"
```

此命令必須由 operator 顯式執行；Phase 12C-YOLO-U runner 不會自動安裝套件。

## Post-Unlock Verification

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe -c "import importlib.util; available = importlib.util.find_spec('ultralytics') is not None; print(f'ultralytics_available={available}'); raise SystemExit(0 if available else 1)"
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip show ultralytics
D:\CARLA\envs\ma-vlna-carla312\python.exe -m workers.core.edge_perception --test yolo
python scripts\run_phase12c_perception_backend_ablation.py --perception-backend-mode yolo_optional --output-dir experiments\phase12
```

YOLO dependency ready 的最低條件：

```text
ultralytics_import_ready=true
ultralytics_pip_metadata_ready=true
edge_yolo_command_passed=true
edge_yolo_fallback_used=false
```

## Future Runtime Command

解鎖成功後，才可進入 YOLO runtime confirmation：

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --controller-mode grp_follower --perception-backend yolo --host 127.0.0.1 --port 2000 --town Town03 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --child-timeout-sec 2400 --output-dir experiments\phase12 --carla-root D:\CARLA\packages\CARLA_0.9.16
```

Phase 12C-YOLO-U 尚未執行此 runtime command。

## Boundary

```text
auto_install_performed=false
baseline_requirements_modified=false
runtime_confirmation_executed=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Phase 12C-YOLO-U 是 optional dependency unlock preparation，不是 YOLO runtime pass，不是 CARLA Leaderboard，不是 formal route benchmark，也不是 infraction benchmark。

## Validation

```powershell
python -m py_compile scripts\run_phase12c_yolo_optional_dependency_unlock.py
python scripts\run_phase12c_yolo_optional_dependency_unlock.py --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

# Walkthrough - Phase 12C-YOLOv9-B EdgePerception YOLOv9 Backend Adapter Prepared

1. Preserve Phase 12C-DUMMY as the only runtime-confirmed perception backend slice.
2. Keep Phase 12C-YOLOv9-U as dependency unlock preparation only.
3. Add an explicit `YOLOv9PerceptionBackend` adapter in `workers.core.edge_perception`.
4. Register `backend="yolov9"` in the `EdgePerception` backend factory.
5. Register `--test yolov9` in the module CLI.
6. Keep fallback behavior unchanged when the optional `yolov9` dependency is missing.
7. Do not auto-install YOLOv9 packages.
8. Do not add YOLOv9 to baseline requirements.
9. Do not start CARLA.
10. Do not execute YOLOv9 runtime confirmation.
11. Keep generated evidence local under `experiments\phase12`.

Generated evidence:

```text
yolov9_backend_adapter=experiments\phase12\20260629T063232Z-1-1
yolov9_unlock=experiments\phase12\20260629T063232Z
phase12c_matrix=experiments\phase12\20260629T063233Z
```

YOLOv9-B adapter result:

```text
adapter_prepared=true
edge_yolov9_backend_registered=true
base_edge_yolov9_command_supported=true
carla312_edge_yolov9_command_supported=true
base_edge_yolov9_command_passed=true
carla312_edge_yolov9_command_passed=true
base_edge_yolov9_fallback_used=true
carla312_edge_yolov9_fallback_used=true
dependency_ready=false
dependency_missing=true
runtime_confirmation_executed=false
```

Phase 12C matrix result:

```text
perception_backend_modes=dummy,rt_detr_optional,yolov9_optional
row_count=15
available_row_count=5
backend_unavailable_count=10
dummy rows=dry_run
yolov9_optional rows=backend_unavailable
rt_detr_optional rows=backend_unavailable
```

Manual unlock commands:

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install <YOLOV9_PACKAGE_SPEC>
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install -r <YOLOV9_REQUIREMENTS_PATH>
```

Post-unlock verification:

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe -c "import importlib.util; module='yolov9'; available = importlib.util.find_spec(module) is not None; print(f'yolov9_import_ready={available}'); raise SystemExit(0 if available else 1)"
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip show yolov9
D:\CARLA\envs\ma-vlna-carla312\python.exe -m workers.core.edge_perception --test yolov9
python scripts\run_phase12c_perception_backend_ablation.py --perception-backend-mode yolov9_optional --output-dir experiments\phase12
```

Ready condition:

```text
yolov9_import_ready=true
yolov9_pip_metadata_ready=true
edge_yolov9_command_supported=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
```

Boundary fields:

```text
auto_install_performed=false
baseline_requirements_modified=false
runtime_confirmation_executed=false
carla_server_started=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Validation checklist:

```text
python -m py_compile workers\core\edge_perception.py scripts\run_phase12c_yolov9_backend_adapter_checks.py scripts\run_phase12c_yolov9_optional_dependency_unlock.py scripts\run_phase12c_perception_backend_ablation.py scripts\run_phase11_carla_checks.py
python -m workers.core.edge_perception --test yolov9
D:\CARLA\envs\ma-vlna-carla312\python.exe -m workers.core.edge_perception --test yolov9
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

Phase 12C-YOLO-U was the earlier generic YOLO unlock preparation. Phase 12C-YOLOv9-U is the revised YOLOv9-specific dependency unlock target. Phase 12C-YOLOv9-B adds the EdgePerception adapter path but still does not claim YOLOv9 runtime verification.

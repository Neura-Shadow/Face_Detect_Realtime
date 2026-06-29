# Walkthrough - Phase 12C-YOLOv9-U YOLOv9 Optional Dependency Unlock Prepared

1. Use Phase 12C perception backend scaffold as the matrix boundary.
2. Replace the earlier generic `yolo_optional` target with `yolov9_optional`.
3. Keep `dummy` unchanged.
4. Keep `rt_detr_optional` unchanged.
5. Preserve Phase 12C-DUMMY as the only runtime-confirmed perception backend slice.
6. Target the dedicated CARLA Python 3.12 environment.
7. Check whether the YOLOv9 dependency module is importable.
8. Check whether YOLOv9 pip metadata is present.
9. Probe whether `EdgePerception --test yolov9` is supported.
10. Generate manual unlock and post-unlock verification commands.
11. Do not auto-install packages.
12. Do not start CARLA.
13. Do not execute YOLOv9 runtime confirmation.

Generated evidence:

```text
yolov9_unlock=experiments\phase12\20260629T034842Z
phase12c_matrix=experiments\phase12\20260629T034842Z-1
```

YOLOv9-U result:

```text
dependency_ready=false
dependency_missing=true
manual_unlock_required=true
yolov9_import_ready=false
yolov9_pip_metadata_ready=false
edge_yolov9_command_supported=false
edge_yolov9_command_passed=null
edge_yolov9_fallback_used=null
auto_install_performed=false
baseline_requirements_modified=false
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
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Validation checklist:

```text
python -m py_compile scripts\run_phase12c_yolov9_optional_dependency_unlock.py scripts\run_phase12c_perception_backend_ablation.py scripts\run_phase11_carla_checks.py
python scripts\run_phase12c_yolov9_optional_dependency_unlock.py --output-dir experiments\phase12
python scripts\run_phase12c_perception_backend_ablation.py --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

Phase 12C-YOLO-U was the earlier generic YOLO unlock preparation. Phase 12C-YOLOv9-U is the revised YOLOv9-specific target. Old evidence is not rewritten as YOLOv9 evidence.

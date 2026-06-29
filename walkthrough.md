# Walkthrough - Phase 12C-YOLO-U YOLO Optional Dependency Unlock Prepared

1. Use Phase 12C perception backend scaffold as the matrix boundary.
2. Keep YOLO optional as an optional dependency, not a baseline requirement.
3. Target the dedicated CARLA Python 3.12 environment.
4. Check whether `ultralytics` can be imported.
5. Check whether `pip show ultralytics` returns metadata.
6. Run `EdgePerception --test yolo` and record whether it falls back to Dummy.
7. Generate manual install and post-unlock verification commands.
8. Do not auto-install packages.
9. Do not execute YOLO runtime confirmation.
10. Preserve all benchmark boundary fields as false.

Generated evidence:

```text
experiments\phase12\20260629T030122Z
```

Preflight result:

```text
dependency_ready=false
dependency_missing=true
manual_unlock_required=true
ultralytics_import_ready=false
ultralytics_pip_metadata_ready=false
edge_yolo_command_passed=true
edge_yolo_fallback_used=true
auto_install_performed=false
baseline_requirements_modified=false
runtime_confirmation_executed=false
```

Manual unlock command:

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install "ultralytics>=8,<9"
```

Post-unlock verification:

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe -c "import importlib.util; available = importlib.util.find_spec('ultralytics') is not None; print(f'ultralytics_available={available}'); raise SystemExit(0 if available else 1)"
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip show ultralytics
D:\CARLA\envs\ma-vlna-carla312\python.exe -m workers.core.edge_perception --test yolo
python scripts\run_phase12c_perception_backend_ablation.py --perception-backend-mode yolo_optional --output-dir experiments\phase12
```

Ready condition:

```text
ultralytics_import_ready=true
ultralytics_pip_metadata_ready=true
edge_yolo_command_passed=true
edge_yolo_fallback_used=false
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
python -m py_compile scripts\run_phase12c_yolo_optional_dependency_unlock.py
python scripts\run_phase12c_yolo_optional_dependency_unlock.py --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

Phase 12C-YOLO-U prepares the dependency unlock only. It does not validate YOLO runtime behavior and does not upgrade MA-VLNA to a formal CARLA benchmark.

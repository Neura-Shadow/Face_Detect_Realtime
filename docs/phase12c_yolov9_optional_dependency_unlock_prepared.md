# Phase 12C-YOLOv9-U — YOLOv9 Optional Dependency Unlock Prepared

## Status

```text
Phase 12C-YOLOv9-U Prepared — YOLOv9 optional dependency unlock commands and evidence were written.
```

Phase 12C-YOLOv9-U revises the earlier generic Phase 12C-YOLO-U target into a YOLOv9-specific optional backend preparation. It does not rewrite the older generic YOLO-U evidence as YOLOv9 evidence.

This is YOLOv9 optional dependency preparation only. It does not validate YOLOv9 runtime, does not install dependencies automatically, does not modify baseline requirements, does not start CARLA, and does not replace Phase 12C-DUMMY runtime confirmation. YOLOv9 runtime confirmation is a later explicit phase.

## Evidence

```text
experiments\phase12\20260629T063232Z
```

Generated files:

- `manifest.json`
- `summary.json`
- `commands.txt`
- `environment.json`
- `README.md`
- `raw_outputs/carla312_import_yolov9_dependency.stdout.txt`
- `raw_outputs/carla312_import_yolov9_dependency.stderr.txt`
- `raw_outputs/carla312_pip_show_yolov9_dependency.stdout.txt`
- `raw_outputs/carla312_pip_show_yolov9_dependency.stderr.txt`
- `raw_outputs/carla312_edge_yolov9_support_probe.stdout.txt`
- `raw_outputs/carla312_edge_yolov9_support_probe.stderr.txt`

## Summary

```text
phase=Phase 12C-YOLOv9-U
status=yolov9_optional_dependency_unlock_prepared
target_python=D:\CARLA\envs\ma-vlna-carla312\python.exe
carla_root=D:\CARLA\packages\CARLA_0.9.16
perception_backend=yolov9
perception_backend_mode=yolov9_optional
dependency_ready=false
dependency_missing=true
manual_unlock_required=true
yolov9_import_ready=false
yolov9_pip_metadata_ready=false
edge_yolov9_command_supported=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=true
auto_install_performed=false
baseline_requirements_modified=false
runtime_confirmation_executed=false
```

Interpretation: Phase 12C-YOLOv9-B now exposes an `EdgePerception --test yolov9` path. The optional dependency is still missing, so the command passes through graceful fallback and records `edge_yolov9_fallback_used=true`. No YOLOv9 runtime claim is made.

Phase 12C-YOLOv9-V now provides the strict post-unlock verifier. Current local V evidence remains blocked because the CARLA Python 3.12 runtime still lacks the YOLOv9 dependency:

```text
experiments\phase12\20260629T124925Z
post_unlock_verified=false
strict_gate_exit_code=1
yolov9_import_ready=false
yolov9_pip_metadata_ready=false
edge_yolov9_fallback_used=true
```

## Manual Unlock Commands

Option A — package-based if supported by the selected YOLOv9 implementation:

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install <YOLOV9_PACKAGE_SPEC>
```

Option B — repository/manual install if required:

```powershell
# operator fills exact YOLOv9 install source
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install -r <YOLOV9_REQUIREMENTS_PATH>
```

The runner records these commands only. It does not execute them.

## Post-Unlock Verification

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe -c "import importlib.util; module='yolov9'; available = importlib.util.find_spec(module) is not None; print(f'yolov9_import_ready={available}'); raise SystemExit(0 if available else 1)"
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip show yolov9
D:\CARLA\envs\ma-vlna-carla312\python.exe -m workers.core.edge_perception --test yolov9
python scripts\run_phase12c_perception_backend_ablation.py --perception-backend-mode yolov9_optional --output-dir experiments\phase12
```

Ready condition for a future YOLOv9 runtime phase:

```text
yolov9_import_ready=true
yolov9_pip_metadata_ready=true
edge_yolov9_command_supported=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
```

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

Phase 12C-YOLOv9-U is not YOLOv9 runtime validation, not YOLOv9 model accuracy evidence, not RT-DETR runtime validation, not a full Phase 12C perception ablation runtime pass, not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

## Validation

```powershell
python -m py_compile scripts\run_phase12c_yolov9_optional_dependency_unlock.py scripts\run_phase12c_perception_backend_ablation.py scripts\run_phase11_carla_checks.py
python scripts\run_phase12c_yolov9_optional_dependency_unlock.py --output-dir experiments\phase12
python scripts\run_phase12c_perception_backend_ablation.py --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

# Current Task - Phase 12C-YOLOv9-B

## Status

```text
Phase 12C-YOLOv9-B Prepared - EdgePerception YOLOv9 backend adapter path is registered.
```

Maintained boundary:

```text
Phase 12C-YOLOv9-B is EdgePerception adapter preparation only. It does not validate YOLOv9 runtime, does not install dependencies automatically, does not modify baseline requirements, does not start CARLA, does not replace Phase 12C-DUMMY runtime confirmation, does not claim CARLA Leaderboard, formal route benchmark, or infraction benchmark, and does not commit raw experiment evidence.
```

## Target Runtime

```text
base_python=python
target_python=D:\CARLA\envs\ma-vlna-carla312\python.exe
carla_root=D:\CARLA\packages\CARLA_0.9.16
perception_backend=yolov9
perception_backend_mode=yolov9_optional
```

## Generated Local Evidence

- YOLOv9-B adapter output dir: `experiments\phase12\20260629T063232Z-1-1`.
- YOLOv9-U dependency unlock output dir: `experiments\phase12\20260629T063232Z`.
- Updated Phase 12C matrix output dir: `experiments\phase12\20260629T063233Z`.
- Generated output remains local and is not committed.

YOLOv9-B files:

- `manifest.json`
- `summary.json`
- `commands.txt`
- `environment.json`
- `README.md`
- `raw_outputs\base_import_yolov9_dependency.stdout.txt`
- `raw_outputs\base_import_yolov9_dependency.stderr.txt`
- `raw_outputs\carla312_import_yolov9_dependency.stdout.txt`
- `raw_outputs\carla312_import_yolov9_dependency.stderr.txt`
- `raw_outputs\base_edge_yolov9_adapter_smoke.stdout.txt`
- `raw_outputs\base_edge_yolov9_adapter_smoke.stderr.txt`
- `raw_outputs\carla312_edge_yolov9_adapter_smoke.stdout.txt`
- `raw_outputs\carla312_edge_yolov9_adapter_smoke.stderr.txt`

## Result

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
auto_install_performed=false
baseline_requirements_modified=false
carla_server_started=false
```

12C matrix:

```text
perception_backend_modes=dummy,rt_detr_optional,yolov9_optional
row_count=15
available_row_count=5
backend_unavailable_count=10
dummy rows=dry_run
yolov9_optional rows=backend_unavailable
rt_detr_optional rows=backend_unavailable
```

## Manual Unlock Commands

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install <YOLOV9_PACKAGE_SPEC>
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install -r <YOLOV9_REQUIREMENTS_PATH>
```

## Validation

- `python -m py_compile workers\core\edge_perception.py scripts\run_phase12c_yolov9_backend_adapter_checks.py scripts\run_phase12c_yolov9_optional_dependency_unlock.py scripts\run_phase12c_perception_backend_ablation.py scripts\run_phase11_carla_checks.py`: passed.
- `python scripts\run_phase12c_yolov9_backend_adapter_checks.py --output-dir experiments\phase12`: passed.
- `python scripts\run_phase12c_yolov9_optional_dependency_unlock.py --output-dir experiments\phase12`: passed.
- `python scripts\run_phase12c_perception_backend_ablation.py --output-dir experiments\phase12`: passed.
- Benchmark boundary fields remain false.

## Next Action

Run full regression checks, source commit boundary gate, then stage source-only files, commit, push to `codex/phase-11o-source-commit-boundary`, and update PR #1 while keeping it Draft/open/unmerged.

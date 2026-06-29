# Current Task - Phase 12C-YOLOv9-U

## Status

```text
Phase 12C-YOLOv9-U Prepared — YOLOv9 optional dependency unlock commands and evidence were written.
```

Maintained boundary:

```text
Phase 12C-YOLOv9-U is YOLOv9 optional dependency preparation only. It does not validate YOLOv9 runtime, does not install dependencies automatically, does not modify baseline requirements, does not start CARLA, does not replace Phase 12C-DUMMY runtime confirmation, does not claim CARLA Leaderboard, formal route benchmark, or infraction benchmark, and does not commit raw experiment evidence.
```

## Target Runtime

```text
target_python=D:\CARLA\envs\ma-vlna-carla312\python.exe
carla_root=D:\CARLA\packages\CARLA_0.9.16
perception_backend=yolov9
perception_backend_mode=yolov9_optional
```

## Generated Local Evidence

- YOLOv9-U output dir: `experiments\phase12\20260629T034842Z`.
- Updated Phase 12C matrix output dir: `experiments\phase12\20260629T034842Z-1`.
- Generated output remains local and is not committed.

YOLOv9-U files:

- `manifest.json`
- `summary.json`
- `commands.txt`
- `environment.json`
- `README.md`
- `raw_outputs\carla312_import_yolov9_dependency.stdout.txt`
- `raw_outputs\carla312_import_yolov9_dependency.stderr.txt`
- `raw_outputs\carla312_pip_show_yolov9_dependency.stdout.txt`
- `raw_outputs\carla312_pip_show_yolov9_dependency.stderr.txt`
- `raw_outputs\carla312_edge_yolov9_support_probe.stdout.txt`
- `raw_outputs\carla312_edge_yolov9_support_probe.stderr.txt`

## Result

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

- `python -m py_compile scripts\run_phase12c_yolov9_optional_dependency_unlock.py scripts\run_phase12c_perception_backend_ablation.py scripts\run_phase11_carla_checks.py`: passed.
- `python scripts\run_phase12c_yolov9_optional_dependency_unlock.py --output-dir experiments\phase12`: passed.
- `python scripts\run_phase12c_perception_backend_ablation.py --output-dir experiments\phase12`: passed.
- Benchmark boundary fields remain false.

## Next Action

Run full regression checks, source commit boundary gate, then stage source-only files, commit, push to `codex/phase-11o-source-commit-boundary`, and update PR #1 while keeping it Draft/open/unmerged.

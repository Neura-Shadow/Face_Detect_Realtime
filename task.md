# Current Task - Phase 12C-YOLO-U

## Status

```text
Phase 12C-YOLO-U Prepared - YOLO optional dependency unlock commands and evidence were written.
```

Maintained boundary:

```text
Phase 12C-YOLO-U is a YOLO optional dependency unlock preparation, not a YOLO runtime validation, RT-DETR runtime validation, CARLA Leaderboard result, formal route benchmark, infraction benchmark, merge, git tag, GitHub Release, CARLA package commit, Python venv commit, .env commit, runtime_logs commit, or raw experiment evidence commit.
```

## Target Runtime

```text
target_python=D:\CARLA\envs\ma-vlna-carla312\python.exe
carla_root=D:\CARLA\packages\CARLA_0.9.16
package_spec=ultralytics>=8,<9
perception_backend=yolo
```

## Generated Local Evidence

- Output dir: `experiments\phase12\20260629T030122Z`.
- Generated files:
  - `manifest.json`
  - `summary.json`
  - `commands.txt`
  - `environment.json`
  - `README.md`
  - `raw_outputs\carla312_import_ultralytics.stdout.txt`
  - `raw_outputs\carla312_import_ultralytics.stderr.txt`
  - `raw_outputs\carla312_pip_show_ultralytics.stdout.txt`
  - `raw_outputs\carla312_pip_show_ultralytics.stderr.txt`
  - `raw_outputs\carla312_edge_yolo_smoke.stdout.txt`
  - `raw_outputs\carla312_edge_yolo_smoke.stderr.txt`
- Generated output remains local and is not committed.

## Result

```text
dependency_ready=false
dependency_missing=true
manual_unlock_required=true
target_python_exists=true
carla_root_exists=true
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

## Validation

- `python -m py_compile scripts\run_phase12c_yolo_optional_dependency_unlock.py`: passed.
- `python scripts\run_phase12c_yolo_optional_dependency_unlock.py --output-dir experiments\phase12`: passed.
- Evidence JSON is valid.
- Commands are PowerShell-safe; the package spec is quoted.
- Benchmark boundary fields remain false.

## Next Action

Run full regression checks, source commit boundary gate, then stage source-only files, commit, push to `codex/phase-11o-source-commit-boundary`, and update PR #1 while keeping it Draft/open/unmerged.

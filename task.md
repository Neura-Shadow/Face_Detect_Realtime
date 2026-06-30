# Current Task - Phase 12C-YOLOv9-SRC-V

## Status

```text
Phase 12C-YOLOv9-SRC-V Passed — official YOLOv9 source adapter verified with no fallback in the CARLA Python 3.12 runtime.
```

Maintained boundary:

```text
Phase 12C-YOLOv9-SRC-V verifies source-root no-fallback readiness only. It does not commit YOLOv9 source, does not commit YOLOv9 weights, does not vendor YOLOv9 into this repository, does not modify baseline requirements, does not start CARLA, does not execute YOLOv9 route runtime confirmation, and does not claim CARLA Leaderboard, formal route benchmark, infraction benchmark, YOLOv9 accuracy, or YOLOv9 route runtime pass.
```

Phase distinction:

- Phase 12C-YOLOv9-SRC prepared the official external source adapter and no-fallback gate.
- Phase 12C-YOLOv9-SRC-V verified official source adapter no-fallback readiness in CARLA Python 3.12.
- Phase 12C-YOLOv9-RUNTIME is a future phase only and has not been executed.

## Operator Contract

```text
YOLOV9_ROOT=<path to official YOLOv9 source repository>
YOLOV9_WEIGHTS=<path to selected YOLOv9 weights>
target_python=D:\CARLA\envs\ma-vlna-carla312\python.exe
```

Example local setup, not committed:

```powershell
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install -r "$env:YOLOV9_ROOT\requirements.txt"
```

## Generated Local Evidence

- Source adapter verified evidence dir: `experiments\phase12\20260630T060621Z`.
- YOLOv9-only Phase 12C rows refresh dir: `experiments\phase12\20260630T060823Z`.
- Post-unlock external-source verified dir: `experiments\phase12\20260630T061015Z`.
- Generated output remains local and is not committed.

## Result

```text
source_adapter_verified=true
require_verified_requested=true
strict_gate_exit_code=0
YOLOV9_ROOT_configured=true
YOLOV9_WEIGHTS_configured=true
yolov9_source_root_ready=true
yolov9_weights_ready=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
post_unlock_verified=true
unlock_mode=external_source
phase12c_yolov9_rows_available=true
backend_unavailable_count=0
runtime_confirmation_executed=false
carla_route_runtime_executed=false
auto_install_performed=false
baseline_requirements_modified=false
carla_server_started=false
```

## Validation

- `python scripts\run_phase12c_yolov9_source_adapter_verification.py --output-dir experiments\phase12 --require-verified`: verified with exit code 0.
- `python scripts\run_phase12c_yolov9_post_unlock_verification.py --unlock-mode external_source --output-dir experiments\phase12 --require-verified`: verified with exit code 0.
- `python scripts\run_phase12c_perception_backend_ablation.py --perception-backend-mode yolov9_optional --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --output-dir experiments\phase12`: produced 5 YOLOv9 rows with `backend_unavailable_count=0`.
- Benchmark boundary fields remain false.

## Next Action

Run regression checks, source commit boundary gate, then stage source/docs only, commit, push to `codex/phase-11o-source-commit-boundary`, and update PR #1 while keeping it Draft/open/unmerged. Full YOLOv9 CARLA route runtime confirmation remains a future Phase 12C-YOLOv9-RUNTIME slice.

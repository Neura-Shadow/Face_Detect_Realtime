# Current Task - Phase 12C-YOLOv9-SRC

## Status

```text
Phase 12C-YOLOv9-SRC Prepared — official YOLOv9 external source adapter, environment contract, and no-fallback verification gate are implemented.
```

Maintained boundary:

```text
Phase 12C-YOLOv9-SRC prepares source-root integration and verification logic only. It does not commit YOLOv9 source, does not commit YOLOv9 weights, does not vendor YOLOv9 into this repository, does not modify baseline requirements, does not start CARLA, does not execute YOLOv9 route runtime confirmation, and does not claim CARLA Leaderboard, formal route benchmark, infraction benchmark, YOLOv9 accuracy, or YOLOv9 route runtime pass.
```

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

- YOLOv9-SRC source adapter verification output dir: `experiments\phase12\20260629T134856Z`.
- YOLOv9-V external-source post-unlock verification output dir: `experiments\phase12\20260629T134856Z-1`.
- YOLOv9-only Phase 12C source-adapter matrix refresh output dir: `experiments\phase12\20260629T134856Z-1-2`.
- Generated output remains local and is not committed.

## Result

```text
source_adapter_verified=false
strict_gate_exit_code=0
yolov9_source_root_configured=false
yolov9_weights_configured=false
yolov9_source_root_ready=false
yolov9_weights_ready=false
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=true
edge_yolov9_no_fallback_verified=false
runtime_confirmation_executed=false
auto_install_performed=false
baseline_requirements_modified=false
carla_server_started=false
```

## Strict Pass Condition

```text
yolov9_source_root_ready=true
yolov9_weights_ready=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
source_adapter_verified=true
```

## Validation

- `python scripts\run_phase12c_yolov9_source_adapter_verification.py --output-dir experiments\phase12`: produced structured local blocked evidence because `YOLOV9_ROOT` and `YOLOV9_WEIGHTS` are not configured.
- `python scripts\run_phase12c_perception_backend_ablation.py --perception-backend-mode yolov9_optional --output-dir experiments\phase12`: produced 5 YOLOv9 rows with `backend_unavailable`.
- Benchmark boundary fields remain false.

## Next Action

Run full regression checks, source commit boundary gate, then stage source-only files, commit, push to `codex/phase-11o-source-commit-boundary`, and update PR #1 while keeping it Draft/open/unmerged. Full YOLOv9 no-fallback verification remains pending until the operator provides official YOLOv9 source and weights through `YOLOV9_ROOT` and `YOLOV9_WEIGHTS`.

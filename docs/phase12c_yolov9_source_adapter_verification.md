# Phase 12C-YOLOv9-SRC — Official YOLOv9 Source Adapter Verification

## Status

```text
Phase 12C-YOLOv9-SRC Prepared — official YOLOv9 external source adapter, environment contract, and no-fallback verification gate are implemented.
```

This phase changes the YOLOv9 unlock contract from a fake `pip show yolov9` requirement to an operator-provided official source repository and weights path.

It does not commit YOLOv9 source, does not commit YOLOv9 weights, does not vendor YOLOv9 into this repository, does not start CARLA, does not execute YOLOv9 route runtime confirmation, and does not claim YOLOv9 model accuracy.

## Environment Contract

Operator-provided local assets:

```powershell
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install -r "$env:YOLOV9_ROOT\requirements.txt"
```

The repository only records the env var names:

```text
YOLOV9_ROOT=<path to official YOLOv9 source repository>
YOLOV9_WEIGHTS=<path to selected YOLOv9 weights>
```

Expected source entries:

```text
detect.py
detect_dual.py
models/
utils/
```

## Evidence

Latest local source-adapter verification evidence:

```text
experiments\phase12\20260629T134856Z
```

Latest YOLOv9-only Phase 12C matrix refresh using source-adapter availability:

```text
experiments\phase12\20260629T134856Z-1-2
```

Generated files:

- `manifest.json`
- `summary.json`
- `commands.txt`
- `environment.json`
- `README.md`
- `raw_outputs/`

## Verification Result

```text
phase=Phase 12C-YOLOv9-SRC
status=yolov9_source_adapter_blocked
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

Interpretation: the source adapter and strict gate are implemented, but this local environment has not provided `YOLOV9_ROOT` and `YOLOV9_WEIGHTS`, so no-fallback readiness remains blocked.

## Strict Pass Conditions

Strict mode can pass only when all of the following are true:

```text
yolov9_source_root_ready=true
yolov9_weights_ready=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
source_adapter_verified=true
```

Strict command:

```powershell
python scripts\run_phase12c_yolov9_source_adapter_verification.py --output-dir experiments\phase12 --require-verified
```

Then refresh Phase 12C YOLOv9 rows:

```powershell
python scripts\run_phase12c_perception_backend_ablation.py --perception-backend-mode yolov9_optional --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --output-dir experiments\phase12
```

## Boundary

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Phase 12C-YOLOv9-SRC is not YOLOv9 route runtime validation, not YOLOv9 accuracy evidence, not RT-DETR validation, not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

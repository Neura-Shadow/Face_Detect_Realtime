# Phase 12C-YOLOv9-U — YOLOv9 Optional Dependency Unlock Prepared

## Status

```text
Phase 12C-YOLOv9-U Prepared — YOLOv9 optional dependency unlock commands and evidence were written.
```

Phase 12C-YOLOv9-U revises the earlier generic Phase 12C-YOLO-U target into a YOLOv9-specific optional backend preparation. It does not rewrite the older generic YOLO-U evidence as YOLOv9 evidence.

This is YOLOv9 optional dependency preparation only. Phase 12C-YOLOv9-SRC revises the official path to an external source-root contract using `YOLOV9_ROOT` and `YOLOV9_WEIGHTS`. It does not validate YOLOv9 runtime, does not install dependencies automatically, does not modify baseline requirements, does not start CARLA, and does not replace Phase 12C-DUMMY runtime confirmation. YOLOv9 runtime confirmation is a later explicit phase.

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

Interpretation: Phase 12C-YOLOv9-B now exposes an `EdgePerception --test yolov9` path. The official source-root contract is still not configured locally, so the command passes through graceful fallback and records `edge_yolov9_fallback_used=true`. No YOLOv9 runtime claim is made.

## Official Source Adapter Contract

Phase 12C-YOLOv9-SRC prepares the official external source adapter:

```text
Phase 12C-YOLOv9-SRC Prepared — official YOLOv9 external source adapter, environment contract, and no-fallback verification gate are implemented.
```

Operator-provided local assets:

```powershell
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install -r "$env:YOLOV9_ROOT\requirements.txt"
python scripts\run_phase12c_yolov9_source_adapter_verification.py --output-dir experiments\phase12 --require-verified
```

YOLOv9 source and weights remain outside this repository and are not committed.

Phase 12C-YOLOv9-V now provides the strict post-unlock verifier. Current local V/SRC evidence remains blocked because the CARLA Python 3.12 runtime has not been given `YOLOV9_ROOT` and `YOLOV9_WEIGHTS`:

```text
authoritative_evidence_dir=experiments\phase12\20260629T125701Z
historical_strict_evidence_dir=experiments\phase12\20260629T124925Z
post_unlock_verified=false
strict_gate_exit_code=1
yolov9_import_ready=false
yolov9_pip_metadata_ready=false
edge_yolov9_fallback_used=true
source_adapter_evidence_dir=experiments\phase12\20260629T134856Z
source_adapter_verified=false
```

## Manual Unlock Commands

Option A — official external source-root setup:

```powershell
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install -r "$env:YOLOV9_ROOT\requirements.txt"
```

Option B — package-based only if the selected alternate implementation supports it:

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install <YOLOV9_PACKAGE_SPEC>
```

The runner records these commands only. It does not execute them.

## Post-Unlock Verification

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe -m workers.core.edge_perception --test yolov9
python scripts\run_phase12c_yolov9_source_adapter_verification.py --output-dir experiments\phase12 --require-verified
python scripts\run_phase12c_perception_backend_ablation.py --perception-backend-mode yolov9_optional --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --output-dir experiments\phase12
```

Ready condition for a future YOLOv9 runtime phase:

```text
yolov9_source_root_ready=true
yolov9_weights_ready=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
source_adapter_verified=true
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

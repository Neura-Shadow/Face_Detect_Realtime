# Phase 12C-R1-RT-DETR-ASSET-SETUP - Dependency and Local Asset Gate

## Status

```text
Phase 12C-R1-RT-DETR-ASSET-SETUP Command-Ready - explicit RT-DETR setup commands and asset contract are written, but setup was not executed.
```

This phase follows the blocked RT-DETR unlock gate. It prepares the CARLA Python 3.12 runtime setup path for RT-DETR without silently installing dependencies, downloading model weights, changing baseline requirements, or starting CARLA route runtime.

## Evidence

```text
rtdetr_asset_setup_evidence_dir=experiments\phase12\20260702T040554Z
rtdetr_unlock_evidence_dir=experiments\phase12\20260702T022636Z-1
lightweight_evidence_dir=experiments\phase12\20260701T165325Z
target_perception_backend=rtdetr
runtime_scope=rtdetr_dependency_asset_setup_only
```

## Current Setup Result

```text
status=command_ready
ultralytics_import_ready_before=false
ultralytics_import_ready_after=false
dependency_install_requested=false
dependency_install_executed=false
rtdetr_weights_configured=false
rtdetr_weights_ready=false
edge_rtdetr_command_passed=null
edge_rtdetr_fallback_used=null
edge_rtdetr_no_fallback_verified=false
phase12c_rtdetr_rows_available=false
recommended_next_phase=R1-RT-DETR-ASSET-SETUP
```

The setup gate wrote auditable commands and a local asset contract. It did not execute dependency installation because `--execute-dependency-install` was not provided, and it did not run post-setup smoke because dependency and weights are not ready.

## Operator Commands

Dry-run / command scaffold:

```powershell
python scripts\run_phase12c_rtdetr_asset_setup.py --dry-run --output-dir experiments\phase12 --rtdetr-unlock-evidence-dir experiments\phase12\20260702T022636Z-1
```

Audit current local setup:

```powershell
python scripts\run_phase12c_rtdetr_asset_setup.py --output-dir experiments\phase12 --rtdetr-unlock-evidence-dir experiments\phase12\20260702T022636Z-1 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --carla-root D:\CARLA\packages\CARLA_0.9.16
```

Prepare asset directory only:

```powershell
python scripts\run_phase12c_rtdetr_asset_setup.py --output-dir experiments\phase12 --prepare-asset-dir --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --carla-root D:\CARLA\packages\CARLA_0.9.16
```

Explicit dependency install:

```powershell
python scripts\run_phase12c_rtdetr_asset_setup.py --output-dir experiments\phase12 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --carla-root D:\CARLA\packages\CARLA_0.9.16 --execute-dependency-install
```

Optional requirements file install:

```powershell
python scripts\run_phase12c_rtdetr_asset_setup.py --output-dir experiments\phase12 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --carla-root D:\CARLA\packages\CARLA_0.9.16 --execute-dependency-install --rtdetr-requirements D:\AIModels\rtdetr\requirements.txt
```

Operator-provided local weights:

```powershell
$env:RTDETR_WEIGHTS = "D:\AIModels\rtdetr\rtdetr-l.pt"
$env:RTDETR_MODEL_HINT = "rtdetr-l.pt"
$env:RTDETR_DEVICE = "auto"
$env:RTDETR_IMG_SIZE = "640"
```

Post-setup EdgePerception smoke:

```powershell
python scripts\run_phase12c_rtdetr_asset_setup.py --output-dir experiments\phase12 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --carla-root D:\CARLA\packages\CARLA_0.9.16 --run-post-setup-smoke
```

## Boundary

```text
baseline_requirements_modified=false
auto_install_performed=false
operator_explicit_install_required=true
weights_downloaded=false
weights_committed=false
carla_server_started=false
runtime_confirmation_executed=false
carla_route_runtime_executed=false
rtdetr_runtime_verified=false
rtdetr_accuracy_verified=false
selected_route_completion_verified=false
full_phase12c_perception_ablation_runtime_pass=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

RT-DETR weights are operator-provided local assets. They are not downloaded, copied into the repository, committed, or treated as release artifacts by this phase. Dependency installation requires an explicit operator command and is isolated to the CARLA Python 3.12 runtime.

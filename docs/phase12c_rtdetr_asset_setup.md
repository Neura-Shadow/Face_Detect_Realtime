# Phase 12C-R1-RT-DETR-ASSET-SETUP / ASSET-EXEC / WEIGHTS-LOCAL - Dependency and Local Asset Gate

## Status

```text
Phase 12C-R1-RT-DETR-ASSET-BLOCKER-FREEZE Completed - RT-DETR branch is formally frozen as external local-weight blocked and Phase 12C summary handoff is prepared.
```

This phase follows the blocked RT-DETR unlock gate. ASSET-SETUP first prepared the CARLA Python 3.12 runtime setup path without executing install commands. ASSET-EXEC then explicitly executed the operator-approved dependency install into the target CARLA Python 3.12 runtime. WEIGHTS-LOCAL verifies the operator-provided weight path and runs smoke only when the local file exists.

## ASSET-BLOCKER-FREEZE Result

```text
rt_detr_branch_frozen_external_asset_blocker=true
rtdetr_dependency_ready=true
ultralytics_import_ready_after=true
ultralytics_version_after=8.4.84
rtdetr_weights_configured=true
rtdetr_weights_ready=false
missing_weight_path=D:\AIModels\rtdetr\rtdetr-l.pt
rtdetr_no_fallback_ready=false
post_setup_smoke_executed=false
edge_rtdetr_no_fallback_verified=false
phase12c_rtdetr_rows_available=false
recommended_next_phase_without_weights=Phase 12C-SUM
recommended_next_phase_if_weights_available=R1-RT-DETR-WEIGHTS-LOCAL-RERUN
```

WEIGHTS-LOCAL and WEIGHTS-LOCAL-RERUN both correctly stopped before smoke because local weights are missing. No no-fallback readiness is claimed, no RT-DETR rows are available, and the RT-DETR branch is frozen until the operator provides `D:\AIModels\rtdetr\rtdetr-l.pt`.

## Evidence

```text
rtdetr_weights_local_evidence_dir=experiments\phase12\20260702T125105Z
rtdetr_asset_exec_evidence_dir=experiments\phase12\20260702T044516Z
rtdetr_asset_setup_evidence_dir=experiments\phase12\20260702T040554Z
rtdetr_unlock_evidence_dir=experiments\phase12\20260702T022636Z-1
lightweight_evidence_dir=experiments\phase12\20260701T165325Z
target_perception_backend=rtdetr
```

## WEIGHTS-LOCAL Result

```text
phase=Phase 12C-R1-RT-DETR-WEIGHTS-LOCAL
status=blocked
runtime_scope=rtdetr_local_weight_adoption_no_fallback_smoke_only
ultralytics_import_ready_after=true
ultralytics_version_after=8.4.84
dependency_install_requested=false
dependency_install_executed=false
dependency_install_exit_code=null
rtdetr_weights_configured=true
rtdetr_weights_ready=false
rtdetr_weights_path=D:\AIModels\rtdetr\rtdetr-l.pt
missing_weight_path=D:\AIModels\rtdetr\rtdetr-l.pt
rtdetr_weights_size_bytes=null
rtdetr_weights_sha256=null
post_setup_smoke_executed=false
edge_rtdetr_command_passed=null
edge_rtdetr_fallback_used=null
edge_rtdetr_no_fallback_verified=false
phase12c_rtdetr_rows_available=false
phase12c_rtdetr_backend_unavailable_count=5
recommended_next_phase=R1-RT-DETR-ASSET-SETUP
```

The target runtime can import `ultralytics`, but the local operator-provided file `D:\AIModels\rtdetr\rtdetr-l.pt` is still missing. No post-setup smoke or RT-DETR-only rows refresh was executed.

## ASSET-EXEC Result

```text
phase=Phase 12C-R1-RT-DETR-ASSET-EXEC
status=blocked
runtime_scope=rtdetr_dependency_asset_setup_execution_only
ultralytics_import_ready_before=false
ultralytics_import_ready_after=true
ultralytics_version_after=8.4.84
dependency_install_requested=true
dependency_install_executed=true
dependency_install_exit_code=0
rtdetr_weights_configured=true
rtdetr_weights_ready=false
rtdetr_weights_path=D:\AIModels\rtdetr\rtdetr-l.pt
post_setup_smoke_executed=false
edge_rtdetr_command_passed=null
edge_rtdetr_fallback_used=null
edge_rtdetr_no_fallback_verified=false
phase12c_rtdetr_rows_available=false
phase12c_rtdetr_backend_unavailable_count=5
recommended_next_phase=R1-RT-DETR-ASSET-SETUP
```

The explicit dependency install succeeded and the target runtime can import `ultralytics`. The run remains blocked because `D:\AIModels\rtdetr\rtdetr-l.pt` is still missing. Post-setup EdgePerception smoke was not executed because dependency and local weights were not both ready.

## ASSET-SETUP Result

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

WEIGHTS-LOCAL local weight audit:

```powershell
python scripts\run_phase12c_rtdetr_asset_setup.py --output-dir experiments\phase12 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --carla-root D:\CARLA\packages\CARLA_0.9.16 --verify-local-weights --rtdetr-unlock-evidence-dir experiments\phase12\20260702T022636Z-1
```

WEIGHTS-LOCAL smoke and row-refresh gate:

```powershell
python scripts\run_phase12c_rtdetr_asset_setup.py --output-dir experiments\phase12 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --carla-root D:\CARLA\packages\CARLA_0.9.16 --verify-local-weights --run-post-setup-smoke --refresh-rtdetr-rows-if-smoke-passed --rtdetr-unlock-evidence-dir experiments\phase12\20260702T022636Z-1
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

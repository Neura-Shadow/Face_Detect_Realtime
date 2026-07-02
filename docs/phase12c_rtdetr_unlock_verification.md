# Phase 12C-R1-RT-DETR-UNLOCK - Optional Backend Readiness Gate

## Status

```text
Phase 12C-R1-RT-DETR-UNLOCK Blocked - RT-DETR optional backend could not be verified because dependency or model assets are unavailable.
```

This phase moves beyond the YOLOv9 lightweight blocker into a separate RT-DETR optional backend readiness gate. It verifies dependency, operator-provided weights, EdgePerception command support, no-fallback behavior, and Phase 12C RT-DETR-only row availability. It does not start CARLA route runtime.

## Evidence

```text
rtdetr_unlock_evidence_dir=experiments\phase12\20260702T022636Z-1
rtdetr_unlock_dry_run_evidence_dir=experiments\phase12\20260702T022636Z
lightweight_evidence_dir=experiments\phase12\20260701T165325Z
latency_opt_evidence_dir=experiments\phase12\20260701T115744Z
route_id=route_01
controller_mode=grp_follower
previous_perception_backend=yolov9
target_perception_backend=rtdetr
runtime_scope=rtdetr_optional_backend_unlock_no_fallback_readiness
recommended_from_previous_phase=R1-RT-DETR-UNLOCK
```

## Readiness Result

```text
ultralytics_import_ready=false
ultralytics_version=null
rtdetr_weights_configured=false
rtdetr_weights_ready=false
rtdetr_model_hint=rtdetr-l.pt
edge_rtdetr_backend_registered=true
edge_rtdetr_command_supported=true
edge_rtdetr_command_passed=true
edge_rtdetr_fallback_used=true
edge_rtdetr_no_fallback_verified=false
phase12c_rtdetr_rows_available=false
phase12c_rtdetr_backend_unavailable_count=5
recommended_next_phase=R1-RT-DETR-ASSET-SETUP
blocked_reason=dependency_missing; weights_missing; fallback_used; rtdetr_rows_unavailable
```

The CARLA Python 3.12 runtime could not import `ultralytics`, and no local RT-DETR weights were configured through `RTDETR_WEIGHTS`. The EdgePerception CLI path is registered and command-supported, but it correctly fell back to `DummyPerceptionBackend`; therefore no-fallback readiness is not verified.

## RT-DETR Asset Contract

Operator-provided assets remain external to the repository:

```powershell
$env:RTDETR_WEIGHTS = "D:\AIModels\rtdetr\rtdetr-l.pt"
$env:RTDETR_MODEL_HINT = "rtdetr-l.pt"
$env:RTDETR_DEVICE = "auto"
$env:RTDETR_IMG_SIZE = "640"  # optional
```

The verifier does not download weights, does not install dependencies, does not modify baseline requirements, and does not copy weights into this repository.

## Commands

Dry-run:

```powershell
python scripts\run_phase12c_rtdetr_unlock_verification.py --dry-run --output-dir experiments\phase12
```

Strict verification:

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_rtdetr_unlock_verification.py --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --require-verified
```

RT-DETR-only rows refresh:

```powershell
python scripts\run_phase12c_perception_backend_ablation.py --perception-backend-mode rt_detr_optional --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --output-dir experiments\phase12
```

## Boundary

```text
auto_install_performed=false
baseline_requirements_modified=false
carla_server_started=false
runtime_confirmation_executed=false
carla_route_runtime_executed=false
rtdetr_runtime_verified=false
rtdetr_accuracy_verified=false
yolo_runtime_row_verified=false
selected_route_completion_verified=false
full_phase12c_perception_ablation_runtime_pass=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

This phase is RT-DETR unlock / no-fallback readiness only. It is not an RT-DETR route runtime pass, not route completion, not RT-DETR accuracy verification, not a YOLOv9 route pass, not full Phase 12C ablation, not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

## Follow-Up - RT-DETR-ASSET-SETUP

```text
Phase 12C-R1-RT-DETR-ASSET-SETUP Command-Ready - explicit RT-DETR setup commands and asset contract are written, but setup was not executed.
```

```text
rtdetr_asset_setup_evidence_dir=experiments\phase12\20260702T040554Z
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

The follow-up setup gate remains dependency and local asset setup only. It does not silently install dependencies, download or commit RT-DETR weights, modify baseline requirements, start CARLA route runtime, verify RT-DETR accuracy, or claim full Phase 12C ablation / Leaderboard / formal route / infraction benchmark evidence.

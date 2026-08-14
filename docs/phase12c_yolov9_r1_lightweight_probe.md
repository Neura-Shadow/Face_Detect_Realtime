# Phase 12C-YOLOv9-R1-YOLOv9-LIGHTWEIGHT - Lightweight Feasibility Probe

## Status

```text
Phase 12C-YOLOv9-R1-YOLOv9-LIGHTWEIGHT Blocked - lightweight YOLOv9 probe could not produce bounded no-fallback route-loop timing evidence.
```

This phase extends the R1-LATENCY-OPT no-improvement result with an operator-provided lightweight YOLOv9 asset contract. It does not download weights, vendor YOLOv9 source, modify baseline requirements, or reinterpret lightweight timing evidence as route completion.

## Evidence

```text
lightweight_evidence_dir=experiments\phase12\20260701T165325Z
lightweight_dry_run_evidence_dir=experiments\phase12\20260701T165245Z
latency_opt_evidence_dir=experiments\phase12\20260701T115744Z
latency_evidence_dir=experiments\phase12\20260701T103721Z
short_route_begin_evidence_dir=experiments\phase12\20260701T064944Z
setup_evidence_dir=experiments\phase12\20260701T045047Z
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
source_adapter_verified=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
setup_probe_passed=true
short_route_begin_verified=true
latency_probe_completed=true
latency_opt_completed=true
lightweight_weights_configured=false
lightweight_weights_ready=false
variant_count=7
executed_variant_count=0
completed_variant_count=0
blocked_variant_count=5
best_variant_id=null
best_variant_profile=null
best_variant_effective_fps=null
best_variant_yolov9_avg_ms=null
best_avg_ms_improvement_vs_latency_pct=null
best_avg_ms_improvement_vs_opt_pct=null
best_fps_improvement_vs_opt_pct=null
lightweight_bottleneck_classification=lightweight_weights_missing
useful_lightweight_profile_verified=false
lightweight_probe_completed=false
recommended_next_phase=R1-RT-DETR-UNLOCK
```

The baseline YOLOv9 source adapter still verifies no fallback in the CARLA Python 3.12 runtime. The lightweight probe is blocked because `YOLOV9_LIGHTWEIGHT_WEIGHTS` was not configured and no operator-provided lightweight weight file was available.

## Asset Contract

```powershell
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"
$env:YOLOV9_LIGHTWEIGHT_WEIGHTS = "D:\AIModels\yolov9\<operator_provided_lightweight_weights>.pt"
$env:YOLOV9_LIGHTWEIGHT_PROFILE = "yolov9_lightweight"
```

`YOLOV9_LIGHTWEIGHT_WEIGHTS` must point to a local file supplied by the operator. The runner does not download, copy, vendor, or commit this asset.

## Variants

```text
variant_01_baseline_recheck=prepared
variant_02_lightweight_default=blocked: lightweight_weights_missing
variant_03_lightweight_imgsz_512=blocked: lightweight_weights_missing
variant_04_lightweight_imgsz_416=blocked: lightweight_weights_missing
variant_05_lightweight_stride_5_cached=blocked: lightweight_weights_missing
variant_06_lightweight_half=blocked: lightweight_weights_missing
variant_07_dummy_reference=prepared
```

No lightweight route-loop variant executed because the lightweight asset contract was not satisfied.

## Boundary

R1-YOLOv9-LIGHTWEIGHT is lightweight runtime feasibility evidence only. It does not claim selected YOLOv9 route runtime pass, route completion, YOLOv9 model accuracy, full Phase 12C perception ablation runtime pass, RT-DETR runtime verification, CARLA Leaderboard, formal route benchmark, or infraction benchmark.

Lightweight weights/profile remain diagnostic-only unless a later phase promotes them.

## Follow-Up: RT-DETR Unlock

The next branch is RT-DETR unlock, not another YOLOv9 runtime claim. Phase 12C-R1-RT-DETR-UNLOCK produced blocked evidence at `experiments\phase12\20260702T022636Z-1`:

```text
target_perception_backend=rtdetr
ultralytics_import_ready=false
rtdetr_weights_configured=false
rtdetr_weights_ready=false
edge_rtdetr_command_supported=true
edge_rtdetr_command_passed=true
edge_rtdetr_fallback_used=true
edge_rtdetr_no_fallback_verified=false
phase12c_rtdetr_backend_unavailable_count=5
recommended_next_phase=R1-RT-DETR-ASSET-SETUP
```

RT-DETR weights remain operator-provided local assets and are not committed. This follow-up does not start CARLA route runtime, does not claim RT-DETR accuracy, and does not claim full Phase 12C ablation or benchmark pass.

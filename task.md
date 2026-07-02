# Current Task - Phase 12C-R1-RT-DETR-UNLOCK

## Latest Status

```text
Phase 12C-R1-RT-DETR-UNLOCK Blocked - RT-DETR optional backend could not be verified because dependency or model assets are unavailable.
```

Maintained boundary:

```text
Phase 12C-R1-RT-DETR-UNLOCK is RT-DETR unlock / no-fallback readiness only. It does not start CARLA route runtime, does not claim RT-DETR route runtime pass, does not claim RT-DETR accuracy, and does not claim full Phase 12C perception ablation runtime pass, CARLA Leaderboard, formal route benchmark, or infraction benchmark.
```

## Latest Evidence

```text
rtdetr_unlock_evidence_dir=experiments\phase12\20260702T022636Z-1
rtdetr_unlock_dry_run_evidence_dir=experiments\phase12\20260702T022636Z
lightweight_evidence_dir=experiments\phase12\20260701T165325Z
route_id=route_01
controller_mode=grp_follower
previous_perception_backend=yolov9
target_perception_backend=rtdetr
recommended_from_previous_phase=R1-RT-DETR-UNLOCK
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
runtime_confirmation_executed=false
carla_route_runtime_executed=false
rtdetr_runtime_verified=false
rtdetr_accuracy_verified=false
yolo_runtime_row_verified=false
selected_route_completion_verified=false
full_phase12c_perception_ablation_runtime_pass=false
blocked_reason=dependency_missing; weights_missing; fallback_used; rtdetr_rows_unavailable
```

The RT-DETR command path is registered, but the CARLA Python 3.12 runtime cannot import `ultralytics`, and no local `RTDETR_WEIGHTS` asset is configured. EdgePerception therefore falls back, and RT-DETR rows remain unavailable.

## Previous Phase - R1-YOLOv9-LIGHTWEIGHT

```text
Phase 12C-YOLOv9-R1-YOLOv9-LIGHTWEIGHT Blocked - lightweight YOLOv9 probe could not produce bounded no-fallback route-loop timing evidence.
```

```text
lightweight_evidence_dir=experiments\phase12\20260701T165325Z
lightweight_dry_run_evidence_dir=experiments\phase12\20260701T165245Z
lightweight_weights_configured=false
lightweight_weights_ready=false
lightweight_bottleneck_classification=lightweight_weights_missing
useful_lightweight_profile_verified=false
recommended_next_phase=R1-RT-DETR-UNLOCK
```

## Previous Phase - R1-LATENCY-OPT

```text
Phase 12C-YOLOv9-R1-LATENCY-OPT No-Improvement - optimization probe completed, but YOLOv9 forward latency remains too high for route completion.
```

```text
latency_opt_evidence_dir=experiments\phase12\20260701T115744Z
useful_latency_improvement_verified=false
best_variant_id=variant_01_baseline_recheck
best_variant_yolov9_avg_ms=2194.8
best_variant_effective_fps=0.168392
recommended_next_phase=R1-YOLOv9-LIGHTWEIGHT
```

## Previous Phase - R1-LATENCY

## Status

```text
Phase 12C-YOLOv9-R1-LATENCY Completed - selected YOLOv9 route-loop latency and cadence evidence produced without claiming route completion.
```

Maintained boundary:

```text
Phase 12C-YOLOv9-R1-LATENCY is latency and cadence evidence only. It does not claim selected YOLOv9 route runtime pass, route completion, YOLOv9 model accuracy, full Phase 12C perception ablation runtime pass, RT-DETR runtime verification, CARLA Leaderboard, formal route benchmark, or infraction benchmark.
```

## Background

```text
short_route_begin_evidence_dir=experiments\phase12\20260701T064944Z
setup_evidence_dir=experiments\phase12\20260701T045047Z
diagnostic_evidence_dir=experiments\phase12\20260630T150500Z
previous_runtime_evidence_dir=experiments\phase12\20260630T134322Z
```

R1-SHORT proved that the selected row enters the closed-loop route loop and emits early YOLOv9 no-fallback breadcrumbs. R1-LATENCY profiles route-loop speed, inference timing components, and diagnostic cadence behavior before any later route-completion attempt.

## Selected Row

```text
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
```

## Generated Local Evidence

```text
latency_evidence_dir=experiments\phase12\20260701T103721Z
dry_run_evidence_dir=experiments\phase12\20260701T102823Z
```

Generated runtime output remains local and is not committed.

## Top-Level Result

```text
variant_count=4
executed_variant_count=2
completed_variant_count=1
blocked_variant_count=1
best_variant_id=variant_01_current_cadence
best_variant_effective_fps=0.239313
best_variant_yolov9_avg_ms=2522.06
baseline_current_cadence_yolov9_avg_ms=2522.06
latency_bottleneck_classification=yolov9_forward_dominant
recommended_next_phase=R1-LATENCY-OPT
latency_probe_completed=true
```

## Executed Variants

### variant_01_current_cadence

```text
diagnostic_steps_completed=50
duration_sec=208.931
effective_fps=0.239313
world_tick_count=50
rgb_frame_received_count=50
edge_perception_call_count=50
yolov9_inference_call_count=50
cached_perception_result_count=0
real_inference_ratio=1.0
edge_yolov9_fallback_used_during_route=false
partial_route_progress_seen=true
yolov9_preprocess_ms_avg=6.8
yolov9_model_forward_ms_avg=2512.84
yolov9_nms_ms_avg=2.84
yolov9_postprocess_ms_avg=0.0
yolov9_total_inference_ms_avg=2522.06
yolov9_total_inference_ms_p95=7014.8
latency_bottleneck_classification=yolov9_forward_dominant
```

### variant_02_stride_5_cached

```text
diagnostic_steps_completed=1
duration_sec=206.497
effective_fps=0.004843
world_tick_count=0
rgb_frame_received_count=0
edge_perception_call_count=0
yolov9_inference_call_count=0
partial_route_progress_seen=false
latency_bottleneck_classification=timeout_before_latency_profile
```

Stride-5 cached mode did not produce a valid route-loop latency profile in this run, so cache/cadence improvement is not yet verified.

## Implementation

```text
latency_wrapper=scripts\run_phase12c_yolov9_r1_latency_probe.py
diagnostic_stride_flags=workers\CARLA_Closed_Loop_Agent.py + scripts\run_phase11m_grp_route_following.py + scripts\run_phase12b_controller_ablation_experiment.py + scripts\run_phase12c_yolov9_runtime_timeout_diagnosis.py
documentation=docs\phase12c_yolov9_r1_latency_probe.md
```

Diagnostic stride/cache behavior is optional and disabled by default:

```text
perception_inference_stride=1
reuse_last_perception_between_inference=false
```

## Commands

Dry-run:

```powershell
python scripts\run_phase12c_yolov9_r1_latency_probe.py --dry-run --output-dir experiments\phase12
```

Latency probe:

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_yolov9_r1_latency_probe.py --route-id route_01 --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --short-route-begin-evidence-dir experiments\phase12\20260701T064944Z --setup-evidence-dir experiments\phase12\20260701T045047Z --require-yolov9-ready --require-setup-passed --require-short-route-begin-passed --child-timeout-sec 600 --parent-timeout-sec 2400
```

## Boundary Fields

```text
yolo_runtime_row_verified=false
selected_route_completion_verified=false
full_phase12c_perception_ablation_runtime_pass=false
rt_detr_runtime_verified=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

## Next Safe Step

The recommended next phase is `R1-LATENCY-OPT`, focused on YOLOv9 forward-path latency reduction or stronger diagnostic cadence isolation. A route-completion attempt remains premature from this evidence.

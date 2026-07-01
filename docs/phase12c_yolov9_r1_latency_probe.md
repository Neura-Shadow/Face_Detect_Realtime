# Phase 12C-YOLOv9-R1-LATENCY - Route-Loop Latency and Cadence Probe

## Status

```text
Phase 12C-YOLOv9-R1-LATENCY Completed - selected YOLOv9 route-loop latency and cadence evidence produced without claiming route completion.
```

R1-LATENCY profiles the same selected row after R1-SHORT:

```text
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
short_route_begin_evidence_dir=experiments\phase12\20260701T064944Z
setup_evidence_dir=experiments\phase12\20260701T045047Z
latency_evidence_dir=experiments\phase12\20260701T103721Z
```

## Purpose

R1-SHORT proved that the selected YOLOv9 row can enter the closed-loop route loop and emit early no-fallback inference breadcrumbs. R1-LATENCY answers the next engineering question: whether the route loop is speed-limited by YOLOv9 inference latency, and whether diagnostic-only cadence/cached-result strategies should be explored before a later route-completion attempt.

This phase measures latency and cadence only. It does not require route completion, goal reach, full horizon completion, model accuracy, formal benchmark criteria, or CARLA Leaderboard criteria.

## Runtime Command

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_yolov9_r1_latency_probe.py --route-id route_01 --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --short-route-begin-evidence-dir experiments\phase12\20260701T064944Z --setup-evidence-dir experiments\phase12\20260701T045047Z --require-yolov9-ready --require-setup-passed --require-short-route-begin-passed --child-timeout-sec 600 --parent-timeout-sec 2400
```

Dry-run:

```powershell
python scripts\run_phase12c_yolov9_r1_latency_probe.py --dry-run --output-dir experiments\phase12
```

## Summary

```text
latency_evidence_dir=experiments\phase12\20260701T103721Z
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

## Variant Results

### variant_01_current_cadence

```text
diagnostic_steps_requested=50
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
last_route_progress_pct=0.0
last_distance_to_goal_m=315.651759
last_collision_count=0
last_lane_invasion_count=2
child_exit_code=0
latency_bottleneck_classification=yolov9_forward_dominant
```

YOLOv9 timing:

```text
yolov9_preprocess_ms_avg=6.8
yolov9_model_forward_ms_avg=2512.84
yolov9_nms_ms_avg=2.84
yolov9_postprocess_ms_avg=0.0
yolov9_total_inference_ms_avg=2522.06
yolov9_total_inference_ms_p95=7014.8
```

Interpretation: route-loop speed is dominated by YOLOv9 model forward time. At current cadence the effective loop rate is about 0.24 FPS, which is too slow to justify a route-completion attempt without latency work.

### variant_02_stride_5_cached

```text
diagnostic_steps_requested=100
diagnostic_steps_completed=1
duration_sec=206.497
effective_fps=0.004843
world_tick_count=0
rgb_frame_received_count=0
edge_perception_call_count=0
yolov9_inference_call_count=0
cached_perception_result_count=0
partial_route_progress_seen=false
latency_bottleneck_classification=timeout_before_latency_profile
```

Interpretation: stride-5 cached mode did not produce a valid route-loop latency profile in this run. Therefore this phase cannot claim that diagnostic caching reduces route-loop stall. The next step should optimize or isolate YOLOv9 latency before promoting a cached cadence strategy.

### Prepared Variants

The following commands were written but not executed in the default bounded run:

```text
variant_03_stride_10_cached
variant_04_dummy_reference
```

## Recommendation

```text
recommended_next_phase=R1-LATENCY-OPT
```

Rationale:

- current cadence completed but is strongly YOLOv9-forward dominated;
- average YOLOv9 total inference is greater than 1000 ms;
- stride-5 cached mode did not produce a stable route-loop profile;
- dummy reference was prepared but not executed in this bounded run;
- a route-completion attempt would be premature without latency optimization or a stronger cadence profile.

## Boundary

R1-LATENCY is latency and cadence evidence only. It is not selected YOLOv9 route runtime pass, not route completion, not YOLOv9 model accuracy evidence, not full Phase 12C perception ablation runtime pass, not RT-DETR runtime verification, not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

The diagnostic-only inference stride/cache behavior remains diagnostic-only unless a later phase explicitly promotes it.

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

## Follow-Up: R1-LATENCY-OPT Probe

R1-LATENCY-OPT used this forward-bottleneck evidence to profile diagnostic-only optimization variants:

```text
latency_opt_evidence_dir=experiments\phase12\20260701T115744Z
status=completed_no_improvement
best_variant_id=variant_01_baseline_recheck
best_variant_effective_fps=0.168392
best_variant_yolov9_avg_ms=2194.8
best_avg_ms_improvement_pct=12.976
best_fps_improvement_pct=-29.635
latency_opt_bottleneck_classification=latency_regressed
useful_latency_improvement_verified=false
recommended_next_phase=R1-YOLOv9-LIGHTWEIGHT
```

Image-size, half precision, forward-only profiling, stride, and cached perception behavior remain diagnostic-only. R1-LATENCY-OPT does not claim route completion, YOLOv9 model accuracy, full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark.

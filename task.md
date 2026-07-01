# Current Task - Phase 12C-YOLOv9-R1-LATENCY-OPT

## Latest Status

```text
Phase 12C-YOLOv9-R1-LATENCY-OPT No-Improvement - optimization probe completed, but YOLOv9 forward latency remains too high for route completion.
```

Maintained boundary:

```text
Phase 12C-YOLOv9-R1-LATENCY-OPT is latency optimization evidence only. It does not claim selected YOLOv9 route runtime pass, route completion, YOLOv9 model accuracy, full Phase 12C perception ablation runtime pass, RT-DETR runtime verification, CARLA Leaderboard, formal route benchmark, or infraction benchmark.
```

## Latest Evidence

```text
latency_opt_evidence_dir=experiments\phase12\20260701T115744Z
latency_evidence_dir=experiments\phase12\20260701T103721Z
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
source_adapter_verified=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
setup_probe_passed=true
short_route_begin_verified=true
latency_probe_completed=true
variant_count=7
executed_variant_count=4
completed_variant_count=2
blocked_variant_count=2
best_variant_id=variant_01_baseline_recheck
best_variant_effective_fps=0.168392
best_variant_yolov9_avg_ms=2194.8
best_avg_ms_improvement_pct=12.976
best_fps_improvement_pct=-29.635
latency_opt_bottleneck_classification=latency_regressed
useful_latency_improvement_verified=false
recommended_next_phase=R1-YOLOv9-LIGHTWEIGHT
```

Image-size, half precision, forward-only profiling, stride, and cached perception behavior remain diagnostic-only unless promoted by a later phase.

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

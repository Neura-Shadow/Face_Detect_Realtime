# Phase 12C-YOLOv9-R1-LATENCY-OPT - Forward-Latency Optimization Probe

## Status

```text
Phase 12C-YOLOv9-R1-LATENCY-OPT No-Improvement - optimization probe completed, but YOLOv9 forward latency remains too high for route completion.
```

This phase extends the R1-LATENCY result with bounded diagnostic-only optimization variants. It compares image-size, cached cadence, half precision preparation, and forward-only profiling commands against the previous selected-row baseline.

## Evidence

```text
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
```

## Variant Result

```text
variant_count=7
executed_variant_count=4
completed_variant_count=2
blocked_variant_count=2
best_variant_id=variant_01_baseline_recheck
best_variant_effective_fps=0.168392
best_variant_yolov9_avg_ms=2194.8
best_variant_yolov9_p95_ms=5222.5
best_variant_img_size=640
best_variant_half=false
best_variant_stride=1
best_variant_cached=false
best_avg_ms_improvement_pct=12.976
best_fps_improvement_pct=-29.635
latency_opt_bottleneck_classification=latency_regressed
useful_latency_improvement_verified=false
latency_opt_completed=true
recommended_next_phase=R1-YOLOv9-LIGHTWEIGHT
```

`variant_01_baseline_recheck` completed 30 closed-loop diagnostic steps with no YOLOv9 fallback. It improved average YOLOv9 total inference relative to the previous R1-LATENCY baseline, but the improvement was only 12.976%, below the 25% useful-improvement gate, and effective FPS regressed.

`variant_02_imgsz_512` also completed 30 steps without fallback, but average total inference did not improve against the baseline and effective FPS regressed. `variant_03_imgsz_416` and `variant_05_stride_5_cached_imgsz_512` did not produce valid route-loop timing evidence in this bounded run. `variant_04_imgsz_512_half`, `variant_06_forward_only_profile`, and `variant_07_dummy_reference` were prepared but not executed under the selected runtime budget.

## Boundary

R1-LATENCY-OPT is latency optimization evidence only. It does not claim selected YOLOv9 route runtime pass, route completion, YOLOv9 model accuracy, full Phase 12C perception ablation runtime pass, RT-DETR runtime verification, CARLA Leaderboard, formal route benchmark, or infraction benchmark.

Image-size changes, half precision, forward-only profiling, stride, and cached perception behavior remain diagnostic-only unless a later phase explicitly promotes them.

## Follow-Up: R1-YOLOv9-LIGHTWEIGHT Probe

R1-YOLOv9-LIGHTWEIGHT implemented the operator-provided lightweight YOLOv9 asset contract and produced blocked evidence at `experiments\phase12\20260701T165325Z`. The baseline YOLOv9 source adapter still verified no fallback, but `YOLOV9_LIGHTWEIGHT_WEIGHTS` was not configured, so no lightweight route-loop timing variant executed.

```text
lightweight_weights_configured=false
lightweight_weights_ready=false
lightweight_bottleneck_classification=lightweight_weights_missing
useful_lightweight_profile_verified=false
recommended_next_phase=R1-RT-DETR-UNLOCK
```

The follow-up does not download or commit YOLOv9 assets and does not claim route completion, YOLOv9 model accuracy, full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark.

## Follow-Up: RT-DETR Unlock

R1-LATENCY-OPT recommended `R1-YOLOv9-LIGHTWEIGHT`; that phase then blocked on missing lightweight YOLOv9 weights and recommended `R1-RT-DETR-UNLOCK`. The RT-DETR unlock gate at `experiments\phase12\20260702T022636Z-1` is blocked because `ultralytics_import_ready=false` and `rtdetr_weights_ready=false`; EdgePerception command support is present but fallback is used, so `edge_rtdetr_no_fallback_verified=false`.

This is a backend readiness branch only. It does not claim RT-DETR route runtime pass, RT-DETR accuracy, full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark.

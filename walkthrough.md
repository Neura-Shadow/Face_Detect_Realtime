# Walkthrough - Phase 12C-R1-RT-DETR-ASSET-EXEC

## Latest Result

```text
Phase 12C-R1-RT-DETR-ASSET-EXEC Blocked - RT-DETR setup execution did not reach no-fallback readiness.
```

```text
rtdetr_asset_exec_evidence_dir=experiments\phase12\20260702T044516Z
rtdetr_asset_setup_evidence_dir=experiments\phase12\20260702T040554Z
rtdetr_unlock_evidence_dir=experiments\phase12\20260702T022636Z-1
lightweight_evidence_dir=experiments\phase12\20260701T165325Z
target_perception_backend=rtdetr
runtime_scope=rtdetr_dependency_asset_setup_execution_only
status=blocked
ultralytics_import_ready_before=false
ultralytics_import_ready_after=true
ultralytics_version_after=8.4.84
dependency_install_requested=true
dependency_install_executed=true
dependency_install_exit_code=0
rtdetr_weights_configured=true
rtdetr_weights_ready=false
rtdetr_weights_path=D:\AIModels\rtdetr\rtdetr-l.pt
edge_rtdetr_command_passed=null
edge_rtdetr_fallback_used=null
edge_rtdetr_no_fallback_verified=false
post_setup_smoke_executed=false
phase12c_rtdetr_rows_available=false
phase12c_rtdetr_backend_unavailable_count=5
recommended_next_phase=R1-RT-DETR-ASSET-SETUP
carla_route_runtime_executed=false
rtdetr_runtime_verified=false
rtdetr_accuracy_verified=false
full_phase12c_perception_ablation_runtime_pass=false
```

R1-LIGHTWEIGHT ended blocked because no operator-provided lightweight YOLOv9 weights were configured, so the branch moved to RT-DETR. R1-RT-DETR-UNLOCK confirmed the command path exists, then blocked because `ultralytics` and `RTDETR_WEIGHTS` were unavailable in the target runtime. R1-RT-DETR-ASSET-SETUP wrote the explicit setup commands. R1-RT-DETR-ASSET-EXEC then explicitly installed `ultralytics` into the CARLA Python 3.12 runtime, but stopped before smoke because the local RT-DETR weights remain missing.

## Previous Walkthrough - RT-DETR-ASSET-SETUP

```text
rtdetr_asset_setup_evidence_dir=experiments\phase12\20260702T040554Z
dependency_install_requested=false
dependency_install_executed=false
rtdetr_weights_configured=false
rtdetr_weights_ready=false
post_setup_smoke_executed=false
edge_rtdetr_no_fallback_verified=false
recommended_next_phase=R1-RT-DETR-ASSET-SETUP
```

## Previous Walkthrough - RT-DETR-UNLOCK

```text
rtdetr_unlock_evidence_dir=experiments\phase12\20260702T022636Z-1
ultralytics_import_ready=false
rtdetr_weights_configured=false
rtdetr_weights_ready=false
edge_rtdetr_command_supported=true
edge_rtdetr_command_passed=true
edge_rtdetr_fallback_used=true
edge_rtdetr_no_fallback_verified=false
phase12c_rtdetr_rows_available=false
phase12c_rtdetr_backend_unavailable_count=5
recommended_next_phase=R1-RT-DETR-ASSET-SETUP
```

## Previous Walkthrough - R1-YOLOv9-LIGHTWEIGHT

```text
lightweight_evidence_dir=experiments\phase12\20260701T165325Z
lightweight_weights_configured=false
lightweight_weights_ready=false
lightweight_bottleneck_classification=lightweight_weights_missing
useful_lightweight_profile_verified=false
recommended_next_phase=R1-RT-DETR-UNLOCK
```

R1-LATENCY identified YOLOv9 model-forward time as the dominant bottleneck. R1-LATENCY-OPT tested diagnostic-only image-size and cached-cadence variants, but did not verify a useful no-fallback latency improvement. R1-YOLOv9-LIGHTWEIGHT then added the operator-provided lightweight asset contract; the local run was blocked because `YOLOV9_LIGHTWEIGHT_WEIGHTS` was not configured.

## Previous Walkthrough - R1-LATENCY-OPT

```text
Phase 12C-YOLOv9-R1-LATENCY-OPT No-Improvement - optimization probe completed, but YOLOv9 forward latency remains too high for route completion.
```

```text
latency_opt_evidence_dir=experiments\phase12\20260701T115744Z
best_variant_id=variant_01_baseline_recheck
best_variant_effective_fps=0.168392
best_variant_yolov9_avg_ms=2194.8
useful_latency_improvement_verified=false
recommended_next_phase=R1-YOLOv9-LIGHTWEIGHT
```

## Previous Walkthrough - R1-LATENCY

## Objective

Measure and characterize YOLOv9 route-loop latency for the selected row:

```text
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
```

This phase profiles latency and cadence only. It is not a route completion gate, YOLOv9 runtime pass, model accuracy check, full Phase 12C ablation, Leaderboard run, formal route benchmark, or infraction benchmark.

## Lineage

```text
previous_runtime_evidence_dir=experiments\phase12\20260630T134322Z
diagnostic_evidence_dir=experiments\phase12\20260630T150500Z
setup_evidence_dir=experiments\phase12\20260701T045047Z
short_route_begin_evidence_dir=experiments\phase12\20260701T064944Z
latency_evidence_dir=experiments\phase12\20260701T103721Z
```

R1-SHORT proved route-loop entry:

```text
short_route_begin_verified=true
world_tick_count=50
rgb_frame_received_count=50
edge_perception_call_count=50
yolov9_inference_call_count=11
edge_yolov9_fallback_used_during_route=false
```

R1-LATENCY then measured route-loop speed and timing components.

## Implementation

New wrapper:

```text
scripts\run_phase12c_yolov9_r1_latency_probe.py
```

Optional diagnostic-only cadence/cache flags were added end-to-end with defaults preserving existing behavior:

```text
--perception-inference-stride N
--reuse-last-perception-between-inference
--record-perception-cache-events
```

Touched runtime path:

```text
workers\CARLA_Closed_Loop_Agent.py
scripts\run_phase11m_grp_route_following.py
scripts\run_phase12b_controller_ablation_experiment.py
scripts\run_phase12c_yolov9_runtime_timeout_diagnosis.py
```

The cache behavior is diagnostic-only. It does not modify VLM, SafetyGate, SemanticPlanner, GRP controller logic, YOLOv9 thresholds, model source, or weights.

## Dry-Run

```powershell
python scripts\run_phase12c_yolov9_r1_latency_probe.py --dry-run --output-dir experiments\phase12
```

Dry-run evidence:

```text
experiments\phase12\20260701T102823Z
```

## Runtime Command

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_yolov9_r1_latency_probe.py --route-id route_01 --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --short-route-begin-evidence-dir experiments\phase12\20260701T064944Z --setup-evidence-dir experiments\phase12\20260701T045047Z --require-yolov9-ready --require-setup-passed --require-short-route-begin-passed --child-timeout-sec 600 --parent-timeout-sec 2400
```

Runtime evidence:

```text
experiments\phase12\20260701T103721Z
```

## Variant Matrix

Executed in this bounded run:

```text
variant_01_current_cadence
variant_02_stride_5_cached
```

Prepared but not executed:

```text
variant_03_stride_10_cached
variant_04_dummy_reference
```

## Results

Top-level:

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

variant_01_current_cadence:

```text
diagnostic_steps_completed=50
duration_sec=208.931
effective_fps=0.239313
edge_perception_call_count=50
yolov9_inference_call_count=50
real_inference_ratio=1.0
yolov9_preprocess_ms_avg=6.8
yolov9_model_forward_ms_avg=2512.84
yolov9_nms_ms_avg=2.84
yolov9_postprocess_ms_avg=0.0
yolov9_total_inference_ms_avg=2522.06
yolov9_total_inference_ms_p95=7014.8
latency_bottleneck_classification=yolov9_forward_dominant
```

variant_02_stride_5_cached:

```text
diagnostic_steps_completed=1
world_tick_count=0
rgb_frame_received_count=0
edge_perception_call_count=0
yolov9_inference_call_count=0
latency_bottleneck_classification=timeout_before_latency_profile
```

## Interpretation

The current cadence route loop is YOLOv9 forward-pass dominated. The effective FPS is about 0.24, and YOLOv9 total inference averages about 2.52 seconds per frame. The stride-5 cached diagnostic did not produce a valid route-loop profile, so cache/cadence improvement is not verified yet.

Recommended next phase:

```text
R1-LATENCY-OPT
```

## Boundary

Allowed claims:

- selected YOLOv9 route-loop latency was profiled;
- early route-loop YOLOv9 inference timing was measured;
- diagnostic cadence comparison was produced;
- next route strategy was recommended from latency evidence.

Forbidden claims:

- YOLOv9 selected route runtime pass;
- YOLOv9 route completion pass;
- YOLOv9 model accuracy verified;
- full Phase 12C perception ablation runtime pass;
- RT-DETR runtime pass;
- CARLA Leaderboard passed;
- formal route benchmark passed;
- infraction benchmark passed.

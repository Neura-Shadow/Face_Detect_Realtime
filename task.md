# Current Task - Phase 13A-EMBEDDED-CONTRACT-SIL

## Latest Status

```text
Phase 13A-EMBEDDED-CONTRACT-SIL Pass — command protocol, Safety MCU state machine, range-shift rejection, stale-command rejection, and host SIL tests passed.
```

```text
evidence_dir=experiments\phase13\20260808T065044Z
protocol_version=1
packet_size_bytes=64
fsm_test_result=passed
range_shift_tests_passed=true
sil_tests=28/28
portable_c_build_test_status=passed
crc_reject_count=1
stale_reject_count=1
sequence_reject_count=2
lease_reject_count=1
range_reject_count=3
false_accept_count=0
false_reject_count=0
```

The verified host path is `EdgePerception -> RangeShiftMonitor -> SafetyGate -> EmbeddedCommandBridge -> bounded binary packet -> Safety MCU emulator`. Portable C parser/FSM tests also passed through CMake/CTest. Generated evidence remains ignored.

Boundary: this is host software-in-the-loop evidence. It does not claim real MCU firmware, HIL, actuator control, CARLA benchmark, model accuracy, or OTA/security validation.

## Previous Task - Phase 12C-YOLOv9-R1 Formal Runtime Rerun

## Previous Status

```text
Phase 12C-YOLOv9-R1 Runtime Confirmation Blocked - selected YOLOv9 backend row did not complete or did not satisfy the selected runtime smoke gate.
```

Maintained boundary:

```text
This targeted rerun covers only `route_01 + grp_follower + yolov9`. It does not claim full Phase 12C perception ablation runtime pass, YOLOv9 model accuracy, RT-DETR runtime verification, CARLA Leaderboard, a formal route benchmark, or an infraction benchmark.
```

## Latest Evidence

```text
runtime_evidence_dir=experiments\phase12\20260713T190904Z
dry_run_evidence_dir=experiments\phase12\20260713T190811Z
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
source_adapter_verified=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
carla_server_reachable=true
runtime_confirmation_executed=true
carla_route_runtime_executed=true
child_row_result=grp_blocked
steps_completed=0
goal_reached=false
yolo_runtime_row_verified=false
full_phase12c_perception_ablation_runtime_pass=false
```

The child reached the real CARLA path but `load_world("Town03_Opt")` exceeded the 60-second setup timeout before ego spawn or route ticks. Generated evidence remains local and ignored, and the CARLA server was stopped after the gate.

## Previous Phase - Phase 12D-VLM-TRIGGER-SCAFFOLD

Phase 12D-VLM-TRIGGER-SCAFFOLD remains prepared at commit `8d3b74cc`: the 20-row VLM-mode matrix is source-ready without claiming CARLA runtime or external VLM execution.

## Previous Phase - Phase 12C-SUM

Phase 12C-SUM remains the authoritative perception handoff: dummy runtime smoke is confirmed, YOLOv9 has route-begin/latency evidence without route completion, and RT-DETR is frozen as an external local-weight blocker. It does not claim full Phase 12C perception ablation runtime pass.

## Previous Phase - RT-DETR-ASSET-BLOCKER-FREEZE

```text
Phase 12C-R1-RT-DETR-ASSET-BLOCKER-FREEZE Completed - RT-DETR branch is formally frozen as external local-weight blocked and Phase 12C summary handoff is prepared.
```

```text
rtdetr_weights_local_rerun_evidence_dir=experiments\phase12\20260702T125105Z
rtdetr_asset_exec_evidence_dir=experiments\phase12\20260702T044516Z
rtdetr_unlock_evidence_dir=experiments\phase12\20260702T022636Z-1
rt_detr_branch_frozen_external_asset_blocker=true
rtdetr_dependency_ready=true
rtdetr_weights_ready=false
missing_weight_path=D:\AIModels\rtdetr\rtdetr-l.pt
rtdetr_no_fallback_ready=false
phase12c_rtdetr_rows_available=false
```

## Previous Phase - RT-DETR-WEIGHTS-LOCAL

```text
Phase 12C-R1-RT-DETR-WEIGHTS-LOCAL Blocked - local RT-DETR weights are still missing.
```

```text
rtdetr_weights_local_evidence_dir=experiments\phase12\20260702T125105Z
rtdetr_asset_exec_evidence_dir=experiments\phase12\20260702T044516Z
rtdetr_asset_setup_evidence_dir=experiments\phase12\20260702T040554Z
rtdetr_unlock_evidence_dir=experiments\phase12\20260702T022636Z-1
rtdetr_weights_configured=true
rtdetr_weights_ready=false
missing_weight_path=D:\AIModels\rtdetr\rtdetr-l.pt
edge_rtdetr_no_fallback_verified=false
phase12c_rtdetr_rows_available=false
recommended_next_phase=R1-RT-DETR-ASSET-SETUP
```

## Previous Phase - RT-DETR-ASSET-EXEC

```text
Phase 12C-R1-RT-DETR-ASSET-EXEC Blocked - RT-DETR setup execution did not reach no-fallback readiness.
```

```text
rtdetr_asset_exec_evidence_dir=experiments\phase12\20260702T044516Z
ultralytics_import_ready_after=true
ultralytics_version_after=8.4.84
dependency_install_requested=true
dependency_install_executed=true
dependency_install_exit_code=0
rtdetr_weights_configured=true
rtdetr_weights_ready=false
post_setup_smoke_executed=false
edge_rtdetr_no_fallback_verified=false
recommended_next_phase=R1-RT-DETR-ASSET-SETUP
```

## Previous Phase - RT-DETR-ASSET-SETUP

```text
Phase 12C-R1-RT-DETR-ASSET-SETUP Command-Ready - explicit RT-DETR setup commands and asset contract are written, but setup was not executed.
```

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

## Previous Phase - RT-DETR-UNLOCK

```text
Phase 12C-R1-RT-DETR-UNLOCK Blocked - RT-DETR optional backend could not be verified because dependency or model assets are unavailable.
```

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

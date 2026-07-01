# Phase 12C-YOLOv9-SRC-V — Source Adapter No-Fallback Verification

## Status

```text
Phase 12C-YOLOv9-SRC-V Passed — official YOLOv9 source adapter verified with no fallback in the CARLA Python 3.12 runtime.
```

This phase verifies the Phase 12C-YOLOv9-SRC adapter under strict no-fallback conditions. It does not install YOLOv9 from MA-VLNA automation, does not commit YOLOv9 source, does not commit YOLOv9 weights, does not start CARLA, and does not execute YOLOv9 route runtime confirmation.

Phase distinction:

- Phase 12C-YOLOv9-SRC prepared the official external source adapter and no-fallback gate.
- Phase 12C-YOLOv9-SRC-V verified official source adapter no-fallback readiness in CARLA Python 3.12.
- Phase 12C-YOLOv9-R1-RERUN reached CARLA and launched the selected route runtime, but the child timed out before route metrics or goal-reach evidence were produced; full YOLOv9 runtime pass remains unverified.

## Evidence

Strict source-adapter evidence:

```text
source_adapter_verified_evidence_dir=experiments\phase12\20260630T060621Z
```

YOLOv9-only Phase 12C matrix refresh after the verified strict attempt:

```text
yolov9_rows_refresh_dir=experiments\phase12\20260630T060823Z
```

Post-unlock external-source evidence:

```text
post_unlock_external_source_verified_dir=experiments\phase12\20260630T061015Z
```

Generated files:

- `manifest.json`
- `summary.json`
- `commands.txt`
- `environment.json`
- `README.md`
- `raw_outputs/`

## Verification Result

```text
phase=Phase 12C-YOLOv9-SRC
status=yolov9_source_adapter_verified
require_verified_requested=true
strict_gate_exit_code=0
target_python_exists=true
YOLOV9_ROOT_configured=true
YOLOV9_WEIGHTS_configured=true
yolov9_source_root_ready=true
yolov9_weights_ready=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
source_adapter_verified=true
post_unlock_verified=true
unlock_mode=external_source
phase12c_yolov9_rows_available=true
backend_unavailable_count=0
runtime_confirmation_executed=false
carla_route_runtime_executed=false
auto_install_performed=false
baseline_requirements_modified=false
carla_server_started=false
```

## Operator Assets

Operator-provided local assets are external and are not committed:

```powershell
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install -r "$env:YOLOV9_ROOT\requirements.txt"
python scripts\run_phase12c_yolov9_source_adapter_verification.py --output-dir experiments\phase12 --require-verified
```

Strict pass requires and now satisfies:

```text
yolov9_source_root_ready=true
yolov9_weights_ready=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
source_adapter_verified=true
```

## Boundary

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

YOLOv9 source repo remains external and is not committed. YOLOv9 weights remain external and are not committed. No YOLOv9 source is vendored into MA-VLNA. No baseline requirements were modified. No YOLOv9 model accuracy claim is made.

Phase 12C-YOLOv9-SRC-V is not YOLOv9 route runtime validation, not YOLOv9 accuracy evidence, not RT-DETR validation, not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

## Follow-up Runtime Attempt

Phase 12C-YOLOv9-R1 attempted one selected route after this no-fallback gate:

```text
runtime_evidence_dir=experiments\phase12\20260630T134322Z
previous_blocked_evidence_dir=experiments\phase12\20260630T094645Z
status=Phase 12C-YOLOv9-R1 Runtime Confirmation Blocked - selected YOLOv9 backend row did not complete or did not satisfy the selected runtime smoke gate.
carla_server_reachable=true
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
source_adapter_verified=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
runtime_confirmation_executed=true
carla_route_runtime_executed=true
child_row_result=timeout
child_inner_exit_code=124
metrics_read_status=loaded
```

The blocker is the selected route child timeout. The YOLOv9 source adapter no-fallback gate remains passed.

## Follow-up Timeout Diagnosis

Phase 12C-YOLOv9-R1-DIAG preserved the no-fallback source adapter result and classified the selected-row blocker as a CARLA setup / map-load / spawn-stage issue:

```text
diagnostic_evidence_dir=experiments\phase12\20260630T150500Z
previous_runtime_evidence_dir=experiments\phase12\20260630T134322Z
timeout_classification=map_load_or_spawn_stall
diagnosis_confidence=high
diagnostic_steps_completed=0
heartbeat_count=0
world_tick_count=0
rgb_frame_received_count=0
edge_perception_call_count=0
yolov9_inference_call_count=0
yolo_runtime_row_verified=false
```

This is diagnostic evidence only. It does not claim selected YOLOv9 route runtime pass or full Phase 12C perception ablation runtime pass.

## Follow-up Setup Recovery Probe

Phase 12C-YOLOv9-R1-SETUP keeps this no-fallback gate as a prerequisite and isolates CARLA setup:

```text
setup_evidence_dir=experiments\phase12\20260701T045047Z
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
target_town=Town03
map_load_mode=reuse_or_load
setup_scope=map_load_spawn_rgb_grp_warmup_only
setup_probe_passed=true
setup_blocker_classification=setup_probe_passed
yolo_runtime_row_verified=false
```

The setup probe is not model accuracy evidence and not a route runtime pass.

## Follow-Up Route-Begin Probe

Phase 12C-YOLOv9-R1-SHORT keeps this no-fallback gate as a prerequisite and verifies early route-loop breadcrumbs:

```text
short_route_begin_evidence_dir=experiments\phase12\20260701T064944Z
setup_evidence_dir=experiments\phase12\20260701T045047Z
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
source_adapter_verified=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
diagnostic_steps_completed=50
heartbeat_count=11
world_tick_count=50
rgb_frame_received_count=50
edge_perception_call_count=50
yolov9_inference_call_count=11
edge_yolov9_fallback_used_during_route=false
partial_route_progress_seen=true
short_route_begin_verified=true
yolo_runtime_row_verified=false
selected_route_completion_verified=false
```

R1-SHORT is not model accuracy evidence, not selected route completion, not full Phase 12C ablation, and not Leaderboard / formal route / infraction benchmark evidence.

## Follow-Up Latency Probe

Phase 12C-YOLOv9-R1-LATENCY keeps this no-fallback gate as a prerequisite and measures route-loop timing:

```text
latency_evidence_dir=experiments\phase12\20260701T103721Z
best_variant_id=variant_01_current_cadence
best_variant_effective_fps=0.239313
yolov9_total_inference_ms_avg=2522.06
yolov9_model_forward_ms_avg=2512.84
latency_bottleneck_classification=yolov9_forward_dominant
recommended_next_phase=R1-LATENCY-OPT
```

This confirms that the source adapter can run without fallback while route-loop cadence remains too slow for route completion attempts.

## Follow-Up: R1-LATENCY-OPT Probe

R1-LATENCY-OPT completed bounded optimization profiling at `experiments\phase12\20260701T115744Z` with `latency_opt_completed=true` and `useful_latency_improvement_verified=false`.

```text
best_variant_id=variant_01_baseline_recheck
best_variant_effective_fps=0.168392
best_variant_yolov9_avg_ms=2194.8
best_avg_ms_improvement_pct=12.976
best_fps_improvement_pct=-29.635
latency_opt_bottleneck_classification=latency_regressed
recommended_next_phase=R1-YOLOv9-LIGHTWEIGHT
```

The no-fallback source adapter gate remains valid; R1-LATENCY-OPT does not claim route completion, YOLOv9 model accuracy, full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark.

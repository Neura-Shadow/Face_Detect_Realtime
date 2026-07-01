# Phase 12C-YOLOv9-R1 - Selected YOLOv9 Runtime Confirmation

## Latest Formal Gate

```text
Phase 12C-YOLOv9-R1 Runtime Confirmation Blocked - selected YOLOv9 backend row did not complete or did not satisfy the selected runtime smoke gate.
```

The latest formal gate was executed with the required YOLOv9 source and weights configured. The wrapper verified the external source adapter and `EdgePerception --test yolov9` no-fallback path, but did not launch the child route runtime because the CARLA server was not reachable at `127.0.0.1:2000`.

```text
runtime_evidence_dir=experiments\phase12\20260701T172906Z
dry_run_evidence_dir=experiments\phase12\20260701T172854Z
previous_runtime_evidence_dir=experiments\phase12\20260630T134322Z
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
runtime_scope=selected_single_route
source_adapter_verified=true
post_unlock_verified=true
phase12c_yolov9_rows_available=true
backend_unavailable_count=0
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
YOLOV9_ROOT_configured=true
YOLOV9_WEIGHTS_configured=true
yolov9_source_root_ready=true
yolov9_weights_ready=true
carla_server_reachable=false
runtime_confirmation_executed=false
carla_route_runtime_executed=false
executed_row_count=0
passed_count=0
blocked_count=1
goal_reached=null
distance_to_goal_m=null
route_progress_pct=null
grp_route_progress_pct=null
collision_count=null
lane_invasion_count=null
metrics_read_status=not_run
yolo_runtime_row_verified=false
blocked_reason=CARLA server is not reachable
```

This is a selected single-route runtime confirmation blocker only. It is not a full Phase 12C perception ablation runtime pass, not YOLOv9 model accuracy evidence, not RT-DETR validation, not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

## Status

```text
Phase 12C-YOLOv9-R1 Runtime Confirmation Blocked - selected YOLOv9 backend row still did not complete or did not satisfy the selected runtime smoke gate.
```

Phase 12C-YOLOv9-R1-RERUN retried the same selected real CARLA runtime row after starting a reachable CARLA 0.9.16 server on `127.0.0.1:2000`.

```text
runtime_evidence_dir=experiments\phase12\20260630T134322Z
previous_blocked_evidence_dir=experiments\phase12\20260630T094645Z
dry_run_evidence_dir=experiments\phase12\20260630T095539Z
carla_server_reachable=true
child_summary_status=controller_ablation_runtime_blocked
child_row_result=timeout
child_exit_code=1
child_inner_exit_code=124
child_duration_sec=2400.311
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
runtime_scope=selected_single_route
```

## Prerequisite Evidence

The wrapper requires the existing Phase 12C-YOLOv9-SRC-V readiness line unless explicitly bypassed. The local prerequisite evidence remains:

```text
source_adapter_verified_evidence_dir=experiments\phase12\20260630T060621Z
yolov9_rows_refresh_dir=experiments\phase12\20260630T060823Z
post_unlock_external_source_verified_dir=experiments\phase12\20260630T061015Z
source_adapter_verified=true
post_unlock_verified=true
phase12c_yolov9_rows_available=true
backend_unavailable_count=0
```

## Runtime Rerun Result

The selected runtime wrapper verified local YOLOv9 readiness, reached the CARLA server, launched the Phase 12B child runtime, and the child launched the Phase 11M GRP route runner with `--perception-backend yolov9`.

```text
YOLOV9_ROOT_configured=true
YOLOV9_WEIGHTS_configured=true
yolov9_source_root_ready=true
yolov9_weights_ready=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
carla_server_reachable=true
runtime_confirmation_executed=true
carla_route_runtime_executed=true
row_count=1
executed_row_count=1
passed_count=0
blocked_count=1
failed_count=0
goal_reached=null
distance_to_goal_m=null
route_progress_pct=null
grp_route_progress_pct=null
collision_count=null
lane_invasion_count=null
avg_speed_kmh=null
max_speed_kmh=null
metrics_read_status=loaded
yolo_runtime_row_verified=false
```

The Phase 11M child did not write route metrics before the Phase 12B child timeout. The Phase 12B row therefore reports:

```text
result=timeout
exit_code=124
runtime_execution_status=timeout
duration_sec=2400.311
metrics_read_status=not_available
```

This is a stronger blocked result than the previous `20260630T094645Z` attempt: the previous run stopped at CARLA reachability preflight, while this rerun reached CARLA and launched the selected route runtime but timed out before producing route metrics or goal-reach evidence.

## Follow-up Timeout Diagnosis

Phase 12C-YOLOv9-R1-DIAG adds bounded diagnostic breadcrumbs to explain the selected-row timeout without changing the runtime pass boundary.

```text
diagnostic_evidence_dir=experiments\phase12\20260630T150500Z
dry_run_evidence_dir=experiments\phase12\20260630T150101Z
previous_runtime_evidence_dir=experiments\phase12\20260630T134322Z
timeout_classification=map_load_or_spawn_stall
diagnosis_confidence=high
diagnostic_steps_requested=300
diagnostic_steps_completed=0
heartbeat_count=0
world_tick_count=0
rgb_frame_received_count=0
edge_perception_call_count=0
yolov9_inference_call_count=0
yolo_runtime_row_verified=false
```

The diagnostic event stream observed YOLOv9 model load start/finish and CARLA setup start, then run failure. It did not observe CARLA setup finish, world ticks, RGB frames, route-loop EdgePerception calls, heartbeat, or partial route progress. Therefore the current blocker is classified as a CARLA setup / map-load / spawn-stage stall before route ticks began, not as verified per-frame YOLOv9 inference latency.

## Follow-up Setup Recovery Probe

Phase 12C-YOLOv9-R1-SETUP adds a setup/spawn-stage probe for the same selected row:

```text
setup_evidence_dir=experiments\phase12\20260701T045047Z
parent_wrapper=scripts\run_phase12c_yolov9_r1_setup_recovery.py
child_probe=scripts\run_phase12c_carla_setup_spawn_probe.py
target_town=Town03
start_spawn_index=3
end_spawn_index=30
map_load_mode=reuse_or_load
setup_probe_passed=true
setup_blocker_classification=setup_probe_passed
runtime_confirmation_executed=false
carla_route_runtime_executed=false
yolo_runtime_row_verified=false
```

It isolates map-load / spawn / RGB / GRP setup before closed-loop route ticks and does not claim YOLOv9 runtime pass.

## Command

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\packages\CARLA_0.9.16\CarlaUE4.exe -carla-rpc-port=2000 -RenderOffScreen -nosound

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_yolov9_runtime_confirmation.py --route-id route_01 --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --child-timeout-sec 2400 --parent-timeout-sec 7200 --require-yolov9-ready
```

Dry-run command:

```powershell
python scripts\run_phase12c_yolov9_runtime_confirmation.py --dry-run --output-dir experiments\phase12
```

## Evidence Layout

The wrapper writes:

```text
manifest.json
summary.json
summary.csv
commands.txt
environment.json
README.md
raw_outputs/
runs/
```

The parent wrapper does not import `carla`; it verifies readiness, checks TCP reachability, and delegates selected route execution to the existing Phase 12B runtime path.

## Boundary

```text
full_phase12c_perception_ablation_runtime_pass=false
rt_detr_runtime_verified=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Phase 12C-YOLOv9-R1 is one selected single-route runtime confirmation attempt only. It is not a full Phase 12C perception ablation runtime pass, not YOLOv9 accuracy evidence, not RT-DETR validation, not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

## Follow-Up: R1-SHORT Route-Begin Probe

R1-SHORT is a bounded follow-up after R1-SETUP, not a replacement for full route runtime confirmation:

```text
short_route_begin_evidence_dir=experiments\phase12\20260701T064944Z
setup_evidence_dir=experiments\phase12\20260701T045047Z
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
runtime_confirmation_executed=true
carla_route_runtime_executed=true
diagnostic_steps_completed=50
heartbeat_count=11
world_tick_count=50
rgb_frame_received_count=50
edge_perception_call_count=50
yolov9_inference_call_count=11
edge_yolov9_fallback_used_during_route=false
short_route_begin_verified=true
yolo_runtime_row_verified=false
selected_route_completion_verified=false
```

The selected row now enters the route loop and emits early YOLOv9 no-fallback inference breadcrumbs. It still does not meet the selected route runtime pass boundary, because R1-SHORT does not require or prove route completion.

## Follow-Up: R1-LATENCY Probe

R1-LATENCY profiles the selected row before any route-completion retry:

```text
latency_evidence_dir=experiments\phase12\20260701T103721Z
executed_variant_count=2
completed_variant_count=1
blocked_variant_count=1
best_variant_id=variant_01_current_cadence
best_variant_effective_fps=0.239313
baseline_current_cadence_yolov9_avg_ms=2522.06
latency_bottleneck_classification=yolov9_forward_dominant
recommended_next_phase=R1-LATENCY-OPT
yolo_runtime_row_verified=false
selected_route_completion_verified=false
```

The latency result recommends optimization before another route-completion attempt; it does not turn R1 into a selected route runtime pass.

YOLOv9 source and weights remain external operator assets and are not committed or vendored into MA-VLNA. Baseline requirements remain unchanged.

## Follow-Up: R1-LATENCY-OPT Probe

R1-LATENCY-OPT completed bounded forward-latency optimization profiling at `experiments\phase12\20260701T115744Z`. The result is `completed_no_improvement`: `best_variant_id=variant_01_baseline_recheck`, `best_variant_yolov9_avg_ms=2194.8`, `best_avg_ms_improvement_pct=12.976`, `best_fps_improvement_pct=-29.635`, and `useful_latency_improvement_verified=false`.

The recommended next phase is `R1-YOLOv9-LIGHTWEIGHT`. This does not claim selected YOLOv9 route runtime pass, route completion, YOLOv9 model accuracy, full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark.

## Follow-Up: R1-YOLOv9-LIGHTWEIGHT Probe

R1-YOLOv9-LIGHTWEIGHT produced blocked evidence at `experiments\phase12\20260701T165325Z`. Baseline no-fallback readiness remained true, but `YOLOV9_LIGHTWEIGHT_WEIGHTS` was not configured, so no lightweight route-loop timing profile was executed.

`lightweight_bottleneck_classification=lightweight_weights_missing`, `useful_lightweight_profile_verified=false`, and `recommended_next_phase=R1-RT-DETR-UNLOCK`. This does not claim route completion, YOLOv9 model accuracy, full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark.

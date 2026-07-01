# Phase 12C-YOLOv9-R1-DIAG - Selected YOLOv9 Runtime Timeout Diagnosis

## Status

```text
Phase 12C-YOLOv9-R1-DIAG Diagnostic Completed - bounded diagnostic evidence was produced without claiming runtime pass.
```

Phase 12C-YOLOv9-R1-DIAG is a selected single-route timeout diagnosis pass for the prior R1-RERUN blocker. It keeps the same scoped runtime row:

```text
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
diagnostic_scope=selected_single_route_timeout_diagnosis
diagnostic_steps_requested=300
```

## Evidence

```text
diagnostic_evidence_dir=experiments\phase12\20260630T150500Z
dry_run_evidence_dir=experiments\phase12\20260630T150101Z
previous_runtime_evidence_dir=experiments\phase12\20260630T134322Z
previous_blocked_evidence_dir=experiments\phase12\20260630T094645Z
```

The diagnostic evidence confirms the YOLOv9 source adapter path was still no-fallback ready and the CARLA server was reachable:

```text
carla_server_reachable=true
source_adapter_verified=true
post_unlock_verified=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
runtime_confirmation_executed=true
carla_route_runtime_executed=true
```

The diagnostic child produced structured breadcrumbs but no route loop heartbeat:

```text
diagnostic_steps_completed=0
heartbeat_count=0
world_tick_count=0
rgb_frame_received_count=0
edge_perception_call_count=0
yolov9_inference_call_count=0
partial_route_progress_seen=false
child_summary_status=controller_ablation_runtime_blocked
child_row_result=grp_blocked
child_exit_code=1
child_row_duration_sec=207.801
```

## Timeout Classification

```text
timeout_classification=map_load_or_spawn_stall
diagnosis_confidence=high
```

Observed event sequence:

```text
edge_perception_model_load_started
edge_perception_model_load_finished
carla_setup_started
run_failed
```

No `carla_setup_finished`, `world_tick_finished`, `rgb_frame_received`, `edge_perception_finished`, heartbeat, or partial route progress event was observed. This classifies the selected-row blocker as a CARLA setup / map-load / spawn-stage stall or failure before the closed-loop route tick began. YOLOv9 model load completed before CARLA setup started; no per-frame YOLOv9 inference timing was available because the route loop never reached an RGB frame or edge perception call.

## Follow-up Setup Recovery Probe

Phase 12C-YOLOv9-R1-SETUP isolates the setup path that R1-DIAG classified as `map_load_or_spawn_stall`.

```text
setup_evidence_dir=experiments\phase12\20260701T045047Z
parent_wrapper=scripts\run_phase12c_yolov9_r1_setup_recovery.py
child_probe=scripts\run_phase12c_carla_setup_spawn_probe.py
target_town=Town03
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
map_load_mode=reuse_or_load
town_ready=true
ego_spawned=true
rgb_sensor_attached=true
first_rgb_frame_received=true
grp_route_generated=true
warmup_ticks_completed=20
setup_probe_passed=true
setup_blocker_classification=setup_probe_passed
```

The setup probe tests CARLA client connect, world availability, Town03 load/reuse, settings, spawn points, ego spawn, RGB sensor attach, first RGB frame, GRP route generation, warm-up ticks, and cleanup before any route runtime retry. It is not YOLOv9 runtime pass evidence.

## Instrumentation Added

- `workers.core.edge_perception.YOLOv9PerceptionBackend` now records model-forward, NMS, postprocess, total inference, device, and frame-shape timing metadata when inference is reached.
- `workers.CARLA_Closed_Loop_Agent` accepts a diagnostic recorder and emits lifecycle breadcrumbs for model load, CARLA setup, route load, world tick, RGB frame receipt, perception, planning, and control.
- `scripts/run_phase11m_grp_route_following.py` can emit `events.jsonl`, `heartbeat.jsonl`, and `partial_metrics.json` in diagnostic mode.
- `scripts/run_phase12b_controller_ablation_experiment.py` can pass bounded diagnostic settings to the selected Phase 11M child.
- `scripts/run_phase12c_yolov9_runtime_timeout_diagnosis.py` orchestrates the selected single-route diagnosis without importing CARLA in the parent process.

## Command

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_yolov9_runtime_timeout_diagnosis.py --route-id route_01 --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --diagnostic-steps 300 --diagnostic-timeout-sec 900 --child-timeout-sec 900 --parent-timeout-sec 1800 --require-yolov9-ready --emit-heartbeat-every 10 --emit-partial-metrics-every 25
```

Dry-run command:

```powershell
python scripts\run_phase12c_yolov9_runtime_timeout_diagnosis.py --dry-run --output-dir experiments\phase12
```

## Evidence Layout

The diagnostic wrapper writes:

```text
manifest.json
summary.json
summary.csv
commands.txt
environment.json
README.md
events.jsonl
heartbeat.jsonl
partial_metrics.json
raw_outputs/
runs/
```

## Boundary

```text
yolo_runtime_row_verified=false
full_phase12c_perception_ablation_runtime_pass=false
rt_detr_runtime_verified=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Phase 12C-YOLOv9-R1-DIAG is timeout diagnosis only. It does not claim selected YOLOv9 route runtime pass, YOLOv9 accuracy, full Phase 12C perception backend ablation runtime pass, RT-DETR runtime verification, CARLA Leaderboard, formal route benchmark, or infraction benchmark.

## Follow-Up: R1-SHORT Route-Begin Probe

After R1-SETUP recovered the setup/spawn path, R1-SHORT ran a bounded route-begin probe for the same selected row:

```text
short_route_begin_evidence_dir=experiments\phase12\20260701T064944Z
setup_evidence_dir=experiments\phase12\20260701T045047Z
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
diagnostic_steps_completed=50
world_tick_count=50
rgb_frame_received_count=50
edge_perception_call_count=50
yolov9_inference_call_count=11
edge_yolov9_fallback_used_during_route=false
partial_route_progress_seen=true
short_route_begin_verified=true
```

This follow-up changes the setup diagnosis lineage: the selected row now reaches the route loop and produces early no-fallback YOLOv9 breadcrumbs. It still does not claim selected YOLOv9 route runtime pass, route completion, model accuracy, full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark.

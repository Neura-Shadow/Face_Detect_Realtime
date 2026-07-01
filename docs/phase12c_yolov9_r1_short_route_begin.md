# Phase 12C-YOLOv9-R1-SHORT - Selected YOLOv9 Route-Begin Probe

## Status

```text
Phase 12C-YOLOv9-R1-SHORT Route-Begin Probe Pass - selected YOLOv9 row entered the closed-loop route loop and produced bounded early runtime evidence with no fallback.
```

R1-SHORT is a bounded route-begin diagnostic on the same selected row:

```text
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
target_town=Town03
```

It follows the Phase 12C lineage:

```text
previous_runtime_evidence_dir=experiments\phase12\20260630T134322Z
diagnostic_evidence_dir=experiments\phase12\20260630T150500Z
setup_evidence_dir=experiments\phase12\20260701T045047Z
short_route_begin_evidence_dir=experiments\phase12\20260701T064944Z
child_diagnostic_evidence_dir=experiments\phase12\20260701T064944Z\runs\20260701T065035Z
```

## Purpose

R1-DIAG classified the previous selected-row blocker as `map_load_or_spawn_stall`. R1-SETUP then proved that the same row can reach Town03 setup, ego spawn, RGB sensor attachment, first RGB frame, GRP route generation, warm-up ticks, and cleanup.

R1-SHORT is the next bounded step. It verifies that the selected YOLOv9 row can enter the actual closed-loop route loop and produce early breadcrumbs:

- world ticks
- RGB frames
- EdgePerception calls
- YOLOv9 no-fallback per-frame inference calls
- early partial route metrics

It does not require route completion, goal reach, full horizon completion, route progress completion, or formal benchmark criteria.

## Command

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_yolov9_r1_short_route_begin.py --route-id route_01 --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --setup-evidence-dir experiments\phase12\20260701T045047Z --diagnostic-steps 50 --diagnostic-timeout-sec 300 --child-timeout-sec 300 --parent-timeout-sec 900 --require-yolov9-ready --require-setup-passed --emit-heartbeat-every 5 --emit-partial-metrics-every 10
```

Dry-run:

```powershell
python scripts\run_phase12c_yolov9_r1_short_route_begin.py --dry-run --output-dir experiments\phase12
```

## Evidence Summary

```text
short_route_begin_evidence_dir=experiments\phase12\20260701T064944Z
setup_evidence_dir=experiments\phase12\20260701T045047Z
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
source_adapter_verified=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
setup_probe_passed=true
runtime_confirmation_executed=true
carla_route_runtime_executed=true
diagnostic_steps_requested=50
diagnostic_steps_completed=50
heartbeat_count=11
world_tick_count=50
rgb_frame_received_count=50
edge_perception_call_count=50
yolov9_inference_call_count=11
edge_yolov9_fallback_used_during_route=false
partial_route_progress_seen=true
last_route_progress_pct=0.0
last_distance_to_goal_m=315.651759
last_collision_count=0
last_lane_invasion_count=2
short_route_begin_verified=true
short_route_begin_blocker_classification=short_route_begin_verified
goal_reached=false
```

YOLOv9 timing summary:

```text
yolov9_total_inference_ms_min=1453.0
yolov9_total_inference_ms_avg=2633.0
yolov9_total_inference_ms_p95=5062.0
yolov9_total_inference_ms_max=6811.0
```

The timing values are performance evidence only. They do not convert this phase into an accuracy benchmark or full route runtime pass.

## Output Files

R1-SHORT writes:

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

`experiments\phase12` remains local runtime evidence and is not committed.

## Pass Criteria

R1-SHORT passes only when the selected row proves all of the following:

```text
setup_probe_passed=true
source_adapter_verified=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
carla_server_reachable=true
runtime_confirmation_executed=true
carla_route_runtime_executed=true
diagnostic_steps_completed>0
world_tick_count>0
rgb_frame_received_count>0
edge_perception_call_count>0
yolov9_inference_call_count>0
heartbeat_count>0
edge_yolov9_fallback_used_during_route=false
short_route_begin_verified=true
```

This pass condition intentionally does not require:

```text
goal_reached=true
route_progress_pct=100
distance_to_goal_m <= 3.0
full horizon completion
```

## Boundary

R1-SHORT is a short route-begin diagnostic only. It is not selected YOLOv9 route runtime pass, not YOLOv9 route completion pass, not YOLOv9 model accuracy evidence, not full Phase 12C perception ablation runtime pass, not RT-DETR runtime verification, not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

The benchmark boundary fields remain false:

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

## Follow-Up: R1-LATENCY Probe

R1-LATENCY profiles the same selected row after this route-begin pass:

```text
latency_evidence_dir=experiments\phase12\20260701T103721Z
short_route_begin_evidence_dir=experiments\phase12\20260701T064944Z
executed_variant_count=2
completed_variant_count=1
blocked_variant_count=1
best_variant_id=variant_01_current_cadence
best_variant_effective_fps=0.239313
baseline_current_cadence_yolov9_avg_ms=2522.06
latency_bottleneck_classification=yolov9_forward_dominant
recommended_next_phase=R1-LATENCY-OPT
latency_probe_completed=true
```

R1-LATENCY confirms that current-cadence route-loop speed is dominated by YOLOv9 model-forward latency. It does not claim route completion, selected YOLOv9 route runtime pass, model accuracy, full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark.

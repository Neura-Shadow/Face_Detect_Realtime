# Walkthrough - Phase 12C-YOLOv9-R1-SHORT Route-Begin Probe

## Objective

Verify that the selected YOLOv9 row enters the closed-loop route loop and produces bounded early runtime breadcrumbs without falling back:

```text
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
target_town=Town03
```

This is not a route completion gate. It is not a YOLOv9 selected-route runtime pass, model accuracy check, full Phase 12C perception ablation, CARLA Leaderboard run, formal route benchmark, or infraction benchmark.

## Lineage

```text
previous_runtime_evidence_dir=experiments\phase12\20260630T134322Z
diagnostic_evidence_dir=experiments\phase12\20260630T150500Z
setup_evidence_dir=experiments\phase12\20260701T045047Z
short_route_begin_evidence_dir=experiments\phase12\20260701T064944Z
```

R1-DIAG:

```text
timeout_classification=map_load_or_spawn_stall
diagnostic_steps_completed=0
heartbeat_count=0
world_tick_count=0
rgb_frame_received_count=0
edge_perception_call_count=0
yolov9_inference_call_count=0
```

R1-SETUP:

```text
setup_probe_passed=true
town_ready=true
ego_spawned=true
rgb_sensor_attached=true
first_rgb_frame_received=true
grp_route_generated=true
warmup_ticks_completed=20
```

R1-SHORT:

```text
short_route_begin_verified=true
short_route_begin_blocker_classification=short_route_begin_verified
```

## Implementation

The new parent wrapper is:

```text
scripts\run_phase12c_yolov9_r1_short_route_begin.py
```

The wrapper:

1. keeps the parent process free of direct CARLA imports;
2. checks the existing YOLOv9 SRC-V no-fallback readiness contract;
3. requires the R1-SETUP evidence by default;
4. checks CARLA server reachability;
5. delegates runtime work to `scripts\run_phase12c_yolov9_runtime_timeout_diagnosis.py`;
6. copies normalized `events.jsonl`, `heartbeat.jsonl`, and `partial_metrics.json` into the R1-SHORT evidence directory;
7. writes SHORT-specific `summary.json`, `summary.csv`, `manifest.json`, `commands.txt`, `environment.json`, and `README.md`.

## Dry-Run

```powershell
python scripts\run_phase12c_yolov9_r1_short_route_begin.py --dry-run --output-dir experiments\phase12
```

Dry-run evidence:

```text
experiments\phase12\20260701T064001Z
```

## Runtime Command

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_yolov9_r1_short_route_begin.py --route-id route_01 --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --setup-evidence-dir experiments\phase12\20260701T045047Z --diagnostic-steps 50 --diagnostic-timeout-sec 300 --child-timeout-sec 300 --parent-timeout-sec 900 --require-yolov9-ready --require-setup-passed --emit-heartbeat-every 5 --emit-partial-metrics-every 10
```

Runtime evidence:

```text
experiments\phase12\20260701T064944Z
```

## Runtime Result

```text
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
goal_reached=false
```

YOLOv9 timing summary:

```text
yolov9_total_inference_ms_min=1453.0
yolov9_total_inference_ms_avg=2633.0
yolov9_total_inference_ms_p95=5062.0
yolov9_total_inference_ms_max=6811.0
```

The timing data is retained as runtime evidence. It is not an accuracy result, not a benchmark score, and not route completion evidence.

## Boundary

Allowed claims:

- selected row entered the closed-loop route loop;
- early RGB frames were observed;
- early EdgePerception calls were observed;
- early YOLOv9 no-fallback inference was observed;
- the short route-begin probe passed.

Forbidden claims:

- YOLOv9 selected route runtime pass;
- YOLOv9 route completion pass;
- YOLOv9 model accuracy verified;
- full Phase 12C perception ablation runtime pass;
- RT-DETR runtime pass;
- CARLA Leaderboard passed;
- formal route benchmark passed;
- infraction benchmark passed.

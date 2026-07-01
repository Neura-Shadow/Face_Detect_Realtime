# Current Task - Phase 12C-YOLOv9-R1-SETUP

## Status

```text
Phase 12C-YOLOv9-R1-SETUP Probe Pass - selected route setup reached map ready, ego spawn, RGB sensor attach, first RGB frame, GRP route generation, and warm-up ticks.
```

Maintained boundary:

```text
Phase 12C-YOLOv9-R1-SETUP is setup / spawn-stage recovery only. It does not claim selected YOLOv9 route runtime pass, full Phase 12C perception ablation runtime pass, YOLOv9 accuracy, RT-DETR runtime verification, CARLA Leaderboard, formal route benchmark, or infraction benchmark.
```

## Background

```text
diagnostic_evidence_dir=experiments\phase12\20260630T150500Z
previous_runtime_evidence_dir=experiments\phase12\20260630T134322Z
timeout_classification=map_load_or_spawn_stall
diagnosis_confidence=high
```

R1-DIAG verified that the selected YOLOv9 row did not fail at the source-adapter no-fallback gate and did not reach per-frame YOLOv9 inference. The blocker is before closed-loop route ticks.

## Selected Setup Probe Row

```text
route_id=route_01
town=Town03
start_spawn_index=3
end_spawn_index=30
controller_mode=grp_follower
perception_backend=yolov9
map_load_mode=reuse_or_load
warmup_ticks=20
```

## Generated Local Evidence

```text
setup_evidence_dir=experiments\phase12\20260701T045047Z
dry_run_evidence_dir=experiments\phase12\20260701T045259Z
```

Generated runtime output remains local and is not committed.

## Result

```text
map_load_mode=reuse_or_load
carla_server_reachable=true
current_map_name=Carla/Maps/Town03
town_ready=true
spawn_point_count=265
start_spawn_available=true
end_spawn_available=true
ego_spawned=true
rgb_sensor_attached=true
first_rgb_frame_received=true
first_rgb_frame_width=800
first_rgb_frame_height=600
first_rgb_frame_latency_sec=0.168
grp_route_generated=true
grp_route_waypoint_count=512
grp_route_distance_m=991.813812
warmup_ticks_completed=20
cleanup_completed=true
setup_probe_passed=true
setup_blocker_classification=setup_probe_passed
setup_stage_failed=null
setup_probe_duration_sec=4.043
```

## Implementation

```text
parent_wrapper=scripts\run_phase12c_yolov9_r1_setup_recovery.py
child_probe=scripts\run_phase12c_carla_setup_spawn_probe.py
documentation=docs\phase12c_yolov9_r1_setup_recovery.md
```

The child probe records separate setup stages:

```text
stage_01_client_connect
stage_02_world_available
stage_03_town03_loaded_or_reused
stage_04_settings_applied
stage_05_spawn_points_loaded
stage_06_ego_spawned
stage_07_rgb_sensor_attached
stage_08_first_rgb_frame_received
stage_09_grp_route_generated
stage_10_warmup_ticks_completed
stage_11_cleanup_completed
```

## Commands

Dry-run:

```powershell
python scripts\run_phase12c_yolov9_r1_setup_recovery.py --dry-run --output-dir experiments\phase12
```

Setup probe:

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_yolov9_r1_setup_recovery.py --route-id route_01 --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --map-load-mode reuse_or_load --setup-timeout-sec 300 --map-load-timeout-sec 180 --spawn-timeout-sec 120 --sensor-timeout-sec 120 --warmup-ticks 20 --warmup-timeout-sec 120 --require-yolov9-ready
```

## Boundary Fields

```text
runtime_confirmation_executed=false
carla_route_runtime_executed=false
yolo_runtime_row_verified=false
full_phase12c_perception_ablation_runtime_pass=false
rt_detr_runtime_verified=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

No YOLOv9 source, weights, runtime evidence, `.env`, CARLA package, Python environment, raw outputs, runs, or release artifacts should be committed.

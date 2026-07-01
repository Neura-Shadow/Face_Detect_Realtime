# Phase 12C-YOLOv9-R1-SETUP - CARLA Setup / Spawn-Stage Recovery Probe

## Status

```text
Phase 12C-YOLOv9-R1-SETUP Probe Pass - selected route setup reached map ready, ego spawn, RGB sensor attach, first RGB frame, GRP route generation, and warm-up ticks.
```

R1-DIAG classified the selected YOLOv9 runtime blocker as:

```text
diagnostic_evidence_dir=experiments\phase12\20260630T150500Z
previous_runtime_evidence_dir=experiments\phase12\20260630T134322Z
timeout_classification=map_load_or_spawn_stall
diagnosis_confidence=high
```

R1-SETUP isolates the CARLA setup path for the same selected row before any route runtime retry:

```text
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
target_town=Town03
start_spawn_index=3
end_spawn_index=30
```

Formal setup evidence:

```text
setup_evidence_dir=experiments\phase12\20260701T045047Z
dry_run_evidence_dir=experiments\phase12\20260701T045259Z
map_load_mode=reuse_or_load
carla_server_reachable=true
current_map_name=Carla/Maps/Town03
town_ready=true
spawn_point_count=265
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

## Probe Scope

The parent wrapper `scripts/run_phase12c_yolov9_r1_setup_recovery.py` does not import CARLA. It verifies YOLOv9 source-adapter no-fallback readiness, checks TCP reachability, and delegates setup probing to `scripts/run_phase12c_carla_setup_spawn_probe.py` under the CARLA Python 3.12 runtime.

The child probe records these stages separately:

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

Each stage records `started`, `finished`, `duration_sec`, `error_type`, `error_message`, and `timeout_sec`.

## Setup Modes

```text
map_load_mode=reuse_or_load
map_load_mode=force_load
map_load_mode=reuse_existing
```

`reuse_existing` requires the current map to be `Town03` / `Town03_Opt`. `force_load` always calls `client.load_world("Town03")`. `reuse_or_load` reuses the current Town03 map or loads it when needed.

The probe cleans up only actors it creates by default. Existing `role_name=hero` actors are removed only when `--cleanup-existing-actors` is explicitly passed.

## Evidence Layout

R1-SETUP writes:

```text
manifest.json
summary.json
summary.csv
commands.txt
environment.json
README.md
events.jsonl
raw_outputs/
runs/
```

Required setup fields include:

```text
current_map_name
target_map_name
map_load_mode
carla_server_reachable
client_connect_ok
world_ready
town_ready
spawn_point_count
ego_spawned
rgb_sensor_attached
first_rgb_frame_received
grp_route_generated
warmup_ticks_completed
cleanup_completed
setup_probe_passed
setup_blocker_classification
setup_stage_failed
```

## Commands

CARLA server:

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\packages\CARLA_0.9.16\CarlaUE4.exe -carla-rpc-port=2000 -RenderOffScreen -nosound
```

Setup probe:

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_yolov9_r1_setup_recovery.py --route-id route_01 --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --map-load-mode reuse_or_load --setup-timeout-sec 300 --map-load-timeout-sec 180 --spawn-timeout-sec 120 --sensor-timeout-sec 120 --warmup-ticks 20 --warmup-timeout-sec 120 --require-yolov9-ready
```

Dry-run:

```powershell
python scripts\run_phase12c_yolov9_r1_setup_recovery.py --dry-run --output-dir experiments\phase12
```

Optional short route-begin retry after `setup_probe_passed=true` only:

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_yolov9_runtime_timeout_diagnosis.py --route-id route_01 --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --diagnostic-steps 50 --diagnostic-timeout-sec 300 --child-timeout-sec 300 --parent-timeout-sec 900 --require-yolov9-ready --emit-heartbeat-every 5 --emit-partial-metrics-every 10
```

## Boundary

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

R1-SETUP is setup / spawn-stage recovery only. It is not YOLOv9 selected route runtime pass, not YOLOv9 route completion pass, not YOLOv9 model accuracy evidence, not full Phase 12C perception ablation, not RT-DETR runtime evidence, not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

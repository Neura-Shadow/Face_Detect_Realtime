# Walkthrough - Phase 12C-YOLOv9-R1-SETUP Setup Recovery Probe

1. Preserve R1-DIAG as the source of truth for the previous blocker: `timeout_classification=map_load_or_spawn_stall`.
2. Keep the selected row fixed: `route_01`, `grp_follower`, `yolov9`, `Town03`, spawn `3 -> 30`.
3. Do not claim YOLOv9 runtime route pass from setup evidence.
4. Verify YOLOv9 source-adapter no-fallback readiness in the parent wrapper.
5. Keep the parent wrapper free of direct `carla` imports.
6. Run CARLA operations only in the child probe under the CARLA Python 3.12 runtime.
7. Test map-load, settings, spawn points, ego spawn, RGB sensor, first RGB frame, GRP route generation, warm-up ticks, and cleanup as separate stages.
8. Clean up only actors created by this probe unless `--cleanup-existing-actors` is explicitly passed.
9. Write structured evidence and classify the setup blocker if any stage fails.
10. Keep runtime evidence, raw outputs, YOLOv9 source/weights, CARLA packages, venvs, `.env`, and release artifacts out of git.

Implemented files:

```text
scripts\run_phase12c_yolov9_r1_setup_recovery.py
scripts\run_phase12c_carla_setup_spawn_probe.py
docs\phase12c_yolov9_r1_setup_recovery.md
```

Generated setup evidence:

```text
setup_evidence_dir=experiments\phase12\20260701T045047Z
dry_run_evidence_dir=experiments\phase12\20260701T045259Z
setup_probe_passed=true
setup_blocker_classification=setup_probe_passed
```

R1-DIAG background:

```text
diagnostic_evidence_dir=experiments\phase12\20260630T150500Z
previous_runtime_evidence_dir=experiments\phase12\20260630T134322Z
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
timeout_classification=map_load_or_spawn_stall
diagnosis_confidence=high
```

Setup stages:

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

Formal setup command:

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_yolov9_r1_setup_recovery.py --route-id route_01 --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --map-load-mode reuse_or_load --setup-timeout-sec 300 --map-load-timeout-sec 180 --spawn-timeout-sec 120 --sensor-timeout-sec 120 --warmup-ticks 20 --warmup-timeout-sec 120 --require-yolov9-ready
```

Probe result:

```text
carla_server_reachable=true
town_ready=true
ego_spawned=true
rgb_sensor_attached=true
first_rgb_frame_received=true
grp_route_generated=true
warmup_ticks_completed=20
setup_probe_passed=true
setup_blocker_classification=setup_probe_passed
```

Boundary fields:

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

Phase 12C-YOLOv9-R1-SETUP prepares and runs setup-stage evidence only. If the setup probe passes, a later short route-begin diagnostic may be prepared, but it still is not route completion, model accuracy, full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark evidence.

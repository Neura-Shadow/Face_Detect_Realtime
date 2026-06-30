# Current Task - Phase 12C-YOLOv9-R1

## Status

```text
Phase 12C-YOLOv9-R1 Runtime Confirmation Blocked - selected YOLOv9 backend row did not complete or did not satisfy the selected runtime smoke gate.
```

Maintained boundary:

```text
Phase 12C-YOLOv9-R1 is a selected single-route runtime confirmation attempt only. It does not claim full Phase 12C perception ablation runtime pass, YOLOv9 accuracy, RT-DETR runtime verification, CARLA Leaderboard, formal route benchmark, or infraction benchmark.
```

## Selected Runtime Row

```text
route_id=route_01
town=Town03
start_spawn_index=3
end_spawn_index=30
controller_mode=grp_follower
perception_backend=yolov9
horizon_steps=2500
target_speed_kmh=18
route_sampling_resolution_m=2.0
lookahead_waypoints=8
```

## Generated Local Evidence

```text
runtime_evidence_dir=experiments\phase12\20260630T094645Z
dry_run_evidence_dir=experiments\phase12\20260630T095539Z
source_adapter_verified_evidence_dir=experiments\phase12\20260630T060621Z
yolov9_rows_refresh_dir=experiments\phase12\20260630T060823Z
post_unlock_external_source_verified_dir=experiments\phase12\20260630T061015Z
```

Generated output remains local and is not committed.

## Result

```text
blocked_reason=CARLA server is not reachable
source_adapter_verified=true
post_unlock_verified=true
phase12c_yolov9_rows_available=true
backend_unavailable_count=0
YOLOV9_ROOT_configured=true
YOLOV9_WEIGHTS_configured=true
yolov9_source_root_ready=true
yolov9_weights_ready=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
runtime_confirmation_executed=false
carla_route_runtime_executed=false
row_count=1
executed_row_count=0
passed_count=0
blocked_count=1
failed_count=0
goal_reached=null
distance_to_goal_m=null
route_progress_pct=null
collision_count=null
lane_invasion_count=null
metrics_read_status=not_run
yolo_runtime_row_verified=false
```

## Commands

Dry-run wrapper check:

```powershell
python scripts\run_phase12c_yolov9_runtime_confirmation.py --dry-run --output-dir experiments\phase12
```

Formal selected-row runtime gate:

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_yolov9_runtime_confirmation.py --route-id route_01 --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --child-timeout-sec 2400 --parent-timeout-sec 7200 --require-yolov9-ready
```

## Validation Plan

```text
python -m py_compile workers\core\edge_perception.py scripts\run_phase12c_yolov9_runtime_confirmation.py scripts\run_phase12c_yolov9_source_adapter_verification.py scripts\run_phase12c_yolov9_post_unlock_verification.py scripts\run_phase12c_perception_backend_ablation.py scripts\run_phase11_carla_checks.py
D:\CARLA\envs\ma-vlna-carla312\python.exe -m py_compile workers\core\edge_perception.py scripts\run_phase12c_yolov9_runtime_confirmation.py scripts\run_phase12c_yolov9_source_adapter_verification.py scripts\run_phase12c_yolov9_post_unlock_verification.py scripts\run_phase12c_perception_backend_ablation.py scripts\run_phase11_carla_checks.py
python scripts\run_phase12c_yolov9_runtime_confirmation.py --dry-run --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11_carla_checks.py
git diff --check
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

## Boundary Fields

```text
full_phase12c_perception_ablation_runtime_pass=false
rt_detr_runtime_verified=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Next unlock action is to start a reachable CARLA server on `127.0.0.1:2000`, then rerun the same selected-row command. No YOLOv9 source, weights, runtime evidence, `.env`, or baseline dependency changes should be committed.

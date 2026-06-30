# Phase 12C-YOLOv9-R1 - Selected YOLOv9 Runtime Confirmation

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

YOLOv9 source and weights remain external operator assets and are not committed or vendored into MA-VLNA. Baseline requirements remain unchanged.

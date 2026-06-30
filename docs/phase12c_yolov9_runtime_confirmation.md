# Phase 12C-YOLOv9-R1 - Selected YOLOv9 Runtime Confirmation

## Status

```text
Phase 12C-YOLOv9-R1 Runtime Confirmation Blocked - selected YOLOv9 backend row did not complete or did not satisfy the selected runtime smoke gate.
```

This phase attempted one selected real CARLA runtime row after the official YOLOv9 source adapter had already passed no-fallback verification.

```text
runtime_evidence_dir=experiments\phase12\20260630T094645Z
dry_run_evidence_dir=experiments\phase12\20260630T095539Z
blocked_reason=CARLA server is not reachable
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

## Runtime Attempt Result

The selected runtime wrapper verified local YOLOv9 readiness before route execution:

```text
YOLOV9_ROOT_configured=true
YOLOV9_WEIGHTS_configured=true
yolov9_source_root_ready=true
yolov9_weights_ready=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
carla_server_reachable=false
runtime_confirmation_executed=false
carla_route_runtime_executed=false
row_count=1
executed_row_count=0
passed_count=0
blocked_count=1
failed_count=0
metrics_read_status=not_run
yolo_runtime_row_verified=false
```

Because `127.0.0.1:2000` was not reachable at the formal preflight gate, the parent wrapper stopped before invoking the Phase 12B / Phase 11M CARLA child runtime. This preserves blocked evidence instead of fabricating route metrics.

## Command

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

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

The parent wrapper does not import `carla`; it only verifies readiness, checks TCP reachability, and delegates selected route execution to the existing Phase 12B runtime path.

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

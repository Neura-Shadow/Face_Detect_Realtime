# Walkthrough - Phase 12C-YOLOv9-R1-RERUN Selected Runtime Retry

1. Preserve Phase 12C-DUMMY as the only full five-route runtime-confirmed perception backend slice.
2. Preserve Phase 12C-YOLOv9-SRC-V as the authoritative official source adapter no-fallback prerequisite.
3. Rerun only one selected row for R1: `route_01`, `grp_follower`, `yolov9`.
4. Start or verify CARLA 0.9.16 on `127.0.0.1:2000`.
5. Do not run RT-DETR.
6. Do not run the full Phase 12C perception backend matrix.
7. Do not modify VLM, SafetyGate, SemanticPlanner, GRP controller logic, or baseline requirements.
8. Do not commit YOLOv9 source.
9. Do not commit YOLOv9 weights.
10. Do not commit runtime evidence or raw outputs.
11. Require `YOLOV9_ROOT` and `YOLOV9_WEIGHTS`.
12. Require `workers.core.edge_perception --test yolov9` to report no fallback.
13. Require existing SRC-V evidence unless explicitly bypassed.
14. Check `127.0.0.1:2000` before launching the CARLA child runtime.
15. If the child route runtime times out or fails to produce metrics, write blocked evidence and do not fake route metrics.
16. Delegate route execution to the existing Phase 12B runtime path.
17. Keep the parent wrapper free of direct `carla` imports.

Generated evidence:

```text
runtime_evidence_dir=experiments\phase12\20260630T134322Z
previous_blocked_evidence_dir=experiments\phase12\20260630T094645Z
dry_run_evidence_dir=experiments\phase12\20260630T095539Z
source_adapter_verified_evidence_dir=experiments\phase12\20260630T060621Z
yolov9_rows_refresh_dir=experiments\phase12\20260630T060823Z
post_unlock_external_source_verified_dir=experiments\phase12\20260630T061015Z
```

R1-RERUN result:

```text
status=Phase 12C-YOLOv9-R1 Runtime Confirmation Blocked - selected YOLOv9 backend row still did not complete or did not satisfy the selected runtime smoke gate.
carla_server_reachable=true
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
runtime_confirmation_executed=true
carla_route_runtime_executed=true
row_count=1
executed_row_count=1
passed_count=0
blocked_count=1
failed_count=0
child_summary_status=controller_ablation_runtime_blocked
child_row_result=timeout
child_inner_exit_code=124
child_duration_sec=2400.311
goal_reached=null
distance_to_goal_m=null
route_progress_pct=null
collision_count=null
lane_invasion_count=null
metrics_read_status=loaded
yolo_runtime_row_verified=false
```

CARLA server command used locally:

```powershell
D:\CARLA\packages\CARLA_0.9.16\CarlaUE4.exe -carla-rpc-port=2000 -RenderOffScreen -nosound
```

Formal selected-row command:

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_yolov9_runtime_confirmation.py --route-id route_01 --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --child-timeout-sec 2400 --parent-timeout-sec 7200 --require-yolov9-ready
```

Boundary fields:

```text
full_phase12c_perception_ablation_runtime_pass=false
rt_detr_runtime_verified=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Validation checklist:

```text
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11_carla_checks.py
git diff --check
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

Phase 12C-YOLOv9-R1-RERUN is not a full Phase 12C perception ablation runtime pass. It means the selected YOLOv9 runtime row reached CARLA and launched the child route runner, but the selected row timed out before route metrics or goal-reach evidence were produced.

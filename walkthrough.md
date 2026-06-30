# Walkthrough - Phase 12C-YOLOv9-R1-DIAG Timeout Diagnosis

1. Preserve Phase 12C-DUMMY as the only full five-route runtime-confirmed perception backend slice.
2. Preserve Phase 12C-YOLOv9-SRC-V as the authoritative official source adapter no-fallback prerequisite.
3. Diagnose only the selected R1 row: `route_01`, `grp_follower`, `yolov9`.
4. Keep the previous R1-RERUN blocked evidence at `experiments\phase12\20260630T134322Z`.
5. Do not rerun the full Phase 12C perception backend matrix.
6. Do not run RT-DETR.
7. Do not modify VLM, SafetyGate, SemanticPlanner, GRP controller decision logic, or baseline requirements.
8. Do not commit YOLOv9 source.
9. Do not commit YOLOv9 weights.
10. Do not commit runtime evidence or raw outputs.
11. Require `YOLOV9_ROOT` and `YOLOV9_WEIGHTS`.
12. Require `workers.core.edge_perception --test yolov9` to report no fallback.
13. Emit diagnostic events, heartbeat files, and partial metrics when the loop reaches runtime steps.
14. If the child route runtime fails before route metrics, classify the timeout from structured breadcrumbs rather than fabricating route metrics.
15. Keep the parent wrapper free of direct `carla` imports.

Generated evidence:

```text
diagnostic_evidence_dir=experiments\phase12\20260630T150500Z
dry_run_evidence_dir=experiments\phase12\20260630T150101Z
previous_runtime_evidence_dir=experiments\phase12\20260630T134322Z
previous_blocked_evidence_dir=experiments\phase12\20260630T094645Z
source_adapter_verified_evidence_dir=experiments\phase12\20260630T060621Z
yolov9_rows_refresh_dir=experiments\phase12\20260630T060823Z
post_unlock_external_source_verified_dir=experiments\phase12\20260630T061015Z
```

R1-DIAG result:

```text
status=Phase 12C-YOLOv9-R1-DIAG Diagnostic Completed - bounded diagnostic evidence was produced without claiming runtime pass.
carla_server_reachable=true
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
diagnostic_scope=selected_single_route_timeout_diagnosis
source_adapter_verified=true
post_unlock_verified=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
runtime_confirmation_executed=true
carla_route_runtime_executed=true
diagnostic_steps_requested=300
diagnostic_steps_completed=0
heartbeat_count=0
world_tick_count=0
rgb_frame_received_count=0
edge_perception_call_count=0
yolov9_inference_call_count=0
partial_route_progress_seen=false
timeout_classification=map_load_or_spawn_stall
diagnosis_confidence=high
child_summary_status=controller_ablation_runtime_blocked
child_row_result=grp_blocked
child_exit_code=1
child_row_duration_sec=207.801
yolo_runtime_row_verified=false
```

Observed breadcrumb sequence:

```text
edge_perception_model_load_started
edge_perception_model_load_finished
carla_setup_started
run_failed
```

No `carla_setup_finished`, `world_tick_finished`, `rgb_frame_received`, `edge_perception_finished`, heartbeat, or partial route progress event appeared. The diagnostic therefore classifies the blocker as `map_load_or_spawn_stall`, not a verified per-frame YOLOv9 inference slowdown.

CARLA server command used locally:

```powershell
D:\CARLA\packages\CARLA_0.9.16\CarlaUE4.exe -carla-rpc-port=2000 -RenderOffScreen -nosound
```

Formal diagnostic command:

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_yolov9_runtime_timeout_diagnosis.py --route-id route_01 --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --diagnostic-steps 300 --diagnostic-timeout-sec 900 --child-timeout-sec 900 --parent-timeout-sec 1800 --require-yolov9-ready --emit-heartbeat-every 10 --emit-partial-metrics-every 25
```

Boundary fields:

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

Validation checklist:

```text
python -m py_compile workers\core\edge_perception.py scripts\run_phase12c_yolov9_runtime_timeout_diagnosis.py scripts\run_phase12c_yolov9_runtime_confirmation.py scripts\run_phase12c_yolov9_source_adapter_verification.py scripts\run_phase12c_yolov9_post_unlock_verification.py scripts\run_phase12c_perception_backend_ablation.py scripts\run_phase11_carla_checks.py
D:\CARLA\envs\ma-vlna-carla312\python.exe -m py_compile workers\core\edge_perception.py scripts\run_phase12c_yolov9_runtime_timeout_diagnosis.py scripts\run_phase12c_yolov9_runtime_confirmation.py scripts\run_phase12c_yolov9_source_adapter_verification.py scripts\run_phase12c_yolov9_post_unlock_verification.py scripts\run_phase12c_perception_backend_ablation.py scripts\run_phase11_carla_checks.py
python scripts\run_phase12c_yolov9_runtime_timeout_diagnosis.py --dry-run --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11_carla_checks.py
git diff --check
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

Phase 12C-YOLOv9-R1-DIAG is not a selected route runtime pass. It only explains the previous selected-row timeout: YOLOv9 no-fallback readiness held, CARLA was reachable, model load completed, and the run failed during CARLA setup before world ticks, RGB frames, or route metrics.

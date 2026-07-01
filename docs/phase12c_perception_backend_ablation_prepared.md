# Phase 12C — Perception Backend Ablation Prepared

## Status

```text
Phase 12C Perception Backend Ablation Prepared - backend matrix, optional dependency preflight, and command scaffold are implemented.
```

Phase 12C 將 Phase 12B-SUM 選出的 strongest smoke controller 固定為 `grp_follower`，只變動 perception backend，避免 controller 與 perception 兩個變因混在一起。此階段是 ablation scaffold / preflight，不啟動 CARLA、不 import `carla` package，也不宣稱 runtime pass。

## Matrix

固定路線仍沿用 calibrated Phase 12A-C / Phase 12B matrix：

| route_id | start_spawn_index | end_spawn_index | horizon_steps | target_speed_kmh | route_sampling_resolution_m | lookahead_waypoints |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `route_01` | 3 | 30 | 2500 | 18 | 2.0 | 8 |
| `route_02` | 8 | 52 | 2800 | 18 | 2.0 | 8 |
| `route_03` | 12 | 74 | 2500 | 18 | 2.0 | 8 |
| `route_04` | 25 | 101 | 2500 | 18 | 2.0 | 8 |
| `route_05` | 40 | 126 | 5400 | 8 | 1.0 | 3 |

Perception backend matrix：

| perception_backend_mode | runtime backend | model hint | dependency | behavior |
| --- | --- | --- | --- | --- |
| `dummy` | `dummy` | `dummy` | none | always available |
| `yolov9_optional` | `yolov9` | `yolov9` | YOLOv9 external source adapter | no-fallback gate 通過後 rows available / command-ready |
| `rt_detr_optional` | `rtdetr` | `rtdetr-l.pt` | `ultralytics` | dependency missing 時標記 `backend_unavailable` |

## Generated Local Evidence

```text
experiments\phase12\20260630T060823Z
```

本次 scaffold output：

```text
row_count=5
route_count=5
backend_count=1
controller_mode=grp_follower
available_row_count=5
backend_unavailable_count=0
yolov9_source_adapter_verified=true
```

本機目前在 target CARLA Python 3.12 runtime 中已配置 `YOLOV9_ROOT` / `YOLOV9_WEIGHTS`，且 official YOLOv9 external source adapter no-fallback verification 已通過，因此 YOLOv9 optional rows 現在是 available / command-ready。這不是 full Phase 12C perception ablation runtime pass；它只代表 scaffold command readiness。RT-DETR optional rows 仍取決於 `ultralytics` dependency，未在本次驗證中宣稱 runtime pass。

YOLOv9 preflight 使用 `--python-executable` 指向的 target runtime 執行 `workers.core.edge_perception --test yolov9`，並要求 `edge_yolov9_fallback_used=false` 才讓 rows available。這可避免只靠 base Python 或 package metadata 誤判 YOLOv9 readiness。

Generated files：

- `manifest.json`
- `summary.csv`
- `summary.json`
- `commands.txt`
- `README.md`

## Command

```powershell
python scripts\run_phase12c_perception_backend_ablation.py --output-dir experiments\phase12
```

若之後要只產生特定 route 或 backend 的 command scaffold：

```powershell
python scripts\run_phase12c_perception_backend_ablation.py --route-id route_01 --perception-backend-mode dummy --output-dir experiments\phase12
```

## Runtime Boundary

Phase 12C 只建立可審核的 backend ablation command scaffold。它不會：

- 啟動 CARLA server
- import `carla`
- 自動安裝 `ultralytics`
- 執行 YOLO / RT-DETR real model inference
- 改動 VLM、SafetyGate、SemanticPlanner、GRP controller 或 baseline requirements

Benchmark boundary：

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

## YOLOv9 Runtime Timeout Diagnosis

Phase 12C-YOLOv9-R1-DIAG has now added selected-row timeout instrumentation after the R1-RERUN blocked evidence.

```text
diagnostic_evidence_dir=experiments\phase12\20260630T150500Z
previous_runtime_evidence_dir=experiments\phase12\20260630T134322Z
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
timeout_classification=map_load_or_spawn_stall
diagnosis_confidence=high
diagnostic_steps_completed=0
heartbeat_count=0
world_tick_count=0
rgb_frame_received_count=0
edge_perception_call_count=0
yolov9_inference_call_count=0
yolo_runtime_row_verified=false
full_phase12c_perception_ablation_runtime_pass=false
```

This diagnosis keeps YOLOv9 optional rows available / command-ready after source-adapter verification, but it does not promote YOLOv9 to a runtime-confirmed backend. The blocker occurred before CARLA setup finished and before the route loop produced RGB frames, heartbeat, or route metrics.

## YOLOv9 Setup Recovery Probe

Phase 12C-YOLOv9-R1-SETUP is the follow-up setup-stage probe for that blocker.

```text
setup_evidence_dir=experiments\phase12\20260701T045047Z
parent_wrapper=scripts\run_phase12c_yolov9_r1_setup_recovery.py
child_probe=scripts\run_phase12c_carla_setup_spawn_probe.py
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
setup_scope=map_load_spawn_rgb_grp_warmup_only
setup_probe_passed=true
setup_blocker_classification=setup_probe_passed
yolo_runtime_row_verified=false
full_phase12c_perception_ablation_runtime_pass=false
```

Passing the setup probe would only prove setup readiness, not route completion or backend ablation runtime pass.

## Validation

```powershell
python -m py_compile scripts\run_phase12c_perception_backend_ablation.py
python scripts\run_phase12c_perception_backend_ablation.py --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
```

Acceptance assertions：

- full scaffold can produce `summary.json.row_count == 15`
- latest YOLOv9-only refresh has `summary.json.row_count == 5`
- dummy rows are available
- YOLOv9 optional rows are available / command-ready after source adapter no-fallback verification
- RT-DETR optional rows may still be `backend_unavailable`
- `backend_unavailable` rows do not make the scaffold exit nonzero
- optional backend dependency checks use the target Python runtime
- all benchmark boundary fields remain false

## Follow-up Runtime Slice

Phase 12C-DUMMY 已完成第一個 backend runtime confirmation：

```text
Phase 12C-DUMMY Runtime Confirmation Pass - dummy backend rows confirmed in real CARLA runtime.
```

Evidence：

```text
experiments\phase12\20260628T173019Z
row_count=5
passed_count=5
collision_count_total=0
lane_invasion_count_total=83
```

詳細記錄請見 [phase12c_dummy_backend_runtime_confirmation.md](phase12c_dummy_backend_runtime_confirmation.md)。

## YOLO Optional Dependency Unlock

Phase 12C-YOLO-U 是早期 generic YOLO unlock preparation 歷史紀錄；Phase 12C-YOLOv9-U 是修訂後的 YOLOv9-specific target。舊 evidence 不會被改寫成 YOLOv9 evidence。

Phase 12C-YOLOv9-U 已完成 YOLOv9 optional dependency unlock preparation：

```text
Phase 12C-YOLOv9-U Prepared — YOLOv9 optional dependency unlock commands and evidence were written.
```

Evidence：

```text
experiments\phase12\20260629T063232Z
dependency_ready=false
dependency_missing=true
edge_yolov9_command_supported=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=true
auto_install_performed=false
baseline_requirements_modified=false
runtime_confirmation_executed=false
```

Manual unlock commands：

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install <YOLOV9_PACKAGE_SPEC>
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install -r <YOLOV9_REQUIREMENTS_PATH>
```

詳細記錄請見 [phase12c_yolov9_optional_dependency_unlock_prepared.md](phase12c_yolov9_optional_dependency_unlock_prepared.md)。

## YOLOv9 Backend Adapter

Phase 12C-YOLOv9-B 已完成 EdgePerception YOLOv9 backend adapter preparation：

```text
Phase 12C-YOLOv9-B Prepared — EdgePerception YOLOv9 backend adapter path is registered.
```

Evidence：

```text
experiments\phase12\20260629T063232Z-1-1
edge_yolov9_backend_registered=true
base_edge_yolov9_command_supported=true
carla312_edge_yolov9_command_supported=true
base_edge_yolov9_fallback_used=true
carla312_edge_yolov9_fallback_used=true
runtime_confirmation_executed=false
```

詳細記錄請見 [phase12c_yolov9_backend_adapter_prepared.md](phase12c_yolov9_backend_adapter_prepared.md)。

## YOLOv9 Post-Unlock Verification

Phase 12C-YOLOv9-V strict post-unlock verification gate 已通過 external_source mode：

```text
Phase 12C-YOLOv9-SRC-V Passed — official YOLOv9 source adapter verified with no fallback in the CARLA Python 3.12 runtime.
```

Evidence：

```text
post_unlock_external_source_verified_dir=experiments\phase12\20260630T061015Z
post_unlock_verified=true
require_verified_requested=true
strict_gate_exit_code=0
unlock_mode=external_source
source_adapter_verified=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
phase12b_yolov9_dry_run_command_ready=true
phase11m_yolov9_cli_ready=true
phase12c_yolov9_rows_available=true
backend_unavailable_count=0
runtime_confirmation_executed=false
carla_route_runtime_executed=false
```

詳細記錄請見 [phase12c_yolov9_post_unlock_verification.md](phase12c_yolov9_post_unlock_verification.md)。

## YOLOv9 Official Source Adapter

Phase 12C-YOLOv9-SRC 已實作官方 source-repo adapter 與 no-fallback verification gate；Phase 12C-YOLOv9-SRC-V 已完成 no-fallback verification：

```text
Phase 12C-YOLOv9-SRC-V Passed — official YOLOv9 source adapter verified with no fallback in the CARLA Python 3.12 runtime.
```

Local source-adapter evidence：

```text
source_adapter_verified_evidence_dir=experiments\phase12\20260630T060621Z
yolov9_rows_refresh_dir=experiments\phase12\20260630T060823Z
post_unlock_external_source_verified_dir=experiments\phase12\20260630T061015Z
source_adapter_verified=true
YOLOV9_ROOT_configured=true
YOLOV9_WEIGHTS_configured=true
yolov9_source_root_ready=true
yolov9_weights_ready=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
post_unlock_verified=true
backend_unavailable_count=0
runtime_confirmation_executed=false
carla_route_runtime_executed=false
auto_install_performed=false
baseline_requirements_modified=false
carla_server_started=false
```

YOLOv9 optional rows are now available / command-ready in the Phase 12C scaffold after no-fallback source adapter verification. YOLOv9 source and weights remain external and are not committed to this repository. No YOLOv9 source is vendored into MA-VLNA, no baseline requirements were modified, and no YOLOv9 model accuracy claim is made. The source-adapter verification itself did not execute a CARLA route runtime; the follow-up R1 selected-row runtime attempt is recorded below as blocked.

詳細記錄請見 [phase12c_yolov9_source_adapter_verification.md](phase12c_yolov9_source_adapter_verification.md)。

## YOLOv9 Selected Runtime Confirmation

Phase 12C-YOLOv9-R1 已嘗試單一路線 runtime confirmation：

```text
Phase 12C-YOLOv9-R1 Runtime Confirmation Blocked - selected YOLOv9 backend row did not complete or did not satisfy the selected runtime smoke gate.
```

Evidence:

```text
runtime_evidence_dir=experiments\phase12\20260630T134322Z
previous_blocked_evidence_dir=experiments\phase12\20260630T094645Z
carla_server_reachable=true
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
source_adapter_verified=true
post_unlock_verified=true
phase12c_yolov9_rows_available=true
backend_unavailable_count=0
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
runtime_confirmation_executed=true
carla_route_runtime_executed=true
child_row_result=timeout
child_inner_exit_code=124
child_duration_sec=2400.311
goal_reached=null
distance_to_goal_m=null
route_progress_pct=null
collision_count=null
lane_invasion_count=null
metrics_read_status=loaded
```

R1-RERUN 只確認 selected single-route runtime gate 的 blocked evidence handling：CARLA server 已可達，selected `grp_follower + yolov9` row 已啟動，但 child route runtime timeout，未產生 route metrics 或 goal-reach evidence。它不是 full Phase 12C perception ablation runtime pass，也不是 YOLOv9 accuracy、RT-DETR runtime、CARLA Leaderboard、formal route benchmark 或 infraction benchmark。

詳細記錄請見 [phase12c_yolov9_runtime_confirmation.md](phase12c_yolov9_runtime_confirmation.md)。

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
| `yolov9_optional` | `yolov9` | `yolov9` | YOLOv9 optional dependency | target CARLA Python dependency missing 時標記 `backend_unavailable` |
| `rt_detr_optional` | `rtdetr` | `rtdetr-l.pt` | `ultralytics` | dependency missing 時標記 `backend_unavailable` |

## Generated Local Evidence

```text
experiments\phase12\20260629T070603Z
```

本次 scaffold output：

```text
row_count=15
route_count=5
backend_count=3
controller_mode=grp_follower
available_row_count=5
backend_unavailable_count=10
```

本機目前在 target CARLA Python 3.12 runtime 中未具備 YOLOv9 optional dependency，且未安裝 `ultralytics` RT-DETR dependency，因此 YOLOv9 / RT-DETR optional rows 被正確標記為 `backend_unavailable`。這不是失敗；Phase 12C 的設計要求 optional backend missing 不得阻塞 dummy baseline scaffold。

Dependency preflight 使用 `--python-executable` 指向的 target runtime，而不是 base Python。這可避免 YOLOv9 只安裝在 `D:\CARLA\envs\ma-vlna-carla312` 時被 base Python 誤判為 unavailable。

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

## Validation

```powershell
python -m py_compile scripts\run_phase12c_perception_backend_ablation.py
python scripts\run_phase12c_perception_backend_ablation.py --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
```

Acceptance assertions：

- `summary.json.row_count == 15`
- dummy rows are available
- optional YOLO / RT-DETR rows may be `backend_unavailable`
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

Phase 12C-YOLOv9-V 已建立 strict post-unlock verification gate，並在目前本機環境產生 blocked evidence：

```text
Phase 12C-YOLOv9-V Blocked — post-unlock verification attempted, but the CARLA Python 3.12 runtime still lacks the YOLOv9 dependency.
```

Evidence：

```text
experiments\phase12\20260629T070450Z
post_unlock_verified=false
yolov9_import_ready=false
yolov9_pip_metadata_ready=false
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=true
phase12b_yolov9_dry_run_command_ready=true
phase11m_yolov9_cli_ready=true
phase12c_yolov9_rows_available=false
```

詳細記錄請見 [phase12c_yolov9_post_unlock_verification.md](phase12c_yolov9_post_unlock_verification.md)。

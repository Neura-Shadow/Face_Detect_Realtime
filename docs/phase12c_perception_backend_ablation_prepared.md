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
| `yolo_optional` | `yolo` | `yolov8n.pt` | `ultralytics` | dependency missing 時標記 `backend_unavailable` |
| `rt_detr_optional` | `rtdetr` | `rtdetr-l.pt` | `ultralytics` | dependency missing 時標記 `backend_unavailable` |

## Generated Local Evidence

```text
experiments\phase12\20260628T170342Z
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

本機目前未安裝 `ultralytics`，因此 YOLO / RT-DETR optional rows 被正確標記為 `backend_unavailable`。這不是失敗；Phase 12C 的設計要求 optional backend missing 不得阻塞 dummy baseline scaffold。

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

Phase 12C-YOLO-U 已完成 YOLO optional dependency unlock preparation：

```text
Phase 12C-YOLO-U Prepared - YOLO optional dependency unlock commands and evidence were written.
```

Evidence：

```text
experiments\phase12\20260629T030122Z
dependency_ready=false
dependency_missing=true
edge_yolo_fallback_used=true
auto_install_performed=false
baseline_requirements_modified=false
runtime_confirmation_executed=false
```

Manual unlock command：

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install "ultralytics>=8,<9"
```

詳細記錄請見 [phase12c_yolo_optional_dependency_unlock_prepared.md](phase12c_yolo_optional_dependency_unlock_prepared.md)。

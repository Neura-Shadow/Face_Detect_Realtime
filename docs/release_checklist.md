# MA-VLNA Release Checklist

## Latest Phase 12C-YOLOv9-R1 Formal Gate Addendum

- [x] **Phase 12C-YOLOv9-R1 Selected Runtime Confirmation Blocked**: `experiments\phase12\20260702T182842Z` records `source_adapter_verified=true`, `post_unlock_verified=true`, `edge_yolov9_command_passed=true`, `edge_yolov9_fallback_used=false`, `edge_yolov9_no_fallback_verified=true`, `phase12c_yolov9_rows_available=true`, and `backend_unavailable_count=0`, but `carla_server_reachable=false`. Therefore `runtime_confirmation_executed=false`, `carla_route_runtime_executed=false`, `metrics_read_status=not_run`, and `yolo_runtime_row_verified=false`. The dry-run evidence is `experiments\phase12\20260702T182831Z`.

Boundary: this is selected single-route gate evidence only. It is not full Phase 12C perception ablation runtime pass, not YOLOv9 model accuracy evidence, not RT-DETR runtime verification, not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

## Latest Phase 12C-R1-RT-DETR-WEIGHTS-LOCAL Addendum

- [x] **Phase 12C-R1-RT-DETR-WEIGHTS-LOCAL-RERUN Local Weight Adoption Blocked**: `experiments\phase12\20260702T125105Z` records `ultralytics_import_ready_after=true`, `ultralytics_version_after=8.4.84`, and `RTDETR_WEIGHTS` configured to `D:\AIModels\rtdetr\rtdetr-l.pt`, but the local file is still missing. Therefore `rtdetr_weights_ready=false`, `missing_weight_path=D:\AIModels\rtdetr\rtdetr-l.pt`, `post_setup_smoke_executed=false`, `edge_rtdetr_command_passed=null`, `edge_rtdetr_fallback_used=null`, `edge_rtdetr_no_fallback_verified=false`, `phase12c_rtdetr_rows_available=false`, and `recommended_next_phase=R1-RT-DETR-ASSET-SETUP`.

Boundary: this is local asset verification and no-fallback smoke gating only. No RT-DETR weights were downloaded or committed, CARLA route runtime was not started, no RT-DETR no-fallback readiness is claimed, and this does not claim RT-DETR route runtime pass, route completion, accuracy, full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark evidence.

## Latest Phase 12C-R1-RT-DETR-ASSET-EXEC Addendum

- [x] **Phase 12C-R1-RT-DETR-ASSET-EXEC Explicit Install Blocked**: `experiments\phase12\20260702T044516Z` records an operator-approved dependency install into the CARLA Python 3.12 runtime. `dependency_install_requested=true`, `dependency_install_executed=true`, `dependency_install_exit_code=0`, `ultralytics_import_ready_before=false`, `ultralytics_import_ready_after=true`, and `ultralytics_version_after=8.4.84`. The gate remains blocked because `rtdetr_weights_configured=true` but `rtdetr_weights_ready=false` for `D:\AIModels\rtdetr\rtdetr-l.pt`; therefore `post_setup_smoke_executed=false`, `edge_rtdetr_command_passed=null`, `edge_rtdetr_fallback_used=null`, `edge_rtdetr_no_fallback_verified=false`, `phase12c_rtdetr_rows_available=false`, and `recommended_next_phase=R1-RT-DETR-ASSET-SETUP`.

Boundary: this is dependency setup and local asset checking only. No RT-DETR weights were downloaded or committed, baseline requirements were not modified, CARLA route runtime was not started, and this does not claim RT-DETR runtime pass, RT-DETR accuracy, full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark evidence.

## Latest Phase 12C-R1-RT-DETR-ASSET-SETUP Addendum

- [x] **Phase 12C-R1-RT-DETR-ASSET-SETUP Command-Ready**: `experiments\phase12\20260702T040554Z` writes explicit RT-DETR dependency install, asset-directory, local-weight, post-setup smoke, and RT-DETR-only row-refresh commands. Current evidence records `ultralytics_import_ready_before=false`, `ultralytics_import_ready_after=false`, `dependency_install_requested=false`, `dependency_install_executed=false`, `rtdetr_weights_configured=false`, `rtdetr_weights_ready=false`, `edge_rtdetr_command_passed=null`, `edge_rtdetr_fallback_used=null`, `edge_rtdetr_no_fallback_verified=false`, `phase12c_rtdetr_rows_available=false`, and `recommended_next_phase=R1-RT-DETR-ASSET-SETUP`.

Boundary: this is dependency and local asset setup only. It does not silently install dependencies, download or commit RT-DETR weights, modify baseline requirements, start CARLA route runtime, claim RT-DETR runtime pass, verify RT-DETR accuracy, or claim full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark evidence.

## Latest Phase 12C-R1-RT-DETR-UNLOCK Addendum

- [x] **Phase 12C-R1-RT-DETR-UNLOCK Optional Backend Readiness Blocked**: `experiments\phase12\20260702T022636Z-1` records `ultralytics_import_ready=false`, `rtdetr_weights_configured=false`, `rtdetr_weights_ready=false`, `edge_rtdetr_command_supported=true`, `edge_rtdetr_command_passed=true`, `edge_rtdetr_fallback_used=true`, `edge_rtdetr_no_fallback_verified=false`, `phase12c_rtdetr_rows_available=false`, `phase12c_rtdetr_backend_unavailable_count=5`, and `recommended_next_phase=R1-RT-DETR-ASSET-SETUP`. The dry-run evidence is `experiments\phase12\20260702T022636Z`.

Boundary: this is RT-DETR unlock / no-fallback readiness only. It does not start CARLA route runtime, does not claim RT-DETR accuracy, and does not claim full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark evidence.

## Latest Phase 12C-YOLOv9-R1 Formal Gate Addendum

- [x] **Phase 12C-YOLOv9-R1 Selected Runtime Confirmation Blocked**: `experiments\phase12\20260702T182842Z` records `source_adapter_verified=true`, `edge_yolov9_fallback_used=false`, `edge_yolov9_no_fallback_verified=true`, `phase12c_yolov9_rows_available=true`, and `backend_unavailable_count=0`, but `carla_server_reachable=false`. Therefore `runtime_confirmation_executed=false`, `carla_route_runtime_executed=false`, `metrics_read_status=not_run`, and `yolo_runtime_row_verified=false`. The dry-run evidence is `experiments\phase12\20260702T182831Z`.

Boundary: this is selected single-route gate evidence only. It is not full Phase 12C perception ablation runtime pass, not YOLOv9 model accuracy evidence, not RT-DETR runtime verification, not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

> 版本發佈前驗證清單 — 記錄所有驗證結果與待辦事項 (v0.3.1 Release)

---

## ✅ Completed & Verified（已完成且驗證之主要工程閉環）

### Core Integration
- [x] **Supabase Real Integration**: 真實資料庫連線、pgvector HNSW 索引、RPC 檢索與前端即時讀取功能皆已完成驗證。
- [x] **Camera / Mock Mode Runtime**: 攝影機介面與模擬迴圈（12 步自動駕駛主迴圈）執行穩定無崩潰。
- [x] **SafetyGate Final Regression**: 仲裁機制全面覆蓋（信心不足、超速、禁止動作、嚴重危害與 Fallback 攔截）。
- [x] **VLM Reasoning Trace Pipeline**: 感知 -> 觸發 -> 推理 -> 安全仲裁 -> 規劃 -> 遙測，完整決策鏈寫入。
- [x] **.env / API Key Safety Audit**: 專案已完全排除 hardcoded keys，`.env.example` 僅存放 placeholder。

### Edge AI Perception
- [x] **Edge AI Perception Abstraction**: 支援標準化的物件偵測介面與統一的 `PerceptionResult` Schema。
- [x] **YOLO / RT-DETR Optional Backend**: 支援外掛式載入。
- [x] **Graceful Fallback**: 若環境缺乏模型、權重或 `ultralytics`，完美降級至 `DummyPerceptionBackend`，不引發 Crash。

### CARLA / Phase 11
- [x] **Phase 11 No-Server Smoke Checks**: `scripts/run_phase11_carla_checks.py` 可在沒有 CARLA server 與 `carla` wheel 的環境下驗證 import、設定載入與 control mapping。
- [x] **Phase 11 Core Runtime Verification**: `scripts/run_phase11_core_runtime_checks.py` 使用 fake CARLA runtime 跑通 local planner 與 LocalStub VLM 兩條 closed-loop orchestration。
- [x] **Phase 11B Real CARLA Smoke Gate**: `scripts/run_phase11b_real_carla_smoke.py` 已建立真實 server preflight / skipped / required-fail 語意。
- [x] **Phase 11B Environment Setup Guide**: `docs/phase11b_real_carla_environment_setup.md` 已補齊 CARLA package、Python wheel、server 啟動、preflight、smoke test 與 troubleshooting 流程。
- [x] **Phase 11C Runtime Execution Attempt**: 已使用 `--require-server` 嘗試真實 CARLA runtime；本機缺少 `carla` wheel 且 `127.0.0.1:2000` 不可達，因此紀錄為 blocked locally。
- [x] **Phase 11D Provisioning Gate**: `scripts/run_phase11d_carla_provisioning_gate.py` 已建立 read-only provisioning gate；目前結果為 blocked，會以 `--require-ready` exit 1 擋下未 provisioned 的 runtime。
- [x] **Phase 11E Unlock Kit**: `scripts/phase11e_unlock_carla_environment.ps1` 已建立 Windows unlock helper，可在指定 `CARLA_ROOT` 後安裝 wheel、啟動 server、重跑 11D 與 11C gate。
- [x] **Phase 11F External CARLA Provisioning Attempt**: 已檢查 `CARLA_ROOT`、`C:\`、`D:\` 與 Downloads；未找到有效 CARLA server package root，因此停止於 blocker，未安裝 wheel、未啟 server、未跑 real runtime smoke。
- [x] **Phase 11G Automated D Drive Provisioning Attempt**: 已下載並解壓 CARLA 0.9.16 Windows package 到 `D:\CARLA`，但 package wheel 為 CPython 3.12，與目前 Python 3.10.14 不相容，因此停止於 wheel install blocker。
- [x] **Phase 11H Python 3.12 CARLA Runtime Environment**: 已建立 `D:\CARLA\envs\ma-vlna-carla312`，安裝 CARLA 0.9.16 `cp312` wheel，啟動真實 CARLA server，並通過 11D `--require-ready`、11C 5-step 與 50-step `--require-server` smoke。
- [x] **Phase 11I CARLA Runtime Evidence Pack**: 已產生 `runtime_logs\carla_runs\20260613T073948Z`，包含 manifest、metrics、events、commands、environment、regression 與 raw stdout/stderr，支援 5/50-step real smoke 審核。
- [x] **Phase 11J CARLA Sensor Metrics Instrumentation**: 已產生 `runtime_logs\carla_runs\20260613T082452Z`，在真實 CARLA smoke 中掛載 collision/lane invasion sensors，並量測 speed 與 distance。
- [x] **Phase 11K Fixed Route Scenario Smoke**: 已產生 `runtime_logs\carla_runs\20260613T092548Z`，在真實 CARLA smoke 中建立 `Town03` spawn-pair route，並量測 route progress。
- [x] **Phase 11L Fixed Route Completion Attempt**: 已產生 `runtime_logs\carla_runs\20260613T130532Z`，在真實 CARLA smoke 中通過 strict fixed spawn-pair goal-reach gate。
- [x] **Phase 11M GRP-backed Route Following**: 已產生 `runtime_logs\carla_runs\20260614T173740Z`，在真實 CARLA smoke 中使用 CARLA `GlobalRoutePlanner` route-following 通過 strict goal-reach gate，並保留 benchmark boundary。
- [x] **Phase 11N Git Snapshot & Release Packaging**: 已產生 timestamped `release_artifacts` package，包含 git snapshot、artifact boundary、checksums 與 release zip；精確路徑與 SHA-256 以 generated `manifest.json` / `package.sha256` 為準。
- [x] **Phase 11O Source Commit Boundary & Draft PR Preparation**: 已新增 staged-file boundary gate 與 Draft PR handoff 文件，將 source commit 與 runtime/release artifacts 明確分離。
- [x] **Phase 12 Experiment Kickoff Preparation**: 已新增 experiment kickoff plan 與 scaffold script；此階段只建立計畫與輸出格式，不啟動 CARLA 或大型實驗。
- [x] **Phase 12A CARLA Route Scaling Evidence Produced**: 已在真實 CARLA runtime 執行 5-route `Town03` GRP smoke batch，產生 aggregate evidence；4/5 routes passed，`route_05` 因 strict goal-reach failure 使 all-route gate 保持 blocked。
- [x] **Phase 12A-R05 Failure Diagnosis & Recovery Evidence**: 已執行 Route 05 專用 recovery-variant runner；4 個 conservative variants 均未達 strict goal tolerance。`r05_slow_short_lookahead` 無碰撞且進度提升至 71.07%，但 Phase 12A-R05 仍保持 blocked。
- [x] **Phase 12A-R05B Waypoint Progression Diagnosis**: 已解析 `r05_slow_short_lookahead` late-route waypoint progression；2500-step 末段仍持續推進，5200-step extended diagnostic 於 step 4431 達成 Route 05 goal tolerance。Phase 12A 原 2500-step all-route gate 仍保持 blocked。
- [x] **Phase 12A-H Horizon Calibration**: 已將 Phase 12A / R05B evidence 校準成 per-route step horizon matrix：`2500, 2800, 2500, 2500, 5400`；此矩陣僅用於 smoke horizon，不是 formal benchmark。
- [x] **Phase 12A-C Calibrated Runtime Confirmation**: 已以 calibrated horizon matrix 重跑五條 `Town03` routes；5/5 routes reached goal，且各 route `collision_count=0`。此結果確認 calibrated smoke setup，不改寫原 2500-step Phase 12A gate。
- [x] **Phase 12B Controller Ablation Scaffold**: 已建立 5 routes x 3 controller modes 的 15-row dry-run scaffold 與 summary aggregation；此階段不執行大型 CARLA runtime，不是 Runtime Pass。
- [x] **Phase 12B-R Controller Ablation Runtime Wiring**: 已加入顯式 `--execute-runtime` path、child stdout/stderr 保存、evidence metrics 讀取與 blocked/pass/fail aggregation；本機 smoke 產生 blocked evidence，不是 Runtime Pass。
- [x] **Phase 12B-GRP GRP Controller Ablation Runtime Pass**: 已在真實 CARLA runtime 執行 5 條 calibrated `grp_follower` rows；5/5 rows passed，且各 route `collision_count=0`。此為 GRP subset pass，不代表所有 controller modes 或 formal benchmark。
- [x] **Phase 12B-LIN Linear Spawn-Pair Controller Runtime Pass / Blocked Evidence**: 初次 full batch 保留 `route_01` map-load timeout blocked evidence；warm-up 後 5/5 `linear_spawn_pair_follower` rows passed route-progress smoke。此結果 collision counts 很高，只代表 route-progress smoke pass。
- [x] **Phase 12B-BASE-M Baseline PlannerAction Mapper Route-Metric Wiring**: 已為 `baseline_planner_action_mapper` rows 接上 dedicated child runner 與 fixed-route metrics aggregation；no-server smoke 產生 structured blocked evidence，不是 baseline runtime pass。
- [x] **Phase 12B-BASE Baseline PlannerAction Mapper Runtime Evidence**: 已在真實 CARLA runtime 執行 5 條 baseline mapper rows；5/5 rows 完成 tick/control/sensor logging，但全部 `route_progress_blocked`。此為負向 runtime evidence，不是 Runtime Pass。
- [x] **Phase 12B-SUM Controller Ablation Comparative Summary**: 已將 GRP、linear、baseline mapper evidence 正規化為 controller / route comparative tables；結論維持 differentiated outcome，不升格為 all-controller pass。
- [x] **Phase 12C Perception Backend Ablation Prepared**: 已建立 5 calibrated routes x 3 perception backend modes 的 scaffold；固定 `grp_follower`，dummy rows 可用，YOLOv9 optional rows 在 source adapter no-fallback verification 通過後已 available / command-ready，RT-DETR optional rows 仍依 dependency 狀態處理。此項不是 full Phase 12C perception ablation runtime pass。
- [x] **Phase 12C-DUMMY Dummy Backend Runtime Confirmation**: 已在真實 CARLA runtime 執行 5 條 calibrated `grp_follower + dummy` rows；5/5 rows reached goal，`collision_count_total=0`，`lane_invasion_count_total=83`。此為 dummy backend smoke confirmation，不是 infraction benchmark。
- [x] **Phase 12C-YOLOv9-U YOLOv9 Optional Dependency Unlock Prepared**: 已針對 CARLA Python 3.12 runtime 產生 YOLOv9 dependency / EdgePerception backend support preflight evidence、manual unlock commands 與 post-unlock verification commands；目前 dependency_missing，但 `edge_yolov9_command_supported=true` 且透過 graceful fallback 通過，未自動安裝，未執行 YOLOv9 runtime confirmation。
- [x] **Phase 12C-YOLOv9-B EdgePerception YOLOv9 Backend Adapter Prepared**: 已新增 `YOLOv9PerceptionBackend` adapter path、`backend="yolov9"` factory branch、CLI `--test yolov9` 與 dedicated adapter evidence；base Python 與 CARLA Python 3.12 均可執行 `EdgePerception --test yolov9`，並在 source/weights 未配置時安全 fallback。此階段不是 YOLOv9 runtime pass。
- [x] **Phase 12C-YOLOv9-V YOLOv9 Post-Unlock Verification Passed**: external_source strict post-unlock verification 已通過；`experiments\phase12\20260630T061015Z` 記錄 `post_unlock_verified=true`、`source_adapter_verified=true`、`edge_yolov9_fallback_used=false`、`edge_yolov9_no_fallback_verified=true`、`phase12c_yolov9_rows_available=true`。不自動安裝、不修改 baseline requirements、不啟動 CARLA、不宣稱 YOLOv9 runtime route pass。
- [x] **Phase 12C-YOLOv9-SRC Official YOLOv9 Source Adapter Prepared**: 已將 YOLOv9 官方路徑改為 external source-root contract，新增 `YOLOV9_ROOT` / `YOLOV9_WEIGHTS` 設定、source entries / weights / no-fallback verification gate 與 source-adapter evidence；source repo 與 weights 仍為外部資產，不提交、不 vendor。
- [x] **Phase 12C-YOLOv9-SRC-V Source Adapter No-Fallback Verification Passed**: 已正式執行 `scripts/run_phase12c_yolov9_source_adapter_verification.py --require-verified`；`experiments\phase12\20260630T060621Z` 記錄 `strict_gate_exit_code=0`、`source_adapter_verified=true`、`edge_yolov9_fallback_used=false`、`edge_yolov9_no_fallback_verified=true`。此為 source adapter no-fallback verification，不宣稱 YOLOv9 CARLA route runtime pass。

```text
source_adapter_verified_evidence_dir=experiments\phase12\20260630T060621Z
yolov9_rows_refresh_dir=experiments\phase12\20260630T060823Z
post_unlock_external_source_verified_dir=experiments\phase12\20260630T061015Z
YOLOV9_ROOT_configured=true
YOLOV9_WEIGHTS_configured=true
yolov9_source_root_ready=true
yolov9_weights_ready=true
source_adapter_verified=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
post_unlock_verified=true
unlock_mode=external_source
phase12c_yolov9_rows_available=true
backend_unavailable_count=0
runtime_confirmation_executed=false
carla_route_runtime_executed=false
auto_install_performed=false
baseline_requirements_modified=false
carla_server_started=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

- [x] **Phase 12C-YOLOv9-R1-DIAG Runtime Timeout Diagnosis Completed**: 已針對 selected `route_01 + grp_follower + yolov9` runtime blocker 增加 bounded diagnostic breadcrumbs；`experiments\phase12\20260630T150500Z` 記錄 `timeout_classification=map_load_or_spawn_stall`、`diagnosis_confidence=high`、`diagnostic_steps_completed=0`、`heartbeat_count=0`、`world_tick_count=0`、`rgb_frame_received_count=0`、`edge_perception_call_count=0`、`yolov9_inference_call_count=0`。此項只完成 timeout diagnosis，不宣稱 YOLOv9 route runtime pass。
- [x] **Phase 12C-YOLOv9-R1-SETUP Setup Recovery Probe Pass**: 已新增 parent wrapper 與 CARLA Python child probe，逐段隔離 `map_load_or_spawn_stall` 的 setup path；`experiments\phase12\20260701T045047Z` 記錄 `setup_probe_passed=true`、`setup_blocker_classification=setup_probe_passed`、`town_ready=true`、`ego_spawned=true`、`rgb_sensor_attached=true`、`first_rgb_frame_received=true`、`grp_route_generated=true`、`warmup_ticks_completed=20`。此項只代表 setup/spawn-stage pass，不宣稱 YOLOv9 runtime pass。
- [x] **Phase 12C-YOLOv9-R1-SHORT Route-Begin Probe Pass**: 已新增 short route-begin parent wrapper，沿用 R1-SETUP evidence 與既有 R1-DIAG -> Phase 12B -> Phase 11M diagnostic path；`experiments\phase12\20260701T064944Z` 記錄 `short_route_begin_verified=true`、`diagnostic_steps_completed=50`、`heartbeat_count=11`、`world_tick_count=50`、`rgb_frame_received_count=50`、`edge_perception_call_count=50`、`yolov9_inference_call_count=11`、`edge_yolov9_fallback_used_during_route=false`、`partial_route_progress_seen=true`。此項只代表 selected row 進入 route loop 並產生早期 no-fallback breadcrumbs，不宣稱 route completion 或 YOLOv9 selected route runtime pass。
- [x] **Phase 12C-YOLOv9-R1-LATENCY Route-Loop Latency Profile Completed**: 已新增 latency/cadence parent wrapper 與 diagnostic-only inference stride/cache flags；`experiments\phase12\20260701T103721Z` 記錄 `latency_probe_completed=true`、`executed_variant_count=2`、`completed_variant_count=1`、`blocked_variant_count=1`、`best_variant_id=variant_01_current_cadence`、`best_variant_effective_fps=0.239313`、`baseline_current_cadence_yolov9_avg_ms=2522.06`、`latency_bottleneck_classification=yolov9_forward_dominant`、`recommended_next_phase=R1-LATENCY-OPT`。此項只代表 latency/cadence profiling，不宣稱 route completion 或 YOLOv9 selected route runtime pass。
- [x] **Phase 12C-YOLOv9-R1-LATENCY-OPT Forward-Latency Optimization No-Improvement**: `experiments\phase12\20260701T115744Z` 記錄 `latency_opt_completed=true`、`useful_latency_improvement_verified=false`、`executed_variant_count=4`、`completed_variant_count=2`、`blocked_variant_count=2`、`best_variant_id=variant_01_baseline_recheck`、`best_variant_effective_fps=0.168392`、`best_variant_yolov9_avg_ms=2194.8`、`best_avg_ms_improvement_pct=12.976`、`best_fps_improvement_pct=-29.635`、`latency_opt_bottleneck_classification=latency_regressed`、`recommended_next_phase=R1-YOLOv9-LIGHTWEIGHT`。此項只代表 latency optimization profiling，不宣稱 route completion、YOLOv9 model accuracy 或 benchmark pass。
- [x] **Phase 12C-YOLOv9-R1-YOLOv9-LIGHTWEIGHT Lightweight Feasibility Blocked**: `experiments\phase12\20260701T165325Z` 記錄 `source_adapter_verified=true`、`edge_yolov9_fallback_used=false`、`edge_yolov9_no_fallback_verified=true`、`latency_opt_completed=true`，但 `lightweight_weights_configured=false`、`lightweight_weights_ready=false`，因此 `status=blocked`、`lightweight_bottleneck_classification=lightweight_weights_missing`、`executed_variant_count=0`、`completed_variant_count=0`、`blocked_variant_count=5`、`recommended_next_phase=R1-RT-DETR-UNLOCK`。此項只建立 lightweight asset contract 與 blocked evidence，不下載、不提交 YOLOv9 assets，不宣稱 route completion、YOLOv9 model accuracy 或 benchmark pass。

### VLM Reasoner
- [x] **VLMReasoner Provider Abstraction**: 定義清楚的 VLM 介面，統一回傳 `VLMOutput`。
- [x] **OpenAI-Compatible VLM Provider**: 支援通用 OpenAI 格式的模型（如 GPT-4V, Gemma 4）。
- [x] **Graceful Fallback**: 若 VLM 未配置 API 金鑰、網路逾時或解析失敗，完美降級至 `LocalStubReasoner` 產出安全預設值。
- [x] **Demo Trigger (`--force-vlm-every`)**: 支援強制週期觸發機制，且不受 Cooldown 阻擋，方便展示。

---

## 🔶 Graceful Fallback Confirmed (尚未經過 Real Backend 全面測試)

雖然框架已具備對接真實後端的能力並能安全降級，但考量到開發者機器環境，以下「真實模型」的效能與準確率**尚未進行大規模硬體驗證**。請勿聲稱其具有真實世界的泛化能力。

- **Real YOLO / RT-DETR Inference**: 目前皆是在缺少依賴的情況下測試其 Fallback 能力，並未以 GPU 實際負載真實路況。
- **Real VLM Endpoint Connection**: 驗證了 API 金鑰缺乏與逾時的 Fallback 防護，端對端的真實 GPT-4V 推論需由終端使用者提供金鑰。
- **Real CLIP / SigLIP Embeddings**: 框架具備調用 `open-clip-torch` 的能力，目前依賴 `DummyEmbeddingBackend` 以保證 Mock 模式無痛執行。
- **Real CARLA Server Runtime**: Phase 11H 已在 dedicated Python 3.12 environment 中完成 CARLA 0.9.16 真實 server runtime smoke。Base Python 3.10 仍保留 no-server/fallback 驗證路徑，不把 `carla` 加入 baseline requirements。
- **CARLA Smoke Evidence Pack**: Phase 11I 已提供 structured metrics 與 event logs。這不是 route benchmark，也不包含 collision/lane invasion sensor 指標。
- **CARLA Sensor Metrics Smoke**: Phase 11J 已驗證 collision/lane sensors 可掛載並寫入 metrics；`collision_count=0` 與 `lane_invasion_count=0` 是 sensor-attached 後的實測 smoke 結果，不是 infraction benchmark。
- **CARLA Fixed Route Progress Smoke**: Phase 11K 已驗證固定 spawn-pair route progress 可寫入 metrics；`route_progress_verified=true` 只代表 smoke 門檻通過，不是 route completion benchmark。
- **CARLA Fixed Route Goal-Reach Smoke**: Phase 11L 已驗證 `distance_to_goal_m <= 3.0` 的 strict fixed spawn-pair gate；`fixed_route_completion_verified=true` 不等同 CARLA Leaderboard 或正式 route benchmark。
- **CARLA GRP Route-Following Smoke**: Phase 11M 已驗證 `GlobalRoutePlanner` route generation 與 runner-only GRP waypoint following；`grp_route_following_verified=true` 與 `fixed_route_completion_verified=true` 仍只代表 fixed spawn-pair smoke gate，不等同 CARLA Leaderboard、正式 route benchmark 或 infraction benchmark。
- **Release Artifact Boundary**: Phase 11N 已產生 release zip 與 checksum；`status_clean=false` 被記錄於 git snapshot，代表這是 workspace artifact snapshot，不是 clean git commit/tag release。
- **Source Commit Boundary**: Phase 11O 已準備 source-only commit boundary 與 Draft PR body；runtime logs、release artifacts、local envs 與 `.env` 仍不得進入 git。遠端 Draft PR、git tag 與 push 需另行執行。
- **Experiment Kickoff Scaffold**: Phase 12 已建立 controlled experiment planning scaffold；`experiments/phase12/*/runs/` 與 `experiments/phase12/*/raw_outputs/` 不得提交，kickoff 不等於正式實驗結果。
- **Route Scaling Experiment**: Phase 12A 已產生 real CARLA 5-route aggregate evidence；`passed_count=4` 與 `route_05 goal_reach_blocked` 只代表 controlled fixed spawn-pair smoke 結果，不等同 CARLA Leaderboard、正式 route benchmark 或 infraction benchmark。
- **Perception Backend Ablation Scaffold**: Phase 12C 只做 backend availability preflight 與 command scaffold；YOLOv9 optional rows 現在 available / command-ready 是因 source adapter no-fallback verification 通過，不代表 full Phase 12C perception ablation runtime pass，也不代表 RT-DETR runtime 已驗證。
- **Dummy Backend Runtime Confirmation**: Phase 12C-DUMMY 已確認 `dummy` backend 可在 fixed calibrated routes 中完成 5/5 goal-reach smoke；lane invasion counts 保留為 sensor metrics，不升格為 infraction benchmark。
- **YOLOv9 Optional Dependency Unlock**: Phase 12C-YOLOv9-U 只準備 YOLOv9 dependency/backend unlock，不修改 baseline requirements，不自動安裝 dependencies，不啟動 CARLA，也不宣稱 YOLOv9 runtime pass。Phase 12C-YOLO-U 是早期 generic YOLO unlock preparation 歷史紀錄。
- **YOLOv9 Backend Adapter**: Phase 12C-YOLOv9-B 只證明 EdgePerception 已註冊 `backend="yolov9"` 與 `--test yolov9` adapter path；SRC-V 另行證明 official external source adapter no-fallback readiness，不代表模型準確率驗證。
- **YOLOv9 Post-Unlock Verification**: Phase 12C-YOLOv9-V 只驗證 operator unlock 之後的 dependency/no-fallback readiness；權威 evidence `experiments\phase12\20260630T061015Z` 記錄 `post_unlock_verified=true`、`edge_yolov9_fallback_used=false`。不代表 YOLOv9 CARLA route runtime pass。
- **YOLOv9 Source Adapter**: Phase 12C-YOLOv9-SRC 只準備官方 YOLOv9 external source adapter 與 no-fallback gate；YOLOv9 source repo 與 weights 必須由 operator 在本機提供，且不得提交到 git。
- **YOLOv9 Source Adapter No-Fallback Verification**: Phase 12C-YOLOv9-SRC-V 是 strict gate evidence；`experiments\phase12\20260630T060621Z` 已驗證 `source_adapter_verified=true`、`edge_yolov9_fallback_used=false`、`edge_yolov9_no_fallback_verified=true`。

---

## ❌ Not Yet Verified / Future Work（尚未驗證/未來規劃）

### ROS2 / Isaac Sim Integration
- `ROS2SimulatorAdapter` 與 `IsaacSimAdapter` 目前為 stub（`NotImplementedError`）。需要真實的 ROS2 Humble 環境與 Isaac Sim 實體連線測試。

### Production Deployment
- Docker / Docker Compose 容器化部署環境設定。
- Frontend (Next.js) 的生產環境部署 (如 Vercel 或 Cloudflare Pages)。
- Supabase 的 Realtime WebSocket 深度訂閱優化。

---

## 📊 驗證覆蓋率摘要

| 類別 | 完成 | 部分 | 未驗證 | 狀態 |
|------|------|------|--------|--------|
| **Python Workers Core** | 100% | — | — | 🟢 Pass |
| **FastAPI Backend** | 100% | — | — | 🟢 Pass |
| **Frontend Build** | 100% | — | — | 🟢 Pass |
| **VLM Fallback / Stub** | 100% | — | — | 🟢 Pass |
| **Real VLM API** | — | 100% | — | 🟡 Fallback Confirmed |
| **Real YOLO / CV** | — | 100% | — | 🟡 Fallback Confirmed |
| **Database Integration**| 100% | — | — | 🟢 Pass |
| **CARLA Fake Runtime** | 100% | — | — | 🟢 Pass |
| **CARLA Real Server** | 100% | — | — | 🟢 Phase 11H Pass |
| **CARLA Runtime Evidence Pack** | 100% | — | — | 🟢 Phase 11I Pass |
| **CARLA Sensor Metrics Smoke** | 100% | — | — | 🟢 Phase 11J Pass |
| **CARLA Fixed Route Progress Smoke** | 100% | — | — | 🟢 Phase 11K Pass |
| **CARLA Fixed Route Goal-Reach Smoke** | 100% | — | — | 🟢 Phase 11L Pass |
| **CARLA GRP Route-Following Smoke** | 100% | — | — | 🟢 Phase 11M Pass |
| **Release Artifact Packaging** | 100% | — | — | 🟢 Phase 11N Pass |
| **Source Commit Boundary** | 100% | — | — | 🟢 Phase 11O Pass |
| **Experiment Kickoff Scaffold** | 100% | — | — | 🟢 Phase 12 Kickoff Pass |
| **CARLA Route Scaling Experiment** | — | 100% | — | 🟡 Phase 12A Evidence Produced |
| **Route 05 Recovery Smoke** | — | 100% | — | 🟡 Phase 12A-R05 Blocked |
| **Route 05 Waypoint Progression Diagnosis** | — | 100% | — | 🟢 Phase 12A-R05B Pass |
| **Route Horizon Calibration** | — | 100% | — | 🟢 Phase 12A-H Pass |
| **Calibrated Route Runtime Confirmation** | — | 100% | — | 🟢 Phase 12A-C Pass |
| **Controller Ablation Scaffold** | — | 100% | — | 🟡 Phase 12B Prepared |
| **Controller Ablation Runtime Wiring** | — | 100% | — | 🟡 Phase 12B-R Prepared |
| **GRP Controller Ablation Runtime** | — | 100% | — | 🟢 Phase 12B-GRP Pass |
| **Linear Controller Route-Progress Runtime** | — | 100% | — | 🟢 Phase 12B-LIN Smoke Pass |
| **Baseline Mapper Route-Metric Wiring** | — | 100% | — | 🟡 Phase 12B-BASE-M Prepared |
| **Baseline Mapper Runtime Evidence** | — | 100% | — | 🟠 Phase 12B-BASE Blocked |
| **Controller Ablation Comparative Summary** | — | 100% | — | 🟡 Phase 12B-SUM Prepared |
| **Perception Backend Ablation Scaffold** | — | 100% | — | 🟡 Phase 12C Prepared |
| **Dummy Backend Runtime Confirmation** | — | 100% | — | 🟢 Phase 12C-DUMMY Pass |
| **YOLOv9 Optional Dependency Unlock** | — | 100% | — | 🟡 Phase 12C-YOLOv9-U Prepared |
| **YOLOv9 Backend Adapter** | — | 100% | — | 🟡 Phase 12C-YOLOv9-B Prepared |
| **YOLOv9 Post-Unlock Verification** | — | 100% | — | 🟢 Phase 12C-YOLOv9-V Pass |
| **YOLOv9 Source Adapter Verification** | — | 100% | — | 🟡 Phase 12C-YOLOv9-SRC Prepared |
| **YOLOv9 Source Adapter No-Fallback Verification** | — | 100% | — | 🟢 Phase 12C-YOLOv9-SRC-V Pass |
| **YOLOv9 Selected Runtime Row** | — | 100% | — | 🟡 Phase 12C-YOLOv9-R1-YOLOv9-LIGHTWEIGHT blocked |
| **生產容器化部署** | 0% | — | 100% | 🔴 TODO |

Phase 12C-YOLOv9-R1-DIAG status note: timeout diagnosis is completed, with `timeout_classification=map_load_or_spawn_stall`; selected YOLOv9 runtime row remains blocked and `yolo_runtime_row_verified=false`.

Phase 12C-YOLOv9-R1-SETUP status note: setup recovery probe passed for the same selected row with `setup_probe_passed=true`; it remains setup-stage evidence only, with `runtime_confirmation_executed=false`, `carla_route_runtime_executed=false`, and `yolo_runtime_row_verified=false`.

Phase 12C-YOLOv9-R1-SHORT status note: short route-begin probe passed for the same selected row with `short_route_begin_verified=true`, `world_tick_count=50`, `rgb_frame_received_count=50`, `edge_perception_call_count=50`, and `yolov9_inference_call_count=11`. It remains route-begin evidence only; `goal_reached=false`, `yolo_runtime_row_verified=false`, `selected_route_completion_verified=false`, and all benchmark boundary fields remain false.

Phase 12C-YOLOv9-R1-LATENCY status note: latency profiling completed for the same selected row with `latency_probe_completed=true`; current cadence is `yolov9_forward_dominant` with `best_variant_effective_fps=0.239313` and average YOLOv9 inference `2522.06ms`. Recommended next phase is `R1-LATENCY-OPT`; route completion, selected runtime pass, model accuracy, and all benchmark claims remain false.

Phase 12C-YOLOv9-R1-LATENCY-OPT status note: optimization profiling completed for the same selected row with `latency_opt_completed=true`, but `useful_latency_improvement_verified=false`. The best bounded variant was `variant_01_baseline_recheck` with average YOLOv9 inference `2194.8ms`, effective FPS `0.168392`, average-latency improvement `12.976%`, and FPS improvement `-29.635%`. Recommended next phase is `R1-YOLOv9-LIGHTWEIGHT`; route completion, selected runtime pass, model accuracy, and all benchmark claims remain false.

Phase 12C-YOLOv9-R1-YOLOv9-LIGHTWEIGHT status note: lightweight feasibility probe is blocked locally because `YOLOV9_LIGHTWEIGHT_WEIGHTS` is not configured. Baseline no-fallback readiness remains true, but no lightweight variant executed and `useful_lightweight_profile_verified=false`. Recommended next phase is `R1-RT-DETR-UNLOCK`; route completion, selected runtime pass, model accuracy, and all benchmark claims remain false.

## 🚧 Explicitly Not Verified

- [ ] CARLA formal route benchmark verified
- [ ] CARLA infraction benchmark verified
- [ ] CARLA Leaderboard passed
- [x] Source-only local commit boundary prepared
- [ ] Remote Draft PR opened
- [ ] Clean git tag release created
- [ ] Real YOLO / RT-DETR verified
- [ ] Real YOLOv9 runtime inference verified
- [ ] Real OpenAI-compatible VLM verified

> **總結**：目前專案處於 **v0.3.1 (Release Candidate)**，非常適合用於作品集展示與架構概念性驗證 (PoC)。核心的決策管線 (Pipeline)、防呆降級 (Graceful Fallback) 與資料流串接已全數打通。

# MA-VLNA — Memory-Augmented Vision-Language Navigation Agent
## Final Technical Report

### 1. 專案概述 (Project Overview)
MA-VLNA (Memory-Augmented Vision-Language Navigation Agent) 是一個結合邊緣端感知 (Edge Perception)、場景記憶 (Scene Memory)、與大型視覺語言模型 (Vision-Language Model, VLM) 的高階自動駕駛代理系統。
本專案的設計理念在於解決傳統自駕系統在面對「未見過 (Out-of-Distribution)」或「長尾 (Long-tail)」罕見場景時的推理能力瓶頸。透過引入 VLM 作為高階推理大腦，並搭配快速的本地邊緣感知與安全守門員機制，MA-VLNA 達成了一個能在邊緣設備上快速反應，並在遇到複雜場景時自動呼叫雲端 VLM 進行深度推理的混合式架構。

### 2. 系統架構 (System Architecture)
MA-VLNA 採用模組化的軟體架構，主要包含以下核心元件：
* **Camera Adapter**：負責從攝影機或模擬影片串流中獲取影像幀。
* **Edge Perception**：輕量化邊緣端感知模組，支援 YOLO、RT-DETR 或 Dummy 模擬後端，快速找出畫面中的物件與潛在危險區域。最新版本已整合 `roboflow/supervision`，提供專業級的物件追蹤 (ByteTrack) 與區域風險評估 (Zone-aware risk assessment)。
* **Scene Memory & Embedding Backend**：利用 CLIP (Contrastive Language-Image Pretraining) 將場景特徵提取為高維度向量，並透過 Supabase 的 `pgvector` 功能進行即時的餘弦相似度比對，尋找歷史相似場景。
* **Trigger Policy**：動態決策引擎，根據 Edge Perception 發現的風險（如行人靠近）、場景熟悉度（相似度過低）、或定期強制觸發等條件，決定是否需要呼叫 VLM 進行高階推理。
* **VLM Reasoner**：系統的「大腦」，負責接收影像與周遭文本脈絡，輸出詳細的場景描述、潛在風險分析與推薦的導航航點 (Waypoints)。系統實作了 Provider Abstraction，支援本地端模擬器 (`LocalStubReasoner`) 與 OpenAI-compatible API 後端。
* **Safety Gate**：最終的安全防線，負責檢驗 VLM 輸出的決策是否違反硬性安全規則（如速度上限、危險區域迴避），確保自駕代理的行為安全可控。
* **Telemetry Publisher**：遠端遙測模組，透過非同步機制將系統狀態、場景記憶與 VLM 決策紀錄上傳至 Supabase 進行後續分析與 Dashboard 視覺化。

### 3. 開發歷程與重要里程碑 (Development Milestones)
* **Phase 1-4: 基礎設施與後端建立**
  - 完成 FastAPI 後端與 Supabase 整合。
  - 實作 CLIP 向量特徵提取與 `pgvector` 相似度搜尋。
* **Phase 5-6: 核心控制循環與 Mock 模式**
  - 建立 12-Step 控制循環的 `Autonomous_Driving_Agent`。
  - 實作基於本地測試的 Mock 模式與 Local Stub，使開發不依賴真實硬體與昂貴 API。
* **Phase 7: 安全機制與 Telemetry**
  - 實作 `SafetyGate` 保證輸出的導航點與速度合乎安全規範。
  - 透過 `TelemetryPublisher` 進行狀態遙測並實作 Replay Dashboard 支援。
* **Phase 8-9: VLM Provider 抽象化與 Release Packaging**
  - 抽離 VLM 邏輯，實作 OpenAI Compatible API 與 Graceful Fallback。
  - 移除原始碼中的 `.env` 與 API Keys，完成 v0.5 發布打包，並加入自動化檢查腳本 `run_demo_checks.py`。
* **Phase 10: Supervision 專業感知擴充**
  - 導入 `roboflow/supervision`，實現 ByteTrack 物件追蹤與自定義感知區域判定。
  - 作為 Optional Dependency，保證在未安裝狀態下的無縫降級 (Graceful Fallback)。
* **Phase 11: CARLA Closed-Loop Integration**
  - 新增 CARLA optional adapter，支援 CARLA server/client 連線、ego vehicle spawn、RGB camera sensor、同步 `world.tick()`、以及 `PlannerAction` 到 `VehicleControl` 的橋接。
  - 新增 `CARLA_Closed_Loop_Agent`，沿用既有 `EdgePerception`、`TriggerPolicy`、`VLMReasoner`、`SafetyGate`、`SemanticPlanner` 與 `TelemetryPublisher`，將 MA-VLNA 從 mock/camera demo 推進到 closed-loop simulation prototype。
  - 新增 Phase 11 Core Runtime Verification，以 fake CARLA runtime 跑通 `RGB frame -> EdgePerception -> TriggerPolicy -> Planner/SafetyGate -> VehicleControl adapter -> telemetry fallback` 的閉環編排，不需要真實 CARLA server 即可驗證核心路徑。
  - 新增 Phase 11B Real CARLA Server Runtime Smoke Test，將真實 CARLA server 驗收拆成獨立 gate，支援 preflight、skipped 與 `--require-server` 強制驗收模式。
  - 新增 Phase 11D/11E/11F/11G provisioning 與 unlock 文件鏈路；Phase 11G 已將 CARLA 0.9.16 下載並解壓至 D 槽，但 package wheel 需要 CPython 3.12，因而在 base Python 3.10.14 環境停止於 wheel ABI blocker。
  - 新增 Phase 11H Python 3.12 CARLA Runtime Environment，建立 `D:\CARLA\envs\ma-vlna-carla312`，安裝 CARLA 0.9.16 `cp312` wheel，啟動真實 CARLA server，並通過 Phase 11D `--require-ready`、Phase 11C 5-step 與 50-step `--require-server` smoke。
  - 新增 Phase 11I CARLA Runtime Evidence Pack，將 Phase 11H 的真實 runtime pass 轉換為可保存、可重跑、可審核的 `manifest.json`、`metrics.json`、`events.jsonl`、`commands.txt`、`environment.txt` 與 `regression.txt`。此 evidence pack 僅證明 5/50-step smoke，不宣稱 route completion、infraction metrics 或 CARLA Leaderboard。
  - 新增 Phase 11J CARLA Sensor Metrics & Infraction Instrumentation，在真實 CARLA smoke 中掛載 collision 與 lane invasion sensors，並從 CARLA vehicle state 量測速度與位移距離。此階段證明 sensor metrics instrumentation 可用，但仍不宣稱 route completion、infraction benchmark 或 CARLA Leaderboard。
  - 新增 Phase 11K Fixed Route Scenario Smoke & Route Progress Metrics，以 `Town03` spawn pair 建立固定 route smoke，量測 `route_progress_m`、`route_progress_pct`、`route_remaining_m` 與 `distance_to_goal_m`。此階段只證明 route progress instrumentation 可用，仍不宣稱 route completion benchmark 或 CARLA Leaderboard。
  - 新增 Phase 11L Fixed Route Completion Attempt & Goal-Reach Gate，在相同 `Town03` spawn pair 上執行 2500-step strict goal-reach gate，於 `distance_to_goal_m=2.906011` 時通過固定路線 smoke completion。此結果仍限於 fixed spawn-pair smoke，不等同 CARLA Leaderboard、infraction benchmark 或正式 route benchmark。
  - 新增 Phase 11M GRP-backed Route Following & Benchmark Boundary Preparation，在相同 `Town03` spawn pair 上要求 CARLA `GlobalRoutePlanner` route generation 與 runner-only GRP waypoint following，於 `goal_reach_step=2073`、`distance_to_goal_m=2.283447` 通過 strict goal-reach gate。此階段新增 structured benchmark boundary evidence，但仍不宣稱 CARLA Leaderboard、infraction benchmark 或正式 route benchmark。
  - 新增 Phase 11N Git Snapshot, Artifact Boundary & Release Packaging，將 Phase 11M evidence、source/docs、artifact boundary、git snapshot 與 checksums 打包為 timestamped release zip。此階段是 workspace release artifact snapshot，不等同 clean git commit/tag release，也不宣稱 CARLA Leaderboard 或正式 benchmark。
  - 新增 Phase 11O Source Commit Boundary & Draft PR Preparation，將 11N 的 artifact snapshot 轉成 source-only commit boundary，加入 staged-file gate 與 Draft PR handoff body。此階段只處理 source review hygiene，不建立 git tag、不 push、不宣稱 formal benchmark。
  - 新增 Phase 12 Experiment Kickoff Preparation，從 Phase 11 的 CARLA runtime verification 與 evidence-pack foundation 進入受控實驗規劃，定義 route scaling、controller ablation、perception backend ablation、VLM trigger comparison 與 evidence aggregation scaffold。此階段不啟動 CARLA、不執行大型實驗、不宣稱 Leaderboard 或 benchmark。
  - 新增 Phase 12A CARLA Route Scaling Experiment，將 Phase 11M 的單一路線 GRP smoke runner 擴展成固定 5 組 `Town03` spawn-pair 的 batch orchestrator，支援 dry-run、continue-all policy 與 `summary.csv` / `summary.json` 聚合。真實 runtime 已產生 5-route aggregate evidence，其中 4 條路線通過 strict goal-reach gate，`route_05` 因 goal-reach failure 保持 blocked。此階段仍只代表 controlled route smoke，不等同 CARLA Leaderboard、正式 route benchmark 或 infraction benchmark。
  - 新增 Phase 12A-R05 Route 05 Failure Diagnosis & Recovery Experiment，針對 `route_05` 的 traffic-light collision/stuck failure 建立專用 recovery-variant runner。此 runner 不修改 GRP controller，只調整 speed、route sampling 與 lookahead 參數來產生可比較 evidence。真實 runtime 已執行 4 個 conservative recovery variants，其中 `r05_slow_short_lookahead` 將 route progress 提升至 71.07% 並消除碰撞，但未達 strict goal tolerance，因此 R05 recovery gate 仍保持 blocked。
  - 新增 Phase 12A-R05B Late-route Waypoint Progression Diagnosis，針對 `r05_slow_short_lookahead` 解析最後 200 步 waypoint progression，確認 2500-step run 末段仍持續推進而非 waypoint index stall。5200-step extended diagnostic 在 step 4431 達成 goal tolerance，證明該失敗主要是原 smoke horizon 不足；此結果不回溯改寫 Phase 12A all-route gate。
  - 新增 Phase 12A-H Horizon Calibration Experiment，將 Phase 12A 與 R05B 的 real CARLA evidence 轉成 per-route step horizon matrix：`route_01=2500`、`route_02=2800`、`route_03=2500`、`route_04=2500`、`route_05=5400`。此階段只校準 smoke horizon，不宣稱 formal route benchmark。
  - 新增 Phase 12A-C Calibrated 5-Route Runtime Confirmation，將 Phase 12A-H 的 calibrated horizon matrix 回灌到五條 `Town03` route 並實際重跑 CARLA runtime。五條 route 均達成 fixed goal tolerance，且 collision_count 全為 0；此結果確認 calibrated smoke setup，但不等同 CARLA Leaderboard 或正式 benchmark。
  - 新增 Phase 12B Controller Ablation Scaffold，建立 5 條 calibrated `Town03` routes x 3 種 controller mode 的 15-row dry-run matrix，輸出 `manifest.json`、`summary.csv`、`summary.json`、`commands.txt` 與 `README.md`。此階段只準備 ablation command scaffold，不執行大型 CARLA runtime，也不宣稱 Runtime Pass。
  - 新增 Phase 12B-R Controller Ablation Runtime Wiring，為同一個 runner 加入顯式 `--execute-runtime` path，能逐 row 啟動既有 child runner、保存 raw stdout/stderr、讀取 child evidence metrics 並聚合 blocked/pass/fail counts。本機 wiring smoke 在沒有 CARLA server 時產生 blocked evidence；此結果只證明 runtime wiring 與 evidence handling，不等同 Runtime Pass。
  - 新增 Phase 12B-GRP GRP Controller Ablation Runtime Pass，使用 Phase 12B-R 的 `--execute-runtime` path 只執行 `grp_follower` controller rows。五條 calibrated `Town03` routes 均達成 goal tolerance，且各 route `collision_count=0`；此結果只代表 GRP controller ablation subset runtime pass，不代表 linear / baseline mapper controller pass，也不等同 CARLA Leaderboard 或正式 benchmark。
  - 新增 Phase 12B-LIN Linear Spawn-Pair Controller Runtime Pass / Blocked Evidence，使用同一 runtime wiring 執行 `linear_spawn_pair_follower` controller rows。初次 batch 保留 `route_01` CARLA map-load timeout blocked evidence；warm-up 後完整 5-row rerun 通過 route-progress smoke gate，但 route 02-05 collision_count 很高且未達 goal，因此只代表 linear route-progress smoke pass，不代表安全完成或 infraction benchmark。
  - 新增 Phase 12B-BASE-M Baseline PlannerAction Mapper Route-Metric Wiring，為 `baseline_planner_action_mapper` controller rows 加入 dedicated child runner，沿用既有 `PlannerActionToCarlaControl` mapper 並輸出 fixed spawn-pair route metrics。已完成 no-server blocked wiring smoke，證明 parent 可讀取 child `metrics.json` 與 boundary fields；此階段不代表 baseline mapper runtime pass。
  - 新增 Phase 12B-BASE Baseline PlannerAction Mapper Runtime Evidence，使用真實 CARLA runtime 執行 5 條 calibrated baseline mapper rows。所有 rows 都完成 ego spawn、RGB frame、world tick、PlannerAction control 與 sensor logging，但 route_progress_m 皆為 0，因此 5/5 rows 正確標記為 `route_progress_blocked`；此為 baseline mapper 的負向 runtime evidence，不是 Runtime Pass。
  - 新增 Phase 12B-SUM Controller Ablation Comparative Summary，將 GRP、linear、baseline mapper 三條 evidence line 正規化為 controller-level 與 route-level comparative tables。結論是 GRP 為唯一 5/5 goal-reach smoke controller，linear 僅為 route-progress smoke 且 collision_count 高，baseline mapper 可執行 closed-loop control 但 5/5 route-progress blocked。
  - 新增 Phase 12C Perception Backend Ablation Prepared，固定 Phase 12B-SUM 選出的 `grp_follower` controller，建立 5 條 calibrated routes x `dummy` / YOLOv9 optional / RT-DETR optional 的 perception backend scaffold。此階段只做 target CARLA Python backend preflight 與 runtime command wiring；YOLOv9 optional rows 在 official source adapter no-fallback verification 通過後已 available / command-ready，RT-DETR optional rows 仍依 dependency 狀態處理。此階段不宣稱 full Phase 12C perception ablation runtime pass。
  - 新增 Phase 12C-DUMMY Dummy Perception Backend Runtime Confirmation，使用 dedicated Python 3.12 + CARLA 0.9.16 runtime 執行 5 條 calibrated `grp_follower + dummy` rows，五條 route 均達成 goal tolerance，`collision_count_total=0`，並保留 `lane_invasion_count_total=83` 作為 sensor metric record。此階段只確認 dummy backend runtime path，不等同 infraction benchmark 或 CARLA Leaderboard。
  - 新增 Phase 12C-YOLOv9-U YOLOv9 Optional Dependency Unlock Prepared，將早期 generic Phase 12C-YOLO-U 修訂為 YOLOv9-specific target；針對 dedicated CARLA Python 3.12 runtime 檢查 YOLOv9 import、pip metadata 與 `EdgePerception --test yolov9` 支援性，確認目前 dependency_missing，但 adapter command 已支援且會 graceful fallback，並產生 operator-driven manual unlock commands 與 post-unlock verification commands。此階段不自動安裝、不修改 baseline requirements、不啟動 CARLA，也不宣稱 YOLOv9 runtime pass。
  - 新增 Phase 12C-YOLOv9-B EdgePerception YOLOv9 Backend Adapter Prepared，為 `workers.core.edge_perception` 加入 `YOLOv9PerceptionBackend`、`backend="yolov9"` factory branch 與 CLI `--test yolov9`。base Python 與 CARLA Python 3.12 均已通過 adapter smoke；在 YOLOv9 source/weights 未配置時結果仍使用 fallback，僅代表 adapter path prepared，不代表 YOLOv9 runtime inference pass。
  - 新增 Phase 12C-YOLOv9-V YOLOv9 Post-Unlock Verification，建立 strict verifier 檢查 CARLA Python 3.12 import/package mode、external source mode、EdgePerception no-fallback、Phase 12B/11M/11K/baseline mapper `yolov9` CLI wiring 與 Phase 12C rows refresh。目前權威 evidence `experiments\phase12\20260630T061015Z` 顯示 external_source mode 已通過：`post_unlock_verified=true`、`source_adapter_verified=true`、`edge_yolov9_fallback_used=false`、`phase12c_yolov9_rows_available=true`；此為 no-fallback readiness，不自動安裝套件、不啟動 CARLA，也不宣稱 YOLOv9 route runtime pass。
  - 新增 Phase 12C-YOLOv9-SRC Official YOLOv9 Source Adapter Prepared，將 YOLOv9 正式路徑改為 operator 提供 `YOLOV9_ROOT` 與 `YOLOV9_WEIGHTS` 的外部官方 source repository 合約；`workers.core.edge_perception` 會檢查 source entries、weights 與 no-fallback smoke，`scripts/run_phase12c_yolov9_source_adapter_verification.py` 會輸出 structured evidence。YOLOv9 source repo 與 weights 維持外部資產，不提交、不 vendor、不修改 baseline requirements。
  - 新增 Phase 12C-YOLOv9-SRC-V Source Adapter No-Fallback Verification，正式以 `--require-verified` 執行 source adapter strict gate。`experiments\phase12\20260630T060621Z` 顯示 `strict_gate_exit_code=0`、`source_adapter_verified=true`、`edge_yolov9_fallback_used=false`、`edge_yolov9_no_fallback_verified=true`；YOLOv9-only rows refresh `experiments\phase12\20260630T060823Z` 顯示 `backend_unavailable_count=0`。此為 source adapter no-fallback verification，不代表 YOLOv9 CARLA route runtime pass、模型準確率、Leaderboard、formal route benchmark 或 infraction benchmark。
  - Phase 12C-YOLOv9-SRC-V structured snapshot：`source_adapter_verified_evidence_dir=experiments\phase12\20260630T060621Z`、`yolov9_rows_refresh_dir=experiments\phase12\20260630T060823Z`、`post_unlock_external_source_verified_dir=experiments\phase12\20260630T061015Z`、`YOLOV9_ROOT_configured=true`、`YOLOV9_WEIGHTS_configured=true`、`yolov9_source_root_ready=true`、`yolov9_weights_ready=true`、`source_adapter_verified=true`、`edge_yolov9_command_passed=true`、`edge_yolov9_fallback_used=false`、`edge_yolov9_no_fallback_verified=true`、`post_unlock_verified=true`、`unlock_mode=external_source`、`phase12c_yolov9_rows_available=true`、`backend_unavailable_count=0`、`runtime_confirmation_executed=false`、`carla_route_runtime_executed=false`、`auto_install_performed=false`、`baseline_requirements_modified=false`、`carla_server_started=false`。
  - 新增 Phase 12C-YOLOv9-R1 Selected YOLOv9 Runtime Confirmation，將 YOLOv9 no-fallback readiness 後的第一個 selected runtime row 固定為 `route_01 + grp_follower + yolov9`。R1-RERUN 正式 evidence `experiments\phase12\20260630T134322Z` 顯示 `source_adapter_verified=true`、`edge_yolov9_fallback_used=false`、`edge_yolov9_no_fallback_verified=true`、`carla_server_reachable=true`、`runtime_confirmation_executed=true`、`carla_route_runtime_executed=true`，但 selected row 的 child runtime 在 `2400.311s` timeout，未產生 route metrics 或 goal-reach evidence。此為 blocked runtime attempt，不代表 full Phase 12C perception ablation runtime pass、YOLOv9 accuracy、RT-DETR runtime、Leaderboard、formal route benchmark 或 infraction benchmark。
  - Phase 11 首版不追求 CARLA Leaderboard，而是先建立可觀測、可回放、可安全退場的仿真閉環。

  - 新增 Phase 12C-YOLOv9-R1-DIAG Selected YOLOv9 Runtime Timeout Diagnosis，針對 `route_01 + grp_follower + yolov9` 的 R1-RERUN timeout 加入 bounded diagnostic breadcrumbs。正式 evidence `experiments\phase12\20260630T150500Z` 顯示 `timeout_classification=map_load_or_spawn_stall`、`diagnosis_confidence=high`、`diagnostic_steps_completed=0`、`heartbeat_count=0`、`world_tick_count=0`、`rgb_frame_received_count=0`、`edge_perception_call_count=0`、`yolov9_inference_call_count=0`。YOLOv9 source adapter no-fallback readiness 仍成立，但此診斷不宣稱 YOLOv9 route runtime pass、full Phase 12C perception ablation runtime pass、YOLOv9 accuracy、Leaderboard、formal route benchmark 或 infraction benchmark。
  - 新增 Phase 12C-YOLOv9-R1-SETUP CARLA Setup / Spawn-Stage Recovery Probe，針對 R1-DIAG 的 `map_load_or_spawn_stall` 結論建立 parent wrapper 與 CARLA Python child probe，逐段檢查 client connect、world available、Town03 load/reuse、settings、spawn points、ego spawn、RGB sensor attach、first RGB frame、GRP route generation、warm-up ticks 與 cleanup。正式 evidence `experiments\phase12\20260701T045047Z` 顯示 `setup_probe_passed=true`、`setup_blocker_classification=setup_probe_passed`、`town_ready=true`、`ego_spawned=true`、`rgb_sensor_attached=true`、`first_rgb_frame_received=true`、`grp_route_generated=true`、`warmup_ticks_completed=20`。此階段只隔離 setup/spawn-stage，不宣稱 YOLOv9 selected route runtime pass、YOLOv9 accuracy、full Phase 12C ablation、Leaderboard、formal route benchmark 或 infraction benchmark。
  - 新增 Phase 12C-YOLOv9-R1-SHORT Selected YOLOv9 Route-Begin Probe，沿用同一 selected row 與 R1-SETUP evidence，透過 CARLA Python 3.12 執行 bounded 50-step route-begin diagnostic。正式 evidence `experiments\phase12\20260701T064944Z` 顯示 `short_route_begin_verified=true`、`diagnostic_steps_completed=50`、`heartbeat_count=11`、`world_tick_count=50`、`rgb_frame_received_count=50`、`edge_perception_call_count=50`、`yolov9_inference_call_count=11`、`edge_yolov9_fallback_used_during_route=false`、`partial_route_progress_seen=true`。YOLOv9 timing summary 為 `min=1453.0ms`、`avg=2633.0ms`、`p95=5062.0ms`、`max=6811.0ms`。此階段只證明 selected row 已進入 closed-loop route loop 並產生早期 no-fallback breadcrumbs，不宣稱 route completion、YOLOv9 selected route runtime pass、YOLOv9 accuracy、full Phase 12C ablation、Leaderboard、formal route benchmark 或 infraction benchmark。
### 4. 關鍵技術亮點 (Technical Highlights)
1. **Graceful Degradation (優雅降級)**
   不論是 VLM 網路連線失敗、Edge Model 依賴未安裝 (YOLO/RT-DETR)、Supervision 未啟用，或 CARLA server 尚未接上，系統皆能自動降級至基礎的 Local Stub、Dummy Backend 或 fake runtime verification path，確保程式不會輕易崩潰。
2. **Memory-Augmented Reasoning (記憶增強推理)**
   VLM 不是孤立地進行判斷，而是透過 Scene Memory 提供過去相似場景的解決方案作為 Context，降低 VLM Hallucination (幻覺) 機率並提高決策一致性。
3. **Safety-Critical Design (安全關鍵設計)**
   採用 VLM-Planner-SafetyGate 三層架構。VLM 僅給出「建議航點 (Waypoints)」，最終由 Rule-based 的 Safety Gate 進行把關，兼顧了 AI 的泛化能力與傳統控制的安全性。
4. **Cloud-Edge Hybrid (雲邊緣混合計算)**
   常規場景透過邊緣設備輕量級模型以高 FPS 運行；複雜與長尾場景則由 Trigger Policy 觸發雲端大型 VLM。有效平衡了系統的即時性與運算成本。

### 5. 未來展望 (Future Work)
MA-VLNA v0.5 已證明了其軟體工程架構的穩定性。未來的開發方向可包含：
* **Hardware-in-the-Loop (HIL) 整合**：在 Phase 11 CARLA closed-loop 原型之上，進一步橋接 ROS2 網路與真實機器人底盤。
* **Multi-Modal Memory**：結合光達 (LiDAR) 或毫米波雷達資料，建構更豐富的 3D 場景記憶。
* **Active Learning (主動學習)**：收集 Safety Gate 拒絕 VLM 決策的 Edge Cases，形成自動化的 Data Flywheel，用於未來微調 (Fine-tuning) 自有的 Local VLM。

### 結論 (Conclusion)
MA-VLNA 專案成功展示了將大語言模型強大的邏輯推理能力整合進即時自動駕駛控制流中的潛力。透過嚴謹的軟體工程實踐與模組化設計，我們建構了一個具備高擴充性、高安全性，且容易展示與測試的系統框架。

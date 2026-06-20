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
  - Phase 11 首版不追求 CARLA Leaderboard，而是先建立可觀測、可回放、可安全退場的仿真閉環。

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

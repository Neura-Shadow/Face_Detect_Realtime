# Release Notes - MA-VLNA v0.5.0

**發佈日期**: 2026-06-10  
**發佈版本**: v0.5.0 (Release Candidate)

MA-VLNA v0.5 標誌著本系統架構的成熟。在此版本中，我們成功地將原先基於 Firebase 與 OpenCV 的單體式人臉辨識腳本，徹底重構為一套現代化、模組化且具備高度防禦性的**具身智能認知系統**。

## 🌟 核心新功能與亮點 (Highlights)

### 1. 雙軌感知與優雅降級 (Edge Perception Abstraction)
- **統一感知介面**：實作了全新的 `EdgePerception` 模組，統一所有電腦視覺模型的輸出 Schema (`PerceptionResult`)。
- **動態後端載入**：支援動態掛載 `ultralytics` 提供的 YOLOv8 與 RT-DETR 等強大物件偵測模型。
- **Graceful Fallback**：若開發環境中缺乏 GPU 資源、`ultralytics` 套件，或網路無法下載權重，系統將無縫降級至預設的 `DummyPerceptionBackend`，確保主流程 100% 不崩潰。

### 2. VLM 認知顧問化 (VLM Reasoner Fallback)
- **OpenAI-Compatible 支援**：整合了通用的 LLM/VLM 介面，能無痛對接 GPT-4V、Claude 3 或本地部屬的 Gemma 4。
- **防呆與自動接管**：具備強健的防呆機制。如果未提供有效的 `VLM_API_KEY` 或遭遇連線逾時，系統會自動切換至 `LocalStubReasoner` 接管認知任務，維持車輛與代理的基礎運行。
- **強制展示觸發**：新增 `--force-vlm-every` CLI 引數，解決 VLM 呼叫過於稀疏不易展示的難題，且能夠繞過內建的 Cooldown 限制，完美適用於 Demo 錄製。

### 3. 三層安全仲裁網 (Tri-layer SafetyGate)
為確保 VLM 的幻覺 (Hallucination) 受到控制，v0.5 正式確立了三層安全防禦網：
1. **SafetyGate**：於 VLM 提案後立即進行「最低信心分數」、「限速閾值」與「禁止動作」審核。任何違規將被強制拒絕。
2. **SemanticPlanner**：確保被放行的 Waypoints 符合幾何路徑與避障邏輯。
3. **SimulatorAdapter**：在執行層遇到無法預期的阻礙時，觸發 `emergency_stop`。

### 4. 自動化發佈驗證 (Release Verification Suite)
- 加入了 `scripts/run_demo_checks.py`。
- 一鍵驗證所有核心模組語法、LocalStub 退回機制、OpenAI-Compatible 降級機制，以及長達 30 步迴圈的壓力測試，保證 Release 版本的品質。

## 🔒 安全性更新 (Security)
- **API Key 保護**：徹底稽核並移除了專案中殘留的寫死金鑰。現在所有的 API Key 皆需透過 `.env` 注入，且 `.env` 已被完全屏除在 Git 追蹤之外。
- **Placeholder 範例**：提供安全的 `config/.env.example` 供開發者參考。

## ⚠️ 已知限制與未來展望 (Known Limitations)
- 目前的「真實 VLM」與「真實 YOLO」僅通過「Graceful Fallback」驗證，系統尚未在搭載實體 GPU 與硬體的真實自駕場域中進行大規模負載測試。
- ROS2 與 Isaac Sim 的 Adapter 目前仍為 Stub 狀態，這將是 v1.0 版本的重點開發項目。
- Post-v0.5 Phase 11 已開始 CARLA closed-loop simulation prototype，新增 optional CARLA adapter、closed-loop runner、無 CARLA server 的 smoke checks、fake CARLA core runtime verification、real CARLA runtime evidence pack、sensor metrics、fixed route progress、goal-reach smoke、GRP route-following smoke、release artifact packaging 與 source-only commit boundary；此功能仍屬 prototype，不列入 v0.5 release guarantee，也不宣稱 CARLA Leaderboard 或正式 benchmark。

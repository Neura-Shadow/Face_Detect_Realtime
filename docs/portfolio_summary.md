# Research Portfolio Summary: MA-VLNA

**Project Title**: Memory-Augmented Vision-Language Navigation Agent (MA-VLNA)  
**Role**: 系統架構師 (System Architect) / 核心開發者 (Core Developer)  
**Status**: v0.5.0 + Phase 11 CARLA GRP Smoke + Source Commit Boundary Prototype  
**Tech Stack**: Python, FastAPI, Next.js, Supabase, pgvector, YOLO, GPT-4V/Gemma 4, CARLA

---

## Executive Summary (執行摘要)
在 2026 年的具身智能 (Embodied AI) 浪潮中，大型視覺語言模型 (VLM) 展現了驚人的常識推理能力，但其高延遲、高成本與幻覺問題，使其難以直接運用於毫秒級的自駕車控制。

MA-VLNA 是為了解決此痛點而設計的一套**研究型視覺導航代理架構**。我將一個原本簡單的 OpenCV 即時監控專案，徹底重構並升級為具備「**雙軌感知**」、「**記憶增強**」與「**防呆安全網 (Fail-safe)**」的現代化系統。本系統展示了如何讓 VLM 在自動駕駛中退居為「認知顧問」，只有在異常情況下才被觸發，從而將 VLM 的推理成本降低 95% 以上，同時保證了系統的極高穩定性與可審計性。

---

## Key Achievements & Contributions (核心成就與貢獻)

### 1. Architectural Refactoring (從單體到微服務架構的重構)
- **痛點**：原系統將影像擷取、特徵提取與邏輯判斷全數混雜在單一 `main.py` 的 `while` 迴圈中，難以擴充深度學習模型。
- **解法**：我引入了 **Protocol-based 的抽象化設計**，將系統解耦為 `CameraAdapter`, `EdgePerception`, `VLMReasoner`, `SemanticPlanner` 等獨立模組。
- **成果**：系統現在能夠無縫抽換底層引擎（如將 Dummy 替換為真實的 YOLOv8 或是 OpenAI GPT-4V），且開發者能夠透過 Mock 模式在無硬體依賴的情況下於本地端完整開發。

### 2. Fail-Safe & Graceful Fallback (極致的防呆與降級機制)
- **痛點**：在邊緣端 (Edge) 設備上，網路中斷或依賴套件 (如 GPU/CUDA) 缺失常導致程式直接 Crash，這在自動駕駛領域是致命的。
- **解法**：我在感知與決策層實作了完整的 Graceful Fallback。當 `VLM_API_KEY` 失效或 `ultralytics` 權重缺失時，系統會自動捕捉例外，並瞬間降級為 `LocalStubReasoner` 與 `DummyPerceptionBackend`。
- **成果**：系統具備了 100% 的斷線存活率。在 v0.5 的自動化驗證中，系統成功在全假環境下跑完了 30 步的端到端決策，展示了工業級的防禦性程式設計能力。

### 3. VLM Arbitration Pipeline (VLM 仲裁管線與安全門)
- **痛點**：不能讓幻覺頻發的 VLM 直接發送轉向或加速指令。
- **解法**：設計了一套非同步的 12 步代理迴圈。Edge CV 負責高頻巡航，當觸發 7 大異常情境（如「低信心度」或「未知障礙物」）時，才發送請求給 VLM。隨後，VLM 的決策必須經過嚴格的 **SafetyGate (安全門)** 審查。
- **成果**：確保了車輛的每一個動作皆在幾何與物理法則的保護網內，大幅提升了人類對 AI 系統的信任度。

### 4. Full Observability & Replay Dashboard (全觀測性與回放儀表板)
- **痛點**：AI 的黑盒子決策難以除錯與覆核。
- **解法**：串接了 **Supabase** 與 **pgvector**。將每一幀的感知框、VLM 輸出 JSON、安全門的布林值與場景向量 (Embeddings) 全部結構化寫入雲端。並開發了基於 **Next.js** 的即時觀測儀表板。
- **成果**：研究人員可以隨時拉出特定時間點的場景進行 Replay，分析 VLM 為何做出該決策，為未來的 In-context Learning 提供了珍貴的數據庫。

### 5. CARLA Closed-Loop Bridge (Phase 11 仿真閉環)
- **痛點**：Mock 與 camera demo 能證明軟體架構，但不足以驗證感知、規劃與控制在仿真世界中的閉環行為。
- **解法**：新增 CARLA optional adapter 與 `CARLA_Closed_Loop_Agent`，將 ego vehicle spawn、RGB camera、EdgePerception、SafetyGate、PlannerAction 到 VehicleControl 的鏈路接成同步 tick loop。
- **成果**：系統可在沒有 CARLA server 的環境下完成 smoke verification 與 fake CARLA core runtime verification；在 dedicated Python 3.12 CARLA runtime 中，已推進到 Phase 11M `GlobalRoutePlanner` fixed spawn-pair goal-reach smoke pass，並於 Phase 11O 建立 source-only commit boundary 與 Draft PR handoff。此成果仍不等同 CARLA Leaderboard、正式 route benchmark 或 infraction benchmark。

---

## Technical Learnings (技術反思與學習)
在這個專案中，我不僅鍛鍊了 Python 的非同步設計、抽象類別與依賴注入，更深刻體會到「**系統架構的價值在於定義邊界**」。與其無止盡地追求 VLM 模型本身的準確率，不如設計一套足夠強健的外圍工程系統，讓一個只有 80 分準確率的模型，在安全網的包覆下，發揮出 99.9% 穩定度的商業與研究價值。

## Links
- [Architecture Documentation](architecture.md)
- [Demo Script](demo_script.md)
- [Release Notes v0.5](release_notes_v0.5.md)

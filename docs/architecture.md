# MA-VLNA 架構說明

> **Memory-Augmented Vision-Language Navigation Agent**  
> 記憶增強型視覺語言導航代理

---

## 系統架構總覽

```
┌─────────────────────────────────────────────────────────────────┐
│                     Frontend Dashboard                          │
│  StatusPanel │ VisualPanel │ VLMPanel │ MemoryPanel │ ReplayLog │
└──────────┬──────────────────────────────────────────────────────┘
           │  REST + Supabase Realtime
┌──────────▼──────────────────────────────────────────────────────┐
│                    FastAPI Backend                               │
│  /vehicle/status │ /scenes │ /memory │ /replay │ /telemetry     │
└──────────┬──────────────────────────────────────────────────────┘
           │  Supabase Client
┌──────────▼──────────────────────────────────────────────────────┐
│                  Supabase (PostgreSQL + pgvector)                │
│  Vehicle_Status │ Scene_Logs │ Trajectory_Memory │ Storage       │
└──────────┬──────────────────────────────────────────────────────┘
           │  Read / Write
┌──────────▼──────────────────────────────────────────────────────┐
│                   Python Workers                                 │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │            Autonomous Driving Agent 主循環               │    │
│  │                                                         │    │
│  │  CameraAdapter ──► EdgePerception ──► EmbeddingBackend  │    │
│  │       │                  │                    │          │    │
│  │       ▼                  ▼                    ▼          │    │
│  │   raw frame      PerceptionResult      scene embedding  │    │
│  │                        │                    │           │    │
│  │                        ▼                    ▼           │    │
│  │               TriggerPolicy ◄── SceneMemoryRetriever    │    │
│  │                   │                                     │    │
│  │         ┌─────────┴─────────┐                           │    │
│  │         ▼                   ▼                           │    │
│  │    NO trigger          YES trigger                      │    │
│  │         │                   │                           │    │
│  │         ▼                   ▼                           │    │
│  │   LocalPlanner       VLMReasoner                        │    │
│  │   MemoryReplay            │                             │    │
│  │         │                  ▼                             │    │
│  │         │            SafetyGate                          │    │
│  │         │                  │                             │    │
│  │         ▼                  ▼                             │    │
│  │         SemanticPlanner (arbitrate)                      │    │
│  │                   │                                     │    │
│  │                   ▼                                     │    │
│  │            SimulatorAdapter                              │    │
│  │                   │                                     │    │
│  │                   ▼                                     │    │
│  │          TelemetryPublisher ──► Supabase                │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 1. 為何此重構方向符合 2026 年具身智能與視覺導航代理研究趨勢

2025–2026 年具身智能（Embodied AI）領域的核心趨勢：

- **VLM 不再是控制器，而是認知顧問**：從 RT-2、SayCan 到 2026 年的主流研究，VLM 的角色已從「直接產生 action token」轉向「提供場景理解與高階策略」，由專門的 planner 做最終決策。MA-VLNA 完全體現這個方向。

- **記憶增強導航取代逐幀推理**：逐幀呼叫大型 VLM 在延遲、成本與能耗上均不可行。記憶增強架構（先查記憶、再決定是否呼叫 VLM）是 2026 年的工程最佳實踐，與 MemoryNav、OVMM+ 等研究方向一致。

- **雙軌感知（Edge CV + VLM）成為標準架構**：高頻低延遲的邊緣 CV（YOLO / RT-DETR + tracker）處理常規幀，VLM 僅在異常事件觸發時介入。這與 NVIDIA DriveOS、Waymo 的感知分層架構一致。

- **決策可回放、可審計是工程要求**：不論學術或產業，具身智能系統必須支持決策回放（replay）、失敗案例分析、人工覆核。MA-VLNA 的 Supabase 記錄層與 dashboard 直接滿足這個需求。

---

## 2. 為何 VLM 適合擔任事件觸發式語義 Reasoner，而不是直接控制器

| 方面 | VLM 作為控制器 | VLM 作為事件觸發 Reasoner |
|---|---|---|
| 延遲 | 每幀 200ms–2s，不可接受 | 僅在觸發時呼叫，主循環不阻塞 |
| 成本 | 每秒 10–30 次推理，極高 | 平均每分鐘 0–3 次推理 |
| 安全 | VLM 幻覺直接影響車輛 | SafetyGate + Planner 仲裁 |
| 可擴展 | 綁死單一模型 | Protocol 接口，可替換任何 VLM |
| 邊緣部署 | 大模型無法在 Jetson 上逐幀跑 | 小模型 E2B/E4B 作為 fallback |

VLM 的價值在於**語義理解**：它能識別「前方是施工區、右邊有行人推嬰兒車、左邊車道雖然窄但可通行」，這是傳統 CV 模型做不到的。但它不需要每幀都做這件事 — 只有在邊緣 CV 無法確定的場景才需要 VLM 介入。

---

## 3. 為何場景記憶比逐幀 VLM 推理更合理

場景記憶（Scene Memory）的核心邏輯：

1. **先查後問**：對每個新場景，先在 pgvector 中查詢相似歷史場景。如果相似度高，直接 replay 歷史成功路徑，不需要呼叫 VLM。

2. **失敗教訓**：記憶中不僅有成功案例，也有失敗案例。失敗案例用於避免重複錯誤，例如「上次在這個彎道剎車太晚」。

3. **冷啟動效率**：新場景的 VLM 推理結果會被存入記憶。下次遇到相似場景時，可以直接使用，大幅降低 VLM 呼叫頻率。

4. **Planner Warm-Start**：歷史軌跡可以作為 planner 的初始解，加速規劃收斂。

這比逐幀 VLM 推理節省 95%+ 的推理資源，同時保留了 VLM 的語義理解能力。

---

## 4. 為何 Planner Arbitration 是安全關鍵

VLM 會產生幻覺（hallucination）。即使是最先進的 VLM，也可能：
- 誤判可通行區域
- 遺漏危險物件
- 建議不合理的速度
- 產生物理上不可行的路徑

因此，MA-VLNA 設計了三層安全機制：

```
VLM Output
    │
    ▼
SafetyGate ──── 檢查信心分數、速度限制、禁止動作
    │
    ▼
SemanticPlanner ── 驗證 waypoints 可行性、碰撞檢測
    │
    ▼
SimulatorAdapter ── 最終執行（第一版不接真實硬體）
```

任何一層拒絕 VLM 建議，系統都會退回保守策略（stop / wait / request_review），並將拒絕原因記錄到 telemetry，確保可追溯。

---

## 5. 為何前端 Dashboard 對研究展示與除錯是必要的

研究型系統不僅要「能跑」，還要「能看」：

- **除錯效率**：dashboard 讓研究者即時看到感知結果、VLM 推理、planner 決策、記憶檢索結果，不需要翻 log 檔。

- **成果展示**：向合作者、指導教授、產業夥伴展示系統能力時，dashboard 比終端輸出有說服力得多。

- **人工覆核**：operator 可以透過 dashboard 審核 VLM 的建議、覆寫 planner 決策、標記失敗案例。

- **Replay 分析**：研究者可以回放歷史場景，觀察系統在不同觸發條件下的行為，識別邊界案例。

- **A/B 比較**：未來可以在 dashboard 上同時顯示不同 VLM / planner 配置的結果，支援消融實驗。

---

## 6. 為何這個架構比原始 Face_Detect_Realtime 更適合作為工程型研究專案

| 維度 | 原始 Face_Detect_Realtime | MA-VLNA |
|---|---|---|
| **架構** | 單檔主循環 + Firebase | 多層解耦：Workers / API / Frontend / Shared Schema |
| **感知** | face_recognition 單模態 | 雙軌：Edge CV + VLM |
| **記憶** | pickle 檔案 + Firebase KV | pgvector 向量記憶 + 軌跡記憶 |
| **決策** | if-else 比對 | Trigger Policy → VLM → SafetyGate → Planner |
| **可替換性** | 硬編碼模型 | Protocol 接口，支援替換任何模組 |
| **可回放** | 無 | 全程記錄，支援 replay 與審計 |
| **前端** | cv2.imshow | 研究 dashboard，5 面板即時展示 |
| **部署** | 僅本機 webcam | 可接 Simulator / ROS2 / Jetson / 真實平台 |
| **擴展** | 無擴展性 | 預留 PostGIS、Isaac Sim、ROS2 接口 |

原始專案是一個「能動的 demo」。MA-VLNA 是一個「可研究、可部署、可驗證的工程系統」。

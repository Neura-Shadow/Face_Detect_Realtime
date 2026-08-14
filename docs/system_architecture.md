# MA-VLNA 系統架構圖

> Memory-Augmented Vision-Language Navigation Agent — 系統架構設計文件

---

## 系統總覽 Mermaid 圖

```mermaid
graph TB
    subgraph Frontend["🖥️ Frontend Dashboard<br/>(Next.js 16 + Tailwind CSS + shadcn/ui)"]
        SP["StatusPanel<br/>車輛狀態"]
        VP["VisualPanel<br/>感知視覺化"]
        VLMP["VLMReasoningPanel<br/>VLM 推理展示"]
        SMP["SceneMemoryPanel<br/>場景記憶 Top-K"]
        RLP["ReplayLogsPanel<br/>軌跡回放"]
    end

    subgraph Backend["⚡ FastAPI Backend<br/>(9 REST Endpoints, Query-Only)"]
        VH["/api/vehicle/status"]
        SC["/api/scenes"]
        MEM["/api/memory/top-k"]
        REP["/api/replay/{id}"]
        TEL["/api/telemetry/recent"]
        TRG["/api/triggers/recent"]
        PLN["/api/planner/state"]
        OPR["/api/operator/review"]
        HLT["/api/health"]
    end

    subgraph Database["🗄️ Supabase<br/>(PostgreSQL + pgvector + Storage)"]
        VS_T["vehicle_status"]
        SL_T["scene_logs"]
        TM_T["trajectory_memory"]
        TE_T["telemetry_entries"]
        TR_T["trigger_events"]
        OR_T["operator_reviews"]
        STR["Storage Bucket<br/>scene-frames"]
        RPC["RPC: match_scene_memories<br/>RPC: match_trajectory_memories"]
    end

    subgraph Workers["🤖 Python Workers<br/>(Autonomous Driving Agent)"]
        CAM["CameraAdapter<br/>相機/模擬器"]
        EP["EdgePerception<br/>YOLO / RT-DETR"]
        EB["EmbeddingBackend<br/>CLIP / SigLIP"]
        SMR["SceneMemoryRetriever<br/>pgvector 查詢"]
        TP["TriggerPolicy<br/>7 大觸發條件"]
        VLM["VLMReasoner<br/>Gemma 4 / Stub"]
        SG["SafetyGate<br/>速度與禁止動作"]
        SPL["SemanticPlanner<br/>A* 本地 + VLM 全局"]
        SIM["SimulatorAdapter<br/>Dummy / ROS2 / Isaac"]
        TPUB["TelemetryPublisher<br/>非同步批次寫入"]
    end

    %% Frontend → Backend
    SP --> VH
    VP --> SC
    VLMP --> SC
    SMP --> MEM
    RLP --> TEL
    RLP --> TRG
    RLP --> REP

    %% Backend → Database
    VH --> VS_T
    SC --> SL_T
    MEM --> RPC
    REP --> TM_T
    TEL --> TE_T
    TRG --> TR_T
    PLN --> VS_T
    OPR --> OR_T

    %% Workers → Database
    TPUB --> VS_T
    TPUB --> SL_T
    TPUB --> TE_T
    TPUB --> TR_T
    SMR --> RPC
    EB --> SL_T

    %% Worker internal flow
    CAM --> EP
    EP --> EB
    EB --> SMR
    SMR --> TP
    TP -->|NO trigger| SPL
    TP -->|YES trigger| VLM
    VLM --> SG
    SG -->|approved| SPL
    SG -->|rejected| SPL
    SPL --> SIM
    SIM --> TPUB

    style Frontend fill:#1e1b4b,stroke:#6366f1,color:#e0e7ff
    style Backend fill:#1a2e05,stroke:#65a30d,color:#ecfccb
    style Database fill:#4a1d1d,stroke:#ef4444,color:#fecaca
    style Workers fill:#172554,stroke:#3b82f6,color:#dbeafe
```

---

## Agent 12 步導航循環 (Main Loop)

```mermaid
flowchart TD
    START(["🚀 主迴圈開始"]) --> S1["Step 1<br/>CameraAdapter.read()"]
    S1 --> S2["Step 2<br/>EdgePerception.detect()"]
    S2 --> S3["Step 3<br/>EmbeddingBackend.encode()"]
    S3 --> S4["Step 4<br/>SceneMemoryRetriever.query_top_k()"]
    S4 --> S5{"Step 5<br/>TriggerPolicy.evaluate()"}

    S5 -->|"❌ NO trigger"| S6A["Step 6A<br/>SemanticPlanner.plan_local()<br/>或 plan_from_replay()"]
    S5 -->|"✅ YES trigger"| S7["Step 7<br/>VLMReasoner.reason()"]

    S7 --> S8{"Step 8<br/>SafetyGate.validate()"}
    S8 -->|"✅ approved"| S9["Step 9<br/>SemanticPlanner.plan_with_vlm()"]
    S8 -->|"❌ rejected"| S12F["記錄拒絕原因<br/>退回保守策略"]

    S6A --> S10
    S9 --> S10["Step 10<br/>SimulatorAdapter.execute()"]
    S12F --> S10

    S10 --> S11["Step 11<br/>TelemetryPublisher.publish()"]
    S11 --> S12{"Step 12<br/>異常處理檢查"}

    S12 -->|"正常"| NEXT["下一幀"]
    S12 -->|"異常"| ESTOP["🛑 emergency_stop()<br/>+ request_review()"]

    NEXT --> S1
    ESTOP --> S1

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style S5 fill:#f59e0b,stroke:#d97706,color:#000
    style S8 fill:#ef4444,stroke:#dc2626,color:#fff
    style S12 fill:#ef4444,stroke:#dc2626,color:#fff
    style ESTOP fill:#dc2626,stroke:#991b1b,color:#fff
```

---

## VLM 觸發條件 (Trigger Policy)

```mermaid
flowchart LR
    subgraph triggers["7 大觸發條件"]
        T1["🆕 未知場景<br/>novelty_score > 閾值"]
        T2["⚠️ 多物件衝突<br/>互動物件 > 上限"]
        T3["🔄 場景劇變<br/>embedding 距離突增"]
        T4["📉 感知不確定<br/>偵測信心低於閾值"]
        T5["⏰ 定時刷新<br/>距上次 VLM 過久"]
        T6["🚧 高風險物件<br/>偵測到行人/施工"]
        T7["👤 人工請求<br/>Operator 強制觸發"]
    end

    triggers --> EVAL{"TriggerPolicy<br/>evaluate()"}
    EVAL -->|"任一成立"| VLM["呼叫 VLMReasoner"]
    EVAL -->|"全部不成立"| LOCAL["使用 LocalPlanner"]

    style triggers fill:#1e1b4b,stroke:#6366f1,color:#e0e7ff
    style EVAL fill:#f59e0b,stroke:#d97706,color:#000
    style VLM fill:#10b981,stroke:#059669,color:#fff
    style LOCAL fill:#6b7280,stroke:#4b5563,color:#fff
```

---

## VLM Reasoner 可替換架構

```mermaid
classDiagram
    class VLMReasoner {
        <<Protocol>>
        +reason(frame, perception, memory_context) VLMOutput
        +name() str
    }

    class LocalStubReasoner {
        +reason() VLMOutput
        +name() "local-stub"
        模擬 VLM 回應，用於 Mock 測試
    }

    class OpenAICompatibleReasoner {
        +reason() VLMOutput
        +name() str
        支援任何 OpenAI-compatible API
        包含 Gemma 4, GPT-4V, Claude
    }

    class GemmaReasoner {
        +reason() VLMOutput
        +name() "gemma-4-27b"
        OpenAICompatibleReasoner 的特化
        使用 Gemma 4 模型端點
    }

    VLMReasoner <|.. LocalStubReasoner
    VLMReasoner <|.. OpenAICompatibleReasoner
    OpenAICompatibleReasoner <|-- GemmaReasoner

    note for VLMReasoner "所有 VLM 輸出必須符合\nshared/schemas/vlm_output_schema.json"
```

---

## 安全機制三層架構

```mermaid
flowchart TD
    VLM_OUT["VLM Output<br/>(JSON 結構化輸出)"] --> CHECK1

    subgraph SafetyGate["🛡️ SafetyGate — 第一層"]
        CHECK1{"信心分數 ≥ 閾值？"}
        CHECK2{"速度 ≤ 上限？"}
        CHECK3{"動作不在禁止列表？"}
        CHECK1 -->|Yes| CHECK2
        CHECK2 -->|Yes| CHECK3
        CHECK1 -->|No| REJ1["❌ 拒絕: 信心不足"]
        CHECK2 -->|No| LIMIT["⚠️ 強制限速"]
        CHECK3 -->|No| REJ2["❌ 拒絕: 禁止動作"]
    end

    CHECK3 -->|Yes| PLANNER
    LIMIT --> PLANNER

    subgraph PlannerValidation["🗺️ SemanticPlanner — 第二層"]
        PLANNER{"Waypoints 可行？<br/>無碰撞？"}
    end

    PLANNER -->|Yes| EXEC
    PLANNER -->|No| FALLBACK["退回 LocalPlanner"]

    subgraph Execution["🤖 SimulatorAdapter — 第三層"]
        EXEC["執行動作序列"]
    end

    REJ1 --> LOG["📋 記錄拒絕到 Telemetry"]
    REJ2 --> LOG
    FALLBACK --> LOG

    style SafetyGate fill:#4a1d1d,stroke:#ef4444,color:#fecaca
    style PlannerValidation fill:#1a2e05,stroke:#65a30d,color:#ecfccb
    style Execution fill:#172554,stroke:#3b82f6,color:#dbeafe
```

---

## 資料流與儲存架構

```mermaid
erDiagram
    vehicle_status {
        text vehicle_id PK
        text mode
        float speed_mps
        jsonb position
        text current_action
        timestamptz updated_at
    }

    scene_logs {
        uuid id PK
        text vehicle_id FK
        text frame_url
        vector768 scene_embedding
        jsonb perception_result
        jsonb vlm_output
        float trigger_score
        text trigger_reason
        timestamptz created_at
    }

    trajectory_memory {
        uuid id PK
        text vehicle_id FK
        uuid scene_id FK
        vector768 scene_embedding
        jsonb planned_path
        text outcome
        float reward_score
        timestamptz created_at
    }

    telemetry_entries {
        uuid id PK
        text vehicle_id FK
        text entry_type
        jsonb payload
        timestamptz created_at
    }

    trigger_events {
        uuid id PK
        text vehicle_id FK
        uuid scene_id FK
        text trigger_type
        float score
        jsonb context
        timestamptz created_at
    }

    operator_reviews {
        uuid id PK
        text vehicle_id FK
        uuid scene_id FK
        text decision
        text reason
        text reviewer_id
        timestamptz created_at
    }

    vehicle_status ||--o{ scene_logs : "produces"
    vehicle_status ||--o{ telemetry_entries : "emits"
    scene_logs ||--o{ trajectory_memory : "generates"
    scene_logs ||--o{ trigger_events : "triggers"
    scene_logs ||--o{ operator_reviews : "reviewed_by"
```

---

## 部署拓撲

```mermaid
graph TB
    subgraph Dev["🧑‍💻 開發環境 (Mock Mode)"]
        DEV_W["Python Agent<br/>Mock Camera + Stub VLM"]
        DEV_B["FastAPI<br/>MockSupabaseClient"]
        DEV_F["Next.js Dev Server<br/>mock-data.ts"]
    end

    subgraph Staging["🧪 暫存環境"]
        STG_W["Python Agent<br/>Simulator + Gemma 4 API"]
        STG_B["FastAPI<br/>Supabase Cloud"]
        STG_F["Next.js<br/>Vercel Preview"]
        STG_DB[("Supabase<br/>PostgreSQL")]
    end

    subgraph Production["🚀 生產環境"]
        PRD_W["Python Agent<br/>Jetson + Camera + VLM"]
        PRD_B["FastAPI<br/>Supabase Cloud"]
        PRD_F["Next.js<br/>Vercel / Docker"]
        PRD_DB[("Supabase<br/>PostgreSQL")]
        PRD_R["ROS2 / Isaac Sim"]
    end

    DEV_W -.->|升級| STG_W
    STG_W -.->|升級| PRD_W
    PRD_W --> PRD_R

    style Dev fill:#1e1b4b,stroke:#6366f1,color:#e0e7ff
    style Staging fill:#1a2e05,stroke:#65a30d,color:#ecfccb
    style Production fill:#4a1d1d,stroke:#ef4444,color:#fecaca
```

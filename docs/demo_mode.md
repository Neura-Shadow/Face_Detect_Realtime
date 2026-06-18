# Mock Demo Mode 完整指南

> 在沒有 Supabase、沒有 VLM API、沒有真實 Camera 的情況下，跑完整 MA-VLNA 系統展示。

---

## 概述

MA-VLNA 提供三層完整的 Mock 模式降級機制，讓研究者可以在任何乾淨的開發環境中，
不需要任何外部 API 金鑰或硬體設備，即可驗證整個 12 步導航循環、9 個 API 端點、
以及 5 面板 Dashboard 的完整功能。

### Mock 模式降級架構

```
┌─────────────────────────────────────────────────────────────┐
│                    Mock Mode 降級層                         │
├──────────────────┬──────────────────────────────────────────┤
│ 模組             │ Mock 替代                                │
├──────────────────┼──────────────────────────────────────────┤
│ Camera           │ SimulatorCameraAdapter (合成 numpy 影像)  │
│ VLM Reasoner     │ LocalStubReasoner (產生模擬 JSON 回應)    │
│ Embedding        │ DummyEmbeddingBackend (隨機 768-dim 向量) │
│ Scene Memory     │ 空記憶庫 → 所有場景視為「未知」            │
│ Supabase (Agent) │ stub 模式：所有寫入操作靜默忽略           │
│ Supabase (API)   │ MockSupabaseClient 產生模擬查詢結果       │
│ Simulator        │ DummySimulatorAdapter (日誌記錄，不執行)   │
│ Frontend Data    │ mock-data.ts 提供靜態展示資料             │
└──────────────────┴──────────────────────────────────────────┘
```

---

## 前置需求

| 工具 | 最低版本 | 檢查指令 |
|------|---------|---------|
| Python | 3.10+ | `python --version` |
| Node.js | 18+ | `node --version` |
| npm | 9+ | `npm --version` |
| pip | 23+ | `pip --version` |

> **注意**：Mock 模式不需要 GPU、CUDA、CLIP 模型、Supabase 帳號或任何 API Key。

---

## 第一步：啟動 Python Agent（Workers 層）

Python Agent 是整個系統的核心，執行 12 步自動駕駛導航循環。

### 安裝依賴

```bash
cd workers
pip install -r requirements.txt
```

### 啟動 Mock Mode Agent

```bash
python -m workers.Autonomous_Driving_Agent --mode mock --steps 10
```

#### 參數說明

| 參數 | 說明 | 預設值 |
|------|------|--------|
| `--mode mock` | 啟用完整 Mock 模式 | `simulator` |
| `--steps N` | 執行 N 步後自動結束 | 無限循環 |

#### 預期輸出

```text
supabase-py 未安裝，SupabaseManager 將以 stub 模式執行
INFO  | 啟動 MA-VLNA 自動駕駛代理系統...
INFO  | ==================================================
INFO  | 啟用 MOCK 模式：自動開啟模擬相機並強制使用 LocalStub VLM
INFO  | ==================================================
INFO  | [Step 1/10] 讀取模擬幀...
INFO  | EdgePerception: 偵測到 3 個物件
INFO  | TriggerPolicy: 觸發條件不滿足，使用本地規劃器
INFO  | [Dummy] 動作 #1: plan_id=plan-xxxx, source=local_planner
...
INFO  | [Step 10/10] 達到指定步數，正常結束主迴圈
INFO  | 關閉 MA-VLNA 代理中...
INFO  | TelemetryPublisher 已關閉
INFO  | SimulatorCameraAdapter 已關閉
INFO  | 關閉完成，總計處理 10 幀。
```

#### 12 步循環中的 Mock 行為

| 步驟 | 行為 | Mock 實現 |
|------|------|-----------|
| 1. 讀取影像 | `SimulatorCameraAdapter` 生成合成幀 | 隨機色彩漸變 numpy 陣列 |
| 2. 邊緣感知 | `EdgePerception` 返回模擬偵測結果 | 隨機物件邊界框 + 類別 |
| 3. 場景嵌入 | `DummyEmbeddingBackend` 生成向量 | 隨機 768 維度浮點向量 |
| 4. 記憶查詢 | `SceneMemoryRetriever` 查詢 pgvector | 回傳空列表（無 Supabase） |
| 5. 觸發判定 | `TriggerPolicy` 評估 7 大條件 | 基於隨機感知結果判定 |
| 6. 無觸發路徑 | 本地 A* 規劃器或記憶 Replay | 生成模擬路徑點 |
| 7. 觸發路徑 | `LocalStubReasoner` 模擬 VLM 回應 | 返回模板化 JSON |
| 8. 安全門 | `SafetyGate` 檢查信心與速度 | 正常驗證流程 |
| 9. 規劃仲裁 | `SemanticPlanner` 整合決策 | 正常仲裁邏輯 |
| 10. 執行 | `DummySimulatorAdapter` 日誌記錄 | 輸出動作到 console |
| 11. 遙測 | `TelemetryPublisher` stub 寫入 | 靜默忽略寫入 |
| 12. 異常處理 | 緊急停車 + 日誌 | 正常異常處理邏輯 |

---

## 第二步：啟動 FastAPI 後端（Backend 層）

FastAPI 後端提供 9 個 REST API 端點，自動偵測 Supabase 連線狀態並降級。

### 安裝依賴

```bash
cd backend
pip install -r requirements.txt
```

### 啟動 Mock Backend Server

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8080 --reload
```

#### 自動降級行為

當環境變數中缺少 `SUPABASE_URL` 或 `SUPABASE_SERVICE_ROLE_KEY` 時，
`backend/deps.py` 會自動創建 `MockSupabaseClient`，為所有端點提供模擬數據：

```text
WARNING  | Supabase 環境變數缺失，啟用 MockSupabaseClient
INFO     | Uvicorn running on http://127.0.0.1:8080
```

### 9 個 API 端點 Mock 行為

| 端點 | HTTP | Mock 回應 |
|------|------|-----------|
| `/api/health` | GET | `{"status": "ok", "mode": "mock"}` |
| `/api/vehicle/status` | GET | 模擬車輛狀態 (vehicle-001) |
| `/api/scenes` | GET | 分頁模擬場景日誌列表 |
| `/api/scenes/{id}` | GET | 單一模擬場景詳情 |
| `/api/memory/top-k` | GET | 模擬 cosine 相似度結果 |
| `/api/replay/{id}` | GET | 模擬場景回放軌跡 |
| `/api/telemetry/recent` | GET | 模擬遙測數據陣列 |
| `/api/triggers/recent` | GET | 模擬觸發事件列表 |
| `/api/planner/state` | GET | 模擬規劃器狀態 |
| `/api/operator/review` | POST | 接受審核決策，返回 OK |

### 快速驗證端點

```bash
# 健康檢查
curl http://127.0.0.1:8080/api/health

# 車輛狀態
curl http://127.0.0.1:8080/api/vehicle/status

# 場景列表
curl http://127.0.0.1:8080/api/scenes?limit=5

# 記憶查詢
curl "http://127.0.0.1:8080/api/memory/top-k?k=3"

# 遙測數據
curl http://127.0.0.1:8080/api/telemetry/recent

# 觸發事件
curl http://127.0.0.1:8080/api/triggers/recent
```

---

## 第三步：啟動 Next.js Dashboard（Frontend 層）

Dashboard 提供 5 個面板的即時視覺化展示，在 Mock 模式下使用靜態展示資料。

### 安裝依賴

```bash
cd frontend
npm install
```

### 啟動開發伺服器

```bash
npm run dev
```

開啟瀏覽器訪問：**http://localhost:3000**

### Dashboard 5 面板

| 面板 | 展示內容 | 資料來源 |
|------|---------|---------|
| **StatusPanel** | 車輛狀態、速度、模式、連線狀態 | `/api/vehicle/status` 或 `mock-data.ts` |
| **VisualPanel** | 感知結果、BEV 視角、偵測框 | `/api/scenes` 或靜態模擬影像 |
| **VLMReasoningPanel** | VLM 推理輸出、信心分數、安全門結果 | `/api/scenes/{id}` 或模擬 JSON |
| **SceneMemoryPanel** | Top-K 相似場景、相似度分數、向量視覺化 | `/api/memory/top-k` 或模擬數據 |
| **ReplayLogsPanel** | 軌跡回放、觸發事件時間線、遙測圖表 | `/api/telemetry/recent` 或模擬數據 |

### Frontend Mock 策略

`src/lib/mock-data.ts` 提供完整的靜態展示資料集，當 API 不可達時自動 fallback：

```typescript
// src/lib/api.ts 中的 fallback 邏輯
async function fetchWithFallback<T>(url: string, mockData: T): Promise<T> {
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(res.statusText);
    return await res.json();
  } catch {
    console.warn(`API 不可達，使用 mock 數據: ${url}`);
    return mockData;
  }
}
```

---

## 一鍵啟動腳本

### Windows (PowerShell)

```powershell
# 終端 1：Workers Agent
cd d:\Face_Detect_Realtime
python -m workers.Autonomous_Driving_Agent --mode mock --steps 20

# 終端 2：FastAPI Backend
cd d:\Face_Detect_Realtime
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8080 --reload

# 終端 3：Frontend Dashboard
cd d:\Face_Detect_Realtime\frontend
npm run dev
```

### Linux / macOS (Bash)

```bash
# 終端 1
cd /path/to/Face_Detect_Realtime
python -m workers.Autonomous_Driving_Agent --mode mock --steps 20

# 終端 2
cd /path/to/Face_Detect_Realtime
uvicorn backend.main:app --host 127.0.0.1 --port 8080 --reload

# 終端 3
cd /path/to/Face_Detect_Realtime/frontend
npm run dev
```

---

## 常見問題

### Q: Mock 模式和真實模式的行為差異？

Mock 模式的核心邏輯（觸發判定、安全門驗證、規劃器仲裁）與真實模式**完全相同**。
唯一的差異在於 I/O 端：

- **輸入端**：合成影像取代真實相機
- **推理端**：模板化 JSON 取代真實 VLM API
- **儲存端**：靜默忽略取代真實 Supabase 寫入
- **執行端**：日誌記錄取代真實機器人控制

### Q: 如何從 Mock 模式切換到真實模式？

1. 配置 `config/.env` 中的 `SUPABASE_URL` 和 `SUPABASE_SERVICE_ROLE_KEY`
2. 在 Supabase SQL Editor 執行 `migrations/001_init.sql`
3. 執行 `python -m workers.Initialize_Supabase` 寫入種子資料
4. 使用 `--mode simulator` 或 `--mode camera` 啟動 Agent

### Q: 可以只跑部分層嗎？

可以。三層完全解耦：

- **只跑 Agent**：驗證 12 步循環邏輯，不需要 Backend 或 Frontend
- **只跑 Backend**：驗證 API 端點和 Mock 數據，不需要 Agent 或 Frontend
- **只跑 Frontend**：使用 `mock-data.ts` 展示 Dashboard，不需要 Backend 或 Agent

### Q: Mock 模式需要 GPU 嗎？

不需要。Mock 模式不載入任何 ML 模型（YOLO、CLIP、VLM），所有計算都是 CPU 上的輕量模擬。

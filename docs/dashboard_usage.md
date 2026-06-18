# MA-VLNA Dashboard 使用指南

## 啟動 Dashboard

### 1. 啟動 FastAPI Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

### 2. 啟動 Frontend

```bash
cd frontend
npm install
npm run dev
```

開啟瀏覽器，前往 `http://localhost:3000`。

### 3.（可選）啟動 Agent Worker

```bash
cd workers
pip install -r requirements.txt
python Autonomous_Driving_Agent.py
```

Agent 啟動後，Dashboard 會透過 Supabase Realtime 自動更新。

---

## Dashboard 面板說明

### StatusPanel（即時狀態面板）

顯示 Agent 的即時運行狀態：

| 欄位 | 說明 |
|---|---|
| vehicle_id | 當前 Agent 的識別碼 |
| planner_state | 規劃器狀態：idle / navigating / stopped / safe_stop / deadlock / waiting_review |
| current_speed | 當前速度（m/s） |
| last_trigger_reason | 最近一次觸發 VLM 的原因 |
| VLM Active | VLM Reasoner 是否正在介入（閃爍青色指示燈表示活躍） |
| current_action | 當前執行的動作 |
| safe_mode | 安全模式是否啟動（紅色警示） |

### VisualPanel（視覺畫面面板）

顯示感知系統的即時輸出：

- **Camera / Simulator 畫面**：顯示最新的關鍵影格。若無即時串流，使用 Scene Log 中的歷史幀。
- **Detection Overlay**：邊界框、類別標籤、信心分數
- **Track 狀態**：追蹤 ID、軌跡線
- **Free Space**：可通行區域估計
- **Waypoint Hints**：規劃器輸出的航點

### VLMReasoningPanel（VLM 推理面板）

當 VLM Reasoner 被觸發時，顯示其結構化輸出：

- **scene_summary**：場景自然語言摘要
- **hazards**：危險物件列表（依嚴重程度標色）
- **navigable_regions**：可通行區域描述
- **waypoint_hints**：語義航點建議
- **speed_hint**：建議速度（stop / slow / normal）
- **must_not_do**：禁止動作（紅色警示）
- **confidence**：VLM 信心分數（漸層進度條）
- **Rejected by Planner**：若 Safety Gate 或 Planner 拒絕了 VLM 建議，顯示拒絕原因

### SceneMemoryPanel（場景記憶面板）

顯示與當前場景最相似的歷史場景：

- **Top-K 相似場景**：依相似度排序
- **Similarity Score**：進度條顯示相似程度
- **Replay Candidate**：是否可作為 replay 候選（星號標記）
- **Success Flag**：歷史案例是成功還是失敗
- **Historical Action Sequence**：歷史動作序列預覽
- **Source Scene ID**：可點擊跳轉到該場景的詳細資料

### ReplayLogsPanel（Replay / 日誌面板）

可滾動的事件時間軸：

- **篩選標籤**：All / Triggers / Planner / Safety / VLM / Operator
- **事件類型**依顏色區分：
  - 🔵 `vlm_triggered` — VLM 被觸發
  - 🔴 `vlm_rejected` — VLM 建議被拒絕
  - 🟠 `safe_stop` — 安全停車
  - 🟡 `request_review` — 請求人工覆核
  - 🟣 `planner_override` — 規劃器覆寫
  - 🟢 `memory_replay` — 記憶回放

---

## 人工覆核操作

1. 在 ReplayLogsPanel 中找到 `request_review` 事件
2. 檢查 VLMReasoningPanel 中的 VLM 輸出
3. 在 StatusPanel 確認當前狀態
4. 使用 Operator Review API 提交決策：
   - **approve**：接受 VLM 建議
   - **reject**：拒絕 VLM 建議，維持保守策略
   - **override**：提供替代動作

---

## 無真實資料時的使用

所有面板在無 Backend 連線時會自動使用 **mock data** 顯示，確保 Dashboard 可獨立展示和開發。

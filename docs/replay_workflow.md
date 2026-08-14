# MA-VLNA Replay 工作流程

## 概述

Replay 是 MA-VLNA 的核心功能之一。它允許研究者回放歷史場景的完整決策閉環：從感知輸入到 VLM 推理、Planner 仲裁、最終動作執行，以及記憶檢索的過程。

---

## Replay 資料流

```
Scene_Logs (Supabase)
    │
    ├── frame_url ──────── 關鍵影格（Supabase Storage）
    ├── detections ─────── Edge CV 偵測結果
    ├── tracks ─────────── 追蹤結果
    ├── lane_state ─────── 車道狀態
    ├── free_space ─────── 可通行區域
    ├── trigger_reason ──── VLM 觸發原因
    ├── vlm_output ─────── VLM 結構化推理輸出
    ├── planner_action ──── Planner 最終決策
    ├── success_flag ────── 結果標記
    └── metadata ────────── 附加資訊
              │
              ▼
Trajectory_Memory (Supabase)
    │
    ├── action_sequence ── 完整動作序列
    ├── waypoints ──────── 航點序列
    ├── outcome ─────────── 執行結果
    └── semantic_summary ── 語義摘要
```

---

## Replay 使用場景

### 1. 除錯失敗案例

```
步驟：
1. 在 ReplayLogsPanel 找到 success_flag = false 的事件
2. 點擊 scene_id 查看該場景的完整記錄
3. 檢查 VLM 推理（是否有幻覺？）
4. 檢查 Planner 決策（是否正確拒絕了不安全的建議？）
5. 檢查 Edge CV 感知（是否遺漏了某些物件？）
6. 根據分析結果調整 trigger policy 或 safety gate 參數
```

### 2. 驗證保守策略

```
步驟：
1. 篩選 event_type = 'vlm_rejected' 的事件
2. 檢查 SafetyGate 的拒絕原因
3. 評估拒絕是否合理
4. 若過度保守，調整 safety_gate 的 confidence_floor 參數
5. 若不夠保守，加嚴觸發條件
```

### 3. 記憶品質評估

```
步驟：
1. 選擇一個 scene_id
2. 在 SceneMemoryPanel 查看 top-k 相似場景
3. 檢查相似度分數是否合理
4. 檢查 replay candidate 的 success_flag
5. 確認歷史 action_sequence 是否適用於當前場景
```

### 4. VLM 模型比較

```
步驟：
1. 收集同一場景在不同 VLM 模型下的推理結果
2. 比較 vlm_output 中的 scene_summary、hazards、confidence
3. 比較 Planner 對不同 VLM 輸出的接受率
4. 評估不同模型的推理延遲 (vlm_latency_ms)
```

---

## Replay API

### 取得單一場景的完整 Replay 資料

```
GET /api/replay/{scene_id}
```

回傳：
```json
{
  "request_id": "...",
  "status": "success",
  "data": {
    "scene_log": { ... },
    "trajectory_memory": { ... },
    "related_scenes": [ ... ]
  }
}
```

### 取得場景日誌時間軸

```
GET /api/scenes?vehicle_id=vehicle-001&limit=50&offset=0
```

### 取得觸發事件

```
GET /api/triggers/recent?vehicle_id=vehicle-001&limit=20
```

---

## Replay 與記憶的關係

Replay 不僅用於除錯，也是記憶系統的核心機制：

1. **成功案例 Replay**：當 SceneMemoryRetriever 找到高相似度的成功案例時，Planner 可以直接使用歷史 action_sequence 作為 warm-start，跳過 VLM 推理。

2. **失敗案例避免**：記憶中的失敗案例（success_flag = false）用於避免重複錯誤。Planner 會檢查候選路徑是否與歷史失敗軌跡相似。

3. **記憶衝突檢測**：如果 replay candidate 的歷史感知與當前感知衝突（例如歷史場景沒有障礙物但當前場景有），系統會自動阻止 replay，改為呼叫 VLM。

```
場景 embedding 查詢
    │
    ├── 相似度 > replay_min_similarity (0.88)
    │   └── 且 success_flag = true
    │       └── 且 無感知衝突
    │           └── ✅ 允許 Replay
    │
    ├── 相似度 > similarity_threshold (0.82)
    │   └── 但不符合 replay 條件
    │       └── 作為 planner warm-start 參考
    │
    └── 相似度 < unknown_scene_threshold (0.55)
        └── 判定為未知場景 → 觸發 VLM
```

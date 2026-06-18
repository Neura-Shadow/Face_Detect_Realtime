# Shared Schema Layer

MA-VLNA 跨層資料格式定義。所有 JSON Schema 檔案是 **唯一的真相來源（single source of truth）**。

## 檔案說明

| Schema | 用途 | 消費者 |
|---|---|---|
| `vlm_output_schema.json` | VLM Reasoner 結構化輸出 | Python VLMReasoner → SafetyGate → Planner → Frontend |
| `telemetry_schema.json` | 遙測資料條目 | TelemetryPublisher → Backend API → Frontend |
| `planner_action_schema.json` | 規劃器動作輸出 | SemanticPlanner → SimulatorAdapter → Frontend |
| `scene_memory_schema.json` | 場景記憶條目 | SceneMemoryRetriever → Backend API → Frontend |

## 使用方式

- **Python**: 透過 `workers/core/config.py` 中的 Pydantic dataclass 實作
- **FastAPI**: 透過 `backend/schemas.py` 中的 Pydantic response model
- **Frontend**: 透過 `frontend/src/types/schemas.ts` 中的 TypeScript type 定義

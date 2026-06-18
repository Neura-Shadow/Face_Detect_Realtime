/**
 * MA-VLNA 後端 API 呼叫函式
 * 提供所有 9 個端點的 fetch 封裝，當後端不可用時自動回退至模擬資料
 */

import type {
  ApiResponse,
  VehicleStatus,
  SceneLog,
  SceneMemoryEntry,
  TelemetryEntry,
  PlannerAction,
  OperatorReview,
} from '@/types/schemas';

import {
  mockVehicleStatus,
  mockSceneLogs,
  mockSceneMemories,
  mockTelemetryEntries,
  mockPlannerAction,
} from '@/lib/mock-data';

/* ─── API 基礎位址 ─── */
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8080';

/* ─── 輔助：產生唯一請求 ID ─── */
const genRequestId = (): string =>
  `req-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

/* ─── 輔助：建立成功回應封裝 ─── */
function wrapOk<T>(data: T): ApiResponse<T> {
  return {
    request_id: genRequestId(),
    status: 'ok',
    data,
    error_code: null,
    error_message: null,
    retryable: false,
  };
}

/* ─── 輔助：通用 fetch 包裝，失敗時回退模擬資料 ─── */
async function safeFetch<T>(
  path: string,
  fallback: T,
  options?: RequestInit,
): Promise<ApiResponse<T>> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json: ApiResponse<T> = await res.json();
    return json;
  } catch {
    // 後端不可用時回退至模擬資料
    console.warn(`[api] ${path} 無法連線，使用模擬資料`);
    return wrapOk(fallback);
  }
}

/* ═══════════════════════════════════════════════════
   1. 車輛即時狀態
   GET /api/v1/vehicle/status
   ═══════════════════════════════════════════════════ */
export async function fetchVehicleStatus(): Promise<ApiResponse<VehicleStatus>> {
  return safeFetch('/api/v1/vehicle/status', mockVehicleStatus);
}

/* ═══════════════════════════════════════════════════
   2. 場景日誌列表
   GET /api/v1/scenes?limit=&offset=
   ═══════════════════════════════════════════════════ */
export async function fetchScenes(
  limit: number = 20,
  offset: number = 0,
): Promise<ApiResponse<SceneLog[]>> {
  return safeFetch(
    `/api/v1/scenes?limit=${limit}&offset=${offset}`,
    mockSceneLogs.slice(offset, offset + limit),
  );
}

/* ═══════════════════════════════════════════════════
   3. 單一場景詳情
   GET /api/v1/scenes/:sceneId
   ═══════════════════════════════════════════════════ */
export async function fetchScene(
  sceneId: string,
): Promise<ApiResponse<SceneLog>> {
  const fallback =
    mockSceneLogs.find((s) => s.scene_id === sceneId) ?? mockSceneLogs[0];
  return safeFetch(`/api/v1/scenes/${sceneId}`, fallback);
}

/* ═══════════════════════════════════════════════════
   4. 場景記憶 Top-K 相似場景
   GET /api/v1/memory/topk?scene_id=&k=
   ═══════════════════════════════════════════════════ */
export async function fetchMemoryTopK(
  sceneId: string,
  k: number = 5,
): Promise<ApiResponse<SceneMemoryEntry[]>> {
  return safeFetch(
    `/api/v1/memory/topk?scene_id=${sceneId}&k=${k}`,
    mockSceneMemories.slice(0, k),
  );
}

/* ═══════════════════════════════════════════════════
   5. 記憶回放資料
   GET /api/v1/replay/:sceneId
   備註：ReplayData 型別暫以 SceneMemoryEntry 替代
   ═══════════════════════════════════════════════════ */
export async function fetchReplay(
  sceneId: string,
): Promise<ApiResponse<SceneMemoryEntry>> {
  const fallback =
    mockSceneMemories.find((m) => m.source_scene_id === sceneId) ??
    mockSceneMemories[0];
  return safeFetch(`/api/v1/replay/${sceneId}`, fallback);
}

/* ═══════════════════════════════════════════════════
   6. 近期遙測紀錄
   GET /api/v1/telemetry/recent?limit=
   ═══════════════════════════════════════════════════ */
export async function fetchTelemetryRecent(
  limit: number = 20,
): Promise<ApiResponse<TelemetryEntry[]>> {
  return safeFetch(
    `/api/v1/telemetry/recent?limit=${limit}`,
    mockTelemetryEntries.slice(0, limit),
  );
}

/* ═══════════════════════════════════════════════════
   7. 近期觸發事件
   GET /api/v1/triggers/recent?limit=
   ═══════════════════════════════════════════════════ */
export async function fetchTriggersRecent(
  limit: number = 10,
): Promise<ApiResponse<TelemetryEntry[]>> {
  const triggerTypes = new Set([
    'vlm_triggered',
    'vlm_rejected',
    'safe_stop',
    'planner_override',
    'request_review',
  ]);
  const fallback = mockTelemetryEntries
    .filter((e) => triggerTypes.has(e.event_type))
    .slice(0, limit);
  return safeFetch(`/api/v1/triggers/recent?limit=${limit}`, fallback);
}

/* ═══════════════════════════════════════════════════
   8. 規劃器目前狀態
   GET /api/v1/planner/state
   ═══════════════════════════════════════════════════ */
export async function fetchPlannerState(): Promise<ApiResponse<PlannerAction>> {
  return safeFetch('/api/v1/planner/state', mockPlannerAction);
}

/* ═══════════════════════════════════════════════════
   9. 操作員審核提交
   POST /api/v1/operator/review
   ═══════════════════════════════════════════════════ */
export async function submitOperatorReview(
  review: OperatorReview,
): Promise<ApiResponse<void>> {
  return safeFetch<void>('/api/v1/operator/review', undefined as never, {
    method: 'POST',
    body: JSON.stringify(review),
  });
}

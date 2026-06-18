/**
 * MA-VLNA 共享 JSON Schema 型別定義
 * 記憶增強視覺語言導航代理系統 — 前端型別
 */

/* ─── 基礎型別 ─── */

/** 三維座標位置 */
export interface Position {
  x: number;
  y: number;
  z: number;
}

/** 二維邊界框 */
export interface BoundingBox {
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
}

/** 航點 */
export interface Waypoint {
  x: number;
  y: number;
  z: number;
  speed_mps: number;
  label?: string;
}

/* ─── VLM 推理輸出 ─── */

/** 危險物件 */
export interface Hazard {
  label: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  description: string;
  bounding_box?: BoundingBox;
}

/** 可通行區域 */
export interface NavigableRegion {
  region_id: string;
  description: string;
  confidence: number;
  direction: string;
}

/** 航點提示 */
export interface WaypointHint {
  direction: string;
  distance_m: number;
  description: string;
  confidence: number;
}

/** VLM 完整推理輸出 */
export interface VLMOutput {
  scene_summary: string;
  hazards: Hazard[];
  navigable_regions: NavigableRegion[];
  waypoint_hints: WaypointHint[];
  speed_hint: 'stop' | 'slow' | 'moderate' | 'maintain' | 'accelerate';
  must_not_do: string[];
  confidence: number;
}

/* ─── 遙測資料 ─── */

/** 事件類型列舉 */
export type EventType =
  | 'vlm_triggered'
  | 'vlm_completed'
  | 'vlm_rejected'
  | 'safe_stop'
  | 'request_review'
  | 'planner_override'
  | 'memory_replay'
  | 'speed_change'
  | 'route_deviation'
  | 'system_heartbeat';

/** 規劃器狀態列舉 */
export type PlannerState =
  | 'idle'
  | 'navigating'
  | 'vlm_reasoning'
  | 'executing_plan'
  | 'safe_stop'
  | 'awaiting_review'
  | 'replaying_memory';

/** 遙測記錄項目 */
export interface TelemetryEntry {
  vehicle_id: string;
  timestamp: string;
  event_type: EventType;
  planner_state: PlannerState;
  current_speed: number;
  position: Position;
  heading_deg: number;
  trigger_reason: string;
  vlm_active: boolean;
  safe_mode: boolean;
  current_action: string;
  details: string;
}

/* ─── 規劃器動作 ─── */

/** 規劃器動作指令 */
export interface PlannerAction {
  plan_id: string;
  timestamp: string;
  source: 'vlm' | 'memory_replay' | 'operator' | 'planner_default';
  waypoints: Waypoint[];
  action_sequence: string[];
  validated: boolean;
  vlm_proposal_accepted: boolean;
  rejection_reason: string | null;
}

/* ─── 場景記憶 ─── */

/** 場景記憶條目 */
export interface SceneMemoryEntry {
  scene_id: string;
  memory_id: string;
  vehicle_id: string;
  timestamp: string;
  similarity_score: number;
  is_replay_candidate: boolean;
  success_flag: boolean;
  semantic_summary: string;
  thumbnail_url: string;
  action_sequence: string[];
  outcome: string;
  replay_count: number;
  source_scene_id: string;
}

/* ─── 車輛狀態 ─── */

/** 車輛即時狀態 */
export interface VehicleStatus {
  vehicle_id: string;
  planner_state: PlannerState;
  current_speed: number;
  position_x: number;
  position_y: number;
  position_z: number;
  heading_deg: number;
  safe_mode: boolean;
  last_trigger_reason: string;
  vlm_active: boolean;
  current_action: string;
  updated_at: string;
}

/* ─── 偵測物件 ─── */

/** 物件偵測結果 */
export interface Detection {
  label: string;
  confidence: number;
  bounding_box: BoundingBox;
  track_id?: string;
}

/** 追蹤狀態 */
export interface Track {
  track_id: string;
  label: string;
  status: 'active' | 'lost' | 'tentative';
  age_frames: number;
  velocity_mps?: number;
}

/* ─── 場景日誌 ─── */

/** 完整場景日誌 */
export interface SceneLog {
  scene_id: string;
  vehicle_id: string;
  timestamp: string;
  frame_url: string;
  thumbnail_url: string;
  detections: Detection[];
  tracks: Track[];
  lane_state: string;
  free_space: string;
  trigger_reason: string;
  vlm_output: VLMOutput | null;
  planner_action: PlannerAction | null;
  planner_state: PlannerState;
  success_flag: boolean;
  outcome: string;
}

/* ─── API 回應封裝 ─── */

/** 統一 API 回應格式 */
export interface ApiResponse<T> {
  request_id: string;
  status: 'ok' | 'error';
  data: T | null;
  error_code: string | null;
  error_message: string | null;
  retryable: boolean;
}

/* ─── 操作員審核 ─── */

/** 操作員審核提交 */
export interface OperatorReview {
  scene_id: string;
  vehicle_id: string;
  operator_id: string;
  decision: 'approve' | 'reject' | 'modify';
  notes: string;
  modified_action?: PlannerAction;
}

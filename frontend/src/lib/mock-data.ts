/**
 * MA-VLNA 模擬資料
 * 用於前端面板展示的擬真測試資料，涵蓋所有儀表板面板
 */

import type {
  VehicleStatus,
  SceneLog,
  SceneMemoryEntry,
  TelemetryEntry,
  PlannerAction,
  VLMOutput,
  Detection,
  Track,
} from '@/types/schemas';

/* ─── 輔助函式：產生 ISO 時間戳記 ─── */
const ts = (minutesAgo: number): string => {
  const d = new Date(Date.now() - minutesAgo * 60_000);
  return d.toISOString();
};

/* ═══════════════════════════════════════════════════
   車輛即時狀態
   ═══════════════════════════════════════════════════ */

export const mockVehicleStatus: VehicleStatus = {
  vehicle_id: 'VLNA-ALPHA-07',
  planner_state: 'navigating',
  current_speed: 4.2,
  position_x: 127.35,
  position_y: -42.18,
  position_z: 0.12,
  heading_deg: 225.7,
  safe_mode: false,
  last_trigger_reason: 'novel_scene_detected',
  vlm_active: true,
  current_action: 'lane_follow_with_caution',
  updated_at: ts(0),
};

/* ═══════════════════════════════════════════════════
   VLM 推理輸出
   ═══════════════════════════════════════════════════ */

export const mockVLMOutput: VLMOutput = {
  scene_summary:
    '前方十字路口有行人正在過馬路，左側有一輛停放的貨車部分遮擋視線。右側車道暢通，路面乾燥。交通號誌為綠燈，但行人號誌正在倒數。建議減速並準備讓行。',
  hazards: [
    {
      label: '行人 (2人)',
      severity: 'high',
      description: '兩名行人正在前方斑馬線上由左向右行走，距離約15公尺',
      bounding_box: { x_min: 320, y_min: 280, x_max: 480, y_max: 520 },
    },
    {
      label: '停放貨車',
      severity: 'medium',
      description: '左側路邊停有大型貨車，遮擋部分前方視線',
      bounding_box: { x_min: 50, y_min: 200, x_max: 280, y_max: 480 },
    },
    {
      label: '施工路障',
      severity: 'low',
      description: '右前方50公尺處有施工警示錐',
    },
    {
      label: '逆向機車',
      severity: 'critical',
      description: '對向車道有機車疑似逆向行駛，距離約30公尺',
      bounding_box: { x_min: 580, y_min: 300, x_max: 650, y_max: 420 },
    },
  ],
  navigable_regions: [
    {
      region_id: 'nav-01',
      description: '目前車道前方（減速後可通行）',
      confidence: 0.82,
      direction: 'forward',
    },
    {
      region_id: 'nav-02',
      description: '右側車道（暢通，可變道）',
      confidence: 0.95,
      direction: 'right',
    },
    {
      region_id: 'nav-03',
      description: '左側車道（被貨車遮擋，不建議）',
      confidence: 0.31,
      direction: 'left',
    },
  ],
  waypoint_hints: [
    {
      direction: 'forward-right',
      distance_m: 8.5,
      description: '靠右行駛，避開行人後直行通過路口',
      confidence: 0.88,
    },
    {
      direction: 'forward',
      distance_m: 22.0,
      description: '通過路口後回到主車道',
      confidence: 0.76,
    },
  ],
  speed_hint: 'slow',
  must_not_do: [
    '禁止加速通過行人斑馬線',
    '禁止向左變道（視線遮擋）',
    '禁止鳴按喇叭催促行人',
  ],
  confidence: 0.87,
};

/* ═══════════════════════════════════════════════════
   規劃器動作
   ═══════════════════════════════════════════════════ */

export const mockPlannerAction: PlannerAction = {
  plan_id: 'plan-20260605-001',
  timestamp: ts(0.5),
  source: 'vlm',
  waypoints: [
    { x: 130.2, y: -40.5, z: 0.1, speed_mps: 2.0, label: '減速點' },
    { x: 135.8, y: -38.2, z: 0.1, speed_mps: 1.5, label: '讓行等待' },
    { x: 142.1, y: -35.0, z: 0.1, speed_mps: 3.5, label: '通過路口' },
    { x: 150.0, y: -32.8, z: 0.1, speed_mps: 4.5, label: '恢復巡航' },
  ],
  action_sequence: [
    'decelerate_to_2mps',
    'yield_to_pedestrians',
    'proceed_when_clear',
    'merge_right_lane',
    'resume_cruise_speed',
  ],
  validated: true,
  vlm_proposal_accepted: true,
  rejection_reason: null,
};

/* ═══════════════════════════════════════════════════
   偵測物件與追蹤資料
   ═══════════════════════════════════════════════════ */

const mockDetections: Detection[] = [
  {
    label: 'pedestrian',
    confidence: 0.96,
    bounding_box: { x_min: 340, y_min: 290, x_max: 400, y_max: 510 },
    track_id: 'trk-041',
  },
  {
    label: 'pedestrian',
    confidence: 0.93,
    bounding_box: { x_min: 400, y_min: 300, x_max: 470, y_max: 520 },
    track_id: 'trk-042',
  },
  {
    label: 'truck',
    confidence: 0.98,
    bounding_box: { x_min: 50, y_min: 200, x_max: 280, y_max: 480 },
    track_id: 'trk-033',
  },
  {
    label: 'motorcycle',
    confidence: 0.89,
    bounding_box: { x_min: 580, y_min: 300, x_max: 650, y_max: 420 },
    track_id: 'trk-055',
  },
  {
    label: 'traffic_light',
    confidence: 0.99,
    bounding_box: { x_min: 440, y_min: 80, x_max: 490, y_max: 160 },
  },
  {
    label: 'construction_cone',
    confidence: 0.85,
    bounding_box: { x_min: 620, y_min: 440, x_max: 660, y_max: 500 },
  },
];

const mockTracks: Track[] = [
  { track_id: 'trk-041', label: 'pedestrian', status: 'active', age_frames: 34, velocity_mps: 1.2 },
  { track_id: 'trk-042', label: 'pedestrian', status: 'active', age_frames: 28, velocity_mps: 1.1 },
  { track_id: 'trk-033', label: 'truck', status: 'active', age_frames: 120, velocity_mps: 0 },
  { track_id: 'trk-055', label: 'motorcycle', status: 'tentative', age_frames: 8, velocity_mps: 6.5 },
  { track_id: 'trk-048', label: 'car', status: 'lost', age_frames: 65, velocity_mps: 0 },
];

/* ═══════════════════════════════════════════════════
   場景日誌（多筆）
   ═══════════════════════════════════════════════════ */

export const mockSceneLogs: SceneLog[] = [
  {
    scene_id: 'scene-20260605-0421',
    vehicle_id: 'VLNA-ALPHA-07',
    timestamp: ts(0.5),
    frame_url: '/frames/scene-0421.jpg',
    thumbnail_url: '/frames/thumb-0421.jpg',
    detections: mockDetections,
    tracks: mockTracks,
    lane_state: 'two_lane_urban_intersection',
    free_space: 'forward: 12m (limited by pedestrians), right: 35m (clear), left: 5m (blocked by truck)',
    trigger_reason: 'novel_scene_detected',
    vlm_output: mockVLMOutput,
    planner_action: mockPlannerAction,
    planner_state: 'navigating',
    success_flag: true,
    outcome: 'safe_pass_completed',
  },
  {
    scene_id: 'scene-20260605-0418',
    vehicle_id: 'VLNA-ALPHA-07',
    timestamp: ts(3),
    frame_url: '/frames/scene-0418.jpg',
    thumbnail_url: '/frames/thumb-0418.jpg',
    detections: [
      {
        label: 'vehicle',
        confidence: 0.97,
        bounding_box: { x_min: 200, y_min: 250, x_max: 500, y_max: 450 },
        track_id: 'trk-039',
      },
    ],
    tracks: [
      { track_id: 'trk-039', label: 'vehicle', status: 'active', age_frames: 45, velocity_mps: 0 },
    ],
    lane_state: 'single_lane_residential',
    free_space: 'forward: 8m (blocked), right: 2m (curb), left: 3m (oncoming possible)',
    trigger_reason: 'obstacle_detected',
    vlm_output: {
      scene_summary: '前方車輛突然停車，單線道住宅區無法變道。需要完全停車等待。',
      hazards: [
        {
          label: '停止車輛',
          severity: 'high',
          description: '前方8公尺處車輛完全停止',
        },
      ],
      navigable_regions: [
        { region_id: 'nav-01', description: '前方（被阻擋）', confidence: 0.15, direction: 'forward' },
      ],
      waypoint_hints: [],
      speed_hint: 'stop',
      must_not_do: ['禁止嘗試從對向車道超車', '禁止倒車'],
      confidence: 0.94,
    },
    planner_action: {
      plan_id: 'plan-20260605-000',
      timestamp: ts(3),
      source: 'vlm',
      waypoints: [{ x: 127.0, y: -42.0, z: 0.1, speed_mps: 0, label: '停車等待' }],
      action_sequence: ['decelerate_to_stop', 'hold_position', 'wait_for_clearance'],
      validated: true,
      vlm_proposal_accepted: true,
      rejection_reason: null,
    },
    planner_state: 'executing_plan',
    success_flag: true,
    outcome: 'safe_stop_and_wait',
  },
  {
    scene_id: 'scene-20260605-0415',
    vehicle_id: 'VLNA-ALPHA-07',
    timestamp: ts(6),
    frame_url: '/frames/scene-0415.jpg',
    thumbnail_url: '/frames/thumb-0415.jpg',
    detections: [
      {
        label: 'dog',
        confidence: 0.78,
        bounding_box: { x_min: 350, y_min: 380, x_max: 420, y_max: 470 },
        track_id: 'trk-036',
      },
    ],
    tracks: [
      { track_id: 'trk-036', label: 'dog', status: 'tentative', age_frames: 5, velocity_mps: 2.8 },
    ],
    lane_state: 'two_lane_suburban',
    free_space: 'forward: 25m (animal crossing), right: 20m, left: 15m',
    trigger_reason: 'unusual_object_detected',
    vlm_output: {
      scene_summary: '偵測到疑似流浪動物（狗）正在橫穿道路，信心度中等。建議減速觀察。',
      hazards: [
        { label: '動物（狗）', severity: 'medium', description: '道路中央有動物移動中' },
      ],
      navigable_regions: [
        { region_id: 'nav-01', description: '前方（減速後可通行）', confidence: 0.72, direction: 'forward' },
        { region_id: 'nav-02', description: '右側空間', confidence: 0.88, direction: 'right' },
      ],
      waypoint_hints: [
        { direction: 'forward', distance_m: 15, description: '減速觀察動物動向', confidence: 0.7 },
      ],
      speed_hint: 'slow',
      must_not_do: ['禁止加速驚嚇動物'],
      confidence: 0.72,
    },
    planner_action: null,
    planner_state: 'vlm_reasoning',
    success_flag: true,
    outcome: 'animal_avoided',
  },
  {
    scene_id: 'scene-20260605-0410',
    vehicle_id: 'VLNA-ALPHA-07',
    timestamp: ts(11),
    frame_url: '/frames/scene-0410.jpg',
    thumbnail_url: '/frames/thumb-0410.jpg',
    detections: [],
    tracks: [],
    lane_state: 'highway_ramp',
    free_space: 'forward: 80m (clear), right: 40m, left: 40m',
    trigger_reason: 'periodic_scan',
    vlm_output: null,
    planner_action: {
      plan_id: 'plan-20260604-998',
      timestamp: ts(11),
      source: 'planner_default',
      waypoints: [
        { x: 100.0, y: -50.0, z: 0.1, speed_mps: 6.0 },
        { x: 110.0, y: -48.0, z: 0.1, speed_mps: 6.0 },
      ],
      action_sequence: ['maintain_speed', 'follow_lane'],
      validated: true,
      vlm_proposal_accepted: false,
      rejection_reason: null,
    },
    planner_state: 'navigating',
    success_flag: true,
    outcome: 'normal_cruise',
  },
  {
    scene_id: 'scene-20260605-0405',
    vehicle_id: 'VLNA-ALPHA-07',
    timestamp: ts(16),
    frame_url: '/frames/scene-0405.jpg',
    thumbnail_url: '/frames/thumb-0405.jpg',
    detections: [
      {
        label: 'bicycle',
        confidence: 0.91,
        bounding_box: { x_min: 500, y_min: 320, x_max: 580, y_max: 490 },
        track_id: 'trk-028',
      },
    ],
    tracks: [
      { track_id: 'trk-028', label: 'bicycle', status: 'active', age_frames: 42, velocity_mps: 3.2 },
    ],
    lane_state: 'bike_lane_adjacent',
    free_space: 'forward: 30m, right: 1.5m (cyclist), left: 12m',
    trigger_reason: 'proximity_alert',
    vlm_output: {
      scene_summary: '右側自行車道有騎士，距離過近需保持安全側向距離。',
      hazards: [
        { label: '自行車騎士', severity: 'high', description: '右側1.5公尺處有自行車同向行駛' },
      ],
      navigable_regions: [
        { region_id: 'nav-01', description: '前方左側偏移', confidence: 0.91, direction: 'forward-left' },
      ],
      waypoint_hints: [
        { direction: 'forward-left', distance_m: 5, description: '向左偏移保持側向距離', confidence: 0.9 },
      ],
      speed_hint: 'moderate',
      must_not_do: ['禁止靠右行駛', '禁止突然加速超越'],
      confidence: 0.91,
    },
    planner_action: {
      plan_id: 'plan-20260604-997',
      timestamp: ts(16),
      source: 'vlm',
      waypoints: [
        { x: 95.0, y: -52.0, z: 0.1, speed_mps: 3.5, label: '左偏' },
        { x: 100.0, y: -53.0, z: 0.1, speed_mps: 4.0, label: '安全超越' },
      ],
      action_sequence: ['shift_left_1m', 'maintain_moderate_speed', 'pass_cyclist', 'return_to_lane'],
      validated: false,
      vlm_proposal_accepted: false,
      rejection_reason: '側向安全距離不足 1.8m 最低要求',
    },
    planner_state: 'navigating',
    success_flag: false,
    outcome: 'vlm_proposal_rejected_insufficient_clearance',
  },
];

/* ═══════════════════════════════════════════════════
   場景記憶（Top-K 相似場景）
   ═══════════════════════════════════════════════════ */

export const mockSceneMemories: SceneMemoryEntry[] = [
  {
    scene_id: 'scene-20260605-0421',
    memory_id: 'mem-00142',
    vehicle_id: 'VLNA-ALPHA-07',
    timestamp: '2026-05-28T14:22:10Z',
    similarity_score: 0.94,
    is_replay_candidate: true,
    success_flag: true,
    semantic_summary: '類似十字路口行人穿越場景，成功減速讓行後通過',
    thumbnail_url: '/frames/mem-00142-thumb.jpg',
    action_sequence: ['decelerate', 'yield_pedestrians', 'proceed_clear'],
    outcome: 'safe_navigation_completed',
    replay_count: 3,
    source_scene_id: 'scene-20260528-0312',
  },
  {
    scene_id: 'scene-20260605-0421',
    memory_id: 'mem-00098',
    vehicle_id: 'VLNA-ALPHA-07',
    timestamp: '2026-05-20T09:15:30Z',
    similarity_score: 0.87,
    is_replay_candidate: true,
    success_flag: true,
    semantic_summary: '都市路口有行人與大型車輛同時出現，採取保守策略成功',
    thumbnail_url: '/frames/mem-00098-thumb.jpg',
    action_sequence: ['slow_approach', 'full_stop', 'wait_clear', 'proceed'],
    outcome: 'conservative_pass_success',
    replay_count: 1,
    source_scene_id: 'scene-20260520-0188',
  },
  {
    scene_id: 'scene-20260605-0421',
    memory_id: 'mem-00205',
    vehicle_id: 'VLNA-ALPHA-03',
    timestamp: '2026-06-01T16:45:00Z',
    similarity_score: 0.79,
    is_replay_candidate: false,
    success_flag: false,
    semantic_summary: '路口行人場景但未及時減速，觸發安全停車機制',
    thumbnail_url: '/frames/mem-00205-thumb.jpg',
    action_sequence: ['maintain_speed', 'late_brake', 'emergency_stop'],
    outcome: 'safe_stop_triggered',
    replay_count: 0,
    source_scene_id: 'scene-20260601-0399',
  },
  {
    scene_id: 'scene-20260605-0421',
    memory_id: 'mem-00178',
    vehicle_id: 'VLNA-ALPHA-07',
    timestamp: '2026-05-30T11:30:15Z',
    similarity_score: 0.72,
    is_replay_candidate: false,
    success_flag: true,
    semantic_summary: '夜間路口場景，有行人但光線不足，成功以低速通過',
    thumbnail_url: '/frames/mem-00178-thumb.jpg',
    action_sequence: ['slow_to_2mps', 'high_beam_check', 'creep_forward', 'clear'],
    outcome: 'low_visibility_safe_pass',
    replay_count: 2,
    source_scene_id: 'scene-20260530-0267',
  },
  {
    scene_id: 'scene-20260605-0421',
    memory_id: 'mem-00055',
    vehicle_id: 'VLNA-ALPHA-05',
    timestamp: '2026-05-15T08:00:45Z',
    similarity_score: 0.65,
    is_replay_candidate: false,
    success_flag: true,
    semantic_summary: '校區附近路口大量行人，需全停等待',
    thumbnail_url: '/frames/mem-00055-thumb.jpg',
    action_sequence: ['full_stop', 'wait_60s', 'proceed_when_clear'],
    outcome: 'patient_wait_success',
    replay_count: 5,
    source_scene_id: 'scene-20260515-0101',
  },
];

/* ═══════════════════════════════════════════════════
   遙測日誌（時間軸事件）
   ═══════════════════════════════════════════════════ */

export const mockTelemetryEntries: TelemetryEntry[] = [
  {
    vehicle_id: 'VLNA-ALPHA-07',
    timestamp: ts(0.2),
    event_type: 'vlm_triggered',
    planner_state: 'vlm_reasoning',
    current_speed: 4.2,
    position: { x: 127.35, y: -42.18, z: 0.12 },
    heading_deg: 225.7,
    trigger_reason: 'novel_scene_detected',
    vlm_active: true,
    safe_mode: false,
    current_action: 'vlm_inference_running',
    details: 'VLM 推理啟動：偵測到新穎場景（行人+路口組合）',
  },
  {
    vehicle_id: 'VLNA-ALPHA-07',
    timestamp: ts(0.5),
    event_type: 'vlm_completed',
    planner_state: 'executing_plan',
    current_speed: 3.8,
    position: { x: 128.1, y: -41.9, z: 0.12 },
    heading_deg: 225.5,
    trigger_reason: 'novel_scene_detected',
    vlm_active: false,
    safe_mode: false,
    current_action: 'lane_follow_with_caution',
    details: 'VLM 推理完成，信心度 0.87，規劃器已接受提案',
  },
  {
    vehicle_id: 'VLNA-ALPHA-07',
    timestamp: ts(1.5),
    event_type: 'speed_change',
    planner_state: 'executing_plan',
    current_speed: 2.0,
    position: { x: 129.5, y: -41.2, z: 0.12 },
    heading_deg: 225.3,
    trigger_reason: 'vlm_speed_hint',
    vlm_active: false,
    safe_mode: false,
    current_action: 'decelerating',
    details: '依據 VLM 建議減速至 2.0 m/s',
  },
  {
    vehicle_id: 'VLNA-ALPHA-07',
    timestamp: ts(3),
    event_type: 'safe_stop',
    planner_state: 'safe_stop',
    current_speed: 0,
    position: { x: 127.0, y: -42.0, z: 0.12 },
    heading_deg: 225.7,
    trigger_reason: 'obstacle_detected',
    vlm_active: false,
    safe_mode: true,
    current_action: 'holding_position',
    details: '前方車輛完全停止，安全停車啟動',
  },
  {
    vehicle_id: 'VLNA-ALPHA-07',
    timestamp: ts(5),
    event_type: 'memory_replay',
    planner_state: 'replaying_memory',
    current_speed: 0,
    position: { x: 127.0, y: -42.0, z: 0.12 },
    heading_deg: 225.7,
    trigger_reason: 'similar_scene_found',
    vlm_active: false,
    safe_mode: false,
    current_action: 'replaying_memory_action',
    details: '記憶回放：mem-00142（相似度 0.94）— 行人讓行策略',
  },
  {
    vehicle_id: 'VLNA-ALPHA-07',
    timestamp: ts(8),
    event_type: 'planner_override',
    planner_state: 'navigating',
    current_speed: 3.0,
    position: { x: 125.5, y: -43.0, z: 0.12 },
    heading_deg: 226.0,
    trigger_reason: 'safety_check_failed',
    vlm_active: false,
    safe_mode: false,
    current_action: 'override_in_progress',
    details: '規劃器覆寫 VLM 提案：側向安全距離不符合要求（<1.8m）',
  },
  {
    vehicle_id: 'VLNA-ALPHA-07',
    timestamp: ts(11),
    event_type: 'system_heartbeat',
    planner_state: 'navigating',
    current_speed: 6.0,
    position: { x: 110.0, y: -48.0, z: 0.12 },
    heading_deg: 220.0,
    trigger_reason: 'periodic_scan',
    vlm_active: false,
    safe_mode: false,
    current_action: 'cruise',
    details: '系統心跳 — 正常巡航中',
  },
  {
    vehicle_id: 'VLNA-ALPHA-07',
    timestamp: ts(14),
    event_type: 'vlm_rejected',
    planner_state: 'navigating',
    current_speed: 4.5,
    position: { x: 98.0, y: -51.5, z: 0.12 },
    heading_deg: 218.0,
    trigger_reason: 'proximity_alert',
    vlm_active: false,
    safe_mode: false,
    current_action: 'lane_follow',
    details: 'VLM 提案被拒絕：自行車超越方案安全距離不足',
  },
  {
    vehicle_id: 'VLNA-ALPHA-07',
    timestamp: ts(16),
    event_type: 'request_review',
    planner_state: 'awaiting_review',
    current_speed: 2.0,
    position: { x: 95.0, y: -52.0, z: 0.12 },
    heading_deg: 218.0,
    trigger_reason: 'vlm_low_confidence',
    vlm_active: false,
    safe_mode: false,
    current_action: 'awaiting_operator',
    details: '請求操作員審核：VLM 信心度低於閾值（0.65），場景複雜度高',
  },
  {
    vehicle_id: 'VLNA-ALPHA-07',
    timestamp: ts(20),
    event_type: 'route_deviation',
    planner_state: 'navigating',
    current_speed: 5.2,
    position: { x: 85.0, y: -55.0, z: 0.12 },
    heading_deg: 215.0,
    trigger_reason: 'route_recalculation',
    vlm_active: false,
    safe_mode: false,
    current_action: 'rerouting',
    details: '路線偏差偵測 — 因施工改道，重新規劃路徑',
  },
];

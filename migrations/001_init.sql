-- ============================================================
-- MA-VLNA — 初始化 Migration
-- 建立 pgvector 擴充、核心資料表與索引
-- ============================================================

-- 啟用 pgvector（場景向量記憶）
CREATE EXTENSION IF NOT EXISTS vector;

-- [可選] 啟用 PostGIS / pgRouting（地理路網規劃）
-- 若需要地理路網搜尋，取消以下註解：
-- CREATE EXTENSION IF NOT EXISTS postgis;
-- CREATE EXTENSION IF NOT EXISTS pgrouting;

-- 啟用 UUID 生成
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- Vehicle_Status：車輛 / Agent 即時狀態
-- 用途：telemetry 即時同步、前端 StatusPanel 展示
-- ============================================================
CREATE TABLE IF NOT EXISTS vehicle_status (
    vehicle_id      TEXT PRIMARY KEY,
    planner_state   TEXT NOT NULL DEFAULT 'idle',
    -- 'idle' | 'navigating' | 'stopped' | 'safe_stop' | 'deadlock' | 'waiting_review'
    current_speed   REAL NOT NULL DEFAULT 0.0,
    position_x      REAL DEFAULT 0.0,
    position_y      REAL DEFAULT 0.0,
    position_z      REAL DEFAULT 0.0,
    heading_deg     REAL DEFAULT 0.0,
    safe_mode       BOOLEAN NOT NULL DEFAULT FALSE,
    last_trigger_reason TEXT DEFAULT NULL,
    -- 觸發 VLM 的原因：'low_confidence' | 'tracker_unstable' | 'unknown_scene' | ...
    vlm_active      BOOLEAN NOT NULL DEFAULT FALSE,
    -- VLM Reasoner 是否正在介入
    current_action  TEXT DEFAULT 'none',
    -- 當前執行的 action：'forward' | 'turn_left' | 'stop' | 'wait' | ...
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- Scene_Logs：場景日誌
-- 用途：
--   - embedding 欄位用於向量記憶查詢（pgvector）
--   - detections / tracks 用於 replay 視覺重現
--   - vlm_output 用於 VLM 推理面板展示
--   - planner_action 用於 planner warm-start
--   - success_flag 用於記憶篩選（成功 / 失敗案例）
-- ============================================================
CREATE TABLE IF NOT EXISTS scene_logs (
    scene_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vehicle_id      TEXT NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 場景向量（用於向量記憶查詢）
    embedding       vector(768),

    -- 關鍵影格 URL（Supabase Storage）
    frame_url       TEXT DEFAULT NULL,
    thumbnail_url   TEXT DEFAULT NULL,

    -- Edge CV 感知輸出（用於 replay）
    detections      JSONB DEFAULT '[]'::jsonb,
    tracks          JSONB DEFAULT '[]'::jsonb,
    lane_state      TEXT DEFAULT 'unknown',
    free_space      JSONB DEFAULT '{}'::jsonb,

    -- 觸發資訊
    trigger_reason  TEXT DEFAULT NULL,
    trigger_details JSONB DEFAULT '{}'::jsonb,

    -- VLM 推理輸出（用於 VLM 面板展示與 replay）
    vlm_output      JSONB DEFAULT NULL,
    vlm_latency_ms  INTEGER DEFAULT NULL,

    -- 規劃器輸出（用於 planner warm-start）
    planner_action  JSONB DEFAULT NULL,
    planner_state   TEXT DEFAULT NULL,

    -- 結果標記（用於記憶篩選）
    success_flag    BOOLEAN DEFAULT NULL,
    outcome         TEXT DEFAULT NULL,

    -- 附加 metadata
    metadata        JSONB DEFAULT '{}'::jsonb
);

-- 場景向量索引（用於 top-k 相似場景查詢）
CREATE INDEX IF NOT EXISTS idx_scene_logs_embedding
    ON scene_logs USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 時間索引（用於 replay timeline）
CREATE INDEX IF NOT EXISTS idx_scene_logs_timestamp
    ON scene_logs (vehicle_id, timestamp DESC);

-- 觸發原因索引（用於 trigger 統計面板）
CREATE INDEX IF NOT EXISTS idx_scene_logs_trigger
    ON scene_logs (trigger_reason)
    WHERE trigger_reason IS NOT NULL;

-- ============================================================
-- Trajectory_Memory：軌跡記憶
-- 用途：
--   - embedding 用於 replay candidate 查詢
--   - action_sequence / waypoints 用於 planner warm-start
--   - success_flag 用於篩選成功案例（避免重複錯誤）
--   - semantic_summary 用於前端記憶面板展示
-- ============================================================
CREATE TABLE IF NOT EXISTS trajectory_memory (
    memory_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    scene_id          UUID REFERENCES scene_logs(scene_id) ON DELETE SET NULL,
    vehicle_id        TEXT NOT NULL,

    -- 場景向量（用於相似軌跡查詢）
    embedding         vector(768),

    -- 動作序列（用於 replay）
    action_sequence   JSONB NOT NULL DEFAULT '[]'::jsonb,
    waypoints         JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- 結果
    outcome           TEXT DEFAULT NULL,
    success_flag      BOOLEAN NOT NULL DEFAULT FALSE,
    replay_count      INTEGER NOT NULL DEFAULT 0,

    -- 語義摘要（用於前端展示）
    semantic_summary  TEXT DEFAULT NULL,

    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 軌跡向量索引
CREATE INDEX IF NOT EXISTS idx_trajectory_memory_embedding
    ON trajectory_memory USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 成功案例索引（用於 replay candidate 篩選）
CREATE INDEX IF NOT EXISTS idx_trajectory_memory_success
    ON trajectory_memory (vehicle_id, success_flag, created_at DESC)
    WHERE success_flag = TRUE;

-- ============================================================
-- Telemetry_Entries：遙測日誌表
-- ============================================================
CREATE TABLE IF NOT EXISTS telemetry_entries (
    entry_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vehicle_id  TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    payload     JSONB DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_telemetry_entries_timestamp
    ON telemetry_entries (vehicle_id, created_at DESC);

-- ============================================================
-- Trigger_Events：VLM 觸發事件表
-- ============================================================
CREATE TABLE IF NOT EXISTS trigger_events (
    event_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vehicle_id      TEXT NOT NULL,
    scene_id        UUID REFERENCES scene_logs(scene_id) ON DELETE SET NULL,
    trigger_reason  TEXT NOT NULL,
    trigger_score   REAL DEFAULT 0.0,
    trigger_details JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trigger_events_timestamp
    ON trigger_events (vehicle_id, created_at DESC);

-- ============================================================
-- Operator_Reviews：操作員人工介入審查表
-- ============================================================
CREATE TABLE IF NOT EXISTS operator_reviews (
    review_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vehicle_id  TEXT NOT NULL,
    scene_id    UUID REFERENCES scene_logs(scene_id) ON DELETE SET NULL,
    decision    TEXT NOT NULL,
    reason      TEXT DEFAULT NULL,
    reviewer_id TEXT DEFAULT 'system',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_operator_reviews_timestamp
    ON operator_reviews (vehicle_id, created_at DESC);

-- ============================================================
-- RPC 函式：場景向量相似度查詢
-- 用途：Backend API /api/memory/top-k 端點
-- ============================================================
CREATE OR REPLACE FUNCTION match_scene_memories(
    query_embedding vector(768),
    match_threshold REAL DEFAULT 0.5,
    match_count INTEGER DEFAULT 5,
    filter_vehicle_id TEXT DEFAULT NULL
)
RETURNS TABLE (
    scene_id UUID,
    vehicle_id TEXT,
    "timestamp" TIMESTAMPTZ,
    similarity REAL,
    frame_url TEXT,
    thumbnail_url TEXT,
    trigger_reason TEXT,
    vlm_output JSONB,
    planner_action JSONB,
    planner_state TEXT,
    success_flag BOOLEAN,
    outcome TEXT,
    semantic_summary TEXT,
    metadata JSONB
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        sl.scene_id,
        sl.vehicle_id,
        sl.timestamp,
        (1 - (sl.embedding <=> query_embedding))::REAL AS similarity,
        sl.frame_url,
        sl.thumbnail_url,
        sl.trigger_reason,
        sl.vlm_output,
        sl.planner_action,
        sl.planner_state,
        sl.success_flag,
        sl.outcome,
        (sl.metadata->>'semantic_summary')::TEXT AS semantic_summary,
        sl.metadata
    FROM scene_logs sl
    WHERE sl.embedding IS NOT NULL
      AND (filter_vehicle_id IS NULL OR sl.vehicle_id = filter_vehicle_id)
      AND (1 - (sl.embedding <=> query_embedding)) >= match_threshold
    ORDER BY sl.embedding <=> query_embedding ASC
    LIMIT match_count;
END;
$$;

-- ============================================================
-- RPC 函式：軌跡記憶相似度查詢（replay candidate）
-- 用途：SceneMemoryRetriever.get_replay_candidates()
-- ============================================================
CREATE OR REPLACE FUNCTION match_trajectory_memories(
    query_embedding vector(768),
    match_threshold REAL DEFAULT 0.5,
    match_count INTEGER DEFAULT 5,
    only_success BOOLEAN DEFAULT TRUE
)
RETURNS TABLE (
    memory_id UUID,
    scene_id UUID,
    vehicle_id TEXT,
    similarity REAL,
    action_sequence JSONB,
    waypoints JSONB,
    outcome TEXT,
    success_flag BOOLEAN,
    replay_count INTEGER,
    semantic_summary TEXT,
    created_at TIMESTAMPTZ
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        tm.memory_id,
        tm.scene_id,
        tm.vehicle_id,
        (1 - (tm.embedding <=> query_embedding))::REAL AS similarity,
        tm.action_sequence,
        tm.waypoints,
        tm.outcome,
        tm.success_flag,
        tm.replay_count,
        tm.semantic_summary,
        tm.created_at
    FROM trajectory_memory tm
    WHERE tm.embedding IS NOT NULL
      AND (NOT only_success OR tm.success_flag = TRUE)
      AND (1 - (tm.embedding <=> query_embedding)) >= match_threshold
    ORDER BY tm.embedding <=> query_embedding ASC
    LIMIT match_count;
END;
$$;

-- ============================================================
-- [可選] PostGIS 路網表（未來擴充）
-- ============================================================
-- CREATE TABLE IF NOT EXISTS road_network (
--     edge_id     SERIAL PRIMARY KEY,
--     source_node INTEGER NOT NULL,
--     target_node INTEGER NOT NULL,
--     cost        REAL NOT NULL,
--     geom        GEOMETRY(LineString, 4326)
-- );
-- CREATE INDEX IF NOT EXISTS idx_road_network_geom
--     ON road_network USING GIST (geom);

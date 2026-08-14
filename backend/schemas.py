"""
MA-VLNA Backend — Pydantic v2 資料模型

定義所有 API 請求 / 回應的資料結構，
嚴格對齊 shared/schemas/ 下的 JSON Schema 契約。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field
from pydantic.generics import GenericModel  # noqa: F401 — Pydantic v2 re-exports

T = TypeVar("T")


# ============================================================
# 共用列舉
# ============================================================

class HazardSeverity(str, Enum):
    """危險等級列舉"""
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class SpeedHint(str, Enum):
    """建議速度等級"""
    stop = "stop"
    slow = "slow"
    normal = "normal"


class PlannerSource(str, Enum):
    """規劃來源列舉"""
    local_planner = "local_planner"
    semantic_planner = "semantic_planner"
    memory_replay = "memory_replay"
    safe_stop = "safe_stop"
    operator_override = "operator_override"


class ActionType(str, Enum):
    """動作類型列舉"""
    forward = "forward"
    turn_left = "turn_left"
    turn_right = "turn_right"
    stop = "stop"
    wait = "wait"
    reverse = "reverse"
    slow_forward = "slow_forward"


class EventType(str, Enum):
    """遙測事件類型"""
    status_update = "status_update"
    vlm_triggered = "vlm_triggered"
    vlm_response = "vlm_response"
    vlm_timeout = "vlm_timeout"
    vlm_rejected = "vlm_rejected"
    planner_update = "planner_update"
    planner_deadlock = "planner_deadlock"
    planner_override = "planner_override"
    safe_stop = "safe_stop"
    request_review = "request_review"
    memory_replay = "memory_replay"
    memory_conflict = "memory_conflict"
    operator_decision = "operator_decision"
    seed_sample = "seed_sample"


class WaypointDirection(str, Enum):
    """航點方向提示"""
    forward = "forward"
    left = "left"
    right = "right"
    back = "back"
    stop = "stop"


class ReviewDecision(str, Enum):
    """操作員審查決策"""
    approve = "approve"
    reject = "reject"
    override = "override"


# ============================================================
# VLM Reasoner 輸出子模型
# ============================================================

class BBox(BaseModel):
    """邊界框座標"""
    x: float
    y: float
    w: float
    h: float


class Hazard(BaseModel):
    """危險物件 / 區域描述"""
    label: str = Field(..., description="危險標籤")
    severity: HazardSeverity = Field(..., description="危險等級")
    bbox: BBox | None = Field(default=None, description="邊界框（可選）")
    description: str | None = Field(default=None, description="附加描述")


class NavigableRegion(BaseModel):
    """可通行區域"""
    region_id: str = Field(..., description="區域識別碼")
    description: str = Field(..., description="區域描述")
    confidence: float | None = Field(default=None, ge=0, le=1, description="信心分數")


class WaypointHint(BaseModel):
    """語義航點提示"""
    hint: str = Field(..., description="航點描述")
    direction: WaypointDirection | None = Field(default=None, description="方向提示")
    distance_hint: str | None = Field(default=None, description="距離提示")
    priority: int | None = Field(default=None, ge=1, description="優先順序")


# ============================================================
# VLMOutput — VLM Reasoner 結構化輸出
# ============================================================

class VLMOutput(BaseModel):
    """
    VLM Reasoner 結構化推理結果。

    包含場景摘要、危險偵測、可通行區域、航點提示、速度建議、
    禁止行為清單與整體信心分數。由 Safety Gate 與 Planner 驗證後執行。
    """
    scene_summary: str = Field(..., description="場景自然語言摘要")
    reasoning_summary: str | None = Field(None, description="決策依據摘要")
    hazards: list[Hazard] = Field(default_factory=list, description="偵測到的危險物件或區域")
    navigable_regions: list[NavigableRegion] = Field(
        default_factory=list, description="可通行區域清單"
    )
    waypoint_hints: list[WaypointHint] = Field(
        default_factory=list, description="建議的航點提示"
    )
    speed_hint: SpeedHint = Field(..., description="建議速度等級")
    must_not_do: list[str] = Field(default_factory=list, description="必須避免的行為")
    confidence: float = Field(..., ge=0, le=1, description="VLM 信心分數")


# ============================================================
# TelemetryEntry — 遙測資料條目
# ============================================================

class Position(BaseModel):
    """三維座標"""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class TelemetryEntry(BaseModel):
    """
    遙測資料條目。

    記錄車輛狀態、觸發事件與規劃決策，
    用於監控面板即時展示與歷史回放。
    """
    vehicle_id: str = Field(..., description="車輛識別碼")
    timestamp: datetime = Field(..., description="事件時間戳")
    event_type: EventType = Field(..., description="事件類型")
    planner_state: str | None = Field(default=None, description="規劃器狀態")
    current_speed: float | None = Field(default=None, description="目前車速")
    position: Position | None = Field(default=None, description="目前位置")
    heading_deg: float | None = Field(default=None, description="航向角（度）")
    trigger_reason: str | None = Field(default=None, description="觸發原因")
    vlm_active: bool | None = Field(default=None, description="VLM 是否啟用")
    safe_mode: bool | None = Field(default=None, description="安全模式狀態")
    current_action: str | None = Field(default=None, description="當前執行動作")
    details: dict[str, Any] | None = Field(default=None, description="附加細節")


# ============================================================
# PlannerAction — 規劃器動作輸出
# ============================================================

class Waypoint(BaseModel):
    """規劃航點"""
    x: float
    y: float
    z: float = 0.0
    speed_limit: float | None = None
    action: str | None = None


class ActionStep(BaseModel):
    """單步動作"""
    action: ActionType = Field(..., description="動作類型")
    duration_sec: float = Field(..., description="持續時間（秒）")
    speed_mps: float | None = Field(default=None, description="速度（公尺/秒）")
    steering_deg: float | None = Field(default=None, description="轉向角度（度）")


class PlannerAction(BaseModel):
    """
    規劃器動作輸出。

    包含 waypoints、action sequence 與驗證狀態，
    可由 simulator adapter 直接執行。
    """
    plan_id: str = Field(..., description="規劃識別碼")
    timestamp: datetime = Field(..., description="規劃時間戳")
    source: PlannerSource = Field(..., description="規劃來源")
    waypoints: list[Waypoint] = Field(default_factory=list, description="航點序列")
    action_sequence: list[ActionStep] = Field(
        default_factory=list, description="動作序列"
    )
    validated: bool | None = Field(default=None, description="是否通過 Safety Gate 驗證")
    vlm_proposal_accepted: bool | None = Field(
        default=None, description="VLM 提案是否被接受"
    )
    rejection_reason: str | None = Field(default=None, description="拒絕原因")


# ============================================================
# SceneMemoryEntry — 場景記憶條目
# ============================================================

class SimpleAction(BaseModel):
    """簡化動作（用於記憶回放）"""
    action: str
    duration_sec: float | None = None


class SceneMemoryEntry(BaseModel):
    """
    場景記憶條目。

    用於 top-k 相似場景檢索、replay 候選評估與記憶面板展示，
    包含相似度分數、語義摘要與動作序列。
    """
    scene_id: str = Field(..., description="場景識別碼")
    memory_id: str | None = Field(default=None, description="記憶識別碼")
    vehicle_id: str = Field(..., description="車輛識別碼")
    timestamp: datetime = Field(..., description="場景時間戳")
    similarity_score: float | str | None = Field(default=None, description="餘弦相似度分數")
    is_replay_candidate: bool = Field(default=False, description="是否為 replay 候選")
    success_flag: bool | None = Field(default=None, description="場景結果是否成功")
    semantic_summary: str | None = Field(default=None, description="語義摘要")
    thumbnail_url: str | None = Field(default=None, description="縮圖 URL")
    action_sequence: list[SimpleAction] | None = Field(
        default=None, description="動作序列"
    )
    outcome: str | None = Field(default=None, description="場景結果描述")
    replay_count: int = Field(default=0, description="已 replay 次數")
    source_scene_id: str | None = Field(default=None, description="來源場景識別碼")


# ============================================================
# VehicleStatus — 車輛即時狀態
# ============================================================

class VehicleStatus(BaseModel):
    """
    車輛 / Agent 即時狀態。

    對應 vehicle_status 資料表，
    用於前端 StatusPanel 展示與遙測同步。
    """
    vehicle_id: str = Field(..., description="車輛識別碼")
    planner_state: str = Field(default="idle", description="規劃器狀態")
    current_speed: float = Field(default=0.0, description="目前車速")
    position_x: float = Field(default=0.0, description="X 座標")
    position_y: float = Field(default=0.0, description="Y 座標")
    position_z: float = Field(default=0.0, description="Z 座標")
    heading_deg: float = Field(default=0.0, description="航向角（度）")
    safe_mode: bool = Field(default=False, description="安全模式狀態")
    last_trigger_reason: str | None = Field(default=None, description="最近觸發原因")
    vlm_active: bool = Field(default=False, description="VLM 是否介入中")
    current_action: str = Field(default="none", description="當前執行動作")
    updated_at: datetime | None = Field(default=None, description="最後更新時間")


# ============================================================
# SceneLog — 場景日誌（完整）
# ============================================================

class SceneLog(BaseModel):
    """
    場景日誌完整記錄。

    包含場景影像、Edge CV 感知輸出、VLM 推理結果、
    規劃器決策與結果標記。對應 scene_logs 資料表。
    """
    scene_id: str = Field(..., description="場景識別碼")
    vehicle_id: str = Field(..., description="車輛識別碼")
    timestamp: datetime = Field(..., description="場景時間戳")
    frame_url: str | None = Field(default=None, description="關鍵影格 URL")
    thumbnail_url: str | None = Field(default=None, description="縮圖 URL")
    detections: list[dict[str, Any]] = Field(
        default_factory=list, description="偵測結果"
    )
    tracks: list[dict[str, Any]] = Field(
        default_factory=list, description="追蹤結果"
    )
    lane_state: str | None = Field(default="unknown", description="車道狀態")
    free_space: dict[str, Any] = Field(
        default_factory=dict, description="可行駛空間"
    )
    trigger_reason: str | None = Field(default=None, description="觸發原因")
    trigger_details: dict[str, Any] = Field(
        default_factory=dict, description="觸發細節"
    )
    vlm_output: VLMOutput | dict[str, Any] | None = Field(
        default=None, description="VLM 推理輸出"
    )
    vlm_latency_ms: int | None = Field(default=None, description="VLM 延遲（毫秒）")
    planner_action: PlannerAction | dict[str, Any] | None = Field(
        default=None, description="規劃器動作"
    )
    planner_state: str | None = Field(default=None, description="規劃器狀態")
    success_flag: bool | None = Field(default=None, description="場景結果是否成功")
    outcome: str | None = Field(default=None, description="結果描述")
    metadata: dict[str, Any] = Field(default_factory=dict, description="附加 metadata")


# ============================================================
# ReplayData — 場景回放資料包
# ============================================================

class ReplayData(BaseModel):
    """
    場景回放資料包。

    聚合場景日誌、軌跡記憶與相關場景，
    供前端 Replay 面板完整重現場景。
    """
    scene_log: SceneLog = Field(..., description="完整場景日誌")
    trajectory_memory: list[dict[str, Any]] = Field(
        default_factory=list, description="關聯軌跡記憶"
    )
    related_scenes: list[SceneLog] = Field(
        default_factory=list, description="相關場景列表"
    )


# ============================================================
# OperatorReviewRequest — 操作員審查請求
# ============================================================

class OperatorReviewRequest(BaseModel):
    """
    操作員審查決策請求。

    允許人類操作員對場景做出 approve / reject / override 決策，
    並附加備註或覆寫動作。
    """
    scene_id: str = Field(..., description="待審查的場景識別碼")
    decision: ReviewDecision = Field(..., description="審查決策")
    operator_notes: str | None = Field(default=None, description="操作員備註")
    override_action: str | None = Field(
        default=None,
        description="覆寫動作（僅 decision=override 時需要）",
    )


# ============================================================
# ApiResponse[T] — 統一 API 回應包裝
# ============================================================

class ApiResponse(BaseModel, Generic[T]):
    """
    統一 API 回應包裝器。

    所有端點均透過此包裝器回傳，確保一致的回應格式：
    - request_id: 唯一請求識別碼（自動生成 UUID）
    - status: success | error
    - data: 回應資料（泛型）
    - error_code / error_message: 錯誤資訊（僅錯誤時填入）
    - retryable: 是否可重試
    """
    request_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="唯一請求識別碼",
    )
    status: str = Field(default="success", description="回應狀態 (success|error)")
    data: T | None = Field(default=None, description="回應資料")
    error_code: str | None = Field(default=None, description="錯誤碼")
    error_message: str | None = Field(default=None, description="錯誤訊息")
    retryable: bool = Field(default=False, description="是否可重試")

    @classmethod
    def success(cls, data: T) -> "ApiResponse[T]":
        """建立成功回應"""
        return cls(status="success", data=data)

    @classmethod
    def error(
        cls,
        error_code: str,
        error_message: str,
        retryable: bool = False,
    ) -> "ApiResponse[None]":
        """建立錯誤回應"""
        return cls(
            status="error",
            data=None,
            error_code=error_code,
            error_message=error_message,
            retryable=retryable,
        )

"""
核心設定模組 — 統一讀取 .env 環境變數與 agent_config.yaml 設定檔，
並透過巢狀 dataclass 將設定傳遞給各子系統。

同時定義 Pydantic v2 模型，鏡像 shared/schemas/ 下的四份 JSON Schema：
  - VLMOutput
  - TelemetryEntry
  - PlannerAction
  - SceneMemoryEntry
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ── 定位專案根目錄與設定檔 ──────────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent          # workers/core/
_WORKERS_DIR = _THIS_DIR.parent                       # workers/
_PROJECT_ROOT = _WORKERS_DIR.parent                   # 專案根目錄

_ENV_PATH = _PROJECT_ROOT / "config" / ".env"
_YAML_PATH = _PROJECT_ROOT / "config" / "agent_config.yaml"


# ════════════════════════════════════════════════════════════════
# 子系統 Dataclass 設定
# ════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class SupabaseConfig:
    """Supabase 連線與資料表設定。"""
    url: str = ""
    key: str = ""
    storage_bucket: str = "scene-frames"
    vehicle_status_table: str = "vehicle_status"
    scene_logs_table: str = "scene_logs"
    trajectory_memory_table: str = "trajectory_memory"


@dataclass(frozen=True)
class VLMConfig:
    """VLM Reasoner（OpenAI-compatible）相關設定。"""
    provider: str = "openai_compatible"
    api_base: str = "http://localhost:8000/v1"
    model: str = ""                         # 從 .env 讀取，絕不寫死
    api_key: str = "optional"
    timeout_sec: float = 30.0
    max_retries: int = 2
    confidence_threshold: float = 0.4
    temperature: float = 0.2
    max_tokens: int = 1024


@dataclass(frozen=True)
class EmbeddingConfig:
    """Embedding 模型設定。"""
    model_name: str = ""                    # 從 .env 讀取
    dimension: int = 768


@dataclass(frozen=True)
class CameraConfig:
    """攝影機 / 影像來源設定。"""
    source: str = "0"                       # "0" = webcam, 或影片路徑
    width: int = 1280
    height: int = 720


@dataclass(frozen=True)
class CarlaConfig:
    """
    CARLA closed-loop 模擬設定。

    CARLA 是 Phase 11 的 optional runtime，不應成為一般 mock/webcam
    開發的硬依賴。所有值都可由 .env 或 agent_config.yaml 覆寫。
    """
    host: str = "127.0.0.1"
    port: int = 2000
    timeout_sec: float = 10.0
    town: str = ""
    synchronous_mode: bool = True
    fixed_delta_seconds: float = 0.05
    max_substep_delta_time: float = 0.01
    max_substeps: int = 10
    ego_blueprint: str = "vehicle.tesla.model3"
    spawn_point_index: int = 0
    camera_width: int = 1280
    camera_height: int = 720
    camera_fov: float = 90.0
    camera_x: float = 1.6
    camera_y: float = 0.0
    camera_z: float = 1.7
    camera_pitch: float = 0.0
    control_hold_ticks: int = 1
    max_control_speed_mps: float = 8.0
    steer_gain: float = 1.0
    throttle_gain: float = 0.7
    brake_gain: float = 1.0


@dataclass(frozen=True)
class TriggerConfig:
    """VLM 觸發策略設定。"""
    low_confidence_threshold: float = 0.45
    tracker_instability_window: int = 10
    unknown_scene_threshold: float = 0.55
    planner_deadlock_count: int = 5
    cooldown_sec: float = 5.0
    max_pending_requests: int = 2
    force_interval_frames: int = 0


@dataclass(frozen=True)
class PlannerConfig:
    """路徑規劃器設定。"""
    algorithm: str = "a_star"
    max_waypoints: int = 20
    safety_margin_m: float = 1.5
    replan_interval_sec: float = 1.0
    deadlock_threshold: int = 5
    global_enabled: bool = False
    waypoint_graph_file: str = ""


@dataclass(frozen=True)
class MemoryConfig:
    """場景記憶設定。"""
    top_k: int = 5
    similarity_threshold: float = 0.82
    replay_min_similarity: float = 0.88
    replay_require_success: bool = True
    conflict_check_enabled: bool = True
    max_memory_entries: int = 10000


@dataclass(frozen=True)
class SafetyConfig:
    """安全閘門設定。"""
    reject_low_confidence: bool = True
    confidence_floor: float = 0.3
    max_speed_hint: str = "normal"
    forbidden_actions: list[str] = field(default_factory=list)
    require_planner_validation: bool = True


@dataclass(frozen=True)
class TelemetryConfig:
    """遙測發佈設定。"""
    publish_interval_sec: float = 1.0
    batch_size: int = 10
    async_writes: bool = True


@dataclass(frozen=True)
class FallbackConfig:
    """保守策略（fallback）設定。"""
    on_vlm_timeout: str = "stop_and_wait"
    on_vlm_low_confidence: str = "request_review"
    on_planner_reject: str = "stop_and_log"
    on_memory_conflict: str = "block_replay"
    on_network_unavailable: str = "local_conservative"
    safe_stop_decel_mps2: float = 3.0


@dataclass(frozen=True)
class PerceptionConfig:
    """邊緣感知設定。"""
    backend: str = "dummy"
    model_name: str = "dummy"
    confidence_threshold: float = 0.5
    yolov9_source_root_env: str = "YOLOV9_ROOT"
    yolov9_weights_env: str = "YOLOV9_WEIGHTS"
    yolov9_profile: str = "baseline"
    yolov9_weights_override: str | None = None
    yolov9_default_img_size: int = 640
    yolov9_confidence_threshold: float = 0.25
    yolov9_iou_threshold: float = 0.45
    yolov9_device: str = "auto"
    yolov9_half: bool = False
    yolov9_warmup_runs: int = 0
    yolov9_forward_only_profile: bool = False
    rtdetr_weights_override: str | None = None
    rtdetr_model_hint: str = "rtdetr-l.pt"
    rtdetr_device: str = "auto"
    rtdetr_img_size: int | None = None


# ════════════════════════════════════════════════════════════════
# 頂層 AgentConfig — 匯集所有子設定
# ════════════════════════════════════════════════════════════════

@dataclass
class AgentConfig:
    """
    統一代理設定 — 從 .env 與 agent_config.yaml 載入後提供給所有模組。

    使用方式：
        cfg = AgentConfig.load()
    """
    # 基本
    agent_id: str = "vehicle-001"
    mode: str = "simulator"
    main_loop_hz: int = 10
    embedding_cache_ttl_sec: float = 2.0

    # 子設定
    supabase: SupabaseConfig = field(default_factory=SupabaseConfig)
    vlm: VLMConfig = field(default_factory=VLMConfig)
    perception: PerceptionConfig = field(default_factory=PerceptionConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    carla: CarlaConfig = field(default_factory=CarlaConfig)
    trigger: TriggerConfig = field(default_factory=TriggerConfig)
    planner: PlannerConfig = field(default_factory=PlannerConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    fallback: FallbackConfig = field(default_factory=FallbackConfig)

    # ── 工廠方法 ────────────────────────────────────────────────
    @classmethod
    def load(
        cls,
        env_path: Path | None = None,
        yaml_path: Path | None = None,
    ) -> "AgentConfig":
        """
        從 .env 與 agent_config.yaml 載入設定並回傳 AgentConfig 實例。

        優先權：環境變數 > .env 檔案 > YAML > 預設值。
        """
        env_p = env_path or _ENV_PATH
        yaml_p = yaml_path or _YAML_PATH

        # 讀取 .env（不覆蓋已設定的環境變數）
        if env_p.exists():
            load_dotenv(dotenv_path=env_p, override=False)
            logger.info("已載入 .env 檔案: %s", env_p)
        else:
            logger.warning(".env 檔案不存在: %s — 僅使用環境變數與預設值", env_p)

        # 讀取 YAML
        yaml_data: dict[str, Any] = {}
        if yaml_p.exists():
            with open(yaml_p, "r", encoding="utf-8") as fh:
                yaml_data = yaml.safe_load(fh) or {}
            logger.info("已載入 YAML 設定: %s", yaml_p)
        else:
            logger.warning("YAML 設定檔不存在: %s — 僅使用環境變數與預設值", yaml_p)

        # 輔助函式：優先取環境變數，其次 YAML nested path，否則 default
        def _env(key: str, default: Any = None) -> Any:
            return os.getenv(key, default)

        def _yaml_nested(path: str, default: Any = None) -> Any:
            """依據 dot-separated 路徑存取 YAML 巢狀值。"""
            parts = path.split(".")
            node: Any = yaml_data
            for p in parts:
                if isinstance(node, dict):
                    node = node.get(p)
                else:
                    return default
            return node if node is not None else default

        def _env_bool(key: str, default: bool) -> bool:
            """讀取布林環境變數，支援 true/false/1/0/yes/no。"""
            raw = os.getenv(key)
            if raw is None:
                return bool(default)
            return raw.strip().lower() in {"1", "true", "yes", "y", "on"}

        # 組合子設定
        agent_section = yaml_data.get("agent", {}) or {}

        supabase_cfg = SupabaseConfig(
            url=_env("SUPABASE_URL", ""),
            key=_env("SUPABASE_KEY", ""),
            storage_bucket=_env("SUPABASE_STORAGE_BUCKET", "scene-frames"),
            vehicle_status_table=_env("VEHICLE_STATUS_TABLE", "vehicle_status"),
            scene_logs_table=_env("SCENE_LOGS_TABLE", "scene_logs"),
            trajectory_memory_table=_env("TRAJECTORY_MEMORY_TABLE", "trajectory_memory"),
        )

        vlm_cfg = VLMConfig(
            provider=_env("VLM_PROVIDER", _yaml_nested("vlm.provider", "openai_compatible")),
            api_base=_env("VLM_API_BASE", "http://localhost:8000/v1"),
            model=_env("VLM_MODEL", ""),
            api_key=_env("VLM_API_KEY", "optional"),
            timeout_sec=float(_env("VLM_TIMEOUT_SEC", _yaml_nested("vlm.timeout_sec", 30))),
            max_retries=int(_env("VLM_MAX_RETRIES", _yaml_nested("vlm.max_retries", 2))),
            confidence_threshold=float(
                _env("VLM_CONFIDENCE_THRESHOLD",
                     _yaml_nested("vlm.confidence_threshold", 0.4))
            ),
            temperature=float(_yaml_nested("vlm.temperature", 0.2)),
            max_tokens=int(_yaml_nested("vlm.max_tokens", 1024)),
        )

        perception_cfg = PerceptionConfig(
            backend=_env("PERCEPTION_BACKEND", _yaml_nested("perception.backend", "dummy")),
            model_name=_env("DETECTION_MODEL", _yaml_nested("perception.model_name", "yolov8n.pt")),
            confidence_threshold=float(_env("PERCEPTION_CONFIDENCE", _yaml_nested("perception.confidence_threshold", 0.5))),
            yolov9_source_root_env=_env("YOLOV9_SOURCE_ROOT_ENV", _yaml_nested("perception.yolov9.source_root_env", "YOLOV9_ROOT")),
            yolov9_weights_env=_env("YOLOV9_WEIGHTS_ENV", _yaml_nested("perception.yolov9.weights_env", "YOLOV9_WEIGHTS")),
            yolov9_profile=_env("YOLOV9_PROFILE", _yaml_nested("perception.yolov9.profile", "baseline")),
            yolov9_weights_override=_env("YOLOV9_WEIGHTS_OVERRIDE", _yaml_nested("perception.yolov9.weights_override", None)),
            yolov9_default_img_size=int(_env("YOLOV9_DEFAULT_IMG_SIZE", _yaml_nested("perception.yolov9.default_img_size", 640))),
            yolov9_confidence_threshold=float(_env("YOLOV9_CONFIDENCE_THRESHOLD", _yaml_nested("perception.yolov9.confidence_threshold", 0.25))),
            yolov9_iou_threshold=float(_env("YOLOV9_IOU_THRESHOLD", _yaml_nested("perception.yolov9.iou_threshold", 0.45))),
            yolov9_device=_env("YOLOV9_DEVICE", _yaml_nested("perception.yolov9.device", "auto")),
            yolov9_half=_env_bool("YOLOV9_HALF", bool(_yaml_nested("perception.yolov9.half", False))),
            yolov9_warmup_runs=int(_env("YOLOV9_WARMUP_RUNS", _yaml_nested("perception.yolov9.warmup_runs", 0))),
            yolov9_forward_only_profile=_env_bool(
                "YOLOV9_FORWARD_ONLY_PROFILE",
                bool(_yaml_nested("perception.yolov9.forward_only_profile", False)),
            ),
            rtdetr_weights_override=_env("RTDETR_WEIGHTS", _yaml_nested("perception.rtdetr.weights", None)),
            rtdetr_model_hint=_env("RTDETR_MODEL_HINT", _yaml_nested("perception.rtdetr.model_hint", "rtdetr-l.pt")),
            rtdetr_device=_env("RTDETR_DEVICE", _yaml_nested("perception.rtdetr.device", "auto")),
            rtdetr_img_size=(
                int(_env("RTDETR_IMG_SIZE", _yaml_nested("perception.rtdetr.img_size", 0))) or None
            ),
        )

        embedding_cfg = EmbeddingConfig(
            model_name=_env("EMBEDDING_MODEL_NAME", ""),
            dimension=int(_env("EMBEDDING_DIMENSION", 768)),
        )

        camera_cfg = CameraConfig(
            source=_env("CAMERA_SOURCE", "0"),
            width=int(_env("CAMERA_WIDTH", 1280)),
            height=int(_env("CAMERA_HEIGHT", 720)),
        )

        carla_section = yaml_data.get("carla", {}) or {}
        carla_cfg = CarlaConfig(
            host=str(_env("CARLA_HOST", carla_section.get("host", "127.0.0.1"))),
            port=int(_env("CARLA_PORT", carla_section.get("port", 2000))),
            timeout_sec=float(_env("CARLA_TIMEOUT_SEC", carla_section.get("timeout_sec", 10.0))),
            town=str(_env("CARLA_TOWN", carla_section.get("town", ""))),
            synchronous_mode=_env_bool(
                "CARLA_SYNC_MODE",
                bool(carla_section.get("synchronous_mode", True)),
            ),
            fixed_delta_seconds=float(
                _env("CARLA_FIXED_DELTA_SECONDS", carla_section.get("fixed_delta_seconds", 0.05))
            ),
            max_substep_delta_time=float(
                _env("CARLA_MAX_SUBSTEP_DELTA_TIME", carla_section.get("max_substep_delta_time", 0.01))
            ),
            max_substeps=int(_env("CARLA_MAX_SUBSTEPS", carla_section.get("max_substeps", 10))),
            ego_blueprint=str(
                _env("CARLA_EGO_BLUEPRINT", carla_section.get("ego_blueprint", "vehicle.tesla.model3"))
            ),
            spawn_point_index=int(
                _env("CARLA_SPAWN_POINT_INDEX", carla_section.get("spawn_point_index", 0))
            ),
            camera_width=int(_env("CARLA_CAMERA_WIDTH", carla_section.get("camera_width", 1280))),
            camera_height=int(_env("CARLA_CAMERA_HEIGHT", carla_section.get("camera_height", 720))),
            camera_fov=float(_env("CARLA_CAMERA_FOV", carla_section.get("camera_fov", 90.0))),
            camera_x=float(_env("CARLA_CAMERA_X", carla_section.get("camera_x", 1.6))),
            camera_y=float(_env("CARLA_CAMERA_Y", carla_section.get("camera_y", 0.0))),
            camera_z=float(_env("CARLA_CAMERA_Z", carla_section.get("camera_z", 1.7))),
            camera_pitch=float(_env("CARLA_CAMERA_PITCH", carla_section.get("camera_pitch", 0.0))),
            control_hold_ticks=int(
                _env("CARLA_CONTROL_HOLD_TICKS", carla_section.get("control_hold_ticks", 1))
            ),
            max_control_speed_mps=float(
                _env("CARLA_MAX_CONTROL_SPEED_MPS", carla_section.get("max_control_speed_mps", 8.0))
            ),
            steer_gain=float(_env("CARLA_STEER_GAIN", carla_section.get("steer_gain", 1.0))),
            throttle_gain=float(_env("CARLA_THROTTLE_GAIN", carla_section.get("throttle_gain", 0.7))),
            brake_gain=float(_env("CARLA_BRAKE_GAIN", carla_section.get("brake_gain", 1.0))),
        )

        trigger_section = yaml_data.get("trigger_policy", {}) or {}
        trigger_cfg = TriggerConfig(
            low_confidence_threshold=float(
                trigger_section.get("low_confidence_threshold", 0.45)
            ),
            tracker_instability_window=int(
                trigger_section.get("tracker_instability_window", 10)
            ),
            unknown_scene_threshold=float(
                _env("UNKNOWN_SCENE_THRESHOLD",
                     trigger_section.get("unknown_scene_threshold", 0.55))
            ),
            planner_deadlock_count=int(
                trigger_section.get("planner_deadlock_count", 5)
            ),
            cooldown_sec=float(trigger_section.get("cooldown_sec", 5.0)),
            max_pending_requests=int(trigger_section.get("max_pending_requests", 2)),
        )

        planner_section = _yaml_nested("planner.local", {}) or {}
        planner_cfg = PlannerConfig(
            algorithm=planner_section.get("algorithm", "a_star"),
            max_waypoints=int(_env("PLANNER_MAX_WAYPOINTS",
                                   planner_section.get("max_waypoints", 20))),
            safety_margin_m=float(_env("PLANNER_SAFETY_MARGIN",
                                       planner_section.get("safety_margin_m", 1.5))),
            replan_interval_sec=float(planner_section.get("replan_interval_sec", 1.0)),
            deadlock_threshold=int(_env("PLANNER_DEADLOCK_THRESHOLD",
                                        planner_section.get("deadlock_threshold", 5))),
            global_enabled=bool(_yaml_nested("planner.global.enabled", False)),
            waypoint_graph_file=str(_yaml_nested("planner.global.waypoint_graph_file", "")),
        )

        memory_section = yaml_data.get("memory", {}) or {}
        memory_cfg = MemoryConfig(
            top_k=int(_env("MEMORY_TOP_K", memory_section.get("top_k", 5))),
            similarity_threshold=float(
                _env("SCENE_SIMILARITY_THRESHOLD",
                     memory_section.get("similarity_threshold", 0.82))
            ),
            replay_min_similarity=float(memory_section.get("replay_min_similarity", 0.88)),
            replay_require_success=bool(memory_section.get("replay_require_success", True)),
            conflict_check_enabled=bool(memory_section.get("conflict_check_enabled", True)),
            max_memory_entries=int(memory_section.get("max_memory_entries", 10000)),
        )

        safety_section = yaml_data.get("safety_gate", {}) or {}
        safety_cfg = SafetyConfig(
            reject_low_confidence=bool(safety_section.get("reject_low_confidence", True)),
            confidence_floor=float(safety_section.get("confidence_floor", 0.3)),
            max_speed_hint=str(safety_section.get("max_speed_hint", "normal")),
            forbidden_actions=list(safety_section.get("forbidden_actions", [])),
            require_planner_validation=bool(
                safety_section.get("require_planner_validation", True)
            ),
        )

        telemetry_section = yaml_data.get("telemetry", {}) or {}
        telemetry_cfg = TelemetryConfig(
            publish_interval_sec=float(telemetry_section.get("publish_interval_sec", 1.0)),
            batch_size=int(telemetry_section.get("batch_size", 10)),
            async_writes=bool(telemetry_section.get("async_writes", True)),
        )

        fallback_section = yaml_data.get("fallback", {}) or {}
        fallback_cfg = FallbackConfig(
            on_vlm_timeout=str(fallback_section.get("on_vlm_timeout", "stop_and_wait")),
            on_vlm_low_confidence=str(
                fallback_section.get("on_vlm_low_confidence", "request_review")
            ),
            on_planner_reject=str(fallback_section.get("on_planner_reject", "stop_and_log")),
            on_memory_conflict=str(fallback_section.get("on_memory_conflict", "block_replay")),
            on_network_unavailable=str(
                fallback_section.get("on_network_unavailable", "local_conservative")
            ),
            safe_stop_decel_mps2=float(
                fallback_section.get("safe_stop_decel_mps2", 3.0)
            ),
        )

        config = cls(
            agent_id=_env("VEHICLE_ID", agent_section.get("id", "vehicle-001")),
            mode=str(agent_section.get("mode", "simulator")),
            main_loop_hz=int(agent_section.get("main_loop_hz", 10)),
            embedding_cache_ttl_sec=float(
                agent_section.get("embedding_cache_ttl_sec", 2.0)
            ),
            supabase=supabase_cfg,
            vlm=vlm_cfg,
            perception=perception_cfg,
            embedding=embedding_cfg,
            camera=camera_cfg,
            carla=carla_cfg,
            trigger=trigger_cfg,
            planner=planner_cfg,
            memory=memory_cfg,
            safety=safety_cfg,
            telemetry=telemetry_cfg,
            fallback=fallback_cfg,
        )
        logger.info("AgentConfig 載入完成 — agent_id=%s, mode=%s", config.agent_id, config.mode)
        return config


# ════════════════════════════════════════════════════════════════
# Pydantic v2 模型 — 鏡像 shared/schemas/*.json
# ════════════════════════════════════════════════════════════════

# ── VLM Output ──────────────────────────────────────────────────

class HazardBBox(BaseModel):
    """危險物件包圍框。"""
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0


class Hazard(BaseModel):
    """VLM 偵測到的危險項目。"""
    label: str
    severity: Literal["low", "medium", "high", "critical"]
    bbox: HazardBBox | None = None
    description: str | None = None


class NavigableRegion(BaseModel):
    """可通行區域描述。"""
    region_id: str
    description: str
    confidence: float | None = None


class WaypointHint(BaseModel):
    """VLM 建議的語義航點提示。"""
    hint: str
    direction: Literal["forward", "left", "right", "back", "stop"] | None = None
    distance_hint: str | None = None
    priority: int | None = None


class VLMOutput(BaseModel):
    """
    VLM Reasoner 結構化輸出 — 對應 vlm_output_schema.json。
    經 Safety Gate 與 Planner 驗證後才可執行。
    """
    scene_summary: str
    reasoning_summary: str | None = None
    hazards: list[Hazard] = Field(default_factory=list)
    navigable_regions: list[NavigableRegion] = Field(default_factory=list)
    waypoint_hints: list[WaypointHint] = Field(default_factory=list)
    speed_hint: Literal["stop", "slow", "normal"]
    must_not_do: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


# ── Telemetry Entry ─────────────────────────────────────────────

class TelemetryPosition(BaseModel):
    """遙測位置座標。"""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class TelemetryEntry(BaseModel):
    """遙測資料條目 — 對應 telemetry_schema.json。"""
    vehicle_id: str
    timestamp: str
    event_type: Literal[
        "status_update",
        "vlm_triggered",
        "vlm_response",
        "vlm_timeout",
        "vlm_rejected",
        "planner_update",
        "planner_deadlock",
        "planner_override",
        "safe_stop",
        "request_review",
        "memory_replay",
        "memory_conflict",
        "operator_decision",
    ]
    planner_state: str | None = None
    current_speed: float | None = None
    position: TelemetryPosition | None = None
    heading_deg: float | None = None
    trigger_reason: str | None = None
    vlm_active: bool | None = None
    safe_mode: bool | None = None
    current_action: str | None = None
    details: dict[str, Any] | None = None


# ── Planner Action ──────────────────────────────────────────────

class Waypoint(BaseModel):
    """規劃航點。"""
    x: float
    y: float
    z: float = 0.0
    speed_limit: float | None = None
    action: str | None = None


class ActionStep(BaseModel):
    """動作序列中的單一步驟。"""
    action: Literal[
        "forward", "turn_left", "turn_right", "stop", "wait", "reverse", "slow_forward"
    ]
    duration_sec: float
    speed_mps: float | None = None
    steering_deg: float | None = None


class PlannerAction(BaseModel):
    """規劃器動作輸出 — 對應 planner_action_schema.json。"""
    plan_id: str
    timestamp: str
    source: Literal[
        "local_planner", "semantic_planner", "memory_replay", "safe_stop", "operator_override"
    ]
    waypoints: list[Waypoint] = Field(default_factory=list)
    action_sequence: list[ActionStep] = Field(default_factory=list)
    validated: bool = False
    vlm_proposal_accepted: bool | None = None
    rejection_reason: str | None = None


# ── Scene Memory Entry ──────────────────────────────────────────

class SceneActionStep(BaseModel):
    """場景記憶動作步驟。"""
    action: str = ""
    duration_sec: float = 0.0


class SceneMemoryEntry(BaseModel):
    """場景記憶條目 — 對應 scene_memory_schema.json。"""
    scene_id: str
    memory_id: str | None = None
    vehicle_id: str
    timestamp: str
    similarity_score: float = Field(ge=0.0, le=1.0)
    is_replay_candidate: bool = False
    success_flag: bool | None = None
    semantic_summary: str | None = None
    thumbnail_url: str | None = None
    action_sequence: list[SceneActionStep] | None = None
    outcome: str | None = None
    replay_count: int = 0
    source_scene_id: str | None = None

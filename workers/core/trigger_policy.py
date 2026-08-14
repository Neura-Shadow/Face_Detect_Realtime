"""
觸發策略模組 — 評估 7 種觸發條件以決定是否需要呼叫 VLM Reasoner，
並包含冷卻機制防止觸發風暴。

觸發條件：
  1. Edge CV 偵測信心度低
  2. 追蹤器不穩定（ID switch / track drift）
  3. 未知場景（場景相似度低於閾值）
  4. 本地規劃器無法生成有效航點
  5. 規劃器震盪 / 死鎖
  6. 未知障礙物 / 長尾場景
  7. 操作員 / 遠端系統請求
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .config import AgentConfig, TriggerConfig

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# 觸發結果
# ════════════════════════════════════════════════════════════════

@dataclass
class TriggerResult:
    """觸發評估結果。"""
    should_trigger: bool
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


# ════════════════════════════════════════════════════════════════
# 觸發策略
# ════════════════════════════════════════════════════════════════

class TriggerPolicy:
    """
    VLM 觸發策略引擎 — 綜合評估多項條件後決定是否觸發 VLM。

    包含冷卻機制：同一原因在冷卻期內不會重複觸發。
    """

    def __init__(self, config: AgentConfig | None = None) -> None:
        cfg = config or AgentConfig.load()
        self._trigger_cfg: TriggerConfig = cfg.trigger
        # 冷卻紀錄：reason → 上次觸發時間戳
        self._cooldowns: dict[str, float] = {}
        # 當前 pending VLM 請求計數
        self._pending_count: int = 0
        logger.info(
            "TriggerPolicy 初始化: cooldown=%.1fs, max_pending=%d",
            self._trigger_cfg.cooldown_sec,
            self._trigger_cfg.max_pending_requests,
        )

    # ── 公開介面 ────────────────────────────────────────────────

    def evaluate(
        self,
        perception: dict[str, Any],
        memory_result: dict[str, Any],
        planner_state: dict[str, Any],
        *,
        operator_request: bool = False,
        frame_count: int = 0,
    ) -> TriggerResult:
        """
        綜合評估所有觸發條件。

        Args:
            perception: 感知結果字典
            memory_result: 場景記憶查詢結果字典
            planner_state: 規劃器狀態字典
            operator_request: 操作員是否手動請求 VLM 介入
            frame_count: 當前幀數，用於計算強制觸發

        Returns:
            TriggerResult 包含觸發與否、原因與細節。
        """
        # 檢查 pending 數量上限
        if self._pending_count >= self._trigger_cfg.max_pending_requests:
            logger.debug("已達 VLM pending 上限 (%d) — 不觸發", self._pending_count)
            return TriggerResult(
                should_trigger=False,
                reason="pending_limit_reached",
                details={"pending_count": self._pending_count},
            )

        # 依序評估 7 種觸發條件（按優先級排列），加上強制觸發
        checks: list[tuple[str, bool, dict[str, Any]]] = [
            self._check_force_interval(frame_count),
            self._check_operator_request(operator_request),
            self._check_low_confidence(perception),
            self._check_tracker_instability(perception),
            self._check_unknown_scene(memory_result),
            self._check_planner_failure(planner_state),
            self._check_planner_oscillation(planner_state),
            self._check_unknown_obstacle(perception),
        ]

        for reason, triggered, details in checks:
            if triggered:
                # force_interval 和 operator_request 繞過冷卻機制
                if reason in ("force_interval", "operator_request") or self._is_cooled_down(reason):
                    self._record_trigger(reason)
                    logger.info("VLM 觸發: reason=%s, details=%s", reason, details)
                return TriggerResult(
                    should_trigger=True,
                    reason=reason,
                    details=details,
                )

        return TriggerResult(
            should_trigger=False,
            reason="no_trigger",
            details={},
        )

    def notify_pending_start(self) -> None:
        """通知有新的 VLM 請求開始（增加 pending 計數）。"""
        self._pending_count += 1

    def notify_pending_end(self) -> None:
        """通知 VLM 請求結束（減少 pending 計數）。"""
        self._pending_count = max(0, self._pending_count - 1)

    # ── 觸發條件 ───────────────────────────────────────────

    def _check_force_interval(
        self, frame_count: int
    ) -> tuple[str, bool, dict[str, Any]]:
        """強制觸發條件：每隔 N 幀強制觸發一次。"""
        interval = self._trigger_cfg.force_interval_frames
        if interval > 0 and frame_count > 0:
            if frame_count % interval == 0:
                return ("force_interval", True, {"frame": frame_count, "interval": interval})
        return ("force_interval", False, {})

    def _check_low_confidence(
        self, perception: dict[str, Any]
    ) -> tuple[str, bool, dict[str, Any]]:
        """條件 1：Edge CV 偵測信心度低於閾值。"""
        raw_conf = perception.get("raw_confidence", 1.0)
        triggered = raw_conf < self._trigger_cfg.low_confidence_threshold
        return (
            "low_confidence",
            triggered,
            {"raw_confidence": raw_conf, "threshold": self._trigger_cfg.low_confidence_threshold},
        )

    def _check_tracker_instability(
        self, perception: dict[str, Any]
    ) -> tuple[str, bool, dict[str, Any]]:
        """條件 2：追蹤器不穩定 — 連續 N 幀有 ID switch。"""
        id_switches = perception.get("tracker_id_switches", 0)
        triggered = id_switches >= self._trigger_cfg.tracker_instability_window
        return (
            "tracker_unstable",
            triggered,
            {
                "id_switches": id_switches,
                "window": self._trigger_cfg.tracker_instability_window,
            },
        )

    def _check_unknown_scene(
        self, memory_result: dict[str, Any]
    ) -> tuple[str, bool, dict[str, Any]]:
        """條件 3：未知場景 — 場景相似度低於閾值。"""
        is_unknown = memory_result.get("is_unknown", False)
        top_sim = memory_result.get("top_similarity", 1.0)
        return (
            "unknown_scene",
            is_unknown,
            {
                "is_unknown": is_unknown,
                "top_similarity": top_sim,
                "threshold": self._trigger_cfg.unknown_scene_threshold,
            },
        )

    def _check_planner_failure(
        self, planner_state: dict[str, Any]
    ) -> tuple[str, bool, dict[str, Any]]:
        """條件 4：本地規劃器無法生成有效航點。"""
        can_plan = planner_state.get("can_plan", True)
        return (
            "planner_no_valid_waypoint",
            not can_plan,
            {"can_plan": can_plan},
        )

    def _check_planner_oscillation(
        self, planner_state: dict[str, Any]
    ) -> tuple[str, bool, dict[str, Any]]:
        """條件 5：規劃器震盪 / 死鎖。"""
        deadlock_count = planner_state.get("deadlock_count", 0)
        oscillation = planner_state.get("oscillation_detected", False)
        triggered = (
            deadlock_count >= self._trigger_cfg.planner_deadlock_count
            or oscillation
        )
        return (
            "planner_deadlock",
            triggered,
            {"deadlock_count": deadlock_count, "oscillation": oscillation},
        )

    def _check_unknown_obstacle(
        self, perception: dict[str, Any]
    ) -> tuple[str, bool, dict[str, Any]]:
        """條件 6：未知障礙物 / 長尾場景（偵測到非常見類別）。"""
        detections = perception.get("detections", [])
        known_labels = {
            "car", "truck", "bus", "pedestrian", "person", "bicycle",
            "motorcycle", "traffic_light", "stop_sign",
        }
        unknown_dets = [
            d for d in detections
            if isinstance(d, dict) and d.get("label", "") not in known_labels
        ]
        triggered = len(unknown_dets) > 0
        return (
            "unknown_obstacle",
            triggered,
            {"unknown_count": len(unknown_dets), "labels": [d.get("label") for d in unknown_dets]},
        )

    @staticmethod
    def _check_operator_request(
        operator_request: bool,
    ) -> tuple[str, bool, dict[str, Any]]:
        """條件 7：操作員 / 遠端系統手動請求。"""
        return (
            "operator_request",
            operator_request,
            {"manual": True},
        )

    # ── 冷卻機制 ────────────────────────────────────────────────

    def _is_cooled_down(self, reason: str) -> bool:
        """檢查指定原因是否已過冷卻期。"""
        last_time = self._cooldowns.get(reason, 0.0)
        elapsed = time.monotonic() - last_time
        if elapsed < self._trigger_cfg.cooldown_sec:
            logger.debug(
                "觸發冷卻中: reason=%s, 剩餘 %.1fs",
                reason,
                self._trigger_cfg.cooldown_sec - elapsed,
            )
            return False
        return True

    def _record_trigger(self, reason: str) -> None:
        """紀錄觸發時間，啟動冷卻。"""
        self._cooldowns[reason] = time.monotonic()

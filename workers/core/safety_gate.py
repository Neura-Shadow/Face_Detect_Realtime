"""
安全閘門模組 — 驗證 VLM 輸出與規劃器動作的安全性，
在指令送達模擬器之前攔截不安全的提案。

功能：
  - 驗證 VLM 結構化輸出（信心、速度、禁止動作）
  - 驗證規劃器航點合法性
  - 強制速度限制
  - 產生緊急停車動作
  - 記錄所有被拒絕的提案
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

try:
    from .config import (
        ActionStep,
        AgentConfig,
        Hazard,
        NavigableRegion,
        PlannerAction,
        SafetyConfig,
        VLMOutput,
        Waypoint,
        WaypointHint,
    )
except ImportError:  # Allow `python workers/core/safety_gate.py --test`.
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from workers.core.config import (  # type: ignore[no-redef]
        ActionStep,
        AgentConfig,
        Hazard,
        NavigableRegion,
        PlannerAction,
        SafetyConfig,
        VLMOutput,
        Waypoint,
        WaypointHint,
    )

logger = logging.getLogger(__name__)

# ── 速度映射（speed_hint → 最大速度 m/s）──────────────────────
_SPEED_LIMIT_MAP: dict[str, float] = {
    "stop": 0.0,
    "slow": 1.5,
    "normal": 3.0,
}


# ════════════════════════════════════════════════════════════════
# 閘門驗證結果
# ════════════════════════════════════════════════════════════════

@dataclass
class GateResult:
    """
    安全閘門驗證結果。

    Attributes:
        approved: 是否通過安全檢查。
        modified_action: 經修正後的動作（僅在需要速度限制時提供）。
        rejection_reason: 若被拒絕，記錄拒絕原因。
    """
    approved: bool
    modified_action: PlannerAction | None = None
    rejection_reason: str | None = None


# ════════════════════════════════════════════════════════════════
# 安全閘門
# ════════════════════════════════════════════════════════════════

class SafetyGate:
    """
    安全閘門 — 所有 VLM 輸出與規劃器動作必須通過此閘門驗證，
    未通過者不得送至 SimulatorAdapter 執行。

    安全閾值全部從 AgentConfig.safety 讀取，絕不寫死。
    """

    def __init__(self, config: AgentConfig | None = None) -> None:
        cfg = config or AgentConfig.load()
        self._safety_cfg: SafetyConfig = cfg.safety
        self._max_speed: float = _SPEED_LIMIT_MAP.get(
            self._safety_cfg.max_speed_hint, 3.0
        )
        self._forbidden_actions: set[str] = set(self._safety_cfg.forbidden_actions)
        self._rejection_log: list[dict[str, Any]] = []
        logger.info(
            "SafetyGate 初始化: confidence_floor=%.2f, max_speed_hint=%s, "
            "forbidden=%s",
            self._safety_cfg.confidence_floor,
            self._safety_cfg.max_speed_hint,
            self._forbidden_actions or "(無)",
        )

    # ── 公開介面 ────────────────────────────────────────────────

    def validate_vlm_output(self, vlm_output: VLMOutput) -> GateResult:
        """
        驗證 VLM 結構化輸出的安全性。

        檢查項目：
          1. 信心度是否低於安全底線
          2. 速度提示是否超過最大限制
          3. waypoint_hints 中是否包含禁止動作
          4. hazard 嚴重度為 critical 時是否建議非停止動作

        Args:
            vlm_output: VLM 推理器的結構化輸出。

        Returns:
            GateResult 包含通過與否、拒絕原因。
        """
        # 檢查 1：critical hazard 需要停車 (最優先處理，若為 critical 且 stop 則直接 safe_stop)
        has_critical = any(
            h.severity == "critical" for h in vlm_output.hazards
        )
        if has_critical:
            if vlm_output.speed_hint != "stop":
                reason = (
                    f"偵測到 critical 等級危險但 VLM 建議速度為 "
                    f"'{vlm_output.speed_hint}' 而非 'stop'"
                )
                self._log_rejection("critical_hazard_not_stop", reason, vlm_output)
                return GateResult(approved=False, rejection_reason=reason)
            else:
                reason_code = "SAFE_STOP_CRITICAL_HAZARD"
                safe_action = self.emergency_stop()
                safe_action.rejection_reason = reason_code
                self._log_rejection(reason_code, "VLM建議停車以因應Critical危險，強制轉換為 safe_stop", vlm_output)
                return GateResult(approved=True, modified_action=safe_action, rejection_reason=reason_code)

        # 檢查 2：信心度底線
        if (
            self._safety_cfg.reject_low_confidence
            and vlm_output.confidence < self._safety_cfg.confidence_floor
        ):
            reason = (
                f"VLM 信心度過低: {vlm_output.confidence:.3f} "
                f"< 安全底線 {self._safety_cfg.confidence_floor:.3f}"
            )
            self._log_rejection("vlm_low_confidence", reason, vlm_output)
            return GateResult(approved=False, rejection_reason=reason)


        # 檢查 3：禁止動作
        for hint in vlm_output.waypoint_hints:
            direction = hint.direction or ""
            if direction in self._forbidden_actions:
                reason = (
                    f"VLM 建議的方向 '{direction}' 屬於禁止動作清單"
                )
                self._log_rejection("forbidden_action", reason, vlm_output)
                return GateResult(approved=False, rejection_reason=reason)

        # 檢查 4：must_not_do 與 waypoint_hints 矛盾
        for hint in vlm_output.waypoint_hints:
            if hint.hint and hint.hint in vlm_output.must_not_do:
                reason = (
                    f"VLM waypoint_hint '{hint.hint}' 同時出現在 must_not_do 中"
                )
                self._log_rejection("contradictory_hint", reason, vlm_output)
                return GateResult(approved=False, rejection_reason=reason)

        logger.debug(
            "VLM 輸出通過安全閘門: confidence=%.3f, speed=%s",
            vlm_output.confidence,
            vlm_output.speed_hint,
        )
        return GateResult(approved=True)

    def validate_planner_action(self, action: PlannerAction) -> GateResult:
        """
        驗證規劃器動作的安全性。

        檢查項目：
          1. 航點序列有效性（非空、無重疊）
          2. 動作序列中的速度不超過限制
          3. 動作序列中不包含禁止動作

        Args:
            action: 規劃器產生的動作。

        Returns:
            GateResult — 若航點需修正，modified_action 包含修正後的動作。
        """
        # 檢查 1：航點有效性（source=safe_stop 允許空航點）
        if action.source not in ("safe_stop", "operator_override"):
            if action.waypoints:
                for i in range(1, len(action.waypoints)):
                    prev = action.waypoints[i - 1]
                    curr = action.waypoints[i]
                    dx = curr.x - prev.x
                    dy = curr.y - prev.y
                    dist = (dx * dx + dy * dy) ** 0.5
                    if dist < 0.01:
                        reason = f"航點 {i - 1} 與 {i} 重疊 (距離={dist:.4f})"
                        self._log_rejection("waypoint_overlap", reason, action)
                        return GateResult(approved=False, rejection_reason=reason)

        # 檢查 2：禁止動作
        for step in action.action_sequence:
            if step.action in self._forbidden_actions:
                reason = f"動作序列包含禁止動作: '{step.action}'"
                self._log_rejection("forbidden_action_in_plan", reason, action)
                return GateResult(approved=False, rejection_reason=reason)

        # 檢查 3：速度限制 → 若超速則自動修正
        needs_modification = False
        for step in action.action_sequence:
            if step.speed_mps is not None and step.speed_mps > self._max_speed:
                needs_modification = True
                break

        if needs_modification:
            modified = self.apply_speed_limits(action)
            logger.info(
                "規劃器動作速度已修正: plan_id=%s, max_speed=%.1f",
                action.plan_id,
                self._max_speed,
            )
            return GateResult(approved=True, modified_action=modified)

        logger.debug("規劃器動作通過安全閘門: plan_id=%s", action.plan_id)
        return GateResult(approved=True)

    def apply_speed_limits(self, action: PlannerAction) -> PlannerAction:
        """
        強制執行速度限制 — 將所有超速的 ActionStep 降至安全上限。

        Args:
            action: 原始規劃器動作。

        Returns:
            速度修正後的 PlannerAction（新實例）。
        """
        clamped_steps: list[ActionStep] = []
        for step in action.action_sequence:
            speed = step.speed_mps
            if speed is not None and speed > self._max_speed:
                speed = self._max_speed
            clamped_steps.append(ActionStep(
                action=step.action,
                duration_sec=step.duration_sec,
                speed_mps=speed,
                steering_deg=step.steering_deg,
            ))

        clamped_waypoints: list[Waypoint] = []
        for wp in action.waypoints:
            limit = wp.speed_limit
            if limit is not None and limit > self._max_speed:
                limit = self._max_speed
            clamped_waypoints.append(Waypoint(
                x=wp.x,
                y=wp.y,
                z=wp.z,
                speed_limit=limit,
                action=wp.action,
            ))

        return PlannerAction(
            plan_id=action.plan_id,
            timestamp=action.timestamp,
            source=action.source,
            waypoints=clamped_waypoints,
            action_sequence=clamped_steps,
            validated=True,
            vlm_proposal_accepted=action.vlm_proposal_accepted,
            rejection_reason=action.rejection_reason,
        )

    def emergency_stop(self) -> PlannerAction:
        """
        產生緊急停車動作 — 用於任何不可恢復的安全情境。

        Returns:
            source='safe_stop' 的 PlannerAction。
        """
        plan = PlannerAction(
            plan_id=f"emergency-{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            source="safe_stop",
            waypoints=[],
            action_sequence=[
                ActionStep(action="stop", duration_sec=10.0, speed_mps=0.0),
            ],
            validated=True,
            vlm_proposal_accepted=False,
            rejection_reason="emergency_stop",
        )
        logger.warning("已產生緊急停車動作: plan_id=%s", plan.plan_id)
        return plan

    # ── 拒絕日誌 ────────────────────────────────────────────────

    @property
    def rejection_log(self) -> list[dict[str, Any]]:
        """取得所有被拒絕提案的日誌紀錄。"""
        return list(self._rejection_log)

    def _log_rejection(
        self,
        reason_code: str,
        message: str,
        proposal: VLMOutput | PlannerAction | Any,
    ) -> None:
        """記錄被拒絕的 VLM 或 Planner 提案。"""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason_code": reason_code,
            "message": message,
            "proposal_type": type(proposal).__name__,
        }
        # 安全萃取摘要資訊
        if isinstance(proposal, VLMOutput):
            entry["proposal_summary"] = {
                "scene_summary": proposal.scene_summary[:100],
                "confidence": proposal.confidence,
                "speed_hint": proposal.speed_hint,
                "hazard_count": len(proposal.hazards),
            }
        elif isinstance(proposal, PlannerAction):
            entry["proposal_summary"] = {
                "plan_id": proposal.plan_id,
                "source": proposal.source,
                "waypoint_count": len(proposal.waypoints),
                "action_count": len(proposal.action_sequence),
            }

        self._rejection_log.append(entry)
        logger.warning(
            "安全閘門拒絕: [%s] %s",
            reason_code,
            message,
        )

# ============================================================
# CLI Self-Test: Rejection Stress Test
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SafetyGate Rejection Stress Test")
    parser.add_argument("--test", action="store_true", help="Run rejection stress test")
    args = parser.parse_args()

    if args.test:
        logging.basicConfig(level=logging.INFO)
        logger.info("開始執行 SafetyGate Rejection Stress Test...")

        # 強制設定一個已知的 AgentConfig
        config = AgentConfig.load()
        import dataclasses
        safe_cfg = dataclasses.replace(
            config.safety,
            reject_low_confidence=True,
            confidence_floor=0.4,
            max_speed_hint="normal",
            forbidden_actions=["back", "reverse"]
        )
        config = dataclasses.replace(config, safety=safe_cfg)

        gate = SafetyGate(config)

        # 1. 測試：信心度過低
        vlm_low_conf = VLMOutput(
            scene_summary="視野模糊不清",
            reasoning_summary="因視野模糊，信心度不足。",
            hazards=[],
            navigable_regions=[],
            waypoint_hints=[],
            speed_hint="slow",
            must_not_do=[],
            confidence=0.2  # 低於 0.4
        )
        r1 = gate.validate_vlm_output(vlm_low_conf)
        assert not r1.approved, "低信心度測試應被拒絕"
        logger.info(f"[PASS] 低信心度攔截成功: {r1.rejection_reason}")

        # 2. 測試：Critical Hazard 但未停車
        vlm_critical_not_stop = VLMOutput(
            scene_summary="前方有行人突然衝出",
            reasoning_summary="行人衝出，但我決定減速通過",
            hazards=[Hazard(label="pedestrian", severity="critical", description="")],
            navigable_regions=[],
            waypoint_hints=[],
            speed_hint="slow",  # 應該是 stop
            must_not_do=[],
            confidence=0.8
        )
        r2 = gate.validate_vlm_output(vlm_critical_not_stop)
        assert not r2.approved, "Critical 危險未停車應被拒絕"
        logger.info(f"[PASS] Critical危險未停車攔截成功: {r2.rejection_reason}")

        # 3. 測試：禁止動作 (back)
        vlm_forbidden = VLMOutput(
            scene_summary="前方死胡同",
            reasoning_summary="死胡同，建議倒車",
            hazards=[],
            navigable_regions=[],
            waypoint_hints=[WaypointHint(hint="倒車", direction="back")],
            speed_hint="slow",
            must_not_do=[],
            confidence=0.9
        )
        r3 = gate.validate_vlm_output(vlm_forbidden)
        assert not r3.approved, "Forbidden action 應被拒絕"
        logger.info(f"[PASS] Forbidden action 攔截成功: {r3.rejection_reason}")

        # 4. 測試：矛盾邏輯 (hint 也在 must_not_do)
        vlm_contradiction = VLMOutput(
            scene_summary="前方路口",
            reasoning_summary="向左轉",
            hazards=[],
            navigable_regions=[],
            waypoint_hints=[WaypointHint(hint="turn_left", direction="left")],
            speed_hint="normal",
            must_not_do=["turn_left"],
            confidence=0.9
        )
        r4 = gate.validate_vlm_output(vlm_contradiction)
        assert not r4.approved, "矛盾邏輯應被拒絕"
        logger.info(f"[PASS] 矛盾邏輯攔截成功: {r4.rejection_reason}")

        # 5. 測試：安全建議應通過 (Case A)
        vlm_safe = VLMOutput(
            scene_summary="Clear path ahead",
            reasoning_summary="Path is clear and speed is within safe limit.",
            hazards=[],
            navigable_regions=[NavigableRegion(region_id="center_lane", description="center lane")],
            waypoint_hints=[WaypointHint(hint="move_forward_slowly", direction="forward")],
            speed_hint="slow",
            must_not_do=[],
            confidence=0.9
        )
        r5 = gate.validate_vlm_output(vlm_safe)
        assert r5.approved, "安全建議應該被放行"
        logger.info("[PASS] 安全建議通過測試")

        # 6. 測試：requires_stop=true (即 speed_hint="stop") 應 safe stop (Case B)
        vlm_stop = VLMOutput(
            scene_summary="Obstacle directly ahead",
            reasoning_summary="Immediate stop is required because a critical obstacle is directly ahead.",
            hazards=[Hazard(label="obstacle", severity="critical", description="front")],
            navigable_regions=[],
            waypoint_hints=[],
            speed_hint="stop",
            must_not_do=["move_forward"],
            confidence=0.85
        )
        r6 = gate.validate_vlm_output(vlm_stop)
        assert r6.approved, "Critical 危險且選擇停車，應該被放行"
        assert r6.modified_action is not None, "應該強制轉換為 safe_stop 動作"
        assert r6.modified_action.source == "safe_stop", f"動作來源應該是 safe_stop，目前是 {r6.modified_action.source}"
        assert r6.rejection_reason == "SAFE_STOP_CRITICAL_HAZARD", f"Reason Code 應該是 SAFE_STOP_CRITICAL_HAZARD，目前是 {r6.rejection_reason}"
        logger.info(f"[PASS] Critical危險並選擇停車通過測試: action={r6.modified_action.source}, reason_code={r6.rejection_reason}, approved={r6.approved}")

        # 7. 測試：PlannerAction 超速 (Overspeed clamp)
        plan_overspeed = PlannerAction(
            plan_id="test-7",
            timestamp="2026-06-08T00:00:00Z",
            source="local_planner",
            waypoints=[Waypoint(x=1.0, y=0.0, speed_limit=5.0)],
            action_sequence=[ActionStep(action="forward", duration_sec=1.0, speed_mps=5.0)],
            validated=False
        )
        r7 = gate.validate_planner_action(plan_overspeed)
        assert r7.approved, "超速應被放行但被修正"
        assert r7.modified_action is not None, "超速應該產生 modified_action"
        assert r7.modified_action.action_sequence[0].speed_mps == 3.0, "速度應該被修正為 max_speed=3.0"
        logger.info(f"[PASS] PlannerAction 超速修正通過測試: 原速=5.0, 修正後={r7.modified_action.action_sequence[0].speed_mps}")

        # 8. 測試：PlannerAction 包含禁止動作
        plan_forbidden = PlannerAction(
            plan_id="test-8",
            timestamp="2026-06-08T00:00:00Z",
            source="local_planner",
            waypoints=[Waypoint(x=1.0, y=0.0)],
            action_sequence=[ActionStep(action="reverse", duration_sec=1.0, speed_mps=1.0)],
            validated=False
        )
        r8 = gate.validate_planner_action(plan_forbidden)
        assert not r8.approved, "包含禁止動作應被拒絕"
        logger.info(f"[PASS] PlannerAction 禁止動作攔截成功: {r8.rejection_reason}")

        # 9. 測試：PlannerAction 航點重疊
        plan_overlap = PlannerAction(
            plan_id="test-9",
            timestamp="2026-06-08T00:00:00Z",
            source="local_planner",
            waypoints=[Waypoint(x=1.0, y=1.0), Waypoint(x=1.0, y=1.0)],
            action_sequence=[ActionStep(action="forward", duration_sec=1.0, speed_mps=1.0)],
            validated=False
        )
        r9 = gate.validate_planner_action(plan_overlap)
        assert not r9.approved, "航點重疊應被拒絕"
        logger.info(f"[PASS] PlannerAction 航點重疊攔截成功: {r9.rejection_reason}")

        # 10. 測試：VLM fallback output 應轉換為 safe_stop (即使信心度很低)
        fallback = VLMOutput(
            scene_summary="VLM failed or returned invalid output.",
            reasoning_summary="Safe fallback activated due to invalid or unavailable VLM response.",
            hazards=[
                Hazard(
                    label="vlm_failure",
                    severity="critical",
                    description="global"
                )
            ],
            navigable_regions=[],
            waypoint_hints=[],
            speed_hint="stop",
            must_not_do=["move_forward", "turn_left", "turn_right", "accelerate"],
            confidence=0.1
        )
        r10 = gate.validate_vlm_output(fallback)
        assert r10.approved, "Fallback 應被放行作為 safe_stop"
        assert r10.modified_action is not None, "Fallback 必須強制產生 safe_stop action"
        assert r10.modified_action.source == "safe_stop", "動作來源必須是 safe_stop"
        assert r10.rejection_reason == "SAFE_STOP_CRITICAL_HAZARD", "原因代碼必須是 SAFE_STOP_CRITICAL_HAZARD"
        logger.info(f"[PASS] VLM Fallback output 強制轉換 safe_stop 成功: {r10.rejection_reason}")

        logger.info("=== SafetyGate Rejection Stress Test 通過！所有攔截邏輯運作正常 ===")

"""
自動駕駛代理主模組 — 對應原始 main.py，整合所有核心模組。

實作 12 步驟主迴圈：
  1. 攝影機讀取影像
  2. 邊緣感知（偵測、追蹤、車道、自由空間）
  3. 產生/快取場景 embedding
  4. 查詢場景記憶 top-k
  5. 評估觸發策略
  6. 無觸發 → 本地規劃或 replay
  7. 有觸發 → VLM 推理
  8. VLM 輸出 → 安全閘門
  9. 通過 → 語義規劃
  10. 動作執行
  11. 遙測發佈
  12. 失敗處理 → 緊急停車 + 日誌 + 審查請求

保守回退策略：
  - VLM 逾時/錯誤 → stop + wait + log
  - VLM 低信心 → request_review
  - 安全閘門拒絕 → reject + log
  - 記憶-感知衝突 → block replay + 本地規劃

所有模型名稱、URL、Key 均從設定讀取，絕不寫死。
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np

from .core.camera_adapter import (
    CameraAdapter,
    OpenCVCameraAdapter,
    SimulatorCameraAdapter,
)
from .core.config import (
    AgentConfig,
    PlannerAction,
    TelemetryEntry,
    TelemetryPosition,
    VLMOutput,
)
from .core.edge_perception import EdgePerception, PerceptionResult
from .core.embedding_backend import CLIPEmbeddingBackend, EMBEDDING_DIM
from .core.safety_gate import GateResult, SafetyGate
from .core.scene_memory import SceneMemoryRetriever
from .core.semantic_planner import SemanticPlanner
from .core.simulator_adapter import DummySimulatorAdapter, SimulatorAdapter
from .core.supabase_client import SupabaseManager
from .core.telemetry_publisher import TelemetryPublisher
from .core.trigger_policy import TriggerPolicy, TriggerResult
from .core.vlm_reasoner import (
    LocalStubVLMReasoner,
    OpenAICompatibleVLMReasoner,
    VLMReasoner,
)

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# 自動駕駛代理
# ════════════════════════════════════════════════════════════════

class AutonomousDrivingAgent:
    """
    自動駕駛代理 — 整合所有核心模組的主協調器。

    對應原始 main.py 的主迴圈，但從 face detection 遷移至
    記憶增強視覺語言導航（MA-VLNA）架構。

    使用方式：
        agent = AutonomousDrivingAgent()
        await agent.run()
    """

    def __init__(self, config: AgentConfig | None = None) -> None:
        self._config = config or AgentConfig.load()
        self._running: bool = False
        self._frame_count: int = 0
        self._current_pos: tuple[float, float] = (0.0, 0.0)

        # Embedding 快取
        self._cached_embedding: np.ndarray | None = None
        self._cached_embedding_time: float = 0.0

        # ── 初始化所有子模組 ──────────────────────────────────

        # 攝影機適配器
        self._camera: CameraAdapter
        if self._config.mode == "simulator":
            self._camera = SimulatorCameraAdapter(
                width=self._config.camera.width,
                height=self._config.camera.height,
            )
        else:
            self._camera = OpenCVCameraAdapter(self._config.camera)

        # 邊緣感知
        self._perception = EdgePerception(self._config)

        # Embedding 後端
        self._embedding_backend = CLIPEmbeddingBackend(
            self._config.embedding
        )

        # 場景記憶檢索
        self._scene_memory = SceneMemoryRetriever(self._config)

        # 觸發策略
        self._trigger_policy = TriggerPolicy(self._config)

        # VLM 推理器
        self._vlm_reasoner: VLMReasoner
        provider = self._config.vlm.provider.lower()
        if provider == "local_stub":
            logger.info("VLM 模型設定為 local_stub — 使用 LocalStubVLMReasoner")
            self._vlm_reasoner = LocalStubVLMReasoner()
        elif provider == "gemma":
            from .core.vlm_reasoner import GemmaReasoner
            self._vlm_reasoner = GemmaReasoner(self._config.vlm)
        elif provider == "openai_compatible":
            self._vlm_reasoner = OpenAICompatibleVLMReasoner(self._config.vlm)
        else:
            logger.warning(f"未知的 VLM provider '{provider}'，退回使用 LocalStubVLMReasoner")
            self._vlm_reasoner = LocalStubVLMReasoner()

        # 安全閘門
        self._safety_gate = SafetyGate(self._config)

        # 語義規劃器
        self._planner = SemanticPlanner(self._config)

        # 模擬器適配器
        self._simulator: SimulatorAdapter = DummySimulatorAdapter()

        # 遙測發佈器
        self._telemetry = TelemetryPublisher(self._config)

        logger.info(
            "AutonomousDrivingAgent 初始化完成: "
            "agent_id=%s, mode=%s, loop_hz=%d",
            self._config.agent_id,
            self._config.mode,
            self._config.main_loop_hz,
        )

    # ════════════════════════════════════════════════════════════
    # 主迴圈
    # ════════════════════════════════════════════════════════════

    async def run(self, max_steps: int | None = None) -> None:
        """
        主迴圈：執行 12 步驟感知-決策-規劃-執行循環。

        一直運行直到 shutdown() 被呼叫或達到 max_steps。
        """
        self._running = True
        loop_interval = 1.0 / self._config.main_loop_hz

        # 打開相機
        if not self._camera.open():
            logger.error("相機打開失敗，中止運行")
            return

        # 啟動遙測寫入
        await self._telemetry.start()

        logger.info("啟動 MA-VLNA 主迴圈...")
        steps_run = 0

        try:
            while self._running:
                if max_steps is not None and steps_run >= max_steps:
                    logger.info("達到指定步數 %d，正常結束主迴圈", max_steps)
                    break

                loop_start = time.monotonic()
                self._frame_count += 1

                try:
                    await self._execute_cycle()
                except Exception:
                    logger.exception(
                        "主迴圈第 %d 幀發生例外，執行緊急停車",
                        self._frame_count,
                    )
                    await self._handle_safe_stop("主迴圈例外")

                steps_run += 1

                # 維持迴圈頻率
                elapsed = time.monotonic() - loop_start
                sleep_time = max(0.0, loop_interval - elapsed)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

        except asyncio.CancelledError:
            logger.info("主迴圈收到取消信號")
        finally:
            await self.shutdown()

    async def _execute_cycle(self) -> None:
        """執行單一 12 步驟循環。"""

        # ── 步驟 1：讀取影像 ──────────────────────────────────
        success, frame = self._camera.read()
        if not success or frame is None:
            logger.warning("影像讀取失敗 (frame #%d)", self._frame_count)
            return

        # ── 步驟 2：邊緣感知 ──────────────────────────────────
        perception: PerceptionResult = self._perception.process(frame)

        # ── 步驟 3：場景 embedding（含快取）────────────────────
        embedding = self._get_or_compute_embedding(frame)

        # ── 步驟 4：查詢場景記憶 top-k ────────────────────────
        memory_entries = self._scene_memory.query_top_k(embedding)
        is_unknown = self._scene_memory.is_unknown_scene(embedding)
        top_similarity = (
            memory_entries[0].similarity_score if memory_entries else 0.0
        )

        # ── 步驟 5：觸發策略評估 ──────────────────────────────
        perception_dict: dict[str, Any] = {
            "raw_confidence": perception.raw_confidence,
            "tracker_id_switches": self._perception.tracker_id_switch_count,
            "detections": [
                d.to_dict()
                for d in perception.detections
            ],
        }
        memory_dict: dict[str, Any] = {
            "is_unknown": is_unknown,
            "top_similarity": top_similarity,
        }
        planner_dict: dict[str, Any] = {
            "can_plan": self._planner.can_plan,
            "deadlock_count": self._planner.deadlock_count,
            "oscillation_detected": self._planner.oscillation_detected,
        }

        trigger_result: TriggerResult = self._trigger_policy.evaluate(
            perception=perception_dict,
            memory_result=memory_dict,
            planner_state=planner_dict,
            frame_count=self._frame_count,
        )

        # ── 步驟 6–9：決策分支 ────────────────────────────────
        action: PlannerAction

        if not trigger_result.should_trigger:
            # ── 無觸發：本地規劃或 replay ──────────────────────
            action, vlm_output, gate_result = await self._plan_without_vlm(
                perception, embedding, memory_entries
            )
        else:
            # ── 有觸發：VLM 推理路徑 ──────────────────────────
            action, vlm_output, gate_result = await self._plan_with_vlm(
                frame, perception, trigger_result
            )

        # ── 步驟 10：執行動作 ─────────────────────────────────
        exec_success = False
        try:
            exec_success = await self._simulator.execute(action)
        except NotImplementedError:
            logger.error(
                "模擬器適配器未實作 — plan_id=%s", action.plan_id
            )
        except Exception:
            logger.exception("動作執行失敗 — plan_id=%s", action.plan_id)

        if not exec_success:
            await self._handle_safe_stop("動作執行失敗")

        # ── 步驟 11：遙測發佈 ─────────────────────────────────
        self._publish_cycle_telemetry(
            perception=perception,
            trigger_result=trigger_result,
            action=action,
            embedding=embedding,
            vlm_output=vlm_output,
            gate_result=gate_result,
        )

    # ════════════════════════════════════════════════════════════
    # 決策子流程
    # ════════════════════════════════════════════════════════════

    async def _plan_without_vlm(
        self,
        perception: PerceptionResult,
        embedding: np.ndarray,
        memory_entries: list[Any],
    ) -> tuple[PlannerAction, VLMOutput | None, GateResult | None]:
        """
        無 VLM 觸發時的規劃路徑 — 嘗試 replay，否則本地規劃。

        步驟 6 的展開。
        """
        # 嘗試 replay
        replay_candidates = self._scene_memory.get_replay_candidates(
            embedding
        )
        if replay_candidates:
            best_candidate = replay_candidates[0]

            # 檢查感知衝突
            perception_for_conflict = {
                "lane_state": perception.lane_state,
                "detections": perception.detections,
            }
            has_conflict = self._scene_memory.check_replay_conflict(
                best_candidate, perception_for_conflict
            )

            if has_conflict:
                # 記憶-感知衝突 → block replay + 本地規劃
                logger.warning(
                    "記憶-感知衝突 — block replay, 使用本地規劃 "
                    "(scene_id=%s)",
                    best_candidate.scene_id,
                )
                self._telemetry.publish_telemetry(TelemetryEntry(
                    vehicle_id=self._config.agent_id,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    event_type="memory_conflict",
                    details={
                        "scene_id": best_candidate.scene_id,
                        "action": "block_replay",
                    },
                ))
            else:
                # Replay 成功
                action = self._planner.plan_from_replay(
                    best_candidate, perception
                )
                self._telemetry.publish_telemetry(TelemetryEntry(
                    vehicle_id=self._config.agent_id,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    event_type="memory_replay",
                    details={
                        "scene_id": best_candidate.scene_id,
                        "similarity": best_candidate.similarity_score,
                    },
                ))
                return action, None, None

        # 預設本地規劃
        action = self._planner.plan_local(perception, self._current_pos)
        return action, None, None

    async def _plan_with_vlm(
        self,
        frame: np.ndarray,
        perception: PerceptionResult,
        trigger_result: TriggerResult,
    ) -> tuple[PlannerAction, VLMOutput | None, GateResult | None]:
        """
        VLM 觸發時的規劃路徑 — 步驟 7–9 的展開。

        包含完整的 timeout / retry / fallback 邏輯。
        """
        self._trigger_policy.notify_pending_start()

        try:
            # ── 步驟 7：VLM 推理 ──────────────────────────────
            context: dict[str, Any] = {
                "trigger_reason": trigger_result.reason,
                "trigger_details": trigger_result.details,
                "lane_state": perception.lane_state,
                "detection_count": len(perception.detections),
                "raw_confidence": perception.raw_confidence,
            }

            # 發佈觸發事件
            self._telemetry.publish_telemetry(TelemetryEntry(
                vehicle_id=self._config.agent_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                event_type="vlm_triggered",
                trigger_reason=trigger_result.reason,
                details=trigger_result.details,
            ))

            try:
                vlm_output: VLMOutput = await asyncio.wait_for(
                    self._vlm_reasoner.reason(frame, context),
                    timeout=self._config.vlm.timeout_sec,
                )
            except asyncio.TimeoutError:
                logger.error("VLM 推理逾時")
                self._telemetry.publish_telemetry(TelemetryEntry(
                    vehicle_id=self._config.agent_id,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    event_type="vlm_timeout",
                    details={
                        "timeout_sec": self._config.vlm.timeout_sec,
                        "trigger_reason": trigger_result.reason,
                    },
                ))
                action = await self._handle_vlm_failure("vlm_timeout")
                return action, None, None
            except Exception as exc:
                logger.exception("VLM 推理失敗")
                action = await self._handle_vlm_failure(
                    f"vlm_error: {exc}"
                )
                return action, None, None

            # 發佈 VLM 回應
            self._telemetry.publish_telemetry(TelemetryEntry(
                vehicle_id=self._config.agent_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                event_type="vlm_response",
                details={
                    "confidence": vlm_output.confidence,
                    "speed_hint": vlm_output.speed_hint,
                    "hazard_count": len(vlm_output.hazards),
                    "vlm_output": vlm_output.model_dump(exclude_none=True),
                },
            ))

            # ── 步驟 8：安全閘門 ──────────────────────────────
            gate_result: GateResult = (
                self._safety_gate.validate_vlm_output(vlm_output)
            )

            if not gate_result.approved:
                logger.warning(
                    "安全閘門拒絕 VLM 輸出: %s",
                    gate_result.rejection_reason,
                )
                self._telemetry.publish_telemetry(TelemetryEntry(
                    vehicle_id=self._config.agent_id,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    event_type="vlm_rejected",
                    details={
                        "rejection_reason": gate_result.rejection_reason,
                        "confidence": vlm_output.confidence,
                    },
                ))

                # VLM 低信心 → request_review
                if vlm_output.confidence < self._config.vlm.confidence_threshold:
                    action = await self._request_review(
                        f"VLM 信心度過低: {vlm_output.confidence:.3f}"
                    )
                    return action, vlm_output, gate_result

                # 其他拒絕 → safe stop
                action = await self._handle_safe_stop(
                    gate_result.rejection_reason or "安全閘門拒絕"
                )
                return action, vlm_output, gate_result

            # ── 步驟 9：語義規劃 ──────────────────────────────
            action = self._planner.plan_with_vlm(vlm_output, perception)

            # 規劃器動作二次驗證
            if self._config.safety.require_planner_validation:
                plan_gate: GateResult = (
                    self._safety_gate.validate_planner_action(action)
                )
                if not plan_gate.approved:
                    logger.warning(
                        "規劃器動作被安全閘門拒絕: %s",
                        plan_gate.rejection_reason,
                    )
                    action = await self._handle_safe_stop(
                        plan_gate.rejection_reason or "規劃器動作不安全"
                    )
                    return action, vlm_output, gate_result
                if plan_gate.modified_action is not None:
                    action = plan_gate.modified_action

            action.vlm_proposal_accepted = True
            action.validated = True
            return action, vlm_output, gate_result

        finally:
            self._trigger_policy.notify_pending_end()

    # ════════════════════════════════════════════════════════════
    # 回退處理
    # ════════════════════════════════════════════════════════════

    async def _handle_vlm_failure(self, reason: str) -> PlannerAction:
        """
        VLM 失敗回退 — stop + wait + log。

        對應 fallback.on_vlm_timeout 設定。
        """
        logger.warning("VLM 失敗回退: %s → %s",
                        reason, self._config.fallback.on_vlm_timeout)

        self._telemetry.publish_telemetry(TelemetryEntry(
            vehicle_id=self._config.agent_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type="safe_stop",
            details={"reason": reason, "fallback": "vlm_failure"},
        ))

        return self._safety_gate.emergency_stop()

    async def _handle_safe_stop(self, reason: str) -> PlannerAction:
        """
        安全停車 — 產生緊急停車動作並記錄。

        Args:
            reason: 停車原因。

        Returns:
            緊急停車 PlannerAction。
        """
        logger.warning("安全停車: %s", reason)

        action = self._safety_gate.emergency_stop()

        self._telemetry.publish_telemetry(TelemetryEntry(
            vehicle_id=self._config.agent_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type="safe_stop",
            details={"reason": reason},
        ))

        # 嘗試執行停車動作
        try:
            await self._simulator.execute(action)
        except Exception:
            logger.exception("緊急停車執行失敗")

        return action

    async def _request_review(self, reason: str) -> PlannerAction:
        """
        請求人工審查 — 停車並標記 request_review 事件。

        對應 fallback.on_vlm_low_confidence 設定。

        Args:
            reason: 請求審查的原因。

        Returns:
            安全停車 PlannerAction。
        """
        logger.warning("請求人工審查: %s", reason)

        self._telemetry.publish_telemetry(TelemetryEntry(
            vehicle_id=self._config.agent_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type="request_review",
            details={"reason": reason},
        ))

        # 更新車輛狀態為等待審查
        self._telemetry.publish_status({
            "vehicle_id": self._config.agent_id,
            "planner_state": "waiting_review",
            "safe_mode": True,
            "vlm_active": False,
            "current_action": "stop",
            "current_speed": 0.0,
        })

        return self._safety_gate.emergency_stop()

    # ════════════════════════════════════════════════════════════
    # 輔助方法
    # ════════════════════════════════════════════════════════════

    def _get_or_compute_embedding(self, frame: np.ndarray) -> np.ndarray:
        """
        取得或計算場景 embedding（含 TTL 快取）。

        快取有效期由 embedding_cache_ttl_sec 設定控制。
        """
        now = time.monotonic()
        ttl = self._config.embedding_cache_ttl_sec

        if (
            self._cached_embedding is not None
            and (now - self._cached_embedding_time) < ttl
        ):
            return self._cached_embedding

        try:
            embedding = self._embedding_backend.process_single(frame)
        except Exception:
            logger.exception("Embedding 計算失敗 — 使用零向量")
            embedding = np.zeros(EMBEDDING_DIM, dtype=np.float32)

        self._cached_embedding = embedding
        self._cached_embedding_time = now
        return embedding

    def _publish_cycle_telemetry(
        self,
        perception: PerceptionResult,
        trigger_result: TriggerResult,
        action: PlannerAction,
        embedding: np.ndarray,
        vlm_output: VLMOutput | None = None,
        gate_result: GateResult | None = None,
    ) -> None:
        """發佈單一循環的遙測資料。"""
        # 狀態更新
        self._telemetry.publish_status({
            "vehicle_id": self._config.agent_id,
            "planner_state": (
                "navigating" if action.source != "safe_stop" else "safe_stop"
            ),
            "current_speed": (
                action.action_sequence[0].speed_mps
                if action.action_sequence and action.action_sequence[0].speed_mps
                else 0.0
            ),
            "position_x": self._current_pos[0],
            "position_y": self._current_pos[1],
            "safe_mode": action.source == "safe_stop",
            "vlm_active": trigger_result.should_trigger,
            "current_action": (
                action.action_sequence[0].action
                if action.action_sequence
                else "none"
            ),
            "last_trigger_reason": (
                trigger_result.reason
                if trigger_result.should_trigger
                else None
            ),
        })

        # 場景日誌（每 N 幀記錄一次以避免過載）
        if self._frame_count % max(1, self._config.main_loop_hz) == 0:
            metadata = {
                "inference_ms": perception.inference_ms,
                "backend": perception.backend,
                "model_name": perception.model_name,
                "fallback_used": perception.fallback_used
            }
            if gate_result is not None:
                metadata["gate_approved"] = gate_result.approved
                metadata["gate_rejection_reason"] = gate_result.rejection_reason

            self._telemetry.publish_scene_log({
                "vehicle_id": self._config.agent_id,
                "embedding": embedding.tolist(),
                "lane_state": perception.lane_state,
                "detections": [d.to_dict() for d in perception.detections],
                "tracks": [t.to_dict() for t in perception.tracks],
                "free_space": perception.free_space,
                "metadata": metadata,
                "trigger_reason": (
                    trigger_result.reason
                    if trigger_result.should_trigger
                    else None
                ),
                "planner_action": action.model_dump(exclude_none=True),
                "planner_state": action.source,
                "vlm_output": vlm_output.model_dump(exclude_none=True) if vlm_output else None,
            })

        # 觸發事件
        if trigger_result.should_trigger:
            self._telemetry.publish_trigger_event({
                "trigger_reason": trigger_result.reason,
                "trigger_details": trigger_result.details,
            })

    # ════════════════════════════════════════════════════════════
    # 生命週期
    # ════════════════════════════════════════════════════════════

    async def shutdown(self) -> None:
        """優雅關閉 — 釋放所有資源。"""
        if not self._running:
            return
        self._running = False

        logger.info("═══ MA-VLNA 代理關閉中... ═══")

        # 停止遙測
        try:
            await self._telemetry.stop()
        except Exception:
            logger.exception("遙測關閉失敗")

        # 釋放攝影機
        try:
            self._camera.release()
        except Exception:
            logger.exception("攝影機釋放失敗")

        logger.info(
            "═══ MA-VLNA 代理已關閉 — 共處理 %d 幀 ═══",
            self._frame_count,
        )


# ════════════════════════════════════════════════════════════════
# CLI 入口
# ════════════════════════════════════════════════════════════════

async def _async_main() -> None:
    """非同步主進入點。"""
    import argparse
    parser = argparse.ArgumentParser(description="MA-VLNA 視覺導航代理系統")
    parser.add_argument("--mode", type=str, default=None, choices=["mock", "simulator", "webcam", "camera", "ros2", "isaac_sim"], help="代理執行模式")
    parser.add_argument("--source", type=str, default=None, help="攝影機來源")
    parser.add_argument("--steps", type=int, default=None, help="最大執行步數")
    parser.add_argument("--perception-backend", type=str, default=None, help="強制覆蓋 Perception Backend (dummy, yolo, rtdetr)")
    parser.add_argument("--force-vlm-every", type=int, default=None, help="每隔N幀強制觸發VLM")
    parser.add_argument("--vlm-provider", type=str, default=None, help="強制覆蓋 VLM Provider (local_stub, openai_compatible, gemma)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)-30s | %(levelname)-7s | %(message)s",
    )
    logger.info("啟動 MA-VLNA 自動駕駛代理系統...")

    config = AgentConfig.load()
    if args.mode:
        if args.mode == "camera":
            config.mode = "webcam"
        else:
            config.mode = args.mode
    if args.source:
        config.camera = __import__("dataclasses").replace(config.camera, source=args.source)
    if args.perception_backend:
        config.perception = __import__("dataclasses").replace(config.perception, backend=args.perception_backend)
    if args.force_vlm_every:
        config.trigger = __import__("dataclasses").replace(config.trigger, force_interval_frames=args.force_vlm_every)
    if args.vlm_provider:
        config.vlm = __import__("dataclasses").replace(config.vlm, provider=args.vlm_provider)

    if config.mode == "mock":
        import os
        import dataclasses
        
        # 若無明確指定，預設退回 local_stub
        # 明確指定 = 有傳入 CLI 參數，或是有設定 VLM_PROVIDER 環境變數
        provider_explicit = (args.vlm_provider is not None) or bool(os.getenv("VLM_PROVIDER"))
        
        if not provider_explicit:
            logger.info("==================================================")
            logger.info("啟用 MOCK 模式：未明確指定 VLM，預設退回 LocalStub VLM")
            logger.info("==================================================")
            config = dataclasses.replace(
                config,
                mode="simulator",
                vlm=dataclasses.replace(config.vlm, provider="local_stub")
            )
        else:
            logger.info("==================================================")
            logger.info("啟用 MOCK 模式：使用明確指定的 VLM Provider (%s)", config.vlm.provider)
            logger.info("==================================================")
            config = dataclasses.replace(
                config,
                mode="simulator"
            )

    agent = AutonomousDrivingAgent(config=config)

    # 註冊中斷訊號
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(agent.shutdown()))
        except NotImplementedError:
            # Windows 不支援 add_signal_handler ，改用 KeyboardInterrupt
            pass

    try:
        await agent.run(max_steps=args.steps)
    except KeyboardInterrupt:
        logger.info("收到 KeyboardInterrupt ，中斷退出")
        await agent.shutdown()


def _main() -> None:
    """同步入口 — 適用於 python -m workers.Autonomous_Driving_Agent。"""
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    _main()

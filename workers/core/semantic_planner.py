"""
語義規劃器模組 — 結合本地 A* 路徑規劃、VLM 語義規劃與記憶 replay，
產生可執行的 PlannerAction。

包含簡化的航點圖與 A* 搜尋實作。
"""

from __future__ import annotations

import heapq
import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np

from .config import (
    ActionStep,
    AgentConfig,
    PlannerAction,
    PlannerConfig,
    SceneMemoryEntry,
    VLMOutput,
    Waypoint,
)
from .edge_perception import PerceptionResult

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# 簡化航點圖（用於 A* 規劃）
# ════════════════════════════════════════════════════════════════

@dataclass
class GraphNode:
    """航點圖節點。"""
    node_id: int
    x: float
    y: float
    neighbors: list[int] = field(default_factory=list)


class _WaypointGraph:
    """
    簡化航點圖 — 用於 A* 路徑搜尋。

    TODO: 從 waypoint_graph_file 載入實際路網，或接入 PostGIS/pgRouting。
    """

    def __init__(self) -> None:
        self._nodes: dict[int, GraphNode] = {}

    def add_node(self, node: GraphNode) -> None:
        """新增節點。"""
        self._nodes[node.node_id] = node

    def add_edge(self, from_id: int, to_id: int) -> None:
        """新增雙向邊。"""
        if from_id in self._nodes and to_id in self._nodes:
            self._nodes[from_id].neighbors.append(to_id)
            self._nodes[to_id].neighbors.append(from_id)

    def get_node(self, node_id: int) -> GraphNode | None:
        """取得節點。"""
        return self._nodes.get(node_id)

    @property
    def nodes(self) -> dict[int, GraphNode]:
        """所有節點。"""
        return self._nodes

    def build_default_grid(self, rows: int = 5, cols: int = 5, spacing: float = 2.0) -> None:
        """建構預設的網格航點圖（測試用）。"""
        for r in range(rows):
            for c in range(cols):
                nid = r * cols + c
                self.add_node(GraphNode(node_id=nid, x=c * spacing, y=r * spacing))
                if c > 0:
                    self.add_edge(nid, nid - 1)
                if r > 0:
                    self.add_edge(nid, nid - cols)


# ════════════════════════════════════════════════════════════════
# A* 路徑搜尋
# ════════════════════════════════════════════════════════════════

def _a_star(
    graph: _WaypointGraph,
    start_id: int,
    goal_id: int,
) -> list[int] | None:
    """
    A* 路徑搜尋演算法。

    Args:
        graph: 航點圖。
        start_id: 起點節點 ID。
        goal_id: 終點節點 ID。

    Returns:
        節點 ID 路徑列表，若無路徑則回傳 None。
    """
    start = graph.get_node(start_id)
    goal = graph.get_node(goal_id)
    if start is None or goal is None:
        return None

    def _heuristic(a: GraphNode, b: GraphNode) -> float:
        return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)

    open_set: list[tuple[float, int]] = [(0.0, start_id)]
    came_from: dict[int, int] = {}
    g_score: dict[int, float] = {start_id: 0.0}

    while open_set:
        _, current_id = heapq.heappop(open_set)
        if current_id == goal_id:
            path = [current_id]
            while current_id in came_from:
                current_id = came_from[current_id]
                path.append(current_id)
            return list(reversed(path))

        current = graph.get_node(current_id)
        if current is None:
            continue

        for neighbor_id in current.neighbors:
            neighbor = graph.get_node(neighbor_id)
            if neighbor is None:
                continue
            tentative_g = g_score[current_id] + _heuristic(current, neighbor)
            if tentative_g < g_score.get(neighbor_id, float("inf")):
                came_from[neighbor_id] = current_id
                g_score[neighbor_id] = tentative_g
                f_score = tentative_g + _heuristic(neighbor, goal)
                heapq.heappush(open_set, (f_score, neighbor_id))

    return None


# ════════════════════════════════════════════════════════════════
# 語義規劃器
# ════════════════════════════════════════════════════════════════

class SemanticPlanner:
    """
    語義規劃器 — 整合本地 A* 規劃、VLM 語義提示與記憶 replay，
    產生可由 SimulatorAdapter 執行的 PlannerAction。
    """

    def __init__(self, config: AgentConfig | None = None) -> None:
        cfg = config or AgentConfig.load()
        self._planner_cfg: PlannerConfig = cfg.planner
        self._graph = _WaypointGraph()
        self._graph.build_default_grid()
        self._deadlock_counter: int = 0
        self._last_plan_id: str = ""
        self._oscillation_history: list[str] = []  # 最近 N 個 plan action 用於偵測震盪
        logger.info(
            "SemanticPlanner 初始化: algorithm=%s, max_waypoints=%d",
            self._planner_cfg.algorithm,
            self._planner_cfg.max_waypoints,
        )

    # ── 公開介面 ────────────────────────────────────────────────

    def plan_local(
        self,
        perception: PerceptionResult,
        current_pos: tuple[float, float],
    ) -> PlannerAction:
        """
        使用本地 A* 規劃器產生路徑。

        Args:
            perception: 邊緣感知結果。
            current_pos: 當前位置 (x, y)。

        Returns:
            PlannerAction 包含航點與動作序列。
        """
        # 尋找最近的圖節點作為起點
        start_id = self._find_nearest_node(current_pos)

        # 選擇目標（簡易版：選擇最遠的可用節點）
        goal_id = self._select_goal(perception, start_id)

        path = _a_star(self._graph, start_id, goal_id) if goal_id is not None else None

        if path is None or len(path) < 2:
            self._deadlock_counter += 1
            logger.warning(
                "本地規劃失敗: deadlock_count=%d", self._deadlock_counter
            )
            return self._create_stop_action("local_planner", "本地規劃無法找到有效路徑")

        self._deadlock_counter = 0
        waypoints = self._path_to_waypoints(path)
        action_seq = self._waypoints_to_actions(waypoints)

        plan = PlannerAction(
            plan_id=self._generate_plan_id(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            source="local_planner",
            waypoints=waypoints[: self._planner_cfg.max_waypoints],
            action_sequence=action_seq,
            validated=True,
        )
        self._track_oscillation(plan)
        return plan

    def plan_with_vlm(
        self,
        vlm_output: VLMOutput,
        perception: PerceptionResult,
    ) -> PlannerAction:
        """
        根據 VLM 語義提示產生規劃動作。

        將 VLM 的 waypoint_hints 轉為可執行的 PlannerAction。

        Args:
            vlm_output: VLM 結構化推理結果。
            perception: 當前感知結果。

        Returns:
            PlannerAction。
        """
        waypoints: list[Waypoint] = []
        action_seq: list[ActionStep] = []

        # 將 waypoint_hints 轉為動作
        for hint in vlm_output.waypoint_hints:
            direction = hint.direction or "forward"
            action_map = {
                "forward": "forward",
                "left": "turn_left",
                "right": "turn_right",
                "back": "reverse",
                "stop": "stop",
            }
            action_name = action_map.get(direction, "forward")

            # 速度映射
            speed_map = {"stop": 0.0, "slow": 1.0, "normal": 3.0}
            speed = speed_map.get(vlm_output.speed_hint, 3.0)

            action_seq.append(ActionStep(
                action=action_name,
                duration_sec=2.0,
                speed_mps=speed,
                steering_deg=0.0 if direction in ("forward", "stop", "back") else (
                    -30.0 if direction == "left" else 30.0
                ),
            ))

            # 產生粗略航點（語義轉座標的簡化版）
            dx = speed * 2.0 * (1.0 if direction != "back" else -1.0)
            dy = 0.0
            if direction == "left":
                dy = -speed * 2.0
            elif direction == "right":
                dy = speed * 2.0

            waypoints.append(Waypoint(x=dx, y=dy, speed_limit=speed))

        if vlm_output.speed_hint == "stop" and not action_seq:
            action_seq.append(ActionStep(action="stop", duration_sec=5.0, speed_mps=0.0))

        plan = PlannerAction(
            plan_id=self._generate_plan_id(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            source="semantic_planner",
            waypoints=waypoints[: self._planner_cfg.max_waypoints],
            action_sequence=action_seq,
            validated=False,                       # 需通過 SafetyGate 驗證
            vlm_proposal_accepted=None,
        )
        self._track_oscillation(plan)
        return plan

    def plan_from_replay(
        self,
        replay_candidate: SceneMemoryEntry,
        perception: PerceptionResult,
    ) -> PlannerAction:
        """
        從記憶 replay 候選產生規劃動作。

        Args:
            replay_candidate: 記憶中的成功案例。
            perception: 當前感知結果。

        Returns:
            PlannerAction。
        """
        action_seq: list[ActionStep] = []
        if replay_candidate.action_sequence:
            for step in replay_candidate.action_sequence:
                # 驗證 action 名稱有效性
                valid_actions = {
                    "forward", "turn_left", "turn_right",
                    "stop", "wait", "reverse", "slow_forward",
                }
                action_name = step.action if step.action in valid_actions else "slow_forward"
                action_seq.append(ActionStep(
                    action=action_name,
                    duration_sec=step.duration_sec,
                    speed_mps=2.0,
                ))

        if not action_seq:
            action_seq.append(ActionStep(action="slow_forward", duration_sec=2.0, speed_mps=1.0))

        return PlannerAction(
            plan_id=self._generate_plan_id(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            source="memory_replay",
            waypoints=[],
            action_sequence=action_seq,
            validated=False,
        )

    def validate_waypoints(self, waypoints: list[Waypoint]) -> bool:
        """
        驗證航點序列的合法性。

        檢查：航點數量限制、航點間距安全邊界、無重複航點。
        """
        if not waypoints:
            return False
        if len(waypoints) > self._planner_cfg.max_waypoints:
            logger.warning("航點數超過上限: %d > %d", len(waypoints), self._planner_cfg.max_waypoints)
            return False

        for i in range(1, len(waypoints)):
            dx = waypoints[i].x - waypoints[i - 1].x
            dy = waypoints[i].y - waypoints[i - 1].y
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < 0.01:
                logger.warning("航點 %d 與 %d 重複 (距離=%.4f)", i - 1, i, dist)
                return False

        return True

    # ── 規劃器狀態（供觸發策略使用）─────────────────────────────

    @property
    def deadlock_count(self) -> int:
        """當前連續死鎖計數。"""
        return self._deadlock_counter

    @property
    def oscillation_detected(self) -> bool:
        """偵測是否發生震盪（最近 N 個動作反覆交替）。"""
        if len(self._oscillation_history) < 4:
            return False
        recent = self._oscillation_history[-4:]
        return recent[0] == recent[2] and recent[1] == recent[3] and recent[0] != recent[1]

    @property
    def can_plan(self) -> bool:
        """規劃器是否能正常產生路徑。"""
        return self._deadlock_counter < self._planner_cfg.deadlock_threshold

    # ── 內部輔助 ────────────────────────────────────────────────

    def _find_nearest_node(self, pos: tuple[float, float]) -> int:
        """尋找最近的圖節點。"""
        best_id = 0
        best_dist = float("inf")
        for nid, node in self._graph.nodes.items():
            dist = math.sqrt((node.x - pos[0]) ** 2 + (node.y - pos[1]) ** 2)
            if dist < best_dist:
                best_dist = dist
                best_id = nid
        return best_id

    def _select_goal(
        self,
        perception: PerceptionResult,
        start_id: int,
    ) -> int | None:
        """選擇目標節點（簡易版：前方最遠的可用節點）。"""
        if not self._graph.nodes:
            return None

        # 簡易策略：選擇距離起點最遠的節點
        start_node = self._graph.get_node(start_id)
        if start_node is None:
            return None

        best_id: int | None = None
        best_dist = -1.0
        for nid, node in self._graph.nodes.items():
            if nid == start_id:
                continue
            dist = math.sqrt(
                (node.x - start_node.x) ** 2 + (node.y - start_node.y) ** 2
            )
            if dist > best_dist:
                best_dist = dist
                best_id = nid
        return best_id

    def _path_to_waypoints(self, path: list[int]) -> list[Waypoint]:
        """將節點路徑轉為 Waypoint 列表。"""
        waypoints: list[Waypoint] = []
        for nid in path:
            node = self._graph.get_node(nid)
            if node:
                waypoints.append(Waypoint(x=node.x, y=node.y))
        return waypoints

    @staticmethod
    def _waypoints_to_actions(waypoints: list[Waypoint]) -> list[ActionStep]:
        """將 Waypoint 序列轉為 ActionStep 序列。"""
        actions: list[ActionStep] = []
        for i in range(1, len(waypoints)):
            dx = waypoints[i].x - waypoints[i - 1].x
            dy = waypoints[i].y - waypoints[i - 1].y
            dist = math.sqrt(dx * dx + dy * dy)

            # 判斷轉向
            angle = math.atan2(dy, dx) * 180.0 / math.pi
            if abs(angle) < 30:
                action_name = "forward"
            elif angle > 0:
                action_name = "turn_right"
            else:
                action_name = "turn_left"

            speed = min(3.0, dist / 2.0) if dist > 0 else 0.0
            duration = dist / speed if speed > 0 else 1.0

            actions.append(ActionStep(
                action=action_name,
                duration_sec=round(duration, 2),
                speed_mps=round(speed, 2),
                steering_deg=round(angle, 1),
            ))
        return actions

    def _create_stop_action(self, source: str, reason: str) -> PlannerAction:
        """建構安全停車動作。"""
        return PlannerAction(
            plan_id=self._generate_plan_id(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            source=source,
            waypoints=[],
            action_sequence=[ActionStep(action="stop", duration_sec=5.0, speed_mps=0.0)],
            validated=True,
            rejection_reason=reason,
        )

    @staticmethod
    def _generate_plan_id() -> str:
        """產生唯一的 plan ID。"""
        return f"plan-{uuid.uuid4().hex[:12]}"

    def _track_oscillation(self, plan: PlannerAction) -> None:
        """追蹤動作歷史以偵測震盪。"""
        if plan.action_sequence:
            self._oscillation_history.append(plan.action_sequence[0].action)
            # 僅保留最近 10 個
            self._oscillation_history = self._oscillation_history[-10:]

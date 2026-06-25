"""
harness-cook 多Agent协商

当多个Agent同时修改同一文件/同一区域时，Negotiation 负责检测冲突并协商解决。
核心能力：
  1. 检测文件冲突（两个Agent修改同一文件）
  2. 自动合并（非重叠区域 → 自动合并）
  3. 辩论解决（重叠区域 → Agent A 和 B 各出理由，评判者裁决）
  4. 升级人工（无法自动解决 → 升级到人类）
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from harness.types import (
    NegotiationEventType, NegotiationEvent, FileConflict,
    IExecutableAgent, AgentDefinition,
)
from harness.bus import EventBus, BusEventType, BusEvent, get_bus


logger = logging.getLogger("harness.negotiation")


# ─── 冲突检测 ────────────────────────────────────────

class ConflictDetector:
    """
    冲突检测器——扫描多个Agent的产出物，找出文件冲突

    冲突类型：
      - 文件级冲突：两个Agent修改了同一文件
      - 行级冲突：两个Agent修改了重叠行范围
    """

    def detect(
        self,
        agent_artifacts: Dict[str, list],   # agent_id → [Artifact]
    ) -> list[FileConflict]:
        """检测所有Agent间的文件冲突"""
        conflicts = []

        # 收集每个Agent修改的文件路径
        file_map: Dict[str, Dict[str, str]] = {}   # path → {agent_id: content}
        for agent_id, artifacts in agent_artifacts.items():
            for artifact in artifacts:
                if artifact.path not in file_map:
                    file_map[artifact.path] = {}
                file_map[artifact.path][agent_id] = artifact.content

        # 同一文件有多个Agent修改 → 冲突
        for path, agents_content in file_map.items():
            if len(agents_content) >= 2:
                agent_ids = list(agents_content.keys())
                for i in range(len(agent_ids) - 1):
                    for j in range(i + 1, len(agent_ids)):
                        conflict = FileConflict(
                            file_path=path,
                            agent_a=agent_ids[i],
                            agent_b=agent_ids[j],
                            ranges_a=[],   # 简化：不做行级分析
                            ranges_b=[],
                            content_a=agents_content[agent_ids[i]],
                            content_b=agents_content[agent_ids[j]],
                        )
                        conflicts.append(conflict)

        return conflicts


# ─── 协商引擎 ────────────────────────────────────────

class NegotiationEngine:
    """
    协商引擎——检测冲突 + 尝试自动解决 + 辩论 + 升级

    解决策略（优先级从高到低）：
      1. 无重叠 → 自动合并
      2. 一个是新增、一个是修改 → 合并
      3. 重叠但有明确优劣 → 辩论裁决
      4. 无法判断 → 升级人工
    """

    def __init__(
        self,
        arbiter: Optional[IExecutableAgent] = None,  # 评判Agent
        bus: Optional[EventBus] = None,
    ):
        self._arbiter = arbiter
        self._bus = bus or get_bus()
        self._detector = ConflictDetector()
        self._stats = {
            "conflicts_detected": 0,
            "auto_merged": 0,
            "debate_resolved": 0,
            "escalated": 0,
        }

    def negotiate(
        self,
        agent_artifacts: Dict[str, list],   # agent_id → [Artifact]
    ) -> list[FileConflict]:
        """
        执行协商——检测冲突并尝试解决

        Returns:
            解决后的冲突列表（resolution字段已填充）
        """
        conflicts = self._detector.detect(agent_artifacts)
        self._stats["conflicts_detected"] += len(conflicts)

        if not conflicts:
            logger.info("No conflicts detected")
            return []

        # 通知事件（reserved）：conflicts 已同步检测并返回给调用方；当前无异步订阅者，保留作可观测/未来消费者接入
        self._bus.emit(BusEvent(
            type=BusEventType.CONFLICT_ALERT,
            execution_id="negotiation",
            data={
                "conflict_count": len(conflicts),
                "files": [c.file_path for c in conflicts],
            },
        ))

        # 尝试解决每个冲突
        for conflict in conflicts:
            self._resolve_conflict(conflict)

        # 发射解决完成事件
        resolved = sum(1 for c in conflicts if c.resolution)
        self._bus.emit(BusEvent(
            type=BusEventType.CONFLICT_RESOLVED,
            execution_id="negotiation",
            data={"total": len(conflicts), "resolved": resolved},
        ))

        return conflicts

    def _resolve_conflict(self, conflict: FileConflict) -> None:
        """尝试解决单个冲突"""
        # 策略1：尝试自动合并
        merged = self._try_auto_merge(conflict)
        if merged:
            conflict.resolution = "merge"
            self._stats["auto_merged"] += 1
            logger.info(f"Auto-merged conflict in {conflict.file_path}")
            return

        # 策略2：辩论裁决（如果有arbiter）
        if self._arbiter:
            result = self._debate(conflict)
            if result:
                conflict.resolution = result
                self._stats["debate_resolved"] += 1
                logger.info(f"Debate resolved conflict in {conflict.file_path}: {result}")
                return

        # 策略3：升级人工
        conflict.resolution = "escalate"
        self._stats["escalated"] += 1
        logger.warning(f"Escalated conflict in {conflict.file_path}")

        self._bus.emit(BusEvent(
            type=BusEventType.ESCALATION,
            execution_id="negotiation",
            data={
                "file_path": conflict.file_path,
                "agent_a": conflict.agent_a,
                "agent_b": conflict.agent_b,
                "reason": "Unable to resolve conflict automatically",
            },
        ))

    def _try_auto_merge(self, conflict: FileConflict) -> bool:
        """尝试自动合并——检查两份内容是否可以无缝拼接"""
        # 简化策略：如果差异行数小于总行数的20%，认为可以合并
        lines_a = conflict.content_a.splitlines()
        lines_b = conflict.content_b.splitlines()

        if not lines_a or not lines_b:
            return False

        # 计算差异比例
        diff_lines = 0
        max_lines = max(len(lines_a), len(lines_b))
        for i in range(min(len(lines_a), len(lines_b))):
            if lines_a[i] != lines_b[i]:
                diff_lines += 1
        diff_lines += abs(len(lines_a) - len(lines_b))

        diff_ratio = diff_lines / max_lines if max_lines > 0 else 1.0
        return diff_ratio < 0.2   # 20%以下的差异 → 可合并

    def _debate(self, conflict: FileConflict) -> Optional[str]:
        """辩论解决——arbiter评判两个版本"""
        if not self._arbiter:
            return None

        try:
            debate_prompt = (
                f"Two agents have conflicting changes for file {conflict.file_path}.\n"
                f"Agent A ({conflict.agent_a}) version:\n{conflict.content_a[:500]}\n\n"
                f"Agent B ({conflict.agent_b}) version:\n{conflict.content_b[:500]}\n\n"
                f"Which version is better? Reply 'a', 'b', or 'merge'."
            )
            result = self._arbiter.execute(debate_prompt, {"conflict": conflict})
            answer = result.artifacts[0].content.strip().lower() if result.artifacts else ""
            if answer in ("a", "b", "merge"):
                return answer
        except Exception as e:
            logger.error(f"Debate failed: {e}")

        return None

    def stats(self) -> dict:
        return dict(self._stats)
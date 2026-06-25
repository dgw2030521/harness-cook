"""
超时自动降级策略——独立模块

从 gate_notification.py 的 AutoDowngrade/GateManager/_execute_downgrade 提取为独立模块,
满足 Phase 5 开发计划交付物要求:
  packages/core/harness/downgrade.py — AutoDowngrade(超时降级策略)

核心能力:
  1. DowngradePolicy — 降级策略配置(超时时间+动作+回调)
  2. DowngradeTracker — 降级事件追踪(记录+统计)
  3. DowngradeEngine — 降级引擎(执行降级+通知+决策)
  4. 与 GateManager 协作: 超时未审批 → 自动降级

降级动作:
  - SKIP: 跳过门禁,继续执行(默认)
  - SIMPLIFY: 简化变更,降低风险后继续
  - ABORT: 中止执行,标记失败

设计原则:
  - 降级决策可审计(每次降级记录原因+时间+策略)
  - 降级策略可配置(不同项目/团队不同超时阈值)
  - 降级事件可追踪(统计降级率,识别瓶颈门禁)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

# 重导出 gate_notification.py 的降级类型(保持单一来源)
from harness.gate_notification import (
    AutoDowngrade,
    DowngradeAction,
    GateApprovalDecision,
)

logger = logging.getLogger("harness.downgrade")


# ═══════════════════════════════════════════════════════════
#  降级策略配置——扩展 AutoDowngrade 为更丰富的策略
# ═══════════════════════════════════════════════════════════

@dataclass
class DowngradePolicy:
    """降级策略——一个项目/团队的降级规则
    
    扩展 AutoDowngrade 的概念:
    - 不同风险级别可以有不同的超时阈值
    - 不同动作可以附带自定义回调
    - 支持策略链(HIGH风险先abort, MEDIUM风险先simplify)
    """
    name: str = "default"
    
    # 按风险级别设置超时(分钟)
    high_timeout_minutes: int = 15       # 高风险: 短超时,快速abort
    medium_timeout_minutes: int = 30     # 中风险: 中等超时
    low_timeout_minutes: int = 60        # 低风险: 长超时,给更多审批时间
    
    # 按风险级别设置降级动作
    high_action: DowngradeAction = DowngradeAction.ABORT
    medium_action: DowngradeAction = DowngradeAction.SIMPLIFY
    low_action: DowngradeAction = DowngradeAction.SKIP
    
    # 自定义回调(降级执行前的hook)
    on_downgrade_callback: Optional[Callable[[str, DowngradeAction, str], None]] = None
    
    # 通知设置
    notify_on_downgrade: bool = True
    fallback_message_template: str = "审批超时({risk}),自动降级({action})"
    
    def get_timeout(self, risk_level: str) -> int:
        """根据风险级别获取超时分钟数"""
        timeouts = {
            "high": self.high_timeout_minutes,
            "medium": self.medium_timeout_minutes,
            "low": self.low_timeout_minutes,
        }
        return timeouts.get(risk_level, self.medium_timeout_minutes)
    
    def get_action(self, risk_level: str) -> DowngradeAction:
        """根据风险级别获取降级动作"""
        actions = {
            "high": self.high_action,
            "medium": self.medium_action,
            "low": self.low_action,
        }
        return actions.get(risk_level, self.medium_action)
    
    def make_auto_downgrade(self, risk_level: str = "medium") -> AutoDowngrade:
        """根据风险级别生成 AutoDowngrade 实例"""
        return AutoDowngrade(
            after_minutes=self.get_timeout(risk_level),
            action=self.get_action(risk_level),
            notify_on_downgrade=self.notify_on_downgrade,
            fallback_message=self.fallback_message_template.format(
                risk=risk_level,
                action=self.get_action(risk_level).value,
            ),
        )


# ═══════════════════════════════════════════════════════════
#  降级事件记录——每次降级的审计轨迹
# ═══════════════════════════════════════════════════════════

@dataclass
class DowngradeEvent:
    """降级事件——记录一次自动降级的完整信息"""
    gate_id: str = ""
    risk_level: str = ""
    action: DowngradeAction = DowngradeAction.SKIP
    reason: str = ""
    timeout_minutes: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    policy_name: str = ""
    notified: bool = False
    
    def summary(self) -> str:
        """事件概要"""
        return (
            f"[{self.action.value}] gate={self.gate_id} "
            f"risk={self.risk_level} reason={self.reason} "
            f"policy={self.policy_name}"
        )


# ═══════════════════════════════════════════════════════════
#  降级事件追踪器——统计降级率、识别瓶颈
# ═══════════════════════════════════════════════════════════

class DowngradeTracker:
    """降级事件追踪器——审计降级决策
    
    功能:
    1. 记录每次降级事件(时间/原因/动作)
    2. 统计降级率(降级次数/总审批次数)
    3. 识别瓶颈门禁(频繁超时的gate_id)
    4. 按风险级别统计分布
    """
    
    def __init__(self):
        self._events: List[DowngradeEvent] = []
        self._lock = threading.Lock()
    
    def record(self, event: DowngradeEvent) -> None:
        """记录降级事件"""
        with self._lock:
            self._events.append(event)
            logger.info(f"降级事件: {event.summary()}")
    
    def get_events(
        self,
        gate_id: Optional[str] = None,
        risk_level: Optional[str] = None,
        limit: int = 50,
    ) -> List[DowngradeEvent]:
        """查询降级事件"""
        with self._lock:
            events = list(self._events)
        
        if gate_id:
            events = [e for e in events if e.gate_id == gate_id]
        if risk_level:
            events = [e for e in events if e.risk_level == risk_level]
        
        return events[-limit:]
    
    def stats(self) -> Dict[str, Any]:
        """降级统计"""
        with self._lock:
            total = len(self._events)
        
        # 按动作分布
        action_counts: Dict[str, int] = {}
        for e in self._events:
            key = e.action.value
            action_counts[key] = action_counts.get(key, 0) + 1
        
        # 按风险级别分布
        risk_counts: Dict[str, int] = {}
        for e in self._events:
            key = e.risk_level
            risk_counts[key] = risk_counts.get(key, 0) + 1
        
        # 瓶颈门禁(降级次数最多的gate_id)
        gate_counts: Dict[str, int] = {}
        for e in self._events:
            if e.gate_id:
                gate_counts[e.gate_id] = gate_counts.get(e.gate_id, 0) + 1
        
        bottleneck_gates = sorted(
            gate_counts.items(), key=lambda x: x[1], reverse=True
        )[:5]
        
        return {
            "total_downgrades": total,
            "by_action": action_counts,
            "by_risk": risk_counts,
            "bottleneck_gates": [
                {"gate_id": g, "count": c} for g, c in bottleneck_gates
            ],
        }
    
    def clear(self) -> None:
        """清空事件记录"""
        with self._lock:
            self._events.clear()


# ═══════════════════════════════════════════════════════════
#  降级引擎——执行降级决策
# ═══════════════════════════════════════════════════════════

class DowngradeEngine:
    """降级引擎——统一管控自动降级
    
    与 GateManager 协作:
    - GateManager 创建门禁 + 发送通知
    - DowngradeEngine 监控超时 + 执行降级
    
    工作流:
    1. register_gate(): 注册需要监控的门禁
    2. check_timeout(): 检查是否超时
    3. execute_downgrade(): 执行降级动作
    4. 记录降级事件到 tracker
    """
    
    def __init__(
        self,
        policy: Optional[DowngradePolicy] = None,
        tracker: Optional[DowngradeTracker] = None,
    ):
        self._policy = policy or DowngradePolicy()
        self._tracker = tracker or DowngradeTracker()
        self._lock = threading.Lock()
    
    @property
    def policy(self) -> DowngradePolicy:
        """当前降级策略"""
        return self._policy
    
    @property
    def tracker(self) -> DowngradeTracker:
        """降级事件追踪器"""
        return self._tracker
    
    def execute_downgrade(
        self,
        gate_id: str,
        risk_level: str = "medium",
        reason: str = "",
    ) -> GateApprovalDecision:
        """执行降级——根据策略选择动作
        
        返回:
          GateApprovalDecision 对应降级结果:
          - SKIP → APPROVED_WITH_CONDITIONS (跳过门禁,有条件通过)
          - SIMPLIFY → APPROVED_WITH_CONDITIONS (简化变更,有条件通过)
          - ABORT → REJECTED (中止执行)
        """
        action = self._policy.get_action(risk_level)
        
        # 执行回调(降级前hook)
        if self._policy.on_downgrade_callback:
            try:
                self._policy.on_downgrade_callback(gate_id, action, reason)
            except Exception as exc:
                logger.warning(f"降级回调执行失败: {exc}")
        
        # 执行降级
        if action == DowngradeAction.SKIP:
            decision = GateApprovalDecision.APPROVED
            reason_str = reason or f"超时降级: 跳过门禁({gate_id})"
        elif action == DowngradeAction.SIMPLIFY:
            decision = GateApprovalDecision.APPROVED
            reason_str = reason or f"超时降级: 简化变更({gate_id})"
        elif action == DowngradeAction.ABORT:
            decision = GateApprovalDecision.REJECTED
            reason_str = reason or f"超时降级: 中止执行({gate_id})"
        else:
            decision = GateApprovalDecision.REJECTED
            reason_str = f"未知降级动作({action})"
        
        # 记录降级事件
        event = DowngradeEvent(
            gate_id=gate_id,
            risk_level=risk_level,
            action=action,
            reason=reason_str,
            timeout_minutes=self._policy.get_timeout(risk_level),
            policy_name=self._policy.name,
            notified=self._policy.notify_on_downgrade,
        )
        self._tracker.record(event)
        
        logger.info(f"降级执行: gate={gate_id} action={action.value} decision={decision.value}")
        return decision
    
    def make_auto_downgrade_for_risk(self, risk_level: str) -> AutoDowngrade:
        """根据风险级别生成 AutoDowngrade(用于 GateManager)"""
        return self._policy.make_auto_downgrade(risk_level)
    
    def stats(self) -> Dict[str, Any]:
        """引擎统计(策略+追踪合并)"""
        return {
            "policy": {
                "name": self._policy.name,
                "high_timeout": self._policy.high_timeout_minutes,
                "medium_timeout": self._policy.medium_timeout_minutes,
                "low_timeout": self._policy.low_timeout_minutes,
                "high_action": self._policy.high_action.value,
                "medium_action": self._policy.medium_action.value,
                "low_action": self._policy.low_action.value,
            },
            "tracker": self._tracker.stats(),
        }


# ═══════════════════════════════════════════════════════════
#  工厂函数
# ═══════════════════════════════════════════════════════════

_engines: Dict[str, DowngradeEngine] = {}
_engine_lock = threading.Lock()


def get_downgrade_engine(
    policy_name: Optional[str] = None,
    policy: Optional[DowngradePolicy] = None,
) -> DowngradeEngine:
    """获取降级引擎(按策略名隔离)"""
    key = policy_name or "default"
    with _engine_lock:
        if key not in _engines:
            _engines[key] = DowngradeEngine(policy=policy)
    return _engines[key]
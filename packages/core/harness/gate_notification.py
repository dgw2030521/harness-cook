"""
Gate通知 + 降级机制——从 nextX GateNotification/AutoDowngrade 提取的设计蓝图

E-9 重构：GateManager EventBus 回调模式
  原始缺陷：wait_for_approval() 使用 time.sleep(0.5) 轮询通知器
  修复方案：
    1. wait_for_approval() 发出 GATE_APPROVAL_REQUEST 事件
    2. 订阅 GATE_APPROVAL_DECISION 事件
    3. 用 threading.Event.wait() 替代 time.sleep(0.5) 轮询
    4. MCP 场景：harness_gate_approve 工具发出 GATE_APPROVAL_DECISION 事件

  触发路径声明（E-9）：
    路径1: wait_for_approval() → GATE_APPROVAL_REQUEST 事件 → EventBus
    路径2: MCP harness_gate_approve → GATE_APPROVAL_DECISION 事件 → EventBus → on_approval_decision 回调
    路径3: 超时降级 → _execute_downgrade()（不经过 EventBus）

2 双通道设计:
    1. validate(ctx) → ValidationResult — 检测问题
    2. auto_fix(ctx, issues) → ValidationResult — 自动修复

    autoFix可选——不是所有Validator都能自动修复。

    与Phase 4 Validator协作:
    - DestructiveChangeValidator: 检测破坏性变更 → CRITICAL severity
    - MaxChangesValidator: 检测变更数量超限 → HIGH severity
    """

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol

logger = logging.getLogger("harness.gate")


# ═══════════════════════════════════════════════════════════
#  通知优先级——从 nextX NotificationPriority 提取
# ═══════════════════════════════════════════════════════════

class NotificationPriority(Enum):
    """通知优先级——3级"""
    URGENT = "urgent"    # 紧急: 需立即审批(阻断流程)
    NORMAL = "normal"    # 正常: 需在deadline前审批
    INFO = "info"        # 信息: 仅通知,不需审批


# ═══════════════════════════════════════════════════════════
#  降级动作——从 nextX DowngradeAction 提取
# ═══════════════════════════════════════════════════════════

class DowngradeAction(Enum):
    """超时降级动作——3种
    
    skip: 跳过审批,继续执行(最低风险)
    simplify: 简化审批,降低验证级别(中等风险)
    abort: 中止执行(零风险但任务失败)
    """
    SKIP = "skip"
    SIMPLIFY = "simplify"
    ABORT = "abort"


# ═══════════════════════════════════════════════════════════
#  审批决策——从 nextX ApprovalDecision 提取
# ═══════════════════════════════════════════════════════════

class GateApprovalDecision(Enum):
    """审批决策——4种结果"""
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


# ═══════════════════════════════════════════════════════════
#  Gate通知——从 nextX GateNotification 提取
# ═══════════════════════════════════════════════════════════

@dataclass
class GateNotification:
    """Gate审批通知——异步人工审批
    
    从 nextX GateNotification 提取:
    - gate_id: 唯一标识(关联Phase 1的GateDefinition)
    - recipient: 通知接收者(人/角色)
    - message: 通知内容
    - action_url: 审批链接
    - deadline: 超时时间
    - priority: 通知优先级
    """
    gate_id: str = ""
    recipient: str = ""
    message: str = ""
    action_url: Optional[str] = None
    deadline: Optional[datetime] = None
    priority: NotificationPriority = NotificationPriority.NORMAL
    created_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
    
    def is_expired(self) -> bool:
        """是否已超时"""
        if self.deadline is None:
            return False
        return datetime.now(timezone.utc) > self.deadline
    
    def time_remaining(self) -> Optional[timedelta]:
        """剩余时间"""
        if self.deadline is None:
            return None
        remaining = self.deadline - datetime.now(timezone.utc)
        return remaining if remaining > timedelta(0) else timedelta(0)
    
    def summary(self) -> str:
        """通知概要"""
        pri = self.priority.value
        remaining = ""
        if self.deadline:
            remaining = f", 剩余{self.time_remaining().total_seconds()}秒"
        return f"[{pri}] Gate {self.gate_id}: {self.message}{remaining}"


# ═══════════════════════════════════════════════════════════
#  自动降级配置——从 nextX AutoDowngrade 提取
# ═══════════════════════════════════════════════════════════

@dataclass
class AutoDowngrade:
    """自动降级配置——超时后的降级策略
    
    从 nextX AutoDowngrade 提取:
    - after_minutes: 超时多少分钟后降级
    - action: 降级动作(skip/simplify/abort)
    - notify_on_downgrade: 降级时是否通知
    """
    after_minutes: int = 30           # 默认30分钟超时
    action: DowngradeAction = DowngradeAction.SKIP
    notify_on_downgrade: bool = True   # 降级时通知
    fallback_message: str = "审批超时,自动降级"
    
    def calculate_deadline(self, created_at: Optional[datetime] = None) -> datetime:
        """计算超时时间"""
        base = created_at or datetime.now(timezone.utc)
        return base + timedelta(minutes=self.after_minutes)


# ═══════════════════════════════════════════════════════════
#  INotifier — Protocol接口
# ═══════════════════════════════════════════════════════════

class INotifier(Protocol):
    """通知发送接口——从 nextX INotifier 提取
    
    首期只做本地日志通知:
    - send(): 发送通知到指定渠道
    - receive(): 接收审批决策
    
    未来扩展:
    - Slack/邮件/Webhook通知
    - CLI交互审批
    """
    def send(self, notification: GateNotification) -> bool: ...
    def receive(self, gate_id: str) -> Optional[GateApprovalDecision]: ...


class LocalNotifier:
    """本地日志通知器——首期实现
    
    所有通知只记录到日志,不做实际推送。
    审批决策通过手动调用decide()注入。
    """
    
    def __init__(self):
        self._pending: Dict[str, GateNotification] = {}
        self._decisions: Dict[str, GateApprovalDecision] = {}
    
    def send(self, notification: GateNotification) -> bool:
        """发送通知——记录到日志+存储"""
        self._pending[notification.gate_id] = notification
        logger.info(f"Gate通知: {notification.summary()}")
        return True
    
    def receive(self, gate_id: str) -> Optional[GateApprovalDecision]:
        """接收审批决策"""
        return self._decisions.get(gate_id)
    
    def decide(self, gate_id: str, decision: GateApprovalDecision) -> None:
        """手动注入审批决策(模拟人工审批)"""
        self._decisions[gate_id] = decision
        logger.info(f"审批决策: {gate_id} → {decision.value}")
    
    def list_pending(self) -> List[GateNotification]:
        """列出待审批通知"""
        return list(self._pending.values())
    
    def clear(self) -> None:
        """清空所有待审批和决策"""
        self._pending.clear()
        self._decisions.clear()


# ═══════════════════════════════════════════════════════════
#  审批记录——审计追溯
# ═══════════════════════════════════════════════════════════

@dataclass
class GateApprovalRecord:
    """审批记录——审计追溯
    
    记录:
    - gate_id: 唯一标识
    - decision: 审批决策
    - decided_at: 决策时间
    - decided_by: 决策者(人工/系统降级)
    - reason: 决策原因
    """
    gate_id: str = ""
    decision: GateApprovalDecision = GateApprovalDecision.APPROVED
    decided_at: Optional[datetime] = None
    decided_by: str = ""          # "human" | "system-downgrade"
    reason: str = ""
    
    def __post_init__(self):
        if self.decided_at is None:
            self.decided_at = datetime.now(timezone.utc)
    
    def summary(self) -> str:
        """记录概要"""
        who = self.decided_by or "unknown"
        return f"Gate {self.gate_id}: {self.decision.value} (by {who}, {self.reason})"


# ═══════════════════════════════════════════════════════════
#  GateManager——生命周期管理
# ═══════════════════════════════════════════════════════════

class GateManager:
    """Gate生命周期管理——创建gate+等待审批+超时降级（E-9 EventBus 回调模式）

    设计:
    1. create_gate(): 创建审批gate,发送通知
    2. wait_for_approval(): 发出 GATE_APPROVAL_REQUEST 事件，用 threading.Event 等待回调
    3. on_approval_decision(): EventBus 回调——收到 GATE_APPROVAL_DECISION 事件时唤醒等待
    4. 超时降级: 自动执行降级动作

    E-9 变更：
    - __init__ 新增 bus 参数，订阅 GATE_APPROVAL_DECISION 事件
    - wait_for_approval() 不再用 time.sleep(0.5) 轮询
    - 改为发出 GATE_APPROVAL_REQUEST 事件 + threading.Event.wait()
    - on_approval_decision() 回调收到决策后唤醒等待线程

    与Phase 1 GateDefinition桥接:
    - GateDefinition.require_review=True → 触发审批通知
    """

    def __init__(
        self,
        notifier: Optional[INotifier] = None,
        downgrade: Optional[AutoDowngrade] = None,
        bus: Optional[Any] = None,  # EventBus 实例（E-9）
    ):
        self._notifier = notifier or LocalNotifier()
        self._downgrade = downgrade or AutoDowngrade()
        self._gates: Dict[str, GateNotification] = {}
        self._records: List[GateApprovalRecord] = []

        # E-9：EventBus 回调模式
        self._bus = bus
        self._pending_decisions: Dict[str, GateApprovalDecision] = {}
        self._pending_events: Dict[str, threading.Event] = {}

        if self._bus is not None:
            self._subscribe_to_bus()
    
    def create_gate(
        self,
        gate_id: str,
        recipient: str = "default",
        message: str = "",
        priority: NotificationPriority = NotificationPriority.NORMAL,
        deadline_minutes: Optional[int] = None,
    ) -> GateNotification:
        """创建审批gate——发送通知
        
        Args:
            gate_id: 唯一标识
            recipient: 通知接收者
            message: 通知内容
            priority: 优先级
            deadline_minutes: 超时分钟数(None=使用downgrade配置)
        """
        deadline = None
        if deadline_minutes is not None:
            deadline = datetime.now(timezone.utc) + timedelta(minutes=deadline_minutes)
        elif self._downgrade.after_minutes > 0:
            deadline = self._downgrade.calculate_deadline()
        
        notification = GateNotification(
            gate_id=gate_id,
            recipient=recipient,
            message=message,
            deadline=deadline,
            priority=priority,
        )
        
        self._gates[gate_id] = notification
        self._notifier.send(notification)
        return notification
    
    def _subscribe_to_bus(self) -> None:
        """订阅 GATE_APPROVAL_DECISION 事件（E-9）"""
        try:
            from harness.types import BusEventType
            self._bus.subscribe(BusEventType.GATE_APPROVAL_DECISION, self.on_approval_decision)
            logger.info("GateManager subscribed to GATE_APPROVAL_DECISION events")
        except Exception as e:
            logger.warning(f"GateManager failed to subscribe to bus: {e}")

    def on_approval_decision(self, event: Any) -> None:
        """E-9：EventBus 回调——收到 GATE_APPROVAL_DECISION 事件时唤醒等待

        事件数据格式：
          {
            "gate_id": str,
            "decision": str (approved/rejected/cancelled),
            "decided_by": str,
            "reason": str,
          }
        """
        gate_id = event.data.get("gate_id", "")
        decision_str = event.data.get("decision", "")
        decided_by = event.data.get("decided_by", "human")
        reason = event.data.get("reason", "")

        # 将决策字符串转为 GateApprovalDecision
        try:
            from harness.types import BusEventType
            decision = GateApprovalDecision(decision_str)
        except ValueError:
            logger.warning(f"Unknown approval decision: {decision_str}")
            decision = GateApprovalDecision.APPROVED

        # 存储决策并唤醒等待线程
        self._pending_decisions[gate_id] = decision

        # 唤醒 threading.Event
        wait_event = self._pending_events.get(gate_id)
        if wait_event is not None:
            wait_event.set()

        logger.info(f"Approval decision received: gate={gate_id}, decision={decision.value}, by={decided_by}")

    def wait_for_approval(
        self,
        gate_id: str,
        timeout_seconds: Optional[int] = None,
    ) -> GateApprovalDecision:
        """等待审批——E-9：EventBus 回调模式替代 time.sleep 轮询

        流程：
        1. 发出 GATE_APPROVAL_REQUEST 事件（通知审批系统）
        2. 创建 threading.Event 等待回调
        3. 阻塞等待 threading.Event.wait(timeout)
        4. 超时则执行降级

        Args:
            gate_id: 等待的gate ID
            timeout_seconds: 本地超时秒数(None=使用downgrade配置)

        Returns:
            审批决策(approved/rejected/timeout/cancelled)
        """
        max_wait = timeout_seconds if timeout_seconds is not None else self._downgrade.after_minutes * 60

        # E-9：发出 GATE_APPROVAL_REQUEST 事件
        if self._bus is not None:
            try:
                from harness.types import BusEventType, BusEvent
                request_event = BusEvent(
                    type=BusEventType.GATE_APPROVAL_REQUEST,
                    execution_id=gate_id,
                    data={
                        "gate_id": gate_id,
                        "message": self._gates.get(gate_id, GateNotification()).message,
                        "priority": self._gates.get(gate_id, GateNotification()).priority.value,
                        "deadline_seconds": max_wait,
                    },
                )
                self._bus.emit(request_event)
                logger.info(f"GATE_APPROVAL_REQUEST emitted for gate={gate_id}")
            except Exception as e:
                logger.warning(f"Failed to emit GATE_APPROVAL_REQUEST: {e}")

        # E-9：用 threading.Event 等待回调替代 time.sleep 轮询
        wait_event = threading.Event()
        self._pending_events[gate_id] = wait_event

        # E-9 修复：wait 前检查是否已有预先注入的决策
        # 覆盖"decide 在 wait 之前调用"的场景——此时 _pending_events 尚未创建，
        # on_approval_decision 的 Event.set() 无目标，wait 会误判超时降级。
        # 两条来源：bus 路径（_pending_decisions）+ 同步路径（notifier.receive）
        existing = self._pending_decisions.pop(gate_id, None)
        if existing is None and self._notifier is not None:
            try:
                existing = self._notifier.receive(gate_id)
            except Exception as e:
                logger.warning(f"Failed to query notifier for existing decision: {e}")
        if existing is not None:
            self._pending_events.pop(gate_id, None)
            record = GateApprovalRecord(
                gate_id=gate_id,
                decision=existing,
                decided_by="human",
                reason=f"人工审批: {existing.value}",
            )
            self._records.append(record)
            return existing

        # 阻塞等待——直到 on_approval_decision 回调唤醒或超时
        received = wait_event.wait(timeout=max_wait)

        # 清理等待事件
        self._pending_events.pop(gate_id, None)

        if received:
            # 收到了审批决策
            decision = self._pending_decisions.pop(gate_id, GateApprovalDecision.APPROVED)
            record = GateApprovalRecord(
                gate_id=gate_id,
                decision=decision,
                decided_by="human",
                reason=f"人工审批: {decision.value}",
            )
            self._records.append(record)
            return decision

        # 超时——执行降级
        downgrade_decision = self._execute_downgrade(gate_id)
        return downgrade_decision
    
    def _execute_downgrade(self, gate_id: str) -> GateApprovalDecision:
        """执行超时降级"""
        action = self._downgrade.action
        
        if action == DowngradeAction.SKIP:
            decision = GateApprovalDecision.TIMEOUT
            reason = f"超时{self._downgrade.after_minutes}分钟,自动跳过审批"
        elif action == DowngradeAction.SIMPLIFY:
            decision = GateApprovalDecision.TIMEOUT
            reason = f"超时{self._downgrade.after_minutes}分钟,简化审批"
        elif action == DowngradeAction.ABORT:
            decision = GateApprovalDecision.REJECTED
            reason = f"超时{self._downgrade.after_minutes}分钟,自动中止"
        else:
            decision = GateApprovalDecision.TIMEOUT
            reason = f"超时降级: {action.value}"
        
        record = GateApprovalRecord(
            gate_id=gate_id,
            decision=decision,
            decided_by="system-downgrade",
            reason=reason,
        )
        self._records.append(record)
        
        if self._downgrade.notify_on_downgrade:
            logger.info(f"Gate降级: {reason}")
        
        return decision
    
    def get_record(self, gate_id: str) -> Optional[GateApprovalRecord]:
        """获取审批记录"""
        for record in self._records:
            if record.gate_id == gate_id:
                return record
        return None
    
    def list_records(self) -> List[GateApprovalRecord]:
        """列出所有审批记录"""
        return list(self._records)
    
    def cancel_gate(self, gate_id: str) -> None:
        """取消gate"""
        record = GateApprovalRecord(
            gate_id=gate_id,
            decision=GateApprovalDecision.CANCELLED,
            decided_by="system",
            reason="主动取消",
        )
        self._records.append(record)
        if gate_id in self._gates:
            del self._gates[gate_id]
    
    def stats(self) -> Dict[str, Any]:
        """统计信息"""
        approved = sum(1 for r in self._records if r.decision == GateApprovalDecision.APPROVED)
        rejected = sum(1 for r in self._records if r.decision == GateApprovalDecision.REJECTED)
        timeout = sum(1 for r in self._records if r.decision == GateApprovalDecision.TIMEOUT)
        cancelled = sum(1 for r in self._records if r.decision == GateApprovalDecision.CANCELLED)
        
        return {
            "total_gates": len(self._gates),
            "total_records": len(self._records),
            "approved": approved,
            "rejected": rejected,
            "timeout": timeout,
            "cancelled": cancelled,
        }


# ═══════════════════════════════════════════════════════════
#  单例工厂
# ═══════════════════════════════════════════════════════════

_gate_managers: Dict[str, GateManager] = {}
_gate_managers_lock = threading.Lock()


def get_gate_manager(project_name: Optional[str] = None) -> GateManager:
    """获取GateManager(按项目隔离)——E-9：自动绑定项目级 EventBus"""
    key = project_name or "default"
    with _gate_managers_lock:
        if key not in _gate_managers:
            try:
                from harness.bus import get_bus
                bus = get_bus(project_name=project_name)
                _gate_managers[key] = GateManager(bus=bus)
            except Exception:
                # bus 未初始化时退化为无 EventBus 模式（仍可用 LocalNotifier）
                _gate_managers[key] = GateManager()
        return _gate_managers[key]
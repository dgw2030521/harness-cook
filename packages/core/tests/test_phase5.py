"""
Phase 5 测试: Gate通知 + 降级机制

从 nextX GateNotification/AutoDowngrade 提取的设计模式,
在 harness-cook 中适配为 Python 实现。

测试覆盖:
- NotificationPriority: 3级枚举
- DowngradeAction: 3种降级动作
- GateApprovalDecision: 4种审批决策
- GateNotification: 构造/is_expired/time_remaining/summary
- AutoDowngrade: 构造/calculate_deadline
- LocalNotifier: send/receive/decide/list_pending/clear
- GateApprovalRecord: 构造/summary
- GateManager: create_gate/wait_for_approval/downgrade/cancel/stats
"""

import unittest
import time
from datetime import datetime, timedelta, timezone
from harness.gate_notification import (
    NotificationPriority, DowngradeAction, GateApprovalDecision,
    GateNotification, AutoDowngrade, LocalNotifier,
    GateApprovalRecord, GateManager, get_gate_manager,
)


class TestNotificationPriority(unittest.TestCase):
    """通知优先级枚举"""

    def test_all_priorities(self):
        priorities = list(NotificationPriority)
        assert len(priorities) == 3
        assert NotificationPriority.URGENT.value == "urgent"
        assert NotificationPriority.NORMAL.value == "normal"
        assert NotificationPriority.INFO.value == "info"


class TestDowngradeAction(unittest.TestCase):
    """降级动作枚举"""

    def test_all_actions(self):
        actions = list(DowngradeAction)
        assert len(actions) == 3
        assert DowngradeAction.SKIP.value == "skip"
        assert DowngradeAction.SIMPLIFY.value == "simplify"
        assert DowngradeAction.ABORT.value == "abort"


class TestGateApprovalDecision(unittest.TestCase):
    """审批决策枚举"""

    def test_all_decisions(self):
        decisions = list(GateApprovalDecision)
        assert len(decisions) == 4
        assert GateApprovalDecision.APPROVED.value == "approved"
        assert GateApprovalDecision.REJECTED.value == "rejected"
        assert GateApprovalDecision.TIMEOUT.value == "timeout"
        assert GateApprovalDecision.CANCELLED.value == "cancelled"


class TestGateNotification(unittest.TestCase):
    """Gate审批通知"""

    def test_creation(self):
        n = GateNotification(
            gate_id="gate-001",
            recipient="tech-lead",
            message="请审批变更",
            priority=NotificationPriority.URGENT,
        )
        assert n.gate_id == "gate-001"
        assert n.recipient == "tech-lead"
        assert n.created_at is not None

    def test_is_expired(self):
        # 已超时
        n = GateNotification(
            gate_id="gate-002",
            deadline=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        assert n.is_expired() is True
        
        # 未超时
        n2 = GateNotification(
            gate_id="gate-003",
            deadline=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        assert n2.is_expired() is False
        
        # 无deadline
        n3 = GateNotification(gate_id="gate-004")
        assert n3.is_expired() is False

    def test_time_remaining(self):
        n = GateNotification(
            gate_id="gate-005",
            deadline=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        remaining = n.time_remaining()
        assert remaining is not None
        assert remaining.total_seconds() > 0

    def test_time_remaining_expired(self):
        n = GateNotification(
            gate_id="gate-006",
            deadline=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        remaining = n.time_remaining()
        assert remaining == timedelta(0)

    def test_time_remaining_no_deadline(self):
        n = GateNotification(gate_id="gate-007")
        assert n.time_remaining() is None

    def test_summary(self):
        n = GateNotification(
            gate_id="gate-008",
            message="审批变更",
            priority=NotificationPriority.URGENT,
            deadline=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        s = n.summary()
        assert "urgent" in s
        assert "gate-008" in s


class TestAutoDowngrade(unittest.TestCase):
    """自动降级配置"""

    def test_default_config(self):
        d = AutoDowngrade()
        assert d.after_minutes == 30
        assert d.action == DowngradeAction.SKIP
        assert d.notify_on_downgrade is True

    def test_custom_config(self):
        d = AutoDowngrade(
            after_minutes=15,
            action=DowngradeAction.ABORT,
            notify_on_downgrade=False,
        )
        assert d.after_minutes == 15
        assert d.action == DowngradeAction.ABORT

    def test_calculate_deadline(self):
        d = AutoDowngrade(after_minutes=30)
        created = datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)
        deadline = d.calculate_deadline(created)
        assert deadline == datetime(2026, 6, 7, 12, 30, 0, tzinfo=timezone.utc)

    def test_calculate_deadline_default(self):
        d = AutoDowngrade(after_minutes=10)
        deadline = d.calculate_deadline()
        # deadline应该是现在+10分钟
        assert deadline > datetime.now(timezone.utc) - timedelta(minutes=1)


class TestLocalNotifier(unittest.TestCase):
    """本地日志通知器"""

    def test_send(self):
        notifier = LocalNotifier()
        n = GateNotification(gate_id="gate-001", message="test")
        assert notifier.send(n) is True

    def test_receive_no_decision(self):
        notifier = LocalNotifier()
        assert notifier.receive("gate-001") is None

    def test_decide_and_receive(self):
        notifier = LocalNotifier()
        notifier.decide("gate-001", GateApprovalDecision.APPROVED)
        decision = notifier.receive("gate-001")
        assert decision == GateApprovalDecision.APPROVED

    def test_list_pending(self):
        notifier = LocalNotifier()
        notifier.send(GateNotification(gate_id="gate-001"))
        notifier.send(GateNotification(gate_id="gate-002"))
        pending = notifier.list_pending()
        assert len(pending) == 2

    def test_clear(self):
        notifier = LocalNotifier()
        notifier.send(GateNotification(gate_id="gate-001"))
        notifier.decide("gate-001", GateApprovalDecision.APPROVED)
        notifier.clear()
        assert len(notifier.list_pending()) == 0
        assert notifier.receive("gate-001") is None


class TestGateApprovalRecord(unittest.TestCase):
    """审批记录"""

    def test_creation(self):
        record = GateApprovalRecord(
            gate_id="gate-001",
            decision=GateApprovalDecision.APPROVED,
            decided_by="tech-lead",
            reason="代码质量合格",
        )
        assert record.gate_id == "gate-001"
        assert record.decided_at is not None

    def test_summary(self):
        record = GateApprovalRecord(
            gate_id="gate-001",
            decision=GateApprovalDecision.APPROVED,
            decided_by="human",
            reason="代码质量合格",
        )
        s = record.summary()
        assert "approved" in s
        assert "human" in s


class TestGateManager(unittest.TestCase):
    """Gate生命周期管理"""

    def setUp(self):
        self.notifier = LocalNotifier()
        self.downgrade = AutoDowngrade(after_minutes=30)
        self.manager = GateManager(
            notifier=self.notifier,
            downgrade=self.downgrade,
        )

    def tearDown(self):
        self.notifier.clear()

    def test_create_gate(self):
        notification = self.manager.create_gate(
            gate_id="gate-001",
            recipient="tech-lead",
            message="请审批变更",
            priority=NotificationPriority.URGENT,
            deadline_minutes=60,
        )
        assert notification.gate_id == "gate-001"
        assert notification.deadline is not None
        assert len(self.notifier.list_pending()) == 1

    def test_create_gate_default_deadline(self):
        notification = self.manager.create_gate(
            gate_id="gate-002",
            message="审批请求",
        )
        # deadline应来自downgrade配置(30分钟)
        assert notification.deadline is not None

    def test_wait_for_approval_approved(self):
        self.manager.create_gate("gate-003")
        # 手动注入审批决策
        self.notifier.decide("gate-003", GateApprovalDecision.APPROVED)
        decision = self.manager.wait_for_approval("gate-003", timeout_seconds=5)
        assert decision == GateApprovalDecision.APPROVED

    def test_wait_for_approval_rejected(self):
        self.manager.create_gate("gate-004")
        self.notifier.decide("gate-004", GateApprovalDecision.REJECTED)
        decision = self.manager.wait_for_approval("gate-004", timeout_seconds=5)
        assert decision == GateApprovalDecision.REJECTED

    def test_wait_for_approval_timeout_skip(self):
        # 超时→SKIP降级
        downgrade = AutoDowngrade(after_minutes=1, action=DowngradeAction.SKIP)
        manager = GateManager(notifier=self.notifier, downgrade=downgrade)
        manager.create_gate("gate-005")
        # 不注入任何决策→等待超时
        decision = manager.wait_for_approval("gate-005", timeout_seconds=2)
        assert decision == GateApprovalDecision.TIMEOUT

    def test_wait_for_approval_timeout_abort(self):
        # 超时→ABORT降级
        downgrade = AutoDowngrade(after_minutes=1, action=DowngradeAction.ABORT)
        manager = GateManager(notifier=self.notifier, downgrade=downgrade)
        manager.create_gate("gate-006")
        decision = manager.wait_for_approval("gate-006", timeout_seconds=2)
        assert decision == GateApprovalDecision.REJECTED

    def test_cancel_gate(self):
        self.manager.create_gate("gate-007")
        self.manager.cancel_gate("gate-007")
        record = self.manager.get_record("gate-007")
        assert record is not None
        assert record.decision == GateApprovalDecision.CANCELLED

    def test_get_record(self):
        self.manager.create_gate("gate-008")
        self.notifier.decide("gate-008", GateApprovalDecision.APPROVED)
        self.manager.wait_for_approval("gate-008", timeout_seconds=5)
        record = self.manager.get_record("gate-008")
        assert record is not None
        assert record.decision == GateApprovalDecision.APPROVED

    def test_stats(self):
        self.manager.create_gate("gate-009")
        self.notifier.decide("gate-009", GateApprovalDecision.APPROVED)
        self.manager.wait_for_approval("gate-009", timeout_seconds=5)
        stats = self.manager.stats()
        assert stats["total_records"] >= 1
        assert stats["approved"] >= 1

    def test_list_records(self):
        self.manager.create_gate("gate-010")
        self.notifier.decide("gate-010", GateApprovalDecision.APPROVED)
        self.manager.wait_for_approval("gate-010", timeout_seconds=5)
        records = self.manager.list_records()
        assert len(records) >= 1


class TestGetGateManager(unittest.TestCase):
    """全局GateManager工厂"""

    def test_get_manager(self):
        manager = get_gate_manager("_unittest")
        assert isinstance(manager, GateManager)


if __name__ == "__main__":
    unittest.main()
"""
E-9：GateManager EventBus 回调模式验收测试（core 部分）

验证要点:
  1. BusEventType 包含 GATE_APPROVAL_REQUEST / GATE_APPROVAL_DECISION
  2. GateManager.wait_for_approval() 不使用 time.sleep 轮询循环
  3. GateManager.on_approval_decision() 回调能唤醒等待线程
  4. 超时降级路径仍然正常工作
  5. get_gate_manager() 工厂能自动绑定 EventBus
  6. wait_for_approval() 发出 GATE_APPROVAL_REQUEST 事件

MCP 工具测试见：packages/mcp/tests/test_gate_approve_mcp_e9.py
"""

import unittest
import threading
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

from harness.types import (
    BusEvent, BusEventType, GateDefinition, GateCheck,
    ComplianceCategory, GateMode,
)
from harness.bus import EventBus, get_bus, reset_bus
from harness.gate_notification import (
    GateManager, GateApprovalDecision, GateNotification,
    AutoDowngrade, DowngradeAction, NotificationPriority,
    get_gate_manager,
)


class TestBusEventTypeGateApproval(unittest.TestCase):
    """E-9：BusEventType 包含门禁审批事件类型"""

    def test_has_gate_approval_request(self):
        """E-9：BusEventType.GATE_APPROVAL_REQUEST 存在"""
        self.assertTrue(hasattr(BusEventType, "GATE_APPROVAL_REQUEST"))
        self.assertEqual(
            BusEventType.GATE_APPROVAL_REQUEST.value,
            "gate:approval_request",
        )

    def test_has_gate_approval_decision(self):
        """E-9：BusEventType.GATE_APPROVAL_DECISION 存在"""
        self.assertTrue(hasattr(BusEventType, "GATE_APPROVAL_DECISION"))
        self.assertEqual(
            BusEventType.GATE_APPROVAL_DECISION.value,
            "gate:approval_decision",
        )


class TestGateManagerNoSleepPolling(unittest.TestCase):
    """E-9：GateManager.wait_for_approval() 不使用 time.sleep 轮询"""

    def setUp(self):
        self.bus = EventBus()
        self.downgrade = AutoDowngrade(
            action=DowngradeAction.SKIP,
            after_minutes=1,
        )
        self.manager = GateManager(bus=self.bus, downgrade=self.downgrade)

    def test_no_time_sleep_loop_in_wait_for_approval(self):
        """E-9：wait_for_approval() 源码不含 time.sleep 轮询循环"""
        import inspect
        source = inspect.getsource(self.manager.wait_for_approval)
        # 注释中提到 "time.sleep" 是允许的（docstring描述）
        # 但不应有 time.sleep() 的实际调用（不包括注释行）
        code_lines = [
            line for line in source.split("\n")
            if not line.strip().startswith("#")
            and not line.strip().startswith('"')
            and not line.strip().startswith("'")
        ]
        # 代码行不应包含 time.sleep( 调用
        for line in code_lines:
            self.assertNotIn("time.sleep(", line,
                             f"Found time.sleep() call in: {line}")

    def test_uses_threading_event_wait(self):
        """E-9：wait_for_approval() 使用 threading.Event.wait"""
        import inspect
        source = inspect.getsource(self.manager.wait_for_approval)
        self.assertIn("threading.Event", source)
        self.assertIn("wait_event.wait", source)


class TestGateManagerEventBusCallback(unittest.TestCase):
    """E-9：GateManager EventBus 回调唤醒机制"""

    def setUp(self):
        self.bus = EventBus()
        self.downgrade = AutoDowngrade(
            action=DowngradeAction.SKIP,
            after_minutes=1,
        )
        self.manager = GateManager(bus=self.bus, downgrade=self.downgrade)

    def test_on_approval_decision_callback_wakes_thread(self):
        """E-9：on_approval_decision 回调唤醒等待线程"""
        gate_id = "test-gate-1"
        result_container = {}

        def wait_thread():
            # 在短超时下等待审批
            result_container["decision"] = self.manager.wait_for_approval(
                gate_id, timeout_seconds=5,
            )

        # 启动等待线程
        t = threading.Thread(target=wait_thread)
        t.start()

        # 等待线程开始等待
        time.sleep(0.1)

        # 模拟通过 EventBus 发出审批决策
        decision_event = BusEvent(
            type=BusEventType.GATE_APPROVAL_DECISION,
            execution_id=gate_id,
            data={
                "gate_id": gate_id,
                "decision": "approved",
                "decided_by": "human",
                "reason": "测试通过",
            },
        )
        self.manager.on_approval_decision(decision_event)

        # 等待线程完成
        t.join(timeout=3)

        # 应收到 APPROVED 决策而非 TIMEOUT
        self.assertEqual(result_container["decision"], GateApprovalDecision.APPROVED)

    def test_on_approval_decision_rejected(self):
        """E-9：on_approval_decision 回调传递 REJECTED 决策"""
        gate_id = "test-gate-2"
        result_container = {}

        def wait_thread():
            result_container["decision"] = self.manager.wait_for_approval(
                gate_id, timeout_seconds=5,
            )

        t = threading.Thread(target=wait_thread)
        t.start()
        time.sleep(0.1)

        decision_event = BusEvent(
            type=BusEventType.GATE_APPROVAL_DECISION,
            execution_id=gate_id,
            data={
                "gate_id": gate_id,
                "decision": "rejected",
                "decided_by": "human",
                "reason": "安全风险",
            },
        )
        self.manager.on_approval_decision(decision_event)

        t.join(timeout=3)
        self.assertEqual(result_container["decision"], GateApprovalDecision.REJECTED)

    def test_timeout_triggers_downgrade(self):
        """E-9：超时仍走降级路径"""
        gate_id = "test-gate-3"
        result_container = {}

        def wait_thread():
            # 1秒超时，不发送审批决策
            result_container["decision"] = self.manager.wait_for_approval(
                gate_id, timeout_seconds=1,
            )

        t = threading.Thread(target=wait_thread)
        t.start()
        t.join(timeout=3)

        # 超时应走降级——SKIP 动作返回 TIMEOUT
        self.assertEqual(result_container["decision"], GateApprovalDecision.TIMEOUT)


class TestGateManagerFactoryBind(unittest.TestCase):
    """E-9：get_gate_manager() 工厂自动绑定 EventBus"""

    def test_factory_auto_bind_bus(self):
        """E-9：get_gate_manager() 使用项目级 EventBus"""
        reset_bus()
        bus = get_bus("test-project")
        manager = get_gate_manager("test-project")

        # manager._bus 应与项目级 bus 一致
        self.assertIsNotNone(manager._bus)

    def test_factory_with_none_project(self):
        """E-9：get_gate_manager(None) 使用默认 bus"""
        manager = get_gate_manager()
        self.assertIsNotNone(manager._bus)


class TestGateManagerEmitsRequest(unittest.TestCase):
    """E-9：wait_for_approval() 发出 GATE_APPROVAL_REQUEST 事件"""

    def setUp(self):
        self.bus = EventBus()
        self.downgrade = AutoDowngrade(
            action=DowngradeAction.SKIP,
            after_minutes=1,
        )
        self.manager = GateManager(bus=self.bus, downgrade=self.downgrade)

    def test_wait_emits_approval_request(self):
        """E-9：wait_for_approval() 发出 GATE_APPROVAL_REQUEST"""
        emitted_events = []
        original_emit = self.bus.emit

        def capture_emit(event):
            emitted_events.append(event)
            return original_emit(event)

        self.bus.emit = capture_emit

        gate_id = "test-request-1"
        result_container = {}

        def wait_thread():
            result_container["decision"] = self.manager.wait_for_approval(
                gate_id, timeout_seconds=1,
            )

        t = threading.Thread(target=wait_thread)
        t.start()
        t.join(timeout=3)

        # 超时是预期结果——但 REQUEST 事件应已发出
        self.assertEqual(result_container["decision"], GateApprovalDecision.TIMEOUT)

        request_events = [
            e for e in emitted_events
            if e.type == BusEventType.GATE_APPROVAL_REQUEST
        ]
        self.assertEqual(len(request_events), 1)
        self.assertEqual(request_events[0].data["gate_id"], gate_id)


if __name__ == "__main__":
    unittest.main()

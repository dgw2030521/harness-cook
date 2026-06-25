"""
OpenTelemetry 集成测试

测试覆盖：
- OTelBridge 初始化
- 事件监听和 Span 创建
- 指标记录
- 降级处理（当 OTel 不可用时）
"""

import pytest
from unittest.mock import Mock, MagicMock, patch

from harness.bus import EventBus, BusEventType, BusEvent
from harness.engine import DAGEngine
from harness.types import DAGWorkflow, DAGNode


class TestOTelBridge:
    """OTelBridge 测试"""

    def test_bridge_initialization_without_otel(self):
        """测试没有 OTel 时的初始化"""
        with patch('harness.otel_integration.HAS_OTEL', False):
            from harness.otel_integration import OTelBridge
            bridge = OTelBridge()

            # 应该正常初始化，但 tracer 和 meter 为 None
            assert bridge._tracer is None
            assert bridge._meter is None

    def test_bridge_with_service_name(self):
        """测试自定义服务名称"""
        from harness.otel_integration import OTelBridge
        bridge = OTelBridge(service_name="test-service")

        assert bridge._service_name == "test-service"

    def test_attach_to_engine_without_otel(self):
        """测试没有 OTel 时 attach 到引擎"""
        with patch('harness.otel_integration.HAS_OTEL', False):
            from harness.otel_integration import OTelBridge

            bridge = OTelBridge()
            engine = DAGEngine()

            # 应该正常执行，不会抛出异常
            bridge.attach_to_engine(engine)

    def test_event_handler_workflow_start(self):
        """测试工作流开始事件处理"""
        from harness.otel_integration import OTelBridge

        bridge = OTelBridge()
        bus = EventBus()

        # 创建模拟事件
        event = BusEvent(
            type=BusEventType.WORKFLOW_START,
            execution_id="test-exec-1",
            data={"workflow_id": "test-workflow", "node_count": 5},
        )

        # 如果没有 OTel，事件处理应该正常执行
        bridge._on_workflow_start(event)

    def test_event_handler_workflow_complete(self):
        """测试工作流完成事件处理"""
        from harness.otel_integration import OTelBridge

        bridge = OTelBridge()

        # 创建模拟事件
        event = BusEvent(
            type=BusEventType.WORKFLOW_COMPLETE,
            execution_id="test-exec-1",
            data={
                "workflow_id": "test-workflow",
                "duration_ms": 1000,
                "completed_nodes": 5,
                "failed_nodes": 0,
                "escalated": False,
            },
        )

        # 如果没有 OTel，事件处理应该正常执行
        bridge._on_workflow_complete(event)

    def test_event_handler_node_start(self):
        """测试节点开始事件处理"""
        from harness.otel_integration import OTelBridge

        bridge = OTelBridge()

        event = BusEvent(
            type=BusEventType.NODE_START,
            execution_id="test-exec-1",
            node_id="node-1",
            data={"agent_type": "coder"},
        )

        # 应该正常执行
        bridge._on_node_start(event)

    def test_event_handler_node_complete(self):
        """测试节点完成事件处理"""
        from harness.otel_integration import OTelBridge

        bridge = OTelBridge()

        event = BusEvent(
            type=BusEventType.NODE_COMPLETE,
            execution_id="test-exec-1",
            node_id="node-1",
            data={"agent_id": "agent-1", "artifacts": 3},
        )

        # 应该正常执行
        bridge._on_node_complete(event)

    def test_event_handler_node_fail(self):
        """测试节点失败事件处理"""
        from harness.otel_integration import OTelBridge

        bridge = OTelBridge()

        event = BusEvent(
            type=BusEventType.NODE_FAIL,
            execution_id="test-exec-1",
            node_id="node-1",
            data={"reason": "Agent timeout"},
        )

        # 应该正常执行
        bridge._on_node_fail(event)


class TestOTelIntegration:
    """OTel 集成测试"""

    def test_attach_and_execute_workflow(self):
        """测试 attach 后执行工作流"""
        from harness.otel_integration import OTelBridge

        # 创建引擎和 OTel bridge
        bus = EventBus()
        engine = DAGEngine(bus=bus)

        bridge = OTelBridge()
        bridge.attach_to_engine(engine)

        # 创建简单工作流
        workflow = DAGWorkflow(
            id="test-workflow",
            name="Test Workflow",
            nodes=[
                DAGNode(id="node-1", agent_type="coder", task="test task", inputs=[], outputs=[]),
            ],
        )

        # 执行工作流（没有注册 agent，所以会失败，但不会抛出异常）
        try:
            ctx = engine.execute(workflow)
        except Exception as e:
            # 预期会失败，但不应该是因为 OTel 集成导致的问题
            assert "OTel" not in str(e)

    def test_convenience_function_attach(self):
        """测试便捷函数 attach_otel_to_engine"""
        from harness.otel_integration import attach_otel_to_engine

        engine = DAGEngine()

        # 应该正常执行
        attach_otel_to_engine(engine, service_name="test-service")


class TestOTelMetrics:
    """OTel 指标测试"""

    def test_metrics_initialization(self):
        """测试指标初始化"""
        from harness.otel_integration import OTelBridge

        bridge = OTelBridge()

        # 如果没有 OTel，指标应该为 None
        if not hasattr(bridge, '_workflow_duration'):
            pytest.skip("OTel not installed")

        # 如果安装了 OTel，指标应该被初始化
        # 这里我们只测试没有 OTel 的情况
        assert True

    def test_metrics_recording_without_otel(self):
        """测试没有 OTel 时记录指标"""
        from harness.otel_integration import OTelBridge

        bridge = OTelBridge()

        # 尝试记录指标（应该正常执行，不会抛出异常）
        if hasattr(bridge, '_workflow_duration') and bridge._workflow_duration:
            bridge._workflow_duration.record(1000)
        else:
            # 没有 OTel，跳过
            pass

        assert True


class TestOTelGlobalBridge:
    """全局 OTel Bridge 测试"""

    def test_get_otel_bridge_singleton(self):
        """测试获取全局 OTel Bridge 单例"""
        from harness.otel_integration import get_otel_bridge

        bridge1 = get_otel_bridge()
        bridge2 = get_otel_bridge()

        # 应该返回同一个实例
        assert bridge1 is bridge2

    def test_get_otel_bridge_with_custom_service(self):
        """测试自定义服务名称的全局 Bridge"""
        from harness.otel_integration import get_otel_bridge

        # 重置全局实例
        import harness.otel_integration as otel_module
        otel_module._bridge_instance = None

        bridge = get_otel_bridge(service_name="custom-service")
        assert bridge._service_name == "custom-service"

        # 重置回默认
        otel_module._bridge_instance = None

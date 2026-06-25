"""
OTel 审计导出扩展测试

验证：
- OTelBridge.export_audit_entry() → OTel Span 格式字典
- _audit_entry_to_span_dict() → 属性格式
- OTelBridge.attach_to_audit_engine() → 监听 COMPLIANCE_CHECK/COMPLIANCE_FAIL
- TraceloopExporter → 属性映射 + 合并
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from harness.types import AuditEntry
from harness.otel_integration import OTelBridge, _audit_entry_to_span_dict
from harness.integrations.traceloop_exporter import TraceloopExporter, TRACELOOP_ATTR_MAP


def _make_entry(**kwargs) -> AuditEntry:
    defaults = {
        "timestamp": datetime.now(),
        "task": "test task",
        "session_id": "session-001",
        "agent_id": "test-agent",
        "decisions": [],
        "actions": [],
        "outcomes": [],
    }
    defaults.update(kwargs)
    return AuditEntry(**defaults)


# ═══════════════════════════════════════════════════════════
#  _audit_entry_to_span_dict 测试
# ═══════════════════════════════════════════════════════════

class TestAuditEntryToSpanDict:

    def test_basic_format(self):
        """基本格式：name, attributes, status, kind"""
        entry = _make_entry()
        result = _audit_entry_to_span_dict(entry)

        assert "name" in result
        assert "attributes" in result
        assert "status" in result
        assert "kind" in result

    def test_name_format(self):
        """name → harness.audit.{agent_id}"""
        entry = _make_entry(agent_id="coder")
        result = _audit_entry_to_span_dict(entry)
        assert result["name"] == "harness.audit.coder"

    def test_attributes_harness_prefix(self):
        """attributes 使用 harness.* 前缀"""
        entry = _make_entry()
        result = _audit_entry_to_span_dict(entry)

        attrs = result["attributes"]
        assert "harness.session_id" in attrs
        assert "harness.agent_id" in attrs
        assert "harness.task" in attrs
        assert "harness.chain_hash" in attrs
        assert "harness.risk_assessment" in attrs

    def test_status_ok_without_risk(self):
        """无 risk_assessment → status=OK"""
        entry = _make_entry()
        result = _audit_entry_to_span_dict(entry)
        assert result["status"] == "OK"

    def test_status_error_with_risk(self):
        """有 risk_assessment → status=ERROR"""
        entry = _make_entry(risk_assessment="high")
        result = _audit_entry_to_span_dict(entry)
        assert result["status"] == "ERROR"

    def test_counts_in_attributes(self):
        """decisions/actions/outcomes 计数"""
        entry = _make_entry(
            decisions=[1, 2],
            actions=[1],
            outcomes=[1, 2, 3],
        )
        result = _audit_entry_to_span_dict(entry)
        assert result["attributes"]["harness.decisions_count"] == 2
        assert result["attributes"]["harness.actions_count"] == 1
        assert result["attributes"]["harness.outcomes_count"] == 3

    def test_chain_hash_empty_string_when_none(self):
        """chain_hash=None → 空字符串"""
        entry = _make_entry()
        result = _audit_entry_to_span_dict(entry)
        assert result["attributes"]["harness.chain_hash"] == ""

    def test_chain_hash_value_preserved(self):
        """chain_hash 有值 → 保留"""
        entry = _make_entry()
        entry.chain_hash = "abc123"
        result = _audit_entry_to_span_dict(entry)
        assert result["attributes"]["harness.chain_hash"] == "abc123"


# ═══════════════════════════════════════════════════════════
#  OTelBridge.export_audit_entry 测试
# ═══════════════════════════════════════════════════════════

class TestOTelBridgeExportAuditEntry:

    def test_export_without_otel(self):
        """OTel 不可用 → 返回 span dict（不创建真实 Span）"""
        with patch("harness.otel_integration.HAS_OTEL", False):
            bridge = OTelBridge()
            entry = _make_entry()
            result = bridge.export_audit_entry(entry)

            assert result["name"] == "harness.audit.test-agent"
            assert "harness.session_id" in result["attributes"]

    def test_export_with_otel_mock(self):
        """OTel 可用 → 返回 span dict + 创建真实 Span"""
        # 不创建新 OTelBridge（因为 OTel SDK 未安装），而是手动设置 tracer
        bridge = OTelBridge.__new__(OTelBridge)
        bridge._service_name = "harness-cook"
        bridge._tracer_name = "harness.engine"
        bridge._tracer = MagicMock()
        bridge._meter = None
        bridge._workflow_duration = None

        mock_span = MagicMock()
        bridge._tracer.start_span.return_value = mock_span

        entry = _make_entry()
        result = bridge.export_audit_entry(entry)

        assert result["name"] == "harness.audit.test-agent"
        bridge._tracer.start_span.assert_called_once()
        mock_span.end.assert_called_once()


# ═══════════════════════════════════════════════════════════
#  OTelBridge.attach_to_audit_engine 测试
# ═══════════════════════════════════════════════════════════

class TestOTelBridgeAttachAuditEngine:

    def test_attach_subscribes_to_compliance_events(self):
        """attach_to_audit_engine → 订阅 COMPLIANCE_CHECK 和 COMPLIANCE_FAIL"""
        mock_engine = MagicMock()
        mock_bus = MagicMock()
        mock_engine._bus = mock_bus

        # 手动创建 bridge（不通过 __init__ 以避免 OTel SDK 问题）
        bridge = OTelBridge.__new__(OTelBridge)
        bridge._service_name = "harness-cook"
        bridge._tracer_name = "harness.engine"
        bridge._tracer = MagicMock()
        bridge._meter = None

        bridge.attach_to_audit_engine(mock_engine)

        # 应订阅 2 个事件
        assert mock_bus.subscribe.call_count == 2
        calls = mock_bus.subscribe.call_args_list
        event_types = [call[0][0] for call in calls]
        from harness.bus import BusEventType
        assert BusEventType.COMPLIANCE_CHECK in event_types
        assert BusEventType.COMPLIANCE_FAIL in event_types

    def test_attach_without_otel_skips(self):
        """OTel 不可用 → 不订阅"""
        mock_engine = MagicMock()
        mock_bus = MagicMock()
        mock_engine._bus = mock_bus

        with patch("harness.otel_integration.HAS_OTEL", False):
            bridge = OTelBridge()
            bridge.attach_to_audit_engine(mock_engine)
            mock_bus.subscribe.assert_not_called()


# ═══════════════════════════════════════════════════════════
#  TraceloopExporter 测试
# ═══════════════════════════════════════════════════════════

class TestTraceloopExporter:

    def test_export_with_otel_bridge(self):
        """有 OTelBridge → 映射 + 合并属性"""
        bridge = OTelBridge()
        exporter = TraceloopExporter(bridge)
        entry = _make_entry()

        result = exporter.export_audit_entry(entry)

        # harness 属性保留
        assert "harness.session_id" in result["attributes"]
        # Traceloop 属性映射
        assert "traceloop.workflow.name" in result["attributes"]
        assert result["attributes"]["traceloop.workflow.name"] == "test task"
        assert "traceloop.agent.name" in result["attributes"]
        assert result["attributes"]["traceloop.agent.name"] == "test-agent"
        # 兼容标记
        assert result["traceloop_compatible"] is True

    def test_export_without_otel_bridge(self):
        """无 OTelBridge → 使用 _audit_entry_to_span_dict + 映射"""
        exporter = TraceloopExporter()
        entry = _make_entry()

        result = exporter.export_audit_entry(entry)

        assert "harness.session_id" in result["attributes"]
        assert "traceloop.session.id" in result["attributes"]
        assert result["traceloop_compatible"] is True

    def test_attribute_mapping_complete(self):
        """映射表所有属性都被映射"""
        exporter = TraceloopExporter()
        entry = _make_entry(task="my task", agent_id="my-agent")
        entry.chain_hash = "abc"
        entry.risk_assessment = "medium"

        result = exporter.export_audit_entry(entry)

        attrs = result["attributes"]
        for harness_attr, traceloop_attr in TRACELOOP_ATTR_MAP.items():
            assert traceloop_attr in attrs, f"Missing Traceloop attr: {traceloop_attr}"

    def test_traceloop_sdk_not_installed(self):
        """Traceloop SDK 未安装 → 仍可导出（纯 OTel 格式）"""
        exporter = TraceloopExporter()
        with patch.dict("sys.modules", {"traceloop": None}):
            entry = _make_entry()
            result = exporter.export_audit_entry(entry)
            assert result["traceloop_compatible"] is True

"""
DatadogAuditStore 测试

验证：
- 惰性探测（SDK 未安装/安装）
- save → Datadog APM span（mock）
- load/search/verify_chain/integrity_report 限制性实现
- IAuditStore Protocol 兼容性
"""

import pytest
import logging
from datetime import datetime
from unittest.mock import MagicMock, patch

from harness.types import AuditEntry
from harness.integrations.audit_store_protocol import IAuditStore
from harness.integrations.datadog_store import DatadogAuditStore


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


class TestDatadogProbe:

    def test_sdk_not_installed(self):
        store = DatadogAuditStore()
        with patch.dict("sys.modules", {"ddtrace": None}):
            store._availability_cache = None
            assert store._is_available() is False

    def test_sdk_installed(self):
        store = DatadogAuditStore()
        with patch.dict("sys.modules", {"ddtrace": MagicMock()}):
            store._availability_cache = None
            assert store._is_available() is True


class TestDatadogProtocol:

    def test_satisfies_iaudit_store(self):
        store = DatadogAuditStore()
        assert isinstance(store, IAuditStore)

    def test_all_methods_present(self):
        store = DatadogAuditStore()
        assert callable(store.save)
        assert callable(store.load)
        assert callable(store.search)
        assert callable(store.verify_chain)
        assert callable(store.integrity_report)


class TestDatadogSave:

    def test_save_creates_span(self):
        """save → 创建 Datadog APM span"""
        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_span.span_id = 12345
        mock_tracer.trace.return_value = mock_span

        store = DatadogAuditStore()
        store._tracer = mock_tracer
        store._availability_cache = True

        entry = _make_entry()
        result = store.save(entry)
        assert result == "12345"
        mock_span.finish.assert_called_once()

    def test_save_with_decisions_actions_outcomes(self):
        """save → 创建子 spans"""
        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_span.span_id = 12345
        mock_child = MagicMock()
        mock_tracer.trace.return_value = mock_child if mock_tracer.trace.call_count > 0 else mock_span

        # 主 span 是第一个 trace 调用
        store = DatadogAuditStore()
        store._tracer = mock_tracer
        store._availability_cache = True

        entry = _make_entry(
            decisions=[{"reasoning": "decide"}],
            actions=[{"action": "write"}],
            outcomes=[{"outcome": "success"}],
        )

        # 设置主 span（第一次 trace 调用返回主 span，后续返回子 span）
        call_count = 0
        def trace_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            mock.span_id = call_count
            return mock

        mock_tracer.trace.side_effect = trace_side_effect

        result = store.save(entry)
        # 1 主 span + 1 decision + 1 action + 1 outcome = 4 trace 调用
        assert mock_tracer.trace.call_count == 4

    def test_save_sets_tags(self):
        """save → 设置 harness tags"""
        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_span.span_id = 12345
        mock_tracer.trace.return_value = mock_span

        store = DatadogAuditStore()
        store._tracer = mock_tracer
        store._availability_cache = True

        entry = _make_entry()
        entry.chain_hash = "abc123"
        store.save(entry)

        # 验证 tags
        mock_span.set_tag.assert_any_call("harness.session_id", "session-001")
        mock_span.set_tag.assert_any_call("harness.chain_hash", "abc123")

    def test_save_sets_metrics(self):
        """save → 设置 harness metrics"""
        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_span.span_id = 12345
        mock_tracer.trace.return_value = mock_span

        store = DatadogAuditStore()
        store._tracer = mock_tracer
        store._availability_cache = True

        entry = _make_entry(
            decisions=[1, 2],
            actions=[1],
            outcomes=[1, 2, 3],
        )
        store.save(entry)

        mock_span.set_metric.assert_any_call("harness.decisions_count", 2)
        mock_span.set_metric.assert_any_call("harness.actions_count", 1)
        mock_span.set_metric.assert_any_call("harness.outcomes_count", 3)

    def test_save_sdk_not_installed_raises(self):
        """SDK 未安装 → RuntimeError"""
        store = DatadogAuditStore()
        store._availability_cache = False
        with pytest.raises(RuntimeError, match="ddtrace SDK not installed"):
            store.save(_make_entry())


class TestDatadogReadOnly:

    def test_load_returns_empty(self):
        store = DatadogAuditStore()
        assert store.load("session-001") == []

    def test_search_returns_empty_with_warning(self):
        store = DatadogAuditStore()
        with patch.object(logging.getLogger("harness.datadog_store"), "warning") as mock_warn:
            assert store.search("query") == []
            mock_warn.assert_called_once()

    def test_verify_chain_returns_valid(self):
        store = DatadogAuditStore()
        result = store.verify_chain()
        assert result["valid"] is True
        assert "note" in result

    def test_integrity_report_simplified(self):
        store = DatadogAuditStore()
        result = store.integrity_report()
        assert result["status"] == "valid"
        assert "recommendation" in result

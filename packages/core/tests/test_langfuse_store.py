"""
LangfuseAuditStore 测试

验证：
- 惰性探测（SDK 未安装 → _is_available=False）
- save → Langfuse trace + spans（mock）
- load → 空列表
- search → 空列表 + warning
- verify_chain → {valid: True}
- integrity_report → 简化报告
- IAuditStore Protocol 兼容性

集成测试标记：@pytest.mark.langfuse
"""

import pytest
import logging
from datetime import datetime
from unittest.mock import MagicMock, patch

from harness.types import AuditEntry
from harness.integrations.audit_store_protocol import IAuditStore
from harness.integrations.langfuse_store import LangfuseAuditStore


# ═══════════════════════════════════════════════════════════
#  辅助
# ═══════════════════════════════════════════════════════════

def _make_entry(
    task: str = "test task",
    session_id: str = "session-001",
    agent_id: str = "test-agent",
    decisions: list = None,
    actions: list = None,
    outcomes: list = None,
) -> AuditEntry:
    """创建测试 AuditEntry"""
    return AuditEntry(
        timestamp=datetime.now(),
        task=task,
        session_id=session_id,
        agent_id=agent_id,
        decisions=decisions or [],
        actions=actions or [],
        outcomes=outcomes or [],
    )


# ═══════════════════════════════════════════════════════════
#  惰性探测测试
# ═══════════════════════════════════════════════════════════

class TestLangfuseProbe:

    def test_sdk_not_installed(self):
        """SDK 未安装 → _is_available=False"""
        store = LangfuseAuditStore()
        with patch.dict("sys.modules", {"langfuse": None}):
            # 清除缓存
            store._availability_cache = None
            assert store._is_available() is False

    def test_sdk_installed(self):
        """SDK 安装 → _is_available=True"""
        store = LangfuseAuditStore()
        with patch.dict("sys.modules", {"langfuse": MagicMock()}):
            store._availability_cache = None
            assert store._is_available() is True

    def test_probe_cached(self):
        """探测结果缓存"""
        store = LangfuseAuditStore()
        with patch.dict("sys.modules", {"langfuse": None}):
            store._availability_cache = None
            store._is_available()  # 第一次探测
            assert store._availability_cache is False

        # 第二次不再探测（缓存=True时已确认，这里是False缓存）
        result = store._is_available()
        assert result is False
        # 缓存已生效，不再重新 import


# ═══════════════════════════════════════════════════════════
#  IAuditStore Protocol 兼容性
# ═══════════════════════════════════════════════════════════

class TestLangfuseProtocol:

    def test_satisfies_iaudit_store(self):
        """LangfuseAuditStore 满足 IAuditStore Protocol"""
        store = LangfuseAuditStore()
        assert isinstance(store, IAuditStore)

    def test_all_methods_present(self):
        """所有 IAuditStore 方法都已实现"""
        store = LangfuseAuditStore()
        assert hasattr(store, "save")
        assert hasattr(store, "load")
        assert hasattr(store, "search")
        assert hasattr(store, "verify_chain")
        assert hasattr(store, "integrity_report")


# ═══════════════════════════════════════════════════════════
#  save 测试（mock）
# ═══════════════════════════════════════════════════════════

class TestLangfuseSave:

    def test_save_creates_trace_with_spans(self):
        """save → 创建 trace + spans（decisions/actions/outcomes）"""
        mock_langfuse = MagicMock()
        mock_trace = MagicMock()
        mock_langfuse.trace.return_value = mock_trace

        store = LangfuseAuditStore()
        store._client = mock_langfuse
        store._availability_cache = True

        entry = _make_entry(
            decisions=[{"reasoning": "test decision"}],
            actions=[{"action": "write_file"}],
            outcomes=[{"outcome": "success"}],
        )

        result = store.save(entry)
        assert result == "session-001"

        # 验证 trace 创建
        mock_langfuse.trace.assert_called_once()
        trace_kwargs = mock_langfuse.trace.call_args[1]
        assert trace_kwargs["id"] == "session-001"
        assert trace_kwargs["name"] == "harness.audit.test-agent"

        # 验证 3 个 spans（1 decision + 1 action + 1 outcome）
        assert mock_trace.span.call_count == 3

    def test_save_without_decisions_actions_outcomes(self):
        """空 decisions/actions/outcomes → trace 无 spans"""
        mock_langfuse = MagicMock()
        mock_trace = MagicMock()
        mock_langfuse.trace.return_value = mock_trace

        store = LangfuseAuditStore()
        store._client = mock_langfuse
        store._availability_cache = True

        entry = _make_entry()
        result = store.save(entry)
        assert result == "session-001"

        # 无 spans
        mock_trace.span.assert_not_called()

    def test_save_flushes_client(self):
        """save → flush 确保 trace 已发送"""
        mock_langfuse = MagicMock()
        mock_trace = MagicMock()
        mock_langfuse.trace.return_value = mock_trace

        store = LangfuseAuditStore()
        store._client = mock_langfuse
        store._availability_cache = True

        entry = _make_entry()
        store.save(entry)

        mock_langfuse.flush.assert_called_once()

    def test_save_sdk_not_installed_raises(self):
        """SDK 未安装 → save 抛 RuntimeError"""
        store = LangfuseAuditStore()
        store._availability_cache = False

        entry = _make_entry()
        with pytest.raises(RuntimeError, match="langfuse SDK not installed"):
            store.save(entry)

    def test_save_includes_chain_hash_in_metadata(self):
        """chain_hash 写入 trace metadata"""
        mock_langfuse = MagicMock()
        mock_trace = MagicMock()
        mock_langfuse.trace.return_value = mock_trace

        store = LangfuseAuditStore()
        store._client = mock_langfuse
        store._availability_cache = True

        entry = _make_entry()
        entry.chain_hash = "abc123def456"
        store.save(entry)

        trace_kwargs = mock_langfuse.trace.call_args[1]
        assert trace_kwargs["metadata"]["chain_hash"] == "abc123def456"

    def test_save_includes_risk_assessment_in_metadata(self):
        """risk_assessment 写入 trace metadata"""
        mock_langfuse = MagicMock()
        mock_trace = MagicMock()
        mock_langfuse.trace.return_value = mock_trace

        store = LangfuseAuditStore()
        store._client = mock_langfuse
        store._availability_cache = True

        entry = _make_entry()
        entry.risk_assessment = "high"
        store.save(entry)

        trace_kwargs = mock_langfuse.trace.call_args[1]
        assert trace_kwargs["metadata"]["risk_assessment"] == "high"


# ═══════════════════════════════════════════════════════════
#  读取方法测试（限制性实现）
# ═══════════════════════════════════════════════════════════

class TestLangfuseReadOnly:

    def test_load_returns_empty(self):
        """load → 空列表"""
        store = LangfuseAuditStore()
        result = store.load("session-001")
        assert result == []

    def test_search_returns_empty_with_warning(self):
        """search → 空列表 + warning"""
        store = LangfuseAuditStore()
        with patch.object(logging.getLogger("harness.langfuse_store"), "warning") as mock_warn:
            result = store.search("test query")
            assert result == []
            mock_warn.assert_called_once()

    def test_verify_chain_returns_valid(self):
        """verify_chain → {valid: True}"""
        store = LangfuseAuditStore()
        result = store.verify_chain()
        assert result["valid"] is True
        assert "note" in result

    def test_integrity_report_returns_simplified(self):
        """integrity_report → 简化报告"""
        store = LangfuseAuditStore()
        result = store.integrity_report()
        assert result["status"] == "valid"
        assert result["total_records"] == 0
        assert "recommendation" in result


# ═══════════════════════════════════════════════════════════
#  集成测试（需要 langfuse SDK，标记 @pytest.mark.langfuse）
# ═══════════════════════════════════════════════════════════

@pytest.mark.langfuse
class TestLangfuseIntegration:
    """需要 langfuse SDK 安装的集成测试"""

    def test_real_save(self):
        """真实 SDK save（需要 LANGFUSE_PUBLIC_KEY/SECRET_KEY 环境变量）"""
        store = LangfuseAuditStore()
        if not store._is_available():
            pytest.skip("langfuse SDK not installed")

        entry = _make_entry(session_id="test-langfuse-integration")
        result = store.save(entry)
        assert result == "test-langfuse-integration"

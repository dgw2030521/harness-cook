"""
ArizeAuditStore 测试

验证：
- 惰性探测（SDK 未安装/安装）
- save → Arize trace + compliance annotations（mock）
- load/search/verify_chain/integrity_report 限制性实现
- IAuditStore Protocol 兼容性
"""

import pytest
import logging
from datetime import datetime
from unittest.mock import MagicMock, patch

from harness.types import AuditEntry
from harness.integrations.audit_store_protocol import IAuditStore
from harness.integrations.arize_store import ArizeAuditStore


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


class TestArizeProbe:

    def test_sdk_not_installed(self):
        store = ArizeAuditStore()
        with patch.dict("sys.modules", {"arize": None}):
            store._availability_cache = None
            assert store._is_available() is False

    def test_sdk_installed(self):
        store = ArizeAuditStore()
        with patch.dict("sys.modules", {"arize": MagicMock()}):
            store._availability_cache = None
            assert store._is_available() is True


class TestArizeProtocol:

    def test_satisfies_iaudit_store(self):
        store = ArizeAuditStore()
        assert isinstance(store, IAuditStore)

    def test_all_methods_present(self):
        store = ArizeAuditStore()
        assert callable(store.save)
        assert callable(store.load)
        assert callable(store.search)
        assert callable(store.verify_chain)
        assert callable(store.integrity_report)


class TestArizeSave:

    def test_save_creates_trace(self):
        """save → 创建 Arize trace"""
        mock_client = MagicMock()
        store = ArizeAuditStore()
        store._client = mock_client
        store._availability_cache = True

        entry = _make_entry()
        result = store.save(entry)
        assert result == "session-001"
        mock_client.log.assert_called()

    def test_save_with_compliance_annotation(self):
        """risk_assessment → 创建 compliance annotation"""
        mock_client = MagicMock()
        store = ArizeAuditStore()
        store._client = mock_client
        store._availability_cache = True

        entry = _make_entry(risk_assessment="high")
        result = store.save(entry)
        assert result == "session-001"
        # 两次 log：trace + compliance annotation
        assert mock_client.log.call_count == 2

    def test_save_without_risk_assessment(self):
        """无 risk_assessment → 只创建 trace"""
        mock_client = MagicMock()
        store = ArizeAuditStore()
        store._client = mock_client
        store._availability_cache = True

        entry = _make_entry()
        store.save(entry)
        # 只一次 log（trace）
        assert mock_client.log.call_count == 1

    def test_save_sdk_not_installed_raises(self):
        """SDK 未安装 → RuntimeError"""
        store = ArizeAuditStore()
        store._availability_cache = False
        with pytest.raises(RuntimeError, match="arize SDK not installed"):
            store.save(_make_entry())


class TestArizeReadOnly:

    def test_load_returns_empty(self):
        store = ArizeAuditStore()
        assert store.load("session-001") == []

    def test_search_returns_empty_with_warning(self):
        store = ArizeAuditStore()
        with patch.object(logging.getLogger("harness.arize_store"), "warning") as mock_warn:
            assert store.search("query") == []
            mock_warn.assert_called_once()

    def test_verify_chain_returns_valid(self):
        store = ArizeAuditStore()
        result = store.verify_chain()
        assert result["valid"] is True
        assert "note" in result

    def test_integrity_report_simplified(self):
        store = ArizeAuditStore()
        result = store.integrity_report()
        assert result["status"] == "valid"
        assert "recommendation" in result

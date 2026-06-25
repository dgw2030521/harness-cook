"""
IAuditStore Protocol + MultiAuditStore 测试

验证：
- IAuditStore Protocol 定义完整（5个方法）
- AuditStore 满足 IAuditStore（鸭子类型兼容）
- MultiAuditStore 双写行为：
  - save → 主存储成功 + 次存储成功
  - save → 主存储成功 + 次存储失败 → AUDIT_SECONDARY_FAIL 事件 + 不阻塞
  - save → 主存储失败 → 抛异常
  - load/search/verify_chain/integrity_report → 仅从主存储
- MultiAuditStore 构造约束：至少1个 store
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from harness.types import AuditEntry, BusEventType, BusEvent
from harness.audit import AuditStore, AuditEngine
from harness.integrations.audit_store_protocol import IAuditStore
from harness.integrations.multi_store import MultiAuditStore
from harness.bus import EventBus


# ═══════════════════════════════════════════════════════════
#  IAuditStore Protocol 测试
# ═══════════════════════════════════════════════════════════

class TestIAuditStoreProtocol:
    """IAuditStore Protocol 定义完整性测试"""

    def test_protocol_is_runtime_checkable(self):
        """IAuditStore 是 runtime_checkable Protocol"""
        assert hasattr(IAuditStore, "__protocol_attrs__") or hasattr(IAuditStore, "_is_protocol")

    def test_protocol_has_required_methods(self):
        """IAuditStore Protocol 定义了 5 个必需方法"""
        # save, load, search, verify_chain, integrity_report
        expected_methods = ["save", "load", "search", "verify_chain", "integrity_report"]
        for method in expected_methods:
            assert hasattr(IAuditStore, method), f"IAuditStore missing method: {method}"

    def test_audit_store_satisfies_protocol(self):
        """AuditStore 满足 IAuditStore Protocol（鸭子类型兼容）"""
        # runtime_checkable 可以用 isinstance 检查
        store = AuditStore()
        # AuditStore 实现了所有 IAuditStore 要求的方法
        assert hasattr(store, "save")
        assert hasattr(store, "load")
        assert hasattr(store, "search")
        assert hasattr(store, "verify_chain")
        assert hasattr(store, "integrity_report")
        # runtime_checkable isinstance 检查
        assert isinstance(store, IAuditStore)

    def test_audit_engine_accepts_iaudit_store(self):
        """AuditEngine.__init__ 接受 IAuditStore 类型"""
        store = AuditStore()
        engine = AuditEngine(store=store)
        assert engine._store is store

    def test_mock_store_satisfies_protocol(self):
        """Mock 对象满足 IAuditStore Protocol"""
        mock_store = MagicMock(spec=IAuditStore)
        mock_store.save.return_value = "/path/to/entry.json"
        mock_store.load.return_value = []
        mock_store.search.return_value = []
        mock_store.verify_chain.return_value = {"valid": True}
        mock_store.integrity_report.return_value = {"status": "valid"}

        # 可以传给 AuditEngine
        engine = AuditEngine(store=mock_store)
        assert engine._store is mock_store


# ═══════════════════════════════════════════════════════════
#  MultiAuditStore 测试
# ═══════════════════════════════════════════════════════════

def _make_entry(
    task: str = "test task",
    session_id: str = "session-001",
    agent_id: str = "test-agent",
) -> AuditEntry:
    """创建测试 AuditEntry"""
    return AuditEntry(
        timestamp=datetime.now(),
        task=task,
        session_id=session_id,
        agent_id=agent_id,
        decisions=[],
        actions=[],
        outcomes=[],
    )


class TestMultiAuditStoreConstruction:
    """MultiAuditStore 构造约束"""

    def test_requires_at_least_one_store(self):
        """空列表 → ValueError"""
        with pytest.raises(ValueError, match="at least one store"):
            MultiAuditStore([])

    def test_single_store_no_secondary(self):
        """只有主存储 → secondary_stores 为空"""
        primary = MagicMock(spec=IAuditStore)
        multi = MultiAuditStore([primary])
        assert multi.primary is primary
        assert multi.secondary_stores == []

    def test_primary_and_secondary(self):
        """1个主存储 + 2个次存储"""
        stores = [MagicMock(spec=IAuditStore) for _ in range(3)]
        multi = MultiAuditStore(stores)
        assert multi.primary is stores[0]
        assert multi.secondary_stores == stores[1:]


class TestMultiAuditStoreSave:
    """MultiAuditStore.save 双写行为"""

    def test_save_primary_success_secondary_success(self):
        """主存储成功 + 次存储成功 → 返回主存储标识"""
        primary = MagicMock(spec=IAuditStore)
        primary.save.return_value = "/audit/entry.json"
        secondary = MagicMock(spec=IAuditStore)
        secondary.save.return_value = "trace-id-123"

        bus = EventBus()
        multi = MultiAuditStore([primary, secondary], bus=bus)
        entry = _make_entry()

        result = multi.save(entry)

        assert result == "/audit/entry.json"
        primary.save.assert_called_once_with(entry)
        secondary.save.assert_called_once_with(entry)

    def test_save_primary_success_secondary_fail_no_blocking(self):
        """主存储成功 + 次存储失败 → 不阻塞，发 AUDIT_SECONDARY_FAIL 事件"""

        # 收集 AUDIT_SECONDARY_FAIL 事件
        emitted_events = []
        bus = EventBus()
        bus.subscribe(BusEventType.AUDIT_SECONDARY_FAIL, lambda e: emitted_events.append(e))

        primary = MagicMock(spec=IAuditStore)
        primary.save.return_value = "/audit/entry.json"
        secondary = MagicMock(spec=IAuditStore)
        secondary.save.side_effect = RuntimeError("Langfuse connection failed")

        multi = MultiAuditStore([primary, secondary], bus=bus)
        entry = _make_entry()

        # 不应该抛异常
        result = multi.save(entry)
        assert result == "/audit/entry.json"

        # 次存储失败 → AUDIT_SECONDARY_FAIL 事件
        assert len(emitted_events) == 1
        event = emitted_events[0]
        assert event.type == BusEventType.AUDIT_SECONDARY_FAIL
        assert event.data["store_name"] == "MagicMock"
        assert "Langfuse connection failed" in event.data["error"]

    def test_save_primary_fail_raises(self):
        """主存储失败 → 抛异常"""
        primary = MagicMock(spec=IAuditStore)
        primary.save.side_effect = RuntimeError("disk full")
        secondary = MagicMock(spec=IAuditStore)

        bus = EventBus()
        multi = MultiAuditStore([primary, secondary], bus=bus)
        entry = _make_entry()

        with pytest.raises(RuntimeError, match="disk full"):
            multi.save(entry)

        # 主存储失败 → 次存储不被调用
        secondary.save.assert_not_called()

    def test_save_multiple_secondary_one_fails(self):
        """2个次存储：1个成功 + 1个失败 → 部分成功"""

        emitted_events = []
        bus = EventBus()
        bus.subscribe(BusEventType.AUDIT_SECONDARY_FAIL, lambda e: emitted_events.append(e))

        primary = MagicMock(spec=IAuditStore)
        primary.save.return_value = "/audit/entry.json"
        secondary_ok = MagicMock(spec=IAuditStore)
        secondary_ok.save.return_value = "trace-ok"
        secondary_fail = MagicMock(spec=IAuditStore)
        secondary_fail.save.side_effect = RuntimeError("connection timeout")

        multi = MultiAuditStore([primary, secondary_ok, secondary_fail], bus=bus)
        entry = _make_entry()

        result = multi.save(entry)
        assert result == "/audit/entry.json"

        # 成功的次存储被调用
        secondary_ok.save.assert_called_once_with(entry)
        # 失败的次存储被调用（但失败了）
        secondary_fail.save.assert_called_once_with(entry)

        # 只有1个 AUDIT_SECONDARY_FAIL 事件
        assert len(emitted_events) == 1

    def test_save_no_secondary_stores(self):
        """只有主存储 → save 只调用主存储"""
        primary = MagicMock(spec=IAuditStore)
        primary.save.return_value = "/audit/entry.json"

        bus = EventBus()
        multi = MultiAuditStore([primary], bus=bus)
        entry = _make_entry()

        result = multi.save(entry)
        assert result == "/audit/entry.json"
        primary.save.assert_called_once_with(entry)


class TestMultiAuditStoreReadOnly:
    """MultiAuditStore load/search/verify_chain/integrity_report → 仅主存储"""

    def setup_method(self):
        """设置测试用的 MultiAuditStore"""
        self.primary = MagicMock(spec=IAuditStore)
        self.secondary = MagicMock(spec=IAuditStore)
        self.multi = MultiAuditStore([self.primary, self.secondary])

    def test_load_from_primary_only(self):
        """load → 仅从主存储"""
        self.primary.load.return_value = [_make_entry()]
        result = self.multi.load("session-001")
        assert len(result) == 1
        self.primary.load.assert_called_once_with("session-001", None)
        self.secondary.load.assert_not_called()

    def test_search_from_primary_only(self):
        """search → 仅从主存储"""
        self.primary.search.return_value = [_make_entry()]
        result = self.multi.search("test query")
        assert len(result) == 1
        self.primary.search.assert_called_once_with("test query", None, None, None, 50)
        self.secondary.search.assert_not_called()

    def test_verify_chain_from_primary_only(self):
        """verify_chain → 仅主存储"""
        self.primary.verify_chain.return_value = {"valid": True}
        result = self.multi.verify_chain()
        assert result["valid"] is True
        self.primary.verify_chain.assert_called_once()
        self.secondary.verify_chain.assert_not_called()

    def test_integrity_report_from_primary_only(self):
        """integrity_report → 仅主存储"""
        self.primary.integrity_report.return_value = {"status": "valid"}
        result = self.multi.integrity_report()
        assert result["status"] == "valid"
        self.primary.integrity_report.assert_called_once()
        self.secondary.integrity_report.assert_not_called()

    def test_chain_head_from_primary(self):
        """chain_head → 主存储的链头 hash"""
        self.primary.chain_head = "abc123"
        result = self.multi.chain_head
        assert result == "abc123"

    def test_chain_head_primary_without_attribute(self):
        """主存储没有 chain_head 属性 → 返回 None"""
        # MagicMock 默认有所有属性，用不带 chain_head 的 mock
        primary = MagicMock(spec=["save", "load", "search", "verify_chain", "integrity_report"])
        multi = MultiAuditStore([primary])
        assert multi.chain_head is None


class TestMultiAuditStoreWithRealAuditStore:
    """MultiAuditStore + 真实 AuditStore 集成"""

    def test_primary_is_real_audit_store(self):
        """主存储为 AuditStore → save 返回真实文件路径"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            primary = AuditStore(store_dir=tmpdir)
            secondary = MagicMock(spec=IAuditStore)
            secondary.save.return_value = "trace-123"

            bus = EventBus()
            multi = MultiAuditStore([primary, secondary], bus=bus)
            entry = _make_entry()

            result = multi.save(entry)
            assert result.endswith(".json")
            secondary.save.assert_called_once()

    def test_load_from_real_primary(self):
        """load → 从真实 AuditStore 加载"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            primary = AuditStore(store_dir=tmpdir)
            secondary = MagicMock(spec=IAuditStore)

            multi = MultiAuditStore([primary, secondary])
            entry = _make_entry(session_id="test-session")
            multi.save(entry)

            loaded = multi.load("test-session")
            assert len(loaded) == 1
            assert loaded[0].task == "test task"

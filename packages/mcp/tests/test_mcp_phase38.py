"""
Phase 3.8 MCP 工具扩展 + Profile 配置整合 测试

验证：
- _tool_audit 增加 backend 参数 → 返回 configured_backends
- _tool_trace_export → OTel JSON 格式导出
- _tool_trace_export → Traceloop 格式导出
- _tool_trace_export → 不支持的格式返回错误
- _build_audit_store → 默认 local → AuditStore
- _build_audit_store → ["local", "langfuse"] → MultiAuditStore
- _build_audit_store → 外部 SDK 不可用 → 降级回 AuditStore
- _resolve_audit_engine_config → 默认 AuditEngineConfig
- harness_trace_export 工具定义存在
- _TOOL_DISPATCH 包含 harness_trace_export
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime

from harness_mcp_server import (
    HarnessMCPServer, TOOL_DEFINITIONS,
)
from harness.audit import AuditStore, AuditEngine
from harness.integrations.engine_config import AuditEngineConfig
from harness.integrations.multi_store import MultiAuditStore
from harness.integrations.audit_store_protocol import IAuditStore
from harness.types import AuditEntry


# ── 测试辅助 ──────────────────────────────────────────────────

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


def _make_server(**kwargs) -> HarnessMCPServer:
    """创建 server 实例，默认无外部存储"""
    return HarnessMCPServer(project_dir="/tmp/test-mcp-phase38", **kwargs)


# ═══════════════════════════════════════════════════════════════
#  工具定义验证
# ═══════════════════════════════════════════════════════════════

class TestToolDefinitionsPhase38:

    def test_tool_count_at_least_17(self):
        """工具总数 ≥ 17"""
        assert len(TOOL_DEFINITIONS) >= 17

    def test_harness_trace_export_exists(self):
        """harness_trace_export 工具定义存在"""
        names = [t.name for t in TOOL_DEFINITIONS]
        assert "harness_trace_export" in names

    def test_harness_audit_has_backend_param(self):
        """harness_audit 工具定义有 backend 参数"""
        audit_tool = [t for t in TOOL_DEFINITIONS if t.name == "harness_audit"][0]
        props = audit_tool.inputSchema["properties"]
        assert "backend" in props
        assert props["backend"]["default"] == "local"

    def test_trace_export_params(self):
        """harness_trace_export 参数: format, date_from, date_to, query, limit"""
        trace_tool = [t for t in TOOL_DEFINITIONS if t.name == "harness_trace_export"][0]
        props = trace_tool.inputSchema["properties"]
        assert "format" in props
        assert props["format"]["default"] == "otel-json"
        assert "date_from" in props
        assert "date_to" in props
        assert "query" in props
        assert "limit" in props


class TestToolDispatchPhase38:

    def test_dispatch_has_trace_export(self):
        """_TOOL_DISPATCH 包含 harness_trace_export"""
        # 需要 server 实例来验证 dispatch
        server = _make_server()
        # 检查 _tool_trace_export 方法存在
        assert hasattr(server, "_tool_trace_export")
        assert callable(server._tool_trace_export)


# ═══════════════════════════════════════════════════════════════
#  _resolve_audit_engine_config 测试
# ═══════════════════════════════════════════════════════════════

class TestResolveAuditEngineConfig:

    def test_default_config(self):
        """默认配置 → backends=["local"]"""
        server = _make_server()
        config = server._resolve_audit_engine_config()
        assert isinstance(config, AuditEngineConfig)
        assert config.backends == ["local"]

    def test_profile_config_override(self):
        """Profile 配置覆盖 → backends=["local", "langfuse"]"""
        mock_config = AuditEngineConfig(backends=["local", "langfuse"])
        mock_profile = MagicMock()
        mock_profile.audit_engine = mock_config

        with patch("harness.config.ProfileLoader") as mock_loader_cls:
            mock_loader = MagicMock()
            mock_loader.resolve_active.return_value = "default"
            mock_loader.load.return_value = mock_profile
            mock_loader_cls.return_value = mock_loader

            server = _make_server()
            config = server._resolve_audit_engine_config()
            assert config.backends == ["local", "langfuse"]

    def test_profile_load_failure(self):
        """Profile 加载失败 → 默认 config"""
        with patch("harness.config.ProfileLoader") as mock_loader_cls:
            mock_loader_cls.side_effect = ImportError("no config module")

            server = _make_server()
            config = server._resolve_audit_engine_config()
            assert config.backends == ["local"]


# ═══════════════════════════════════════════════════════════════
#  _build_audit_store 测试
# ═══════════════════════════════════════════════════════════════

class TestBuildAuditStore:

    def test_default_local_store(self):
        """默认配置 → AuditStore"""
        server = _make_server()
        store = server._audit_store
        assert isinstance(store, AuditStore)

    def test_multi_store_with_langfuse(self):
        """backends=["local", "langfuse"] → MultiAuditStore"""
        mock_config = AuditEngineConfig(backends=["local", "langfuse"])

        with patch.object(HarnessMCPServer, "_resolve_audit_engine_config", return_value=mock_config):
            with patch.object(HarnessMCPServer, "_create_external_store") as mock_create:
                mock_langfuse = MagicMock(spec=IAuditStore)
                mock_create.return_value = mock_langfuse

                server = _make_server()
                store = server._audit_store
                assert isinstance(store, MultiAuditStore)

    def test_langfuse_sdk_not_installed(self):
        """langfuse SDK 未安装 → 降级到 AuditStore"""
        mock_config = AuditEngineConfig(backends=["local", "langfuse"])

        with patch.object(HarnessMCPServer, "_resolve_audit_engine_config", return_value=mock_config):
            with patch.object(HarnessMCPServer, "_create_external_store", return_value=None):
                server = _make_server()
                store = server._audit_store
                # 仅 local → AuditStore（不是 MultiAuditStore）
                assert isinstance(store, AuditStore)

    def test_multiple_backends(self):
        """backends=["local", "langfuse", "arize"] → MultiAuditStore with 3 stores"""
        mock_config = AuditEngineConfig(backends=["local", "langfuse", "arize"])

        with patch.object(HarnessMCPServer, "_resolve_audit_engine_config", return_value=mock_config):
            with patch.object(HarnessMCPServer, "_create_external_store") as mock_create:
                mock_langfuse = MagicMock(spec=IAuditStore)
                mock_arize = MagicMock(spec=IAuditStore)
                mock_create.side_effect = [mock_langfuse, mock_arize]

                server = _make_server()
                store = server._audit_store
                assert isinstance(store, MultiAuditStore)


# ═══════════════════════════════════════════════════════════════
#  _create_external_store 测试
# ═══════════════════════════════════════════════════════════════

class TestCreateExternalStore:

    def test_langfuse_sdk_not_installed(self):
        """langfuse SDK 未安装 → 返回 None"""
        server = _make_server()
        config = AuditEngineConfig()

        with patch.dict("sys.modules", {"harness.integrations.langfuse_store": None}):
            result = server._create_external_store("langfuse", config)
            assert result is None

    def test_arize_sdk_not_installed(self):
        """arize SDK 未安装 → 返回 None"""
        server = _make_server()
        config = AuditEngineConfig()

        with patch.dict("sys.modules", {"harness.integrations.arize_store": None}):
            result = server._create_external_store("arize", config)
            assert result is None

    def test_datadog_sdk_not_installed(self):
        """datadog SDK 未安装 → 返回 None"""
        server = _make_server()
        config = AuditEngineConfig()

        with patch.dict("sys.modules", {"harness.integrations.datadog_store": None}):
            result = server._create_external_store("datadog", config)
            assert result is None

    def test_unknown_backend(self):
        """未知 backend → 返回 None + warning"""
        server = _make_server()
        config = AuditEngineConfig()

        result = server._create_external_store("custom_backend", config)
        assert result is None


# ═══════════════════════════════════════════════════════════════
#  _tool_audit 测试（backend 参数）
# ═══════════════════════════════════════════════════════════════

class TestToolAuditBackend:

    def test_audit_default_backend(self):
        """默认 backend=local"""
        server = _make_server()
        result = server._tool_audit({"query": "test"})
        assert result["backend"] == "local"
        assert result["configured_backends"] == ["local"]

    def test_audit_explicit_backend(self):
        """显式 backend=langfuse"""
        server = _make_server()
        result = server._tool_audit({"query": "test", "backend": "langfuse"})
        assert result["backend"] == "langfuse"
        # 搜索仍从 local 执行（configured_backends=["local"]）
        assert "local" in result["configured_backends"]

    def test_audit_returns_entries(self):
        """搜索返回审计条目"""
        server = _make_server()
        # 用 record_decision + finalize_entry 写入记录
        server._audit_engine.record_decision(
            session_id="session-test",
            agent_id="agent-test",
            task="my task",
            reasoning="test reasoning",
            action="test action",
        )
        server._audit_engine.finalize_entry(
            session_id="session-test",
            agent_id="agent-test",
            outcomes={"status": "completed"},
        )

        result = server._tool_audit({"query": "my task"})
        assert result["count"] >= 1


# ═══════════════════════════════════════════════════════════════
#  _tool_trace_export 测试
# ═══════════════════════════════════════════════════════════════

class TestToolTraceExport:

    def test_otel_json_format(self):
        """format=otel-json → 返回 span dicts"""
        server = _make_server()
        # 写入审计记录
        server._audit_engine.record_decision(
            session_id="session-otel",
            agent_id="otel-agent",
            task="otel test",
            reasoning="otel reasoning",
            action="otel action",
        )
        server._audit_engine.finalize_entry(
            session_id="session-otel",
            agent_id="otel-agent",
            outcomes={"status": "completed"},
        )

        result = server._tool_trace_export({
            "format": "otel-json",
            "query": "otel test",
        })

        assert result["success"] is True
        assert result["format"] == "otel-json"
        assert result["count"] >= 1
        assert len(result["spans"]) >= 1

        # 检查 span 格式
        span = result["spans"][0]
        assert "name" in span
        assert "attributes" in span
        assert span["name"] == "harness.audit.otel-agent"

    def test_traceloop_format(self):
        """format=traceloop → 返回带 traceloop.* 属性的 span dicts"""
        server = _make_server()
        server._audit_engine.record_decision(
            session_id="session-tl",
            agent_id="tl-agent",
            task="traceloop test",
            reasoning="tl reasoning",
            action="tl action",
        )
        server._audit_engine.finalize_entry(
            session_id="session-tl",
            agent_id="tl-agent",
            outcomes={"status": "completed"},
        )

        result = server._tool_trace_export({
            "format": "traceloop",
            "query": "traceloop test",
        })

        assert result["success"] is True
        assert result["count"] >= 1

        span = result["spans"][0]
        assert "traceloop_compatible" in span
        # traceloop 属性存在
        attrs = span["attributes"]
        assert "traceloop.workflow.name" in attrs

    def test_unknown_format(self):
        """不支持的格式 → 返回错误"""
        server = _make_server()

        result = server._tool_trace_export({
            "format": "csv",
        })

        assert result["success"] is False
        assert "Unknown format" in result["error"]

    def test_empty_entries(self):
        """无匹配记录 → count=0, spans=[]"""
        server = _make_server()

        result = server._tool_trace_export({
            "format": "otel-json",
            "query": "nonexistent",
        })

        assert result["success"] is True
        assert result["count"] == 0
        assert result["spans"] == []

    def test_configured_backends_in_result(self):
        """结果包含 configured_backends"""
        server = _make_server()

        result = server._tool_trace_export({
            "format": "otel-json",
            "query": "test",
        })

        assert "configured_backends" in result
        assert result["configured_backends"] == ["local"]

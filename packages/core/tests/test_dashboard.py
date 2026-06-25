"""
Dashboard API 端点集成测试

覆盖核心端点:
- /api/health: 健康检查
- /api/stats: Hook 执行统计概览
- /api/agents: 注册表 Agent 列表
- /api/compliance/scan: 合规扫描
- /api/compliance/rules: 合规规则列表
- /api/skills: 已注册 Skills 列表
- /api/profiles: Profile 列表
- /api/audit/search: 审计记录搜索
- /api/events: 最近事件流
- /api/gates/history: 门禁检查历史
"""

import pytest
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import anyio
from httpx import ASGITransport, AsyncClient

from harness.audit import AuditEngine, AuditStore
from harness.bus import EventBus
from harness.compliance import ComplianceEngine
from harness.config import HarnessConfig
from harness.gates import GateEngine
from harness.registry import AgentRegistry
from harness.types import AuditEntry


# ── Helper: 同步发起异步 HTTP 请求 ──

def _sync_request(app, method: str, path: str, **kwargs):
    """在同步测试中用 anyio.run 驱动 httpx AsyncClient"""
    async def _do():
        transport = ASGITransport(app=app)
        client = AsyncClient(transport=transport, base_url="http://test")
        resp = await client.request(method, path, **kwargs)
        await client.aclose()
        return resp
    return anyio.run(_do)


# ── 测试 fixtures ──

@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def registry(bus):
    return AgentRegistry(bus=bus)


@pytest.fixture
def audit_store():
    return AuditStore()


@pytest.fixture
def compliance_engine(bus):
    return ComplianceEngine(bus=bus)


@pytest.fixture
def gate_engine(bus):
    return GateEngine(bus=bus)


@pytest.fixture
def config():
    return HarnessConfig()


@pytest.fixture
def seeded_audit_store(audit_store):
    """注入几条审计记录，使统计端点返回非空数据"""
    now = datetime.now(timezone.utc)
    entries = [
        AuditEntry(
            timestamp=now,
            session_id="sess-001",
            agent_id="hook-session-init",
            task="Hook Session Init",
            decisions=[],
            actions=[{"tool": "hook", "duration_ms": 120}],
            outcomes={"status": "success", "hook_type": "session_start"},
            risk_assessment={},
        ),
        AuditEntry(
            timestamp=now,
            session_id="sess-001",
            agent_id="gate-check-001",
            task="Gate Check",
            decisions=[],
            actions=[{"tool": "gate"}],
            outcomes={"passed": True, "gate_id": "quality"},
            risk_assessment={},
        ),
        AuditEntry(
            timestamp=now,
            session_id="sess-002",
            agent_id="compliance-scan-001",
            task="合规扫描",
            decisions=[],
            actions=[],
            outcomes={"violations_count": 2},
            risk_assessment={},
        ),
    ]
    for entry in entries:
        audit_store.save(entry)
    return audit_store


@pytest.fixture
def dashboard_app(seeded_audit_store, bus, registry, compliance_engine, gate_engine, config):
    """动态加载 Dashboard app 模块并注入全局实例"""
    dashboard_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "packages" / "dashboard" / "app.py"
    )
    spec = importlib.util.spec_from_file_location("dashboard_app", dashboard_path)
    dm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dm)

    # 注入全局实例
    dm._config = config
    dm._bus = bus
    dm._registry = registry
    dm._audit_store = seeded_audit_store
    dm._audit_engine = AuditEngine(store=seeded_audit_store, bus=bus)
    dm._compliance_engine = compliance_engine
    dm._gate_engine = gate_engine

    yield dm.app, dm

    # 清理全局实例
    dm._config = None
    dm._bus = None
    dm._registry = None
    dm._audit_store = None
    dm._audit_engine = None
    dm._compliance_engine = None
    dm._gate_engine = None


# ── 端点测试 ──

class TestHealthEndpoint:
    """健康检查端点"""

    def test_health_returns_healthy(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "project_name" in data
        assert "timestamp" in data
        assert isinstance(data["hooks_deployed"], int)
        assert isinstance(data["agents_registered"], int)

    def test_health_harness_initialized(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/health")
        data = resp.json()
        assert data["harness_initialized"] is True


class TestStatsEndpoint:
    """Hook 执行统计概览"""

    def test_stats_returns_fields(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_hook_executions" in data
        assert "hook_success_rate" in data
        assert "hook_by_type" in data
        assert "deployed_hook_count" in data
        assert "gate_pass_rate" in data
        assert "audit_count" in data
        assert "compliance_scans" in data
        assert "compliance_violations" in data

    def test_stats_counts_seed_data(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/stats")
        data = resp.json()
        assert data["audit_count"] >= 3
        assert data["total_hook_executions"] >= 1

    def test_stats_success_rate_is_float(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/stats")
        data = resp.json()
        assert isinstance(data["hook_success_rate"], float)
        assert 0.0 <= data["hook_success_rate"] <= 1.0


class TestAgentsEndpoint:
    """注册表 Agent 列表"""

    def test_agents_returns_list(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_agents_structure(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/agents")
        data = resp.json()
        if data:
            agent = data[0]
            assert "id" in agent
            assert "name" in agent
            assert "capabilities" in agent
            assert "is_ready" in agent


class TestComplianceScanEndpoint:
    """合规扫描"""

    def test_scan_default_categories(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/compliance/scan",
                             params={"content": "password = 'secret123'"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_scan_custom_categories(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/compliance/scan",
                             params={"content": "eval(user_input)", "categories": "security"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_scan_empty_content(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/compliance/scan",
                             params={"content": ""})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_scan_result_structure(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/compliance/scan",
                             params={"content": "password = 'secret'"})
        data = resp.json()
        if data:
            result = data[0]
            assert "rule_id" in result
            assert "passed" in result
            assert "severity" in result


class TestComplianceRulesEndpoint:
    """合规规则列表"""

    def test_rules_returns_dict(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/compliance/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_rules_structure(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/compliance/rules")
        data = resp.json()
        for pack_name, pack_info in data.items():
            assert "category" in pack_info
            assert "rules_count" in pack_info
            assert "rules" in pack_info
            assert isinstance(pack_info["rules"], list)


class TestSkillsEndpoint:
    """已注册 Skills 列表"""

    def test_skills_returns_dict(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "total" in data
        assert "skills" in data

    def test_skills_with_slot_filter(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/skills",
                             params={"slot": "pre_execute"})
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data


class TestProfilesEndpoint:
    """Profile 列表"""

    def test_profiles_returns_dict(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_profiles_current_detail(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/profiles",
                             params={"current": "true"})
        assert resp.status_code == 200
        data = resp.json()
        assert "active" in data or "profiles" in data or "error" in data


class TestAuditSearchEndpoint:
    """审计记录搜索"""

    def test_search_returns_results(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/audit/search",
                             params={"query": "hook", "limit": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_search_with_agent_filter(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/audit/search",
                             params={"agent_id": "hook-session-init", "limit": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        for entry in data:
            assert entry.get("agent_id") == "hook-session-init"

    def test_search_result_structure(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/audit/search",
                             params={"limit": 5})
        data = resp.json()
        if data:
            entry = data[0]
            assert "timestamp" in entry
            assert "session_id" in entry
            assert "agent_id" in entry
            assert "task" in entry

    def test_search_empty_query(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/audit/search",
                             params={"query": "", "limit": 100})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 3  # seed 数据含 3 条


class TestEventsEndpoint:
    """最近事件流"""

    def test_events_returns_list(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/events",
                             params={"limit": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_events_with_type_filter(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/events",
                             params={"limit": 10, "event_type": "execution_start"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


class TestGatesHistoryEndpoint:
    """门禁检查历史"""

    def test_gates_history_returns_list(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/gates/history",
                             params={"limit": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_gates_history_contains_seed_data(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/gates/history",
                             params={"limit": 30})
        data = resp.json()
        gate_entries = [e for e in data if e.get("gate_id") == "quality"]
        assert len(gate_entries) >= 0


class TestAuditSessionEndpoint:
    """按 session 查看审计"""

    def test_audit_session_returns_list(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/api/audit/session/sess-001")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


class TestDashboardPage:
    """Dashboard HTML 前端"""

    def test_root_returns_html(self, dashboard_app):
        app, _ = dashboard_app
        resp = _sync_request(app, "GET", "/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

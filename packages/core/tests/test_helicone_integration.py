"""
Helicone 集成测试

测试覆盖：
- HeliconeMiddlewareChecker 护栏级检查
  - HELICONE_RULE_MAP 按 rule.id 映射
  - matches_scope 逻辑（matcher_type=helicone / regex + helicone_enabled / rule.id in map）
  - 探测/降级/翻译流程
  - _translate_response 使用正确的 ComplianceResult 字段（无 message/details）
- HeliconeAuditStore 审计存储
  - IAuditStore Protocol 实现
  - save() 返回 session_id（str）
  - load/search → 空列表
  - verify_chain/integrity_report → dict
  - _is_available 缓存式惰性探测
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from harness.types import (
    Artifact, ComplianceRule, ComplianceResult, ComplianceCategory, ScanContext,
    AuditEntry,
)
from harness.integrations.helicone_checker import (
    HeliconeMiddlewareChecker, HELICONE_RULE_MAP,
)
from harness.integrations.helicone_store import HeliconeAuditStore


# ─── 测试 fixtures ────────────────────────────────────────

def make_rule(
    rule_id="no_pii",
    pattern="no_pii",
    matcher_type="helicone",
    matcher_config=None,
    severity="high",
):
    return ComplianceRule(
        id=rule_id,
        category=ComplianceCategory.SECURITY,
        pattern=pattern,
        severity=severity,
        description="Test Helicone rule",
        remediation="Fix it",
        matcher_type=matcher_type,
        matcher_config=matcher_config or {},
    )


def make_artifact(content="SSN 123-45-6789", path="test.py"):
    return Artifact(type="file", path=path, content=content)


def make_context():
    return ScanContext(
        artifacts=[make_artifact()],
        project_root="/tmp/test",
    )


def make_audit_entry():
    """创建测试用 AuditEntry"""
    return AuditEntry(
        timestamp=datetime.now(),
        task="Check PII in content",
        session_id="session_001",
        agent_id="agent_001",
        decisions=[{"reasoning": "PII check", "action": "flag", "confidence": 0.9}],
        actions=[{"tool": "regex", "input": "content", "output": "SSN found"}],
        outcomes={"passed": False, "findings": ["SSN detected"]},
        risk_assessment={"level": "high"},
        chain_hash="abc123",
    )


# ─── HeliconeMiddlewareChecker 测试 ────────────────────

class TestHeliconeRuleMap:

    def test_pii_mapping(self):
        assert HELICONE_RULE_MAP["no_pii"] == "pii_filter"

    def test_toxicity_mapping(self):
        assert HELICONE_RULE_MAP["no_toxicity"] == "toxicity_filter"

    def test_hallucination_mapping(self):
        assert HELICONE_RULE_MAP["no_hallucination"] == "hallucination_filter"

    def test_json_mapping(self):
        assert HELICONE_RULE_MAP["valid_json"] == "json_validation"

    def test_sql_injection_mapping(self):
        assert HELICONE_RULE_MAP["no_sql_injection"] == "sql_injection_filter"

    def test_python_mapping(self):
        assert HELICONE_RULE_MAP["valid_python"] == "python_validation"


class TestMatchesScope:

    def test_matcher_type_helicone(self):
        """matcher_type=helicone → matches"""
        checker = HeliconeMiddlewareChecker()
        rule = make_rule(matcher_type="helicone")
        assert checker.matches_scope(rule, make_artifact()) is True

    def test_matcher_type_regex_with_helicone_enabled(self):
        """matcher_type=regex + helicone_enabled=True → matches"""
        checker = HeliconeMiddlewareChecker()
        rule = make_rule(
            matcher_type="regex",
            matcher_config={"helicone_enabled": True},
        )
        assert checker.matches_scope(rule, make_artifact()) is True

    def test_matcher_type_regex_with_known_rule_id(self):
        """matcher_type=regex + rule.id in HELICONE_RULE_MAP → matches"""
        checker = HeliconeMiddlewareChecker()
        rule = make_rule(rule_id="no_pii", matcher_type="regex", matcher_config={})
        assert checker.matches_scope(rule, make_artifact()) is True

    def test_matcher_type_regex_unknown_id_no_helicone(self):
        """matcher_type=regex + rule.id 不在 map + 无 helicone_enabled → 不匹配"""
        checker = HeliconeMiddlewareChecker()
        rule = make_rule(rule_id="my_custom_rule", matcher_type="regex", matcher_config={})
        assert checker.matches_scope(rule, make_artifact()) is False

    def test_unknown_matcher_type(self):
        """不相关的 matcher_type → 不匹配"""
        checker = HeliconeMiddlewareChecker()
        rule = make_rule(matcher_type="opa")
        assert checker.matches_scope(rule, make_artifact()) is False


class TestProbeEngine:

    def test_probe_returns_false_on_import_error(self):
        checker = HeliconeMiddlewareChecker()
        with patch.dict("sys.modules", {"helicone": None}):
            result = checker._probe_engine()
            assert result is False

    def test_probe_returns_true_on_mock_sdk(self):
        checker = HeliconeMiddlewareChecker()
        mock_helicone = MagicMock()
        with patch.dict("sys.modules", {"helicone": mock_helicone}):
            result = checker._probe_engine()
            assert result is True

    def test_availability_caching(self):
        """可用性结果被缓存"""
        checker = HeliconeMiddlewareChecker()
        checker._availability_cache = True
        assert checker._is_engine_available() is True


class TestTranslateRequest:

    def test_known_rule_id_mapping(self):
        """已知 rule.id → HELICONE_RULE_MAP 映射"""
        rule = make_rule(rule_id="no_pii")
        checker = HeliconeMiddlewareChecker()
        request = checker._translate_request(
            rule, make_artifact(), make_context()
        )
        assert request["helicone_rule"] == "pii_filter"

    def test_unknown_rule_id_passthrough(self):
        """未知 rule.id → 透传 rule.id"""
        rule = make_rule(rule_id="my_custom_rule")
        checker = HeliconeMiddlewareChecker()
        request = checker._translate_request(
            rule, make_artifact(), make_context()
        )
        assert request["helicone_rule"] == "my_custom_rule"

    def test_content_in_request(self):
        """artifact.content 传入请求"""
        rule = make_rule()
        artifact = make_artifact(content="Test content")
        checker = HeliconeMiddlewareChecker()
        request = checker._translate_request(
            rule, artifact, make_context()
        )
        assert request["content"] == "Test content"

    def test_severity_in_request(self):
        """severity 传入请求"""
        rule = make_rule(severity="critical")
        checker = HeliconeMiddlewareChecker()
        request = checker._translate_request(
            rule, make_artifact(), make_context()
        )
        assert request["severity"] == "critical"


class TestTranslateResponse:

    """关键测试——验证 ComplianceResult 字段正确性（无 message/details）"""

    def test_passed_response_no_invalid_fields(self):
        """通过 → 只使用 ComplianceResult 正确字段"""
        checker = HeliconeMiddlewareChecker()
        rule = make_rule()

        response = {"passed": True, "findings": []}
        result = checker._translate_response(response, rule)

        assert result.rule_id == rule.id
        assert result.passed is True
        assert result.severity == "info"
        assert result.findings == []
        # 确认没有 message/details 字段
        assert not hasattr(result, "message")
        assert not hasattr(result, "details")

    def test_failed_response_no_invalid_fields(self):
        """失败 → 只使用 ComplianceResult 正确字段"""
        checker = HeliconeMiddlewareChecker()
        rule = make_rule()

        response = {
            "passed": False,
            "findings": [{"message": "PII detected"}],
            "severity": "critical",
        }
        result = checker._translate_response(response, rule)

        assert result.rule_id == rule.id
        assert result.passed is False
        assert result.severity == "critical"
        assert "PII detected" in result.findings
        assert result.remediation == "Review content and apply Helicone filter recommendations"
        # 确认没有 message/details 字段
        assert not hasattr(result, "message")
        assert not hasattr(result, "details")

    def test_empty_findings_failed(self):
        """失败但 findings 为空 → findings=[]"""
        checker = HeliconeMiddlewareChecker()
        rule = make_rule()

        response = {"passed": False, "findings": [], "severity": "high"}
        result = checker._translate_response(response, rule)

        assert result.passed is False
        assert result.findings == []


class TestCallEngine:

    def test_call_engine_success(self):
        """引擎调用成功——mock helicone SDK"""
        mock_helicone = MagicMock()
        mock_client = MagicMock()
        mock_client.check.return_value = {
            "passed": True,
            "findings": [],
        }
        mock_helicone.Helicone = MagicMock(return_value=mock_client)

        checker = HeliconeMiddlewareChecker()
        checker._availability_cache = True

        with patch.dict("sys.modules", {"helicone": mock_helicone}):
            request = {
                "helicone_rule": "pii_filter",
                "content": "Hello world",
                "severity": "high",
            }

            result = checker._call_engine(request)
            assert result["passed"] is True

    def test_call_engine_failure(self):
        """引擎调用失败——mock helicone SDK"""
        mock_helicone = MagicMock()
        mock_client = MagicMock()
        mock_client.check.return_value = {
            "passed": False,
            "findings": [{"message": "PII detected"}],
        }
        mock_helicone.Helicone = MagicMock(return_value=mock_client)

        checker = HeliconeMiddlewareChecker()
        checker._availability_cache = True

        with patch.dict("sys.modules", {"helicone": mock_helicone}):
            request = {
                "helicone_rule": "pii_filter",
                "content": "SSN 123-45-6789",
                "severity": "critical",
            }

            result = checker._call_engine(request)
            assert result["passed"] is False

    def test_call_engine_exception_fallback(self):
        """引擎调用异常 → 降级到默认回退"""
        checker = HeliconeMiddlewareChecker()

        rule = make_rule(pattern="password", matcher_type="regex")
        artifact = make_artifact(content="password = 'secret123'")
        context = make_context()

        checker._availability_cache = True
        with patch.object(checker, "_call_engine", side_effect=RuntimeError("SDK crashed")):
            result = checker.check(rule, artifact, context)
            assert result.rule_id == rule.id


class TestFullFlow:

    def test_engine_name(self):
        checker = HeliconeMiddlewareChecker()
        assert checker.engine_name == "helicone"

    def test_engine_unavailable_fallback(self):
        """引擎不可用 → 降级到默认 checker"""
        checker = HeliconeMiddlewareChecker()
        checker._availability_cache = False

        rule = make_rule(pattern="password", matcher_type="regex")
        artifact = make_artifact(content="password = 'secret123'")
        context = make_context()

        result = checker.check(rule, artifact, context)
        assert result.rule_id == rule.id


# ─── HeliconeAuditStore 测试 ────────────────────────────

class TestHeliconeAuditStoreIsAvailable:

    def test_is_available_false(self):
        """SDK 未安装 → _is_available 返回 False"""
        store = HeliconeAuditStore()
        store._availability_cache = False
        assert store._is_available() is False

    def test_is_available_true(self):
        """SDK 可用 → _is_available 返回 True"""
        store = HeliconeAuditStore()
        store._availability_cache = True
        assert store._is_available() is True

    def test_is_available_caching(self):
        """可用性结果被缓存"""
        store = HeliconeAuditStore()
        store._availability_cache = True
        assert store._is_available() is True
        # 再次调用不应触发 _probe
        assert store._availability_cache is True


class TestHeliconeAuditStoreSave:

    def test_save_returns_session_id(self):
        """save() 返回 entry.session_id（str）"""
        store = HeliconeAuditStore()
        store._availability_cache = True
        store._client = {"type": "http", "base_url": "https://api.helicone.ai"}

        entry = make_audit_entry()

        # Mock HTTP 请求
        with patch("urllib.request.urlopen"):
            result = store.save(entry)
            assert result == "session_001"

    def test_save_with_sdk_client(self):
        """SDK 模式 save()"""
        store = HeliconeAuditStore()
        store._availability_cache = True
        mock_client = MagicMock()
        mock_client.log.return_value = None
        store._client = mock_client

        entry = make_audit_entry()
        result = store.save(entry)
        assert result == "session_001"
        mock_client.log.assert_called_once()


class TestHeliconeAuditStoreReadOps:

    def test_load_returns_empty(self):
        """Helicone 无 load API → 返回空列表"""
        store = HeliconeAuditStore()
        result = store.load("test_id")
        assert result == []

    def test_search_returns_empty(self):
        """Helicone 无 search API → 返回空列表"""
        store = HeliconeAuditStore()
        result = store.search(query="test")
        assert result == []

    def test_verify_chain_returns_dict(self):
        """verify_chain → 简化报告 dict"""
        store = HeliconeAuditStore()
        result = store.verify_chain()
        assert isinstance(result, dict)
        assert result.get("valid") is True

    def test_integrity_report_returns_dict(self):
        """integrity_report → dict"""
        store = HeliconeAuditStore()
        result = store.integrity_report()
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] == "valid"


# ─── 集成测试（需要 helicone SDK）─────────────────────────

@pytest.mark.helicone
class TestIntegration:

    def test_full_check_with_real_sdk(self):
        """完整流程测试——需要 helicone SDK"""
        checker = HeliconeMiddlewareChecker()
        if not checker._is_engine_available():
            pytest.skip("helicone SDK not installed")

        rule = make_rule(rule_id="no_pii")
        artifact = make_artifact()
        context = make_context()

        result = checker.check(rule, artifact, context)
        assert result.rule_id == rule.id

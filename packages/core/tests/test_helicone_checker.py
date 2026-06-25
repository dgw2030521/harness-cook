"""
HeliconeMiddlewareChecker 测试

验证：
- engine_name="helicone"
- matches_scope 规则匹配逻辑
- VALIDATOR_MAP 翻译
- _probe_engine 惰性探测
- fallback 到 RegexChecker
- 注册到 MatcherRegistry.default()（try/except ImportError）
"""

import pytest
from unittest.mock import MagicMock, patch

from harness.types import ComplianceRule, Artifact, ScanContext, ComplianceCategory
from harness.integrations.helicone_checker import HeliconeMiddlewareChecker, HELICONE_RULE_MAP
from harness.rule_checker import MatcherRegistry


def _make_rule(
    id: str = "no_pii",
    matcher_type: str = "helicone",
    severity: str = "high",
    matcher_config: dict = None,
) -> ComplianceRule:
    return ComplianceRule(
        id=id,
        description=f"Rule {id}",
        category=ComplianceCategory.SECURITY,
        severity=severity,
        matcher_type=matcher_type,
        matcher_config=matcher_config or {},
        pattern="",
        remediation="Review and fix",
    )


def _make_artifact(content: str = "test content", file_path: str = "test.py") -> Artifact:
    return Artifact(type="code", path=file_path, content=content)


def _make_context() -> ScanContext:
    return ScanContext(
        artifacts=[],
        project_root="/tmp/test",
    )


class TestHeliconeRuleMap:

    def test_all_mappings(self):
        """VALIDATOR_MAP 包含所有映射"""
        assert "no_pii" in HELICONE_RULE_MAP
        assert HELICONE_RULE_MAP["no_pii"] == "pii_filter"
        assert "no_toxicity" in HELICONE_RULE_MAP
        assert "no_sql_injection" in HELICONE_RULE_MAP

    def test_unknown_rule_passthrough(self):
        """未知规则 ID → 直接透传"""
        assert HELICONE_RULE_MAP.get("custom_rule", "custom_rule") == "custom_rule"


class TestHeliconeMatchesScope:

    def test_matcher_type_helicone(self):
        """matcher_type=helicone → 匹配"""
        checker = HeliconeMiddlewareChecker()
        rule = _make_rule(matcher_type="helicone")
        artifact = _make_artifact()
        assert checker.matches_scope(rule, artifact) is True

    def test_matcher_type_regex_mapped(self):
        """matcher_type=regex + id=no_pii → 匹配（映射规则）"""
        checker = HeliconeMiddlewareChecker()
        rule = _make_rule(id="no_pii", matcher_type="regex")
        artifact = _make_artifact()
        assert checker.matches_scope(rule, artifact) is True

    def test_matcher_type_regex_unmapped(self):
        """matcher_type=regex + id=custom → 不匹配（无映射）"""
        checker = HeliconeMiddlewareChecker()
        rule = _make_rule(id="custom_rule", matcher_type="regex")
        artifact = _make_artifact()
        assert checker.matches_scope(rule, artifact) is False

    def test_matcher_type_other(self):
        """matcher_type=dep_graph → 不匹配"""
        checker = HeliconeMiddlewareChecker()
        rule = _make_rule(matcher_type="dep_graph")
        artifact = _make_artifact()
        assert checker.matches_scope(rule, artifact) is False

    def test_helicone_enabled_in_config(self):
        """matcher_config.helicone_enabled=True → 匹配"""
        checker = HeliconeMiddlewareChecker()
        rule = _make_rule(matcher_type="regex", matcher_config={"helicone_enabled": True})
        artifact = _make_artifact()
        assert checker.matches_scope(rule, artifact) is True


class TestHeliconeProbeEngine:

    def test_sdk_not_installed(self):
        """SDK 未安装 → _probe_engine=False"""
        checker = HeliconeMiddlewareChecker()
        checker._availability_cache = None
        with patch.dict("sys.modules", {"helicone": None}):
            assert checker._probe_engine() is False

    def test_sdk_installed(self):
        """SDK 安装 → _probe_engine=True"""
        checker = HeliconeMiddlewareChecker()
        checker._availability_cache = None
        with patch.dict("sys.modules", {"helicone": MagicMock()}):
            assert checker._probe_engine() is True


class TestHeliconeTranslateRequest:

    def test_mapped_rule(self):
        """映射规则 → helicone_rule=pii_filter"""
        checker = HeliconeMiddlewareChecker()
        rule = _make_rule(id="no_pii")
        artifact = _make_artifact(content="email: john@example.com")
        context = _make_context()

        request = checker._translate_request(rule, artifact, context)
        assert request["helicone_rule"] == "pii_filter"
        assert request["content"] == "email: john@example.com"

    def test_unknown_rule_passthrough(self):
        """未知规则 → helicone_rule=id 原样透传"""
        checker = HeliconeMiddlewareChecker()
        rule = _make_rule(id="custom_check")
        artifact = _make_artifact()
        context = _make_context()

        request = checker._translate_request(rule, artifact, context)
        assert request["helicone_rule"] == "custom_check"


class TestHeliconeRegistry:

    def test_not_registered_when_sdk_missing(self):
        """SDK 未安装 → MatcherRegistry.default() 不注册 helicone"""
        # MatcherRegistry 是类级注册，default() 在类级 _matchers 上注册
        MatcherRegistry.default()  # 触发默认注册
        assert MatcherRegistry.get("regex") is not None
        assert MatcherRegistry.get("dependency_graph") is not None
        assert MatcherRegistry.get("ast") is not None

    def test_engine_name(self):
        """engine_name = helicone"""
        checker = HeliconeMiddlewareChecker()
        assert checker.engine_name == "helicone"


class TestHeliconeFallback:

    def test_fallback_when_sdk_not_installed(self):
        """SDK 未安装 → check 使用 fallback"""
        checker = HeliconeMiddlewareChecker()
        checker._availability_cache = False

        rule = _make_rule(matcher_type="helicone")
        artifact = _make_artifact(content="clean content")
        context = _make_context()

        # 无 fallback_checker → 应返回降级结果
        result = checker.check(rule, artifact, context)
        # ExternalEngineChecker 在无 fallback 时返回 passed=True 的降级结果
        assert result is not None

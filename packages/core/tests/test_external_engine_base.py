"""
ExternalEngineChecker 基类测试

验证模板方法模式的完整流程：
- 可用性探测和缓存
- 降级回退机制
- 请求翻译 → 引擎调用 → 响应翻译流程
- 错误回退（翻译失败、调用失败、响应翻译失败）
- matches_scope 委托 fallback_checker
- reset_availability_cache
"""

import pytest
from unittest.mock import MagicMock, patch

from harness.types import (
    Artifact, ComplianceRule, ComplianceResult, ScanContext,
    ComplianceCategory,
)
from harness.rule_checker import RegexChecker
from harness.integrations.base import ExternalEngineChecker


# ═══════════════════════════════════════════════════════════
#  测试用 MockChecker——继承 ExternalEngineChecker
# ═══════════════════════════════════════════════════════════

class MockAvailableChecker(ExternalEngineChecker):
    """引擎可用的 mock checker"""

    def _probe_engine(self) -> bool:
        return True

    def _translate_request(self, rule, artifact, context):
        return {
            "validator": rule.pattern,
            "content": artifact.content,
            "severity": rule.severity,
        }

    def _call_engine(self, request):
        return {
            "passed": True,
            "findings": [],
            "severity": request["severity"],
        }


class MinimalChecker(ExternalEngineChecker):
    """最小化 checker——不覆盖 _translate_response，使用基类默认实现"""

    def _probe_engine(self) -> bool:
        return True

    def _translate_request(self, rule, artifact, context):
        return {"content": artifact.content, "pattern": rule.pattern}

    def _call_engine(self, request):
        # 返回原始引擎响应，交给基类 _translate_response 处理
        return self._stored_response

    def set_response(self, response: dict):
        """设置模拟引擎响应——用于测试"""
        self._stored_response = response


class MockUnavailableChecker(ExternalEngineChecker):
    """引擎不可用的 mock checker"""

    def _probe_engine(self) -> bool:
        return False


class MockFailingCallChecker(ExternalEngineChecker):
    """引擎调用失败的 mock checker"""

    def _probe_engine(self) -> bool:
        return True

    def _translate_request(self, rule, artifact, context):
        return {"key": "value"}

    def _call_engine(self, request):
        raise RuntimeError("Engine connection timeout")


class MockFailingTranslateChecker(ExternalEngineChecker):
    """翻译请求失败的 mock checker"""

    def _probe_engine(self) -> bool:
        return True

    def _translate_request(self, rule, artifact, context):
        raise ValueError("Cannot translate rule pattern")


class MockFailingResponseChecker(ExternalEngineChecker):
    """翻译响应失败的 mock checker"""

    def _probe_engine(self) -> bool:
        return True

    def _translate_request(self, rule, artifact, context):
        return {"key": "value"}

    def _call_engine(self, request):
        return {"malformed": True}  # 缺少 passed/findings

    def _translate_response(self, response, rule):
        raise ValueError("Cannot translate engine response")


# ═══════════════════════════════════════════════════════════
#  测试辅助数据
# ═══════════════════════════════════════════════════════════

def make_rule(
    id: str = "TEST-001",
    pattern: str = "password|secret",
    matcher_type: str = "mock_engine",
    severity: str = "high",
) -> ComplianceRule:
    return ComplianceRule(
        id=id,
        category=ComplianceCategory.SECURITY,
        pattern=pattern,
        severity=severity,
        description="Test rule",
        remediation="Fix it",
        matcher_type=matcher_type,
    )


def make_artifact(content: str = "some content with password") -> Artifact:
    return Artifact(
        type="code",
        path="test.py",
        content=content,
    )


def make_context() -> ScanContext:
    return ScanContext(
        artifacts=[make_artifact()],
        project_root="/tmp/test",
    )


# ═══════════════════════════════════════════════════════════
#  测试用例
# ═══════════════════════════════════════════════════════════

class TestAvailabilityCache:
    """可用性探测缓存测试"""

    def test_probe_only_called_once(self):
        """首次探测后缓存结果，不再重复调用"""
        checker = MockAvailableChecker(engine_name="mock")
        # 第一次调用 → 执行 _probe_engine
        assert checker._is_engine_available() is True
        # 第二次调用 → 使用缓存，不重新探测
        assert checker._is_engine_available() is True

    def test_unavailable_engine_cached(self):
        """不可用引擎也缓存"""
        checker = MockUnavailableChecker(engine_name="mock-unavail")
        assert checker._is_engine_available() is False
        assert checker._is_engine_available() is False  # 缓存

    def test_reset_cache(self):
        """重置缓存后重新探测"""
        checker = MockAvailableChecker(engine_name="mock")
        assert checker._is_engine_available() is True
        checker.reset_availability_cache()
        # 缓存已清除，重新探测
        assert checker._availability_cache is None
        assert checker._is_engine_available() is True

    def test_probe_exception_sets_false(self):
        """探测抛异常时缓存为 False"""
        checker = MockAvailableChecker(engine_name="mock")
        with patch.object(checker, "_probe_engine", side_effect=RuntimeError("import failed")):
            assert checker._is_engine_available() is False
            # 异常结果也缓存
            assert checker._availability_cache is False


class TestFallbackBehavior:
    """降级回退测试"""

    def test_unavailable_engine_falls_back_to_regex(self):
        """引擎不可用时回退到 RegexChecker"""
        checker = MockUnavailableChecker(engine_name="mock-unavail")
        rule = make_rule(pattern="password")
        artifact = make_artifact(content="has password here")
        context = make_context()

        result = checker.check(rule, artifact, context)
        # RegexChecker 会匹配到 "password"
        assert result.passed is False
        assert len(result.findings) > 0
        assert result.rule_id == "TEST-001"

    def test_custom_fallback_checker(self):
        """自定义 fallback_checker"""
        mock_fallback = MagicMock()
        mock_fallback.check.return_value = ComplianceResult(
            rule_id="TEST-001", passed=True, severity="high", findings=["mocked"],
        )
        mock_fallback.matches_scope.return_value = True

        checker = MockUnavailableChecker(
            engine_name="mock-unavail",
            fallback_checker=mock_fallback,
        )
        rule = make_rule()
        artifact = make_artifact()
        context = make_context()

        result = checker.check(rule, artifact, context)
        assert result.passed is True
        assert result.findings == ["mocked"]
        mock_fallback.check.assert_called_once_with(rule, artifact, context)

    def test_call_failure_falls_back(self):
        """引擎调用失败时回退到 fallback"""
        checker = MockFailingCallChecker(engine_name="mock-fail")
        rule = make_rule(pattern="password")
        artifact = make_artifact(content="has password here")
        context = make_context()

        result = checker.check(rule, artifact, context)
        # 回退到 RegexChecker
        assert result.passed is False  # "password" 会被 RegexChecker 匹配到

    def test_translate_request_failure_falls_back(self):
        """翻译请求失败时回退"""
        checker = MockFailingTranslateChecker(engine_name="mock-trans-fail")
        rule = make_rule(pattern="password")
        artifact = make_artifact(content="has password here")
        context = make_context()

        result = checker.check(rule, artifact, context)
        # 回退到 RegexChecker
        assert result.passed is False

    def test_translate_response_failure_falls_back(self):
        """翻译响应失败时回退"""
        checker = MockFailingResponseChecker(engine_name="mock-resp-fail")
        rule = make_rule(pattern="password")
        artifact = make_artifact(content="has password here")
        context = make_context()

        result = checker.check(rule, artifact, context)
        # 回退到 RegexChecker
        assert result.passed is False


class TestSuccessfulEngineCall:
    """引擎可用且成功调用测试"""

    def test_available_engine_returns_result(self):
        """引擎可用时返回翻译后的结果"""
        checker = MinimalChecker(engine_name="mock-ok")
        checker.set_response({"passed": True, "findings": [], "severity": "critical"})
        rule = make_rule(pattern="no_pii", severity="critical")
        artifact = make_artifact(content="clean content")
        context = make_context()

        result = checker.check(rule, artifact, context)
        assert result.passed is True
        assert result.rule_id == "TEST-001"
        assert result.severity == "critical"

    def test_engine_result_with_findings(self):
        """引擎返回违规结果"""
        checker = MinimalChecker(engine_name="mock-violation")
        checker.set_response({
            "passed": False,
            "findings": ["PII detected: email@example.com"],
            "severity": "high",
            "locations": [{"line": 5, "match": "email@example.com"}],
        })
        rule = make_rule()
        artifact = make_artifact()
        context = make_context()

        result = checker.check(rule, artifact, context)
        assert result.passed is False
        assert "PII detected: email@example.com" in result.findings
        # locations 应包含 engine 标记
        assert result.locations[0].get("engine") == "mock-violation"


class TestMatchesScope:
    """matches_scope 委托测试"""

    def test_delegates_to_fallback(self):
        """matches_scope 委托给 fallback_checker"""
        mock_fallback = MagicMock()
        mock_fallback.matches_scope.return_value = True

        checker = MockAvailableChecker(
            engine_name="mock",
            fallback_checker=mock_fallback,
        )
        rule = make_rule()
        artifact = make_artifact()

        assert checker.matches_scope(rule, artifact) is True
        mock_fallback.matches_scope.assert_called_once_with(rule, artifact)

    def test_regex_fallback_language_filter(self):
        """RegexChecker fallback 的语言过滤"""
        checker = MockUnavailableChecker(engine_name="mock-unavail")
        # Java-only 规则，Python 文件不应匹配
        rule = ComplianceRule(
            id="JAVA-001",
            category=ComplianceCategory.SECURITY,
            pattern="System.exit",
            severity="high",
            description="No System.exit",
            remediation="Use proper shutdown",
            languages=["java"],  # 只适用于 Java
        )
        artifact = Artifact(type="code", path="main.py", content="System.exit(0)")

        assert checker.matches_scope(rule, artifact) is False


class TestTranslateResponseDefault:
    """_translate_response 通用默认实现测试"""

    def test_default_translates_standard_fields(self):
        """默认实现正确提取 passed/findings/severity/remediation"""
        checker = MinimalChecker(engine_name="mock")
        rule = make_rule(severity="critical")
        response = {
            "passed": False,
            "findings": ["Issue found"],
            "severity": "high",
            "remediation": "Fix it properly",
            "locations": [{"line": 10}],
        }

        result = checker._translate_response(response, rule)
        assert result.passed is False
        assert result.findings == ["Issue found"]
        assert result.severity == "high"
        assert result.remediation == "Fix it properly"
        assert result.locations == [{"line": 10}]

    def test_default_falls_back_to_rule_fields(self):
        """响应缺少字段时回退到规则字段"""
        checker = MinimalChecker(engine_name="mock")
        rule = make_rule(severity="critical")
        response = {"passed": True}  # 最简响应

        result = checker._translate_response(response, rule)
        assert result.passed is True
        assert result.severity == "critical"  # 从 rule 回退
        assert result.remediation == "Fix it"  # 从 rule 回退
        assert result.findings == []  # 默认空

    def test_findings_string_converted_to_list(self):
        """findings 字段为字符串时自动转为列表"""
        checker = MinimalChecker(engine_name="mock")
        rule = make_rule()
        response = {"passed": False, "findings": "Single issue"}

        result = checker._translate_response(response, rule)
        assert result.findings == ["Single issue"]


class TestProperties:
    """属性访问测试"""

    def test_engine_name(self):
        checker = MockAvailableChecker(engine_name="test-engine")
        assert checker.engine_name == "test-engine"

    def test_fallback_checker(self):
        default_checker = MockAvailableChecker(engine_name="mock")
        assert isinstance(default_checker.fallback_checker, RegexChecker)

        custom = MagicMock()
        custom_checker = MockAvailableChecker(
            engine_name="mock",
            fallback_checker=custom,
        )
        assert custom_checker.fallback_checker is custom

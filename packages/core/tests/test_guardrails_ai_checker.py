"""
GuardrailsAIChecker 测试

验证：
- validator 映射（关键词自动映射 + matcher_config 直接指定）
- 引擎不可用时回退到 RegexChecker
- 请求翻译格式
- 响应翻译格式
- 端到端流程（mock 模式，不依赖真实 SDK）

注意：集成测试标记为 @pytest.mark.guardrails，需要安装 guardrails-ai SDK 才能运行。
单元测试使用 mock，不依赖任何外部 SDK。
"""

import pytest
from unittest.mock import MagicMock, patch

from harness.types import (
    Artifact, ComplianceRule, ComplianceResult, ScanContext,
    ComplianceCategory,
)
from harness.integrations.guardrails_ai_checker import (
    GuardrailsAIChecker,
    VALIDATOR_MAP,
)


# ═══════════════════════════════════════════════════════════
#  测试辅助数据
# ═══════════════════════════════════════════════════════════

def make_rule(
    id: str = "PII-001",
    pattern: str = "no_pii",
    matcher_type: str = "guardrails_ai",
    severity: str = "critical",
    matcher_config: dict = None,
    languages: list = None,
) -> ComplianceRule:
    return ComplianceRule(
        id=id,
        category=ComplianceCategory.PRIVACY,
        pattern=pattern,
        severity=severity,
        description="PII detection rule",
        remediation="Remove PII from content",
        matcher_type=matcher_type,
        matcher_config=matcher_config or {},
        languages=languages or [],
    )


def make_artifact(content: str = "Hello, my email is john@example.com") -> Artifact:
    return Artifact(type="code", path="test.py", content=content)


def make_context() -> ScanContext:
    return ScanContext(
        artifacts=[make_artifact()],
        project_root="/tmp/test",
    )


# ═══════════════════════════════════════════════════════════
#  Validator 映射测试
# ═══════════════════════════════════════════════════════════

class TestValidatorMapping:
    """validator 名称解析测试"""

    def test_config_validator_priority(self):
        """matcher_config.validator 直接指定优先级最高"""
        checker = GuardrailsAIChecker()
        rule = make_rule(
            pattern="no_pii",
            matcher_config={"validator": "CustomValidator"},
        )
        assert checker._resolve_validator(rule) == "CustomValidator"

    def test_pattern_keyword_mapping(self):
        """pattern 关键词自动映射"""
        checker = GuardrailsAIChecker()
        test_cases = [
            ("no_pii", "PII"),
            ("pii", "PII"),
            ("no_toxicity", "Toxicity"),
            ("toxicity", "Toxicity"),
            ("no_hallucination", "Relevance"),
            ("relevance", "Relevance"),
            ("valid_json", "ValidJSON"),
            ("valid_python", "ValidPython"),
            ("no_sql_injection", "SqlInjection"),
            ("sql_injection", "SqlInjection"),
        ]
        for pattern, expected_validator in test_cases:
            rule = make_rule(pattern=pattern)
            result = checker._resolve_validator(rule)
            assert result == expected_validator, f"pattern '{pattern}' → expected '{expected_validator}', got '{result}'"

    def test_pattern_passthrough(self):
        """未知 pattern 原值透传"""
        checker = GuardrailsAIChecker()
        rule = make_rule(pattern="SomeCustomValidator")
        assert checker._resolve_validator(rule) == "SomeCustomValidator"

    def test_pattern_case_insensitive_mapping(self):
        """pattern 映射大小写不敏感"""
        checker = GuardrailsAIChecker()
        rule = make_rule(pattern="NO_PII")
        assert checker._resolve_validator(rule) == "PII"

    def test_validator_map_coverage(self):
        """VALIDATOR_MAP 包含所有预期的映射"""
        expected_keys = [
            "no_pii", "pii", "no_toxicity", "toxicity",
            "no_hallucination", "hallucination", "relevance",
            "valid_json", "json_validation",
            "valid_python", "python_validation",
            "no_sql_injection", "sql_injection",
            "no_code_safety", "code_safety",
        ]
        for key in expected_keys:
            assert key in VALIDATOR_MAP, f"Missing mapping for '{key}'"


# ═══════════════════════════════════════════════════════════
#  请求翻译测试
# ═══════════════════════════════════════════════════════════

class TestTranslateRequest:
    """_translate_request 测试"""

    def test_request_has_required_fields(self):
        """翻译后的请求包含所有必需字段"""
        checker = GuardrailsAIChecker()
        rule = make_rule(pattern="no_pii", severity="critical")
        artifact = make_artifact()
        context = make_context()

        request = checker._translate_request(rule, artifact, context)
        assert "validator" in request
        assert "content" in request
        assert "path" in request
        assert "rule_id" in request
        assert "severity" in request
        assert request["validator"] == "PII"
        assert request["content"] == artifact.content
        assert request["path"] == artifact.path
        assert request["severity"] == "critical"

    def test_request_with_config_validator(self):
        """matcher_config.validator 直接指定"""
        checker = GuardrailsAIChecker()
        rule = make_rule(
            pattern="custom",
            matcher_config={"validator": "Toxicity"},
        )
        artifact = make_artifact()
        context = make_context()

        request = checker._translate_request(rule, artifact, context)
        assert request["validator"] == "Toxicity"


# ═══════════════════════════════════════════════════════════
#  降级回退测试
# ═══════════════════════════════════════════════════════════

class TestFallbackBehavior:
    """引擎不可用时的降级回退测试"""

    def test_sdk_not_installed_falls_back(self):
        """Guardrails AI SDK 未安装 → 回退到 RegexChecker"""
        checker = GuardrailsAIChecker()
        # 模拟 _probe_engine 返回 False
        checker._availability_cache = False

        rule = make_rule(
            pattern="password|secret",
            matcher_type="guardrails_ai",
        )
        artifact = make_artifact(content="has password here")
        context = make_context()

        result = checker.check(rule, artifact, context)
        # RegexChecker 会匹配到 "password"
        assert result.passed is False
        assert result.rule_id == "PII-001"

    def test_sdk_import_error_falls_back(self):
        """SDK import 失败 → 回退"""
        checker = GuardrailsAIChecker()
        with patch("builtins.__import__", side_effect=ImportError("No module named 'guardrails'")):
            checker.reset_availability_cache()
            # _probe_engine 会因 ImportError 设置 _availability_cache=False
            assert checker._is_engine_available() is False

        rule = make_rule(pattern="password")
        artifact = make_artifact(content="has password here")
        context = make_context()

        result = checker.check(rule, artifact, context)
        assert result.passed is False  # RegexChecker 匹配

    def test_engine_call_exception_falls_back(self):
        """引擎调用异常 → 回退"""
        checker = GuardrailsAIChecker()
        checker._availability_cache = True  # 强制引擎可用

        with patch.object(checker, "_call_engine", side_effect=RuntimeError("API timeout")):
            rule = make_rule(pattern="password|secret")
            artifact = make_artifact(content="has password here")
            context = make_context()

            result = checker.check(rule, artifact, context)
            # 回退到 RegexChecker
            assert result.passed is False


# ═══════════════════════════════════════════════════════════
#  端到端流程测试（mock 模式）
# ═══════════════════════════════════════════════════════════

class TestEndToEndMock:
    """端到端测试——用 mock 替代真实 SDK 调用"""

    def test_validation_passed(self):
        """验证通过场景"""
        checker = GuardrailsAIChecker()
        checker._availability_cache = True  # 强制可用

        with patch.object(checker, "_call_engine") as mock_call:
            mock_call.return_value = {
                "passed": True,
                "findings": [],
                "severity": "critical",
            }

            rule = make_rule(pattern="no_pii", severity="critical")
            artifact = make_artifact(content="clean content without PII")
            context = make_context()

            result = checker.check(rule, artifact, context)
            assert result.passed is True
            assert result.findings == []
            assert result.severity == "critical"
            mock_call.assert_called_once()

    def test_validation_failed(self):
        """验证失败场景"""
        checker = GuardrailsAIChecker()
        checker._availability_cache = True

        with patch.object(checker, "_call_engine") as mock_call:
            mock_call.return_value = {
                "passed": False,
                "findings": ["PII detected: email@example.com"],
                "severity": "critical",
                "remediation": "Remove PII from content",
                "locations": [{"line": 0, "match": "full_content", "validator": "PII"}],
            }

            rule = make_rule(pattern="no_pii", severity="critical")
            artifact = make_artifact(content="my email is john@example.com")
            context = make_context()

            result = checker.check(rule, artifact, context)
            assert result.passed is False
            assert "PII detected" in result.findings[0]
            assert result.severity == "critical"
            # locations 应有 engine 标记
            assert result.locations[0].get("engine") == "guardrails-ai"

    def test_full_pipeline_unavailable(self):
        """完整管道：引擎不可用 → RegexChecker 回退"""
        checker = GuardrailsAIChecker()
        # 模拟引擎不可用
        checker._availability_cache = False

        rule = make_rule(
            id="SEC-001",
            pattern="password|secret|api_key",
            severity="high",
        )
        artifact = make_artifact(content="config contains api_key = 'abc123'")
        context = make_context()

        result = checker.check(rule, artifact, context)
        # RegexChecker 匹配
        assert result.passed is False
        assert result.rule_id == "SEC-001"

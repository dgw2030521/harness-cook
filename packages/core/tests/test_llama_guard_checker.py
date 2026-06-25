"""
LlamaGuardChecker 测试

测试覆盖：
- CATEGORY_MAP 映射完整性（与实现完全对齐）
- DIRECTION_MAP 映射完整性
- _resolve_category 优先级（matcher_config > pattern 映射 > pattern 原值）
- _resolve_direction 方向推断
- _extract_categories 输出解析（S 类别 + 自定义类别）
- SDK 未安装时降级到默认 checker
- 引擎调用异常时 catch 回退
- _translate_response 使用基类默认实现（ComplianceResult 正确字段）
"""

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field

from harness.types import (
    Artifact, ComplianceRule, ComplianceResult, ComplianceCategory, ScanContext,
)
from harness.integrations.llama_guard_checker import (
    LlamaGuardChecker, CATEGORY_MAP, DIRECTION_MAP,
)


# ─── 测试 fixtures ────────────────────────────────────────

def make_rule(
    pattern="no_pii",
    matcher_type="llama-guard",
    matcher_config=None,
    severity="high",
):
    return ComplianceRule(
        id="test_rule_llama",
        category=ComplianceCategory.SECURITY,
        pattern=pattern,
        severity=severity,
        description="Test rule for Llama Guard",
        remediation="Fix the issue",
        matcher_type=matcher_type,
        matcher_config=matcher_config or {},
        languages=field(default_factory=list),
    )


def make_artifact(content="SSN 123-45-6789 detected", path="test.py"):
    return Artifact(type="file", path=path, content=content)


def make_context():
    return ScanContext(
        artifacts=[make_artifact()],
        project_root="/tmp/test",
    )


# ─── 映射表测试（与实际 CATEGORY_MAP 对齐）────────────

class TestCategoryMap:

    def test_pii_mapping(self):
        assert CATEGORY_MAP["no_pii"] == "pii_leak"
        assert CATEGORY_MAP["pii"] == "pii_leak"

    def test_toxicity_mapping(self):
        assert CATEGORY_MAP["no_toxicity"] == "S1"
        assert CATEGORY_MAP["toxicity"] == "S1"

    def test_harmful_input_mapping(self):
        assert CATEGORY_MAP["no_harmful_input"] == "S1"

    def test_harmful_output_mapping(self):
        assert CATEGORY_MAP["no_harmful_output"] == "S1"

    def test_hallucination_mapping(self):
        assert CATEGORY_MAP["no_hallucination"] == "factuality"

    def test_sql_injection_mapping(self):
        assert CATEGORY_MAP["no_sql_injection"] == "sql_injection"

    def test_json_validation_mapping(self):
        assert CATEGORY_MAP["valid_json"] == "json_validation"

    def test_python_validation_mapping(self):
        assert CATEGORY_MAP["valid_python"] == "code_validation"


class TestDirectionMap:

    def test_pii_direction(self):
        assert DIRECTION_MAP["no_pii"] == "input"
        assert DIRECTION_MAP["pii"] == "input"

    def test_toxicity_direction_both(self):
        """no_toxicity 方向为 both（双向检查）"""
        assert DIRECTION_MAP["no_toxicity"] == "both"
        assert DIRECTION_MAP["toxicity"] == "both"

    def test_harmful_input_direction(self):
        assert DIRECTION_MAP["no_harmful_input"] == "input"

    def test_harmful_output_direction(self):
        assert DIRECTION_MAP["no_harmful_output"] == "output"

    def test_hallucination_direction(self):
        assert DIRECTION_MAP["no_hallucination"] == "output"

    def test_sql_injection_direction(self):
        assert DIRECTION_MAP["no_sql_injection"] == "input"


# ─── 可用性探测测试 ─────────────────────────────────────

class TestProbeEngine:

    def test_sdk_not_installed_fallback(self):
        """transformers/torch 未安装 → 降级"""
        checker = LlamaGuardChecker()
        checker._availability_cache = False

        rule = make_rule(pattern="password", matcher_type="regex")
        artifact = make_artifact(content="password = 'secret'")
        context = make_context()

        result = checker.check(rule, artifact, context)
        assert result.rule_id == rule.id
        assert result.passed is False  # RegexChecker 匹配

    def test_probe_returns_false_on_import_error(self):
        checker = LlamaGuardChecker()
        with patch.dict("sys.modules", {"transformers": None}):
            result = checker._probe_engine()
            assert result is False

    def test_probe_returns_true_on_mock_sdk(self):
        """模拟 SDK 可用"""
        checker = LlamaGuardChecker()
        mock_tf = MagicMock()

        with patch.dict("sys.modules", {"transformers": mock_tf}):
            result = checker._probe_engine()
            assert result is True


# ─── 请求翻译测试 ────────────────────────────────────────

class TestTranslateRequest:

    def test_category_from_config(self):
        """matcher_config.category 优先级最高"""
        rule = make_rule(
            pattern="no_pii",
            matcher_config={"category": "custom_category"},
        )
        checker = LlamaGuardChecker()
        request = checker._translate_request(
            rule, make_artifact(), make_context()
        )
        assert request["category"] == "custom_category"

    def test_category_from_pattern_mapping(self):
        """pattern 关键词自动映射"""
        rule = make_rule(pattern="no_pii")
        checker = LlamaGuardChecker()
        request = checker._translate_request(
            rule, make_artifact(), make_context()
        )
        assert request["category"] == "pii_leak"

    def test_category_fallback_to_pattern(self):
        """无映射时透传 pattern"""
        rule = make_rule(pattern="my_custom_check")
        checker = LlamaGuardChecker()
        request = checker._translate_request(
            rule, make_artifact(), make_context()
        )
        assert request["category"] == "my_custom_check"

    def test_direction_input(self):
        """no_pii → direction=input"""
        rule = make_rule(pattern="no_pii")
        checker = LlamaGuardChecker()
        request = checker._translate_request(
            rule, make_artifact(), make_context()
        )
        assert request["direction"] == "input"

    def test_direction_output(self):
        """no_hallucination → direction=output"""
        rule = make_rule(pattern="no_hallucination")
        checker = LlamaGuardChecker()
        request = checker._translate_request(
            rule, make_artifact(), make_context()
        )
        assert request["direction"] == "output"

    def test_direction_both(self):
        """no_toxicity → direction=both"""
        rule = make_rule(pattern="no_toxicity")
        checker = LlamaGuardChecker()
        request = checker._translate_request(
            rule, make_artifact(), make_context()
        )
        assert request["direction"] == "both"

    def test_direction_generic_fallback(self):
        """无方向映射 → both"""
        rule = make_rule(pattern="my_custom_check")
        checker = LlamaGuardChecker()
        request = checker._translate_request(
            rule, make_artifact(), make_context()
        )
        assert request["direction"] == "both"

    def test_model_name_default(self):
        """默认模型名称 meta-llama/Llama-Guard-3-8B"""
        rule = make_rule(pattern="no_pii")
        checker = LlamaGuardChecker()
        request = checker._translate_request(
            rule, make_artifact(), make_context()
        )
        assert request["model_name"] == "meta-llama/Llama-Guard-3-8B"

    def test_model_name_from_config(self):
        """自定义模型名称"""
        rule = make_rule(
            pattern="no_pii",
            matcher_config={"model_name": "meta-llama/Llama-Guard-3-1B"},
        )
        checker = LlamaGuardChecker()
        request = checker._translate_request(
            rule, make_artifact(), make_context()
        )
        assert request["model_name"] == "meta-llama/Llama-Guard-3-1B"

    def test_content_in_request(self):
        """artifact.content 传入请求"""
        rule = make_rule()
        artifact = make_artifact(content="Test content here")
        checker = LlamaGuardChecker()
        request = checker._translate_request(
            rule, artifact, make_context()
        )
        assert request["content"] == "Test content here"


# ─── 输出解析测试 ────────────────────────────────────────

class TestExtractCategories:

    def test_safe_output(self):
        """safe 输出 → 无违规类别"""
        checker = LlamaGuardChecker()
        categories = checker._extract_categories("safe")
        assert categories == []

    def test_single_s_category(self):
        """单个 S 类别"""
        checker = LlamaGuardChecker()
        categories = checker._extract_categories("unsafe\nS1")
        assert "S1" in categories

    def test_multiple_s_categories(self):
        """多个 S 类别"""
        checker = LlamaGuardChecker()
        categories = checker._extract_categories("S1\nS3\nS5")
        assert "S1" in categories
        assert "S3" in categories
        assert "S5" in categories

    def test_custom_category(self):
        """自定义类别（非 S 编号）"""
        checker = LlamaGuardChecker()
        categories = checker._extract_categories("unsafe\npii_leak")
        assert "pii_leak" in categories

    def test_sql_injection_category(self):
        """sql_injection 自定义类别"""
        checker = LlamaGuardChecker()
        categories = checker._extract_categories("unsafe\nsql_injection")
        assert "sql_injection" in categories

    def test_mixed_categories(self):
        """S 类别 + 自定义类别混合"""
        checker = LlamaGuardChecker()
        categories = checker._extract_categories("S1\npii_leak\nS10\nfactuality")
        assert "S1" in categories
        assert "pii_leak" in categories
        assert "S10" in categories
        assert "factuality" in categories

    def test_empty_output(self):
        """空输出 → 无类别"""
        checker = LlamaGuardChecker()
        categories = checker._extract_categories("")
        assert categories == []


# ─── 引擎调用测试 ────────────────────────────────────────

class TestCallEngine:

    def test_call_engine_exception_fallback(self):
        """引擎调用异常 → 回退到默认 checker"""
        checker = LlamaGuardChecker()
        checker._availability_cache = True

        rule = make_rule(pattern="password", matcher_type="regex")
        artifact = make_artifact(content="password = 'secret123'")
        context = make_context()

        with patch.object(checker, "_call_engine", side_effect=RuntimeError("model crashed")):
            result = checker.check(rule, artifact, context)
            assert result.rule_id == rule.id
            assert result.passed is False


# ─── 响应翻译测试 ────────────────────────────────────────

class TestTranslateResponse:

    def test_passed_response_fields(self):
        """通过 → ComplianceResult 正确字段"""
        checker = LlamaGuardChecker()
        rule = make_rule()

        response = {
            "passed": True,
            "findings": [],
            "severity": "info",
        }

        result = checker._translate_response(response, rule)
        assert result.passed is True
        assert result.rule_id == rule.id
        assert result.findings == []
        assert not hasattr(result, "message")
        assert not hasattr(result, "details")

    def test_failed_response_fields(self):
        """失败 → ComplianceResult 正确字段"""
        checker = LlamaGuardChecker()
        rule = make_rule()

        response = {
            "passed": False,
            "findings": ["S1 violation detected"],
            "severity": "critical",
            "remediation": "Remove toxic content",
        }

        result = checker._translate_response(response, rule)
        assert result.passed is False
        assert result.rule_id == rule.id
        assert "S1 violation detected" in result.findings
        assert not hasattr(result, "message")
        assert not hasattr(result, "details")


# ─── 整体流程测试 ────────────────────────────────────────

class TestFullFlow:

    def test_engine_name_property(self):
        checker = LlamaGuardChecker()
        assert checker.engine_name == "llama-guard"

    def test_engine_unavailable_full_flow(self):
        """引擎不可用 → 完整降级流程"""
        checker = LlamaGuardChecker()
        checker._availability_cache = False

        rule = make_rule(pattern="secret", matcher_type="regex")
        artifact = make_artifact(content="secret_key = 'abc123'")
        context = make_context()

        result = checker.check(rule, artifact, context)
        assert result.rule_id == rule.id

    def test_reset_availability_cache(self):
        checker = LlamaGuardChecker()
        checker._availability_cache = True
        checker.reset_availability_cache()
        assert checker._availability_cache is None


# ─── 集成测试（需要 transformers/torch）─────────────────

@pytest.mark.llama_guard
class TestIntegration:

    def test_full_check_with_real_sdk(self):
        """完整流程测试——需要 transformers + torch"""
        checker = LlamaGuardChecker()
        if not checker._is_engine_available():
            pytest.skip("transformers/torch not installed")

        rule = make_rule(pattern="no_pii", matcher_config={"category": "pii_leak"})
        artifact = make_artifact(content="My SSN is 123-45-6789")
        context = make_context()

        result = checker.check(rule, artifact, context)
        assert result.rule_id == rule.id

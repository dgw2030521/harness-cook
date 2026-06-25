"""
NeMoGuardrailsChecker 测试

测试覆盖：
- RAIL_TYPE_MAP 映射完整性
- _resolve_rail_type 优先级（matcher_config > pattern 映射 > pattern 原值）
- _resolve_direction 推断（input_*/output_*/both）
- _build_default_colang 模板生成
- SDK 未安装时降级到 RegexChecker
- 引擎调用异常时 catch 回退
- _translate_response 使用基类默认实现（ComplianceResult 正确字段）
"""

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field
from datetime import datetime

from harness.types import (
    Artifact, ComplianceRule, ComplianceResult, ComplianceCategory, ScanContext,
)
from harness.integrations.nemo_guardrails_checker import (
    NeMoGuardrailsChecker, RAIL_TYPE_MAP,
)


# ─── 测试 fixtures ────────────────────────────────────────

def make_rule(
    pattern="no_pii",
    matcher_type="nemo",
    matcher_config=None,
    severity="high",
):
    return ComplianceRule(
        id="test_rule_001",
        category=ComplianceCategory.SECURITY,
        pattern=pattern,
        severity=severity,
        description="Test rule for NeMo Guardrails",
        remediation="Fix the issue",
        matcher_type=matcher_type,
        matcher_config=matcher_config or {},
        languages=field(default_factory=list),
    )


def make_artifact(content="This has SSN 123-45-6789", path="test.py"):
    return Artifact(type="file", path=path, content=content)


def make_context():
    return ScanContext(
        artifacts=[make_artifact()],
        project_root="/tmp/test",
    )


# ─── 映射表测试 ─────────────────────────────────────────

class TestRAILTypeMap:

    def test_pii_mapping(self):
        assert RAIL_TYPE_MAP["no_pii"] == "input_pii"
        assert RAIL_TYPE_MAP["pii"] == "input_pii"

    def test_toxicity_mapping(self):
        assert RAIL_TYPE_MAP["no_toxicity"] == "input_toxicity"
        assert RAIL_TYPE_MAP["toxicity"] == "input_toxicity"

    def test_factuality_mapping(self):
        assert RAIL_TYPE_MAP["no_hallucination"] == "output_factuality"
        assert RAIL_TYPE_MAP["hallucination"] == "output_factuality"

    def test_sql_injection_mapping(self):
        assert RAIL_TYPE_MAP["no_sql_injection"] == "input_sql_injection"

    def test_json_validation_mapping(self):
        assert RAIL_TYPE_MAP["valid_json"] == "output_json_validation"

    def test_harmful_input_mapping(self):
        assert RAIL_TYPE_MAP["no_harmful_input"] == "input_toxicity"

    def test_harmful_output_mapping(self):
        assert RAIL_TYPE_MAP["no_harmful_output"] == "output_toxicity"


# ─── 可用性探测测试 ─────────────────────────────────────

class TestProbeEngine:

    def test_sdk_not_installed_fallback(self):
        """SDK 未安装 → 降级到默认 checker"""
        checker = NeMoGuardrailsChecker()
        checker._availability_cache = False

        rule = make_rule(pattern="password", matcher_type="regex")
        artifact = make_artifact(content="password = 'secret123'")
        context = make_context()

        result = checker.check(rule, artifact, context)
        assert result.rule_id == rule.id
        # RegexChecker 匹配 password
        assert result.passed is False

    def test_probe_returns_false_on_import_error(self):
        checker = NeMoGuardrailsChecker()
        with patch.dict("sys.modules", {"nemoguardrails": None}):
            result = checker._probe_engine()
            assert result is False

    def test_probe_returns_true_on_mock_sdk(self):
        """模拟 SDK 可用"""
        checker = NeMoGuardrailsChecker()
        mock_nemo = MagicMock()
        mock_nemo.RailsConfig.from_content.return_value = MagicMock()

        with patch.dict("sys.modules", {"nemoguardrails": mock_nemo}):
            result = checker._probe_engine()
            assert result is True


# ─── 请求翻译测试 ────────────────────────────────────────

class TestTranslateRequest:

    def test_rail_type_from_config(self):
        """matcher_config.rail_type 优先级最高"""
        rule = make_rule(
            pattern="no_pii",
            matcher_config={"rail_type": "custom_rail"},
        )
        checker = NeMoGuardrailsChecker()
        request = checker._translate_request(
            rule, make_artifact(), make_context()
        )
        assert request["rail_type"] == "custom_rail"

    def test_rail_type_from_pattern_mapping(self):
        """pattern 关键词自动映射"""
        rule = make_rule(pattern="no_pii")
        checker = NeMoGuardrailsChecker()
        request = checker._translate_request(
            rule, make_artifact(), make_context()
        )
        assert request["rail_type"] == "input_pii"

    def test_rail_type_fallback_to_pattern(self):
        """无映射时透传 pattern 原值"""
        rule = make_rule(pattern="my_custom_check")
        checker = NeMoGuardrailsChecker()
        request = checker._translate_request(
            rule, make_artifact(), make_context()
        )
        assert request["rail_type"] == "my_custom_check"

    def test_direction_input(self):
        """input_* rail → direction=input"""
        rule = make_rule(pattern="no_pii")
        checker = NeMoGuardrailsChecker()
        request = checker._translate_request(
            rule, make_artifact(), make_context()
        )
        assert request["direction"] == "input"

    def test_direction_output(self):
        """output_* rail → direction=output"""
        rule = make_rule(pattern="no_hallucination")
        checker = NeMoGuardrailsChecker()
        request = checker._translate_request(
            rule, make_artifact(), make_context()
        )
        assert request["direction"] == "output"

    def test_direction_both_for_generic(self):
        """非 input/output 前缀 → direction=both"""
        rule = make_rule(pattern="my_custom_rail")
        checker = NeMoGuardrailsChecker()
        request = checker._translate_request(
            rule, make_artifact(), make_context()
        )
        assert request["direction"] == "both"

    def test_colang_flow_in_request(self):
        """matcher_config.colang_flow 传入请求"""
        colang = "define flow test\n  user ask $x\n  bot respond"
        rule = make_rule(
            pattern="no_pii",
            matcher_config={"colang_flow": colang},
        )
        checker = NeMoGuardrailsChecker()
        request = checker._translate_request(
            rule, make_artifact(), make_context()
        )
        assert request["colang_flow"] == colang

    def test_severity_in_request(self):
        """severity 传入请求"""
        rule = make_rule(severity="critical")
        checker = NeMoGuardrailsChecker()
        request = checker._translate_request(
            rule, make_artifact(), make_context()
        )
        assert request["severity"] == "critical"


# ─── Colang 模板生成测试 ─────────────────────────────────

class TestBuildDefaultColang:

    def test_pii_template(self):
        checker = NeMoGuardrailsChecker()
        colang = checker._build_default_colang("input_pii")
        assert "pii" in colang.lower()

    def test_toxicity_template(self):
        checker = NeMoGuardrailsChecker()
        colang = checker._build_default_colang("input_toxicity")
        assert "toxic" in colang.lower()

    def test_generic_template(self):
        checker = NeMoGuardrailsChecker()
        colang = checker._build_default_colang("my_custom_rail")
        assert "my_custom_rail" in colang

    def test_factuality_template(self):
        checker = NeMoGuardrailsChecker()
        colang = checker._build_default_colang("output_factuality")
        assert "factual" in colang.lower()


# ─── 引擎调用测试 ────────────────────────────────────────

class TestCallEngine:

    def test_call_engine_passed(self):
        """NeMo Guardrails 检查通过——内容未被拦截"""
        checker = NeMoGuardrailsChecker()
        checker._availability_cache = True

        request = {
            "rail_type": "input_pii",
            "content": "Hello world",
            "direction": "input",
            "severity": "high",
            "colang_flow": "",
        }

        # Mock NeMo SDK 调用
        mock_nemo = MagicMock()
        mock_rails = MagicMock()
        mock_rails.generate.return_value = "Hello world"  # 返回原内容 → 通过

        with patch.dict("sys.modules", {"nemoguardrails": mock_nemo}):
            mock_nemo.RailsConfig.from_content = MagicMock(return_value=MagicMock())
            mock_nemo.LLMRails = MagicMock(return_value=mock_rails)

            result = checker._call_engine(request)
            assert result["passed"] is True
            assert result["findings"] == []

    def test_call_engine_failed(self):
        """NeMo Guardrails 检查失败——内容被拦截"""
        checker = NeMoGuardrailsChecker()
        checker._availability_cache = True

        request = {
            "rail_type": "input_pii",
            "content": "SSN 123-45-6789",
            "direction": "input",
            "severity": "high",
            "colang_flow": "",
        }

        mock_nemo = MagicMock()
        mock_rails = MagicMock()
        # 返回拦截消息 → 不等于原内容 → 失败
        mock_rails.generate.return_value = "BLOCKED: PII detected in input"

        with patch.dict("sys.modules", {"nemoguardrails": mock_nemo}):
            mock_nemo.RailsConfig.from_content = MagicMock(return_value=MagicMock())
            mock_nemo.LLMRails = MagicMock(return_value=mock_rails)

            result = checker._call_engine(request)
            assert result["passed"] is False
            assert len(result["findings"]) > 0

    def test_call_engine_exception_fallback(self):
        """引擎调用异常 → 回退到默认 checker"""
        checker = NeMoGuardrailsChecker()

        rule = make_rule(pattern="password", matcher_type="regex")
        artifact = make_artifact(content="password = 'secret'")
        context = make_context()

        checker._availability_cache = True
        with patch.object(checker, "_call_engine", side_effect=RuntimeError("model crashed")):
            result = checker.check(rule, artifact, context)
            assert result.rule_id == rule.id


# ─── 响应翻译测试 ────────────────────────────────────────

class TestTranslateResponse:

    def test_passed_response_fields(self):
        """通过 → ComplianceResult 正确字段"""
        checker = NeMoGuardrailsChecker()
        rule = make_rule()

        response = {
            "passed": True,
            "findings": [],
            "severity": "info",
        }

        result = checker._translate_response(response, rule)
        assert result.rule_id == rule.id
        assert result.passed is True
        assert result.severity == "info"
        assert result.findings == []
        # ComplianceResult 没有 message/details 字段
        assert not hasattr(result, "message")
        assert not hasattr(result, "details")

    def test_failed_response_fields(self):
        """失败 → ComplianceResult 正确字段"""
        checker = NeMoGuardrailsChecker()
        rule = make_rule()

        response = {
            "passed": False,
            "findings": ["PII detected"],
            "severity": "critical",
            "remediation": "Remove PII",
            "locations": [{"line": 1}],
        }

        result = checker._translate_response(response, rule)
        assert result.passed is False
        assert result.rule_id == rule.id
        assert result.severity == "critical"
        assert "PII detected" in result.findings
        assert not hasattr(result, "message")
        assert not hasattr(result, "details")


# ─── 整体流程测试 ─────────────────────────────────────────

class TestFullFlow:

    def test_engine_unavailable_full_flow(self):
        """引擎不可用 → 完整降级流程"""
        checker = NeMoGuardrailsChecker()
        checker._availability_cache = False

        rule = make_rule(pattern="password", matcher_type="regex")
        artifact = make_artifact(content="password = 'secret_key'")
        context = make_context()

        result = checker.check(rule, artifact, context)
        assert result.rule_id == rule.id

    def test_engine_name_property(self):
        checker = NeMoGuardrailsChecker()
        assert checker.engine_name == "nemo-guardrails"

    def test_reset_availability_cache(self):
        checker = NeMoGuardrailsChecker()
        checker._availability_cache = True
        checker.reset_availability_cache()
        assert checker._availability_cache is None


# ─── 集成测试（需要 nemoguardrails SDK）─────────────────

@pytest.mark.nemo
class TestIntegration:

    def test_full_check_with_real_sdk(self):
        """完整流程测试——需要 nemoguardrails SDK"""
        checker = NeMoGuardrailsChecker()
        if not checker._is_engine_available():
            pytest.skip("nemoguardrails SDK not installed")

        rule = make_rule(pattern="no_pii")
        artifact = make_artifact()
        context = make_context()

        result = checker.check(rule, artifact, context)
        assert result.rule_id == rule.id

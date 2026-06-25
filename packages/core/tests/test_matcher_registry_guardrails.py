"""
MatcherRegistry GuardrailsAI 注册测试

验证：
- GuardrailsAIChecker 在 MatcherRegistry.default() 中被注册
- SDK 未安装时不注册（ImportError 回退）
- 注册后的 guardrails_ai matcher 可正常获取
- 不影响内置 matcher 注册
"""

import pytest
from unittest.mock import patch

from harness.rule_checker import MatcherRegistry


# ═══════════════════════════════════════════════════════════
#  注册测试
# ═══════════════════════════════════════════════════════════

class TestMatcherRegistryGuardrails:
    """GuardrailsAIChecker 在 MatcherRegistry 中注册的测试"""

    def setup_method(self):
        """每个测试前重置 MatcherRegistry"""
        MatcherRegistry._matchers = {}

    def test_guardrails_ai_registered_after_default(self):
        """default() 后 guardrails_ai matcher 已注册"""
        MatcherRegistry.default()
        checker = MatcherRegistry.get("guardrails_ai")
        assert checker is not None
        # 验证是 GuardrailsAIChecker 实例
        from harness.integrations.guardrails_ai_checker import GuardrailsAIChecker
        assert isinstance(checker, GuardrailsAIChecker)

    def test_guardrails_ai_not_registered_when_sdk_missing(self):
        """SDK 未安装 → ImportError → 不注册 guardrails_ai"""
        # 模拟 GuardrailsAIChecker import 失败
        with patch.dict("sys.modules", {"harness.integrations.guardrails_ai_checker": None}):
            MatcherRegistry._matchers = {}
            MatcherRegistry.default()
            # guardrails_ai 不应被注册
            assert MatcherRegistry.get("guardrails_ai") is None

    def test_builtin_matchers_still_registered_when_sdk_missing(self):
        """SDK 未安装不影响内置 matcher 注册"""
        with patch.dict("sys.modules", {"harness.integrations.guardrails_ai_checker": None}):
            MatcherRegistry._matchers = {}
            MatcherRegistry.default()
            # 4个内置 matcher 应全部注册
            assert MatcherRegistry.get("regex") is not None
            assert MatcherRegistry.get("dependency_graph") is not None
            assert MatcherRegistry.get("ast") is not None
            assert MatcherRegistry.get("cross_file") is not None

    def test_guardrails_ai_checker_engine_name(self):
        """注册的 GuardrailsAIChecker 有正确的 engine_name"""
        MatcherRegistry.default()
        checker = MatcherRegistry.get("guardrails_ai")
        assert checker is not None
        assert checker.engine_name == "guardrails-ai"

"""
MCP harness_guardrails_check engine 参数测试

验证：
- engine=builtin → 使用 GuardrailsPair（行为不变）
- engine=guardrails-ai → 使用 GuardrailsAIChecker（mock）
- engine=guardrails-ai SDK 未安装 → 回退到 builtin + warning
- engine=未知值 → 回退到 builtin + warning
- 默认 engine=builtin
"""

import pytest
from unittest.mock import MagicMock, patch

from harness_mcp_server import HarnessMCPServer


# ═══════════════════════════════════════════════════════════
#  测试
# ═══════════════════════════════════════════════════════════

class TestMCPGuardrailsEngine:
    """harness_guardrails_check engine 路由测试"""

    def _make_logic(self):
        """创建 HarnessLogic 实例"""
        return HarnessMCPServer()

    def test_builtin_engine_default(self):
        """默认 engine=builtin → GuardrailsPair 行为"""
        logic = self._make_logic()
        result = logic._tool_guardrails_check({
            "content": "Hello, my email is john@example.com",
            "direction": "input",
        })
        assert result["engine"] == "builtin"
        assert result["action"] in ("allow", "block", "warn", "redact")
        assert "original_content" in result

    def test_builtin_engine_explicit(self):
        """显式 engine=builtin → GuardrailsPair 行为"""
        logic = self._make_logic()
        result = logic._tool_guardrails_check({
            "content": "clean content without PII",
            "direction": "input",
            "engine": "builtin",
        })
        assert result["engine"] == "builtin"

    def test_guardrails_ai_engine_mock_passed(self):
        """engine=guardrails-ai + 验证通过 → mock 模式"""
        logic = self._make_logic()
        with patch("harness.integrations.guardrails_ai_checker.GuardrailsAIChecker") as MockChecker:
            mock_checker = MockChecker.return_value
            mock_checker._availability_cache = True
            mock_result = MagicMock()
            mock_result.passed = True
            mock_result.findings = []
            mock_result.severity = "critical"
            mock_result.remediation = None
            mock_checker.check.return_value = mock_result

            # 模拟 import 成功
            with patch.dict("sys.modules", {"harness.integrations.guardrails_ai_checker": MagicMock(return_value=MockChecker)}):
                # 直接模拟 _tool_guardrails_check 的 guardrails-ai 分支
                from harness.integrations.guardrails_ai_checker import GuardrailsAIChecker
                from harness.types import Artifact, ComplianceRule, ScanContext, ComplianceCategory

                checker = GuardrailsAIChecker()
                checker._availability_cache = True

                with patch.object(checker, "check", return_value=mock_result):
                    # 模拟 import
                    with patch("harness.integrations.guardrails_ai_checker.GuardrailsAIChecker", return_value=checker):
                        result = logic._tool_guardrails_check({
                            "content": "clean content",
                            "direction": "input",
                            "engine": "guardrails-ai",
                        })
                        assert result["engine"] == "guardrails-ai"
                        assert result["action"] == "allow"
                        assert result["blocked"] is False

    def test_guardrails_ai_sdk_not_installed_fallback(self):
        """engine=guardrails-ai + SDK 未安装 → 回退 builtin + warning"""
        logic = self._make_logic()
        with patch.dict("sys.modules", {"harness.integrations.guardrails_ai_checker": None}):
            result = logic._tool_guardrails_check({
                "content": "Hello, my email is john@example.com",
                "direction": "input",
                "engine": "guardrails-ai",
            })
            # 回退到 builtin
            assert result["engine"] == "builtin"
            assert result["fallback_reason"] == "guardrails-ai SDK not installed"
            # warnings 应包含回退提示
            assert any("fallback" in w for w in result["warnings"])

    def test_unknown_engine_fallback(self):
        """engine=未知值 → 回退 builtin + warning"""
        logic = self._make_logic()
        result = logic._tool_guardrails_check({
            "content": "clean content",
            "direction": "input",
            "engine": "some-fake-engine",
        })
        assert result["engine"] == "builtin"
        assert "fallback_reason" in result
        assert any("Unknown engine" in w for w in result["warnings"])

    def test_builtin_direction_output(self):
        """engine=builtin + direction=output → GuardrailsPair 输出检查"""
        logic = self._make_logic()
        result = logic._tool_guardrails_check({
            "content": "response content",
            "direction": "output",
            "engine": "builtin",
        })
        assert result["engine"] == "builtin"

"""
LangGraphGovernanceNode 治理中间件测试

验证：
1. LangGraphGovernanceNode.__init__ 默认配置和自定义配置
2. _check_guardrails 输入/输出方向（mock GuardrailsPair）
3. _check_compliance 合规扫描（mock ComplianceEngine）
4. _evaluate_gate 三种门禁模式（strict/hybrid/loose）
5. execute 完整流程（输入护栏+输出护栏+合规+门禁）
6. wrap_node_with_governance 前置/后置包裹逻辑
7. strict 模式下输入护栏失败阻断
8. build_governance_graph 图构建（mock langgraph 导入）
9. langgraph ImportError 时 build_governance_graph 的错误处理
10. @pytest.mark.langgraph 标记的集成测试

注意：单元测试使用 mock，不依赖任何外部包。
集成测试标记为 @pytest.mark.langgraph，需要安装 langgraph 才能运行。
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from harness.integrations.langgraph_middleware import (
    LangGraphGovernanceNode,
    wrap_node_with_governance,
    build_governance_graph,
)


# ═══════════════════════════════════════════════════════════
#  测试辅助数据
# ═══════════════════════════════════════════════════════════

def make_guardrails_result(passed=True, findings=None, violations=None, redactions=None):
    """构造护栏检查结果（模拟 GuardrailResult dataclass）

    修复后的 _check_guardrails 使用 GuardrailResult 的属性访问
    （violations, redactions, blocked, action, processed_content），
    而不是 dict 的 get() 方法。
    """
    result = MagicMock()
    result.violations = violations or []
    result.redactions = redactions or []
    result.warnings = []
    result.blocked = not passed if violations else False
    result.action = MagicMock()
    result.action.value = "redact" if redactions else ("warn" if not passed else "allow")
    result.original_content = ""
    result.processed_content = ""
    # passed 逻辑：有 violations 则失败
    # findings 不再是 GuardrailResult 的属性，由 _check_guardrails 从 violations/redactions 组合
    return result


def make_guardrails_check_result(direction="input", passed=True, findings=None):
    """构造 _check_guardrails 返回的结果格式"""
    return {
        "type": "guardrails",
        "direction": direction,
        "passed": passed,
        "findings": findings or [],
    }


def make_compliance_result(passed=True, findings=None):
    """构造合规扫描结果"""
    return {
        "type": "compliance",
        "passed": passed,
        "findings": findings or [],
    }


def make_state(input_text="", output_text="", file_path="test.py",
               file_type="python", project_root="/tmp", metadata=None):
    """构造测试用的 state dict"""
    return {
        "input_text": input_text,
        "output_text": output_text,
        "file_path": file_path,
        "file_type": file_type,
        "project_root": project_root,
        "metadata": metadata or {},
    }


# ═══════════════════════════════════════════════════════════
#  1. LangGraphGovernanceNode.__init__ 配置测试
# ═══════════════════════════════════════════════════════════

class TestLangGraphGovernanceNodeInit:

    def test_default_config_when_none_passed(self):
        """传入 None 时使用默认配置"""
        node = LangGraphGovernanceNode(config=None)
        assert node._config["check_input_guardrails"] is True
        assert node._config["check_output_guardrails"] is True
        assert node._config["check_compliance"] is True
        assert node._config["gate_mode"] == "hybrid"
        assert node._gate_mode == "hybrid"

    def test_default_config_when_no_arg(self):
        """不传参数时使用默认配置"""
        node = LangGraphGovernanceNode()
        assert node._config["check_input_guardrails"] is True
        assert node._gate_mode == "hybrid"

    def test_custom_config(self):
        """传入自定义配置时覆盖默认值"""
        custom_config = {
            "check_input_guardrails": False,
            "check_output_guardrails": True,
            "check_compliance": False,
            "gate_mode": "strict",
        }
        node = LangGraphGovernanceNode(config=custom_config)
        assert node._config["check_input_guardrails"] is False
        assert node._config["check_output_guardrails"] is True
        assert node._config["check_compliance"] is False
        assert node._gate_mode == "strict"

    def test_gate_mode_fallback_when_missing(self):
        """config 中缺少 gate_mode 时回退到 hybrid"""
        config = {"check_input_guardrails": True}
        node = LangGraphGovernanceNode(config=config)
        assert node._gate_mode == "hybrid"


# ═══════════════════════════════════════════════════════════
#  2. _check_guardrails 测试（mock GuardrailsPair）
# ═══════════════════════════════════════════════════════════

class TestCheckGuardrails:

    @patch("harness.integrations.langgraph_middleware.GuardrailsPair",
           create=True)
    def _mock_guardrails_pair(self, mock_cls):
        """辅助：mock GuardrailsPair 类，返回 mock 实例"""
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        return mock_instance

    @patch("harness.guardrails.GuardrailsPair")
    def test_input_direction_calls_check_input(self, mock_pair_cls):
        """direction=input 时调用 pair.check_input"""
        mock_pair = MagicMock()
        mock_pair_cls.return_value = mock_pair
        mock_pair.check_input.return_value = make_guardrails_result(
            passed=True, findings=[]
        )

        node = LangGraphGovernanceNode()
        result = node._check_guardrails("Hello world", direction="input")

        mock_pair.check_input.assert_called_once_with("Hello world")
        mock_pair.check_output.assert_not_called()
        assert result["type"] == "guardrails"
        assert result["direction"] == "input"
        assert result["passed"] is True

    @patch("harness.guardrails.GuardrailsPair")
    def test_output_direction_calls_check_output(self, mock_pair_cls):
        """direction=output 时调用 pair.check_output"""
        mock_pair = MagicMock()
        mock_pair_cls.return_value = mock_pair
        mock_pair.check_output.return_value = make_guardrails_result(
            passed=True, findings=[]
        )

        node = LangGraphGovernanceNode()
        result = node._check_guardrails("AI response", direction="output")

        mock_pair.check_output.assert_called_once_with("AI response")
        mock_pair.check_input.assert_not_called()
        assert result["direction"] == "output"

    @patch("harness.guardrails.GuardrailsPair")
    def test_guardrails_failed_returns_findings(self, mock_pair_cls):
        """护栏检查失败时返回 passed=False 和 findings

        修复后 _check_guardrails 使用 GuardrailResult 的 violations 属性，
        passed 由 not result.violations 决定。
        """
        mock_pair = MagicMock()
        mock_pair_cls.return_value = mock_pair
        mock_violation = MagicMock()
        mock_violation.__str__ = lambda self: "SSN detected"
        mock_pair.check_input.return_value = make_guardrails_result(
            passed=False,
            violations=[mock_violation],
        )

        node = LangGraphGovernanceNode()
        result = node._check_guardrails("My SSN is 123-45-6789", direction="input")

        assert result["passed"] is False
        assert len(result["findings"]) > 0

    @patch("harness.guardrails.GuardrailsPair", side_effect=ImportError("no module"))
    def test_guardrails_exception_does_not_block(self, mock_pair_cls):
        """GuardrailsPair 导入失败时 passed=True（不阻塞）+ warning"""
        # 侧效应在 import 时触发，需要通过模块内部 import 路径 mock
        with patch.dict("sys.modules", {"harness.guardrails": MagicMock(
            GuardrailsPair=MagicMock(side_effect=ImportError("no module"))
        )}):
            # 重新触发 _check_guardrails 内部的 import 会抛异常
            node = LangGraphGovernanceNode()
            # 直接 mock _check_guardrails 内部 import 路径
            with patch("harness.guardrails.GuardrailsPair",
                       side_effect=Exception("guardrails unavailable")):
                result = node._check_guardrails("test text", direction="input")

        # 失败时 passed=True，不阻塞流程
        assert result["passed"] is True
        assert len(result["findings"]) >= 1
        assert "warning" in result["findings"][0]

    @patch("harness.guardrails.GuardrailsPair")
    def test_guardrails_returns_findings_from_pair(self, mock_pair_cls):
        """护栏结果中的 findings 来自 GuardrailsPair 返回值的 violations/redactions

        修复后 _check_guardrails 从 GuardrailResult.violations 和
        GuardrailResult.redactions 组合 findings，不再是直接透传 dict.findings。
        """
        mock_pair = MagicMock()
        mock_pair_cls.return_value = mock_pair
        mock_redaction = {"type": "email", "original": "email@domain.com", "redacted": "[REDACTED]"}
        mock_pair.check_input.return_value = make_guardrails_result(
            passed=True,
            redactions=[mock_redaction],
        )

        node = LangGraphGovernanceNode()
        result = node._check_guardrails("contact email@domain.com", direction="input")

        # findings 应包含 redaction 信息
        assert len(result["findings"]) > 0


# ═══════════════════════════════════════════════════════════
#  3. _check_compliance 测试（mock ComplianceEngine）
# ═══════════════════════════════════════════════════════════

class TestCheckCompliance:

    @patch("harness.compliance_engine.ComplianceEngine")
    def test_compliance_scan_passes(self, mock_engine_cls):
        """合规扫描通过时返回 passed=True

        修复后 _check_compliance 使用 scan_quick() 而非 scan()，
        不再需要 mock Artifact 和 ScanContext。
        """
        mock_engine = MagicMock()
        mock_engine_cls.return_value = mock_engine

        # 构造 mock 的 ComplianceResult
        mock_result = MagicMock()
        mock_result.passed = True
        mock_result.rule_id = "SEC-001"
        mock_result.findings = []
        mock_engine.scan_quick.return_value = [mock_result]

        node = LangGraphGovernanceNode()
        state = make_state(output_text="safe code")
        result = node._check_compliance(state)

        assert result["type"] == "compliance"
        assert result["passed"] is True
        assert result["findings"] == []

    @patch("harness.compliance_engine.ComplianceEngine")
    def test_compliance_scan_fails_with_findings(self, mock_engine_cls):
        """合规扫描失败时返回 passed=False 和 findings 列表

        修复后使用 scan_quick(content, path) 而非 scan(artifacts, context)。
        """
        mock_engine = MagicMock()
        mock_engine_cls.return_value = mock_engine

        mock_result = MagicMock()
        mock_result.passed = False
        mock_result.rule_id = "PII-001"
        mock_result.findings = ["SSN found at line 5"]
        mock_engine.scan_quick.return_value = [mock_result]

        node = LangGraphGovernanceNode()
        state = make_state(output_text="SSN: 123-45-6789")
        result = node._check_compliance(state)

        assert result["passed"] is False
        assert len(result["findings"]) == 1
        assert result["findings"][0]["rule_id"] == "PII-001"

    def test_compliance_empty_content_returns_pass(self):
        """state 中无内容时合规扫描直接通过"""
        node = LangGraphGovernanceNode()
        state = make_state(input_text="", output_text="")
        # mock 内部 import 路径以避免真实引擎
        with patch("harness.compliance_engine.ComplianceEngine"):
            with patch("harness.types.Artifact"):
                with patch("harness.types.ScanContext"):
                    result = node._check_compliance(state)

        assert result["type"] == "compliance"
        assert result["passed"] is True
        assert result["findings"] == []

    @patch("harness.compliance_engine.ComplianceEngine",
           side_effect=Exception("engine crash"))
    def test_compliance_exception_does_not_block(self, mock_engine_cls):
        """合规引擎异常时 passed=True（不阻塞）+ warning"""
        node = LangGraphGovernanceNode()
        state = make_state(output_text="some content")
        result = node._check_compliance(state)

        # 异常不阻塞
        assert result["passed"] is True
        assert "warning" in result["findings"][0]


# ═══════════════════════════════════════════════════════════
#  4. _evaluate_gate 三种门禁模式测试
# ═══════════════════════════════════════════════════════════

class TestEvaluateGate:

    def test_loose_mode_always_allow(self):
        """loose 模式下无论是否有失败，都返回 allow"""
        node = LangGraphGovernanceNode(config={"gate_mode": "loose"})
        # 即使有失败结果
        results = [
            {"type": "guardrails", "passed": False,
             "findings": [{"severity": "critical"}]},
        ]
        gate = node._evaluate_gate(results)

        assert gate["decision"] == "allow"
        assert gate["blocked"] is False

    def test_loose_mode_empty_results(self):
        """loose 模式下空结果也返回 allow"""
        node = LangGraphGovernanceNode(config={"gate_mode": "loose"})
        gate = node._evaluate_gate([])

        assert gate["decision"] == "allow"
        assert gate["blocked"] is False

    def test_strict_mode_any_failed_blocks(self):
        """strict 模式下任何失败 → blocked"""
        node = LangGraphGovernanceNode(config={"gate_mode": "strict"})
        results = [
            {"type": "guardrails", "passed": False, "findings": []},
        ]
        gate = node._evaluate_gate(results)

        assert gate["decision"] == "block"
        assert gate["blocked"] is True

    def test_strict_mode_all_passed_allows(self):
        """strict 模式下全部通过 → allow"""
        node = LangGraphGovernanceNode(config={"gate_mode": "strict"})
        results = [
            {"type": "guardrails", "passed": True, "findings": []},
            {"type": "compliance", "passed": True, "findings": []},
        ]
        gate = node._evaluate_gate(results)

        assert gate["decision"] == "allow"
        assert gate["blocked"] is False

    def test_hybrid_mode_severe_blocks(self):
        """hybrid 模式下严重级别（critical/high）→ blocked + interrupt_before"""
        node = LangGraphGovernanceNode(config={"gate_mode": "hybrid"})
        results = [
            {"type": "guardrails", "passed": False,
             "findings": [{"severity": "critical", "rule": "PII"}]},
        ]
        gate = node._evaluate_gate(results)

        assert gate["decision"] == "block"
        assert gate["blocked"] is True
        assert gate["interrupt_before"] == ["human_review"]

    def test_hybrid_mode_high_severity_blocks(self):
        """hybrid 模式下 high 级别 → blocked"""
        node = LangGraphGovernanceNode(config={"gate_mode": "hybrid"})
        results = [
            {"type": "compliance", "passed": False,
             "findings": [{"severity": "high"}]},
        ]
        gate = node._evaluate_gate(results)

        assert gate["decision"] == "block"
        assert gate["blocked"] is True

    def test_hybrid_mode_non_severe_failed_warns(self):
        """hybrid 模式下失败但非严重 → warn（不阻塞）"""
        node = LangGraphGovernanceNode(config={"gate_mode": "hybrid"})
        results = [
            {"type": "guardrails", "passed": False,
             "findings": [{"severity": "medium"}]},
        ]
        gate = node._evaluate_gate(results)

        assert gate["decision"] == "warn"
        assert gate["blocked"] is False

    def test_hybrid_mode_all_passed_allows(self):
        """hybrid 模式下全部通过 → allow"""
        node = LangGraphGovernanceNode(config={"gate_mode": "hybrid"})
        results = [
            {"type": "guardrails", "passed": True, "findings": []},
        ]
        gate = node._evaluate_gate(results)

        assert gate["decision"] == "allow"
        assert gate["blocked"] is False

    def test_hybrid_mode_mixed_severity_blocks_on_severe(self):
        """hybrid 模式下混合结果：有 severe 的发现 → 仍然 block"""
        node = LangGraphGovernanceNode(config={"gate_mode": "hybrid"})
        results = [
            {"type": "guardrails", "passed": True, "findings": []},
            {"type": "compliance", "passed": False,
             "findings": [{"severity": "medium"}, {"severity": "critical"}]},
        ]
        gate = node._evaluate_gate(results)

        assert gate["decision"] == "block"
        assert gate["blocked"] is True

    def test_default_findings_severity_is_medium(self):
        """findings 中未指定 severity 时默认为 medium（不触发 hybrid block）"""
        node = LangGraphGovernanceNode(config={"gate_mode": "hybrid"})
        results = [
            {"type": "guardrails", "passed": False,
             "findings": [{"rule": "style"}]},  # 无 severity 字段
        ]
        gate = node._evaluate_gate(results)

        # 默认 severity="medium"，hybrid 模式下 → warn
        assert gate["decision"] == "warn"
        assert gate["blocked"] is False


# ═══════════════════════════════════════════════════════════
#  5. execute 完整流程测试
# ═══════════════════════════════════════════════════════════

class TestExecute:

    @patch.object(LangGraphGovernanceNode, "_check_compliance")
    @patch.object(LangGraphGovernanceNode, "_check_guardrails")
    def test_full_flow_input_output_compliance_gate(self, mock_guardrails, mock_compliance):
        """execute 完整流程：输入护栏 → 输出护栏 → 合规 → 门禁"""
        mock_guardrails.side_effect = [
            make_guardrails_check_result(direction="input", passed=True),
            make_guardrails_check_result(direction="output", passed=True),
        ]
        mock_compliance.return_value = make_compliance_result(passed=True)

        node = LangGraphGovernanceNode()
        state = make_state(input_text="safe input", output_text="safe output")
        result = node.execute(state)

        # 检查 mock 调用次数：input + output = 2次 guardrails
        assert mock_guardrails.call_count == 2
        mock_compliance.assert_called_once()

        # 结果结构完整
        assert "governance_results" in result
        assert "governance_passed" in result
        assert "governance_blocked" in result
        assert "gate_decision" in result
        assert result["governance_passed"] is True
        assert result["governance_blocked"] is False
        assert result["gate_decision"] == "allow"

    @patch.object(LangGraphGovernanceNode, "_check_compliance")
    @patch.object(LangGraphGovernanceNode, "_check_guardrails")
    def test_execute_with_guardrails_failure(self, mock_guardrails, mock_compliance):
        """输入护栏失败时 passed=False，但 loose 模式不阻塞"""
        mock_guardrails.return_value = make_guardrails_check_result(
            direction="input", passed=False,
            findings=[{"severity": "high"}],
        )
        mock_compliance.return_value = make_compliance_result(passed=True)

        node = LangGraphGovernanceNode(config={"gate_mode": "loose"})
        state = make_state(input_text="bad input", output_text="")
        result = node.execute(state)

        # loose 模式不阻塞
        assert result["governance_passed"] is False
        assert result["governance_blocked"] is False
        assert result["gate_decision"] == "allow"

    @patch.object(LangGraphGovernanceNode, "_check_compliance")
    @patch.object(LangGraphGovernanceNode, "_check_guardrails")
    def test_execute_skips_input_guardrails_when_disabled(self, mock_guardrails,
                                                           mock_compliance):
        """配置禁用输入护栏时跳过检查"""
        mock_guardrails.return_value = make_guardrails_check_result(
            direction="output", passed=True,
        )
        mock_compliance.return_value = make_compliance_result(passed=True)

        node = LangGraphGovernanceNode(config={
            "check_input_guardrails": False,
            "check_output_guardrails": True,
            "check_compliance": True,
            "gate_mode": "hybrid",
        })
        state = make_state(input_text="some text", output_text="output")
        result = node.execute(state)

        # 只调用 output 方向的护栏，不调用 input
        mock_guardrails.assert_called_once_with("output", direction="output")

    @patch.object(LangGraphGovernanceNode, "_check_compliance")
    @patch.object(LangGraphGovernanceNode, "_check_guardrails")
    def test_execute_skips_compliance_when_disabled(self, mock_guardrails, mock_compliance):
        """配置禁用合规扫描时跳过"""
        mock_guardrails.return_value = make_guardrails_check_result(
            direction="input", passed=True,
        )

        node = LangGraphGovernanceNode(config={
            "check_input_guardrails": True,
            "check_output_guardrails": False,
            "check_compliance": False,
            "gate_mode": "hybrid",
        })
        state = make_state(input_text="text", output_text="")
        result = node.execute(state)

        mock_compliance.assert_not_called()

    @patch.object(LangGraphGovernanceNode, "_check_compliance")
    @patch.object(LangGraphGovernanceNode, "_check_guardrails")
    def test_execute_empty_text_skips_guardrails(self, mock_guardrails, mock_compliance):
        """state 中 input_text/output_text 为空时不调用护栏"""
        mock_compliance.return_value = make_compliance_result(passed=True)

        node = LangGraphGovernanceNode()
        state = make_state(input_text="", output_text="")
        result = node.execute(state)

        mock_guardrails.assert_not_called()
        # 只有合规扫描结果
        assert len(result["governance_results"]) == 1

    @patch.object(LangGraphGovernanceNode, "_check_compliance")
    @patch.object(LangGraphGovernanceNode, "_check_guardrails")
    def test_execute_strict_blocks_on_failure(self, mock_guardrails, mock_compliance):
        """strict 模式下任何失败 → gate_decision=block"""
        mock_guardrails.side_effect = [
            make_guardrails_check_result(direction="input", passed=True),
            make_guardrails_check_result(direction="output", passed=False,
                                          findings=[{"severity": "medium"}]),
        ]
        mock_compliance.return_value = make_compliance_result(passed=True)

        node = LangGraphGovernanceNode(config={"gate_mode": "strict"})
        state = make_state(input_text="ok", output_text="bad output")
        result = node.execute(state)

        assert result["gate_decision"] == "block"
        assert result["governance_blocked"] is True


# ═══════════════════════════════════════════════════════════
#  6. wrap_node_with_governance 前置/后置包裹测试
# ═══════════════════════════════════════════════════════════

class TestWrapNodeWithGovernance:

    @patch.object(LangGraphGovernanceNode, "_check_compliance")
    @patch.object(LangGraphGovernanceNode, "_check_guardrails")
    def test_wrap_executes_node_fn(self, mock_guardrails, mock_compliance):
        """包裹函数执行原始 node_fn"""
        mock_guardrails.return_value = make_guardrails_check_result(
            direction="output", passed=True,
        )
        mock_compliance.return_value = make_compliance_result(passed=True)

        def my_node(state):
            return {"output_text": f"processed: {state['input_text']}"}

        wrapped = wrap_node_with_governance(my_node, config={"gate_mode": "loose"})
        state = make_state(input_text="hello")
        result = wrapped(state)

        assert "processed: hello" in result["output_text"]

    @patch.object(LangGraphGovernanceNode, "_check_compliance")
    @patch.object(LangGraphGovernanceNode, "_check_guardrails")
    def test_wrap_merges_node_result_with_governance(self, mock_guardrails, mock_compliance):
        """包裹结果合并原始节点输出和治理字段"""
        mock_guardrails.return_value = make_guardrails_check_result(
            direction="output", passed=True,
        )
        mock_compliance.return_value = make_compliance_result(passed=True)

        def my_node(state):
            return {"output_text": "result", "custom_field": "value"}

        wrapped = wrap_node_with_governance(my_node, config={"gate_mode": "loose"})
        state = make_state(input_text="hello", output_text="")
        result = wrapped(state)

        # 原始节点字段保留
        assert result["output_text"] == "result"
        assert result["custom_field"] == "value"
        # 治理字段附加
        assert "governance_results" in result
        assert "governance_passed" in result
        assert "governance_blocked" in result
        assert "gate_decision" in result

    @patch.object(LangGraphGovernanceNode, "_check_guardrails")
    def test_wrap_post_check_uses_merged_state_output(self, mock_guardrails):
        """后置输出护栏检查使用 node_fn 返回的 output_text"""
        mock_guardrails.side_effect = [
            make_guardrails_check_result(direction="input", passed=True),
            make_guardrails_check_result(direction="output", passed=True),
        ]

        def my_node(state):
            return {"output_text": "AI generated text"}

        wrapped = wrap_node_with_governance(my_node, config={
            "gate_mode": "loose",
            "check_compliance": False,
        })
        state = make_state(input_text="prompt")
        result = wrapped(state)

        # 第二次 _check_guardrails 调用应使用 node_fn 的 output_text
        calls = mock_guardrails.call_args_list
        assert calls[0] == (("prompt",), {"direction": "input"})
        assert calls[1] == (("AI generated text",), {"direction": "output"})

    @patch.object(LangGraphGovernanceNode, "_check_guardrails")
    def test_wrap_disables_input_guardrails_skips_pre_check(self, mock_guardrails):
        """配置禁用输入护栏时跳过前置检查"""
        mock_guardrails.return_value = make_guardrails_check_result(
            direction="output", passed=True,
        )

        def my_node(state):
            return {"output_text": "output"}

        wrapped = wrap_node_with_governance(my_node, config={
            "check_input_guardrails": False,
            "check_output_guardrails": True,
            "check_compliance": False,
            "gate_mode": "loose",
        })
        state = make_state(input_text="text")
        result = wrapped(state)

        # 只调用 output 方向
        mock_guardrails.assert_called_once_with("output", direction="output")


# ═══════════════════════════════════════════════════════════
#  7. strict 模式下输入护栏失败阻断测试
# ═══════════════════════════════════════════════════════════

class TestStrictInputGuardrailsBlock:

    @patch.object(LangGraphGovernanceNode, "_check_guardrails")
    def test_strict_input_failure_returns_blocked(self, mock_guardrails):
        """strict 模式下输入护栏失败 → 直接返回 blocked，不执行 node_fn"""
        mock_guardrails.return_value = make_guardrails_check_result(
            direction="input", passed=False,
            findings=[{"severity": "critical"}],
        )

        def my_node(state):
            # 不应该被执行
            return {"output_text": "should not reach here"}

        wrapped = wrap_node_with_governance(my_node, config={
            "gate_mode": "strict",
            "check_input_guardrails": True,
            "check_output_guardrails": True,
            "check_compliance": True,
        })
        state = make_state(input_text="malicious input")
        result = wrapped(state)

        # 阻断结果
        assert result["governance_blocked"] is True
        assert result["output_text"] == ""
        # node_fn 不应被执行，没有 custom 字段
        assert "should not reach here" not in str(result)

    @patch.object(LangGraphGovernanceNode, "_check_guardrails")
    def test_hybrid_input_failure_does_not_block(self, mock_guardrails):
        """hybrid 模式下输入护栏失败 → 不阻断前置，继续执行 node_fn"""
        mock_guardrails.side_effect = [
            make_guardrails_check_result(direction="input", passed=False,
                                          findings=[{"severity": "medium"}]),
            make_guardrails_check_result(direction="output", passed=True),
        ]

        node_fn_tracker = {"called": False}

        def my_node(state):
            node_fn_tracker["called"] = True
            return {"output_text": "processed"}

        wrapped = wrap_node_with_governance(my_node, config={
            "gate_mode": "hybrid",
            "check_compliance": False,
        })
        state = make_state(input_text="questionable input")
        result = wrapped(state)

        # hybrid 模式不阻断前置
        assert node_fn_tracker["called"] is True
        assert result["output_text"] == "processed"

    @patch.object(LangGraphGovernanceNode, "_check_guardrails")
    def test_loose_input_failure_continues(self, mock_guardrails):
        """loose 模式下输入护栏失败 → 正常继续执行"""
        mock_guardrails.side_effect = [
            make_guardrails_check_result(direction="input", passed=False),
            make_guardrails_check_result(direction="output", passed=True),
        ]

        def my_node(state):
            return {"output_text": "result"}

        wrapped = wrap_node_with_governance(my_node, config={
            "gate_mode": "loose",
            "check_compliance": False,
        })
        state = make_state(input_text="bad input")
        result = wrapped(state)

        assert result["output_text"] == "result"
        assert result["governance_blocked"] is False


# ═══════════════════════════════════════════════════════════
#  8. build_governance_graph 图构建测试（mock langgraph）
# ═══════════════════════════════════════════════════════════

class TestBuildGovernanceGraph:

    def _mock_langgraph_modules(self):
        """构造 mock langgraph 模块，注入 sys.modules"""
        import types

        # 创建 mock langgraph.graph 模块
        mock_graph_module = types.ModuleType("langgraph.graph")
        mock_state_graph_cls = MagicMock()
        mock_graph_module.StateGraph = mock_state_graph_cls
        mock_graph_module.END = "__END__"

        # 创建 mock langgraph 模块
        mock_langgraph_module = types.ModuleType("langgraph")
        mock_langgraph_module.graph = mock_graph_module

        return {
            "langgraph": mock_langgraph_module,
            "langgraph.graph": mock_graph_module,
            "langgraph.graph.StateGraph": mock_state_graph_cls,
        }

    @patch("harness.integrations.langgraph_middleware.LangGraphGovernanceNode")
    @patch("harness.integrations.langgraph_middleware.wrap_node_with_governance")
    def test_graph_structure_with_steps(self, mock_wrap, mock_node_cls):
        """构建包含多个步骤的治理图"""
        mock_modules = self._mock_langgraph_modules()
        mock_state_graph_cls = mock_modules["langgraph.graph.StateGraph"]
        mock_graph_instance = MagicMock()
        mock_state_graph_cls.return_value = mock_graph_instance

        mock_gov_node = MagicMock()
        mock_gov_node.execute = MagicMock(return_value={
            "governance_passed": True,
            "governance_blocked": False,
        })
        mock_node_cls.return_value = mock_gov_node
        mock_wrap.return_value = MagicMock()

        with patch.dict("sys.modules", mock_modules):
            step_functions = {
                "analyze": MagicMock(return_value={"output_text": "analysis"}),
                "plan": MagicMock(return_value={"output_text": "plan"}),
                "execute": MagicMock(return_value={"output_text": "result"}),
            }

            graph = build_governance_graph(
                workflow_config={
                    "steps": ["analyze", "plan", "execute"],
                    "step_functions": step_functions,
                },
                governance_config={"gate_mode": "hybrid"},
            )

            # 验证节点被添加
            add_node_calls = mock_graph_instance.add_node.call_args_list
            node_names = [c[0][0] for c in add_node_calls]
            assert "input_guardrails" in node_names
            assert "output_guardrails" in node_names
            assert "analyze" in node_names
            assert "plan" in node_names
            assert "execute" in node_names

            # 验证 wrap_node_with_governance 被调用
            assert mock_wrap.call_count == 3  # 3 个步骤

            # 验证入口设置
            mock_graph_instance.set_entry_point.assert_called_once_with("input_guardrails")

    @patch("harness.integrations.langgraph_middleware.LangGraphGovernanceNode")
    @patch("harness.integrations.langgraph_middleware.wrap_node_with_governance")
    def test_graph_with_single_step(self, mock_wrap, mock_node_cls):
        """单步骤工作流的治理图构建"""
        mock_modules = self._mock_langgraph_modules()
        mock_state_graph_cls = mock_modules["langgraph.graph.StateGraph"]
        mock_graph_instance = MagicMock()
        mock_state_graph_cls.return_value = mock_graph_instance

        mock_gov_node = MagicMock()
        mock_gov_node.execute = MagicMock()
        mock_node_cls.return_value = mock_gov_node
        mock_wrap.return_value = MagicMock()

        with patch.dict("sys.modules", mock_modules):
            graph = build_governance_graph(
                workflow_config={
                    "steps": ["process"],
                    "step_functions": {"process": MagicMock()},
                },
            )

            # 单步骤不需要步骤间治理检查节点
            add_node_calls = mock_graph_instance.add_node.call_args_list
            node_names = [c[0][0] for c in add_node_calls]
            # 应有：input_guardrails, process, output_guardrails
            assert "input_guardrails" in node_names
            assert "process" in node_names
            assert "output_guardrails" in node_names

    @patch("harness.integrations.langgraph_middleware.LangGraphGovernanceNode")
    @patch("harness.integrations.langgraph_middleware.wrap_node_with_governance")
    def test_graph_edges_connect_correctly(self, mock_wrap, mock_node_cls):
        """验证边的连接关系"""
        mock_modules = self._mock_langgraph_modules()
        mock_state_graph_cls = mock_modules["langgraph.graph.StateGraph"]
        mock_graph_instance = MagicMock()
        mock_state_graph_cls.return_value = mock_graph_instance

        mock_gov_node = MagicMock()
        mock_gov_node.execute = MagicMock()
        mock_node_cls.return_value = mock_gov_node
        mock_wrap.return_value = MagicMock()

        with patch.dict("sys.modules", mock_modules):
            graph = build_governance_graph(
                workflow_config={
                    "steps": ["step_a", "step_b"],
                    "step_functions": {
                        "step_a": MagicMock(),
                        "step_b": MagicMock(),
                    },
                },
            )

            # 验证 add_edge 调用
            edge_calls = mock_graph_instance.add_edge.call_args_list
            # input_guardrails → step_a
            found_entry_edge = any(
                c[0][0] == "input_guardrails" and c[0][1] == "step_a"
                for c in edge_calls
            )
            assert found_entry_edge

            # output_guardrails → END
            found_end_edge = any(
                c[0][0] == "output_guardrails" and c[0][1] == "__END__"
                for c in edge_calls
            )
            assert found_end_edge


# ═══════════════════════════════════════════════════════════
#  9. langgraph ImportError 错误处理测试
# ═══════════════════════════════════════════════════════════

class TestBuildGovernanceGraphImportError:

    def test_raises_import_error_when_langgraph_missing(self):
        """langgraph 未安装时 build_governance_graph 抛出 ImportError"""
        # 通过 sys.modules mock 让 langgraph.graph 导入失败
        with patch.dict("sys.modules", {"langgraph": None, "langgraph.graph": None}):
            with pytest.raises(ImportError) as exc_info:
                build_governance_graph(
                    workflow_config={"steps": ["analyze"]},
                )

            # 错误信息包含安装提示
            assert "langgraph" in str(exc_info.value)
            assert "harness-cook[langgraph]" in str(exc_info.value)

    def test_import_error_message_includes_install_command(self):
        """ImportError 信息包含安装命令"""
        with patch.dict("sys.modules", {"langgraph": None, "langgraph.graph": None}):
            with pytest.raises(ImportError) as exc_info:
                build_governance_graph(
                    workflow_config={"steps": ["step1"]},
                    governance_config={"gate_mode": "strict"},
                )

            error_msg = str(exc_info.value)
            assert "pip install" in error_msg


# ═══════════════════════════════════════════════════════════
#  10. @pytest.mark.langgraph 标记的集成测试
# ═══════════════════════════════════════════════════════════

@pytest.mark.langgraph
class TestLanggraphIntegration:

    """集成测试：需要安装 langgraph 包才能运行

    运行方式：pytest -m langgraph
    """

    def test_build_governance_graph_returns_state_graph(self):
        """build_governance_graph 返回 StateGraph 实例"""
        try:
            from langgraph.graph import StateGraph
        except ImportError:
            pytest.skip("langgraph not installed")

        def analyze_fn(state):
            return {"output_text": f"analysis of {state.get('input_text', '')}"}

        graph = build_governance_graph(
            workflow_config={
                "steps": ["analyze"],
                "step_functions": {"analyze": analyze_fn},
            },
            governance_config={"gate_mode": "hybrid"},
        )

        assert isinstance(graph, StateGraph)

    def test_graph_compiles_and_invokes(self):
        """治理图可以 compile 和 invoke"""
        try:
            from langgraph.graph import StateGraph
        except ImportError:
            pytest.skip("langgraph not installed")

        def step_fn(state):
            return {"output_text": "processed"}

        graph = build_governance_graph(
            workflow_config={
                "steps": ["process"],
                "step_functions": {"process": step_fn},
            },
            governance_config={
                "gate_mode": "loose",
                "check_input_guardrails": False,
                "check_output_guardrails": False,
                "check_compliance": False,
            },
        )

        compiled = graph.compile()

        # invoke 需要初始 state
        result = compiled.invoke({
            "input_text": "test input",
            "output_text": "",
        })

        # 验证结果包含治理字段
        assert "governance_passed" in result
        assert "gate_decision" in result

    def test_wrap_node_with_governance_in_graph(self):
        """wrap_node_with_governance 在真实 StateGraph 中工作"""
        try:
            from langgraph.graph import StateGraph
        except ImportError:
            pytest.skip("langgraph not installed")

        def my_step(state):
            return {"output_text": "step output"}

        wrapped = wrap_node_with_governance(my_step, config={
            "gate_mode": "loose",
            "check_input_guardrails": False,
            "check_output_guardrails": False,
            "check_compliance": False,
        })

        graph = build_governance_graph(
            workflow_config={
                "steps": ["my_step"],
                "step_functions": {"my_step": wrapped},
            },
            governance_config={"gate_mode": "loose"},
        )

        compiled = graph.compile()
        result = compiled.invoke({"input_text": "hello", "output_text": ""})

        assert result.get("output_text") is not None

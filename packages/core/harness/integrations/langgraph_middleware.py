"""
LangGraphMiddleware — LangGraph 治理中间件

将 harness-cook 的治理能力嵌入 LangGraph 工作流，在工作流步骤间
插入治理检查点（输入护栏、输出护栏、合规检查、门禁评审）。

核心组件：
1. LangGraphGovernanceNode — LangGraph 兼容节点，执行治理检查
2. wrap_node_with_governance — 前置输入护栏 + 后置输出护栏+门禁+合规
3. build_governance_graph — 构建嵌入治理节点的 StateGraph

安装：pip install harness-cook[langgraph]
"""

import json
import logging
from typing import Optional, Callable, Any, Dict, List

from harness.integrations.base import ExternalEngineChecker

logger = logging.getLogger("harness.integrations.langgraph")


# ─── LangGraphGovernanceNode ──────────────────────────────────────


class LangGraphGovernanceNode:
    """LangGraph 兼容的治理检查节点

    在工作流 StateGraph 中作为节点插入，执行：
    - 输入护栏检查（PII、毒性等）
    - 输出护栏检查
    - 合规扫描
    - 门禁评审（HYBRID 模式使用 interrupt_before）

    用法：
        governance_node = LangGraphGovernanceNode(
            config={
                "check_input_guardrails": True,
                "check_output_guardrails": True,
                "check_compliance": True,
                "gate_mode": "hybrid",
            }
        )
        # 在 StateGraph 中添加节点
        graph.add_node("governance_check", governance_node.execute)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {
            "check_input_guardrails": True,
            "check_output_guardrails": True,
            "check_compliance": True,
            "gate_mode": "hybrid",
        }
        self._gate_mode = self._config.get("gate_mode", "hybrid")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行治理检查，返回更新后的状态

        LangGraph 节点要求：接收 state dict，返回更新字段 dict。

        状态字段约定：
        - input_text: 输入文本（输入护栏检查对象）
        - output_text: 输出文本（输出护栏检查对象）
        - governance_results: 治理检查结果列表
        - governance_passed: 总体是否通过
        - governance_blocked: 是否被门禁拦截（需要人工评审）
        """
        results = []

        # ── 输入护栏检查 ────────────────────────────────
        if self._config.get("check_input_guardrails", True):
            input_text = state.get("input_text", "")
            if input_text:
                input_result = self._check_guardrails(
                    input_text, direction="input",
                )
                results.append(input_result)

        # ── 输出护栏检查 ────────────────────────────────
        if self._config.get("check_output_guardrails", True):
            output_text = state.get("output_text", "")
            if output_text:
                output_result = self._check_guardrails(
                    output_text, direction="output",
                )
                results.append(output_result)

        # ── 合规扫描 ──────────────────────────────────────
        if self._config.get("check_compliance", True):
            compliance_result = self._check_compliance(state)
            results.append(compliance_result)

        # ── 门禁评审 ──────────────────────────────────────
        gate_result = self._evaluate_gate(results)

        # ── 状态更新 ──────────────────────────────────────
        passed = all(r.get("passed", True) for r in results)
        blocked = gate_result.get("blocked", False)

        return {
            "governance_results": results,
            "governance_passed": passed,
            "governance_blocked": blocked,
            "gate_decision": gate_result.get("decision", "allow"),
        }

    def _check_guardrails(
        self, text: str, direction: str = "input",
    ) -> Dict[str, Any]:
        """执行护栏检查

        使用 harness-cook 的 GuardrailsPair（内置）或外部引擎。
        GuardrailsPair 需要默认的 input/output 配置才能创建。
        """
        try:
            from harness.guardrails import GuardrailsPair
            from harness.types import (
                InputGuardrailConfig, OutputGuardrailConfig, GuardrailAction,
            )

            input_config = InputGuardrailConfig(
                detect_pii_types=["email", "phone", "ssn", "credit_card", "api_key", "ip_address"],
                pii_action=GuardrailAction.REDACT,
            )
            output_config = OutputGuardrailConfig(
                detect_pii_in_output=True,
                output_pii_action=GuardrailAction.REDACT,
            )
            pair = GuardrailsPair(input_config=input_config, output_config=output_config)

            if direction == "input":
                result = pair.check_input(text)
            else:
                result = pair.check_output(text)

            # GuardrailResult 是 dataclass，用属性访问而非 dict
            findings = []
            if result.violations:
                findings.extend([str(v) for v in result.violations])
            if result.redactions:
                findings.extend([
                    f"PII redacted: {r.get('type', 'unknown')}" if isinstance(r, dict) else str(r)
                    for r in result.redactions
                ])

            return {
                "type": "guardrails",
                "direction": direction,
                "passed": not result.violations,
                "blocked": result.blocked,
                "action": result.action.value if hasattr(result.action, "value") else str(result.action),
                "findings": findings,
                "processed_content": result.processed_content,
            }
        except Exception as e:
            logger.warning(f"Guardrails check failed: {e}")
            return {
                "type": "guardrails",
                "direction": direction,
                "passed": True,  # 护栏检查失败不阻塞，记录警告
                "findings": [{"warning": f"guardrails check failed: {e}"}],
            }

    def _check_compliance(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行合规扫描

        使用 ComplianceEngine.scan_quick() 进行单文件快速扫描，
        避免手动构造 Artifact/ScanContext 的 API 差异问题。
        """
        try:
            from harness.compliance_engine import ComplianceEngine
            engine = ComplianceEngine()

            # 从 state 中提取需要检查的文本
            content = state.get("output_text", state.get("input_text", ""))
            if not content:
                return {
                    "type": "compliance",
                    "passed": True,
                    "findings": [],
                }

            file_path = state.get("file_path", "unknown")
            results = engine.scan_quick(content, path=file_path)

            # 合并所有规则的结果
            passed = all(r.passed for r in results) if results else True
            findings = []
            for r in results:
                if not r.passed:
                    for f in r.findings:
                        findings.append({
                            "rule_id": r.rule_id,
                            "message": f,
                        })

            return {
                "type": "compliance",
                "passed": passed,
                "findings": findings,
            }
        except Exception as e:
            logger.warning(f"Compliance check failed: {e}")
            return {
                "type": "compliance",
                "passed": True,  # 合规检查失败不阻塞
                "findings": [{"warning": f"compliance check failed: {e}"}],
            }

    def _evaluate_gate(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """门禁评审

        gate_mode:
        - strict: 任何检查失败 → blocked
        - hybrid: 严重级别 high/critical → blocked + interrupt_before
        - loose: 仅记录，不阻塞
        """
        if self._gate_mode == "loose":
            return {"decision": "allow", "blocked": False}

        # 收集失败级别
        any_failed = False
        any_severe = False
        for r in results:
            if not r.get("passed", True):
                any_failed = True
                # 检查是否严重
                findings = r.get("findings", [])
                for f in findings:
                    severity = f.get("severity", "medium")
                    if severity in ("critical", "high"):
                        any_severe = True
                        break

        if self._gate_mode == "strict" and any_failed:
            return {"decision": "block", "blocked": True}

        if self._gate_mode == "hybrid" and any_severe:
            return {
                "decision": "block",
                "blocked": True,
                "interrupt_before": ["human_review"],  # HYBRID 模式使用 LangGraph interrupt
            }

        if self._gate_mode == "hybrid" and any_failed:
            return {"decision": "warn", "blocked": False}

        return {"decision": "allow", "blocked": False}


# ─── wrap_node_with_governance ────────────────────────────────────


def wrap_node_with_governance(
    node_fn: Callable,
    config: Optional[Dict[str, Any]] = None,
) -> Callable:
    """将 LangGraph 节点函数包裹在治理检查中

    前置：输入护栏检查
    执行：原始节点函数
    后置：输出护栏检查 + 门禁评审 + 合规扫描

    用法：
        original_node = lambda state: {"output_text": process(state["input_text"])}
        wrapped = wrap_node_with_governance(original_node, config={
            "gate_mode": "hybrid",
        })
        graph.add_node("my_step", wrapped)

    Returns:
        包裹后的节点函数，接收 state dict，返回更新字段 dict
    """
    governance_node = LangGraphGovernanceNode(config)

    def wrapped_node(state: Dict[str, Any]) -> Dict[str, Any]:
        # ── 前置输入护栏 ──────────────────────────────
        if governance_node._config.get("check_input_guardrails", True):
            input_text = state.get("input_text", "")
            if input_text:
                input_check = governance_node._check_guardrails(
                    input_text, direction="input",
                )
                if not input_check.get("passed", True) and governance_node._gate_mode == "strict":
                    return {
                        "governance_blocked": True,
                        "governance_results": [input_check],
                        "output_text": "",
                    }

        # ── 执行原始节点 ──────────────────────────────
        node_result = node_fn(state)

        # 合入原始节点输出到 state（用于后置检查）
        merged_state = {**state, **node_result}

        # ── 后置输出护栏 + 合规 + 门禁 ──────────────
        post_results = []

        # 输出护栏
        output_text = merged_state.get("output_text", "")
        if output_text and governance_node._config.get("check_output_guardrails", True):
            output_check = governance_node._check_guardrails(
                output_text, direction="output",
            )
            post_results.append(output_check)

        # 合规扫描
        if governance_node._config.get("check_compliance", True):
            compliance_check = governance_node._check_compliance(merged_state)
            post_results.append(compliance_check)

        # 门禁评审
        gate_result = governance_node._evaluate_gate(post_results)

        # 合并结果
        all_results = (
            [input_check] if "input_check" in dir() and input_text else []
        ) + post_results

        passed = all(r.get("passed", True) for r in all_results)
        blocked = gate_result.get("blocked", False)

        return {
            **node_result,
            "governance_results": all_results,
            "governance_passed": passed,
            "governance_blocked": blocked,
            "gate_decision": gate_result.get("decision", "allow"),
        }

    return wrapped_node


# ─── build_governance_graph ────────────────────────────────────────


def build_governance_graph(
    workflow_config: Dict[str, Any],
    governance_config: Optional[Dict[str, Any]] = None,
) -> Any:
    """构建嵌入治理节点的 LangGraph StateGraph

    在每个工作流步骤前后插入治理检查点，形成：
    input_guardrails → step_1 → governance_check → step_2 → governance_check → ... → output_guardrails

    用法：
        graph = build_governance_graph(
            workflow_config={
                "steps": ["analyze", "plan", "execute"],
                "step_functions": {
                    "analyze": analyze_fn,
                    "plan": plan_fn,
                    "execute": execute_fn,
                },
            },
            governance_config={
                "gate_mode": "hybrid",
                "check_input_guardrails": True,
                "check_output_guardrails": True,
                "check_compliance": True,
            },
        )

    依赖：langgraph 包（pip install harness-cook[langgraph]）

    Returns:
        LangGraph StateGraph 实例，可直接 compile() 和 invoke()
    """
    try:
        from langgraph.graph import StateGraph, END
    except ImportError:
        logger.warning("langgraph not installed — cannot build governance graph")
        raise ImportError(
            "langgraph is required for build_governance_graph. "
            "Install with: pip install harness-cook[langgraph]"
        )

    governance_config = governance_config or {
        "gate_mode": "hybrid",
        "check_input_guardrails": True,
        "check_output_guardrails": True,
        "check_compliance": True,
    }

    # ── 定义状态 Schema ──────────────────────────────
    # 使用 TypedDict 或 dict 作为状态类型
    from typing import TypedDict

    class GovernanceState(TypedDict, total=False):
        input_text: str
        output_text: str
        file_path: str
        file_type: str
        project_root: str
        metadata: Dict[str, Any]
        governance_results: List[Dict[str, Any]]
        governance_passed: bool
        governance_blocked: bool
        gate_decision: str
        current_step: str
        step_output: Dict[str, Any]

    # ── 构建 StateGraph ──────────────────────────────
    graph = StateGraph(GovernanceState)

    # 输入护栏节点
    input_guardrails_node = LangGraphGovernanceNode({
        **governance_config,
        "check_output_guardrails": False,
        "check_compliance": False,
    })

    # 输出护栏节点
    output_guardrails_node = LangGraphGovernanceNode(governance_config)

    # 步骤间治理检查节点
    step_governance_node = LangGraphGovernanceNode({
        **governance_config,
        "check_input_guardrails": False,  # 步骤间只检查输出
    })

    # ── 添加节点 ──────────────────────────────────────
    graph.add_node("input_guardrails", input_guardrails_node.execute)

    # 添加工作流步骤（用治理包裹）
    steps = workflow_config.get("steps", [])
    step_functions = workflow_config.get("step_functions", {})

    wrapped_steps = {}
    for step_name in steps:
        step_fn = step_functions.get(step_name, lambda s: {"output_text": s.get("input_text", "")})
        wrapped_fn = wrap_node_with_governance(step_fn, governance_config)
        wrapped_steps[step_name] = wrapped_fn
        graph.add_node(step_name, wrapped_fn)

    # 步骤间治理检查
    if len(steps) > 1:
        for i in range(len(steps) - 1):
            check_name = f"governance_after_{steps[i]}"
            graph.add_node(check_name, step_governance_node.execute)

    graph.add_node("output_guardrails", output_guardrails_node.execute)

    # ── 定义边 ──────────────────────────────────────
    # START → input_guardrails → first_step
    graph.add_edge("input_guardrails", steps[0] if steps else "output_guardrails")

    # 步骤间：step → governance_check → next_step / END
    for i in range(len(steps) - 1):
        current_step = steps[i]
        check_name = f"governance_after_{current_step}"
        next_step = steps[i + 1]

        graph.add_edge(current_step, check_name)

        # 门禁决策路由
        def should_continue(state: Dict[str, Any]) -> str:
            if state.get("governance_blocked", False):
                return "output_guardrails"  # 阻塞 → 直接到输出
            return next_step

        graph.add_conditional_edges(
            check_name,
            should_continue,
            {
                next_step: next_step,
                "output_guardrails": "output_guardrails",
            },
        )

    # 最后一步 → output_guardrails
    if steps:
        last_step = steps[-1]
        graph.add_edge(last_step, "output_guardrails")

    # output_guardrails → END
    graph.add_edge("output_guardrails", END)

    # 设置入口
    graph.set_entry_point("input_guardrails")

    return graph

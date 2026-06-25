"""
LangGraph 治理中间件示例

演示如何通过 harness-cook 的 LangGraphMiddleware 在 LangGraph 工作流中
嵌入治理检查点（输入护栏、输出护栏、合规检查、门禁评审）。

运行方式:
  python demo_langgraph_governance.py

前置:
  pip install harness-cook[langgraph]

输出:
  - LangGraphGovernanceNode 执行结果
  - wrap_node_with_governance 包裹效果
  - build_governance_graph 构建的 StateGraph 结构
"""

import json
import sys

# ── 添加项目路径 ───────────────────────────────────────────────
sys.path.insert(0, "../../packages/core")

from harness.integrations.langgraph_middleware import (
    LangGraphGovernanceNode,
    wrap_node_with_governance,
)


def main():
    print("=" * 60)
    print("LangGraph Governance Middleware Demo")
    print("=" * 60)

    # ── 1. LangGraphGovernanceNode ─────────────────────────────
    print("\n--- 1. LangGraphGovernanceNode ---")

    governance_node = LangGraphGovernanceNode(config={
        "check_input_guardrails": True,
        "check_output_guardrails": True,
        "check_compliance": True,
        "gate_mode": "hybrid",
    })

    # 模拟 LangGraph 状态
    state = {
        "input_text": "请帮我分析这段代码",
        "output_text": "分析结果：代码结构良好，无重大问题",
        "file_path": "example.py",
        "file_type": "python",
        "project_root": "/path/to/project",
    }

    result = governance_node.execute(state)
    print(f"Governance passed: {result.get('governance_passed')}")
    print(f"Gate decision: {result.get('gate_decision')}")
    print(f"Governance blocked: {result.get('governance_blocked')}")
    print(f"Results count: {len(result.get('governance_results', []))}")

    # ── 2. wrap_node_with_governance ────────────────────────────
    print("\n--- 2. wrap_node_with_governance ---")

    # 定义原始节点函数
    def my_node(state):
        return {
            "output_text": f"Processed: {state.get('input_text', '')}",
        }

    # 包裹治理检查
    wrapped = wrap_node_with_governance(my_node, config={
        "gate_mode": "hybrid",
    })

    wrapped_result = wrapped(state)
    print(f"Wrapped node output: {wrapped_result.get('output_text', '')[:50]}")
    print(f"Governance passed: {wrapped_result.get('governance_passed')}")
    print(f"Gate decision: {wrapped_result.get('gate_decision')}")

    # ── 3. build_governance_graph（需要 langgraph 包）──────────────
    print("\n--- 3. build_governance_graph ---")

    try:
        from harness.integrations.langgraph_middleware import build_governance_graph

        graph = build_governance_graph(
            workflow_config={
                "steps": ["analyze", "plan", "execute"],
                "step_functions": {
                    "analyze": lambda s: {"output_text": f"Analyzed: {s.get('input_text', '')}"},
                    "plan": lambda s: {"output_text": f"Planned: {s.get('input_text', '')}"},
                    "execute": lambda s: {"output_text": f"Executed: {s.get('input_text', '')}"},
                },
            },
            governance_config={
                "gate_mode": "hybrid",
                "check_input_guardrails": True,
                "check_output_guardrails": True,
                "check_compliance": True,
            },
        )

        print(f"Graph type: {type(graph).__name__}")
        print("Governance graph built successfully!")

    except ImportError:
        print("langgraph not installed — skipping build_governance_graph demo")
        print("Install with: pip install harness-cook[langgraph]")

    # ── 4. 三档门禁对比 ──────────────────────────────────────
    print("\n--- 4. Gate Mode Comparison ---")

    for mode in ["strict", "hybrid", "loose"]:
        node = LangGraphGovernanceNode(config={
            "gate_mode": mode,
            "check_input_guardrails": True,
            "check_output_guardrails": True,
            "check_compliance": True,
        })
        result = node.execute({
            "input_text": "test",
            "output_text": "test output",
        })
        print(f"  {mode}: decision={result.get('gate_decision')}, "
              f"blocked={result.get('governance_blocked')}")


if __name__ == "__main__":
    main()

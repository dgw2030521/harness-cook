"""
DeerFlow 治理桥接示例

演示如何通过 harness-cook 的 DeerFlowBridge 将治理配置翻译为
DeerFlow workflow 定义，在工作流中注入治理检查点。

运行方式:
  python demo_deerflow_bridge.py

输出:
  - Gate → DeerFlow 验证步骤翻译结果
  - Profile → DeerFlow workflow 翻译结果
  - execute_with_governance 注入治理检查点的结果
"""

import json
import sys

# ── 添加项目路径 ───────────────────────────────────────────────
sys.path.insert(0, "../../packages/core")

from harness.integrations.deerflow_bridge import DeerFlowBridge


# ── 示例 Gate 定义 ────────────────────────────────────────────

SAMPLE_GATE = {
    "id": "quality_gate",
    "gate_type": "hybrid",
    "checks": [
        {
            "id": "no_pii",
            "category": "guardrails",
            "severity": "high",
            "description": "禁止 PII 信息泄露",
        },
        {
            "id": "no_sql_injection",
            "category": "security",
            "severity": "critical",
            "description": "禁止 SQL 注入漏洞",
        },
        {
            "id": "layer_violation",
            "category": "compliance",
            "severity": "medium",
            "description": "检查分层架构违规",
        },
    ],
    "auto_fix": False,
}


# ── 示例 Profile ──────────────────────────────────────────────

SAMPLE_PROFILE = {
    "name": "production",
    "gates": [
        SAMPLE_GATE,
        {
            "id": "security_gate",
            "gate_type": "strict",
            "checks": [
                {
                    "id": "no_hardcoded_secrets",
                    "category": "security",
                    "severity": "critical",
                    "description": "禁止硬编码密钥",
                },
            ],
            "auto_fix": False,
        },
    ],
    "rules": [],
}


# ── 示例 DeerFlow workflow ────────────────────────────────────

SAMPLE_WORKFLOW = {
    "name": "my_workflow",
    "steps": [
        {"name": "analyze", "type": "action", "description": "分析需求"},
        {"name": "plan", "type": "action", "description": "制定方案"},
        {"name": "execute", "type": "action", "description": "执行任务"},
    ],
    "edges": [
        {"from": "__start__", "to": "analyze"},
        {"from": "analyze", "to": "plan"},
        {"from": "plan", "to": "execute"},
        {"from": "execute", "to": "__end__"},
    ],
}


def main():
    print("=" * 60)
    print("DeerFlow Bridge Demo")
    print("=" * 60)

    bridge = DeerFlowBridge()

    # ── 1. Gate → DeerFlow 验证步骤 ────────────────────────
    print("\n--- 1. Gate → DeerFlow Validation Step ---")

    validation = bridge.translate_gate_to_validation(SAMPLE_GATE)
    print(json.dumps(validation, indent=2, ensure_ascii=False))

    # ── 2. Profile → DeerFlow workflow ─────────────────────
    print("\n--- 2. Profile → DeerFlow Workflow ---")

    workflow = bridge.translate_profile_to_workflow(SAMPLE_PROFILE)
    print(f"Workflow name: {workflow['name']}")
    print(f"Steps count: {len(workflow['steps'])}")
    print(f"Edges count: {len(workflow['edges'])}")
    print("\nSteps:")
    for step in workflow["steps"]:
        print(f"  - {step['name']} ({step['type']})")

    # ── 3. execute_with_governance ──────────────────────────
    print("\n--- 3. Execute with Governance Injection ---")

    result = bridge.execute_with_governance(
        SAMPLE_WORKFLOW,
        config={
            "gate_mode": "hybrid",
            "inject_governance": True,
        },
    )

    print(f"Governance injected: {result['governance_injected']}")
    print(f"Original steps: {result['original_steps_count']}")
    print(f"Enhanced steps: {result['enhanced_steps_count']}")
    print(f"Governance checkpoints added: {result['governance_checkpoints_added']}")
    print(f"Gate mode: {result['gate_mode']}")

    print("\nEnhanced steps:")
    for step in result["workflow"]["steps"]:
        print(f"  - {step['name']} ({step['type']})")

    # ── 4. 三档门禁对比 ──────────────────────────────────
    print("\n--- 4. Gate Mode Comparison ---")

    for mode in ["strict", "hybrid", "loose"]:
        gate = {**SAMPLE_GATE, "gate_type": mode}
        validation = bridge.translate_gate_to_validation(gate)
        print(f"  {mode}: interrupt_on_failure={validation.get('interrupt_on_failure')}")


if __name__ == "__main__":
    main()

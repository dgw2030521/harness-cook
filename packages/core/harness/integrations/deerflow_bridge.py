"""
DeerFlowBridge — DeerFlow 编排平台治理桥接

将 harness-cook 的治理配置翻译为 DeerFlow workflow 定义，
在工作流中注入治理检查点（验证步骤、评审关卡）。

核心组件：
1. translate_gate_to_validation — Gate 定义 → DeerFlow 验证步骤
2. translate_profile_to_workflow — Profile → DeerFlow workflow 定义
3. execute_with_governance — 注入治理检查点执行工作流

DeerFlow 是开源多智能体编排框架，支持 workflow 定义、验证步骤、
和中断机制。harness-cook 将其作为治理中间件桥接目标。

安装：pip install harness-cook[deerflow]
"""

import json
import logging
from typing import Optional, Dict, Any, List

from harness.integrations.base import ExternalEngineChecker

logger = logging.getLogger("harness.integrations.deerflow")


# ─── DeerFlowBridge ────────────────────────────────────────────────


class DeerFlowBridge:
    """DeerFlow 编排平台治理桥接

    将 harness-cook 的治理能力翻译为 DeerFlow 可消费的格式：
    - Gate → DeerFlow 验证步骤（validation_steps）
    - Profile → DeerFlow workflow 定义（含治理检查点）
    - 三档门禁 → DeerFlow 中断机制

    用法：
        bridge = DeerFlowBridge()
        # 翻译单个 Gate
        validation = bridge.translate_gate_to_validation(gate)
        # 翻译整个 Profile
        workflow = bridge.translate_profile_to_workflow(profile)
        # 执行带治理的工作流
        result = bridge.execute_with_governance(workflow_config, governance_config)
    """

    # ─── Gate → DeerFlow 验证步骤 ───────────────────────

    def translate_gate_to_validation(
        self,
        gate: Any,
    ) -> Dict[str, Any]:
        """将 Gate 定义翻译为 DeerFlow 验证步骤格式

        DeerFlow 验证步骤格式：
        {
            "name": "gate_name",
            "type": "validation",
            "checks": [
                {
                    "id": "check_id",
                    "category": "compliance/security/...",
                    "severity": "critical/high/...",
                    "description": "检查描述",
                }
            ],
            "mode": "strict/hybrid/loose",
            "auto_fix": false,
        }

        Args:
            gate: harness Gate 对象或 dict

        Returns:
            DeerFlow 验证步骤定义 dict
        """
        # 从 Gate 提取信息
        if isinstance(gate, dict):
            gate_id = gate.get("id", "unknown_gate")
            gate_type = gate.get("gate_type", "hybrid")
            checks = gate.get("checks", [])
            auto_fix = gate.get("auto_fix", False)
        else:
            gate_id = getattr(gate, "id", "unknown_gate")
            gate_type = getattr(gate, "gate_type", "hybrid")
            checks = getattr(gate, "checks", [])
            auto_fix = getattr(gate, "auto_fix", False)

        # 翻译 checks
        translated_checks = []
        for check in checks:
            if isinstance(check, dict):
                translated_checks.append({
                    "id": check.get("id", "unknown"),
                    "category": check.get("category", "compliance"),
                    "severity": check.get("severity", "medium"),
                    "description": check.get("description", ""),
                })
            else:
                translated_checks.append({
                    "id": getattr(check, "id", "unknown"),
                    "category": getattr(check, "category", "compliance"),
                    "severity": getattr(check, "severity", "medium"),
                    "description": getattr(check, "description", ""),
                })

        # Gate mode → DeerFlow mode
        mode_map = {
            "strict": "strict",
            "hybrid": "hybrid",
            "loose": "loose",
        }

        return {
            "name": f"gate_{gate_id}",
            "type": "validation",
            "checks": translated_checks,
            "mode": mode_map.get(gate_type, "hybrid"),
            "auto_fix": auto_fix,
            # DeerFlow 特定：interrupt_on_failure 用于 hybrid 门禁
            "interrupt_on_failure": gate_type == "hybrid",
        }

    # ─── Profile → DeerFlow workflow ───────────────────────

    def translate_profile_to_workflow(
        self,
        profile: Any,
    ) -> Dict[str, Any]:
        """将 Profile 翻译为 DeerFlow workflow 定义

        DeerFlow workflow 格式：
        {
            "name": "profile_name",
            "steps": [
                {"name": "step_1", "type": "action", ...},
                {"name": "validation_after_step_1", "type": "validation", ...},
                {"name": "step_2", "type": "action", ...},
                {"name": "validation_after_step_2", "type": "validation", ...},
                ...
            ],
            "edges": [
                {"from": "step_1", "to": "validation_after_step_1"},
                {"from": "validation_after_step_1", "to": "step_2",
                 "condition": "validation_passed"},
                ...
            ],
            "metadata": {
                "source": "harness-cook",
                "profile_name": "...",
            },
        }

        Args:
            profile: harness Profile 对象或 dict

        Returns:
            DeerFlow workflow 定义 dict
        """
        # 从 Profile 提取信息
        if isinstance(profile, dict):
            profile_name = profile.get("name", "default")
            gates = profile.get("gates", [])
            rules = profile.get("rules", [])
        else:
            profile_name = getattr(profile, "name", "default")
            gates = getattr(profile, "gates", [])
            rules = getattr(profile, "rules", [])

        steps = []
        edges = []

        # ── 初始护栏检查步骤 ──────────────────────────────
        input_validation = {
            "name": "input_guardrails",
            "type": "validation",
            "checks": [
                {
                    "id": "input_pii_check",
                    "category": "guardrails",
                    "severity": "high",
                    "description": "检查输入文本中的 PII 信息",
                },
                {
                    "id": "input_toxicity_check",
                    "category": "guardrails",
                    "severity": "high",
                    "description": "检查输入文本中的毒性内容",
                },
            ],
            "mode": "hybrid",
        }
        steps.append(input_validation)

        # ── 从 Gates 翻译验证步骤 ────────────────────────
        gate_validations = []
        for gate in gates:
            validation = self.translate_gate_to_validation(gate)
            gate_validations.append(validation)

        # ── 构建工作流步骤 ────────────────────────────────
        # 核心步骤：analyze → plan → execute → review
        core_steps = [
            {"name": "analyze", "type": "action", "description": "分析任务需求"},
            {"name": "plan", "type": "action", "description": "制定执行计划"},
            {"name": "execute", "type": "action", "description": "执行任务"},
            {"name": "review", "type": "action", "description": "审查执行结果"},
        ]

        # 在每个核心步骤后插入验证步骤
        for i, core_step in enumerate(core_steps):
            steps.append(core_step)

            # 插入对应的 Gate 验证（如果有的话）
            if i < len(gate_validations):
                validation_name = f"validation_after_{core_step['name']}"
                validation = gate_validations[i]
                validation["name"] = validation_name
                steps.append(validation)

                # 边：核心步骤 → 验证 → 下一步（条件路由）
                edges.append({
                    "from": core_step["name"],
                    "to": validation_name,
                })

                # 验证通过 → 下一步；验证失败 → human_review 或 END
                next_step = core_steps[i + 1]["name"] if i + 1 < len(core_steps) else "output_guardrails"
                edges.append({
                    "from": validation_name,
                    "to": next_step,
                    "condition": "validation_passed",
                })
                edges.append({
                    "from": validation_name,
                    "to": "human_review",
                    "condition": "validation_failed_and_hybrid",
                })
            else:
                # 没有 Gate 验证 → 直接到下一步
                next_step = core_steps[i + 1]["name"] if i + 1 < len(core_steps) else "output_guardrails"
                edges.append({
                    "from": core_step["name"],
                    "to": next_step,
                })

        # ── 人工评审步骤（HYBRID 门禁）───────────────────────
        steps.append({
            "name": "human_review",
            "type": "interrupt",
            "description": "人工评审（HYBRID 门禁中断点）",
        })
        # 人工评审通过 → 继续；失败 → END
        edges.append({
            "from": "human_review",
            "to": "output_guardrails",
            "condition": "review_approved",
        })

        # ── 输出护栏检查步骤 ──────────────────────────────
        output_validation = {
            "name": "output_guardrails",
            "type": "validation",
            "checks": [
                {
                    "id": "output_compliance_check",
                    "category": "compliance",
                    "severity": "medium",
                    "description": "检查输出合规性",
                },
                {
                    "id": "output_guardrails_check",
                    "category": "guardrails",
                    "severity": "high",
                    "description": "检查输出护栏",
                },
            ],
            "mode": "hybrid",
        }
        steps.append(output_validation)

        # ── 入口边 ────────────────────────────────────────
        edges.append({
            "from": "__start__",
            "to": "input_guardrails",
        })
        edges.append({
            "from": "input_guardrails",
            "to": "analyze",
            "condition": "validation_passed",
        })

        return {
            "name": f"harness_governance_{profile_name}",
            "steps": steps,
            "edges": edges,
            "metadata": {
                "source": "harness-cook",
                "profile_name": profile_name,
                "version": "2.0",
            },
        }

    # ─── 执行带治理的工作流 ────────────────────────────────

    def execute_with_governance(
        self,
        workflow: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """注入治理检查点并执行 DeerFlow 工作流

        在已定义的工作流中注入 governance 验证步骤，
        然后模拟执行（返回执行计划，而非真正执行）。

        Args:
            workflow: DeerFlow workflow 定义 dict
            config: 治理配置（gate_mode 等）

        Returns:
            执行结果 dict（含治理检查点注入信息）
        """
        config = config or {
            "gate_mode": "hybrid",
            "inject_governance": True,
        }

        if not config.get("inject_governance", True):
            # 不注入治理 → 直接返回工作流
            return {
                "workflow": workflow,
                "governance_injected": False,
                "steps": workflow.get("steps", []),
                "total_steps": len(workflow.get("steps", [])),
            }

        # ── 注入治理检查点 ──────────────────────────────
        original_steps = workflow.get("steps", [])
        original_edges = workflow.get("edges", [])

        enhanced_steps = []
        enhanced_edges = []

        for step in original_steps:
            enhanced_steps.append(step)

            # 在每个 action 步骤后注入治理验证
            if step.get("type") == "action":
                governance_step_name = f"governance_after_{step['name']}"
                governance_step = {
                    "name": governance_step_name,
                    "type": "validation",
                    "checks": [
                        {
                            "id": f"governance_{step['name']}",
                            "category": "governance",
                            "severity": "medium",
                            "description": f"治理检查点：{step.get('description', step['name'])}",
                        },
                    ],
                    "mode": config.get("gate_mode", "hybrid"),
                    "interrupt_on_failure": config.get("gate_mode") == "hybrid",
                }
                enhanced_steps.append(governance_step)

                # 边：action → governance
                enhanced_edges.append({
                    "from": step["name"],
                    "to": governance_step_name,
                })

        # ── 构建增强边 ──────────────────────────────────
        # 保留原始边中非 action → action 的边
        for edge in original_edges:
            from_step = edge.get("from", "")
            # 如果原始边从 action 到下一步，替换为从 governance 到下一步
            if from_step in [s["name"] for s in original_steps if s.get("type") == "action"]:
                governance_step_name = f"governance_after_{from_step}"
                # governance 通过 → 下一步
                enhanced_edges.append({
                    "from": governance_step_name,
                    "to": edge.get("to", ""),
                    "condition": "governance_passed",
                })
            else:
                enhanced_edges.append(edge)

        return {
            "workflow": {
                **workflow,
                "steps": enhanced_steps,
                "edges": enhanced_edges,
            },
            "governance_injected": True,
            "original_steps_count": len(original_steps),
            "enhanced_steps_count": len(enhanced_steps),
            "governance_checkpoints_added": len(enhanced_steps) - len(original_steps),
            "gate_mode": config.get("gate_mode", "hybrid"),
        }

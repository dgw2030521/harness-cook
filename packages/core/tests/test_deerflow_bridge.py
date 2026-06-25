"""DeerFlowBridge 单元测试 — DeerFlow 编排平台治理桥接

覆盖三个核心翻译方法的 dict/对象双输入、mode 映射、
条件路由、治理注入等场景，以及集成标记测试。

测试范围：
1. translate_gate_to_validation — dict 输入
2. translate_gate_to_validation — 对象输入（mock gate 对象）
3. checks 翻译（dict 和对象两种形式）
4. mode 映射（strict/hybrid/loose）
5. interrupt_on_failure 逻辑
6. translate_profile_to_workflow — dict 输入
7. translate_profile_to_workflow — 对象输入
8. workflow 结构完整性（steps/edges/metadata）
9. execute_with_governance — 不注入治理
10. execute_with_governance — 注入治理检查点
11. enhanced 边的条件路由
12. @pytest.mark.deerflow 集成测试
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.integrations.deerflow_bridge import DeerFlowBridge


# ─── Mock 对象 — 用于模拟 harness Gate / Check / Profile ────────────────


class MockCheck:
    """模拟 harness Gate Check 对象"""

    def __init__(self, id="check_1", category="compliance", severity="medium", description="测试检查"):
        self.id = id
        self.category = category
        self.severity = severity
        self.description = description


class MockGate:
    """模拟 harness Gate 对象"""

    def __init__(self, id="gate_1", gate_type="hybrid", checks=None, auto_fix=False):
        self.id = id
        self.gate_type = gate_type
        self.checks = checks or [MockCheck()]
        self.auto_fix = auto_fix


class MockProfile:
    """模拟 harness Profile 对象"""

    def __init__(self, name="test_profile", gates=None, rules=None):
        self.name = name
        self.gates = gates or []
        self.rules = rules or []


# ─── translate_gate_to_validation 测试 ────────────────────────────────────


class TestTranslateGateToValidation:
    """Gate → DeerFlow 验证步骤翻译测试"""

    def setup_method(self):
        self.bridge = DeerFlowBridge()

    # 1. dict 输入
    def test_gate_dict_input(self):
        """dict 形式的 Gate 输入正确翻译为验证步骤"""
        gate_dict = {
            "id": "security_gate",
            "gate_type": "strict",
            "checks": [
                {"id": "no-secrets", "category": "security", "severity": "critical", "description": "禁止硬编码密钥"},
            ],
            "auto_fix": True,
        }
        result = self.bridge.translate_gate_to_validation(gate_dict)

        assert result["name"] == "gate_security_gate"
        assert result["type"] == "validation"
        assert result["mode"] == "strict"
        assert result["auto_fix"] is True
        assert len(result["checks"]) == 1
        assert result["checks"][0]["id"] == "no-secrets"

    # 2. 对象输入
    def test_gate_object_input(self):
        """对象形式的 Gate 输入正确翻译为验证步骤"""
        gate_obj = MockGate(id="quality_gate", gate_type="loose", auto_fix=True)
        result = self.bridge.translate_gate_to_validation(gate_obj)

        assert result["name"] == "gate_quality_gate"
        assert result["type"] == "validation"
        assert result["mode"] == "loose"
        assert result["auto_fix"] is True

    # 3a. checks 翻译 — dict
    def test_checks_dict_translation(self):
        """dict 形式的 checks 正确翻译"""
        gate_dict = {
            "id": "g1",
            "gate_type": "hybrid",
            "checks": [
                {"id": "c1", "category": "security", "severity": "high", "description": "安全检查"},
                {"id": "c2", "category": "compliance", "severity": "medium", "description": "合规检查"},
            ],
            "auto_fix": False,
        }
        result = self.bridge.translate_gate_to_validation(gate_dict)

        assert len(result["checks"]) == 2
        assert result["checks"][0]["id"] == "c1"
        assert result["checks"][0]["category"] == "security"
        assert result["checks"][0]["severity"] == "high"
        assert result["checks"][1]["category"] == "compliance"

    # 3b. checks 翻译 — 对象
    def test_checks_object_translation(self):
        """对象形式的 checks 正确翻译"""
        checks = [
            MockCheck(id="obj_c1", category="privacy", severity="low", description="隐私检查"),
            MockCheck(id="obj_c2", category="performance", severity="medium", description="性能检查"),
        ]
        gate_obj = MockGate(id="g2", checks=checks)
        result = self.bridge.translate_gate_to_validation(gate_obj)

        assert len(result["checks"]) == 2
        assert result["checks"][0]["id"] == "obj_c1"
        assert result["checks"][0]["category"] == "privacy"
        assert result["checks"][0]["severity"] == "low"
        assert result["checks"][1]["category"] == "performance"

    # 3c. checks 缺失字段时使用默认值
    def test_checks_missing_fields_defaults(self):
        """checks 中缺失字段时回退到默认值"""
        gate_dict = {
            "id": "g_defaults",
            "gate_type": "hybrid",
            "checks": [{"id": "only_id"}],  # 缺少 category/severity/description
        }
        result = self.bridge.translate_gate_to_validation(gate_dict)

        assert result["checks"][0]["id"] == "only_id"
        assert result["checks"][0]["category"] == "compliance"  # 默认值
        assert result["checks"][0]["severity"] == "medium"  # 默认值
        assert result["checks"][0]["description"] == ""  # 默认值

    # 4. mode 映射
    def test_mode_strict(self):
        """gate_type=strict 映射为 mode=strict"""
        result = self.bridge.translate_gate_to_validation({"id": "g", "gate_type": "strict"})
        assert result["mode"] == "strict"

    def test_mode_hybrid(self):
        """gate_type=hybrid 映射为 mode=hybrid"""
        result = self.bridge.translate_gate_to_validation({"id": "g", "gate_type": "hybrid"})
        assert result["mode"] == "hybrid"

    def test_mode_loose(self):
        """gate_type=loose 映射为 mode=loose"""
        result = self.bridge.translate_gate_to_validation({"id": "g", "gate_type": "loose"})
        assert result["mode"] == "loose"

    def test_mode_unknown_defaults_hybrid(self):
        """未知的 gate_type 回退为 mode=hybrid"""
        result = self.bridge.translate_gate_to_validation({"id": "g", "gate_type": "unknown_type"})
        assert result["mode"] == "hybrid"

    # 5. interrupt_on_failure 逻辑
    def test_interrupt_on_failure_hybrid(self):
        """gate_type=hybrid 时 interrupt_on_failure=True"""
        result = self.bridge.translate_gate_to_validation({"id": "g", "gate_type": "hybrid"})
        assert result["interrupt_on_failure"] is True

    def test_interrupt_on_failure_strict(self):
        """gate_type=strict 时 interrupt_on_failure=False"""
        result = self.bridge.translate_gate_to_validation({"id": "g", "gate_type": "strict"})
        assert result["interrupt_on_failure"] is False

    def test_interrupt_on_failure_loose(self):
        """gate_type=loose 时 interrupt_on_failure=False"""
        result = self.bridge.translate_gate_to_validation({"id": "g", "gate_type": "loose"})
        assert result["interrupt_on_failure"] is False

    # 边界：空 Gate
    def test_empty_gate_dict(self):
        """空 dict 输入使用默认值"""
        result = self.bridge.translate_gate_to_validation({})
        assert result["name"] == "gate_unknown_gate"
        assert result["mode"] == "hybrid"
        assert result["checks"] == []
        assert result["auto_fix"] is False


# ─── translate_profile_to_workflow 测试 ───────────────────────────────────


class TestTranslateProfileToWorkflow:
    """Profile → DeerFlow workflow 定义翻译测试"""

    def setup_method(self):
        self.bridge = DeerFlowBridge()

    # 6. dict 输入
    def test_profile_dict_input(self):
        """dict 形式的 Profile 翻译为完整 workflow"""
        profile_dict = {
            "name": "my_project",
            "gates": [
                {
                    "id": "security",
                    "gate_type": "strict",
                    "checks": [{"id": "no-secrets", "category": "security", "severity": "high", "description": "密钥检查"}],
                },
            ],
            "rules": [],
        }
        result = self.bridge.translate_profile_to_workflow(profile_dict)

        assert result["name"] == "harness_governance_my_project"
        assert isinstance(result["steps"], list)
        assert isinstance(result["edges"], list)
        assert isinstance(result["metadata"], dict)

    # 7. 对象输入
    def test_profile_object_input(self):
        """对象形式的 Profile 翻译为完整 workflow"""
        gate = MockGate(id="quality", gate_type="loose")
        profile_obj = MockProfile(name="quality_project", gates=[gate])
        result = self.bridge.translate_profile_to_workflow(profile_obj)

        assert result["name"] == "harness_governance_quality_project"
        assert len(result["steps"]) > 0

    # 8. workflow 结构完整性
    def test_workflow_has_required_fields(self):
        """workflow 结果包含 steps、edges、metadata 三个必需字段"""
        result = self.bridge.translate_profile_to_workflow({"name": "minimal", "gates": []})

        assert "steps" in result
        assert "edges" in result
        assert "metadata" in result
        assert result["metadata"]["source"] == "harness-cook"
        assert result["metadata"]["profile_name"] == "minimal"
        assert result["metadata"]["version"] == "2.0"

    def test_workflow_has_guardrails_steps(self):
        """workflow 包含 input_guardrails 和 output_guardrails 步骤"""
        result = self.bridge.translate_profile_to_workflow({"name": "p", "gates": []})
        step_names = [s["name"] for s in result["steps"]]

        assert "input_guardrails" in step_names
        assert "output_guardrails" in step_names

    def test_workflow_has_core_steps(self):
        """workflow 包含 analyze、plan、execute、review 四个核心步骤"""
        result = self.bridge.translate_profile_to_workflow({"name": "p", "gates": []})
        step_names = [s["name"] for s in result["steps"]]

        assert "analyze" in step_names
        assert "plan" in step_names
        assert "execute" in step_names
        assert "review" in step_names

    def test_workflow_has_human_review_step(self):
        """workflow 包含 human_review 步骤"""
        result = self.bridge.translate_profile_to_workflow({"name": "p", "gates": []})
        step_names = [s["name"] for s in result["steps"]]

        assert "human_review" in step_names

    def test_workflow_start_edge(self):
        """workflow 包含 __start__ → input_guardrails 的入口边"""
        result = self.bridge.translate_profile_to_workflow({"name": "p", "gates": []})
        start_edges = [e for e in result["edges"] if e["from"] == "__start__"]

        assert len(start_edges) == 1
        assert start_edges[0]["to"] == "input_guardrails"

    def test_gate_validation_inserted_after_core_step(self):
        """Gate 验证步骤插在对应核心步骤之后"""
        gates = [
            {"id": "g1", "gate_type": "strict", "checks": [{"id": "c1"}]},
            {"id": "g2", "gate_type": "hybrid", "checks": [{"id": "c2"}]},
        ]
        result = self.bridge.translate_profile_to_workflow({"name": "p", "gates": gates})
        step_names = [s["name"] for s in result["steps"]]

        # 第一个 Gate 验证在 analyze 之后
        assert "validation_after_analyze" in step_names
        # 第二个 Gate 验证在 plan 之后
        assert "validation_after_plan" in step_names

    def test_gate_validation_edges_have_condition(self):
        """Gate 验证步骤的边包含条件路由"""
        gates = [
            {"id": "g1", "gate_type": "hybrid", "checks": [{"id": "c1"}]},
        ]
        result = self.bridge.translate_profile_to_workflow({"name": "p", "gates": gates})

        # 验证通过 → 下一步
        pass_edges = [e for e in result["edges"]
                      if e.get("from") == "validation_after_analyze"
                      and e.get("condition") == "validation_passed"]
        assert len(pass_edges) == 1

        # 验证失败 → human_review（hybrid 门禁）
        fail_edges = [e for e in result["edges"]
                      if e.get("from") == "validation_after_analyze"
                      and e.get("condition") == "validation_failed_and_hybrid"]
        assert len(fail_edges) == 1

    def test_no_gate_core_steps_have_direct_edges(self):
        """没有对应 Gate 的核心步骤直接连接下一步"""
        result = self.bridge.translate_profile_to_workflow({"name": "p", "gates": []})
        # 只有 0 个 gate，所有核心步骤之间没有验证步骤
        # execute → review 应有直连边（无 Gate 验证在 execute 后）
        # 但实际上 core_steps 只有 4 个，gate_validations 只有 0 个
        # 所以 execute(索引2) 和 review(索引3) 都走 else 分支：直连

        # review 是最后一个核心步骤，直连到 output_guardrails
        review_direct = [e for e in result["edges"]
                         if e.get("from") == "review"
                         and "condition" not in e]
        assert len(review_direct) >= 1

    def test_empty_profile_defaults(self):
        """空 Profile dict 使用默认值"""
        result = self.bridge.translate_profile_to_workflow({})
        assert result["name"] == "harness_governance_default"
        assert result["metadata"]["profile_name"] == "default"


# ─── execute_with_governance 测试 ────────────────────────────────────────


class TestExecuteWithGovernance:
    """治理注入与执行测试"""

    def setup_method(self):
        self.bridge = DeerFlowBridge()

    # 9. 不注入治理
    def test_no_governance_injection(self):
        """inject_governance=False 时返回原始 workflow，不注入检查点"""
        workflow = {
            "steps": [
                {"name": "step1", "type": "action", "description": "做点什么"},
                {"name": "step2", "type": "action", "description": "再做点什么"},
            ],
            "edges": [
                {"from": "step1", "to": "step2"},
            ],
        }
        config = {"gate_mode": "hybrid", "inject_governance": False}
        result = self.bridge.execute_with_governance(workflow, config)

        assert result["governance_injected"] is False
        assert result["workflow"] == workflow  # 原始 workflow 不变
        assert result["total_steps"] == 2

    # 10. 注入治理检查点
    def test_governance_injection_adds_checkpoints(self):
        """inject_governance=True 时在每个 action 步骤后注入治理验证"""
        workflow = {
            "steps": [
                {"name": "analyze", "type": "action", "description": "分析任务"},
                {"name": "execute", "type": "action", "description": "执行任务"},
                {"name": "input_guardrails", "type": "validation", "checks": []},
            ],
            "edges": [
                {"from": "__start__", "to": "input_guardrails"},
                {"from": "input_guardrails", "to": "analyze"},
                {"from": "analyze", "to": "execute"},
            ],
        }
        config = {"gate_mode": "strict", "inject_governance": True}
        result = self.bridge.execute_with_governance(workflow, config)

        assert result["governance_injected"] is True
        assert result["original_steps_count"] == 3
        assert result["enhanced_steps_count"] == 5  # 3 原始 + 2 治理（2 个 action）
        assert result["governance_checkpoints_added"] == 2
        assert result["gate_mode"] == "strict"

    def test_governance_step_structure(self):
        """注入的治理检查点结构正确"""
        workflow = {
            "steps": [
                {"name": "analyze", "type": "action", "description": "分析任务"},
            ],
            "edges": [],
        }
        config = {"gate_mode": "hybrid", "inject_governance": True}
        result = self.bridge.execute_with_governance(workflow, config)

        enhanced_steps = result["workflow"]["steps"]
        governance_step = enhanced_steps[1]  # 在 analyze 之后

        assert governance_step["name"] == "governance_after_analyze"
        assert governance_step["type"] == "validation"
        assert governance_step["checks"][0]["id"] == "governance_analyze"
        assert governance_step["checks"][0]["category"] == "governance"
        assert governance_step["mode"] == "hybrid"
        assert governance_step["interrupt_on_failure"] is True  # hybrid 门禁

    def test_governance_step_interrupt_strict(self):
        """strict 门禁下治理检查点 interrupt_on_failure=False"""
        workflow = {
            "steps": [{"name": "s", "type": "action", "description": "步骤"}],
            "edges": [],
        }
        config = {"gate_mode": "strict", "inject_governance": True}
        result = self.bridge.execute_with_governance(workflow, config)

        gov_step = result["workflow"]["steps"][1]
        assert gov_step["interrupt_on_failure"] is False

    # 11. enhanced 边的条件路由
    def test_enhanced_edge_action_to_governance(self):
        """action → governance 直连边正确生成"""
        workflow = {
            "steps": [
                {"name": "analyze", "type": "action", "description": "分析"},
            ],
            "edges": [
                {"from": "analyze", "to": "next_step"},
            ],
        }
        config = {"gate_mode": "hybrid", "inject_governance": True}
        result = self.bridge.execute_with_governance(workflow, config)

        enhanced_edges = result["workflow"]["edges"]

        # action → governance 的直连边
        direct_edge = [e for e in enhanced_edges
                       if e.get("from") == "analyze"
                       and e.get("to") == "governance_after_analyze"]
        assert len(direct_edge) == 1

    def test_enhanced_edge_governance_to_next_with_condition(self):
        """governance → 下一步 的条件边正确生成"""
        workflow = {
            "steps": [
                {"name": "analyze", "type": "action", "description": "分析"},
            ],
            "edges": [
                {"from": "analyze", "to": "next_step"},
            ],
        }
        config = {"gate_mode": "hybrid", "inject_governance": True}
        result = self.bridge.execute_with_governance(workflow, config)

        enhanced_edges = result["workflow"]["edges"]

        # governance 通过 → 下一步（条件路由）
        condition_edge = [e for e in enhanced_edges
                          if e.get("from") == "governance_after_analyze"
                          and e.get("to") == "next_step"
                          and e.get("condition") == "governance_passed"]
        assert len(condition_edge) == 1

    def test_non_action_edges_preserved(self):
        """非 action 步骤的原始边被保留"""
        workflow = {
            "steps": [
                {"name": "guardrails", "type": "validation", "checks": []},
                {"name": "analyze", "type": "action", "description": "分析"},
            ],
            "edges": [
                {"from": "__start__", "to": "guardrails"},  # 非 action 边
                {"from": "guardrails", "to": "analyze"},  # 非 action 边
                {"from": "analyze", "to": "output"},  # action 边 → 被替换
            ],
        }
        config = {"gate_mode": "hybrid", "inject_governance": True}
        result = self.bridge.execute_with_governance(workflow, config)

        enhanced_edges = result["workflow"]["edges"]

        # 非 action 边保留
        start_edge = [e for e in enhanced_edges if e.get("from") == "__start__"]
        assert len(start_edge) == 1
        assert start_edge[0]["to"] == "guardrails"

        guardrails_edge = [e for e in enhanced_edges if e.get("from") == "guardrails"]
        assert len(guardrails_edge) == 1
        assert guardrails_edge[0]["to"] == "analyze"

    def test_default_config_when_none(self):
        """config 为 None 时使用默认配置（hybrid, inject=True）"""
        workflow = {
            "steps": [{"name": "s", "type": "action", "description": "步骤"}],
            "edges": [],
        }
        result = self.bridge.execute_with_governance(workflow, None)

        assert result["governance_injected"] is True
        assert result["gate_mode"] == "hybrid"

    def test_no_action_steps_no_governance_added(self):
        """workflow 中无 action 步骤时不添加治理检查点"""
        workflow = {
            "steps": [
                {"name": "input_guardrails", "type": "validation", "checks": []},
                {"name": "output_guardrails", "type": "validation", "checks": []},
            ],
            "edges": [
                {"from": "input_guardrails", "to": "output_guardrails"},
            ],
        }
        config = {"gate_mode": "hybrid", "inject_governance": True}
        result = self.bridge.execute_with_governance(workflow, config)

        assert result["governance_injected"] is True
        assert result["governance_checkpoints_added"] == 0
        assert result["enhanced_steps_count"] == result["original_steps_count"]


# ─── 集成测试 — @pytest.mark.deerflow ───────────────────────────────────


@pytest.mark.deerflow
class TestDeerFlowIntegration:
    """DeerFlow 全流程集成测试

    从 Profile 定义 → workflow 生成 → 治理注入的完整链路验证。
    标记为 @pytest.mark.deerflow，可单独筛选运行：
        pytest -m deerflow
    """

    def setup_method(self):
        self.bridge = DeerFlowBridge()

    def test_full_pipeline_dict(self):
        """完整 pipeline：Profile dict → workflow → 治理注入"""
        profile = {
            "name": "secure_pipeline",
            "gates": [
                {
                    "id": "security",
                    "gate_type": "strict",
                    "checks": [
                        {"id": "no-secrets", "category": "security", "severity": "critical", "description": "禁止密钥"},
                    ],
                    "auto_fix": True,
                },
                {
                    "id": "quality",
                    "gate_type": "hybrid",
                    "checks": [
                        {"id": "code-style", "category": "quality", "severity": "medium", "description": "代码风格"},
                    ],
                    "auto_fix": False,
                },
            ],
            "rules": [],
        }

        # 第一步：Profile → workflow
        workflow = self.bridge.translate_profile_to_workflow(profile)
        assert workflow["name"] == "harness_governance_secure_pipeline"

        # 第二步：workflow → 注入治理
        result = self.bridge.execute_with_governance(workflow, {"gate_mode": "hybrid", "inject_governance": True})
        assert result["governance_injected"] is True
        assert result["enhanced_steps_count"] > result["original_steps_count"]

    def test_full_pipeline_object(self):
        """完整 pipeline：Profile 对象 → workflow → 治理注入"""
        gates = [
            MockGate(id="privacy", gate_type="loose", checks=[MockCheck(id="pii-check", category="privacy", severity="high")]),
        ]
        profile = MockProfile(name="privacy_pipeline", gates=gates)

        workflow = self.bridge.translate_profile_to_workflow(profile)
        assert workflow["name"] == "harness_governance_privacy_pipeline"

        result = self.bridge.execute_with_governance(workflow, {"gate_mode": "loose", "inject_governance": True})
        assert result["gate_mode"] == "loose"
        assert result["governance_injected"] is True

    def test_gate_modes_propagate_through_pipeline(self):
        """不同 Gate mode 在 pipeline 中正确传播"""
        # strict 门禁：interrupt_on_failure=False, mode=strict
        strict_gate = {"id": "strict_g", "gate_type": "strict", "checks": [{"id": "c"}]}
        # hybrid 门禁：interrupt_on_failure=True, mode=hybrid
        hybrid_gate = {"id": "hybrid_g", "gate_type": "hybrid", "checks": [{"id": "c"}]}

        for gate, expected_mode, expected_interrupt in [
            (strict_gate, "strict", False),
            (hybrid_gate, "hybrid", True),
        ]:
            validation = self.bridge.translate_gate_to_validation(gate)
            assert validation["mode"] == expected_mode
            assert validation["interrupt_on_failure"] == expected_interrupt

    def test_workflow_to_governance_edge_consistency(self):
        """workflow → 治理注入后边的关系一致性"""
        profile = {
            "name": "edge_test",
            "gates": [
                {"id": "g1", "gate_type": "hybrid", "checks": [{"id": "c1"}]},
            ],
        }
        workflow = self.bridge.translate_profile_to_workflow(profile)
        result = self.bridge.execute_with_governance(workflow, {"gate_mode": "hybrid", "inject_governance": True})

        enhanced = result["workflow"]
        # 每个 action 步骤必须有对应的 governance 边
        action_steps = [s for s in enhanced["steps"] if s.get("type") == "action"]
        for action_step in action_steps:
            gov_name = f"governance_after_{action_step['name']}"
            # action → governance 边存在
            action_to_gov = [e for e in enhanced["edges"] if e.get("from") == action_step["name"] and e.get("to") == gov_name]
            assert len(action_to_gov) >= 1, f"缺少 {action_step['name']} → {gov_name} 的边"

    def test_governance_injection_without_governance_then_with(self):
        """先不注入再注入，结果差异明显"""
        profile = {"name": "toggle_test", "gates": []}
        workflow = self.bridge.translate_profile_to_workflow(profile)

        no_inject = self.bridge.execute_with_governance(workflow, {"inject_governance": False})
        with_inject = self.bridge.execute_with_governance(workflow, {"gate_mode": "hybrid", "inject_governance": True})

        assert no_inject["governance_injected"] is False
        assert with_inject["governance_injected"] is True
        assert with_inject["enhanced_steps_count"] > no_inject["total_steps"]

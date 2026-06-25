"""
自主循环 & 跨文件合规扫描 Demo

演示 harness-cook @experimental 模块的两个核心引擎:
  - AutonomousLoopEngine: 自主循环引擎 — DAG 工作流迭代执行 + 收敛检测
  - CrossFileScanEngine: 跨文件合规扫描 — 影响传播 + 风险分级

运行方式:
  cd packages/core
  PYTHONPATH=. python3 ../../examples/autonomous-loop/demo_autonomous_loop.py

注意: 此 Demo 使用 @experimental 模块, API 可能变更。
"""

import sys
import os
import time

sys.path.insert(0, "../../packages/core")

from harness.types import (
    DAGWorkflow, DAGNode, DAGEdge, DAGEdge,
    TaskResult, TaskStatus, Artifact,
    ComplianceRule, ComplianceCategory, ComplianceResult,
)
from harness.engine import DAGEngine, ExecutionContext
from harness.experimental.autonomous_loop import (
    AutonomousLoopEngine,
    AutonomousLoopConfig,
    AutonomousLoopResult,
)
from harness.experimental.cross_file_scanner import (
    CrossFileScanEngine,
    CrossFileScanResult,
    CrossFileRiskGrade,
    FileCompliancePropagation,
)
from harness.impact_types import DependencyGraph
from harness.impact_analyzer import FileImpactAnalyzer


# ═══════════════════════════════════════════════════════════
#  辅助: 构造一个带产出物的简单 DAG workflow
# ═══════════════════════════════════════════════════════════

def make_simple_workflow(workflow_id: str = "loop-demo") -> DAGWorkflow:
    """构造一个单节点 DAG workflow, 用于演示循环迭代"""
    node = DAGNode(
        id="scanner",
        agent_type="analyst",
        task="扫描代码合规",
        inputs=[],
        outputs=[],
    )
    return DAGWorkflow(
        id=workflow_id,
        name="合规扫描循环",
        nodes=[node],
        edges=[],
        entry_node="scanner",
    )


def make_multi_node_workflow(workflow_id: str = "pipeline-demo") -> DAGWorkflow:
    """构造一个三节点 pipeline workflow"""
    return DAGWorkflow(
        id=workflow_id,
        name="分析-编码-验证 Pipeline",
        nodes=[
            DAGNode(id="analyze", agent_type="analyst", task="分析需求", inputs=[], outputs=["implement"]),
            DAGNode(id="implement", agent_type="coder", task="实现功能", inputs=["analyze"], outputs=["validate"]),
            DAGNode(id="validate", agent_type="validator", task="验证结果", inputs=["implement"], outputs=[]),
        ],
        edges=[
            DAGEdge(from_node="analyze", to_node="implement"),
            DAGEdge(from_node="implement", to_node="validate"),
        ],
        entry_node="analyze",
    )


class MockAgent:
    """模拟 Agent — 每次迭代产出不同数量的 artifact, 用于观察收敛行为"""

    def __init__(self, iteration_limit: int = 5):
        self._call_count = 0
        self._iteration_limit = iteration_limit

    def execute(self, task: str, context: dict) -> TaskResult:
        self._call_count += 1
        # 前 iteration_limit 次每次产出新 artifact, 之后不再产出新产出物 → 触发收敛
        if self._call_count <= self._iteration_limit:
            artifact = Artifact(
                type="code",
                path=f"output/scan_result_iter_{self._call_count}.py",
                content=f"# 第 {self._call_count} 次扫描结果\npass",
            )
        else:
            # 不产出新 artifact → 产出物集合不再增长
            artifact = Artifact(
                type="code",
                path=f"output/scan_result_iter_{self._iteration_limit}.py",  # 路径重复
                content=f"# 重复扫描 (iter {self._call_count})\npass",
            )

        return TaskResult(
            task_id=f"task-{self._call_count}",
            agent_id="mock-agent",
            status=TaskStatus.COMPLETED,
            artifacts=[artifact],
            tokens_used=100 + self._call_count * 10,
            duration_ms=50,
        )


def register_mock_agent(dag_engine: DAGEngine, agent_cls, **kwargs):
    """注册模拟 Agent 到 registry"""
    from harness.registry import AgentRegistry, AgentRecord
    from harness.types import AgentDefinition, AgentCapability

    agent_impl = agent_cls(**kwargs)
    definition = AgentDefinition(
        id=agent_impl.__class__.__name__.lower(),
        name=f"Mock {agent_impl.__class__.__name__}",
        capabilities=[AgentCapability.EXECUTE],
        toolsets=["mock"],
    )
    record = AgentRecord(definition=definition, implementation=agent_impl)
    dag_engine._registry._agents[definition.id] = record
    # 同时注册所有标准 agent_type 到同一个 mock
    for agent_type in ("analyst", "coder", "validator", "committer"):
        if agent_type not in dag_engine._registry._agents:
            type_def = AgentDefinition(
                id=agent_type,
                name=f"Mock {agent_type}",
                capabilities=[AgentCapability.EXECUTE],
                toolsets=["mock"],
            )
            type_record = AgentRecord(definition=type_def, implementation=agent_impl)
            dag_engine._registry._agents[agent_type] = type_record


# ═══════════════════════════════════════════════════════════
#  Demo 1: 自主循环引擎 — AutonomousLoopEngine 配置 + 迭代执行
# ═══════════════════════════════════════════════════════════

def demo_autonomous_loop_engine():
    """Demo 1: AutonomousLoopEngine 基本用法 — 配置 + 迭代执行"""
    print("\n" + "=" * 60)
    print("Demo 1: 自主循环引擎 — AutonomousLoopEngine 配置 + 迭代执行")
    print("=" * 60)

    # 1. 创建 DAGEngine 和 AutonomousLoopEngine
    dag_engine = DAGEngine()
    register_mock_agent(dag_engine, MockAgent, iteration_limit=3)
    loop_engine = AutonomousLoopEngine(dag_engine)

    # 2. 创建 DAG workflow
    workflow = make_simple_workflow()

    # 3. 配置自主循环
    config = AutonomousLoopConfig(
        max_iterations=10,            # 最大迭代 10 次
        convergence_window=2,         # 连续 2 次无新发现 → 收敛
        budget_token_limit=0,         # 不限 token 预算
        budget_time_limit_ms=0,       # 不限时间预算
    )

    print(f"  配置: max_iterations={config.max_iterations}, "
          f"convergence_window={config.convergence_window}")
    print(f"  Workflow: {workflow.id} ({len(workflow.nodes)} 个节点)")

    # 4. 运行自主循环
    result = loop_engine.run(workflow, config)

    print(f"\n  运行结果:")
    print(f"    迭代次数: {result.iterations}")
    print(f"    是否收敛: {result.converged}")
    print(f"    预算耗尽: {result.budget_exhausted}")
    print(f"    停止原因: {result.stop_reason}")
    print(f"    总 token: {result.total_tokens}")
    print(f"    总耗时:   {result.total_duration_ms} ms")
    print(f"    上下文数: {len(result.contexts)}")

    # 5. 检查各迭代的产出物
    print(f"\n  各迭代产出物路径:")
    for i, ctx in enumerate(result.contexts, 1):
        paths = []
        for node_id, artifacts in ctx.node_artifacts.items():
            for a in artifacts:
                paths.append(a.path)
        print(f"    iter {i}: {paths}")

    print(f"\n  解读: MockAgent 前3次产出新 artifact (路径不同), "
          f"之后路径重复 → 连续2次无新发现 → 收敛停止")


# ═══════════════════════════════════════════════════════════
#  Demo 2: 循环条件 — max_iterations / convergence / gate_pass
# ═══════════════════════════════════════════════════════════

def demo_loop_conditions():
    """Demo 2: 不同停止条件的对比"""
    print("\n" + "=" * 60)
    print("Demo 2: 循环条件 — max_iterations / convergence / budget")
    print("=" * 60)

    # ── 条件 A: max_iterations 硬上限 ──
    print("\n  [条件 A] max_iterations 硬上限 (不收敛 → 跑满)")
    dag_engine_a = DAGEngine()
    register_mock_agent(dag_engine_a, MockAgent, iteration_limit=999)  # 永远产出新 artifact
    loop_engine_a = AutonomousLoopEngine(dag_engine_a)
    workflow_a = make_simple_workflow("cond-max-iter")
    config_a = AutonomousLoopConfig(max_iterations=5, convergence_window=3)
    result_a = loop_engine_a.run(workflow_a, config_a)
    print(f"    iterations={result_a.iterations}, converged={result_a.converged}, "
          f"stop_reason={result_a.stop_reason}")

    # ── 条件 B: convergence_window 收敛检测 ──
    print("\n  [条件 B] convergence_window 收敛 (产出物不增长 → 自动停止)")
    dag_engine_b = DAGEngine()
    register_mock_agent(dag_engine_b, MockAgent, iteration_limit=2)  # 2次后路径重复
    loop_engine_b = AutonomousLoopEngine(dag_engine_b)
    workflow_b = make_simple_workflow("cond-convergence")
    config_b = AutonomousLoopConfig(max_iterations=10, convergence_window=2)
    result_b = loop_engine_b.run(workflow_b, config_b)
    print(f"    iterations={result_b.iterations}, converged={result_b.converged}, "
          f"stop_reason={result_b.stop_reason}")
    print(f"    解读: 第3次迭代起产出物路径重复 → 连续2次无新发现 → 收敛")

    # ── 条件 C: budget_token_limit 预算控制 ──
    print("\n  [条件 C] budget_token_limit 预算控制 (token 超限 → 停止)")
    dag_engine_c = DAGEngine()
    register_mock_agent(dag_engine_c, MockAgent, iteration_limit=999)
    loop_engine_c = AutonomousLoopEngine(dag_engine_c)
    workflow_c = make_simple_workflow("cond-budget")
    config_c = AutonomousLoopConfig(
        max_iterations=20,
        convergence_window=10,  # 高收敛窗口, 让预算先触发
        budget_token_limit=500,  # 500 token 预算
    )
    result_c = loop_engine_c.run(workflow_c, config_c)
    print(f"    iterations={result_c.iterations}, converged={result_c.converged}, "
          f"budget_exhausted={result_c.budget_exhausted}, "
          f"stop_reason={result_c.stop_reason}")
    print(f"    total_tokens={result_c.total_tokens}")
    print(f"    解读: 每次迭代消耗 ~110+10N tokens, 累计达500后预算耗尽停止")

    # ── 条件 D: 自定义收敛检查 ──
    print("\n  [条件 D] 自定义收敛检查 (convergence_check callback)")
    custom_check = lambda contexts: len(contexts) >= 3  # 第3次迭代就判定收敛
    dag_engine_d = DAGEngine()
    register_mock_agent(dag_engine_d, MockAgent, iteration_limit=999)
    loop_engine_d = AutonomousLoopEngine(dag_engine_d)
    workflow_d = make_simple_workflow("cond-custom")
    config_d = AutonomousLoopConfig(
        max_iterations=10,
        convergence_window=5,
        convergence_check=custom_check,
    )
    result_d = loop_engine_d.run(workflow_d, config_d)
    print(f"    iterations={result_d.iterations}, converged={result_d.converged}, "
          f"stop_reason={result_d.stop_reason}")
    print(f"    解读: 自定义检查在第3次迭代返回 True → 收敛停止")

    # ── 条件 E: 升级 (escalated) 中断 — 通过 gate 检查触发 ──
    print("\n  [条件 E] 升级中断 (Gate 检查升级 → 循环立即停止)")
    dag_engine_e = DAGEngine()
    # 用一个永远产出新 artifact 的 agent, 但 gate 会在迭代时触发升级
    register_mock_agent(dag_engine_e, MockAgent, iteration_limit=999)
    loop_engine_e = AutonomousLoopEngine(dag_engine_e)

    # 构造一个带升级门禁的 workflow
    from harness.types import GateDefinition, GateCheck, GateMode, CheckResult
    escalating_gate = GateDefinition(
        id="escalation-gate",
        checks=[
            GateCheck(
                id="always-escalate",
                category="security",
                severity="critical",
                description="模拟升级",
                check_fn=lambda artifact: CheckResult(
                    passed=False, severity="critical",
                    message="模拟升级: 门禁检查失败",
                    auto_fixable=False,
                ),
            ),
        ],
        mode=GateMode.STRICT,
    )
    node_with_gate = DAGNode(
        id="scanner",
        agent_type="analyst",
        task="扫描代码",
        inputs=[], outputs=[],
        gate=escalating_gate,
    )
    workflow_e = DAGWorkflow(
        id="cond-escalate",
        name="升级中断演示",
        nodes=[node_with_gate],
        edges=[],
        entry_node="scanner",
    )
    config_e = AutonomousLoopConfig(max_iterations=10, convergence_window=3)
    result_e = loop_engine_e.run(workflow_e, config_e)
    print(f"    iterations={result_e.iterations}, converged={result_e.converged}, "
          f"stop_reason={result_e.stop_reason}")
    print(f"    解读: 第1次迭代 Gate 检查失败升级 → ctx.escalated=True → 循环立即中断")

    print(f"\n  总结: 5 种停止条件优先级 — "
          f"budget > escalated > convergence_check > convergence_window > max_iterations")


# ═══════════════════════════════════════════════════════════
#  Demo 3: 跨文件合规扫描 — CrossFileScanEngine 影响传播
# ═══════════════════════════════════════════════════════════

def demo_cross_file_scan():
    """Demo 3: 跨文件合规扫描 — 变更文件 → 影响传播 → 合规扫描"""
    print("\n" + "=" * 60)
    print("Demo 3: 跨文件合规扫描 — CrossFileScanEngine 影响传播")
    print("=" * 60)

    # 1. 手工构建依赖图 (避免扫描真实项目文件系统)
    analyzer = FileImpactAnalyzer(project_root="/tmp/demo-project")
    graph = DependencyGraph()

    # 模拟一个典型的分层项目: controller → service → dao
    graph.add_node("controller/user_controller.py")
    graph.add_node("service/user_service.py")
    graph.add_node("dao/user_dao.py")
    graph.add_node("model/user_model.py")
    graph.add_node("utils/validator.py")
    graph.add_node("config/db_config.py")

    # 依赖关系: controller → service → dao → model
    graph.add_edge("controller/user_controller.py", "service/user_service.py")
    graph.add_edge("controller/user_controller.py", "utils/validator.py")
    graph.add_edge("service/user_service.py", "dao/user_dao.py")
    graph.add_edge("dao/user_dao.py", "model/user_model.py")
    graph.add_edge("dao/user_dao.py", "config/db_config.py")

    # 注入到 analyzer
    analyzer._graph = graph
    analyzer._built = True

    print(f"  依赖图节点数: {graph.stats()['total_nodes']}")
    print(f"  依赖图边数:   {graph.stats()['total_edges']}")

    # 2. 构造合规规则
    rules = [
        ComplianceRule(
            id="SEC-001",
            category=ComplianceCategory.SECURITY,
            pattern=r"(?:password|secret|api_key)\s*=",
            severity="critical",
            description="禁止硬编码密钥",
            remediation="使用环境变量或配置中心",
            matcher_type="regex",
        ),
        ComplianceRule(
            id="SEC-002",
            category=ComplianceCategory.SECURITY,
            pattern=r"eval\s*\(",
            severity="high",
            description="禁止 eval 调用",
            remediation="使用安全的替代方案",
            matcher_type="regex",
        ),
        ComplianceRule(
            id="ARCH-001",
            category=ComplianceCategory.ARCHITECTURE,
            pattern=r"import\s+dao",
            severity="medium",
            description="Controller 不应直接依赖 DAO",
            remediation="通过 Service 层间接访问",
            matcher_type="regex",
        ),
    ]

    # 3. 构造 artifact (模拟文件内容, 含违规)
    artifacts = [
        Artifact(
            type="code",
            path="dao/user_dao.py",
            content="# DAO layer\nimport model\npassword = 'hardcoded_secret'\n",
        ),
        Artifact(
            type="code",
            path="service/user_service.py",
            content="# Service layer\nimport dao\nresult = eval(data)\n",
        ),
        Artifact(
            type="code",
            path="controller/user_controller.py",
            content="# Controller\nimport service\nimport validator\n",
        ),
        Artifact(
            type="code",
            path="model/user_model.py",
            content="# Model\npass\n",
        ),
    ]

    # 4. 创建 CrossFileScanEngine 并执行扫描
    scan_engine = CrossFileScanEngine(analyzer)
    change_files = ["dao/user_dao.py"]

    print(f"\n  变更文件: {change_files}")
    print(f"  执行跨文件合规扫描...")

    result = scan_engine.scan(change_files, artifacts, rules)

    print(f"\n  扫描结果:")
    print(f"    影响分析概要: {result.impact_analysis.summary()}")
    print(f"    受影响文件:   {result.affected_files}")
    print(f"    变更文件:     {result.change_files}")
    print(f"    总违规数:     {result.total_violations}")
    print(f"    风险评级:     {result.risk_grade.value}")
    print(f"    概要文本:     {result.summary}")

    # 5. 逐文件传播详情
    print(f"\n  逐文件传播详情:")
    for fp in result.file_propagations:
        print(f"    [{fp.file_path}]")
        print(f"      is_change_file: {fp.is_change_file}")
        print(f"      impact_level:   {fp.impact_level}")
        print(f"      violation_count: {fp.violation_count}")
        print(f"      highest_severity: {fp.highest_severity}")
        for cr in fp.compliance_results:
            status = "PASS" if cr.passed else "FAIL"
            print(f"        {cr.rule_id}: {status} (severity={cr.severity})")

    print(f"\n  解读:")
    print(f"    dao/user_dao.py 是变更文件 → 全规则扫描 → 发现 SEC-001(硬编码密钥)")
    print(f"    service/user_service.py 是直接影响 → security+architecture 规则 → 发现 SEC-002(eval)")
    print(f"    controller/user_controller.py 是间接影响 → 仅 critical 规则 → 0 违规")


# ═══════════════════════════════════════════════════════════
#  Demo 4: 风险分级 — CrossFileRiskGrade LOW/MEDIUM/HIGH/CRITICAL
# ═══════════════════════════════════════════════════════════

def demo_risk_grades():
    """Demo 4: 风险分级 — 4 种场景演示不同 CrossFileRiskGrade"""
    print("\n" + "=" * 60)
    print("Demo 4: 风险分级 — CrossFileRiskGrade 5 级评定")
    print("=" * 60)

    # 展示所有风险级别
    print("\n  CrossFileRiskGrade 枚举值:")
    for grade in CrossFileRiskGrade:
        print(f"    {grade.name} = '{grade.value}'")

    # ── 场景 1: CLEAN — 无违规 ──
    print("\n  [场景 1] CLEAN — 变更1文件, 0 违规")
    graph1 = DependencyGraph()
    graph1.add_node("utils/helper.py")
    graph1.add_node("app/main.py")
    graph1.add_edge("app/main.py", "utils/helper.py")
    analyzer1 = FileImpactAnalyzer(project_root="/tmp/demo-clean")
    analyzer1._graph = graph1
    analyzer1._built = True

    rules = [ComplianceRule(
        id="SEC-001", category=ComplianceCategory.SECURITY,
        pattern=r"password\s*=", severity="critical",
        description="硬编码密钥", remediation="用环境变量", matcher_type="regex",
    )]
    artifacts1 = [Artifact(type="code", path="utils/helper.py", content="# clean\npass\n")]

    engine1 = CrossFileScanEngine(analyzer1)
    result1 = engine1.scan(["utils/helper.py"], artifacts1, rules)
    print(f"    risk_grade={result1.risk_grade.value}, "
          f"total_violations={result1.total_violations}, summary='{result1.summary}'")

    # ── 场景 2: LOW — 影响范围小, 违规级别 low ──
    print("\n  [场景 2] LOW — low 影响风险 + low 级别违规")
    graph2 = DependencyGraph()
    graph2.add_node("utils/format.py")
    graph2.add_node("app/tool.py")
    graph2.add_edge("app/tool.py", "utils/format.py")
    analyzer2 = FileImpactAnalyzer(project_root="/tmp/demo-low")
    analyzer2._graph = graph2
    analyzer2._built = True

    rules_low = [ComplianceRule(
        id="STYLE-001", category=ComplianceCategory.STYLE,
        pattern=r"console\.log", severity="low",
        description="生产代码禁止 console.log", remediation="移除或替换", matcher_type="regex",
    )]
    artifacts2 = [Artifact(type="code", path="utils/format.py", content="# utils\nconsole.log('debug')\n")]
    engine2 = CrossFileScanEngine(analyzer2)
    result2 = engine2.scan(["utils/format.py"], artifacts2, rules_low)
    print(f"    risk_grade={result2.risk_grade.value}, "
          f"total_violations={result2.total_violations}, summary='{result2.summary}'")

    # ── 场景 3: HIGH — medium 影响风险 + critical 违规 ──
    print("\n  [场景 3] HIGH — medium 影响风险 + critical 违规")
    graph3 = DependencyGraph()
    graph3.add_node("service/auth_service.py")
    for i in range(3):
        graph3.add_node(f"handler/handler_{i}.py")
        graph3.add_edge(f"handler/handler_{i}.py", "service/auth_service.py")
    analyzer3 = FileImpactAnalyzer(project_root="/tmp/demo-high")
    analyzer3._graph = graph3
    analyzer3._built = True

    rules_high = [ComplianceRule(
        id="SEC-001", category=ComplianceCategory.SECURITY,
        pattern=r"password\s*=", severity="critical",
        description="硬编码密钥", remediation="用环境变量", matcher_type="regex",
    )]
    artifacts3 = [
        Artifact(type="code", path="service/auth_service.py",
                 content="# auth\npassword = 'admin123'\n"),
    ]
    engine3 = CrossFileScanEngine(analyzer3)
    result3 = engine3.scan(["service/auth_service.py"], artifacts3, rules_high)
    print(f"    risk_grade={result3.risk_grade.value}, "
          f"total_violations={result3.total_violations}, summary='{result3.summary}'")

    # ── 场景 4: CRITICAL — high 影响风险 + critical/high 违规 ──
    print("\n  [场景 4] CRITICAL — high 影响风险 + critical 违规")
    graph4 = DependencyGraph()
    graph4.add_node("core/engine.py", is_entry_point=True)  # 入口文件
    for i in range(7):
        graph4.add_node(f"module/module_{i}.py")
        graph4.add_edge(f"module/module_{i}.py", "core/engine.py")
    analyzer4 = FileImpactAnalyzer(project_root="/tmp/demo-critical")
    analyzer4._graph = graph4
    analyzer4._built = True

    rules_critical = [ComplianceRule(
        id="SEC-001", category=ComplianceCategory.SECURITY,
        pattern=r"password\s*=", severity="critical",
        description="硬编码密钥", remediation="用环境变量", matcher_type="regex",
    )]
    artifacts4 = [
        Artifact(type="code", path="core/engine.py",
                 content="# core engine\npassword = 'super_secret'\n"),
    ]
    engine4 = CrossFileScanEngine(analyzer4)
    result4 = engine4.scan(["core/engine.py"], artifacts4, rules_critical)
    print(f"    risk_grade={result4.risk_grade.value}, "
          f"total_violations={result4.total_violations}, summary='{result4.summary}'")

    print(f"\n  风险分级算法 (_compute_risk_grade):")
    print(f"    total_violations=0 → CLEAN")
    print(f"    影响风险=high  + 违规severity∈(critical,high) → CRITICAL")
    print(f"    影响风险=high  + 其他违规 → HIGH")
    print(f"    影响风险=medium + 违规severity=critical → HIGH")
    print(f"    影响风险=medium + 其他违规 → MEDIUM")
    print(f"    影响风险=low   + 违规severity∈(critical,high) → MEDIUM")
    print(f"    影响风险=low   + 其他违规 → LOW")


# ═══════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("Harness Autonomous Loop & Cross-File Scan Demo")
    print("(@experimental — API 可能变更)")
    print("=" * 60)

    demo_autonomous_loop_engine()
    demo_loop_conditions()
    demo_cross_file_scan()
    demo_risk_grades()

    print("\n" + "=" * 60)
    print("所有 Demo 完成")
    print("=" * 60)

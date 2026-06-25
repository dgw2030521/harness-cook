"""
Pipeline 编排 Demo 示例

演示 harness-cook 的六步流水线编排——Analyst→Coder→Validator→Committer，
以及 MCP 工具触发的编码 Pipeline（含门禁强制执行）。

运行方式:
  cd packages/core
  PYTHONPATH=. python3 ../../examples/pipeline/demo_pipeline.py

输出:
  - 六步流水线定义——PIPELINE_STEPS 角色分配
  - Pipeline 配置——门禁模式、步骤跳过、重试策略
  - DAG 工作流构建——流水线转 DAG + 条件分支
  - MCP Pipeline 工具——analyst→coder→validator→committer 编码流水线
"""

import sys
sys.path.insert(0, "../../packages/core")

from harness.experimental import (
    MultiAgentOrchestrator, PipelineConfig, OrchestrationResult, PIPELINE_STEPS,
)
from harness.engine import DAGEngine
from harness.gates import GateMode


def demo_pipeline_steps():
    """Demo 1: 六步流水线定义"""
    print("\n" + "=" * 60)
    print("Demo 1: 六步流水线定义——角色分配")
    print("=" * 60)

    print("  PIPELINE_STEPS:")
    for agent_type, step_name, description in PIPELINE_STEPS:
        print(f"    {agent_type.value:12s} → {step_name:10s} → {description}")


def demo_pipeline_config():
    """Demo 2: Pipeline 配置"""
    print("\n" + "=" * 60)
    print("Demo 2: Pipeline 配置——门禁模式 + 步骤跳过 + 重试")
    print("=" * 60)

    # 默认配置
    default_config = PipelineConfig()
    print(f"  默认配置:")
    print(f"    跳过步骤: {default_config.skip_steps}")
    print(f"    最大重试: {default_config.max_retries}")
    print(f"    门禁模式: {default_config.gate_mode}")

    # 自定义配置——跳过 planner 和 reviewer
    custom_config = PipelineConfig(
        skip_steps=["plan", "review"],
        max_retries=3,
        gate_mode=GateMode.STRICT,
        task_description="修复安全漏洞",
    )
    print(f"  自定义配置:")
    print(f"    跳过步骤: {custom_config.skip_steps}")
    print(f"    最大重试: {custom_config.max_retries}")
    print(f"    门禁模式: {custom_config.gate_mode}")


def demo_dag_workflow():
    """Demo 3: DAG 工作流构建——流水线转 DAG"""
    print("\n" + "=" * 60)
    print("Demo 3: DAG 工作流——流水线转 DAG + 条件分支")
    print("=" * 60)

    engine = DAGEngine()
    orchestrator = MultiAgentOrchestrator(engine)

    # 构建工作流（不执行）
    config = PipelineConfig(
        task_description="修复 XSS 漏洞",
        gate_mode=GateMode.HYBRID,
    )
    workflow = orchestrator.build_workflow(config)

    print(f"  工作流 ID: {workflow.id}")
    print(f"  工作流名称: {workflow.name}")
    print(f"  节点数: {len(workflow.nodes)}")
    print(f"  边数: {len(workflow.edges)}")
    print(f"  入口节点: {workflow.entry_node}")
    print(f"  出口节点: {workflow.exit_nodes}")

    print(f"\n  DAG 节点:")
    for node in workflow.nodes:
        gate_str = "有门禁" if node.gate else "无门禁"
        print(f"    {node.id}: agent={node.agent_type}, step={node.metadata.get('step_name', '?')}, {gate_str}")

    print(f"\n  DAG 边:")
    for edge in workflow.edges:
        cond_str = f" (条件: {edge.condition})" if edge.condition else ""
        print(f"    {edge.from_node} → {edge.to_node}{cond_str}")

    print(f"\n  条件分支: reviewer 失败 → 回到 coder 重试")


def demo_mcp_pipeline():
    """Demo 4: MCP Pipeline 工具——编码流水线"""
    print("\n" + "=" * 60)
    print("Demo 4: MCP Pipeline 工具——analyst→coder→validator→committer")
    print("=" * 60)

    print("  MCP 工具: harness_pipeline_run")
    print("  参数:")
    print("    task: '修复 XSS 漏洞'")
    print("    gate_mode: 'hybrid' (strict/hybrid/loose)")
    print("    agents: ['analyst', 'coder', 'validator', 'committer']")
    print("    max_retries: 2")
    print("    working_directory: '.'")
    print()
    print("  执行流程:")
    print("    1. analyst  → 分析需求、评估影响范围和风险")
    print("    2. coder    → 根据分析结果实现代码修改")
    print("    3. validator → 验证修改正确性，运行测试和合规检查")
    print("    4. committer → 提交已验证的变更")
    print()
    print("  门禁强制执行:")
    print("    hybrid: 首次失败自动修复，二次失败暂停")
    print("    strict: 任何门禁失败立即暂停")
    print("    loose:  门禁失败记录但继续执行")
    print()
    print("  MCP 工具调用方式（在 IDE/Claude Code 中）:")
    print("    harness_pipeline_run(task='修复XSS漏洞', gate_mode='hybrid')")


def demo_pipeline_result():
    """Demo 5: Pipeline 结果结构"""
    print("\n" + "=" * 60)
    print("Demo 5: Pipeline 结果——StepResult + OrchestrationResult")
    print("=" * 60)

    print("  StepResult 结构:")
    print("    agent:        执行的 Agent 类型")
    print("    status:        completed / failed / skipped")
    print("    output:        Agent 输出内容")
    print("    duration_ms:   执行耗时")
    print("    gate_passed:   门禁是否通过")
    print("    gate_reason:   门禁失败原因")
    print("    retries:       重试次数")
    print()
    print("  OrchestrationResult 结构:")
    print("    workflow_id:       工作流 ID")
    print("    pipeline_steps:    总步骤数")
    print("    completed_steps:   完成步骤数")
    print("    failed_steps:      失败步骤数")
    print("    skipped_steps:     跳过步骤列表")
    print("    success:           整体是否成功")
    print("    last_artifacts:    最后完成的 Agent 产出")


if __name__ == "__main__":
    print("=" * 60)
    print("Harness Pipeline Demo")
    print("=" * 60)
    demo_pipeline_steps()
    demo_pipeline_config()
    demo_dag_workflow()
    demo_mcp_pipeline()
    demo_pipeline_result()
    print("\n✅ 所有 Pipeline Demo 完成")

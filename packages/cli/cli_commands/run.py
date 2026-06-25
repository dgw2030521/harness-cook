"""
harness run 命令——执行编排流程

加载工作流定义，注册 Agent，通过 DAGEngine 执行编排。
支持 --dry-run（只验证不执行）和门禁模式配置。
"""

import json
import time
from pathlib import Path

from harness.types import (
    DAGNode, DAGEdge, DAGWorkflow, GateDefinition, GateMode,
    GateCheck, CheckResult, RetryStrategy, Artifact,
    AgentDefinition, AgentCapability,
    IExecutableAgent, TaskResult,
)
from harness.engine import DAGEngine, ExecutionContext
from harness.registry import AgentRegistry, get_registry, AgentRecord
from harness.gates import GateEngine
from cli_commands.plan import _load_workflow


# ─── 内置 Mock Agent（用于演示/测试）──────────────────────

class MockAgent(IExecutableAgent):
    """内置 Mock Agent——用于 dry-run 和演示执行"""

    def __init__(self, definition: AgentDefinition):
        self._definition = definition

    @property
    def id(self) -> str:
        return self._definition.id

    @property
    def name(self) -> str:
        return self._definition.name

    @property
    def capabilities(self):
        return self._definition.capabilities

    def can_execute(self, task: str) -> bool:
        return True

    def execute(self, task: str, context: dict) -> TaskResult:
        """Mock 执行——返回成功结果"""
        return TaskResult(
            task_id=context.get("task_id", f"mock-task-{self.id}"),
            agent_id=self.id,
            status="completed",
            artifacts=[
                Artifact(
                    type="code",
                    path=f"output-{self.id}.txt",
                    content=f"{self.name} 的产出: {task}",
                    metadata={"agent": self.id, "mock": True},
                )
            ],
            duration_ms=100,
            tokens_used=50,
        )

    def estimate_tokens(self, task: str) -> int:
        """预估 token 数——Mock 返回固定值"""
        return 100


def _auto_register_agents(workflow: DAGWorkflow, registry: AgentRegistry) -> None:
    """自动为工作流中的 agent_type 创建 MockAgent 并注册"""
    for node in workflow.nodes:
        agent_type = node.agent_type
        # 检查是否已注册
        try:
            existing = registry.get(agent_type)
            if existing and existing.is_ready:
                continue
        except Exception:
            pass

        # 从 JSON 加载时 agent_type 可能不是完整定义
        # 创建一个简单的 AgentDefinition
        agent_def = AgentDefinition(
            id=agent_type,
            name=agent_type,
            capabilities=[AgentCapability.EXECUTE],
            toolsets=["default"],
        )
        mock = MockAgent(agent_def)
        registry.register(agent_def, mock)


def _format_execution_result(ctx: ExecutionContext) -> str:
    """格式化执行结果输出"""
    lines = []
    lines.append("=" * 50)
    lines.append(f"工作流执行结果: {ctx.workflow_id}")
    lines.append(f"执行 ID: {ctx.execution_id}")
    lines.append(f"耗时: {ctx.duration_ms}ms")
    lines.append("=" * 50)
    lines.append("")

    # 每个节点的状态
    for nid, status in ctx.node_status.items():
        status_icon = {
            "completed": "✓",
            "failed": "✗",
            "skipped": "○",
            "running": "…",
            "pending": "·",
        }.get(status, "?")
        lines.append(f"  {status_icon} {nid}: {status}")

        # 产出物
        if nid in ctx.node_artifacts and ctx.node_artifacts[nid]:
            for art in ctx.node_artifacts[nid]:
                lines.append(f"    产出: {art.type} — {art.path}")

        # 门禁结果
        if nid in ctx.node_gate_results:
            gate = ctx.node_gate_results[nid]
            gate_icon = "✓" if gate.passed else "✗"
            lines.append(f"    门禁 {gate_icon}: {gate.passed_checks}/{gate.total_checks} 通过")
            if gate.escalated:
                lines.append(f"    升级: {gate.escalation_reason}")

    lines.append("")

    # 汇总
    total = len(ctx.node_status)
    completed = len(ctx.completed_nodes)
    failed = len(ctx.failed_nodes)
    lines.append(f"汇总: {completed}/{total} 完成, {failed} 失败")

    if ctx.escalated:
        lines.append(f"升级: {ctx.escalation_reason}")

    return "\n".join(lines)


def cmd_run(args):
    """执行 run 命令"""
    # 加载工作流
    workflow = _load_workflow(args.workflow)

    # 获取注册表
    registry = get_registry()

    # dry-run 模式
    if args.dry_run:
        print("DRY RUN — 验证工作流配置（不执行）")
        print("")

        # 验证 DAG 结构
        node_ids = {n.id for n in workflow.nodes}
        errors = []

        for edge in workflow.edges:
            if edge.from_node not in node_ids:
                errors.append(f"边 {edge.from_node}->{edge.to_node}: source 不存在")
            if edge.to_node not in node_ids:
                errors.append(f"边 {edge.from_node}->{edge.to_node}: target 不存在")

        # 检查循环依赖（拓扑排序）
        adj = {n.id: [] for n in workflow.nodes}
        in_degree = {n.id: 0 for n in workflow.nodes}
        for edge in workflow.edges:
            if edge.from_node in node_ids and edge.to_node in node_ids:
                adj[edge.from_node].append(edge.to_node)
                in_degree[edge.to_node] += 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        sorted_count = 0
        while queue:
            node = queue.pop(0)
            sorted_count += 1
            for next_node in adj[node]:
                in_degree[next_node] -= 1
                if in_degree[next_node] == 0:
                    queue.append(next_node)

        if sorted_count != len(workflow.nodes):
            errors.append("DAG 存在循环依赖")

        if errors:
            print("验证失败:")
            for err in errors:
                print(f"  ✗ {err}")
            return 1

        # 注册 Agent
        _auto_register_agents(workflow, registry)

        print("验证通过:")
        print(f"  ✓ DAG 结构合法 ({len(workflow.nodes)} 节点, {len(workflow.edges)} 边)")
        print(f"  ✓ {len(registry.list_active())} Agent 已注册")

        for node in workflow.nodes:
            gate_info = ""
            if node.gate:
                gate_info = f" [门禁: {node.gate.mode.value}]"
            print(f"  ✓ {node.task} ({node.agent_type}){gate_info}")

        print(f"  ✓ 门禁模式: {args.gate_mode}")
        print(f"  ✓ 最大重试: {args.max_retries}")
        return 0

    # ─── 实际执行 ──────────────────────────────────

    # 注册 Agent（Mock）
    _auto_register_agents(workflow, registry)

    # 覆盖门禁模式（如果命令行指定）
    gate_mode = GateMode(args.gate_mode)
    for node in workflow.nodes:
        if node.gate:
            node.gate.mode = gate_mode
            node.gate.max_retries = args.max_retries

    # 加载初始上下文
    initial_context = None
    if args.context:
        ctx_path = Path(args.context)
        initial_context = json.loads(ctx_path.read_text(encoding="utf-8"))

    # 执行
    engine = DAGEngine(registry=registry)
    ctx = engine.execute(workflow, initial_context=initial_context)

    # 输出结果
    print(_format_execution_result(ctx))

    # 返回码
    if ctx.escalated:
        return 3  # 有人工升级
    elif ctx.failed_nodes:
        return 1  # 有失败节点
    else:
        return 0
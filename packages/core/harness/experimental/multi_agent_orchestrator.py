"""
harness-cook 多 Agent 编排器 — @experimental

扩展 AgentType 角色定义为真正的编排器：
  1. 根据 AgentType 角色分配任务
  2. 支持 Analyst→Planner→Coder→Reviewer→Validator→Committer 六步流水线
  3. 与 DAGEngine 集成：将流水线转为 DAG workflow

注意：此模块为 @experimental，API 可能变更。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, List

from harness.types import (
    AgentType, DAGNode, DAGEdge, DAGWorkflow, GateMode, BusEventType, BusEvent,
)
from harness.engine import DAGEngine, ExecutionContext
from harness.registry import AgentRegistry, get_registry
from harness.bus import EventBus, get_bus
from harness.gates import default_coding_gate

logger = logging.getLogger("harness.experimental.orchestrator")

# 六步流水线定义
PIPELINE_STEPS = [
    (AgentType.ANALYST,    "analyze",    "分析需求和影响评估"),
    (AgentType.PLANNER,    "plan",       "任务分解和策略制定"),
    (AgentType.CODER,      "implement",  "代码生成和修复实现"),
    (AgentType.REVIEWER,   "review",     "代码审查和质量检查"),
    (AgentType.VALIDATOR,  "validate",   "测试验证和合规检查"),
    (AgentType.COMMITTER,  "commit",     "变更提交和发布操作"),
]

_STEP_TASKS = {
    "analyze":  "分析以下需求，评估影响范围和风险",
    "plan":     "基于分析结果，制定实现方案和任务分解",
    "implement": "根据方案实现代码修改",
    "review":   "审查代码修改的质量和安全性",
    "validate": "验证修改的正确性，运行测试和合规检查",
    "commit":   "提交已验证的变更",
}


@dataclass
class PipelineConfig:
    """流水线配置——控制步骤跳过和重试"""
    skip_steps: List[str] = field(default_factory=list)
    max_retries: int = 2
    gate_mode: GateMode = GateMode.HYBRID
    task_description: str = ""
    project_root: str = ""


@dataclass
class OrchestrationResult:
    """编排结果——流水线执行后的汇总"""
    workflow_id: str = ""
    pipeline_steps: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    skipped_steps: List[str] = field(default_factory=list)
    execution_context: Optional[ExecutionContext] = None
    success: bool = False

    @property
    def last_artifacts(self) -> list:
        if not self.execution_context: return []
        for node_id in reversed(list(self.execution_context.node_artifacts.keys())):
            if self.execution_context.node_status.get(node_id) == "completed":
                return self.execution_context.node_artifacts[node_id]
        return []


class MultiAgentOrchestrator:
    """多 Agent 编排器——根据 AgentType 角色分配任务，执行六步流水线

    用法:
        orchestrator = MultiAgentOrchestrator(dag_engine)
        result = orchestrator.execute("修复 XSS 漏洞", config)

    流水线转 DAG: 每步 → DAGNode，步骤依赖 → DAGEdge
    条件分支: reviewer 失败 → 回到 coder 重试
    """

    def __init__(self, dag_engine: DAGEngine,
                 registry: Optional[AgentRegistry] = None, bus: Optional[EventBus] = None):
        self._dag_engine = dag_engine
        self._registry = registry or get_registry()
        self._bus = bus or get_bus()
        self._counter = 0

    def execute(self, task: str, config: PipelineConfig = PipelineConfig()) -> OrchestrationResult:
        config.task_description = task
        workflow = self._build_workflow(config)
        self._counter += 1
        result = OrchestrationResult(workflow_id=workflow.id,
            pipeline_steps=len(workflow.nodes), skipped_steps=config.skip_steps)

        self._bus.emit(BusEvent(type=BusEventType.WORKFLOW_START,
            execution_id=f"orch-{self._counter}", data={"task": task}))

        missing = [n.agent_type for n in workflow.nodes
                   if not self._registry.get(n.agent_type) or not self._registry.get(n.agent_type).is_ready]
        if missing: logger.warning(f"Agents not ready: {missing}")

        ctx = self._dag_engine.execute(workflow)
        result.execution_context = ctx
        for nid, st in ctx.node_status.items():
            if st == "completed": result.completed_steps += 1
            elif st == "failed":  result.failed_steps += 1
        result.success = not ctx.escalated and result.completed_steps == result.pipeline_steps

        self._bus.emit(BusEvent(
            type=BusEventType.WORKFLOW_COMPLETE if result.success else BusEventType.WORKFLOW_FAIL,
            execution_id=f"orch-{self._counter}",
            data={"success": result.success, "completed": result.completed_steps}))
        return result

    def build_workflow(self, config: PipelineConfig) -> DAGWorkflow:
        """公共 API：构建流水线 DAG（不执行）"""
        return self._build_workflow(config)

    def _build_workflow(self, config: PipelineConfig) -> DAGWorkflow:
        task = config.task_description
        active_steps = [(a, s, d) for a, s, d in PIPELINE_STEPS if s not in config.skip_steps]

        nodes = []
        for agent_type, step_name, _ in active_steps:
            step_task = f"{_STEP_TASKS.get(step_name, step_name)}：{task}"
            gate = default_coding_gate() if step_name in ("implement", "review", "validate") else None
            nodes.append(DAGNode(
                id=f"{step_name}-{agent_type.value}", agent_type=agent_type.value,
                task=step_task, inputs=[], outputs=[], gate=gate,
                metadata={"step_name": step_name}))

        # 依赖链 + 条件分支
        for i, node in enumerate(nodes):
            if i > 0: node.inputs.append(nodes[i-1].id); nodes[i-1].outputs.append(node.id)

        edges = [DAGEdge(from_node=nodes[i].id, to_node=nodes[i+1].id) for i in range(len(nodes)-1)]

        # reviewer 失败 → coder 重试
        reviewer = next((n for n in nodes if n.metadata.get("step_name") == "review"), None)
        coder = next((n for n in nodes if n.metadata.get("step_name") == "implement"), None)
        if reviewer and coder:
            edges.append(DAGEdge(from_node=reviewer.id, to_node=coder.id,
                condition=f"failure:{reviewer.id}"))

        return DAGWorkflow(id=f"pipeline-{self._counter+1}", name="six-step-pipeline",
            description=f"Pipeline for: {task}", nodes=nodes, edges=edges,
            entry_node=nodes[0].id if nodes else "",
            exit_nodes=[nodes[-1].id] if nodes else [])

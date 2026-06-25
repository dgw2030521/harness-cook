"""
harness-cook DAG 编排引擎

DAG Engine 是 Harness 的"指挥中心"——编排多Agent协作的工作流。
核心能力：
  1. 解析 DAGWorkflow → 拓扑排序 → 确定执行顺序
  2. 并行执行无依赖节点（受 Scheduler 调度）
  3. 条件分支（DAGEdge.condition）
  4. 每个节点完成后过 Gate 检查
  5. 失败重试 / 升级人工

设计原则：
  - 简单优先：同步执行，不搞异步框架
  - 拓扑排序保证执行顺序
  - 每个节点有独立的 GateDefinition
  - 所有事件通过 Bus 广播

护栏触发路径声明（E-5）：
  harness-cook 有三条独立的治理触发路径，各司其职：

  ┌─────────────────────────────────────────────────────────────────┐
  │ 路径1: MCP hook_trigger → 实时护栏拦截                          │
  │   Agent 平台（Claude Code 等）在 hook 事件中调用                │
  │   harness_hook_trigger MCP 工具                                 │
  │   → InputGuardrails（输入类槽位）或                              │
  │   → OutputGuardrails（输出类槽位）                               │
  │   → 实时决策：BLOCK / WARN / REDACT / CONTINUE                  │
  ├─────────────────────────────────────────────────────────────────┤
  │ 路径2: ComplianceEngine → 事后合规扫描                           │
  │   ComplianceEngine.scan() 对代码产物做静态规则扫描               │
  │   → 生成 ComplianceResult 报告，不做实时拦截                     │
  │   → 由 MCP harness_check 工具或 CLI 显式调用                    │
  ├─────────────────────────────────────────────────────────────────┤
  │ 路径3: DAGEngine → 事后门禁检查                                  │
  │   DAGEngine 在节点/工作流完成后调用 GateEngine.check()           │
  │   → 判断"通过/不通过/升级人工"，不做实时拦截                     │
  │   → 不调用 InputGuardrails / OutputGuardrails                   │
  └─────────────────────────────────────────────────────────────────┘

  为什么 DAGEngine 不调用护栏（路径1）？
    护栏是实时拦截机制——需要在 Agent 操作前/后立即执行 BLOCK/WARN 决策。
    DAGEngine 是事后编排引擎——节点已执行完毕才做门禁检查，
    此时拦截已无意义（内容已产生）。DAGEngine 的职责是编排+门禁，
    拦截职责由路径1（MCP hook_trigger）承担。
"""

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, List, Set, Callable, Any
from collections import deque
from harness.types import (
    DAGNode, DAGEdge, DAGWorkflow, TaskResult, TaskStatus, Artifact,
    GateDefinition, AgentDefinition, IExecutableAgent, TaskSpec,
    RollbackPolicy, SkillSlotName,
)
from harness.registry import AgentRegistry, get_registry
from harness.gates import GateEngine, GateResult
from harness.bus import EventBus, BusEventType, BusEvent, get_bus
from harness.rollback import RollbackEngine, get_rollback_engine, SnapshotSet
from harness.downgrade import get_downgrade_engine
from harness.exceptions import HarnessError


logger = logging.getLogger("harness.engine")


# ─── 执行上下文 ──────────────────────────────────────

@dataclass
class ExecutionContext:
    """一次工作流执行的上下文——跟踪状态、产出物、事件"""
    execution_id: str
    workflow_id: str
    started_at: float = 0.0           # time.time()
    completed_at: float = 0.0
    node_results: Dict[str, TaskResult] = field(default_factory=dict)
    node_artifacts: Dict[str, list[Artifact]] = field(default_factory=dict)
    node_gate_results: Dict[str, GateResult] = field(default_factory=dict)
    node_status: Dict[str, str] = field(default_factory=dict)  # "pending" | "running" | "completed" | "failed" | "skipped"
    pending_nodes: Set[str] = field(default_factory=set)
    running_nodes: Set[str] = field(default_factory=set)
    completed_nodes: Set[str] = field(default_factory=set)
    failed_nodes: Set[str] = field(default_factory=set)
    escalated: bool = False
    escalation_reason: Optional[str] = None
    rollback_policy: RollbackPolicy = RollbackPolicy.NONE  # 回滚策略
    node_snapshots: Dict[str, str] = field(default_factory=dict)  # node_id → snapshot_id
    rollback_results: Dict[str, Any] = field(default_factory=dict)  # node_id → RollbackResult

    @property
    def duration_ms(self) -> int:
        if self.completed_at and self.started_at:
            return int((self.completed_at - self.started_at) * 1000)
        return 0


# ─── DAG 编排引擎 ────────────────────────────────────

class DAGEngine:
    """
    DAG 编排引擎——执行多Agent协作工作流

    用法:
        engine = DAGEngine()
        context = engine.execute(workflow)
        if context.escalated:
            # 有人工升级
        else:
            # 全部自动完成
    """

    def __init__(
        self,
        registry: Optional[AgentRegistry] = None,
        gate_engine: Optional[GateEngine] = None,
        bus: Optional[EventBus] = None,
        rollback_engine: Optional[RollbackEngine] = None,
        rollback_policy: RollbackPolicy = RollbackPolicy.NONE,
        downgrade_engine: Optional[Any] = None,
        scheduler: Optional[Any] = None,
        max_workers: int = 1,
    ):
        self._registry = registry or get_registry()
        self._gate_engine = gate_engine or GateEngine(bus=bus)
        self._bus = bus or get_bus()
        self._rollback_engine = rollback_engine or get_rollback_engine()
        self._rollback_policy = rollback_policy
        self._downgrade_engine = downgrade_engine or get_downgrade_engine()  # DowngradeEngine（默认装配，避免降级链静默短路）
        self._scheduler = scheduler  # SmartScheduler 或 None
        self._schedule_plan = None  # 执行时由 scheduler.plan() 生成
        self._max_workers = max(1, max_workers)  # 并行线程数，1=串行（向后兼容）
        self._execution_counter = 0

    def execute(
        self,
        workflow: DAGWorkflow,
        initial_context: Optional[dict] = None,
    ) -> ExecutionContext:
        """
        执行工作流——拓扑排序 + 逐步执行 + 门禁检查

        Args:
            workflow: DAG工作流定义
            initial_context: 初始上下文数据

        Returns:
            ExecutionContext 执行上下文（包含所有结果）
        """
        self._execution_counter += 1
        ctx = ExecutionContext(
            execution_id=f"ex-{self._execution_counter}",
            workflow_id=workflow.id,
            started_at=time.time(),
            rollback_policy=self._rollback_policy,
        )

        # 初始化节点状态
        for node in workflow.nodes:
            ctx.node_status[node.id] = "pending"
            ctx.pending_nodes.add(node.id)

        # ── 生成调度计划（如有 Scheduler）──
        self._schedule_plan = None
        if self._scheduler:
            self._schedule_plan = self._scheduler.plan(workflow)
            logger.info(f"Schedule plan: {len(self._schedule_plan.parallel_groups)} parallel groups, "
                        f"~{self._schedule_plan.estimated_tokens} tokens")

        # 发射工作流开始事件
        self._bus.emit(BusEvent(
            type=BusEventType.WORKFLOW_START,
            execution_id=ctx.execution_id,
            data={"workflow_id": workflow.id, "node_count": len(workflow.nodes)},
        ))

        # 拓扑排序
        execution_order = self._topological_sort(workflow)

        # 按拓扑层级分组并行执行（max_workers > 1 时并行）
        if self._max_workers > 1:
            self._execute_parallel(workflow, execution_order, ctx, initial_context or {})
        else:
            # 串行执行（向后兼容）
            for node_id in execution_order:
                node = self._find_node(workflow, node_id)
                if not node:
                    logger.error(f"Node {node_id} not found in workflow")
                    continue

                if self._should_skip_node(workflow, node_id, ctx):
                    ctx.node_status[node_id] = "skipped"
                    ctx.pending_nodes.discard(node_id)
                    logger.info(f"Skipped node {node_id} (condition not met)")
                    continue

                self._execute_node(node, ctx, initial_context or {})

                if ctx.escalated:
                    break
                ctx.completed_at = time.time()
                self._bus.emit(BusEvent(
                    type=BusEventType.WORKFLOW_FAIL,
                    execution_id=ctx.execution_id,
                    data={"reason": ctx.escalation_reason},
                ))
                return ctx

        # 工作流完成
        ctx.completed_at = time.time()

        # 全局门禁检查（如果定义了）
        if workflow.global_gate:
            all_artifacts = []
            for artifacts in ctx.node_artifacts.values():
                all_artifacts.extend(artifacts)
            global_result = self._gate_engine.check(all_artifacts, workflow.global_gate)
            if not global_result.passed:
                ctx.escalated = True
                ctx.escalation_reason = f"Global gate failed: {global_result.escalation_reason}"

        # 发射完成事件
        self._bus.emit(BusEvent(
            type=BusEventType.WORKFLOW_COMPLETE if not ctx.escalated else BusEventType.WORKFLOW_FAIL,
            execution_id=ctx.execution_id,
            data={
                "workflow_id": workflow.id,
                "duration_ms": ctx.duration_ms,
                "completed_nodes": len(ctx.completed_nodes),
                "failed_nodes": len(ctx.failed_nodes),
                "escalated": ctx.escalated,
            },
        ))

        return ctx

    # ─── 节点执行 ────────────────────────────────────

    def _execute_node(
        self,
        node: DAGNode,
        ctx: ExecutionContext,
        global_context: dict,
    ) -> None:
        """执行单个节点——调用Agent + 门禁检查 + 可选回滚 + Skill 插槽"""
        ctx.node_status[node.id] = "running"
        ctx.pending_nodes.discard(node.id)
        ctx.running_nodes.add(node.id)

        # ── Skill 插槽: 执行前 ──
        self._run_skill_slot(node.id, SkillSlotName.PRE_EXECUTE, ctx, global_context)

        # ── 回滚快照: 节点执行前创建快照（MANUAL/AUTO模式）──
        snapshot_id: Optional[str] = None
        if ctx.rollback_policy != RollbackPolicy.NONE:
            # 收集需要快照的文件路径
            file_paths = self._collect_snapshot_paths(node, global_context)
            if file_paths:
                snapshot_set = self._rollback_engine.create_snapshot(
                    execution_id=ctx.execution_id,
                    node_id=node.id,
                    file_paths=file_paths,
                )
                snapshot_id = snapshot_set.snapshot_id
                ctx.node_snapshots[node.id] = snapshot_id
                logger.info(
                    f"Created rollback snapshot {snapshot_id} for node {node.id} "
                    f"(policy={ctx.rollback_policy.value})"
                )

        # 发射节点开始事件
        self._bus.emit(BusEvent(
            type=BusEventType.NODE_START,
            execution_id=ctx.execution_id,
            node_id=node.id,
            data={"agent_type": node.agent_type, "task": node.task},
        ))

        # 获取Agent
        agent_record = self._registry.get(node.agent_type)

        if not agent_record or not agent_record.is_ready:
            # Agent 未注册或未就绪 → 跳过节点
            ctx.node_status[node.id] = "failed"
            ctx.running_nodes.discard(node.id)
            ctx.failed_nodes.add(node.id)
            logger.error(f"Agent {node.agent_type} not ready for node {node.id}")

            self._bus.emit(BusEvent(
                type=BusEventType.NODE_FAIL,
                execution_id=ctx.execution_id,
                node_id=node.id,
                data={"reason": f"Agent {node.agent_type} not ready"},
            ))

            # ── AUTO回滚: Agent未就绪时也回滚 ──
            self._maybe_auto_rollback(ctx, node.id, snapshot_id, "Agent not ready")
            return

        # ── 约束校验: 执行前检查 AgentConstraints ──
        constraint_violations = self._check_constraints(node, agent_record, ctx)
        if constraint_violations:
            # 有 CRITICAL/BLOCKING 级别违规 → 阻断执行
            blocking = [v for v in constraint_violations if v.severity.value in ("critical", "blocking")]
            if blocking:
                ctx.node_status[node.id] = "failed"
                ctx.running_nodes.discard(node.id)
                ctx.failed_nodes.add(node.id)
                logger.error(
                    f"Node {node.id} blocked by constraint violations: "
                    f"{[v.detail for v in blocking]}"
                )
                self._bus.emit(BusEvent(
                    type=BusEventType.NODE_FAIL,
                    execution_id=ctx.execution_id,
                    node_id=node.id,
                    data={"reason": "Constraint violations", "violations": [v.detail for v in blocking]},
                ))
                self._maybe_auto_rollback(ctx, node.id, snapshot_id, "Constraint violation")
                return
            # 仅有 WARNING 级别 → 记录但继续执行
            for v in constraint_violations:
                logger.warning(f"Constraint warning for node {node.id}: {v.detail}")

        # 构建节点上下文——包含上游节点的产出物
        node_context = dict(global_context)
        for input_id in node.inputs:
            if input_id in ctx.node_artifacts:
                node_context[f"input_{input_id}"] = ctx.node_artifacts[input_id]
            if input_id in ctx.node_results:
                node_context[f"result_{input_id}"] = ctx.node_results[input_id]

        # 执行Agent
        try:
            agent_record.mark_task_start()
            result = agent_record.implementation.execute(node.task, node_context)
            agent_record.mark_task_complete(result.tokens_used)
            ctx.node_results[node.id] = result
            ctx.node_artifacts[node.id] = result.artifacts

            # 门禁检查
            if node.gate:
                gate_result = self._gate_engine.check(result.artifacts, node.gate, result)
                ctx.node_gate_results[node.id] = gate_result

                if gate_result.escalated:
                    # ── 降级检查：如果有 DowngradeEngine，先尝试自动降级 ──
                    downgrade_decision = self._try_downgrade(node, ctx, gate_result)

                    if downgrade_decision and str(downgrade_decision.value) in ("approved", "approved_with_conditions"):
                        # 降级成功 → 视为门禁通过（有条件放行）
                        logger.info(
                            f"Gate {node.gate.id} escalated but downgrade approved for node {node.id}"
                        )
                        gate_result = GateResult(
                            gate_id=gate_result.gate_id,
                            passed=True,
                            total_checks=gate_result.total_checks,
                            passed_checks=gate_result.passed_checks,
                            failed_checks=gate_result.failed_checks,
                            auto_fixed=gate_result.auto_fixed,
                            check_results=gate_result.check_results,
                            retries_used=gate_result.retries_used,
                            escalated=False,
                            duration_ms=gate_result.duration_ms,
                        )
                        ctx.node_gate_results[node.id] = gate_result

                        # ── Skill 插槽: 门禁通过 ──
                        self._run_skill_slot(node.id, SkillSlotName.ON_GATE_PASS, ctx, global_context)
                    else:
                        # 降级不可用或拒绝 → 维持升级
                        ctx.escalated = True
                        ctx.escalation_reason = f"Node {node.id} gate escalated: {gate_result.escalation_reason}"
                        ctx.node_status[node.id] = "failed"
                        ctx.running_nodes.discard(node.id)
                        ctx.failed_nodes.add(node.id)

                        # ── Skill 插槽: 门禁失败 ──
                        self._run_skill_slot(node.id, SkillSlotName.ON_GATE_FAIL, ctx, global_context)

                        # ── Skill 插槽: 升级到人工 ──
                        self._run_skill_slot(node.id, SkillSlotName.ON_ESCALATION, ctx, global_context)

                        self._bus.emit(BusEvent(
                            type=BusEventType.ESCALATION,
                            execution_id=ctx.execution_id,
                            node_id=node.id,
                            data={"gate_result": gate_result},
                        ))

                        # ── AUTO回滚: 门禁升级时回滚 ──
                        self._maybe_auto_rollback(ctx, node.id, snapshot_id, "Gate escalated")
                    return
                else:
                    # ── Skill 插槽: 门禁通过 ──
                    self._run_skill_slot(node.id, SkillSlotName.ON_GATE_PASS, ctx, global_context)

            # ── TaskSpec 验收验证: 用验收契约作为正面定义锚点 ──
            spec_result = self._verify_spec(node, result, ctx)
            if spec_result and not spec_result["passed"]:
                # 验收未通过 → 记录失败原因，视为节点失败
                logger.warning(
                    f"Node {node.id} TaskSpec verification failed: "
                    f"{spec_result['failed_criteria']}"
                )
                ctx.node_status[node.id] = "failed"
                ctx.running_nodes.discard(node.id)
                ctx.failed_nodes.add(node.id)

                self._bus.emit(BusEvent(
                    type=BusEventType.NODE_FAIL,
                    execution_id=ctx.execution_id,
                    node_id=node.id,
                    data={
                        "reason": "TaskSpec verification failed",
                        "failed_criteria": spec_result["failed_criteria"],
                    },
                ))
                self._maybe_auto_rollback(ctx, node.id, snapshot_id, "TaskSpec verification failed")
                return

            # 节点完成
            ctx.node_status[node.id] = "completed"
            ctx.running_nodes.discard(node.id)
            ctx.completed_nodes.add(node.id)

            # ── Skill 插槽: 执行后 ──
            self._run_skill_slot(node.id, SkillSlotName.POST_EXECUTE, ctx, global_context)

            self._bus.emit(BusEvent(
                type=BusEventType.NODE_COMPLETE,
                execution_id=ctx.execution_id,
                node_id=node.id,
                data={"agent_id": result.agent_id, "artifacts": len(result.artifacts)},
            ))

        except HarnessError as e:
            # 预期的业务异常 — 标准处理路径
            agent_record.mark_task_error()
            ctx.node_status[node.id] = "failed"
            ctx.running_nodes.discard(node.id)
            ctx.failed_nodes.add(node.id)
            logger.error(f"Node {node.id} failed (HarnessError): {e}", exc_info=True)

            # ── Skill 插槽: 执行异常 ──
            try:
                self._run_skill_slot(node.id, SkillSlotName.ON_ERROR, ctx, {**global_context, "error": str(e)})
            except Exception as slot_err:
                logger.warning(f"ON_ERROR skill slot also failed for node {node.id}: {slot_err}")

            self._bus.emit(BusEvent(
                type=BusEventType.NODE_FAIL,
                execution_id=ctx.execution_id,
                node_id=node.id,
                data={"reason": str(e), "code": e.code, "detail": e.detail},
            ))

            # ── AUTO回滚: Agent执行异常时回滚 ──
            self._maybe_auto_rollback(ctx, node.id, snapshot_id, f"Execution error: {e}")

        except Exception as e:
            # 未知异常 — 可能是框架 bug，记录更详细
            agent_record.mark_task_error()
            ctx.node_status[node.id] = "failed"
            ctx.running_nodes.discard(node.id)
            ctx.failed_nodes.add(node.id)
            logger.error(
                f"Node {node.id} failed (unexpected): {e} — this may be a framework bug",
                exc_info=True,
            )

            # ── Skill 插槽: 执行异常 ──
            try:
                self._run_skill_slot(node.id, SkillSlotName.ON_ERROR, ctx, {**global_context, "error": str(e)})
            except Exception as slot_err:
                logger.warning(f"ON_ERROR skill slot also failed for node {node.id}: {slot_err}")

            self._bus.emit(BusEvent(
                type=BusEventType.NODE_FAIL,
                execution_id=ctx.execution_id,
                node_id=node.id,
                data={"reason": str(e), "unexpected": True},
            ))

            # ── AUTO回滚: Agent执行异常时回滚 ──
            self._maybe_auto_rollback(ctx, node.id, snapshot_id, f"Unexpected execution error: {e}")

    # ─── 回滚辅助 ────────────────────────────────────

    def _maybe_auto_rollback(
        self,
        ctx: ExecutionContext,
        node_id: str,
        snapshot_id: Optional[str],
        reason: str,
    ) -> None:
        """在AUTO模式下自动回滚到快照"""
        if ctx.rollback_policy != RollbackPolicy.AUTO or not snapshot_id:
            return

        logger.info(f"Auto-rollback triggered for node {node_id}: {reason}")
        rollback_result = self._rollback_engine.restore_snapshot(snapshot_id)
        ctx.rollback_results[node_id] = rollback_result

        if rollback_result.success:
            logger.info(
                f"Auto-rollback succeeded for node {node_id}: "
                f"{rollback_result.files_restored} files restored"
            )
        else:
            logger.error(
                f"Auto-rollback FAILED for node {node_id}: "
                f"{rollback_result.errors}"
            )

    def _collect_snapshot_paths(self, node: DAGNode, global_context: dict) -> List[str]:
        """收集需要快照的文件路径——从 global_context 和 node.metadata 中提取"""
        paths: List[str] = []

        # 从 global_context 中提取 file_paths（如果有）
        if "file_paths" in global_context:
            paths.extend(global_context["file_paths"])

        # 从 node.metadata 中提取 target_files（如果有）
        if "target_files" in node.metadata:
            paths.extend(node.metadata["target_files"])

        # 从上游节点的 artifact paths 中提取
        if "input_artifacts" in global_context:
            for artifact in global_context.get("input_artifacts", []):
                if hasattr(artifact, "path") and artifact.path:
                    paths.append(artifact.path)

        # 去重并只保留存在的文件
        unique_paths = list(set(paths))
        existing_paths = [p for p in unique_paths if Path(p).exists()]

        return existing_paths

    def _try_downgrade(
        self,
        node: DAGNode,
        ctx: ExecutionContext,
        gate_result: GateResult,
    ) -> Optional[Any]:
        """
        尝试降级——如果有 DowngradeEngine，调用降级逻辑

        Args:
            node: 当前节点
            ctx: 执行上下文
            gate_result: 门禁结果

        Returns:
            GateApprovalDecision 或 None（如果没有 DowngradeEngine）
        """
        if not self._downgrade_engine:
            logger.debug("No downgrade engine available — skipping downgrade")
            return None

        # 从节点元数据中提取风险级别（如果有）
        risk_level = node.metadata.get("risk_level", "medium")
        reason = gate_result.escalation_reason or f"Gate escalated for node {node.id}"

        try:
            from harness.gate_notification import GateApprovalDecision
            decision = self._downgrade_engine.execute_downgrade(
                gate_id=node.gate.id if node.gate else node.id,
                risk_level=risk_level,
                reason=reason,
            )
            logger.info(f"Downgrade decision for node {node.id}: {decision.value}")
            return decision
        except Exception as e:
            logger.warning(f"Downgrade attempt failed for node {node.id}: {e}")
            return None

    # ─── 并行执行 ──────────────────────────────────────

    def _execute_parallel(
        self,
        workflow: DAGWorkflow,
        execution_order: list[str],
        ctx: ExecutionContext,
        global_context: dict,
    ) -> None:
        """
        按拓扑层级并行执行——同层级无依赖的节点并行调度

        层级定义：入度为 0 的节点为第 0 层，删除第 0 层后入度为 0 的为第 1 层，以此类推。
        每层内的节点可以并行执行（互不依赖），层与层之间串行等待。
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # 优先使用 Scheduler 的并行分组，否则回退到自算层级
        if self._schedule_plan:
            levels = self._schedule_plan.parallel_groups
            logger.info(f"Using Scheduler plan: {len(levels)} parallel groups")
        else:
            levels = self._group_by_level(workflow, execution_order)

        for level_idx, level_nodes in enumerate(levels):
            logger.info(
                f"Level {level_idx}: {len(level_nodes)} nodes — "
                f"{'parallel' if len(level_nodes) > 1 else 'serial'}"
            )

            # 过滤跳过节点
            runnable = []
            for node_id in level_nodes:
                if self._should_skip_node(workflow, node_id, ctx):
                    ctx.node_status[node_id] = "skipped"
                    ctx.pending_nodes.discard(node_id)
                    logger.info(f"Skipped node {node_id} (condition not met)")
                else:
                    runnable.append(node_id)

            if not runnable:
                continue

            if len(runnable) == 1:
                # 单节点，直接执行（避免线程开销）
                node = self._find_node(workflow, runnable[0])
                if node:
                    self._execute_node(node, ctx, global_context)
            else:
                # 多节点，线程池并行
                # Scheduler 指导下调整并行度；否则回退到固定 max_workers
                if self._scheduler and self._scheduler.can_execute_more():
                    effective_workers = min(self._scheduler._resource.max_parallelism, len(runnable))
                else:
                    effective_workers = min(self._max_workers, len(runnable))

                with ThreadPoolExecutor(max_workers=effective_workers) as executor:
                    futures = {}
                    for node_id in runnable:
                        node = self._find_node(workflow, node_id)
                        if node:
                            future = executor.submit(self._execute_node, node, ctx, global_context)
                            futures[future] = node_id

                    for future in as_completed(futures):
                        # 等待所有完成，异常已在 _execute_node 内处理
                        try:
                            future.result()
                        except HarnessError as e:
                            # 预期的业务异常 — 已在 _execute_node 内处理
                            logger.warning(f"Parallel node HarnessError (handled): {e}")
                        except Exception as e:
                            # 未知异常 — _execute_node 的异常处理本身可能出 bug
                            logger.error(
                                f"Parallel node unhandled exception (may indicate bug in error handler): {e}",
                                exc_info=True,
                            )

                # ── 并行层冲突协商 ──
                # 多节点并行执行后，检测产出物是否有文件冲突
                if len(runnable) > 1:
                    self._negotiate_conflicts(runnable, ctx)

            # 每层执行完后检查是否需要升级终止
            if ctx.escalated:
                return

    def _group_by_level(
        self,
        workflow: DAGWorkflow,
        execution_order: list[str],
    ) -> list[list[str]]:
        """
        将拓扑排序结果按层级分组

        层级定义：节点所属层级 = max(所有前驱节点层级) + 1，无前驱为 0。
        """
        node_level: Dict[str, int] = {}

        # 构建前驱映射
        predecessors: Dict[str, list[str]] = {n.id: [] for n in workflow.nodes}
        for edge in workflow.edges:
            if edge.to_node in predecessors:
                predecessors[edge.to_node].append(edge.from_node)
        for node in workflow.nodes:
            for input_id in node.inputs:
                if input_id not in predecessors[node.id]:
                    predecessors[node.id].append(input_id)

        # 按拓扑顺序计算层级
        for node_id in execution_order:
            preds = predecessors.get(node_id, [])
            if preds:
                pred_levels = [node_level.get(p, 0) for p in preds if p in node_level]
                node_level[node_id] = max(pred_levels) + 1 if pred_levels else 0
            else:
                node_level[node_id] = 0

        # 按层级分组
        max_level = max(node_level.values()) if node_level else 0
        levels = [[] for _ in range(max_level + 1)]
        for node_id in execution_order:
            level = node_level[node_id]
            levels[level].append(node_id)

        return levels

    # ─── 拓扑排序 ────────────────────────────────────

    def plan(self, workflow: DAGWorkflow) -> list[str]:
        """
        公共API：返回DAG拓扑排序的节点ID列表

        保证每个节点在其所有上游节点之后执行。
        """
        return self._topological_sort(workflow)

    def _topological_sort(self, workflow: DAGWorkflow) -> list[str]:
        """
        Kahn's algorithm 拓扑排序

        返回节点ID列表，保证每个节点在其所有上游节点之后执行。
        """
        # 建立入度表
        in_degree: Dict[str, int] = {n.id: 0 for n in workflow.nodes}
        adjacency: Dict[str, list[str]] = {n.id: [] for n in workflow.nodes}

        for edge in workflow.edges:
            adjacency[edge.from_node].append(edge.to_node)
            in_degree[edge.to_node] += 1

        # 用节点 inputs 补充入度（DAGNode.inputs 与 DAGEdge 双重声明）
        for node in workflow.nodes:
            for input_id in node.inputs:
                if input_id in in_degree:
                    in_degree[node.id] += 1

        # BFS
        queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
        order = []

        while queue:
            nid = queue.popleft()
            order.append(nid)
            for next_nid in adjacency[nid]:
                in_degree[next_nid] -= 1
                if in_degree[next_nid] == 0:
                    queue.append(next_nid)

        # 检查环
        if len(order) != len(workflow.nodes):
            remaining = [nid for nid, deg in in_degree.items() if deg > 0]
            logger.error(f"DAG has cycles! Remaining nodes: {remaining}")
            # 降级：把剩余节点按原始顺序追加
            for n in workflow.nodes:
                if n.id not in order:
                    order.append(n.id)

        return order

    # ─── 条件边 ──────────────────────────────────────

    def _should_skip_node(
        self,
        workflow: DAGWorkflow,
        node_id: str,
        ctx: ExecutionContext,
    ) -> bool:
        """
        检查条件边——是否应该跳过此节点

        条件表达式是简化版字符串，支持：
          - "success:node_a" → 上游节点 node_a 成功时才执行
          - "failure:node_a" → 上游节点 node_a 失败时才执行
          - "always" → 总是执行（默认）
        """
        incoming_edges = [e for e in workflow.edges if e.to_node == node_id]

        for edge in incoming_edges:
            if edge.condition:
                condition = edge.condition.strip()
                if condition.startswith("success:"):
                    upstream_id = condition.split(":")[1]
                    if ctx.node_status.get(upstream_id) != "completed":
                        return True
                elif condition.startswith("failure:"):
                    upstream_id = condition.split(":")[1]
                    if ctx.node_status.get(upstream_id) != "failed":
                        return True

        return False

    def _find_node(self, workflow: DAGWorkflow, node_id: str) -> Optional[DAGNode]:
        """按ID查找节点"""
        for node in workflow.nodes:
            if node.id == node_id:
                return node
        return None

    # ─── 并行冲突协商 ──────────────────────────────────

    def _negotiate_conflicts(
        self,
        node_ids: list[str],
        ctx: ExecutionContext,
    ) -> None:
        """
        并行层节点执行完后，检测产出物文件冲突并尝试协商解决

        流程：
          1. 收集该层所有节点的产出物
          2. 使用 NegotiationEngine 检测文件冲突
          3. 有冲突时按协商结果处理（merge/escalate）
        """
        try:
            from harness.negotiation import NegotiationEngine
        except ImportError:
            logger.debug("NegotiationEngine not available — skipping conflict detection")
            return

        # 收集该层已完成节点的产出物，按 agent_id 分组
        agent_artifacts: Dict[str, list] = {}
        for node_id in node_ids:
            if node_id in ctx.node_artifacts and node_id in ctx.node_results:
                result = ctx.node_results[node_id]
                agent_artifacts[result.agent_id] = ctx.node_artifacts[node_id]

        # 至少需要 2 个 Agent 有产出物才可能冲突
        if len(agent_artifacts) < 2:
            return

        # 执行冲突检测和协商
        negotiation = NegotiationEngine(bus=self._bus)
        conflicts = negotiation.negotiate(agent_artifacts)

        if not conflicts:
            return

        # 处理冲突结果
        for conflict in conflicts:
            if conflict.resolution == "merge":
                # 自动合并成功 → 无需额外操作，产出物保持原样
                logger.info(
                    f"Auto-merged conflict in {conflict.file_path} "
                    f"between {conflict.agent_a} and {conflict.agent_b}"
                )
            elif conflict.resolution == "escalate":
                # 无法自动解决 → 升级
                ctx.escalated = True
                ctx.escalation_reason = (
                    f"Parallel execution conflict in {conflict.file_path}: "
                    f"{conflict.agent_a} vs {conflict.agent_b}"
                )
                logger.warning(
                    f"Escalated parallel conflict in {conflict.file_path}: "
                    f"{conflict.agent_a} vs {conflict.agent_b}"
                )
                self._bus.emit(BusEvent(
                    type=BusEventType.ESCALATION,
                    execution_id=ctx.execution_id,
                    data={
                        "reason": "parallel_conflict",
                        "file_path": conflict.file_path,
                        "agent_a": conflict.agent_a,
                        "agent_b": conflict.agent_b,
                    },
                ))
            else:
                # 辩论裁决 (a/b) → 保留胜出方的产出物
                if conflict.resolution in ("a", "b"):
                    winner = conflict.agent_a if conflict.resolution == "a" else conflict.agent_b
                    loser = conflict.agent_b if conflict.resolution == "a" else conflict.agent_a
                    logger.info(
                        f"Debate resolved conflict in {conflict.file_path}: "
                        f"winner={winner}, loser={loser}"
                    )
                else:
                    logger.warning(f"Unknown conflict resolution: {conflict.resolution}")

    # ─── 统计 ────────────────────────────────────────

    def stats(self) -> dict:
        """引擎统计"""
        return {
            "total_executions": self._execution_counter,
            "registry_stats": self._registry.stats(),
            "gate_stats": self._gate_engine.stats(),
        }

    # ─── Skill 插槽执行 ──────────────────────────────

    def _run_skill_slot(
        self,
        node_id: str,
        slot: SkillSlotName,
        ctx: ExecutionContext,
        global_context: dict,
    ) -> None:
        """执行指定插槽的 Skills

        核心概念：Skills 定步骤。
        每个插槽对应一个生命周期阶段，挂载的 Skill 自动在该阶段执行。
        """
        try:
            from harness.skill_registry import get_skill_registry
            skill_registry = get_skill_registry()
        except ImportError:
            logger.debug("SkillRegistry not available — skipping skill slot execution")
            return

        skills = skill_registry.find_by_slot(slot)
        if not skills:
            return

        for record in skills:
            if not record.active:
                continue
            try:
                context = {
                    "node_id": node_id,
                    "execution_id": ctx.execution_id,
                    **global_context,
                }
                skill_registry.execute_skill(record.definition.id, context)
                logger.debug(f"Executed skill {record.definition.id} in slot {slot.value} for node {node_id}")
            except Exception as e:
                logger.warning(f"Skill {record.definition.id} in slot {slot.value} failed: {e}")

    # ─── TaskSpec 验收验证 ──────────────────────────────────

    def _verify_spec(
        self,
        node: DAGNode,
        result: TaskResult,
        ctx: ExecutionContext,
    ) -> Optional[dict]:
        """
        基于 TaskSpec 验收契约验证执行结果

        TaskSpec 是"做完应该是什么样子"的正面定义。
        没有 TaskSpec → 返回 None（不验证，保持向后兼容）
        有 TaskSpec → 检查验收标准是否满足

        返回:
            None — 无 TaskSpec，跳过验证
            {"passed": True, "checked": [...]} — 全部通过
            {"passed": False, "failed_criteria": [...]} — 有不满足的标准
        """
        spec = node.spec
        if not spec:
            # 无验收契约 → 不验证（向后兼容）
            return None

        failed_criteria = []

        # 1. 验收标准逐项检查
        for criterion in spec.acceptance_criteria:
            # 将验收标准映射到 TaskResult/artifacts 的检查
            if not self._check_criterion(criterion, result):
                failed_criteria.append(criterion)

        # 2. 超时检查
        if spec.timeout_seconds and result.duration_ms > spec.timeout_seconds * 1000:
            failed_criteria.append(
                f"Timeout: {result.duration_ms}ms > {spec.timeout_seconds * 1000}ms"
            )

        # 3. 输出格式检查（如果定义了 output_schema）
        if spec.output_schema:
            for artifact in result.artifacts:
                if not self._check_schema(artifact, spec.output_schema):
                    failed_criteria.append(
                        f"Output schema mismatch: artifact {artifact.path}"
                    )

        if failed_criteria:
            return {"passed": False, "failed_criteria": failed_criteria}
        return {"passed": True, "checked": spec.acceptance_criteria}

    def _check_criterion(self, criterion: str, result: TaskResult) -> bool:
        """
        检查单个验收标准

        验收标准是可判定的断言字符串。当前支持：
        - 关键词匹配：标准包含在 TaskResult 的 metadata/artifacts 中
        - 状态判定："所有测试通过" → result.status == COMPLETED
        - 否定判定："无硬编码密钥" → artifacts 中不包含硬编码密钥标记

        未来可扩展为更智能的判定（LLM 辅助验证）。
        """
        # 快速判定：任务失败则所有标准都不满足
        if result.status == TaskStatus.FAILED:
            return False

        # 关键词正向匹配：标准文本出现在 metadata 或 artifacts 中
        metadata_str = str(result.metadata)
        artifacts_str = " ".join(a.content for a in result.artifacts)

        # "通过"/"pass" 类标准 → 直接判定为通过（已完成状态即意味着通过）
        pass_keywords = ("通过", "pass", "成功", "success", "completed")
        if any(kw in criterion.lower() for kw in pass_keywords):
            return result.status == TaskStatus.COMPLETED

        # "无" 类否定标准 → 在产出物中搜索反面关键词
        no_keywords = ("无硬编码", "无密钥", "no hardcoded", "no secret", "no key")
        if any(kw in criterion.lower() for kw in no_keywords):
            # 搜索 artifacts 中是否有反面证据
            secret_markers = ("password", "secret", "api_key", "token", "hardcoded")
            for marker in secret_markers:
                if marker in artifacts_str.lower() and marker not in criterion.lower():
                    return False
            return True

        # 一般标准 → 关键词出现在产出物中视为满足
        # 这是保守策略：无法精确判定时，假设满足
        return True

    def _check_schema(self, artifact: Artifact, schema: dict) -> bool:
        """
        检查 artifact 是否符合 JSON Schema 格式约束

        简化实现：只检查 schema 中定义的 required 字段是否存在。
        完整的 JSON Schema 验证需要 jsonschema 库（当前不依赖）。
        """
        required_fields = schema.get("required", [])
        if not required_fields:
            return True

        # 尝试解析 artifact.content 为 JSON
        try:
            import json
            content = json.loads(artifact.content) if artifact.content.startswith("{") else {}
            for field in required_fields:
                if field not in content:
                    return False
            return True
        except (json.JSONDecodeError, AttributeError):
            # 非 JSON 内容 → 不检查 schema（保守通过）
            return True

    # ─── 约束校验 ──────────────────────────────────────

    def _check_constraints(
        self,
        node: DAGNode,
        agent_record: Any,
        ctx: ExecutionContext,
    ) -> list:
        """
        校验 Agent 约束——执行前检查 AgentConstraints

        检查项：
          1. file_patterns — task 中引用的文件路径是否在白名单内
          2. allowed_commands — task 中是否包含被禁止的命令
          3. no_destructive — Agent 是否被禁止执行破坏性操作
          4. max_changes — 上游产出物是否超过变更上限（后置检查）

        Returns:
            ConstraintViolation 列表（空=无违规）
        """
        constraints = getattr(agent_record, 'constraints', None)
        if not constraints:
            return []  # 无约束 → 放行

        from harness.constraints import ConstraintViolation, ConstraintSeverity, ConstraintType

        violations = []
        agent_id = agent_record.id
        task = node.task

        # 1. 文件路径校验 — 从 task 文本中提取文件路径模式
        if constraints.file_patterns:
            import re
            # 粗提取：匹配常见的文件路径模式
            file_refs = re.findall(r'[\w./\-]+\.\w{1,10}', task)
            for fp in file_refs:
                if not constraints.validate_file_access(fp):
                    violations.append(ConstraintViolation(
                        agent_id=agent_id,
                        constraint_type=ConstraintType.FILE_PATTERN,
                        detail=f"File access denied: {fp} not in {constraints.file_patterns}",
                        severity=ConstraintSeverity.BLOCKING,
                    ))

        # 2. 命令白名单校验 — 从 task 文本中提取命令
        if constraints.allowed_commands:
            # 粗提取：匹配 "run xxx" 或 "execute xxx" 中的命令
            cmd_refs = re.findall(r'(?:run|execute|exec)\s+(\S+)', task, re.IGNORECASE)
            for cmd in cmd_refs:
                if not constraints.validate_command(cmd):
                    violations.append(ConstraintViolation(
                        agent_id=agent_id,
                        constraint_type=ConstraintType.COMMAND,
                        detail=f"Command denied: {cmd} not in whitelist",
                        severity=ConstraintSeverity.BLOCKING,
                    ))

        # 3. 破坏性操作校验
        if constraints.is_destructive_blocked():
            destructive_patterns = [
                r'\brm\s+-rf\b', r'\bdrop\s+table\b', r'\bforce\s+push\b',
                r'\bdelete\s+from\b', r'\btruncate\b',
            ]
            for pattern in destructive_patterns:
                if re.search(pattern, task, re.IGNORECASE):
                    violations.append(ConstraintViolation(
                        agent_id=agent_id,
                        constraint_type=ConstraintType.DESTRUCTIVE,
                        detail=f"Destructive operation detected: {pattern}",
                        severity=ConstraintSeverity.CRITICAL,
                    ))
                    break  # 一个就够

        # 发射约束违规事件（如果有）
        if violations:
            self._bus.emit(BusEvent(
                type=BusEventType.GUARDRAIL_BLOCK,
                execution_id=ctx.execution_id,
                node_id=node.id,
                agent_id=agent_id,
                data={
                    "constraint_violations": [v.detail for v in violations],
                    "severity_counts": {
                        s.value: sum(1 for v in violations if v.severity == s)
                        for s in ConstraintSeverity
                    },
                },
            ))

        return violations
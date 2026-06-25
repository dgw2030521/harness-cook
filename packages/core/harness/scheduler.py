"""
harness-cook 智能调度器

Scheduler 决定"什么时候跑、并行多少、token预算够不够"。
核心能力：
  1. 分析 DAG 拓扑 → 确定并行分组
  2. 跟踪资源使用（token、RPM、并行度）
  3. 动态调整并行度（token预算紧张时降级串行）
  4. 小任务合并（多个微任务合并为一次LLM调用）
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Set
from harness.types import (
    DAGNode, DAGEdge, DAGWorkflow, SchedulePlan, ResourceUsage,
    SmartSchedulerConfig, AgentCapability,
)
from harness.registry import AgentRegistry, get_registry
from harness.bus import EventBus, BusEvent, BusEventType, get_bus


logger = logging.getLogger("harness.scheduler")


class SmartScheduler:
    """
    智能调度器——分析工作流拓扑，生成最优执行计划

    用法:
        scheduler = SmartScheduler()
        plan = scheduler.plan(workflow)
        # plan.parallel_groups → 并行执行的节点组
        # plan.critical_path → 关键路径
        # plan.estimated_tokens → token预估
    """

    def __init__(
        self,
        config: Optional[SmartSchedulerConfig] = None,
        registry: Optional[AgentRegistry] = None,
        bus: Optional[EventBus] = None,
    ):
        self.config = config or SmartSchedulerConfig()
        self._registry = registry or get_registry()
        self._bus = bus or get_bus()
        self._schedule_hints: Dict[str, float] = {}  # 推荐调整值：token_ratio, timeout_ratio
        # 订阅 Learning→Scheduler 闭环
        self._bus.subscribe(
            BusEventType.RECOMMENDATION,
            self._on_recommendation,
            name="scheduler:on_recommendation",
        )
        self._resource = ResourceUsage(
            tokens_budget=self.config.token_budget,
            rpm_limit=self.config.llm_rate_limit_per_minute,
            max_parallelism=self.config.max_parallelism,
        )

    def plan(self, workflow: DAGWorkflow) -> SchedulePlan:
        """
        生成调度计划

        1. 分析拓扑 → 找出可并行组
        2. 估算 token → 每个节点基于 Agent 定义
        3. 识别关键路径 → 最长串行链
        4. 标记检查点 → 门禁失败暂停节点
        """
        # 1. 分层分组——同一层的节点可并行
        parallel_groups = self._group_by_depth(workflow)

        # 2. Token预估
        estimated_tokens = self._estimate_tokens(workflow)
        estimated_duration = self._estimate_duration(workflow, parallel_groups)

        # 3. 关键路径
        critical_path = self._find_critical_path(workflow)

        # 4. 检查点
        checkpoints = [
            n.id for n in workflow.nodes
            if n.gate and self.config.checkpoint_on_gate_fail
        ]

        # 资源警告
        warnings = []
        if estimated_tokens > self.config.token_budget:
            warnings.append(f"Estimated tokens ({estimated_tokens}) exceeds budget ({self.config.token_budget})")
        if len(parallel_groups[0] if parallel_groups else []) > self.config.max_parallelism:
            warnings.append(f"First parallel group exceeds max_parallelism ({self.config.max_parallelism})")

        plan = SchedulePlan(
            parallel_groups=parallel_groups,
            sequential_groups=[[n.id] for n in workflow.nodes],  # 单节点串行（降级模式）
            critical_path=critical_path,
            checkpoints=checkpoints,
            estimated_duration_ms=estimated_duration,
            estimated_tokens=estimated_tokens,
            resource_warnings=warnings,
        )

        logger.info(f"Scheduled workflow {workflow.id}: "
                     f"{len(parallel_groups)} groups, "
                     f"~{estimated_tokens} tokens, "
                     f"~{estimated_duration}ms, "
                     f"warnings: {warnings}")

        return plan

    def update_resource(self, tokens_used: int, rpm_used: int, parallelism: int) -> ResourceUsage:
        """更新资源使用情况"""
        self._resource.tokens_used += tokens_used
        self._resource.rpm_used = rpm_used
        self._resource.current_parallelism = parallelism
        return self._resource

    def can_execute_more(self) -> bool:
        """是否还能执行更多任务——检查预算和并行度"""
        tokens_remaining = self._resource.tokens_budget - self._resource.tokens_used
        parallelism_ok = self._resource.current_parallelism < self._resource.max_parallelism
        return tokens_remaining > 0 and parallelism_ok

    def recommend_mode(self) -> str:
        """推荐执行模式——基于当前资源情况"""
        tokens_remaining = self._resource.tokens_budget - self._resource.tokens_used
        if tokens_remaining < self.config.token_budget * 0.1:
            return "conservative"  # token预算紧张 → 串行 + 小任务合并
        elif tokens_remaining < self.config.token_budget * 0.3:
            return "moderate"      # token预算一般 → 有限并行
        else:
            return "aggressive"    # token预算充足 → 最大并行

    # ─── RECOMMENDATION 事件处理 ────────────────────────────

    def _on_recommendation(self, event: BusEvent) -> None:
        """
        处理 Learning 模块的推荐事件，补全 Learning→Scheduler 闭环

        低置信度(<0.6)忽略，高置信度推荐调整调度参数。
        """
        data = event.data or {}
        rec_type = data.get("type", "")
        confidence = data.get("confidence", 0.0)
        suggested_action = data.get("suggested_action", "")
        description = data.get("description", "")

        # 只处理调度类推荐
        if rec_type != "schedule":
            return

        # 低置信度忽略
        if confidence < 0.6:
            logger.debug(f"Skipping low-confidence recommendation: {description} (conf={confidence:.2f})")
            return

        # 根据建议动作调整调度参数
        if suggested_action == "reduce_token_budget":
            # 降低 token 预估比例（如推荐缩减 30%，则 token_ratio=0.7）
            ratio = data.get("ratio", 0.7)
            self._schedule_hints["token_ratio"] = float(ratio)
            logger.info(f"Applied recommendation: reduce token budget ratio={ratio:.2f} (conf={confidence:.2f})")
        elif suggested_action == "increase_timeout":
            # 增加超时预估比例（如推荐增加 50%，则 timeout_ratio=1.5）
            ratio = data.get("ratio", 1.5)
            self._schedule_hints["timeout_ratio"] = float(ratio)
            logger.info(f"Applied recommendation: increase timeout ratio={ratio:.2f} (conf={confidence:.2f})")
        else:
            logger.debug(f"Unhandled schedule recommendation: {suggested_action}")

    # ─── 内部方法 ────────────────────────────────────

    def _group_by_depth(self, workflow: DAGWorkflow) -> list[list[str]]:
        """按深度分组——同一深度的节点可并行执行"""
        # 计算每个节点的深度（最长上游路径长度）
        depths: Dict[str, int] = {}
        node_map = {n.id: n for n in workflow.nodes}

        def get_depth(nid: str) -> int:
            if nid in depths:
                return depths[nid]
            node = node_map.get(nid)
            if not node or not node.inputs:
                depths[nid] = 0
                return 0
            max_upstream = max(get_depth(inp) for inp in node.inputs)
            depths[nid] = max_upstream + 1
            return depths[nid]

        for node in workflow.nodes:
            get_depth(node.id)

        # 按深度分组
        groups: Dict[int, list[str]] = {}
        for nid, depth in depths.items():
            if depth not in groups:
                groups[depth] = []
            groups[depth].append(nid)

        # 按深度排序返回
        return [groups[d] for d in sorted(groups.keys())]

    def _estimate_tokens(self, workflow: DAGWorkflow) -> int:
        """估算总token消耗——考虑推荐调整值"""
        total = 0
        for node in workflow.nodes:
            record = self._registry.get(node.agent_type)
            if record:
                # 简化估算：基于任务描述长度 × Agent 温度系数
                task_length = len(node.task)
                multiplier = 1.0 + record.definition.temperature
                estimated = int(task_length * 50 * multiplier)  # 每字符约50token
                total += estimated
            else:
                # 默认估算
                total += 5000  # 单任务默认5000token
        # 应用推荐调整：reduce_token_budget 会缩减预估上限
        token_ratio = self._schedule_hints.get("token_ratio", 1.0)
        adjusted_total = int(total * token_ratio)
        if token_ratio != 1.0:
            logger.debug(f"Token estimate adjusted: {total} → {adjusted_total} (ratio={token_ratio:.2f})")
        return adjusted_total

    def _estimate_duration(self, workflow: DAGWorkflow, groups: list[list[str]]) -> int:
        """估算总执行时间——考虑推荐调整值"""
        # 每组并行执行，组间串行
        # 每组内取最慢节点的时间
        total_ms = 0
        for group in groups:
            group_max_ms = 0
            for nid in group:
                # 单节点默认30秒
                group_max_ms = max(group_max_ms, 30000)
            total_ms += group_max_ms
        # 应用推荐调整：increase_timeout 会增加预估超时时间
        timeout_ratio = self._schedule_hints.get("timeout_ratio", 1.0)
        adjusted_ms = int(total_ms * timeout_ratio)
        if timeout_ratio != 1.0:
            logger.debug(f"Duration estimate adjusted: {total_ms}ms → {adjusted_ms}ms (ratio={timeout_ratio:.2f})")
        return adjusted_ms

    def _find_critical_path(self, workflow: DAGWorkflow) -> list[str]:
        """找出关键路径——最长串行链"""
        node_map = {n.id: n for n in workflow.nodes}
        if not workflow.nodes:
            return []

        # 从入口节点开始，找最长路径
        # 简化版：直接用拓扑排序（假设所有节点都在关键路径上）
        entry = workflow.entry_node or workflow.nodes[0].id
        path = [entry]
        current = entry

        # 沿着 outputs 遍历
        while True:
            node = node_map.get(current)
            if not node or not node.outputs:
                break
            # 取第一个输出（简化——完整版应选最长的）
            next_node = node.outputs[0]
            path.append(next_node)
            current = next_node

        return path

    def stats(self) -> dict:
        return {
            "config": {
                "max_parallelism": self.config.max_parallelism,
                "token_budget": self.config.token_budget,
                "rpm_limit": self.config.llm_rate_limit_per_minute,
            },
            "resource": {
                "tokens_used": self._resource.tokens_used,
                "tokens_remaining": self._resource.tokens_budget - self._resource.tokens_used,
                "current_parallelism": self._resource.current_parallelism,
            },
        }
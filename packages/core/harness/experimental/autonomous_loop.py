"""
harness-cook 自主循环引擎 — @experimental

让 DAGEngine 支持自主迭代执行（/loop 模式）：
  1. 每次迭代执行一次 DAG workflow
  2. 检查收敛条件（连续2次无新发现则停止）
  3. 预算控制（token 或时间超限则停止）

设计原则：
  - 持有 DAGEngine 引用，组合模式
  - 收敛检测基于"产出物增量"——连续N次无新发现 = 收敛
  - 预算控制双维度：token 累计 + wall-clock 时间

注意：此模块为 @experimental，API 可能变更。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Callable, List, Set

from harness.types import DAGWorkflow, BusEventType, BusEvent
from harness.engine import DAGEngine, ExecutionContext
from harness.bus import EventBus, get_bus

logger = logging.getLogger("harness.experimental.loop")


@dataclass
class AutonomousLoopConfig:
    """自主循环配置——控制迭代行为"""
    max_iterations: int = 10               # 最大迭代次数（硬上限）
    convergence_window: int = 2            # 连续N次无新发现则停止
    budget_token_limit: int = 0            # token 预算上限（0=不限制）
    budget_time_limit_ms: int = 0          # 时间预算上限（毫秒，0=不限制）
    convergence_check: Optional[Callable[[List[ExecutionContext]], bool]] = None


@dataclass
class AutonomousLoopResult:
    """自主循环结果——汇总所有迭代"""
    iterations: int = 0
    converged: bool = False
    budget_exhausted: bool = False
    contexts: List[ExecutionContext] = field(default_factory=list)
    total_tokens: int = 0
    total_duration_ms: int = 0
    stop_reason: str = ""  # "converged" | "budget_exhausted" | "max_iterations" | "escalated"

    @property
    def last_context(self) -> Optional[ExecutionContext]:
        return self.contexts[-1] if self.contexts else None


class AutonomousLoopEngine:
    """自主循环引擎——让 DAGEngine 支持自主迭代执行

    用法:
        dag_engine = DAGEngine()
        loop_engine = AutonomousLoopEngine(dag_engine)
        result = loop_engine.run(workflow, config)

    收敛检测: 每次迭代收集产出物路径集合，连续 convergence_window 次无增量 → 收敛
    预算控制: token 累计或 wall-clock 超限 → budget_exhausted
    """

    def __init__(self, dag_engine: DAGEngine, bus: Optional[EventBus] = None):
        self._dag_engine = dag_engine
        self._bus = bus or get_bus()

    def run(self, workflow: DAGWorkflow,
            config: AutonomousLoopConfig = AutonomousLoopConfig(),
            initial_context: Optional[dict] = None) -> AutonomousLoopResult:
        """迭代执行 DAG workflow 直到收敛或预算耗尽"""
        result = AutonomousLoopResult()
        start_time = time.time()
        prev_artifact_paths: Set[str] = set()
        convergence_counter = 0

        for iteration in range(1, config.max_iterations + 1):
            # 预算检查
            elapsed_ms = int((time.time() - start_time) * 1000)
            if config.budget_token_limit and result.total_tokens >= config.budget_token_limit:
                result.budget_exhausted, result.stop_reason = True, "budget_exhausted:token"
                logger.info(f"Loop stopped: token budget exhausted at iteration {iteration}")
                break
            if config.budget_time_limit_ms and elapsed_ms >= config.budget_time_limit_ms:
                result.budget_exhausted, result.stop_reason = True, "budget_exhausted:time"
                logger.info(f"Loop stopped: time budget exhausted at iteration {iteration}")
                break

            self._bus.emit(BusEvent(type=BusEventType.WORKFLOW_START,
                execution_id=f"loop-iter-{iteration}",
                data={"iteration": iteration, "workflow_id": workflow.id}))

            ctx = self._dag_engine.execute(workflow, initial_context)
            result.contexts.append(ctx)
            result.iterations = iteration
            result.total_duration_ms = elapsed_ms
            iter_tokens = sum(r.tokens_used for r in ctx.node_results.values())
            result.total_tokens += iter_tokens

            # 升级检查
            if ctx.escalated:
                result.stop_reason = "escalated"
                logger.warning(f"Loop stopped: escalated at iteration {iteration}")
                break

            # 收敛检测: 产出物增量
            current_paths: Set[str] = set()
            for artifacts in ctx.node_artifacts.values():
                for a in artifacts: current_paths.add(a.path)

            new_discoveries = current_paths - prev_artifact_paths
            prev_artifact_paths = current_paths
            convergence_counter = 0 if new_discoveries else convergence_counter + 1

            if config.convergence_check and config.convergence_check(result.contexts):
                result.converged, result.stop_reason = True, "converged:custom"
                logger.info(f"Loop converged at iteration {iteration}: custom check")
                break
            elif convergence_counter >= config.convergence_window:
                result.converged, result.stop_reason = True, "converged:no_new_discoveries"
                logger.info(f"Loop converged at iteration {iteration}: no new discoveries for {convergence_counter} iterations")
                break

            logger.info(f"Iteration {iteration}: {len(new_discoveries)} new artifacts, {iter_tokens} tokens")

        if not result.stop_reason:
            result.stop_reason = "max_iterations"
        return result

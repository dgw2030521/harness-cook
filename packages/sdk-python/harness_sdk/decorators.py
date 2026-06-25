"""
harness-sdk 装饰器——简化版 Agent 注册接口

核心装饰器:
  1. @harness_agent — 完整版，支持约束+门禁+工具集
  2. @simple_agent — 极简版，只需 name + capabilities，约束自动生成

设计来源:
  - harness.core.decorators.harness_agent 是底层实现（直接操作 Registry + Bus）
  - SDK 版重导出底层 @harness_agent + 新增 @simple_agent 简化版
  - @simple_agent 是 @harness_agent 的快捷入口，适合入门用户
"""

import logging
from typing import Optional, List, Callable, Union

from harness.decorators import harness_agent as _core_harness_agent, DecoratedAgent
from harness.constraints import AgentConstraints, AgentPriority
from harness.types import (
    AgentCapability, AgentDefinition, GateMode, AgentType, TaskResult,
)

logger = logging.getLogger("harness_sdk.decorators")


def harness_agent(
    name: str,
    capabilities: List[AgentCapability],
    constraints: Optional[AgentConstraints] = None,
    gate_mode: GateMode = GateMode.HYBRID,
    toolsets: Optional[List[str]] = None,
    max_rounds: int = 15,
    temperature: float = 0.2,
    system_prompt: str = "",
    priority: Optional[AgentPriority] = None,
    agent_type: Optional[AgentType] = None,
    auto_register: bool = True,
):
    """@harness_agent 装饰器——完整版 Agent 注册

    SDK 版重导出 core 版的 @harness_agent，参数和行为完全一致。
    直接使用即可，无需额外 import harness.decorators。

    用法:
        from harness_sdk import harness_agent, AgentConstraints, Capability

        @harness_agent(
            name="code-reviewer",
            capabilities=[Capability.PERCEIVE, Capability.REASON],
            constraints=AgentConstraints(
                file_patterns=["*.py"],
                max_changes=50,
                no_destructive=True,
            ),
            gate_mode=GateMode.HYBRID,
            toolsets=["terminal", "file"],
        )
        def review_code(task: str, context: dict) -> TaskResult:
            ...
    """
    return _core_harness_agent(
        name=name,
        capabilities=capabilities,
        constraints=constraints,
        gate_mode=gate_mode,
        toolsets=toolsets,
        max_rounds=max_rounds,
        temperature=temperature,
        system_prompt=system_prompt,
        priority=priority,
        agent_type=agent_type,
        auto_register=auto_register,
    )


def simple_agent(
    name: str,
    capabilities: Optional[List[Union[AgentCapability, str]]] = None,
    gate_mode: GateMode = GateMode.HYBRID,
    toolsets: Optional[List[str]] = None,
    max_changes: int = 20,
    no_destructive: bool = True,
    timeout: int = 300,
    auto_register: bool = True,
):
    """@simple_agent 装饰器——极简版 Agent 注册

    只需 name 即可注册，其余参数自动生成默认值:
    - capabilities 默认 [PERCEIVE, REASON]（大多数Agent的基础能力）
    - constraints 自动生成: max_changes=20, no_destructive=True, timeout=300s
    - toolsets 默认 ["terminal", "file"]

    适合入门用户快速接入 Harness，无需手动构造 AgentConstraints。

    用法:
        from harness_sdk import simple_agent, TaskResult

        @simple_agent(name="my-worker")
        def do_work(task: str, context: dict) -> TaskResult:
            ...

    Args:
        name: Agent 名称（人类可读）
        capabilities: Agent能力列表（可传str或AgentCapability，默认[PERCEIVE, REASON]）
        gate_mode: 质量门禁模式
        toolsets: 需要的工具集（默认["terminal", "file"]）
        max_changes: 最大变更文件数（默认20）
        no_destructive: 是否禁止破坏性操作（默认True）
        timeout: 单任务超时秒数（默认300）
        auto_register: 是否自动注册（默认True）
    """
    # capabilities 兼容 str 和 AgentCapability
    if capabilities is None:
        resolved_caps = [AgentCapability.PERCEIVE, AgentCapability.REASON]
    else:
        resolved_caps = []
        for cap in capabilities:
            if isinstance(cap, str):
                resolved_caps.append(AgentCapability(cap))
            else:
                resolved_caps.append(cap)

    if toolsets is None:
        toolsets = ["terminal", "file"]

    # 自动生成约束
    constraints = AgentConstraints(
        max_changes=max_changes,
        no_destructive=no_destructive,
        timeout=timeout,
    )

    return _core_harness_agent(
        name=name,
        capabilities=resolved_caps,
        constraints=constraints,
        gate_mode=gate_mode,
        toolsets=toolsets,
        auto_register=auto_register,
    )
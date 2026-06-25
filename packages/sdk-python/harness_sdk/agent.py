"""
harness-sdk Agent 接入接口——注册、发现、创建

Agent 接口封装 core.registry 的底层操作，提供:
  1. AgentClient — Agent 的客户端包装（查询+执行）
  2. create_agent — 快速创建 AgentDefinition
  3. register_agent — 注册到 Harness（手动注册，不需要装饰器）
  4. get_agent / list_agents — 查询已注册的 Agent

用法:
    from harness_sdk import create_agent, register_agent, TaskResult

    def my_handler(task: str, context: dict) -> TaskResult:
        ...

    definition = create_agent("my-worker", ["perceive", "reason"])
    register_agent(definition, my_handler)

    # 查询
    agent = get_agent("my-worker")
    result = agent.execute("do something", {"task_id": "t-1"})
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable, Union

from harness.types import (
    AgentCapability, AgentDefinition, AgentType,
    IExecutableAgent, TaskResult, GateMode,
)
from harness.constraints import AgentConstraints, AgentPriority
from harness.registry import AgentRegistry, get_registry
from harness.bus import EventBus, BusEventType, BusEvent, get_bus

logger = logging.getLogger("harness_sdk.agent")


# ─── Agent 信息 ────────────────────────────────────────

@dataclass
class AgentInfo:
    """Agent 注册信息——对外展示的摘要

    包含: id, name, capabilities, constraints, gate_mode, status
    """
    id: str
    name: str
    capabilities: List[str]
    gate_mode: str = "hybrid"
    constraints_summary: Dict[str, Any] = field(default_factory=dict)
    registered_at: Optional[str] = None
    status: str = "active"


# ─── Agent Client ────────────────────────────────────────

class AgentClient:
    """Agent 客户端——包装 IExecutableAgent 的执行+查询接口

    用法:
        client = AgentClient(definition, agent_impl)
        result = client.run("review this code", {"task_id": "t-001"})
        info = client.info()
    """

    def __init__(
        self,
        definition: AgentDefinition,
        agent: IExecutableAgent,
    ):
        self._definition = definition
        self._agent = agent

    def run(self, task: str, context: Optional[Dict[str, Any]] = None) -> TaskResult:
        """执行 Agent 任务——简化版 execute()

        自动填充 task_id（如未提供）
        """
        if context is None:
            context = {}
        if "task_id" not in context:
            context["task_id"] = str(uuid.uuid4())
        return self._agent.execute(task, context)

    def info(self) -> AgentInfo:
        """获取 Agent 信息摘要"""
        caps = [c.value for c in self._definition.capabilities]
        constraints_data = {}
        if hasattr(self._agent, "constraints"):
            constraints_data = self._agent.constraints.summary()

        gate_mode = "hybrid"
        if hasattr(self._agent, "gate_mode"):
            gate_mode = self._agent.gate_mode.value

        return AgentInfo(
            id=self._definition.id,
            name=self._definition.name,
            capabilities=caps,
            gate_mode=gate_mode,
            constraints_summary=constraints_data,
        )

    @property
    def definition(self) -> AgentDefinition:
        return self._definition


# ─── 便捷函数 ────────────────────────────────────────

def create_agent(
    name: str,
    capabilities: Optional[List[Union[AgentCapability, str]]] = None,
    agent_type: Optional[AgentType] = None,
    toolsets: Optional[List[str]] = None,
    max_rounds: int = 15,
    temperature: float = 0.2,
    system_prompt: str = "",
) -> AgentDefinition:
    """快速创建 AgentDefinition

    Args:
        name: Agent 名称
        capabilities: 能力列表（可传str或AgentCapability）
        agent_type: Agent 类型
        toolsets: 需要的工具集
        max_rounds: 最大轮次
        temperature: LLM温度
        system_prompt: 系统提示词

    Returns:
        AgentDefinition 对象
    """
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
        toolsets = []

    agent_id = name.replace(" ", "-").lower()

    return AgentDefinition(
        id=agent_id,
        name=name,
        capabilities=resolved_caps,
        toolsets=toolsets,
        agent_type=agent_type,
        max_rounds=max_rounds,
        temperature=temperature,
        system_prompt=system_prompt,
    )


def register_agent(
    definition: AgentDefinition,
    handler: Union[IExecutableAgent, Callable],
    constraints: Optional[AgentConstraints] = None,
    gate_mode: GateMode = GateMode.HYBRID,
) -> AgentClient:
    """注册 Agent 到 Harness——手动注册版（不需要装饰器）

    Args:
        definition: Agent 定义
        handler: 执行器（IExecutableAgent 或普通函数）
        constraints: 约束（可选）
        gate_mode: 门禁模式

    Returns:
        AgentClient 包装对象
    """
    registry = get_registry()

    # 普通函数包装为 IExecutableAgent
    if hasattr(handler, "execute") and callable(getattr(handler, "execute")):
        agent = handler
    else:
        # 包装普通函数
        from harness_sdk._wrapper import FunctionWrapper
        agent = FunctionWrapper(handler, definition)

    registry.register(definition, agent)
    logger.info(f"Agent '{definition.name}'({definition.id}) 注册到 Harness")

    # 发布注册事件
    bus = get_bus()
    bus.emit(BusEvent(
        type=BusEventType.AGENT_REGISTERED,
        execution_id=f"register-{definition.id}",
        agent_id=definition.id,
        data={
            "name": definition.name,
            "capabilities": [c.value for c in definition.capabilities],
            "gate_mode": gate_mode.value,
        }
    ))

    return AgentClient(definition, agent)


def get_agent(agent_id: str) -> Optional[AgentClient]:
    """获取已注册的 Agent

    Args:
        agent_id: Agent ID

    Returns:
        AgentClient 或 None
    """
    registry = get_registry()
    definition = registry.get_definition(agent_id)
    if definition is None:
        return None

    agent = registry.get_implementation(agent_id)
    if agent is None:
        return None

    return AgentClient(definition, agent)


def list_agents() -> List[AgentInfo]:
    """列出所有已注册的 Agent

    Returns:
        AgentInfo 列表
    """
    registry = get_registry()
    definitions = [r.definition for r in registry.list_all()]

    infos = []
    for defn in definitions:
        impl = registry.get_implementation(defn.id)
        if impl:
            caps = [c.value for c in defn.capabilities]

            constraints_data = {}
            if hasattr(impl, "constraints"):
                constraints_data = impl.constraints.summary()

            gate_mode = "hybrid"
            if hasattr(impl, "gate_mode"):
                gate_mode = impl.gate_mode.value

            infos.append(AgentInfo(
                id=defn.id,
                name=defn.name,
                capabilities=caps,
                gate_mode=gate_mode,
                constraints_summary=constraints_data,
            ))

    return infos
"""
harness-cook Agent 注册与发现

Agent Registry 是 Harness 的"花名册"——所有接入 Harness 的 Agent
必须先注册才能被调度引擎调用。

设计原则：
  - 注册是声明式的：AgentDefinition 声明能力，不声明实现
  - 实现通过 IExecutableAgent protocol 提供，可以后绑定
  - 支持动态注册/注销（运行时增减 Agent）
"""

import logging
from typing import Optional, Dict, TypeVar, Any
from harness.types import AgentDefinition, IExecutableAgent, AgentCapability
from harness.bus import EventBus, BusEventType, BusEvent, get_bus


logger = logging.getLogger("harness.registry")


# ─── Agent 记录 ──────────────────────────────────────

class AgentRecord:
    """Agent 注册记录——定义 + 实现 + 约束 + 状态"""

    def __init__(
        self,
        definition: AgentDefinition,
        implementation: Optional[IExecutableAgent] = None,
        constraints: Optional[Any] = None,
    ):
        self.definition = definition
        self.implementation = implementation
        self.constraints = constraints   # AgentConstraints 或 None
        self.active: bool = True          # 是否激活（可被调度）
        self.task_count: int = 0          # 已执行任务数
        self.last_used: Optional[float] = None   # 最后使用时间戳
        self.error_count: int = 0         # 错误次数
        self.total_tokens: int = 0        # 累计token消耗

    @property
    def id(self) -> str:
        return self.definition.id

    @property
    def is_ready(self) -> bool:
        """是否就绪——有实现 + 激活状态"""
        return self.active and self.implementation is not None

    def mark_task_start(self) -> None:
        """标记任务开始"""
        import time
        self.last_used = time.time()
        self.task_count += 1

    def mark_task_complete(self, tokens_used: int = 0) -> None:
        """标记任务完成"""
        self.total_tokens += tokens_used

    def mark_task_error(self) -> None:
        """标记任务错误"""
        self.error_count += 1


# ─── Agent 注册表 ────────────────────────────────────

class AgentRegistry:
    """
    Agent 注册表——管理所有已注册的 Agent

    用法:
        registry = AgentRegistry()
        registry.register(definition, implementation)
        agent = registry.get("coder-agent")
        candidates = registry.find_by_capability(AgentCapability.EXECUTE)
    """

    def __init__(self, bus: Optional[EventBus] = None):
        self._agents: Dict[str, AgentRecord] = {}
        self._bus = bus or get_bus()

    # ─── 注册 ────────────────────────────────────────

    def register(
        self,
        definition: AgentDefinition,
        implementation: Optional[IExecutableAgent] = None,
    ) -> AgentRecord:
        """
        注册 Agent

        Args:
            definition: Agent 定义（ID、能力、工具集等）
            implementation: Agent 实现对象（可选，可后绑定）
                — 如果实现有 .constraints 属性（如 DecoratedAgent），自动提取

        Returns:
            AgentRecord 注册记录
        """
        # 自动从 implementation 提取 constraints（如 DecoratedAgent）
        constraints = None
        if implementation and hasattr(implementation, 'constraints'):
            constraints = implementation.constraints

        if definition.id in self._agents:
            logger.warning(f"Agent {definition.id} already registered — updating")
            record = self._agents[definition.id]
            record.definition = definition
            if implementation:
                record.implementation = implementation
            if constraints:
                record.constraints = constraints
        else:
            record = AgentRecord(definition, implementation, constraints=constraints)
            self._agents[definition.id] = record

        constraints_info = f" with constraints: {constraints.summary()}" if constraints else ""
        logger.info(f"Registered agent {definition.id} ({definition.name}) "
                     f"with capabilities: {[c.value for c in definition.capabilities]}{constraints_info}")

        self._bus.emit(BusEvent(
            type=BusEventType.NODE_START,  # 复用事件类型表示注册
            execution_id="registry",
            data={"agent_id": definition.id, "agent_name": definition.name},
        ))

        return record

    def bind_implementation(self, agent_id: str, implementation: IExecutableAgent) -> bool:
        """
        后绑定实现——先注册定义，后提供实现

        适用场景：Agent 定义从配置加载，实现从代码注入
        """
        record = self._agents.get(agent_id)
        if not record:
            logger.error(f"Agent {agent_id} not registered — cannot bind implementation")
            return False

        record.implementation = implementation
        logger.info(f"Bound implementation to agent {agent_id}")
        return True

    # ─── 查询 ────────────────────────────────────────

    def get(self, agent_id: str) -> Optional[AgentRecord]:
        """按ID获取Agent记录"""
        return self._agents.get(agent_id)

    def get_definition(self, agent_id: str) -> Optional[AgentDefinition]:
        """按ID获取Agent定义"""
        record = self._agents.get(agent_id)
        return record.definition if record else None

    def get_implementation(self, agent_id: str) -> Optional[IExecutableAgent]:
        """按ID获取Agent实现"""
        record = self._agents.get(agent_id)
        return record.implementation if record else None

    def find_by_capability(self, capability: AgentCapability) -> list[AgentRecord]:
        """按能力查找——返回所有具备该能力的Agent"""
        return [
            r for r in self._agents.values()
            if capability in r.definition.capabilities and r.is_ready
        ]

    def find_by_toolset(self, toolset: str) -> list[AgentRecord]:
        """按工具集查找——返回所有需要该工具集的Agent"""
        return [
            r for r in self._agents.values()
            if toolset in r.definition.toolsets and r.is_ready
        ]

    def list_active(self) -> list[AgentRecord]:
        """列出所有激活的Agent"""
        return [r for r in self._agents.values() if r.active]

    def list_all(self) -> list[AgentRecord]:
        """列出所有已注册的Agent（包括未激活）"""
        return list(self._agents.values())

    # ─── 状态管理 ─────────────────────────────────────

    def activate(self, agent_id: str) -> bool:
        """激活Agent——允许被调度"""
        record = self._agents.get(agent_id)
        if not record:
            return False
        record.active = True
        logger.info(f"Activated agent {agent_id}")
        return True

    def deactivate(self, agent_id: str) -> bool:
        """停用Agent——不再被调度，但保留注册"""
        record = self._agents.get(agent_id)
        if not record:
            return False
        record.active = False
        logger.info(f"Deactivated agent {agent_id}")
        return True

    def unregister(self, agent_id: str) -> bool:
        """注销Agent——从注册表中移除"""
        if agent_id not in self._agents:
            return False

        record = self._agents.pop(agent_id)
        logger.info(f"Unregistered agent {agent_id} "
                     f"(tasks={record.task_count}, tokens={record.total_tokens})")
        return True

    # ─── 统计 ────────────────────────────────────────

    def stats(self) -> dict:
        """注册表统计"""
        records = list(self._agents.values())
        return {
            "total_agents": len(records),
            "active_agents": sum(1 for r in records if r.active),
            "ready_agents": sum(1 for r in records if r.is_ready),
            "total_tasks_executed": sum(r.task_count for r in records),
            "total_tokens_consumed": sum(r.total_tokens for r in records),
            "agents_by_capability": {
                cap.value: sum(
                    1 for r in records
                    if cap in r.definition.capabilities
                )
                for cap in AgentCapability
            },
        }


# ─── 全局单例 ────────────────────────────────────────

_global_registry: Optional[AgentRegistry] = None


def get_registry() -> AgentRegistry:
    """获取全局Agent注册表单例"""
    global _global_registry
    if _global_registry is None:
        _global_registry = AgentRegistry()
    return _global_registry


def reset_registry() -> None:
    """重置全局注册表（主要用于测试）"""
    global _global_registry
    _global_registry = AgentRegistry()
"""
harness_agent 装饰器——一键接入 Harness 管控

设计来源：nextX 的 defineAgent() + createExecutableAgent()
nextX 需要两步: defineAgent(定义) → createExecutableAgent(创建可执行实例)
harness-cook 简化为一步: @harness_agent(装饰器) → 自动注册+自动创建

核心功能:
1. 将普通Python函数变为IExecutableAgent实现
2. 自动注册到AgentRegistry
3. 自动发布agent.registered事件到EventBus
4. 自动添加AgentConstraints约束管控
5. 自动关联GateDefinition质量门禁

用法:
    from harness.decorators import harness_agent
    from harness.constraints import AgentConstraints, AgentPriority
    from harness.types import AgentCapability, GateMode

    @harness_agent(
        name="code-reviewer",
        capabilities=[AgentCapability.PERCEIVE, AgentCapability.REASON],
        constraints=AgentConstraints(
            file_patterns=["*.py", "*.ts"],
            max_changes=50,
            require_review=True,
            no_destructive=True,
            timeout=300,
            priority=AgentPriority.HIGH,
            allowed_commands=["pytest", "git status"],
            max_tokens=4000
        ),
        gate_mode=GateMode.HYBRID,
        toolsets=["terminal", "file", "web"]
    )
    def review_code(task: str, context: dict) -> TaskResult:
        # ... 你的业务逻辑 ...
        return TaskResult(task_id=context.get("task_id", ""), ...)

    # 调用
    result = review_code("review this code", {"task_id": "t-001"})
"""

import functools
import uuid
import logging
from typing import Optional, List, Callable, Any
from harness.constraints import AgentConstraints, AgentPriority, ConstraintViolation, ConstraintSeverity, ConstraintType
from harness.types import (
    AgentCapability, AgentDefinition, IExecutableAgent,
    TaskResult, TaskStatus, Artifact, GateMode, AgentType
)
from harness.registry import AgentRegistry, get_registry
from harness.bus import EventBus, BusEventType, BusEvent, get_bus

logger = logging.getLogger("harness.decorators")


class DecoratedAgent:
    """装饰后的Agent——IExecutableAgent的自动实现
    
    将普通函数包装为IExecutableAgent:
    - 实现 execute(task, context) → 调用原函数
    - 实现 estimate_tokens(task) → 按constraints.max_tokens或启发式估算
    - 持有AgentDefinition + AgentConstraints
    - 执行前检查约束(文件/命令/破坏性)
    """
    
    def __init__(
        self,
        fn: Callable,
        definition: AgentDefinition,
        constraints: AgentConstraints,
        gate_mode: GateMode,
    ):
        self._fn = fn
        self._definition = definition
        self._constraints = constraints
        self._gate_mode = gate_mode
        # 保留原函数的属性
        self.__name__ = fn.__name__
        self.__doc__ = fn.__doc__
        self.__module__ = fn.__module__
        # 保存__wrapped__用于functools.wraps兼容
        self.__wrapped__ = fn
    
    def execute(self, task: str, context: dict) -> TaskResult:
        """执行Agent任务——带约束检查
        
        执行流程:
        1. 约束前置检查(文件/命令/破坏性)
        2. 调用原函数
        3. 约束后置检查(变更数/Token)
        4. 返回TaskResult
        """
        # ── 约束前置检查 ──
        violations = self._pre_check(task, context)
        if violations:
            # 有blocking级别的违规 → 直接返回失败结果
            blocking = [v for v in violations if v.severity == ConstraintSeverity.BLOCKING]
            if blocking:
                logger.warning(
                    f"Agent {self._definition.id} 约束违规(blocking): "
                    f"{blocking[0].detail}"
                )
                return TaskResult(
                    task_id=context.get("task_id", str(uuid.uuid4())),
                    agent_id=self._definition.id,
                    status=TaskStatus.FAILED,
                    artifacts=[],
                    duration_ms=0,
                    error=f"约束违规: {blocking[0].detail}",
                    metadata={"constraint_violations": [
                        {"type": v.constraint_type, "detail": v.detail}
                        for v in blocking
                    ]}
                )
        
        # ── 调用原函数 ──
        result = self._fn(task, context)
        
        # ── 约束后置检查 ──
        if result and result.artifacts:
            post_violations = self._post_check(result)
            if post_violations:
                # 后置违规标记到metadata
                blocking_post = [v for v in post_violations if v.severity == ConstraintSeverity.BLOCKING]
                if blocking_post and result.status == TaskStatus.COMPLETED:
                    result.status = TaskStatus.ESCALATED
                    result.metadata["constraint_violations"] = [
                        {"type": v.constraint_type, "detail": v.detail}
                        for v in blocking_post
                    ]
                    logger.warning(
                        f"Agent {self._definition.id} 后置约束违规: "
                        f"{blocking_post[0].detail}"
                    )
        
        return result
    
    def estimate_tokens(self, task: str) -> int:
        """预估Token消耗
        
        优先使用constraints.max_tokens作为上限
        否则按任务长度启发式估算
        """
        if self._constraints.max_tokens:
            return min(self._constraints.max_tokens, len(task) * 4 + 500)
        # 启发式: 每字符约4token + 基础开销500
        return len(task) * 4 + 500
    
    def _pre_check(self, task: str, context: dict) -> List[ConstraintViolation]:
        """约束前置检查"""
        violations = []
        agent_id = self._definition.id
        
        # 检查破坏性操作
        if self._constraints.is_destructive_blocked():
            destructive_keywords = ["delete", "drop", "remove", "force", "rm -rf", "truncate"]
            for kw in destructive_keywords:
                if kw.lower() in task.lower():
                    violations.append(ConstraintViolation(
                        agent_id=agent_id,
                        constraint_type=ConstraintType.DESTRUCTIVE,
                        detail=f"破坏性操作被约束禁止: 检测到关键词 '{kw}'",
                        severity=ConstraintSeverity.BLOCKING
                    ))
        
        # 检查文件访问权限
        target_files = context.get("target_files", [])
        for fp in target_files:
            if not self._constraints.validate_file_access(fp):
                violations.append(ConstraintViolation(
                    agent_id=agent_id,
                    constraint_type=ConstraintType.FILE_PATTERN,
                    detail=f"文件 '{fp}' 不在允许的模式列表中",
                    severity=ConstraintSeverity.BLOCKING
                ))
        
        # 检查命令白名单
        commands = context.get("commands", [])
        for cmd in commands:
            if not self._constraints.validate_command(cmd):
                violations.append(ConstraintViolation(
                    agent_id=agent_id,
                    constraint_type=ConstraintType.COMMAND,
                    detail=f"命令 '{cmd}' 不在白名单中",
                    severity=ConstraintSeverity.BLOCKING
                ))
        
        # 需要审查标记（warning级别，不blocking）
        if self._constraints.needs_review():
            violations.append(ConstraintViolation(
                agent_id=agent_id,
                constraint_type=ConstraintType.FILE_PATTERN,
                detail="该Agent要求人工审查",
                severity=ConstraintSeverity.WARNING
            ))
        
        return violations
    
    def _post_check(self, result: TaskResult) -> List[ConstraintViolation]:
        """约束后置检查"""
        violations = []
        agent_id = self._definition.id
        
        # 检查变更文件数
        if self._constraints.max_changes:
            changed_files = [a.path for a in result.artifacts if a.type in ("code", "config", "test")]
            if len(changed_files) > self._constraints.max_changes:
                violations.append(ConstraintViolation(
                    agent_id=agent_id,
                    constraint_type=ConstraintType.MAX_CHANGES,
                    detail=f"变更文件数 {len(changed_files)} 超过上限 {self._constraints.max_changes}",
                    severity=ConstraintSeverity.BLOCKING
                ))
        
        # 检查Token消耗
        if self._constraints.max_tokens and result.tokens_used > self._constraints.max_tokens:
            violations.append(ConstraintViolation(
                agent_id=agent_id,
                constraint_type=ConstraintType.TOKENS,
                detail=f"Token消耗 {result.tokens_used} 超过上限 {self._constraints.max_tokens}",
                severity=ConstraintSeverity.WARNING
            ))
        
        return violations
    
    def __call__(self, task: str, context: dict) -> TaskResult:
        """直接调用 → 执行execute方法"""
        return self.execute(task, context)

    @property
    def definition(self) -> AgentDefinition:
        return self._definition
    
    @property
    def constraints(self) -> AgentConstraints:
        return self._constraints
    
    @property
    def gate_mode(self) -> GateMode:
        return self._gate_mode


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
    """@harness_agent 装饰器——一键让Python函数接入Harness管控
    
    Args:
        name: Agent名称（人类可读）
        capabilities: Agent能力列表
        constraints: 行为约束（可选，不设=无约束）
        gate_mode: 质量门禁模式（STRICT/HYBRID/LOOSE）
        toolsets: 需要的工具集名称列表
        max_rounds: 单任务最大执行轮次
        temperature: LLM温度参数
        system_prompt: Agent系统提示词
        priority: Agent优先级（不设=从constraints继承或NORMAL）
        auto_register: 是否自动注册到AgentRegistry（默认True）
    
    Returns:
        装饰后的Agent——既是Callable（可直接调用），又是IExecutableAgent
    
    用法:
        @harness_agent(
            name="code-reviewer",
            capabilities=[AgentCapability.PERCEIVE, AgentCapability.REASON],
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
    # 合并优先级——用 dataclasses.replace 避免手工解包的脆弱性
    if priority and constraints:
        if constraints.priority != priority:
            from dataclasses import replace as dc_replace
            constraints = dc_replace(constraints, priority=priority)
    elif priority and not constraints:
        constraints = AgentConstraints(priority=priority)
    elif not constraints:
        constraints = AgentConstraints()
    
    if toolsets is None:
        toolsets = []
    
    def decorator(fn: Callable) -> DecoratedAgent:
        # 生成唯一Agent ID
        agent_id = f"{fn.__module__}.{fn.__name__}" if fn.__module__ != "__main__" else fn.__name__
        
        # 创建AgentDefinition
        definition = AgentDefinition(
            id=agent_id,
            name=name,
            capabilities=capabilities,
            toolsets=toolsets,
            agent_type=agent_type,
            max_rounds=max_rounds,
            temperature=temperature,
            system_prompt=system_prompt,
            metadata={
                "constraints": constraints.summary(),
                "gate_mode": gate_mode.value,
                "decorated": True,
            }
        )
        
        # 创建DecoratedAgent包装
        agent = DecoratedAgent(
            fn=fn,
            definition=definition,
            constraints=constraints,
            gate_mode=gate_mode,
        )
        
        # 自动注册
        if auto_register:
            registry = get_registry()
            registry.register(definition, agent)
            logger.info(f"Agent '{name}'({agent_id}) 自动注册到Registry")
            
            # 通知事件（reserved）：Agent 已同步注册到 Registry（registry.register 已完成）；当前无异步订阅者，保留作可观测/未来消费者接入
            bus = get_bus()
            bus.emit(BusEvent(
                type=BusEventType.AGENT_REGISTERED,
                execution_id=f"register-{agent_id}",
                agent_id=agent_id,
                data={
                    "name": name,
                    "capabilities": [c.value for c in capabilities],
                    "constraints": constraints.summary(),
                    "gate_mode": gate_mode.value,
                }
            ))
        
        return agent
    
    return decorator
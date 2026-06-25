"""
harness-sdk — Universal Agent Harness SDK

Agent 决策执行，Harness 稳定约束。

SDK 提供简化版 API，让开发者几行代码就能让 Python 函数接入 Harness 管控:
  - @harness_agent 装饰器 → 一键注册+约束+门禁
  - Lifecycle Hooks → before/after/on_error 生命周期控制
  - Harness Client → DAG编排、合规扫描、审计查询

用法:
    from harness_sdk import harness_agent, AgentConstraints, AgentPriority

    @harness_agent(
        name="code-reviewer",
        capabilities=["perceive", "reason"],
        constraints=AgentConstraints(
            file_patterns=["*.py", "*.ts"],
            max_changes=50,
            no_destructive=True,
        ),
    )
    def review_code(task: str, context: dict) -> TaskResult:
        ...

    # 直接调用 → 自动走约束检查+门禁
    result = review_code("review this code", {"task_id": "t-001"})
"""

__version__ = "0.1.0"

# ─── 核心类型（从 harness 重导出，简化命名）──────────────────────

from harness.types import (
    # Agent
    AgentCapability as Capability,
    AgentType,
    AgentDefinition,
    IExecutableAgent,
    TaskResult,
    TaskStatus,
    Artifact,
    # Gate
    GateMode,
    GateDefinition,
    GateCheck,
    CheckResult,
    RetryStrategy,
    # Compliance
    ComplianceCategory,
    ComplianceRule,
    ComplianceResult,
    # Guardrails
    GuardrailAction,
    InputGuardrailConfig,
    OutputGuardrailConfig,
    # DAG
    DAGNode,
    DAGEdge,
    DAGWorkflow,
    # Scheduler
    SchedulePlan,
    ResourceUsage,
    SmartSchedulerConfig,
    # Negotiation
    NegotiationEventType,
    NegotiationEvent,
    FileConflict,
    # Audit
    AuditEntry,
    AuditStats,
    # Learning
    ExecutionTrace,
    TraceNode,
    Recommendation,
    # Bus
    BusEventType,
    BusEvent,
)

# ─── 约束系统（简化版）──────────────────────────────────────────

from harness.constraints import (
    AgentConstraints,
    AgentPriority as Priority,
    ConstraintViolation,
    ConstraintSeverity,
    ConstraintType,
)

# ─── 装饰器（SDK 核心）──────────────────────────────────────────

from harness_sdk.decorators import (
    harness_agent,
    simple_agent,
)

# ─── 生命周期钩子（SDK 核心）─────────────────────────────────────

from harness_sdk.hooks import (
    Hook,
    HookType,
    HookContext,
    HookResult,
    before_hook,
    after_hook,
    error_hook,
    HookChain,
)

# ─── Agent 接入接口（SDK 核心）────────────────────────────────────

from harness_sdk.agent import (
    AgentClient,
    AgentInfo,
    create_agent,
    register_agent,
    get_agent,
    list_agents,
)

# ─── Harness Client（编排/合规/审计一站式）─────────────────────────

from harness_sdk.client import (
    HarnessClient,
    HarnessClientConfig,
    create_client,
)

# ─── 配置便捷 ──────────────────────────────────────────────────

from harness.config import (
    HarnessConfig,
    ConfigLoader,
    load_config,
    default_config,
)

# ─── 知识管理 ──────────────────────────────────────────────────

from harness.knowledge import (
    KnowledgeType as Knowledge,
    KnowledgeScope as Scope,
    KnowledgeEntry,
    KnowledgeQuery,
    KnowledgeQueryResult,
    LocalKnowledgeProvider,
    KnowledgeContext,
    get_knowledge_provider,
)

__all__ = [
    # Types
    "Capability", "AgentType", "AgentDefinition", "IExecutableAgent",
    "TaskResult", "TaskStatus", "Artifact",
    "GateMode", "GateDefinition", "GateCheck", "CheckResult", "RetryStrategy",
    "ComplianceCategory", "ComplianceRule", "ComplianceResult",
    "GuardrailAction", "InputGuardrailConfig", "OutputGuardrailConfig",
    "DAGNode", "DAGEdge", "DAGWorkflow",
    "SchedulePlan", "ResourceUsage", "SmartSchedulerConfig",
    "NegotiationEventType", "NegotiationEvent", "FileConflict",
    "AuditEntry", "AuditStats",
    "ExecutionTrace", "TraceNode", "Recommendation",
    "BusEventType", "BusEvent",
    # Constraints
    "AgentConstraints", "Priority", "ConstraintViolation",
    "ConstraintSeverity", "ConstraintType",
    # SDK
    "harness_agent", "simple_agent",
    "Hook", "HookType", "HookContext", "HookResult",
    "before_hook", "after_hook", "error_hook", "HookChain",
    "AgentClient", "AgentInfo", "create_agent", "register_agent",
    "get_agent", "list_agents",
    "HarnessClient", "HarnessClientConfig", "create_client",
    # Config
    "HarnessConfig", "ConfigLoader", "load_config", "default_config",
    # Knowledge
    "Knowledge", "Scope", "KnowledgeEntry", "KnowledgeQuery",
    "KnowledgeQueryResult", "LocalKnowledgeProvider", "KnowledgeContext",
    "get_knowledge_provider",
]
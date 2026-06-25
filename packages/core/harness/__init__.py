"""
harness-cook — Universal Agent Harness SDK

Agent 决策执行，Harness 稳定约束。
"""

__version__ = "0.1.0"

from harness.types import (
    # Agent
    AgentCapability,
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
    # Rollback
    RollbackPolicy,
    # Skill — 可插拔能力单元
    SkillSlotName,
    SkillTool,
    SkillDefinition,
    # Profile — 脚手架配置
    StepConfig,
    WorkflowConfig,
    ProfileConfig,
    # S-3: 个性化治理分层——三级合并
    merge_profiles,
)
from harness.constraints import (
    AgentConstraints,
    AgentPriority,
    ConstraintViolation,
    ConstraintSeverity,
    ConstraintType,
)
from harness.decorators import (
    harness_agent,
    DecoratedAgent,
)
# Agent 资源约束——约束 Agent 的资源使用边界（token预算、模型分级、温度限制）
# 不直接调度 LLM：ILLMProvider/LLMDispatcher/CircuitBreaker/ModelRouter 等已移除
from harness.llm import (
    ModelTier,
    LLMConstraints,
    TokenUsageRecord,
    TokenTracker,
    PromptTemplate,
    get_tracker,
)
from harness.knowledge import (
    KnowledgeType,
    KnowledgeScope,
    KnowledgeEntry,
    KnowledgeQuery,
    KnowledgeQueryResult,
    LocalKnowledgeProvider,
    NoOpEmbeddingService,
    KnowledgeContext,
    get_knowledge_provider,
)
from harness.validator_types import (
    IssueSeverity,
    RequirementPriority,
    CodeLocation,
    ValidationIssue,
    Requirement,
    ChangeDescription,
    ValidationContext,
    ValidationResult,
    ValidatorRegistry,
    DestructiveChangeValidator,
    MaxChangesValidator,
    get_validator_registry,
)
from harness.impact_types import (
    ImpactRiskLevel,
    DependencyNode,
    CallGraphNode,
    ImpactRisk,
    ImpactAnalysis,
    DependencyGraph,
)
from harness.impact_analyzer import (
    FileImpactAnalyzer,
    get_impact_analyzer,
    IImpactAnalyzer,
)
from harness.gate_notification import (
    NotificationPriority,
    DowngradeAction,
    GateApprovalDecision,
    GateNotification,
    AutoDowngrade,
    LocalNotifier,
    GateApprovalRecord,
    GateManager,
    get_gate_manager,
)
# Phase 5 交付物: 独立降级模块
from harness.downgrade import (
    DowngradePolicy,
    DowngradeEvent,
    DowngradeTracker,
    DowngradeEngine,
    get_downgrade_engine,
)
# God Class 精度提升模块: ATFD+WMC+TCC 复合检测
from harness.god_class_metrics import (
    GodClassMetrics,
    ClassMetrics,
    CompoundThresholds,
    make_thresholds_from_config,
    DEFAULT_ATFD_FEW,
    DEFAULT_WMC_HIGH,
    DEFAULT_TCC_LOW,
)
from harness.audit import (
    AuditStore,
    verify_audit_chain,
)
# 自动回滚引擎
from harness.rollback import (
    RollbackSnapshot,
    SnapshotSet,
    RollbackResult,
    VerifyResult,
    RollbackEngine,
    get_rollback_engine,
    reset_rollback_engine,
)
# 可视化增强: HTML/DOT/DSM 报告生成器
from harness.report import (
    HTMLReportGenerator,
    DOTReportGenerator,
    DSMReport,
)
# 污点追踪: source→sink 数据流检测
from harness.taint import (
    TaintTracker,
    TaintSource,
    TaintSink,
    TaintSourceType,
    TaintSinkType,
    TaintFinding,
    BUILTIN_SOURCES,
    BUILTIN_SINKS,
)
# 方法级调用图
from harness.call_graph import (
    CallGraph,
    CallGraphBuilder,
)
# 日志配置
from harness.logging_config import (
    HarnessFormatter,
    configure_logging,
)
# Skill 注册表
from harness.skill_registry import (
    SkillRecord,
    SkillRegistry,
    get_skill_registry,
    reset_skill_registry,
    register_builtin_skills,
    register_project_skills,
)
# Profile 加载器
from harness.config import (
    ProfileLoader,
    load_profile,
    list_profiles,
    find_project_root,
    resolve_harness_root,
    resolve_hook_command,
    builtin_profiles_dir,
)
# Bridge — 一键部署到 Agent 平台
from harness.bridge import (
    HarnessBridge,
    get_bridge,
)
# Agent 适配器
from harness.adapters import (
    IAgentAdapter,
    ClaudeCodeAdapter,
)
# 审计日志
from harness.audit_logger import (
    write_audit_log,
    log_hook_execute,
    log_skill_execute,
    log_gate_check,
    log_deploy,
)
# 异常类型体系
from harness.exceptions import (
    HarnessError,
    ConstraintViolationError,
    GateCheckError,
    SkillExecutionError,
    ProfileLoadError,
    ComplianceError,
    BridgeDeployError,
    DowngradeError,
)
# S-2: 治理语义标准化——GovernanceSemantic + Registry
from harness.governance_semantics import (
    GovernanceAction,
    GovernanceSemantic,
    GovernanceSemanticRegistry,
    get_governance_semantic_registry,
)
# 外部引擎集成——治理集成总线
from harness.integrations import (
    ExternalEngineChecker,
)
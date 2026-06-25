"""
harness-cook 核心类型定义

所有框架接口的纯定义层——不依赖任何 runtime，只定义"是什么"。
实现层在各自的模块中（engine.py, gates.py 等）。

注意：类定义顺序遵循依赖关系——被引用的类型先定义。
"""

from __future__ import annotations

from typing import Protocol, TypeVar, Generic, Optional, Callable, Any, List
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


# ═══════════════════════════════════════════════════════════
#  Agent — 智能体定义与执行结果
# ═══════════════════════════════════════════════════════════

class AgentCapability(Enum):
    """Agent 能力枚举——声明一个 Agent 能做什么"""
    PERCEIVE = "perceive"       # 感知环境/上下文
    REASON = "reason"           # 推理与规划
    EXECUTE = "execute"         # 执行操作（写代码、调API等）
    REMEMBER = "remember"       # 记忆与检索
    COLLABORATE = "collaborate" # 与其他Agent协作
    SELF_DRIVE = "self_drive"   # 自驱动（自主决定下一步）


# ═══════════════════════════════════════════════════════════
#  Platform — 平台能力声明与执行策略（S-1/S-5）
# ═══════════════════════════════════════════════════════════

class ExecutionStrategy(Enum):
    """护栏执行策略——根据平台能力声明决定（S-5 退让检测）"""
    ENHANCEMENT = "enhancement"   # 平台已有等价能力 → harness 退让为可选增强（双通道协同）
    COOPERATIVE = "cooperative"   # 平台有部分能力 → harness 补充平台不覆盖的场景
    FALLBACK = "fallback"         # 平台无等价能力 → harness 完全负责（兜底模式）


@dataclass
class PlatformCapability:
    """平台治理能力声明（S-1/S-5）

    每个适配器通过 get_capabilities() 返回此声明。
    resolve_execution_strategy() 根据此声明决定护栏执行策略。
    """
    supports_realtime_redact: bool = False   # 能做内容级脱敏替换
    supports_realtime_block: bool = False    # 能做内容级阻止
    supports_pii_detection: bool = False    # 有 PII 检测能力
    pii_types_supported: List[str] = field(default_factory=list)  # 支持哪些 PII 类型
    supports_compliance_scan: bool = False   # 有合规扫描能力
    compliance_engines: List[str] = field(default_factory=list)   # 有哪些合规引擎

    @property
    def has_full_guardrail(self) -> bool:
        """平台有完整护栏能力（redact + block）"""
        return self.supports_realtime_redact and self.supports_realtime_block

    @property
    def has_partial_pii(self) -> bool:
        """平台有部分 PII 检测能力（有检测能力 OR 有类型列表）"""
        return self.supports_pii_detection or len(self.pii_types_supported) > 0

    def resolve_execution_strategy(self) -> "ExecutionStrategy":
        """S-5：根据平台能力声明决定护栏执行策略

        退让检测逻辑：
        1. 平台有完整护栏（redact + block）→ ENHANCEMENT
           harness 退让为可选增强层，与平台双通道协同
        2. 平台有部分能力 → COOPERATIVE
           harness 补充平台不覆盖的场景（如 PII 检测 + 合规扫描）
        3. 平台无等价能力 → FALLBACK
           harness 完全负责护栏检测和拦截

        Returns:
            ExecutionStrategy — 护栏执行策略
        """
        if self.has_full_guardrail:
            return ExecutionStrategy.ENHANCEMENT

        if self.supports_realtime_redact or self.supports_realtime_block:
            return ExecutionStrategy.COOPERATIVE

        if self.has_partial_pii or self.supports_compliance_scan:
            return ExecutionStrategy.COOPERATIVE

        return ExecutionStrategy.FALLBACK

    def summary(self) -> str:
        """能力摘要"""
        parts = []
        if self.supports_realtime_redact:
            parts.append("realtime-redact")
        if self.supports_realtime_block:
            parts.append("realtime-block")
        if self.has_partial_pii:
            types = ",".join(self.pii_types_supported) if self.pii_types_supported else "generic"
            parts.append(f"pii({types})")
        if self.supports_compliance_scan or self.compliance_engines:
            engines = ",".join(self.compliance_engines) if self.compliance_engines else "generic"
            parts.append(f"compliance({engines})")
        return " | ".join(parts) if parts else "none"

# ── nextX扩展: AgentType角色分类 ──
class AgentType(Enum):
    """Agent 角色分类——从nextX AgentType提取
    
    nextX定义8种角色: analyst/impact/planner/coder/reviewer/validator/committer/coordinator
    harness-cook保留核心6种，去掉coordinator(由engine.py编排代替)和impact(合并到REASON)
    """
    ANALYST = "analyst"     # 分析师——需求分析、影响评估
    PLANNER = "planner"     # 规划师——任务分解、策略制定
    CODER = "coder"         # 编码者——代码生成、修复实现
    REVIEWER = "reviewer"   # 审查者——代码审查、质量检查
    VALIDATOR = "validator" # 验证者——测试验证、合规检查
    COMMITTER = "committer" # 提交者——变更提交、发布操作


# ── TaskStatus 枚举先定义（被 TaskResult 引用）──

class TaskStatus(Enum):
    """任务执行状态——枚举化，不再用裸字符串

    向后兼容: TaskStatus.COMPLETED == "completed" 返回 True，
    方便已有代码从字符串比较平滑过渡到枚举。
    """
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"

    def __eq__(self, other):
        if isinstance(other, TaskStatus):
            return self.value == other.value
        if isinstance(other, str):
            return self.value == other
        return NotImplemented

    def __hash__(self):
        return hash(self.value)


# ── Artifact 和 TaskResult 先定义（被 IExecutableAgent 引用）──

@dataclass
class Artifact:
    """任务产出物——代码、文档、配置、测试等"""
    type: str                           # "code" | "doc" | "config" | "test" | "log" | "data"
    path: str                           # 文件路径或标识符
    content: str                        # 内容文本
    metadata: dict = field(default_factory=dict)


@dataclass
class TaskResult:
    """Agent 执行结果——标准化的任务产出"""
    task_id: str
    agent_id: str
    status: TaskStatus = TaskStatus.COMPLETED  # 改为 Enum，默认 completed
    artifacts: list[Artifact] = field(default_factory=list)
    duration_ms: int = 0
    tokens_used: int = 0
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        """向后兼容: 允许 str 自动转为 TaskStatus Enum"""
        if isinstance(self.status, str):
            # 尝试匹配已知状态
            try:
                self.status = TaskStatus(self.status)
            except ValueError:
                # 未知状态字符串 → 降级为 FAILED 并记录原始值
                self.metadata["_original_status"] = self.status
                self.status = TaskStatus.FAILED


@dataclass
class AgentDefinition:
    """Agent 注册卡——告诉 Harness 这个 Agent 是谁、能做什么"""
    id: str
    name: str
    capabilities: list[AgentCapability]
    toolsets: list[str]                # 该Agent需要的工具集名称
    max_rounds: int = 15               # 单任务最大执行轮次
    temperature: float = 0.2           # LLM温度参数
    system_prompt: str = ""            # Agent的系统提示词
    agent_type: Optional[AgentType] = None  # nextX扩展: 角色分类
    metadata: dict = field(default_factory=dict)  # 扩展元数据


class IExecutableAgent(Protocol):
    """Agent 执行接口——任何接入 Harness 的 Agent 必须实现"""
    def execute(self, task: str, context: dict) -> TaskResult: ...

    def estimate_tokens(self, task: str) -> int:
        """预估该任务消耗的token数（用于调度预算）"""
        ...


# ═══════════════════════════════════════════════════════════
#  Gate — 质量门禁
# ═══════════════════════════════════════════════════════════

# ── CheckResult 先定义（被 GateCheck 引用）──

@dataclass
class CheckResult:
    """检查结果——通过/失败 + 诊断信息"""
    passed: bool
    severity: str
    message: str
    auto_fixable: bool = False
    fix_suggestion: Optional[str] = None
    details: dict = field(default_factory=dict)


@dataclass
class RetryStrategy:
    """重试策略——失败后如何处理"""
    max_retries: int = 3
    backoff_ms: int = 1000            # 退避间隔
    depth_reduction: bool = True      # 重试时降低检查深度（只跑critical）
    escalation_threshold: int = 3     # 连续N次失败升级人工


@dataclass
class GateCheck:
    """单个检查项——一个可执行的验证逻辑"""
    id: str
    category: str               # "security" | "privacy" | "compliance" | "style" | "logic"
    severity: str               # "critical" | "high" | "medium" | "low"
    description: str
    check_fn: Callable[[Artifact], CheckResult]   # 检查函数
    auto_fix_fn: Optional[Callable[[Artifact, CheckResult], Artifact]] = None  # 自动修复函数


class GateMode(Enum):
    """门禁模式——决定检查失败后的行为"""
    STRICT = "strict"        # 所有检查必须通过，否则阻塞
    HYBRID = "hybrid"        # lint/style可自动修复，逻辑错误升级人工
    LOOSE = "loose"          # 只做基本检查，不阻塞交付


@dataclass
class GateDefinition:
    """质量门禁定义——一组检查规则的容器"""
    id: str
    checks: list[GateCheck]
    mode: GateMode = GateMode.HYBRID
    max_retries: int = 3
    retry_strategy: RetryStrategy = field(default_factory=RetryStrategy)


# ═══════════════════════════════════════════════════════════
#  Spec — 任务验收契约
# ═══════════════════════════════════════════════════════════

@dataclass
class TaskSpec:
    """任务验收契约——执行前的正面定义

    Harness Engineering 核心思想：Constraints 告诉 Agent "不能做什么",
    TaskSpec 告诉 Agent 和 Gate "做完应该是什么样子"。

    没有 TaskSpec 的 Gate 检查是"看起来不错"的直觉判断;
    有 TaskSpec 的 Gate 检查是"符合规范"的锚定验证。

    用法:
        spec = TaskSpec(
            objective="实现用户认证模块",
            acceptance_criteria=[
                "所有测试通过",
                "无硬编码密钥",
                "API 返回 200/401/403",
            ],
            output_schema={"type": "object", "properties": {"module": {"type": "string"}}},
        )
        node = DAGNode(id="auth", agent_type="coder", task="...", spec=spec)
        # DAGEngine 执行后用 spec 作为 Gate 验证锚点
    """
    objective: str                                  # 任务目标——一句话描述"做完什么"
    acceptance_criteria: list[str] = field(default_factory=list)  # 验收标准——每个是可判定的断言
    input_schema: Optional[dict] = None             # 输入格式约束（JSON Schema）
    output_schema: Optional[dict] = None            # 输出格式约束（JSON Schema）
    max_retries: int = 2                            # 不满足标准时的最大重试次数
    timeout_seconds: int = 300                      # 超时判定阈值


# ═══════════════════════════════════════════════════════════
#  DAG — 工作流编排
# ═══════════════════════════════════════════════════════════

class ComplianceCategory(Enum):
    """合规类别"""
    SECURITY = "security"           # 安全（注入、硬编码密钥等）
    PRIVACY = "privacy"             # 隐私（PII泄露等）
    LICENSE = "license"             # 许可证合规
    LEGAL = "legal"                 # 法律风险（AI生成内容版权、免责声明、合规声明等）
    STYLE = "style"                 # 代码风格
    ARCHITECTURE = "architecture"   # 架构约束（依赖方向等）


@dataclass
class PatternDefinition:
    """统一模式定义——所有治理层共享的正则检测模式

    PatternDefinition 是护栏/合规/门禁三层检测正则的唯一定义源。
    新增检测模式只需注册一个 PatternDefinition，各层按需获取。

    与 ComplianceRule 的区别：
    - PatternDefinition 定义"检测什么"（正则+目标+基准 severity）
    - ComplianceRule 定义"如何合规检查"（含修复建议+matcher_type+语言范围）
    - PatternDefinition → ComplianceRule 是一层转换，不是替代

    各层使用方式：
    - 护栏层：从 PatternRegistry 获取模式 → 做拦截决策（BLOCK/WARN/REDACT）
    - 合规层：从 PatternRegistry 获取模式 → 生成 ComplianceRule → 做报告记录
    - 门禁层：从 PatternRegistry 获取模式 → 生成 CheckResult → 做质量检查
    """
    id: str                               # 唯一标识，如 "hardcoded-password"
    pattern: str                          # 正则表达式（canonical 版本）
    category: ComplianceCategory          # 类别（SECURITY/PRIVACY 等）
    target_type: str                      # 检测目标类型
                                          # "secret" | "pii" | "code_injection" | "sql_injection" | "unsafe_code"
    canonical_severity: str               # 标准严重程度（"critical"/"high"/"medium"/"low"）
    description: str                      # 人类可读描述
    remediation: str = ""                 # 修复建议
    languages: list[str] = field(default_factory=list)  # 适用语言（空=全部）
    sub_type: str = ""                    # 子类型细分（如 "password"/"api_key"/"token"/"email"/"phone"）
    flags: int = 0                        # 正则编译 flags（re.IGNORECASE | re.DOTALL 等，0=无额外 flags）


@dataclass
class ComplianceRule:
    """合规规则——一条可匹配的检查规则

    matcher_type 决定规则如何匹配:
    - "regex": 正则表达式匹配（默认，单文件模式）
    - "dependency_graph": 依赖图架构检查（跨文件，需要 ScanContext.dependency_graph）
    - "ast": AST 结构检查（单文件，使用 Python stdlib ast 模块）
    - "cross_file": 跨文件模式检查（需要 ScanContext 中多个 artifact）
    """
    id: str
    category: ComplianceCategory
    pattern: str                # 正则表达式或检查逻辑描述
    severity: str               # "critical" | "high" | "medium" | "low"
    description: str
    remediation: str            # 修复建议
    auto_fixable: bool = False
    languages: list[str] = field(default_factory=list)   # 适用语言（空=全部）
    # ── 可插拔匹配策略 ──
    matcher_type: str = "regex"                     # "regex" | "dependency_graph" | "ast" | "cross_file"
    matcher_config: dict = field(default_factory=dict)  # 匹配策略所需的配置参数


@dataclass
class ComplianceResult:
    """合规检查结果"""
    rule_id: str
    passed: bool
    severity: str
    findings: list[str]             # 发现的问题列表
    remediation: Optional[str] = None
    locations: list[dict] = field(default_factory=list)   # 问题位置


@dataclass
class ScanContext:
    """扫描上下文——跨文件分析所需的全局信息

    当 matcher_type 为 dependency_graph/cross_file 时，
    ComplianceEngine.scan 会构建 ScanContext 传递给 IRuleChecker。
    """
    artifacts: list[Artifact]                           # 所有待扫描的产出物
    dependency_graph: Optional[Any] = None              # 依赖图（DependencyGraph 实例）
    project_root: Optional[str] = None                  # 项目根目录
    metadata: dict = field(default_factory=dict)        # 扩展元数据


# ═══════════════════════════════════════════════════════════
#  Guardrails — 输入输出安全过滤
# ═══════════════════════════════════════════════════════════

class GuardrailAction(Enum):
    """护栏动作——检测到问题后的处理方式"""
    BLOCK = "block"           # 完全阻止，不执行
    WARN = "warn"             # 警告但继续执行
    REDACT = "redact"         # 脱敏处理后继续
    REPLACE = "replace"       # 替换敏感内容后继续


@dataclass
class InputGuardrailConfig:
    """输入护栏配置——进入Agent前的过滤规则"""
    detect_pii_types: list[str]               # 要检测的PII类型: ["email","phone","ssn","credit_card"]
    pii_action: GuardrailAction               # PII检测后的动作
    max_input_length: int = 10000             # 输入最大长度
    banned_phrases: list[str] = field(default_factory=list)  # 禁止的短语
    long_prompt_threshold: int = 5000         # 超长提示阈值
    virtual_keys: dict = field(default_factory=dict)         # 虚拟密钥映射


@dataclass
class OutputGuardrailConfig:
    """输出护栏配置——Agent输出后的过滤规则"""
    detect_pii_in_output: bool = True
    output_pii_action: GuardrailAction = GuardrailAction.REDACT
    banned_output_patterns: list[str] = field(default_factory=list)  # 禁止的输出模式
    max_output_length: int = 50000            # 输出最大长度
    check_code_safety: bool = True            # 检查代码安全性（eval/注入等）
    require_artifact_validation: bool = True  # 要求所有产出物经过验证


# ═══════════════════════════════════════════════════════════
#  DAG — 有向无环图编排
# ═══════════════════════════════════════════════════════════

@dataclass
class DAGNode:
    """DAG节点——一个可执行的任务单元"""
    id: str
    agent_type: str                # 引用 registry 中的 Agent 类型
    task: str                      # 该节点的任务描述
    inputs: list[str]              # 上游节点ID列表
    outputs: list[str]             # 下游节点ID列表
    gate: Optional[GateDefinition] = None   # 该节点的质量门禁
    spec: Optional[TaskSpec] = None         # 任务验收契约——正面定义"做完应该是什么样子"
    metadata: dict = field(default_factory=dict)


@dataclass
class DAGEdge:
    """DAG边——节点间的连接，可带条件"""
    from_node: str
    to_node: str
    condition: Optional[str] = None   # 条件表达式（简化版，不支持eval）


@dataclass
class DAGWorkflow:
    """完整工作流——一个DAG图的完整定义"""
    id: str
    name: str
    description: str = ""
    nodes: list[DAGNode] = field(default_factory=list)
    edges: list[DAGEdge] = field(default_factory=list)
    entry_node: str = ""              # 入口节点ID
    exit_nodes: list[str] = field(default_factory=list)   # 终止节点ID列表
    global_gate: Optional[GateDefinition] = None   # 全局质量门禁（每个节点结束后检查）


# ═══════════════════════════════════════════════════════════
#  Scheduler — 资源感知调度
# ═══════════════════════════════════════════════════════════

@dataclass
class SchedulePlan:
    """调度计划——并行分组 + 关键路径 + 检查点"""
    parallel_groups: list[list[str]]      # 并行执行的节点组（每组内并行）
    sequential_groups: list[list[str]]    # 串行执行的节点组（组间串行）
    critical_path: list[str]              # 关键路径节点序列
    checkpoints: list[str]                # 检查点节点（完成后暂停等待确认）
    estimated_duration_ms: int
    estimated_tokens: int
    resource_warnings: list[str] = field(default_factory=list)


@dataclass
class ResourceUsage:
    """资源使用情况——实时追踪"""
    tokens_used: int = 0
    tokens_budget: int = 200000
    rpm_used: int = 0
    rpm_limit: int = 60
    current_parallelism: int = 0
    max_parallelism: int = 4
    elapsed_ms: int = 0


@dataclass
class SmartSchedulerConfig:
    """智能调度配置"""
    max_parallelism: int = 4              # 最大并行Agent数
    llm_rate_limit_per_minute: int = 60   # LLM RPM限制
    token_budget: int = 200000            # 总token预算
    retry_strategy: str = "adaptive"      # "fixed" | "adaptive" | "exponential"
    merge_threshold: int = 2              # 小任务合并阈值（token<此值时合并）
    checkpoint_on_gate_fail: bool = True  # 门禁失败时暂停等待人工


# ═══════════════════════════════════════════════════════════
#  Negotiation — 多Agent协商
# ═══════════════════════════════════════════════════════════

class NegotiationEventType(Enum):
    """协商事件类型"""
    CONFLICT_ALERT = "conflict_alert"       # 冲突警报
    REVIEW_REQUEST = "review_request"       # 评审请求
    DEBATE_PROPOSAL = "debate_proposal"     # 辩论提议
    DEBATE_RESULT = "debate_result"         # 辩论结果
    ESCALATION = "escalation"               # 升级人工


@dataclass
class NegotiationEvent:
    """协商事件"""
    id: str
    timestamp: datetime
    event_type: NegotiationEventType
    payload: dict


@dataclass
class FileConflict:
    """文件冲突——两个Agent修改了同一文件"""
    file_path: str
    agent_a: str
    agent_b: str
    ranges_a: list[dict]           # Agent A 的修改范围
    ranges_b: list[dict]           # Agent B 的修改范围
    content_a: str                 # Agent A 的内容
    content_b: str                 # Agent B 的内容
    resolution: Optional[str] = None   # "a" | "b" | "merge" | "escalate"


# ═══════════════════════════════════════════════════════════
#  Audit — 审计溯源与可观测
# ═══════════════════════════════════════════════════════════

@dataclass
class AuditEntry:
    """审计记录——一次任务的完整决策链"""
    timestamp: datetime
    task: str
    session_id: str
    agent_id: str
    decisions: list[dict]              # 决策列表 [{reasoning, action, confidence}]
    actions: list[dict]                # 行动列表 [{tool, input, output, duration}]
    outcomes: dict                     # 结果概要
    risk_assessment: Optional[dict] = None   # 风险评估
    escalation_history: list[dict] = field(default_factory=list)
    chain_hash: Optional[str] = None          # SHA-256哈希链(不可篡改)


@dataclass
class AuditStats:
    """审计统计——全局健康指标"""
    total_tasks: int = 0
    delivered: int = 0
    auto_fixed: int = 0
    escalated: int = 0
    verification_pass_rate: float = 0.0
    avg_duration_ms: int = 0
    avg_tokens_per_task: int = 0
    conflict_rate: float = 0.0


# ═══════════════════════════════════════════════════════════
#  Learning — 自学习（模式挖掘、校准）
# ═══════════════════════════════════════════════════════════

# ── TraceNode 先定义（被 ExecutionTrace 引用）──

@dataclass
class TraceNode:
    """轨迹节点——单个任务的运行记录"""
    node_id: str
    agent_type: str
    task: str
    result_status: str               # "completed" | "failed" | "skipped"
    duration_ms: int
    files_modified: list[str]
    files_read: list[str]
    tokens_used: int
    gate_passed: bool = True
    retries: int = 0


@dataclass
class ExecutionTrace:
    """执行轨迹——一个完整工作流的运行记录"""
    workflow_id: str
    timestamp: datetime
    duration_ms: int
    nodes: list[TraceNode]
    gate_results: list[CheckResult]
    final_status: str                # "completed" | "failed" | "escalated"


@dataclass
class Recommendation:
    """学习推荐——基于历史数据的建议"""
    type: str                        # "schedule" | "gate" | "agent" | "architecture"
    confidence: float                # 0.0 ~ 1.0
    description: str
    suggested_action: str
    evidence: list[str] = field(default_factory=list)   # 支撑证据


@dataclass
class Insight:
    """学习洞见——从反模式检测中提炼的治理洞察（E-6）

    与 Recommendation 的区别：
      - Recommendation 是原始推荐，包含各种类型（schedule, gate 等）
      - Insight 是经过治理提炼的洞见，只关注反模式+风险+修复建议
      - Insight 不自动注册为 ComplianceRule（需要人工审核后采纳）
      - Insight 进入知识库供查看和决策，而非自动生效

    洞见路径：
      LearningEngine.learn() → 检测反模式 → 产出 Insight
      → EventBus 发射 INSIGHT_FOUND 事件
      → 知识库写入（KnowledgeEntry）
      → 用户查看/采纳 → 采纳后可手动激活为规则（S-4）

    禁止路径：
      Insight → 自动注册为 ComplianceRule（E-6 消除此路径）
    """
    pattern_type: str                # 反模式类型："antipattern" | "risk" | "architecture"
    confidence: float                # 0.0 ~ 1.0
    title: str                       # 洞见标题
    description: str                 # 洞见描述（发现了什么）
    remediation: str                 # 修复建议（怎么做）
    evidence: list[str] = field(default_factory=list)  # 支撑证据
    source_project: Optional[str] = None  # 来源项目名
    metadata: Optional[dict] = None  # 额外元数据


# ═══════════════════════════════════════════════════════════
#  Bus — 事件总线
# ═══════════════════════════════════════════════════════════

class RollbackPolicy(Enum):
    """回滚策略——决定节点失败时的回滚行为"""
    NONE = "none"        # 不快照、不回滚
    MANUAL = "manual"    # 创建快照但不自动回滚（需手动调用）
    AUTO = "auto"        # 创建快照且失败时自动回滚


class BusEventType(Enum):
    """总线事件类型——覆盖所有生命周期阶段"""
    # Agent生命周期
    AGENT_REGISTERED = "agent:registered"
    AGENT_DEREGISTERED = "agent:deregistered"
    # 执行生命周期
    NODE_START = "node:start"
    NODE_COMPLETE = "node:complete"
    NODE_FAIL = "node:fail"
    NODE_RETRY = "node:retry"
    # 门禁生命周期
    GATE_CHECK = "gate:check"
    GATE_PASS = "gate:pass"
    GATE_FAIL = "gate:fail"
    GATE_RETRY = "gate:retry"
    # 门禁审批（E-9：EventBus 回调模式）
    GATE_APPROVAL_REQUEST = "gate:approval_request"     # E-9：请求人工审批
    GATE_APPROVAL_DECISION = "gate:approval_decision"   # E-9：审批决策到达
    # 工作流生命周期
    WORKFLOW_START = "workflow:start"
    WORKFLOW_COMPLETE = "workflow:complete"
    WORKFLOW_FAIL = "workflow:fail"
    # 合规
    COMPLIANCE_CHECK = "compliance:check"
    COMPLIANCE_PASS = "compliance:pass"
    COMPLIANCE_FAIL = "compliance:fail"
    # 协商
    CONFLICT_ALERT = "conflict:alert"
    CONFLICT_RESOLVED = "conflict:resolved"
    # 升级
    ESCALATION = "escalation"
    # 护栏
    GUARDRAIL_BLOCK = "guardrail:block"
    GUARDRAIL_REDACT = "guardrail:redact"
    # 学习
    TRACE_CAPTURED = "trace:captured"
    RECOMMENDATION = "recommendation"
    INSIGHT_FOUND = "insight:found"      # E-6：洞见发现事件（替代 Recommendation→rule 自动路径）

    # 回滚
    ROLLBACK_SNAPSHOT_CREATED = "rollback:snapshot_created"
    ROLLBACK_RESTORED = "rollback:restored"
    ROLLBACK_FAILED = "rollback:failed"
    ROLLBACK_VERIFIED = "rollback:verified"
    # 审计
    AUDIT_SECONDARY_FAIL = "audit:secondary_fail"


@dataclass
class BusEvent:
    """总线事件——所有模块间通信的标准格式"""
    type: BusEventType
    execution_id: str               # 执行上下文ID
    node_id: Optional[str] = None   # 关联的DAG节点ID
    agent_id: Optional[str] = None  # 关联的Agent ID
    project_name: Optional[str] = None  # 关联的项目名（E-7：项目级隔离）
    data: Optional[dict] = None     # 事件数据
    timestamp: datetime = field(default_factory=datetime.now)


# ═══════════════════════════════════════════════════════════
#  Skill — 可插拔的能力单元
# ═══════════════════════════════════════════════════════════

class SkillSlotName(Enum):
    """Skill 插槽名——流程节点上的挂载点（E-8 分层重构）

    核心概念：Skills 定步骤。
    每个插槽对应一个生命周期阶段，Skill 挂载到插槽后自动在该阶段执行。

    插槽三层分类（E-8）：

    ┌──────────┬───────────────────────────────────────────────────────┐
    │ 层级     │ 插槽                                                 │
    ├──────────┼───────────────────────────────────────────────────────┤
    │ 核心通道 │ SESSION_START, POST_EXECUTE, ON_ERROR,               │
    │ (5个)    │ ON_GATE_PASS, ON_GATE_FAIL                          │
    │ 默认启用 │ DAGEngine 集成，Profile YAML 默认展示               │
    ├──────────┼───────────────────────────────────────────────────────┤
    │ 扩展通道 │ SESSION_END, PRE_EXECUTE                            │
    │ (2个)    │ 有真实 hook 脚本支持，Profile YAML 可选展示         │
    ├──────────┼───────────────────────────────────────────────────────┤
    │ 理论通道 │ PRE_TOOL_USE, POST_TOOL_USE, ON_FILE_CHANGE,        │
    │ (10个)   │ PRE_COMMIT, POST_COMMIT, ON_DELEGATE, ON_CONFLICT,  │
    │ 仅枚举   │ ON_DECISION, ON_ESCALATION, USER_PROMPT_SUBMIT      │
    │ 不展示   │ SkillSlotName 存在但无生产集成，Profile YAML 不展示 │
    └──────────┴───────────────────────────────────────────────────────┘

    Profile YAML 只展示核心+扩展通道（7行），理论通道见：
      docs/45-Slot分层映射表-20260616.md

    Slot → HookType 映射：
      每个 SkillSlotName 对应 SDK HookType 的一种时序（BEFORE/AFTER/ON_ERROR），
      具体映射见 docs/45-Slot分层映射表-20260616.md 的映射表章节。
    """
    # ═══ 核心通道 ═══
    SESSION_START = "session_start"    # [核心] 会话开始 — BEFORE
    POST_EXECUTE = "post_execute"      # [核心] Agent 执行任务后 — AFTER ⭐默认启用
    ON_ERROR = "on_error"              # [核心] 任务执行异常时 — ON_ERROR
    ON_GATE_PASS = "on_gate_pass"      # [核心] 门禁检查通过后 — AFTER
    ON_GATE_FAIL = "on_gate_fail"      # [核心] 门禁检查失败时 — ON_ERROR

    # ═══ 扩展通道 ═══
    SESSION_END = "session_end"        # [扩展] 会话结束 — AFTER
    PRE_EXECUTE = "pre_execute"        # [扩展] Agent 执行任务前 — BEFORE

    # ═══ 理论通道 ═══
    PRE_TOOL_USE = "pre_tool_use"      # [理论] 使用工具前 — BEFORE
    POST_TOOL_USE = "post_tool_use"    # [理论] 使用工具后 — AFTER
    ON_FILE_CHANGE = "on_file_change"  # [理论] 文件变更时 — AFTER
    PRE_COMMIT = "pre_commit"          # [理论] 提交代码前 — BEFORE
    POST_COMMIT = "post_commit"        # [理论] 提交代码后 — AFTER
    ON_DELEGATE = "on_delegate"        # [理论] 委派任务给子 Agent 时 — BEFORE
    ON_CONFLICT = "on_conflict"        # [理论] 检测到冲突时 — ON_ERROR
    ON_DECISION = "on_decision"        # [理论] Agent 做出重要决策时 — AFTER
    ON_ESCALATION = "on_escalation"    # [理论] 问题升级到人工时 — ON_ERROR
    USER_PROMPT_SUBMIT = "user_prompt_submit"  # [理论] 用户提交提示词时 — BEFORE


@dataclass
class SkillTool:
    """Skill 专属工具——Skill 可以声明自己的工具

    用法:
        SkillTool(name="git-diff", command="git diff HEAD~1", description="查看最近变更")
    """
    name: str                         # "git-diff" | "eslint"
    command: str                      # "git diff HEAD~1"
    description: str = ""


@dataclass
class SkillDefinition:
    """Skill 定义——注册到 SkillRegistry 的声明

    用法:
        SkillDefinition(
            id="auto-audit",
            name="自动审计",
            description="任务完成后自动记录审计日志",
            entry_point="skills/auto-audit/audit_report.py",
            slot=SkillSlotName.POST_EXECUTE,
            tags=["audit", "compliance"],
        )
    """
    id: str                           # "auto-audit" | "custom-lint"
    name: str                         # 人类可读名称
    description: str = ""
    version: str = "1.0.0"
    entry_point: str = ""             # "skills/auto-audit/audit_report.py"
    prompt_template: str = ""         # 提示词模板路径（可选）
    slot: SkillSlotName = SkillSlotName.POST_EXECUTE
    tools: list[SkillTool] = field(default_factory=list)  # Skill 专属工具
    tags: list[str] = field(default_factory=list)
    config_schema: dict = field(default_factory=dict)     # 配置 JSON Schema
    metadata: dict = field(default_factory=dict)
    timeout_seconds: int = 60         # implementation 执行超时（秒），0=不限


# ═══════════════════════════════════════════════════════════
#  Profile — 一套完整的脚手架配置
# ═══════════════════════════════════════════════════════════

@dataclass
class StepConfig:
    """流程步骤配置——可指定 Skill + 步骤级 Hooks

    核心概念：步骤级 Agent 切换 + 步骤级 hooks。
    每个步骤可以指定不同的 skill，也可以有自己的 pre/post hooks。

    用法:
        StepConfig(
            name="review-code",
            skill="code-review",
            hooks_pre=[{"type": "script", "command": "python3 check-ticket.py"}],
        )
    """
    name: str                         # "review-code"
    skill: str = ""                   # 使用的 Skill ID
    condition: str = ""               # 条件表达式（简化版）
    parallel: bool = False            # 是否并行
    hooks_pre: list[dict] = field(default_factory=list)
    hooks_post: list[dict] = field(default_factory=list)


@dataclass
class WorkflowConfig:
    """工作流配置——编排多个步骤

    用法:
        WorkflowConfig(
            name="feature-dev",
            steps=[
                StepConfig(name="analyze", skill="requirement-analysis"),
                StepConfig(name="implement", skill="code-generation"),
                StepConfig(name="review", skill="code-review"),
            ],
        )
    """
    name: str
    description: str = ""
    vars: dict = field(default_factory=dict)         # 流程变量
    steps: list[StepConfig] = field(default_factory=list)


@dataclass
class ProfileConfig:
    """Profile——一套完整的脚手架配置

    一个 Profile 描述了：默认 Agent、pipeline 步骤、skill 插槽、hooks、gates。
    切换 Profile 即切换整套行为模式。

    用法:
        ProfileConfig(
            name="default",
            default_agent="claude-code",
            pipeline_agents=["analyst", "coder", "validator", "committer"],
            hooks={"session_start": [{"type": "script", "command": "..."}]},
        )
    """
    name: str = "default"
    description: str = ""
    # 默认 Agent（第一期硬编码 claude-code，后续可切换）
    default_agent: str = "claude-code"
    # Pipeline
    pipeline_agents: list[str] = field(default_factory=lambda: [
        "analyst", "coder", "validator", "committer"])
    # 工作流步骤（细粒度编排，覆盖 pipeline_agents 的默认顺序）
    workflow: Optional[WorkflowConfig] = None
    # Skill 插槽: {"analyst": {"post_execute": ["custom-req-check"]}, ...}
    skill_slots: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    # 全局 Hooks: {"session_start": [{"type": "script", "command": "..."}], ...}
    hooks: dict[str, list[dict]] = field(default_factory=dict)
    # Gates
    default_gate_mode: GateMode = GateMode.HYBRID
    gate_checks: list[dict] = field(default_factory=list)
    # 约束
    constraints: dict = field(default_factory=dict)
    # 任务验收契约模板——每个节点继承这些默认标准
    default_spec: Optional[TaskSpec] = None
    # ─── 治理集成总线引擎配置 ───
    # 所有字段默认 None → 向后兼容，现有 Profile YAML 无需改动
    # 护栏层引擎配置（Guardrails AI 等）
    guardrails_engine: Optional["GuardrailsEngineConfig"] = None
    # 合规层引擎配置（SonarQube/OPA/ArchUnit/dep-cruiser）
    compliance_engine: Optional["ComplianceEngineConfig"] = None
    # 审计层引擎配置（Langfuse/Arize/Datadog）
    audit_engine: Optional["AuditEngineConfig"] = None
    # ─── S-3: 个性化治理分层 ───
    # Profile 来源层级：project > team > user（项目级强制项不可被下游覆盖）
    layer: str = "project"  # "project" | "team" | "user"
    # 项目级强制字段——合并时这些字段不会被 team/user 层覆盖
    # 例如 ["hooks", "gate_checks"] 表示项目级 hooks 和 gate_checks 不可被覆盖
    forced_keys: list[str] = field(default_factory=lambda: [
        "hooks", "gate_checks", "default_gate_mode",
    ])


def merge_profiles(
    project_profile: ProfileConfig,
    team_profile: Optional[ProfileConfig] = None,
    user_profile: Optional[ProfileConfig] = None,
) -> ProfileConfig:
    """S-3：三级治理分层合并

    合并策略：
      - 项目级强制项（forced_keys）不可被 team/user 层覆盖
      - 非强制项按 team > user 优先级合并（team 优先于 user）
      - 合并产生新的 ProfileConfig，不修改原始对象

    层级图示：

    ```
    project（强制层）
      ├── hooks          ← 项目强制，不可覆盖
      ├── gate_checks    ← 项目强制，不可覆盖
      ├── default_gate_mode ← 项目强制，不可覆盖
      ├── constraints    ← 可被 team/user 补充
      └── 其他非强制项   ← 可被 team/user 覆盖
    team（团队层）
      ├── 可补充非强制项
      └── 不可覆盖项目强制项
    user（个人层）
      ├── 可补充非强制项
      └── 不可覆盖项目强制项
    ```

    Args:
        project_profile: 项目级 Profile（最高优先级）
        team_profile: 团队级 Profile（中间优先级）
        user_profile: 用户级 Profile（最低优先级）

    Returns:
        合并后的 ProfileConfig
    """
    import copy

    # 以项目级 Profile 为基线
    result = copy.deepcopy(project_profile)

    # 收集项目级强制项的值——这些值将被保护
    forced_values = {}
    for key in project_profile.forced_keys:
        forced_values[key] = copy.deepcopy(getattr(project_profile, key, None))

    # 按优先级合并：team → user
    for upper_profile in [team_profile, user_profile]:
        if upper_profile is None:
            continue

        for field_name in [
            "description", "default_agent", "pipeline_agents",
            "workflow", "skill_slots", "constraints", "default_spec",
            "guardrails_engine", "compliance_engine", "audit_engine",
            # 强制项默认包含这些字段，但也可通过 forced_keys 移除保护
            # 当不在 forced_keys 中时，允许被 team/user 层合并或覆盖
            "hooks", "gate_checks", "default_gate_mode",
        ]:
            # 非强制项：上游层可覆盖
            if field_name in forced_values:
                continue  # 强制项跳过

            upper_value = getattr(upper_profile, field_name, None)
            if upper_value is not None:
                # 特殊处理 dict 类型：合并而非覆盖
                current = getattr(result, field_name, None)
                if isinstance(current, dict) and isinstance(upper_value, dict):
                    # 合并 dict（上游层补充当前缺失的键）
                    merged_dict = copy.deepcopy(current)
                    for k, v in upper_value.items():
                        if k not in merged_dict:
                            merged_dict[k] = copy.deepcopy(v)
                    setattr(result, field_name, merged_dict)
                elif isinstance(current, list) and isinstance(upper_value, list):
                    # 合并 list（上游层补充当前缺失的元素）
                    merged_list = copy.deepcopy(current)
                    for item in upper_value:
                        if item not in merged_list:
                            merged_list.append(copy.deepcopy(item))
                    setattr(result, field_name, merged_list)
                else:
                    # 其他类型：上游层直接覆盖
                    setattr(result, field_name, copy.deepcopy(upper_value))

    # 强制项恢复——确保没有被修改
    for key, value in forced_values.items():
        if value is not None:
            setattr(result, key, copy.deepcopy(value))

    # 合后 layer 标记为 "merged"
    result.layer = "merged"

    return result

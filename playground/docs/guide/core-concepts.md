# 核心概念

harness-cook 围绕八大核心模块 + integrations 集成子包构建，每个模块职责清晰、接口独立，通过 EventBus 松耦合协作。

## 模块总览

| 模块 | 职责 | 关键类 |
|------|------|--------|
| Registry | Agent 注册与发现 | `AgentRegistry`, `AgentDefinition` |
| Engine | DAG 工作流编排与执行 | `DAGEngine`, `ExecutionContext` |
| Gates | 质量门禁与审批 | `GateEngine`, `GateDefinition`, `GateMode` |
| Compliance | 合规规则扫描 | `ComplianceEngine`, `ComplianceRule`, `RulePack` |
| Guardrails | 安全护栏（PII 检测/脱敏 + 外部引擎可选） | `PIIDetector`, `InputGuardrails`, `OutputGuardrails` |
| Audit | 审计日志存储 | `AuditStore`, `AuditEntry`, `IAuditStore`, `MultiAuditStore` |
| Scheduler | 智能调度——资源感知并行分组 | `SmartScheduler`, `SmartSchedulerConfig`, `SchedulePlan` |
| Negotiation | 多 Agent 冲突检测与协商 | `ConflictDetector`, `NegotiationEngine`, `FileConflict` |
| Downgrade | 降级策略——超时自动降级 | `DowngradeEngine`, `DowngradePolicy`, `DowngradeAction` |
| Rollback | 自动回滚——文件快照还原 | `RollbackEngine`, `RollbackSnapshot` |
| Constraints | Agent 约束 + LLM 资源分层 | `AgentConstraints`, `ModelTier`, `LLMConstraints`, `TokenTracker` |
| Learning | 自学习闭环——模式挖掘+推荐 | `PatternMiner`, `AntiPatternDetector`, `LearningEngine` |
| Knowledge | 知识管理——10类知识+TF-IDF搜索 | `IKnowledgeProvider`, `LocalKnowledgeProvider`, `KnowledgeType` |
| Impact | 影响分析——依赖图+风险评级 | `FileImpactAnalyzer`, `DependencyGraph`, `ImpactRiskLevel` |
| Taint | 污点追踪——source-to-sink安全追踪 | `TaintTracker`, `TaintSourceType`, `TaintSinkType` |
| DeclarativeRules | 声明式规则——YAML→GateDefinition | `DeclarativeRule`, `CheckerBase`, `RegexChecker` |
| RuleMarket | 规则市场——发现/安装/搜索 | `RuleMarket`, `RulePackMetadata` |
| Config | 配置系统——Profile/Overlay合叠 | `HarnessConfig`, `ProfileLoader`, `ProfileConfig` |
| OTel | OTel集成——Span+指标+导出 | `OTelBridge`, `OTelConfig`, `HAS_OTEL` |
| Report | 可视化报告——HTML/DOT/DSM | `HTMLReportGenerator`, `DOTReportGenerator`, `DSMReport` |
| Experimental | 实验性模块——自主循环等 | `AutonomousLoopEngine`, `AutonomousLoopConfig` |
| **SkillRegistry** | **Skill 注册与执行** | `SkillRegistry`, `SkillDefinition`, `SkillSlotName` |
| **Bridge** | **Profile 部署** | `HarnessBridge`, `ProfileConfig` |
| **SuperpowersBridge** | **Superpowers Skill 桥接** | `scan_superpowers_dir`, `map_superpowers_to_skill_definition` |
| **Integrations** | **引擎集成总线** | `ExternalEngineChecker`, 各引擎适配器（按护栏/合规/审计/编排分类）, `IAuditStore`, `MultiAuditStore` |

模块间通过 `EventBus` 传递事件，不直接调用——修改一个模块不影响其他模块的运行。

---

## Integrations 子包（治理集成总线）

integrations 子包是 harness-cook 的战略核心——将外部专业引擎接入治理框架。

### ExternalEngineChecker 基类

所有外部合规引擎适配器继承此基类，只需实现 4 个方法：

```python
class ExternalEngineChecker(IRuleChecker):
    """模板方法模式——探测→不可用则fallback→翻译→调用→翻译响应→出错catch回退"""

    def _probe_engine(self)          → 子类实现（import SDK + 轻量实例）
    def _translate_request(rule, artifact, context) → dict → 子类实现
    def _call_engine(request) → dict                   → 子类实现
    def _translate_response(response, rule) → ComplianceResult → 通用默认，子类可覆盖

    def check(rule, artifact, context) → ComplianceResult:
        # 1. 惰性探测引擎可用性（缓存）
        # 2. 不可用 → fallback 到内置 RegexChecker
        # 3. 翻译请求 → 调用引擎 → 翻译响应
        # 4. 出错 → catch 回退到内置 checker
```

### 已实现的引擎适配器

| 类别 | 适配器 | engine_name | fallback |
|---|---|---|---|
| 护栏 | GuardrailsAIChecker | guardrails-ai | RegexChecker |
| 护栏 | NeMoGuardrailsChecker | nemo-guardrails | RegexChecker |
| 护栏 | LlamaGuardChecker | llama-guard | RegexChecker |
| 护栏 | HeliconeMiddlewareChecker | helicone | RegexChecker |
| 合规 | SonarQubeChecker | sonarqube | RegexChecker |
| 合规 | OPAChecker | opa | RegexChecker |
| 合规 | ArchUnitChecker | archunit | DependencyGraphChecker |
| 合规 | DepCruiserChecker | dep_cruiser | DependencyGraphChecker |

### MatcherRegistry 引擎路由

MatcherRegistry.default() 通过 `try/except ImportError` 块注册所有引擎适配器：

```python
class MatcherRegistry:
    @classmethod
    def default(cls) -> 'MatcherRegistry':
        registry = cls()
        # 内置 checkers
        registry.register("regex", RegexChecker())
        registry.register("dependency_graph", DependencyGraphChecker())
        # 外部引擎——不装→不注册→规则回退内置 checker
        try:
            from harness.integrations.guardrails_ai_checker import GuardrailsAIChecker
            registry.register("guardrails_ai", GuardrailsAIChecker())
        except ImportError:
            pass
        # ... 其他引擎同理
        return registry
```

### 语言感知路由

ComplianceEngine.scan() 可根据文件语言自动路由最优引擎：

| 语言 | 推荐引擎 | fallback |
|---|---|---|
| Java | ArchUnitChecker | DependencyGraphChecker |
| JavaScript / TypeScript | DepCruiserChecker | DependencyGraphChecker |
| 通用策略 | OPAChecker | RegexChecker |

```yaml
# Profile 配置语言路由
compliance:
  language_routing:
    java: archunit
    javascript: dep_cruiser
    typescript: dep_cruiser
```

语言路由是建议性的——用户可通过 `matcher_type` 显式覆盖。

### 规则导入器

从外部引擎导入规则到 ComplianceRule 格式：

```python
from harness.integrations.rule_importer import SonarQubeRuleImporter, RulePack

importer = SonarQubeRuleImporter(sonarqube_url="http://sonar:9000", token="xxx")
pack = importer.import_rules(project_key="my-project")
engine.load_pack(pack)  # SonarQube 规则 → ComplianceEngine 可扫描
```

---

## IAuditStore Protocol（审计存储契约）

IAuditStore 是审计存储的统一契约——所有审计后端必须实现此 Protocol：

```python
from runtime_checkable import Protocol
from harness.integrations.audit_store_protocol import IAuditStore

class IAuditStore(Protocol):
    def save(self, entry: AuditEntry) -> str: ...
    def load(self, entry_id: str) -> Optional[AuditEntry]: ...
    def search(self, query: str, limit: int = 50) -> list[AuditEntry]: ...
    def verify_chain(self) -> dict: ...
    def integrity_report(self) -> dict: ...
```

AuditEngine.__init__ 类型提示从 AuditStore 改为 IAuditStore——默认行为不变（AuditStore 继续做默认存储），但可按配置替换为任意 IAuditStore 实现。

---

## MultiAuditStore（多后端双写）

MultiAuditStore 实现审计多后端叠加——本地永远主存储，外部按配置叠加：

```python
from harness.integrations.multi_store import MultiAuditStore
from harness.audit import AuditStore

# 本地永远可用
stores = [AuditStore()]  # 主存储（本地 SQLite）

# 按配置叠加外部后端
# stores.append(LangfuseAuditStore(...))  # 次存储
# stores.append(ArizeAuditStore(...))     # 次存储

multi_store = MultiAuditStore(stores)
```

**双写策略：**
- 主存储（stores[0]）必须成功——失败则报错
- 次存储（stores[1:]）火忘式写入——失败只记 warning + 发 AUDIT_SECONDARY_FAIL 事件

---

## 编排平台中间件

harness-cook 提供两个编排平台中间件，将治理能力嵌入工作流：

### LangGraphGovernanceNode

```python
from harness.integrations.langgraph_middleware import LangGraphGovernanceNode

# LangGraph StateGraph 中插入治理检查点
governance_node = LangGraphGovernanceNode(config=governance_config)
graph.add_node("governance_check", governance_node.execute)
```

### wrap_node_with_governance

```python
from harness.integrations.langgraph_middleware import wrap_node_with_governance

# 前置输入护栏 + 后置输出护栏+门禁+合规
wrapped_node = wrap_node_with_governance(my_node_fn, config=governance_config)
```

### DeerFlowBridge

```python
from harness.integrations.deerflow_bridge import DeerFlowBridge

bridge = DeerFlowBridge()
validation_step = bridge.translate_gate_to_validation(gate)
workflow = bridge.translate_profile_to_workflow(profile)
```

---

## Agent Registry

Agent Registry 是 Agent 的注册中心。每个 Agent 由两部分组成：

- **AgentDefinition** —— 声明 Agent 的身份与能力（名字、类型、工具集、约束）
- **IExecutableAgent** —— Agent 的实际执行逻辑（`execute()` + `estimate_tokens()`）

```python
from harness.registry import AgentRegistry
from harness.types import AgentDefinition, AgentCapability, AgentType
from harness.bus import EventBus

bus = EventBus()
registry = AgentRegistry(bus=bus)

# 定义
definition = AgentDefinition(
    id="my-agent",
    name="My Agent",
    capabilities=[AgentCapability.EXECUTE, AgentCapability.REASON],
    agent_type=AgentType.CODER,
    toolsets=["terminal", "file"],
)

# 注册（definition + implementation 分离）
registry.register(definition, MyAgentImpl())

# 发现
record = registry.get("my-agent")
stats = registry.stats()
```

AgentCapability 六种能力：

| 能力 | 含义 |
|------|------|
| `PERCEIVE` | 感知——读取外部信息 |
| `REASON` | 推理——分析与决策 |
| `EXECUTE` | 执行——产出代码/文档 |
| `REMEMBER` | 记忆——保持上下文 |
| `COLLABORATE` | 协作——与其他 Agent 交互 |
| `SELF_DRIVE` | 自驱——自主规划任务 |

AgentType 六种角色：`analyst`, `planner`, `coder`, `reviewer`, `validator`, `committer`。

## DAG Engine

DAGEngine 将复杂任务拆解为有向无环图（DAG）工作流，拓扑排序后逐步执行。

**核心类型：**

- **DAGNode** —— 工作流节点，字段：`id`, `agent_type`(str), `task`(str), `inputs`, `outputs`
- **DAGEdge** —— 节点间依赖，字段：`from_node`, `to_node`, `condition`（注意：是 `from_node`/`to_node`，不是 `source`/`target`）
- **DAGWorkflow** —— 完整工作流，字段：`id`, `name`, `nodes`, `edges`, `description`, `global_gate`

**两阶段执行：**

```python
from harness.engine import DAGEngine
from harness.types import DAGNode, DAGEdge, DAGWorkflow

engine = DAGEngine(registry=registry, bus=bus)

# Phase 1: 规划——拓扑排序
order = engine.plan(workflow)  # → list[str] 如 ["analyze", "code", "verify"]

# Phase 2: 执行——逐步调用 Agent
context = engine.execute(workflow)  # → ExecutionContext
```

ExecutionContext 包含完整执行结果：`execution_id`, `workflow_id`, `duration_ms`, `node_status`, `completed_nodes`, `failed_nodes`, `node_artifacts`, `escalated`。

::: warning
DAGEdge 字段名是 `from_node` 和 `to_node`。旧版 YAML 中可能出现 `source`/`target`，bridge.py 已做双兼容，但 Python API 统一用 `from_node`/`to_node`。
:::

## Scheduler

智能调度器决定"什么时候跑、并行多少、token 预算够不够"。它分析 DAG 拓扑结构，将节点按深度分层——同一深度的节点可并行执行，不同深度串行推进。此外它跟踪资源使用（token 消耗、RPM 限制、并行度），动态调整执行策略：token 预算紧张时降级为串行模式，预算充足时最大化并行。

核心类型与配置：

- **SmartSchedulerConfig** —— 调度参数：`max_parallelism`, `token_budget`, `llm_rate_limit_per_minute`, `checkpoint_on_gate_fail`
- **SchedulePlan** —— 调度计划产出：`parallel_groups`, `sequential_groups`, `critical_path`, `checkpoints`, `estimated_tokens`, `resource_warnings`
- **ResourceUsage** —— 实时资源追踪：`tokens_budget`, `tokens_used`, `rpm_limit`, `rpm_used`, `max_parallelism`, `current_parallelism`

```python
from harness.scheduler import SmartScheduler
from harness.types import DAGWorkflow, SmartSchedulerConfig

# 配置调度参数
config = SmartSchedulerConfig(
    max_parallelism=3,
    token_budget=100000,
    llm_rate_limit_per_minute=60,
)

scheduler = SmartScheduler(config=config)

# 生成调度计划
plan = scheduler.plan(workflow)
# plan.parallel_groups → [[入口节点], [中间节点组], [出口节点]]
# plan.estimated_tokens → 预估总 token 消耗
# plan.critical_path → 关键路径（最长串行链）
# plan.resource_warnings → 资源超限预警

# 运行时资源追踪
scheduler.update_resource(tokens_used=5000, rpm_used=12, parallelism=2)
can_continue = scheduler.can_execute_more()  # token 余量 + 并行度检查
mode = scheduler.recommend_mode()            # "aggressive" | "moderate" | "conservative"
```

**三档执行模式：**

| 模式 | 条件 | 行为 |
|------|------|------|
| `aggressive` | token 余量 > 30% | 最大并行，充分利用预算 |
| `moderate` | token 余量 10%-30% | 有限并行，谨慎使用 |
| `conservative` | token 余量 < 10% | 串行执行 + 小任务合并 |

**Learning→Scheduler 闭环：** SmartScheduler 订阅 EventBus 的 `RECOMMENDATION` 事件，接受 Learning 模块的高置信度（>=0.6）调度推荐——如 `reduce_token_budget`（缩减 token 预估比例）或 `increase_timeout`（增加超时预估比例），动态调整后续调度参数。

## Gate Engine

Gate Engine 为工作流节点提供质量门禁。三种模式对应不同管控强度：

| 模式 | 行为 |
|------|------|
| `STRICT` | 每个节点产出必须通过所有检查才继续 |
| `HYBRID` | 高严重性违规阻断，低严重性放行 |
| `LOOSE` | 仅记录违规，不阻断执行 |

```python
from harness.types import GateDefinition, GateMode, GateCheck, CheckResult
from harness.gates import GateEngine

gate_engine = GateEngine(bus=bus)

gate = GateDefinition(
    node_id="code",
    mode=GateMode.HYBRID,
    checks=[
        GateCheck(id="sec-001", category="security", severity="high",
                  description="禁止硬编码密钥", check_fn=my_check_fn),
    ],
)

gate_engine.register(gate)
```

GateCheck 的 `check_fn` 接收 `Artifact`，返回 `CheckResult`。可选提供 `auto_fix_fn` 实现自动修复。

**三档门禁是 harness-cook 的核心护城河**——编排层不做、审计层不做、合规层不做，只有 harness-cook 做事前拦截决策。

## GateNotification（门禁通知推送）

GateNotification 实现门禁审批的异步人工交互——当 GateDefinition 标记 `require_review=True` 时，系统自动创建审批通知，推送给指定接收者，等待人工决策。超时未审批则触发自动降级。

核心类型：

- **GateNotification** —— 审批通知：`gate_id`, `recipient`, `message`, `action_url`, `deadline`, `priority`
- **NotificationPriority** —— 三级优先级：`URGENT`（需立即审批，阻断流程）、`NORMAL`（在 deadline 前审批）、`INFO`（仅通知，不需审批）
- **GateApprovalDecision** —— 四种审批结果：`APPROVED`, `REJECTED`, `TIMEOUT`, `CANCELLED`
- **GateApprovalRecord** —— 审批记录（审计追溯）：`gate_id`, `decision`, `decided_at`, `decided_by`（"human" | "system-downgrade"）, `reason`

```python
from harness.gate_notification import (
    GateManager, GateNotification, NotificationPriority, GateApprovalDecision,
)

# 创建 GateManager（默认使用 LocalNotifier — 本地日志通知）
manager = GateManager()

# 创建审批 gate — 发送通知
notification = manager.create_gate(
    gate_id="deploy-gate-001",
    recipient="tech-lead",
    message="生产环境部署需审批",
    priority=NotificationPriority.URRGENT,
    deadline_minutes=15,
)

# 检查通知状态
notification.is_expired()          # 是否已超时
notification.time_remaining()      # 剩余时间（timedelta）
notification.summary()             # "[urgent] Gate deploy-gate-001: 生产环境部署需审批, 剩余900秒"

# 等待审批（轮询通知器，超时自动降级）
decision = manager.wait_for_approval("deploy-gate-001", timeout_seconds=900)

# 审批统计
stats = manager.stats()  # {"total_gates": 1, "approved": 0, "rejected": 0, "timeout": 0, "cancelled": 0}
```

**INotifier Protocol** 定义通知渠道接口——`send()` 发送通知、`receive()` 接收审批决策。首期实现 `LocalNotifier` 只记录日志、手动注入决策；未来可扩展为 Slack/邮件/Webhook/CLI 交互审批。

## DowngradeEngine（降级引擎）

DowngradeEngine 从 GateNotification 模块提取为独立模块，统一管控超时自动降级策略。核心设计：不同风险级别对应不同超时阈值和降级动作，每次降级都记录审计轨迹。

**DowngradePolicy** 按风险级别配置降级规则：

| 风险级别 | 默认超时 | 默认动作 | 逻辑 |
|----------|----------|----------|------|
| `high` | 15 分钟 | `ABORT` | 短超时，快速中止（零风险） |
| `medium` | 30 分钟 | `SIMPLIFY` | 中等超时，简化变更后继续 |
| `low` | 60 分钟 | `SKIP` | 长超时，跳过审批继续（最低风险） |

**DowngradeAction** 三种降级动作：

| 动作 | 行为 | 对应 GateApprovalDecision |
|------|------|---------------------------|
| `SKIP` | 跳过门禁，继续执行 | `APPROVED` |
| `SIMPLIFY` | 简化变更，降低风险后继续 | `APPROVED` |
| `ABORT` | 中止执行，标记失败 | `REJECTED` |

```python
from harness.downgrade import DowngradeEngine, DowngradePolicy
from harness.gate_notification import DowngradeAction

# 自定义降级策略
policy = DowngradePolicy(
    name="production",
    high_timeout_minutes=10,
    medium_timeout_minutes=20,
    low_timeout_minutes=45,
    high_action=DowngradeAction.ABORT,
    medium_action=DowngradeAction.SIMPLIFY,
    low_action=DowngradeAction.SKIP,
    on_downgrade_callback=lambda gate_id, action, reason: print(f"降级: {gate_id} → {action.value}"),
)

engine = DowngradeEngine(policy=policy)

# 执行降级
decision = engine.execute_downgrade(
    gate_id="deploy-gate-001",
    risk_level="high",
    reason="审批超时10分钟",
)
# high → ABORT → decision = GateApprovalDecision.REJECTED

# 为 GateManager 生成 AutoDowngrade
auto_downgrade = engine.make_auto_downgrade_for_risk("medium")
# → AutoDowngrade(after_minutes=20, action=SIMPLIFY)

# 降级统计
stats = engine.stats()
# stats["tracker"] → {"total_downgrades": 1, "by_action": {"abort": 1}, "by_risk": {"high": 1}, "bottleneck_gates": [...]}
```

**DowngradeTracker** 记录每次降级事件的完整审计轨迹——时间、原因、动作、策略名。它还能统计降级率和识别瓶颈门禁（频繁超时的 gate_id），帮助团队优化审批流程。

## RollbackEngine（回滚引擎）

RollbackEngine 是 Harness 的"安全网"——节点执行前自动创建文件快照，节点失败时可选回滚到快照状态，防止部分修改破坏项目完整性。快照存储在 `~/.harness/rollback/` 目录，使用 SHA-256 确保内容完整性。

核心类型：

- **RollbackSnapshot** —— 单文件快照：`file_path`, `content_hash`（SHA-256）, `content_snapshot`（完整内容拷贝）, `timestamp`
- **SnapshotSet** —— 一组文件快照集合：`snapshot_id`, `execution_id`, `node_id`, `snapshots`
- **RollbackResult** —— 回滚操作结果：`success`, `files_restored`, `files_failed`, `errors`, `duration_ms`
- **VerifyResult** —— 验证结果：`files_consistent`, `files_modified`, `files_missing`, `consistent`, `modified_paths`, `missing_paths`

```python
from harness.rollback import RollbackEngine

engine = RollbackEngine()

# 创建快照（节点执行前）
snapshot_set = engine.create_snapshot(
    execution_id="ex-001",
    node_id="coder-node",
    file_paths=["/src/main.py", "/src/config.py"],
)

# 验证快照完整性（检查当前文件 hash 是否与快照一致）
verify = engine.verify_snapshot(snapshot_set.snapshot_id)
# verify.consistent → True（文件未被修改）
# verify.modified_paths → []（被修改的文件路径列表）

# 恢复快照（节点失败时，还原所有文件到快照时状态）
result = engine.restore_snapshot(snapshot_set.snapshot_id)
# result.success → True
# result.files_restored → 2
# result.duration_ms → 回滚耗时

# 清理过期快照（TTL 7天 + 最大保留 100 个）
deleted = engine.cleanup_snapshots()

# 引擎统计
stats = engine.stats()
# {"total_snapshots": 5, "total_files_snapshotted": 15, "store_dir": "~/.harness/rollback"}
```

快照生命周期完整链路：创建 → 验证（检查是否被修改）→ 恢复（还原内容）→ 清理（过期删除）。每次操作都通过 EventBus 发射 `ROLLBACK_SNAPSHOT_CREATED` / `ROLLBACK_RESTORED` / `ROLLBACK_FAILED` / `ROLLBACK_VERIFIED` 事件。

## Compliance Engine

合规引擎扫描产出物，检测违反规则的代码/文档/配置。

```python
from harness.compliance import ComplianceEngine
from harness.rule_packs import get_security_pack, get_coding_pack

engine = ComplianceEngine(bus=bus)
engine.load_pack(get_security_pack())
engine.load_pack(get_coding_pack())

# 扫描产出物
results = engine.scan(artifacts)

# 快速扫描代码片段
results = engine.scan_quick(code_string, "config.py")
```

四种内置 RulePack 工厂函数：`get_coding_pack()`, `get_security_pack()`, `get_data_pack()`, `get_devops_pack()`。

**引擎路由扩展：**

ComplianceEngine 可配置外部引擎和语言感知路由：

```yaml
compliance:
  engines: [builtin, sonarqube, opa]
  language_routing:
    java: archunit
    javascript: dep_cruiser
```

## Guardrails

安全护栏分两层——输入防护和输出过滤：

- **InputGuardrails** —— 检测用户输入中的 PII（邮箱/手机/身份证/信用卡/API 密钥等），可选脱敏或阻断
- **OutputGuardrails** —— 检查 Agent 输出中的 PII 泄露和 unsafe code

```python
from harness.guardrails import InputGuardrails, OutputGuardrails, default_guardrails

pair = default_guardrails()
input_result = pair.check_input("用户邮箱是 test@test.com")
output_result = pair.check_output("生成的代码: os.system('rm -rf /tmp')")
```

**引擎可替换：**

Profile 配置可选择护栏引擎：

```yaml
guardrails:
  engine: builtin         # builtin | guardrails-ai | nemo | llama-guard | helicone
```

默认 `builtin`（PIIDetector），安装对应可选依赖后可切换到 Guardrails AI / NeMo / Llama Guard / Helicone。

## Audit Store

审计存储记录所有关键决策与执行事件，不可篡改。

```python
from harness.audit import AuditStore, AuditEntry

store = AuditStore()
entry = AuditEntry(
    session_id="s-001",
    agent_id="coder",
    action="execute",
    decision="completed",
    timestamp=datetime.now(),
)
store.save(entry)

# 搜索审计记录
entries = store.search(agent_id="coder")
```

**多后端叠加：**

```python
from harness.integrations.multi_store import MultiAuditStore

# 本地 + 外部
multi = MultiAuditStore([AuditStore(), LangfuseAuditStore(...)])
multi.save(entry)  # 主存储必须成功，次存储火忘式写入
```

## EventBus

EventBus 是模块间松耦合的事件通道。所有模块通过它发布/订阅事件，不直接引用彼此。

```python
from harness.bus import EventBus, BusEventType

bus = EventBus()
bus.emit(BusEventType.AGENT_REGISTERED, {"agent_id": "coder"})
```

::: tip
创建独立 EventBus 实例可避免全局单例冲突。Demo 和测试中建议每次创建新的 `EventBus()`。
:::

## Skill Registry

Skill Registry 管理所有可插拔的 Skill——注册、发现、按插槽查找、执行。

### 核心概念

- **SkillDefinition** —— 声明 Skill 的身份与能力（名字、插槽、入口点）
- **SkillSlotName** —— 17 个插槽点，覆盖完整生命周期
- **SkillRegistry** —— 注册表，管理所有 Skills

### 17 个插槽点

| 分类 | 插槽 | 默认启用 | 触发时机 |
|------|------|---------|---------|
| **会话级** | `SESSION_START` | ✅ | 会话开始 |
| **任务级** | `POST_EXECUTE` | ✅ | Agent 执行任务后 |
| **会话级** | `SESSION_END` | ✅ | 会话结束 |
| **任务级** | `PRE_EXECUTE` | ❌ | Agent 执行任务前 |
| **任务级** | `ON_ERROR` | ❌ | 任务执行异常时 |
| **工具级** | `PRE_TOOL_USE` | ❌ | 使用工具前 |
| **工具级** | `POST_TOOL_USE` | ❌ | 使用工具后 |
| **门禁级** | `ON_GATE_PASS` | ❌ | 门禁检查通过后 |
| **门禁级** | `ON_GATE_FAIL` | ❌ | 门禁检查失败时 |
| **文件级** | `ON_FILE_CHANGE` | ❌ | 文件变更时 |
| **提交级** | `PRE_COMMIT` | ❌ | 提交代码前 |
| **提交级** | `POST_COMMIT` | ❌ | 提交代码后 |
| **协作级** | `ON_DELEGATE` | ❌ | 委派任务时 |
| **协作级** | `ON_CONFLICT` | ❌ | 检测到冲突时 |
| **决策级** | `ON_DECISION` | ❌ | 做出重要决策时 |
| **决策级** | `ON_ESCALATION` | ❌ | 问题升级到人工时 |
| **交互级** | `USER_PROMPT_SUBMIT` | ❌ | 用户提交提示词时 |

详细指南见 [Skill 插槽点完整指南](/guide/skill-slots)

### 注册与查询

SkillRegistry 采用声明式注册——先注册 SkillDefinition，实现（implementation）可后绑定。查询支持按 ID、插槽、标签三种方式。

```python
from harness.skill_registry import SkillRegistry
from harness.types import SkillDefinition, SkillSlotName

registry = SkillRegistry()

# 声明式注册（定义先行，实现可后绑定）
registry.register(SkillDefinition(
    id="auto-audit",
    name="自动审计",
    description="任务完成后自动记录审计日志",
    entry_point="skills/auto-audit/audit_report.py",
    slot=SkillSlotName.POST_EXECUTE,
    tags=["audit", "compliance"],
))

# 后绑定实现（Python 函数）
registry.bind_implementation("auto-audit", my_audit_function)

# 注册带实现的 Skill（一步完成）
registry.register(SkillDefinition(
    id="custom-check",
    name="自定义检查",
    slot=SkillSlotName.PRE_EXECUTE,
    tags=["security"],
), implementation=my_check_function)

# 查询
skill = registry.get("auto-audit")              # 按 ID
skills = registry.find_by_slot(SkillSlotName.POST_EXECUTE)  # 按插槽
skills = registry.find_by_tag("audit")           # 按标签
all_skills = registry.list_active()              # 所有激活 Skill
slots_map = registry.list_slots()                # 每个插槽上的 Skill ID 列表

# 激活/停用
registry.deactivate("auto-audit")
registry.activate("auto-audit")
```

### 执行双模式

SkillRegistry 执行 Skill 时采用双模式策略——优先使用 Python `implementation`（函数调用），否则用 CLI 方式执行 `entry_point`（`python3 entry_point`）。执行过程带超时保护（Unix 用 `SIGALRM`，Windows/非主线程用 `threading.Timer`），超时后返回 `TaskStatus.FAILED`。

```python
# 执行 Skill — 自动选择模式
result = registry.execute_skill("auto-audit", {
    "task_id": "t-001",
    "session_id": "s-001",
    "node_id": "coder",
})
# result → TaskResult(status=COMPLETED, artifacts=[...])

# CLI 方式执行 — 有 entry_point 但无 implementation
result = registry.execute_skill("auto-review", {"task_id": "t-002"})
# → subprocess.run(["python3", "skills/auto-review/review_gate.py"], ...)

# 执行统计
stats = registry.stats()
# {"total_skills": 3, "active_skills": 3, "total_executions": 5, "total_errors": 0, "slots": {...}}
```

::: tip
entry_point 路径有安全校验——禁止路径穿越（`../`）、禁止绝对路径（`/`开头）、必须以 `.py` 结尾。
:::

### 项目级 Skills 发现

`register_project_skills()` 自动扫描项目 `.harness/skills/` 目录，发现并注册项目级 Skills。每个 Skill 子目录需包含 `SKILL.md`（YAML frontmatter 声明元数据）和 Python 入口脚本。内置 Skill 优先级高于同名项目级 Skill——内置已注册时，项目级同名 Skill 跳过。

```yaml
# .harness/skills/custom-review/SKILL.md
---
name: custom-review
description: "项目定制的代码审查 Skill"
slot: post_execute
tags: ["review", "project-custom"]
---
```

```python
from harness.skill_registry import register_project_skills, register_builtin_skills

# 注册内置 Skills（auto-audit, auto-review, auto-verify）
register_builtin_skills()

# 注册项目级 Skills（从 .harness/skills/ 自动发现）
count = register_project_skills()
# → 扫描 .harness/skills/*/SKILL.md，解析 YAML frontmatter，自动查找 .py 入口脚本
```

## Bridge

Bridge 负责将 Profile 配置翻译成 Agent 原生格式，实现一键部署。

### 核心流程

1. **读取 Profile** — 从 `.harness/profiles/default.yaml` 加载配置
2. **翻译配置** — 将 hooks/skills/gates 翻译成 Agent 原生格式
3. **部署配置** — 写入 `.claude/settings.json` 等目标文件
4. **记录审计** — 每次部署都记录到审计日志

### 多平台适配器

Bridge 通过 IAgentAdapter Protocol 支持多平台部署：

| 适配器 | 目标文件 | 有 hooks？ | 说明 |
|---|---|---|---|
| ClaudeCodeAdapter | `.claude/settings.json` | ✅ 原生 hooks | ✅ 已实现——强制性治理 |
| CopilotCLIAdapter | `.copilot/config.json` | ✅ 有 hook 概念 | ✅ 已实现——强制性治理 |
| HermesAdapter | `~/.hermes/config.yaml` | ❌ 无原生 hooks | ✅ 已实现——治理通过 MCP Server 工具 |
| CursorAdapter | `.cursor/mcp.json` | ❌ 无 hooks | ✅ 已实现——仅 MCP server + metadata |
| OpenAIAdapter | 无本地配置 | ❌ 无 hooks | ✅ 已实现——function calling 定义 |

适配器选择由 5 级优先级链决定：

| 优先级 | 来源 | 说明 |
|--------|------|------|
| 1️⃣ 最高 | `--agent` CLI 参数 | 用户显式指定 |
| 2️⃣ | `HARNESS_ADAPTER` 环境变量 | CI/自动化覆盖 |
| 3️⃣ | `.harness/env` 中 `HARNESS_ADAPTER=` | 机器级持久化 |
| 4️⃣ | `.harness/active_adapter` 标记文件 | 项目级持久化 |
| 5️⃣ | Profile `agent.adapter` 字段 | 配置回退 |
| 6️⃣ 最低 | `"claude-code"` | 最终回退 |

> **Adapter 与 Profile 正交**：Adapter 决定"部署到哪"，Profile 决定"部署什么规则"。

### 部署流程与代码示例

HarnessBridge 的部署流程分六步：选择适配器 → 翻译 hooks → 翻译 gates（生成 prompt）→ 收集 skills → 合并写入目标配置 → 安装 git pre-commit hook（兜底防线）。

```python
from harness.bridge import HarnessBridge
from harness.config import load_profile

bridge = HarnessBridge()
profile = load_profile("default")

# 一键部署
result = bridge.deploy(
    profile,
    adapter_name="claude-code",   # 可选——显式指定适配器（覆盖优先级链）
)
# result → {
#   "profile": "default",
#   "adapter": "claude-code",
#   "supports_hooks": True,
#   "prompt_strength": "mild",          # 有-hooks Agent 用轻提示
#   "settings_path": ".claude/settings.json",
#   "hooks_deployed": 4,
#   "gate_checks": 2,
#   "skills_available": 3,
#   "git_hook_installed": True,
#   "status": "deployed",
# }

# 查看部署状态
status = bridge.status()
# {"deployed": True, "adapter": "claude-code", "total_hooks": 4, "has_harness_hooks": True}
```

**门禁提示翻译策略：** 有-hooks 适配器（Claude Code, Copilot CLI）用轻提示（`mild`）——hooks 已自动强制执行，prompt 只是补充说明；无-hooks 适配器（Cursor, Hermes）用强提示（`mandatory`）——prompt 是唯一的事前治理手段，标注 `MUST` 要求。

**settings.json 校验：** 写入前 HarnessBridge 会校验结构合法性——`hooks` 必须是 dict、每个 hook type 的 entries 必须是 list 且每条是 dict、`permissions` 必须是 dict。校验失败抛出 `BridgeDeployError`。

**git pre-commit hook：** 无论适配器是否支持 hooks，Bridge 都会安装 git pre-commit hook 作为兜底防线——任何不合规的变更在 git commit 时被拦截。安装策略：已有 pre-commit hook → 在末尾追加 harness 检查段；已有 harness 标记 → 替换旧版本；无 hook → 创建新的。

详细指南见 [Bridge 指南](/guide/bridge)

## SuperpowersBridge（Superpowers Skill 桥接）

SuperpowersBridge 将 Claude Code 官方 superpowers 插件的 Skills 发现并注册到 harness SkillRegistry，实现两套体系的融合桥接。

**两套体系的映射规则：**

- superpowers skills 使用 YAML frontmatter 格式（`name`, `description`）声明元数据
- harness SkillDefinition 使用 `id`, `name`, `description`, `slot`, `tags`, `entry_point` 格式
- 命名空间策略：superpowers skills 使用 `superpowers:` 前缀（如 `brainstorming` → `superpowers:brainstorming`），避免与 harness 内置 Skills ID 冲突

**Slot 映射策略：** 基于 superpowers skill 的语义分类，将 14 个 skill 映射到对应的 SkillSlotName：

| superpowers skill | 映射 Slot | 语义分类 |
|-------------------|-----------|----------|
| brainstorming, writing-plans, test-driven-development | `PRE_EXECUTE` | 执行前规划 |
| subagent-driven-development, dispatching-parallel-agents, executing-plans | `PRE_EXECUTE` | 执行前任务分解 |
| using-git-worktrees, writing-skills | `PRE_EXECUTE` | 执行前准备 |
| verification-before-completion, receiving-code-review, requesting-code-review | `POST_EXECUTE` | 执行后验证/审查 |
| finishing-a-development-branch | `POST_EXECUTE` | 分支完成 |
| systematic-debugging | `ON_ERROR` | 异常调试 |
| using-superpowers | `SESSION_START` | 会话初始化 |

未在映射表中的 skill 默认映射到 `PRE_EXECUTE`。

```python
from harness.superpowers_bridge import (
    scan_superpowers_dir,
    map_superpowers_to_skill_definition,
    register_superpowers_skills,
    find_superpowers_dir,
)

# 自动定位 superpowers 插件目录
superpowers_dir = find_superpowers_dir()
# 搜索路径: HARNESS_SUPERPOWERS_DIR 环境变量 → ~/.claude/plugins/cache/superpowers/<version>/skills/

# 扫描发现所有 skill.md 文件
discovered = scan_superpowers_dir(superpowers_dir)
# → [(skill_name, skill_md_path, frontmatter_dict), ...]

# 单个 skill 映射为 SkillDefinition
skill_def = map_superpowers_to_skill_definition(
    skill_name="brainstorming",
    skill_md_path="/path/to/skill.md",
    frontmatter={"name": "brainstorming", "description": "..."},
    plugin_version="5.1.0",
)
# skill_def.id → "superpowers:brainstorming"
# skill_def.slot → SkillSlotName.PRE_EXECUTE
# skill_def.tags → ["planning", "design", "pre-implementation", "superpowers"]

# 一键注册所有 superpowers skills 到 SkillRegistry
registered = register_superpowers_skills()
# → 扫描 + 映射 + 注册，返回 SkillDefinition 列表
```

**发现逻辑：** `find_superpowers_dir()` 搜索三个路径——环境变量 `HARNESS_SUPERPOWERS_DIR`（优先）、`~/.claude/plugins/cache/` 下最新版本目录、项目内 `.claude/skills/`。`scan_superpowers_dir()` 扫描每个子目录的 `skill.md` / `SKILL.md`，解析 YAML frontmatter 获取 `name` 和 `description`。

详细指南见 [Superpowers Bridge](/guide/superpowers-bridge)

## 下一步

治理四层深入：
- [护栏层](/guide/guardrails-layer) · [合规层](/guide/compliance-layer) · [审计层](/guide/audit-layer) · [门禁层](/guide/gate-layer)

智能增强与执行管控：
- [自学习与推荐](/guide/learning) · [知识管理](/guide/knowledge) · [影响分析](/guide/impact-analysis) · [污点追踪](/guide/taint-tracking)
- [DAG 编排引擎](/guide/dag-engine) · [调度器](/guide/scheduler) · [协商](/guide/negotiation) · [降级策略](/guide/downgrade) · [回滚](/guide/rollback) · [约束与资源管控](/guide/constraints)

引擎集成：
- [引擎集成总线](/guide/engine-bus) · [规则包](/guide/rule-packs) · [声明式规则](/guide/declarative-rules) · [规则市场](/guide/rule-market)

编排平台：
- [LangGraph 中间件](/guide/langgraph-middleware) · [DeerFlow 桥接](/guide/deerflow-bridge) · [自主循环(@experimental)](/guide/autonomous-loop)

开发者接入与部署：
- [装饰器](/guide/decorators) · [配置系统](/guide/config-system) · [Bridge](/guide/bridge) · [Superpowers Bridge](/guide/superpowers-bridge) · [MCP Server](/guide/mcp-server) · [Skill 插槽点](/guide/skill-slots) · [Agents 模块](/guide/agents-module) · [CLI](/guide/cli) · [Dashboard](/guide/dashboard) · [可视化报告](/guide/report) · [OTel 集成](/guide/otel-integration)

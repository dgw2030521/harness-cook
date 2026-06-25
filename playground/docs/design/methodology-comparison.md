# Harness Engineering 方法论对照分析

> harness-cook 项目是否真正践行了 2025–2026 年 AI Agent 圈最火的工程理念——Harness Engineering？

## 方法论速览

Harness Engineering 的核心思想：不能只靠 Prompt，要把"约束、信息、工具、验证、纠错、记忆、状态管理"全部工程化、系统化、闭环化，才能让 Agent 长期可靠干活。

五大原则：

1. **Constrain**（约束）：权限、工具白名单、资源限制
2. **Inform**（告知）：给对的上下文、代码图谱、文档、知识库
3. **Execute/Orchestrate**（执行编排）：步骤编排、状态流转、长任务管理
4. **Verify**（验证）：结果检查、单元测试、评审、自动化评估
5. **Correct**（纠正）：失败重试、回滚、自动修复、反馈闭环

## 结论

**harness-cook 在模块级全面覆盖了方法论的五大原则，并且在多个维度上有超越方法论的创新。5 个关键闭环断裂已全部修复——模块不仅存在，而且已接入执行主流程，运行时闭环接通。**

---

## 逐项对照

### 1. Constrain（约束） ✅ 模块完整 ✅ 执行路径已接通

| 方法论要求 | 项目实现 |
|---|---|
| 权限控制 | `AgentConstraints.file_patterns` — 文件操作白名单 |
| 工具白名单 | `AgentConstraints.allowed_commands` — 终端命令白名单 |
| 资源限制 | `AgentConstraints.max_changes` / `max_tokens` / `timeout` |
| 优先级 | `AgentPriority` — LOW→CRITICAL 四级 |
| 破坏性操作禁止 | `AgentConstraints.no_destructive` |
| LLM Token 预算 | `TokenTracker` / `LLMConstraints` / `ModelTier` |

**超越点**：方法论只说了"要有约束"，我们做到了**约束可执行** — `validate_file_access()`、`validate_command()` 不是声明式的，是运行时真的拦截。而且 `ConstraintViolation` 带有 `ConstraintSeverity` 分级（WARNING→BLOCKING→CRITICAL），这是方法论没细化但我们补上的。

✅ **Constraints 已在执行路径上**：DAGEngine._execute_node() 调用 `_check_constraints()` 方法强制校验，Agent 无法突破约束。

---

### 2. Inform（告知/上下文） ✅ 模块完整 ✅ Knowledge-Learning 桥接已实现

| 方法论要求 | 项目实现 |
|---|---|
| 代码图谱 | `CallGraph` / `CallGraphBuilder` — 方法级调用图 |
| 知识库 | `KnowledgeType` 10种 + `KnowledgeScope` 4级 + `LocalKnowledgeProvider` |
| 影响分析 | `FileImpactAnalyzer` / `DependencyGraph` / `ImpactRiskLevel` |
| 污点追踪 | `TaintTracker` — source→sink 数据流检测 |
| 文档/规则 | 5 大 RulePack（coding/security/data/devops/architecture） |

**超越点**：方法论说"给 Agent 对的上下文"，我们不仅给了静态知识（知识库），还给了**动态分析能力**（调用图、污点追踪、影响分析）。这意味着 Agent 在动手前能知道"改了这个会影响到谁"——这不只是告知，是**可操作的情报**。

✅ **Knowledge 与 Learning 之间桥接已实现**：LearningEngine 持有 knowledge_provider，`_persist_to_knowledge` 方法沉淀高置信度推荐为知识条目。

---

### 3. Execute/Orchestrate（执行编排） ✅ 核心完整 ✅ 并行协商和降级已接入

| 方法论要求 | 项目实现 |
|---|---|
| 步骤编排 | `DAGEngine` — DAG 拓扑排序 + 条件分支 + 并行执行 |
| 状态流转 | `ExecutionContext` — pending→running→completed→failed |
| 长任务管理 | `Scheduler` + `SmartSchedulerConfig` + DAGEngine scheduler 集成 |
| Agent 注册与调度 | `AgentRegistry` + `AgentType` 6 种角色 |
| Pipeline 编排 | Analyst→Coder→Validator→Committer 四步流水线 |
| 模块间通信 | `EventBus` — 解耦的事件驱动 |

✅ **NegotiationEngine 已被 DAGEngine 集成**：并行层执行完后调用 `_negotiate_conflicts()`，支持三种解决策略：merge / escalate / debate。

✅ **DowngradeEngine 已被 DAGEngine 集成**：超时降级 `_try_downgrade`，Gate 超时后可以自动降级。

---

### 4. Verify（验证） ✅ 完整实现

| 方法论要求 | 项目实现 |
|---|---|
| 结果检查 | `GateEngine` — 每个节点完成后过 Gate |
| 自动化评估 | `GateMode` 三级 — STRICT/HYBRID/LOOSE |
| 合规扫描 | `ComplianceEngine` + 5 大 RulePack |
| 护栏检测 | `GuardrailsPair` — 输入/输出 PII + 安全 |
| 变更验证 | 多种 Validator 类型 |
| 审计链 | `AuditStore` + `verify_audit_chain()` — 不可篡改审计 |
| Hook 实时检查 | 6 个 Hook（合规扫描/PII/输入护栏/会话初始化/任务审计/写前门禁） |

**超越点**：Gate 三级模式是方法论只说"验证"但没说的——验证的严格程度应该是可配置的。Hook 机制把验证嵌入了 Agent 的工具调用生命周期，是**实时拦截**而非事后验证。

---

### 5. Correct（纠正） ✅ 模块完整 ✅ Learning 反馈闭环已接通

| 方法论要求 | 项目实现 |
|---|---|
| 失败重试 | `RetryStrategy` + Gate 的 `max_retries` |
| 自动修复 | `auto_fixable` 检查项 + HYBRID 模式自动修复重试 |
| 回滚 | `RollbackEngine` — 快照+SHA-256+自动恢复 |
| 升级人工 | `GateManager` + `GateApprovalRecord` |
| 降级策略 | `DowngradeEngine` / `DowngradePolicy` |
| 自学习纠正 | `PatternMiner` + `AntiPatternDetector` + `PredictionCalibrator` |

**超越点**：方法论只说了"失败重试、回滚"，我们做到了**分层纠正**：自动修复（Gate HYBRID）→ 降级（DowngradeEngine）→ 升级人工（GateManager）→ 回滚（RollbackEngine），四层递进。

✅ **Learning → Gate/Scheduler/Knowledge 反馈闭环全部接通**

---

## 方法论没覆盖但项目实现了的（额外创新）

| 能力 | 实现模块 | 意义 |
|---|---|---|
| **TaskSpec（任务验收契约）** | `types.py` + `engine.py` | 正面定义"做完应该是什么样子" |
| **Learning → RulePack 闭环** | `learning.py` + `compliance_engine.py` | 反模式→推荐→注册规则→下次生效 |
| **Profile 分级部署** | `basic.yaml` / `default.yaml` / `enterprise.yaml` | 控制强度可切换 |
| **Bridge 适配器** | `HarnessBridge` + `ClaudeCodeAdapter` | 一键部署到 Agent 平台 |
| **MCP Server** | MCP Python SDK 官方实现 | 任何 MCP 客户端都能用 Harness 的能力 |
| **Skill 注册表** | `SkillRegistry` + `SkillSlotName` | Hook/Skill/Gate 的统一管理 |
| **谈判机制** | `negotiation.py` | 多 Agent 并行修改冲突时协商 |
| **声明式规则注册** | `declarative_rules.py` | YAML 声明合规规则 |

---

## 一句话

方法论是"怎么驾驭烈马的原则"，harness-cook 是我们给马做的那套定制马具——马具的部件精度超过了原则本身的要求。

# Harness Engineering 与 harness-cook：让 AI Agent 真正可控

> 为什么 Prompt Engineering 不够？为什么需要 Harness Engineering？harness-cook 如何实现？

---

## 背景：从 Prompt Engineering 到 Harness Engineering

2025–2026 年，AI Agent 工程领域发生了一次范式转变：

**Prompt Engineering 时代的局限**：靠写提示词让 AI Agent "听话"——但 Prompt 是软性的、不强制、不闭环、不可审计。Agent 想绕过约束？改一句话就行。出了问题？事后查日志，没有系统化的纠正机制。

**Harness Engineering 的回答**：不能只靠 Prompt，要把"约束、信息、工具、验证、纠错、记忆、状态管理"全部**工程化、系统化、闭环化**，才能让 Agent 长期可靠干活。

这不是一个新框架的营销话术——这是一个工程事实：**没有结构化运行时控制的 Agent，就像没有缰绳的马——有力气但没有方向。**

---

## Harness Engineering 方法论核心

### 五大原则（CIVC + Correct）

| 原则 | 含义 | 对应的控制维度 |
|------|------|----------------|
| **Constrain** | 约束——权限、资源限制、操作白名单 | Agent 能做什么？不能做什么？ |
| **Inform** | 告知——给对的上下文、代码图谱、知识库 | Agent 知道什么？不知道什么？ |
| **Execute/Orchestrate** | 执行编排——步骤编排、状态流转 | Agent 按什么顺序做？ |
| **Verify** | 验证——结果检查、评审、自动化评估 | Agent 做完的东西对不对？ |
| **Correct** | 纠正——失败重试、回滚、自动修复 | Agent 出错了怎么恢复？ |

### 六大运行时组件

| 组件 | 作用 | 为什么不能省 |
|------|------|-------------|
| **Spec** | 任务验收契约——"做完应该是什么样子" | 没有 Spec，Gate 检查没有锚点 |
| **Rule** | 合规规则——持续扫描产出物 | 没有 Rule，安全/质量违规无法系统化发现 |
| **Skill** | 可插拔的能力单元——标准化的流程节点 | 没有 Skill，每个项目都要从零造流程 |
| **Workflow** | DAG 工作流——编排多 Agent 协作 | 没有 Workflow，Agent 之间没有协作秩序 |
| **Gate** | 门禁检查——质量/安全的硬性关卡 | 没有 Gate，"做完" ≠ "做对了" |
| **Feedback** | 反馈闭环——学习驱动迭代 | 没有 Feedback，系统不会越用越好 |

### 三层架构

| 层 | 作用 | 关键设计 |
|-----|------|---------|
| **Tool Layer** | Agent 可以用的工具 | 白名单 + 权限边界 |
| **Process Layer** | Agent 执行的流程 | Spec + Rule + Skill + Workflow + Gate + Feedback |
| **Organization Layer** | 人类如何管理 Agent | Profile（分级配置） + Audit（审计链） |

---

## harness-cook 的架构设计思想

### 核心定位

**harness-cook 是 Harness Engineering 的完整实现**——不是理论对照，不是概念映射，是可运行的、闭环接通的、生产级代码。

一句话定位：**为 AI Agent 系上缰绳，让 Agent 有力且有方向。**

### 五层架构

harness-cook 在方法论三层架构的基础上，细化为五层：

| 层 | 核心模块 | 对应方法论原则 |
|-----|---------|---------------|
| **Access Layer** | `ClaudeCodeAdapter`, `Bridge`, `Hooks` | Inform（接入 Agent） |
| **Dispatch Layer** | `DAGEngine`, `SmartScheduler` | Execute（编排执行） |
| **Control Layer** | `Gate`, `Compliance`, `Constraints`, `TaskSpec` | Constrain + Verify |
| **Communication Layer** | `EventBus`, `MCP Server`, `Dashboard` | 可观测性 |
| **Memory Layer** | `Audit`, `Learning`, `Knowledge`, `Profile` | Correct + Feedback |

### 关键设计决策

1. **Contract First（契约先行）**：所有模块先定义类型契约（`types.py`），再写实现。契约是对上下游的承诺，实现是对契约的兑现。

2. **EventBus 为通信中枢**：所有模块间通信通过 `EventBus`，不走直接调用。好处：模块可独立替换、事件可审计、下游可订阅。

3. **Profile 为分级入口**：`basic` / `default` / `enterprise` 三级配置，切换 Profile 即切换整套行为模式（Gate 模式、Hooks、Pipeline、Constraints）。

4. **闭环是硬性要求**：每条功能链必须闭环——Constraints→validate→拦截→事件→Learning→RulePack→下次生效。不是声明式，是运行时强制闭环。

---

## 超越方法论的创新点

harness-cook 不仅覆盖了 Harness Engineering 方法论，还在以下维度有创新：

### 1. TaskSpec（任务验收契约）——方法论没提，我们补上了

方法论的 Spec 只说了"Agent 理解任务"，没有说"做完应该是什么样子"。我们加了 `TaskSpec`：

- `objective`：任务目标
- `acceptance_criteria`：验收标准列表
- `input_schema` / `output_schema`：输入输出格式约束
- `timeout_seconds` / `max_retries`：时间和重试约束

**核心区别**：Constraints 是"不能做什么"（负面定义），TaskSpec 是"做完应该是什么样子"（正面定义）。两者互补，缺一不可。

### 2. Learning → RulePack 闭环——从 Feedback 到 Rule 的自动迭代

方法论的 Feedback 只说"调整阈值"，我们做了更激进的事：

- AntiPatternDetector 检测到反模式 → 发射 `type="rule"` 的 Recommendation
- ComplianceEngine 收到 → 自动注册到 `learned-rules` 包
- **下次扫描新规则生效——系统越用越严格**

这不是调阈值，是**规则的自动生长**。

### 3. 审计链不可篡改——方法论没提，我们做了

方法论的 Organization Layer 只说了"管理 Agent"，我们做了不可篡改的审计链：

- 每个操作记录为链式结构（`AuditChain`）
- `verify_chain()` 验证完整性——任何篡改都能检测
- 损坏文件标记为 `_corrupted`，链断裂时标记

这是**合规底线**——你无法证明你做过什么，就无法证明你合规。

### 4. Profile 分级部署——方法论没提，我们做了

方法论没有区分"个人项目"和"企业项目"应该有不同的控制强度。我们做了：

- `basic.yaml`：LOOSE + 最少 hooks + 3步 pipeline
- `enterprise.yaml`：STRICT + 全 hooks + 5步 pipeline + 严格约束

一个 YAML 切换，整套行为模式就变了。

---

**harness-cook：为 AI Agent 系上缰绳，让 Agent 有力且有方向。**

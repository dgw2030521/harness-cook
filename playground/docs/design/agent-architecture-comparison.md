# Harness-Cook 与 AI Agent 架构的机制对比分析

> 核心结论：两者存在大量结构性相似，但设计动机不同——harness-cook 是"用 Agent 架构来治理代码生产"，AI Agent 是"用 Agent 架构来执行任务"。

## 一、核心相似机制一览

| AI Agent 架构机制 | Harness-Cook 对应机制 | 相似度 |
|---|---|---|
| **感知（Perceive）** | Guardrails 输入护栏 `check_input` | ★★★★ |
| **推理（Reason）** | ComplianceEngine 规则扫描 + AuditEngine 决策记录 | ★★★ |
| **执行（Execute）** | DAG Engine 拓扑排序 → Agent 逐步执行 | ★★★★★ |
| **记忆（Remember）** | AuditEngine + AuditStore 审计日志持久化 | ★★★★ |
| **协作（Collaborate）** | Pipeline：Analyst→Coder→Validator→Committer | ★★★★★ |
| **自治（Self-Drive）** | Skill Slot 自动触发 + Learning→RulePack 闭环 | ★★★ |
| **约束/安全边界** | Gate 门禁系统（strict/hybrid/loose 三档） | ★★★★★ |

## 二、逐层深度对比

### 1. 执行循环：最核心的相似点

AI Agent 的核心循环：

```
感知 → 规划 → 执行 → 反思 → 循环
```

Harness-Cook 的 Pipeline 循环：

```
Analyst(分析) → Coder(编码) → Validator(验证) → Committer(提交) → Gate(门禁检查)
```

**本质相同**：都是多阶段串行流水线，每个阶段有明确的输入/输出契约。

### 2. 护栏系统 = Agent 的安全感知层

```python
pair.check_input(content)   # 感知输入是否安全
pair.check_output(content)  # 感知输出是否合规
```

### 3. Gate 门禁 = Agent 的反思/自检机制

三档模式（strict/hybrid/loose）对应了 Agent 在不同场景下的"反思强度"：
- **strict** → 每步必须自检通过，等于 Agent 的"强制反思"
- **hybrid** → 关键节点自检，等于 Agent 的"选择性反思"
- **loose** → 信任执行结果，等于 Agent 的"无反思直接行动"

### 4. EventBus = Agent 的内部消息总线

各引擎（审计、合规、护栏）都订阅 Bus 事件，形成松耦合的事件驱动架构——这就是 Agent 内部的"感知-响应"模式。

### 5. Skill Slot = Agent 的 Hook/Plugin 机制

```python
SkillSlotName.PRE_EXECUTE   # 执行前
SkillSlotName.POST_EXECUTE  # 执行后
SkillSlotName.ON_GATE_PASS  # 门禁通过时
SkillSlotName.ON_GATE_FAIL  # 门禁失败时
SkillSlotName.ON_ERROR      # 错误时
```

### 6. Profile + Overlay = Agent 的角色配置 + 行为调节

- **Profile** = 角色（senior-dev、qa、security-reviewer、legal-reviewer）
- **Overlay** = 行为强度调节（strict/hybrid/loose）

**叠加而非替换**——这比很多 Agent 系统做得更精细。

## 三、关键差异

| 维度 | AI Agent 架构 | Harness-Cook |
|---|---|---|
| **设计目标** | 执行任务、完成目标 | **治理**代码生产过程 |
| **推理方式** | LLM 自由推理 | **规则驱动**的合规引擎 |
| **记忆类型** | 对话记忆 + 长期记忆 | **审计日志**（只记决策和行动） |
| **自治程度** | 可完全自治（Self-Drive） | **人机协作**（升级/escalation 机制） |
| **错误恢复** | 反思→重试 | **回滚引擎**（RollbackEngine） + 自动修复 |

## 四、核心洞察

1. **Agent 架构是骨架，治理逻辑是灵魂** — harness-cook 复用了 Agent 架构的所有结构要素，但填入的是"合规规则"而非"自由推理"
2. **Gate = 反思的强制化** — AI Agent 的反思是可选的、启发式的；harness-cook 的 Gate 是强制的、规则驱动的、有三档强度的
3. **Audit = 不可篡改的记忆** — 比对话记忆更严格，是决策的审计证据链
4. **Profile + Overlay = 角色分级** — 比 Agent 的单一角色配置更精细，支持角色 + 行为强度的二维叠加

这种设计让 harness-cook 兼具 Agent 的灵活性（DAG 编排、Skill 扩展）和治理的确定性（规则引擎、门禁强制），是一个非常巧妙的架构选择。

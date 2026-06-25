# @harness_agent 装饰器

> harness-cook 的「**一键接入**」——@harness_agent 装饰器让任意函数秒入 Harness 管控

**快速导航**：[📖 原理（本页）](#原理) · [🎓 使用方法](/tutorial/basic-usage) · [🏃 可运行 Demo](/demo/complete-workflow)

---

## 原理

### 装饰器注册

`@harness_agent` 自动将函数注册到 AgentRegistry——无需手动调用 `register_agent()`，一个装饰器即完成注册+约束绑定+事件发布。

### 约束绑定

装饰器参数绑定 AgentConstraints，执行前后自动检查约束（文件模式、变更数量、破坏性操作等）。

### 事件发布

注册时自动发布 `agent.registered` 事件到 EventBus，其他模块可监听此事件获取 Agent 信息。

### 执行流程

1. **pre-check**——约束验证（AgentConstraints 检查）
2. **调用原始函数**——执行用户定义的函数体
3. **post-check**——产出验证（约束+Gate 检查）

### token 估算

constraints.max_tokens 直接指定 token 上限；未指定时启发式估算 `len(task) * 4 + 500`。

```python
from harness.decorators import harness_agent
from harness.constraints import AgentConstraints

@harness_agent(
    name="code-reviewer",
    capabilities=["perceive", "reason"],
    constraints=AgentConstraints(
        max_changes=50,
        destructive_blocked=True,
    ),
    gate_mode="hybrid",
    toolsets=["read", "grep"],
)
def review_code(task: str, context: dict) -> dict:
    return {"findings": [], "approved": True}
```

### 核心概念

| 类/函数 | 职责 |
|---------|------|
| harness_agent() | 装饰器——注册+约束+事件 |
| DecoratedAgent | 被装饰后的 Agent 对象 |
| HarnessAgentConfig | Agent 配置（name/capabilities/constraints/gate_mode） |

### 装饰流程

```mermaid
flowchart TD
    A[@harness_agent 装饰] --> B[注册到 AgentRegistry]
    B --> C[发布 agent.registered 事件]
    C --> D[调用函数时]
    D --> E[pre-check 约束验证]
    E -->|通过| F[执行原始函数]
    F --> G[post-check 约束验证]
    E -->|不通过| H[阻断执行]
```

<details>
<summary>ASCII 原图</summary>

```
@harness_agent 装饰 → 注册到 AgentRegistry → 发布 agent.registered 事件
→ 调用函数时 → pre-check 约束验证
  → 通过 → 执行原始函数 → post-check 约束验证
  → 不通过 → 阻断执行
```
</details>

### 与 Agents 模块协作

| 协作模块 | 方式 |
|----------|------|
| AgentRegistry | 注册装饰后的 Agent |
| EventBus | 发布 agent.registered 事件 |
| AgentConstraints | 执行前后约束检查 |
| GateEngine | post-check 时 Gate 检查 |

---

## 配置

### Profile YAML 配置

```yaml
decorators:
  default_gate_mode: hybrid     # 默认门禁模式
  auto_register: true           # 自动注册到 AgentRegistry
  publish_event: true           # 发布 agent.registered 事件
```

---

更多配置细节见 [基础用法教程](/tutorial/basic-usage)，可运行 Demo 见 [完整工作流 Demo](/demo/complete-workflow)。
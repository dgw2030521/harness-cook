# 基础用法

本教程带你从零创建一个 Harness Agent——定义它、注册它、运行它。

## Step 1: 创建 Agent 定义

每个 Agent 需要一份「身份证」—— `AgentDefinition`：

```python
from harness.types import AgentDefinition, AgentCapability, AgentType

analyst_def = AgentDefinition(
    id="analyst",
    name="需求分析师",
    capabilities=[AgentCapability.PERCEIVE, AgentCapability.REASON],
    agent_type=AgentType.ANALYST,
    toolsets=["terminal", "file"],
    system_prompt="你是一个专业的需求分析师。",
)
```

关键字段说明：

- **id** —— Agent 唯一标识，DAGNode 通过 `agent_type` 引用此 ID
- **capabilities** —— Agent 能力声明（perceive/reason/execute/remember/collaborate/self_drive）
- **agent_type** —— Agent 角色（analyst/planner/coder/reviewer/validator/committer）
- **toolsets** —— Agent 可用工具集

## Step 2: 实现 Agent 执行逻辑

`IExecutableAgent` protocol 要求两个方法：`execute()` 和 `estimate_tokens()`：

```python
from harness.types import TaskResult, Artifact

class AnalystAgent:
    """分析师 Agent 实现"""

    def execute(self, task: str, context: dict) -> TaskResult:
        return TaskResult(
            task_id=context.get("task_id", "t-001"),
            agent_id="analyst",
            status="completed",
            artifacts=[
                Artifact(
                    type="doc",
                    path="analysis.md",
                    content="# 分析报告\n\n核心需求已梳理完毕。",
                ),
            ],
            duration_ms=200,
            tokens_used=300,
        )

    def estimate_tokens(self, task: str) -> int:
        return len(task) * 4 + 500
```

## Step 3: 注册到 Registry

```python
from harness.registry import AgentRegistry
from harness.bus import EventBus

bus = EventBus()
registry = AgentRegistry(bus=bus)

registry.register(analyst_def, AnalystAgent())

# 检查注册状态
stats = registry.stats()
print(f"已注册: {stats['total_agents']}, 就绪: {stats['ready_agents']}")
```

## Step 4: 使用装饰器接入

更简洁的方式——`@harness_agent` 一行装饰器自动注册到全局 Registry：

```python
from harness.decorators import harness_agent
from harness.types import AgentCapability, TaskResult, Artifact
from harness.constraints import AgentConstraints, AgentPriority

@harness_agent(
    name="快速分析师",
    capabilities=[AgentCapability.REASON],
    constraints=AgentConstraints(
        priority=AgentPriority.HIGH,
        max_changes=5,
        no_destructive=True,
    ),
    agent_type=AgentType.ANALYST,
)
def quick_analyst(task: str, context: dict) -> TaskResult:
    return TaskResult(
        task_id=context.get("task_id", "t-002"),
        agent_id="quick_analyst",
        status="completed",
        artifacts=[Artifact(type="doc", path="quick.md", content="快速分析完成")],
        duration_ms=50,
        tokens_used=100,
    )
```

::: tip
装饰器使用全局 Registry，适合单进程场景。独立 Registry（手动注册）适合测试和需要隔离的场景。
:::

## Step 5: Agent 约束配置

`AgentConstraints` 为 Agent 设定行为边界：

```python
from harness.constraints import AgentConstraints, AgentPriority

constraints = AgentConstraints(
    priority=AgentPriority.HIGH,      # 调度优先级
    max_changes=10,                    # 单次最大改动数
    no_destructive=True,              # 禁止破坏性操作
    file_patterns=["src/**/*.py"],    # 允许操作的文件范围
    require_review=True,              # 改动需人工审批
    cooldown_seconds=30,              # 执行间隔冷却
)
```

约束在 DAGEngine 执行时自动生效——超过 `max_changes` 的改动被拦截，破坏性操作直接拒绝。

## 完整示例

将上述步骤合并为一个可运行脚本：

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "packages/core"))

from harness.types import *
from harness.registry import AgentRegistry
from harness.bus import EventBus
from harness.decorators import harness_agent

bus = EventBus()
registry = AgentRegistry(bus=bus)

analyst_def = AgentDefinition(
    id="analyst", name="分析师",
    capabilities=[AgentCapability.REASON],
    agent_type=AgentType.ANALYST,
)

class AnalystImpl:
    def execute(self, task, context):
        return TaskResult(task_id="t-001", agent_id="analyst", status="completed",
                          artifacts=[Artifact(type="doc", path="report.md",
                                               content="分析完成")],
                          duration_ms=100, tokens_used=200)
    def estimate_tokens(self, task):
        return len(task) * 4

registry.register(analyst_def, AnalystImpl())
print(f"注册成功: {registry.stats()['total_agents']} agents")
```

下一步 → [合规扫描](./compliance-scan)
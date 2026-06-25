# Pipeline 编排

本教程展示如何使用 harness-cook 的 Pipeline 功能编排 analyst→coder→validator→committer 四步流水线，配置门禁模式、指定工作目录、查询执行状态和设置重试策略。

## Step 1: 理解 Pipeline 流程

Pipeline 是一个预定义的四步线性流水线，每步由一个专职 Agent 执行，并有对应的门禁检查：

| 步骤 | Agent 角色 | 任务 | 门禁检查项 |
|------|-----------|------|-----------|
| 1 | `analyst` | 分析任务需求，拆解子任务，识别约束和风险 | `requirements_completeness`, `risk_identified` |
| 2 | `coder` | 根据分析结果编写代码/配置变更 | `code_syntax`, `no_hardcoded_secrets`, `follows_project_style` |
| 3 | `validator` | 验证代码变更：语法检查、合规扫描、门禁审查 | `all_syntax_pass`, `no_compliance_violations`, `tests_pass` |
| 4 | `committer` | 生成 commit 信息，整理变更摘要 | `commit_message_format`, `no_sensitive_data_in_diff` |

步骤之间有严格顺序依赖——analyst 的分析结果传递给 coder，coder 的代码变更传递给 validator，validator 的审查结果传递给 committer。

## Step 2: 通过 MCP 工具启动 Pipeline

最常见的方式是通过 MCP 工具 `harness_pipeline_run` 启动 Pipeline：

```json
{
  "task": "为用户登录功能添加 JWT token 验证中间件",
  "gate_mode": "hybrid",
  "working_directory": "/path/to/project",
  "max_retries": 2
}
```

参数说明：

- **task**（必填）—— Pipeline 要执行的任务描述
- **gate_mode** —— 门禁严格度，三档可选
- **working_directory** —— 项目工作目录，默认当前目录
- **max_retries** —— 门禁失败时最大重试次数，默认 2
- **agents** —— 自定义 Agent 序列，默认 `["analyst", "coder", "validator", "committer"]`

返回值是一个 `PipelineDefinition`——包含步骤定义和编排指令，由 Agent 平台（如 Claude Code）按步骤编排执行：

```json
{
  "success": true,
  "pipeline_id": "pipeline-20260615143000",
  "task": "为用户登录功能添加 JWT token 验证中间件",
  "agents": ["analyst", "coder", "validator", "committer"],
  "gate_mode": "hybrid",
  "max_retries": 2,
  "working_directory": "/path/to/project",
  "steps": [
    {
      "agent": "analyst",
      "task": "分析任务需求，拆解为子任务，识别约束和风险",
      "gate_checks": ["requirements_completeness", "risk_identified"]
    },
    {
      "agent": "coder",
      "task": "根据分析结果编写代码/配置变更",
      "gate_checks": ["code_syntax", "no_hardcoded_secrets", "follows_project_style"]
    },
    {
      "agent": "validator",
      "task": "验证代码变更：语法检查、合规扫描、门禁审查",
      "gate_checks": ["all_syntax_pass", "no_compliance_violations", "tests_pass"]
    },
    {
      "agent": "committer",
      "task": "生成 commit 信息，整理变更摘要",
      "gate_checks": ["commit_message_format", "no_sensitive_data_in_diff"]
    }
  ],
  "instruction": "Claude Code 收到此 PipelineDefinition 后，应使用 Workflow/Agent 工具编排执行..."
}
```

::: tip
`harness_pipeline_run` 返回的是编排计划（`PipelineDefinition`），不是直接执行结果。MCP Server 进程无法直接 spawn subagent，编排执行由 Agent 平台完成。
:::

## Step 3: gate_mode 三档配置

三档门禁模式定义见 [门禁层原理](/guide/gate-layer#三档门禁模式)。Pipeline 中通过 `gate_mode` 参数指定：

```python
from harness.types import GateMode

# 推荐：hybrid 模式——关键违规阻断，低级别记录
gate_mode = GateMode.HYBRID

# 安全审计场景：零容忍
gate_mode = GateMode.STRICT

# 探索性开发：宽松模式
gate_mode = GateMode.LOOSE
```

每个步骤完成后，Pipeline 使用 `harness_check` 和 `harness_gate_create` 执行门禁检查。`gate_mode` 决定检查失败时的行为——阻断还是放行。

## Step 4: 自定义 Agent 序列

默认四步序列是 `analyst→coder→validator→committer`，你可以通过 `agents` 参数自定义：

```json
{
  "task": "快速修复登录页面的 CSS 问题",
  "agents": ["coder", "validator"],
  "gate_mode": "loose",
  "max_retries": 1
}
```

跳过 analyst 和 committer，直接从 coder 开始——适合小修复场景。

也可以只保留验证步骤：

```json
{
  "task": "审查现有代码的安全合规性",
  "agents": ["validator"],
  "gate_mode": "strict"
}
```

::: warning
自定义 Agent 序列时，步骤间仍保持线性顺序依赖。`analyst→coder→validator→committer` 的默认序列经过实践验证，修改序列可能影响任务完成质量。
:::

## Step 5: 查询 Pipeline 状态

使用 `harness_pipeline_status` 查询 Pipeline 的配置和可用信息：

```json
// 调用 harness_pipeline_status
{
  "available": true,
  "default_agents": ["analyst", "coder", "validator", "committer"],
  "gate_modes": ["strict", "hybrid", "loose"],
  "default_gate_mode": "hybrid",
  "default_max_retries": 2,
  "note": "Use harness_pipeline_run to start a pipeline. Status is returned in the run result..."
}
```

::: tip
MCP Server 不持久化 Pipeline 执行状态。`harness_pipeline_run` 的返回值包含了完整的步骤定义和编排指令，Agent 平台自行跟踪执行进度。如需查看历史执行记录，使用 `harness_audit` 搜索审计日志。
:::

## Step 6: 重试策略

当某步骤的门禁检查未通过时，Pipeline 按 `max_retries` 参数重试：

```python
from harness.types import RetryStrategy

retry = RetryStrategy(
    max_retries=3,           # 最大重试次数
    backoff_seconds=2.0,     # 退避间隔（2→4→8 秒指数递增）
    escalate_on_fail=True,   # 重试耗尽后升级人工
)
```

重试流程：

1. 步骤执行 → 门禁检查失败
2. 等待退避间隔（指数递增）
3. 重新执行步骤 → 再次门禁检查
4. 重试耗尽 → `escalate_on_fail=True` 时升级人工

## Step 7: 与 DAGEngine 集成

Pipeline 内部使用 `DAGEngine` 执行线性 DAG 工作流。你也可以直接用 DAGEngine 模拟 Pipeline 行为：

```python
from harness.engine import DAGEngine
from harness.registry import AgentRegistry
from harness.gates import GateEngine
from harness.bus import EventBus
from harness.types import DAGNode, DAGEdge, DAGWorkflow, GateMode

bus = EventBus()
registry = AgentRegistry(bus=bus)
gate_engine = GateEngine(bus=bus)
engine = DAGEngine(registry=registry, gate_engine=gate_engine, bus=bus)

# 构建 Pipeline 对应的 DAG
workflow = DAGWorkflow(
    id="wf-pipeline-manual",
    name="手动构建的 Pipeline",
    nodes=[
        DAGNode(id="analyze", agent_type="analyst", task="分析需求",
                gate=GateDefinition(id="gate-analyze", mode=GateMode.HYBRID, checks=[])),
        DAGNode(id="code", agent_type="coder", task="编写代码",
                gate=GateDefinition(id="gate-code", mode=GateMode.HYBRID, checks=[])),
        DAGNode(id="verify", agent_type="validator", task="验证代码",
                gate=GateDefinition(id="gate-verify", mode=GateMode.HYBRID, checks=[])),
        DAGNode(id="commit", agent_type="committer", task="提交变更",
                gate=GateDefinition(id="gate-commit", mode=GateMode.HYBRID, checks=[])),
    ],
    edges=[
        DAGEdge(from_node="analyze", to_node="code"),
        DAGEdge(from_node="code", to_node="verify"),
        DAGEdge(from_node="verify", to_node="commit"),
    ],
)

# 执行
context = engine.execute(workflow)
print(f"成功节点: {list(context.completed_nodes)}")
print(f"失败节点: {list(context.failed_nodes)}")
print(f"升级人工: {context.escalated}")
```

## Step 8: 完整 Pipeline 调用示例

通过 MCP 工具调用完整 Pipeline：

```json
// 1. 启动 Pipeline
harness_pipeline_run({
  "task": "为 Express.js 项目添加请求速率限制中间件",
  "gate_mode": "hybrid",
  "working_directory": "/projects/my-api",
  "max_retries": 2
})
// → 返回 PipelineDefinition，包含 4 个步骤定义

// 2. 查询可用 Agent
harness_agent_list({})
// → 列出 analyst/coder/validator/committer 的工具白名单和系统提示词

// 3. 查询 Pipeline 配置
harness_pipeline_status({})
// → 返回默认参数和可用选项

// 4. 审计 Pipeline 执行记录
harness_audit({ "query": "pipeline", "limit": 20 })
// → 搜索审计日志中的 Pipeline 执行记录
```

下一步 → [降级与回滚](./downgrade-rollback) | [Adapter 部署](./adapter-deployment)

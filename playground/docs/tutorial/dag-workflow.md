# DAG 工作流

本教程展示如何定义 DAG 节点和边、构建工作流、执行并跟踪结果。

## Step 1: 定义 DAG 节点

每个 DAGNode 代表一个 Agent 执行步骤：

```python
from harness.types import DAGNode

node_analyze = DAGNode(
    id="analyze",
    agent_type="analyst",       # 引用 AgentDefinition.id
    task="分析用户登录功能需求",
    inputs=[],                  # 入口节点，无上游输入
    outputs=["code"],           # 标注输出（不影响拓扑）
)

node_code = DAGNode(
    id="code",
    agent_type="coder",
    task="根据分析报告实现登录代码",
    inputs=[],
    outputs=["verify"],
)

node_verify = DAGNode(
    id="verify",
    agent_type="validator",
    task="验证代码安全性与合规性",
    inputs=[],
    outputs=[],                 # 终止节点
)
```

::: warning
`agent_type` 必须与 AgentDefinition 的 `id` 一致。如果 Registry 中没有对应 Agent，执行时会报错。
:::

## Step 2: 定义 DAG 边

DAGEdge 声明节点间的依赖关系和条件：

```python
from harness.types import DAGEdge

edge_1 = DAGEdge(from_node="analyze", to_node="code")
edge_2 = DAGEdge(from_node="code", to_node="verify")
```

**字段名是 `from_node` 和 `to_node`**，不是 `source`/`target`。

可选的 `condition` 字段用于条件分支：

```python
edge_conditional = DAGEdge(
    from_node="analyze",
    to_node="code",
    condition="analysis_passed",   # 当上游产出满足条件时才走这条边
)
```

## Step 3: 组装工作流

```python
from harness.types import DAGWorkflow

workflow = DAGWorkflow(
    id="wf-login-feature",
    name="用户登录功能开发",
    description="从需求分析到代码实现再到验证的完整流程",
    nodes=[node_analyze, node_code, node_verify],
    edges=[edge_1, edge_2],
)
```

## Step 4: 拓扑排序（规划阶段）

DAGEngine 先计算拓扑排序，确定执行顺序：

```python
from harness.engine import DAGEngine
from harness.registry import AgentRegistry
from harness.bus import EventBus

bus = EventBus()
registry = AgentRegistry(bus=bus)
engine = DAGEngine(registry=registry, bus=bus)

# 规划——仅看执行顺序，不实际执行
order = engine.plan(workflow)
print(f"执行顺序: {order}")   # → ["analyze", "code", "verify"]
```

`plan()` 返回节点 ID 的拓扑排序列表，只做依赖分析，不调用任何 Agent。

## Step 5: 执行工作流

```python
# 实际执行——按拓扑顺序调用 Agent
context = engine.execute(workflow)
```

`execute()` 返回 `ExecutionContext`，包含完整执行结果：

| 字段 | 含义 |
|------|------|
| `execution_id` | 执行唯一标识 |
| `workflow_id` | 工作流 ID |
| `duration_ms` | 总耗时（毫秒） |
| `node_status` | 各节点状态 dict |
| `completed_nodes` | 成功完成的节点集合 |
| `failed_nodes` | 失败的节点集合 |
| `node_artifacts` | 各节点产出物 dict |
| `escalated` | 是否升级人工 |

## Step 6: 查看执行结果

```python
# 总览
print(f"执行ID: {context.execution_id}")
print(f"耗时: {context.duration_ms}ms")
print(f"成功: {list(context.completed_nodes)}")
print(f"失败: {list(context.failed_nodes)}")
print(f"升级: {context.escalated}")

# 各节点产出物
for node_id, artifacts in context.node_artifacts.items():
    print(f"\n[{node_id}]")
    for art in artifacts:
        print(f"  type={art.type}, path={art.path}")
        preview = art.content[:80].replace("\n", " ")
        print(f"  preview: {preview}...")
```

## Step 7: 并行节点

当多个节点之间没有依赖关系，DAGEngine 自动并行调度：

```python
# analyze 完成后，code 和 review 可以并行
workflow = DAGWorkflow(
    id="wf-parallel",
    nodes=[
        DAGNode(id="analyze", agent_type="analyst", task="分析需求"),
        DAGNode(id="code", agent_type="coder", task="实现代码"),
        DAGNode(id="review", agent_type="reviewer", task="审查设计"),
        DAGNode(id="verify", agent_type="validator", task="验证结果"),
    ],
    edges=[
        DAGEdge(from_node="analyze", to_node="code"),
        DAGEdge(from_node="analyze", to_node="review"),   # 两条边从同一源发出
        DAGEdge(from_node="code", to_node="verify"),
        DAGEdge(from_node="review", to_node="verify"),
    ],
)

# plan() 返回顺序中 code 和 review 可能并行
order = engine.plan(workflow)
# → ["analyze", "code", "review", "verify"] 或 ["analyze", "review", "code", "verify"]
```

## Step 8: YAML 定义工作流

CLI 命令支持 YAML/JSON 格式的工作流定义文件：

```yaml
workflow:
  id: wf-login-feature
  name: 用户登录功能开发
  nodes:
    - id: analyze
      agent_type: analyst
      task: 分析需求
    - id: code
      agent_type: coder
      task: 实现代码
    - id: verify
      agent_type: validator
      task: 验证结果
  edges:
    - from_node: analyze
      to_node: code
    - from_node: code
      to_node: verify
```

通过 CLI 运行：`python3 -m cli_commands run workflow.yaml`

下一步 → [MCP 集成](./mcp-integration)
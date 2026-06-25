# DAG 工作流 Demo

> 跑起来看看 DAG 工作流的节点/边定义、拓扑排序执行和结果跟踪。

## 前置

```bash
cd harness-cook/packages/core
PYTHONPATH=. python3 -c "from harness.engine import DAGEngine; print('✅ OK')"
```

---

## Demo：完整 DAG 工作流

```python
from harness.engine import DAGEngine
from harness.registry import AgentRegistry
from harness.types import DAGWorkflow, DAGNode, DAGEdge
from harness.bus import EventBus

bus = EventBus()
registry = AgentRegistry()
engine = DAGEngine(registry=registry, bus=bus)

# 定义工作流节点
nodes = [
    DAGNode(id="research", agent_type="research", task="Research Agent"),
    DAGNode(id="code", agent_type="code", task="Code Agent"),
    DAGNode(id="review", agent_type="review", task="Review Agent"),
    DAGNode(id="deploy", agent_type="deploy", task="Deploy Agent"),
]

# 定义边（依赖关系）
edges = [
    DAGEdge(from_node="research", to_node="code"),
    DAGEdge(from_node="code", to_node="review"),
    DAGEdge(from_node="review", to_node="deploy"),
]

workflow = DAGWorkflow(id="dev-flow", name="Development Flow", nodes=nodes, edges=edges)

# 执行工作流
context = engine.execute(workflow)

print(f"工作流执行完成")
print(f"节点状态: {context.node_status}")
print(f"完成节点: {list(context.completed_nodes)}")
print(f"失败节点: {list(context.failed_nodes)}")
```

---

## Demo：拓扑排序可视化

```python
from harness.engine import DAGEngine

# 使用 harness_pipeline_run MCP 工具可视化 DAG
workflow_yaml = """
nodes:
  - id: analyst
    type: agent
  - id: coder
    type: agent
  - id: validator
    type: agent
  - id: committer
    type: agent
edges:
  - from_node: analyst
    to_node: coder
  - from_node: coder
    to_node: validator
  - from_node: validator
    to_node: committer
"""

# 通过 MCP 工具调用
# harness_plan(workflow_yaml=workflow_yaml) → 返回拓扑排序结果
```

---

## Demo：MCP 工具调用

```python
from harness_mcp_server import HarnessMCPServer

server = HarnessMCPServer()

# harness_pipeline_run
tool = next(t for t in server._TOOL_DEFINITIONS if t['name'] == 'harness_pipeline_run')
params = list(tool['inputSchema']['properties'].keys())
print(f"harness_pipeline_run 参数: {params}")
# 应包含: task, agents, gate_mode, working_directory

# harness_run
tool2 = next(t for t in server._TOOL_DEFINITIONS if t['name'] == 'harness_run')
params2 = list(tool2['inputSchema']['properties'].keys())
print(f"harness_run 参数: {params2}")
# 应包含: workflow_yaml
```

---

## 相关导航

- 📖 架构原理 → [核心概念](/guide/core-concepts)
- 🎓 使用方法 → [DAG 工作流](/tutorial/dag-workflow)

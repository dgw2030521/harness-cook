"""
harness plan 命令——可视化 DAG 工作流 + 门禁配置

解析工作流定义文件(YAML/JSON)，输出 DAG 拓扑图和门禁配置摘要。

输出格式:
  - tree: 树状拓扑图（默认，最直观）
  - dot: Graphviz DOT 格式（可渲染为图形）
  - json: 原始结构数据（程序化处理）
"""

import json
from pathlib import Path
from datetime import datetime

from harness.types import (
    DAGNode, DAGEdge, DAGWorkflow, GateDefinition, GateMode,
    GateCheck, CheckResult, RetryStrategy, Artifact,
    AgentDefinition, AgentCapability, AgentType,
)

# AgentCapability 值映射——JSON 中的字符串映射到枚举
_CAPABILITY_MAP = {
    "perceive": AgentCapability.PERCEIVE,
    "reason": AgentCapability.REASON,
    "execute": AgentCapability.EXECUTE,
    "remember": AgentCapability.REMEMBER,
    "collaborate": AgentCapability.COLLABORATE,
    "self_drive": AgentCapability.SELF_DRIVE,
    # 兼容常见别名
    "collect": AgentCapability.EXECUTE,
    "analyze": AgentCapability.REASON,
    "generate": AgentCapability.EXECUTE,
    "x": AgentCapability.EXECUTE,
}

# 默认检查函数——从JSON加载时无法提供真实check_fn
def _noop_check(artifact: Artifact) -> CheckResult:
    return CheckResult(passed=True, severity="low", message="No-op check (loaded from JSON)")

def _map_capability(cap_str: str) -> AgentCapability:
    """将字符串映射为 AgentCapability 枚举"""
    lower = cap_str.lower().replace("-", "_").replace(" ", "_")
    if lower in _CAPABILITY_MAP:
        return _CAPABILITY_MAP[lower]
    # 尝试直接构造（如果是枚举值字符串）
    try:
        return AgentCapability(lower)
    except ValueError:
        # 未知能力 → 默认 EXECUTE
        return AgentCapability.EXECUTE


def _load_workflow(filepath: str) -> DAGWorkflow:
    """从 YAML/JSON 文件加载工作流定义"""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"工作流文件不存在: {filepath}")

    content = path.read_text(encoding="utf-8")

    # 尝试解析 JSON
    if path.suffix in (".json",):
        data = json.loads(content)
    else:
        # 尝试 YAML（如果 yaml 可用），否则要求 JSON
        try:
            import yaml
            data = yaml.safe_load(content)
        except ImportError:
            # 没有 yaml 库，只支持 JSON
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                raise ValueError(
                    "无法解析工作流文件。请安装 PyYAML (pip install pyyaml) "
                    "或使用 JSON 格式。"
                )

    # 转换为 DAGWorkflow 对象
    nodes = []
    for n in data.get("nodes", []):
        gate_def = None
        if "gate" in n:
            g = n["gate"]
            checks = []
            for c in g.get("checks", []):
                checks.append(GateCheck(
                    id=c.get("id", ""),
                    category=c.get("category", "style"),
                    severity=c.get("severity", "medium"),
                    description=c.get("description", c.get("name", "")),
                    check_fn=_noop_check,
                    auto_fix_fn=None,  # 从JSON无法加载真实修复函数
                ))
            gate_def = GateDefinition(
                id=g.get("id", ""),
                mode=GateMode(g.get("mode", "hybrid")),
                checks=checks,
                max_retries=g.get("max_retries", 3),
                retry_strategy=RetryStrategy(
                    max_retries=g.get("max_retries", 3),
                    backoff_ms=g.get("backoff_ms", 1000),
                    depth_reduction=g.get("depth_reduction", True),
                    escalation_threshold=g.get("escalation_threshold", 3),
                ),
            )

        # 从 JSON agent 定义映射
        agent_data = n.get("agent", {})
        agent_caps = [_map_capability(c) for c in agent_data.get("capabilities", ["execute"])]
        agent_type_str = n.get("agent_type", agent_data.get("type", None))
        agent_type = None
        if agent_type_str:
            try:
                agent_type = AgentType(agent_type_str)
            except ValueError:
                agent_type = None

        nodes.append(DAGNode(
            id=n.get("id", ""),
            agent_type=agent_data.get("id", n.get("agent_type", "")),
            task=n.get("task", n.get("name", "")),
            inputs=n.get("inputs", []),
            outputs=n.get("outputs", []),
            gate=gate_def,
            metadata=n.get("metadata", {}),
        ))

    edges = []
    for e in data.get("edges", []):
        edges.append(DAGEdge(
            from_node=e.get("from_node", e.get("source", "")),
            to_node=e.get("to_node", e.get("target", "")),
            condition=e.get("condition"),
        ))

    return DAGWorkflow(
        id=data.get("id", path.stem),
        name=data.get("name", path.stem),
        description=data.get("description", ""),
        nodes=nodes,
        edges=edges,
        entry_node=data.get("entry_node", ""),
        exit_nodes=data.get("exit_nodes", []),
    )


def _topological_sort(workflow: DAGWorkflow) -> list:
    """拓扑排序——确定执行顺序"""
    # 构建邻接表
    adj = {n.id: [] for n in workflow.nodes}
    in_degree = {n.id: 0 for n in workflow.nodes}

    for edge in workflow.edges:
        adj[edge.from_node].append(edge.to_node)
        in_degree[edge.to_node] += 1

    # 也考虑 DAGNode.inputs 声明的依赖
    node_map = {n.id: n for n in workflow.nodes}
    for node in workflow.nodes:
        for input_id in node.inputs:
            if input_id in in_degree:
                in_degree[node.id] += 1

    # BFS
    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    order = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for next_node in adj[node]:
            in_degree[next_node] -= 1
            if in_degree[next_node] == 0:
                queue.append(next_node)

    if len(order) != len(workflow.nodes):
        remaining = [n.id for n in workflow.nodes if n.id not in order]
        print(f"警告: DAG 中存在循环依赖，以下节点无法排序: {remaining}")

    return order


def _format_tree(workflow: DAGWorkflow, show_gates: bool) -> str:
    """树状拓扑图输出"""
    lines = []
    lines.append(f"工作流: {workflow.name}")
    lines.append(f"  ID: {workflow.id}")
    if workflow.description:
        lines.append(f"  描述: {workflow.description}")
    lines.append(f"  节点数: {len(workflow.nodes)}")
    lines.append(f"  边数: {len(workflow.edges)}")
    lines.append("")

    # 拓扑顺序
    order = _topological_sort(workflow)
    node_map = {n.id: n for n in workflow.nodes}

    # 构建父子映射（谁是谁的前驱）
    parents = {n.id: [] for n in workflow.nodes}
    for edge in workflow.edges:
        parents[edge.to_node].append(edge.from_node)

    lines.append("DAG 拓扑 (执行顺序):")
    for i, nid in enumerate(order):
        node = node_map[nid]
        prefix = "  " * (len(parents[nid]))
        step_label = f"步骤 {i + 1}"
        lines.append(f"  {step_label}: {prefix}{node.task} ({nid})")

        # 前驱
        if parents[nid]:
            deps = ", ".join(parents[nid])
            lines.append(f"    依赖: {deps}")

        # 后继
        successors = [e.to_node for e in workflow.edges if e.from_node == nid]
        if successors:
            succ_tasks = [node_map[s].task for s in successors if s in node_map]
            lines.append(f"    后继: {', '.join(succ_tasks)}")

        # 门禁配置
        if show_gates and node.gate:
            gate = node.gate
            lines.append(f"    门禁: {gate.mode.value} ({len(gate.checks)} 项检查)")
            for c in gate.checks:
                fix_tag = " [可自动修复]" if c.auto_fix_fn else ""
                lines.append(f"      - {c.description} ({c.severity}{fix_tag})")
            lines.append(f"    最大重试: {gate.max_retries}")

        lines.append("")

    # 检测并行节点（无依赖的节点可以同时执行）
    parallel_groups = []
    visited = set()
    for nid in order:
        if not parents[nid] and nid not in visited:
            # 找所有同层无依赖节点
            group = [n.id for n in workflow.nodes if not parents[n.id] and n.id not in visited]
            if len(group) > 1:
                parallel_groups.append(group)
            visited.update(group)
            break  # 只看第一层

    # 更精确的并行检测
    layers = []
    remaining = set(order)
    processed = set()
    while remaining:
        layer = [nid for nid in remaining if all(p in processed for p in parents[nid])]
        if not layer:
            break
        layers.append(layer)
        processed.update(layer)
        remaining -= set(layer)

    if len(layers) > 1:
        lines.append("并行执行层:")
        for i, layer in enumerate(layers):
            tasks = [node_map[nid].task for nid in layer if nid in node_map]
            lines.append(f"  层 {i + 1}: {', '.join(tasks)}")

    return "\n".join(lines)


def _format_dot(workflow: DAGWorkflow) -> str:
    """Graphviz DOT 格式输出"""
    lines = ["digraph harness_dag {"]
    lines.append("  rankdir=TB;")
    lines.append("  node [shape=box, style=filled, fillcolor=\"#e8f4fd\"];")
    lines.append("")

    for node in workflow.nodes:
        label = f"{node.task}\\n({node.id})"
        if node.gate:
            label += f"\\n[gate: {node.gate.mode.value}]"
        lines.append(f"  \"{node.id}\" [label=\"{label}\"];")

    lines.append("")
    for edge in workflow.edges:
        attrs = ""
        if edge.condition:
            attrs = f" [label=\"{edge.condition}\"]"
        lines.append(f"  \"{edge.from_node}\" -> \"{edge.to_node}\"{attrs};")

    lines.append("}")
    return "\n".join(lines)


def _format_json(workflow: DAGWorkflow) -> str:
    """原始 JSON 输出"""
    data = {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "topological_order": _topological_sort(workflow),
        "nodes": [
            {
                "id": n.id,
                "task": n.task,
                "agent_type": n.agent_type,
                "gate": {
                    "mode": n.gate.mode.value if n.gate else None,
                    "checks": [
                        {"description": c.description, "severity": c.severity, "auto_fixable": c.auto_fix_fn is not None}
                        for c in (n.gate.checks if n.gate else [])
                    ],
                } if n.gate else None,
            }
            for n in workflow.nodes
        ],
        "edges": [
            {"from": e.from_node, "to": e.to_node, "condition": e.condition}
            for e in workflow.edges
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def cmd_plan(args):
    """执行 plan 命令"""
    workflow = _load_workflow(args.workflow)

    # 验证 DAG 基础约束
    node_ids = {n.id for n in workflow.nodes}
    edge_errors = []
    for edge in workflow.edges:
        if edge.from_node not in node_ids:
            edge_errors.append(f"边 {edge.from_node}->{edge.to_node}: source 不存在")
        if edge.to_node not in node_ids:
            edge_errors.append(f"边 {edge.from_node}->{edge.to_node}: target 不存在")

    if edge_errors:
        print("DAG 验证失败:")
        for err in edge_errors:
            print(f"  - {err}")
        return 1

    # 输出
    if args.format == "tree":
        output = _format_tree(workflow, args.show_gates)
    elif args.format == "dot":
        output = _format_dot(workflow)
    elif args.format == "json":
        output = _format_json(workflow)
    else:
        output = _format_tree(workflow, args.show_gates)

    print(output)
    return 0
# plan — 可视化 DAG 工作流

> 解析工作流定义文件，输出 DAG 拓扑图和门禁配置摘要

```bash
# 默认输出树状图
harness plan workflow.yaml

# Graphviz DOT 格式
harness plan workflow.yaml --format dot

# JSON 格式
harness plan workflow.yaml --format json

# 显示门禁配置
harness plan workflow.yaml --show-gates
```

## 参数

| 参数 | 说明 |
|------|------|
| `workflow` | 工作流定义文件 (YAML/JSON) |
| `--format` | 输出格式: tree(树状)/dot(Graphviz)/json(原始) |
| `--show-gates` | 显示每个节点的门禁配置 |

---

← [update](/cli/update) · [命令总览](/cli/) · → [run](/cli/run)

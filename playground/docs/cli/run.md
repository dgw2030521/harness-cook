# run — 执行编排流程

> 加载工作流定义，注册 Agent，执行 DAG 编排

```bash
# 执行工作流
harness run workflow.yaml

# 验证但不执行
harness run workflow.yaml --dry-run

# 严格门禁模式
harness run workflow.yaml --gate-mode strict

# 自定义重试 + 上下文
harness run workflow.yaml --max-retries 3 --context context.json
```

## 参数

| 参数 | 说明 |
|------|------|
| `workflow` | 工作流定义文件 (YAML/JSON) |
| `--dry-run` | 只验证不执行——检查 DAG 是否合法、Agent 是否注册 |
| `--gate-mode` | 门禁模式: strict/hybrid/loose |
| `--max-retries` | 每个节点最大重试次数 |
| `--context` | 初始上下文 JSON 文件 |

---

← [plan](/cli/plan) · [命令总览](/cli/) · → [check](/cli/check)

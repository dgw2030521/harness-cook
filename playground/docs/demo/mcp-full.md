# MCP 工具全量 Demo

> 25 个 MCP 工具定义和调用——harness-cook 在 IDE 中的完整工具集

**定位**：MCP 工具是 harness-cook 在 IDE 中的交互接口——25 个工具覆盖合规检查、审计追踪、工作流编排、门禁管理、注册配置五大领域。

完整可运行脚本见项目 `examples/mcp-full/` 目录（`demo_mcp_full.py`）。

---

## 工具总览

| # | 工具名 | 领域 | 说明 |
|---|--------|------|------|
| 1 | `harness_check` | 合规检查 | 合规扫描——规则包 + 语言路由 |
| 2 | `harness_guardrails_check` | 合规检查 | 护栏检查——PII/安全 |
| 3 | `harness_rule_import` | 合规检查 | 规则导入——SonarQube/ArchUnit/DepCruiser |
| 4 | `harness_audit` | 审计追踪 | 审计搜索——关键词查询 |
| 5 | `harness_trace_export` | 审计追踪 | OTel/Traceloop 导出 |
| 6 | `harness_status` | 审计追踪 | 系统状态聚合 |
| 7 | `harness_plan` | 工作流 | DAG 可视化——拓扑排序 |
| 8 | `harness_run` | 工作流 | DAG 执行 |
| 9 | `harness_pipeline_run` | 工作流 | 编码 Pipeline 执行 |
| 10 | `harness_pipeline_status` | 工作流 | Pipeline 状态查询 |
| 11 | `harness_gate_create` | 门禁 | 门禁定义——检查项 |
| 12 | `harness_register` | 注册 | Agent 注册 |
| 13 | `harness_agent_list` | 注册 | Agent 列表 |
| 14 | `harness_profile_list` | 配置 | Profile 列表 |
| 15 | `harness_profile_load` | 配置 | Profile 加载 + Overlay |
| 16 | `harness_skill_list` | 配置 | Skill 列表 |
| 17 | `harness_skill_register` | 配置 | Skill 注册 |
| 18 | `harness_bridge_deploy` | 配置 | Bridge 部署——Claude/Copilot/Hermes/Cursor/OpenAI |
| 19 | `harness_gate_approve` | 门禁 | 门禁审批——批准/拒绝待审请求 |
| 20 | `harness_hook_trigger` | 门禁 | 生命周期插槽治理触发——返回决策 |
| 21 | `harness_knowledge_query` | 知识 | 知识条目查询——架构决策/风险/约定 |
| 22 | `harness_knowledge_search` | 知识 | 知识检索——关键词 + TF-IDF 语义 |
| 23 | `harness_knowledge_stats` | 知识 | 知识库统计——条目分布概览 |
| 24 | `harness_knowledge_activate` | 知识 | Insight 激活为合规规则（S-4） |
| 25 | `harness_knowledge_deactivate` | 知识 | 撤销 Insight 规则激活（S-4） |

---

## MCP JSON-RPC 调用协议

MCP Server 使用 JSON-RPC 2.0 over stdio 协议：

```json
// 请求
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "harness_check",
    "arguments": {
      "path": "src/main.py",
      "pack_names": ["security"],
      "engine": "builtin"
    }
  }
}

// 响应
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {"type": "text", "text": "{\"violations\": [...], \"total\": 5, ...}"}
    ]
  }
}
```

---

## Demo 1：合规检查工具组

### harness_check

```
参数:
  path: 文件路径或标识符
  pack_names: 规则包名称列表 (coding, security, data, devops)
  engine: 合规引擎 (builtin, sonarqube, opa, archunit, dep_cruiser)
  language_routing: 语言→引擎映射

调用示例:
  harness_check(path="src/main.py", pack_names=["security"], engine="builtin")
```

### harness_guardrails_check

```
参数:
  content: 待检查内容
  direction: input / output
  engine: builtin / guardrails-ai

调用示例:
  harness_guardrails_check(content="用户数据", direction="input")
```

### harness_rule_import

```
参数:
  source: sonarqube / archunit / dep_cruiser
  config: 源配置字典
  languages: 语言过滤列表
  project_key: SonarQube 项目键

调用示例:
  harness_rule_import(source="sonarqube", config={"url": "http://localhost:9000"})
```

---

## Demo 2：审计追踪工具组

### harness_audit

```
参数:
  query: 搜索关键词
  backend: local / langfuse / arize / datadog
  limit: 最大结果数

调用示例:
  harness_audit(query="code_generate", backend="local", limit=50)
```

### harness_trace_export

```
参数:
  format: otel-json / traceloop
  query: 搜索关键词
  date_from / date_to: 日期范围
  limit: 最大条数

调用示例:
  harness_trace_export(format="otel-json", date_from="2026-01-01")
```

### harness_status

```
无参数，返回系统聚合状态（registry、compliance、engine stats）

调用示例:
  harness_status()
```

---

## Demo 3：工作流编排工具组

### harness_plan

```
参数:
  workflow_yaml: YAML 格式的 DAG 定义

调用示例:
  harness_plan(workflow_yaml="nodes:\n  - id: analyst\n  - id: coder\nedges:\n  - from: analyst\n    to: coder")
```

### harness_run

```
参数:
  workflow_yaml: YAML 格式的 DAG 定义

调用示例:
  harness_run(workflow_yaml="...")
```

### harness_pipeline_run

```
参数:
  task: 任务描述
  agents: Pipeline agent 序列 (默认: analyst, coder, validator, committer)
  gate_mode: strict / hybrid / loose
  max_retries: 最大重试次数
  working_directory: 工作目录

调用示例:
  harness_pipeline_run(task="修复安全违规", gate_mode="hybrid")
```

### harness_pipeline_status

```
无参数，查询当前或最近 Pipeline 执行状态

调用示例:
  harness_pipeline_status()
```

---

## Demo 4：门禁管理工具组

### harness_gate_create

```
参数:
  gate_type: strict / hybrid / loose
  checks: 检查项列表 [{id, category, severity, description}]
  auto_fix: 是否自动修复

调用示例:
  harness_gate_create(
    gate_type="hybrid",
    checks=[{"id": "no-raw-sql", "category": "security", "severity": "high", "description": "禁止拼接SQL"}]
  )
```

---

## Demo 5：注册/配置工具组

### harness_register / harness_agent_list

```
harness_register(agent_id="coder", name="Coder Agent", capabilities=["execute"], toolsets=["bash"])
harness_agent_list()  → 返回所有已注册 Agent
```

### harness_profile_list / harness_profile_load

```
harness_profile_list()  → 返回所有 Profile
harness_profile_load(name="default")  → 加载 Profile
```

### harness_skill_list / harness_skill_register

```
harness_skill_list(slot="post_execute")  → 按 slot 过滤
harness_skill_register(skill_id="auto-test", name="Auto Test", slot="post_tool_use")
```

### harness_bridge_deploy

```
参数:
  adapter: claude-code / copilot-cli / hermes / cursor / openai
  profile_name: Profile 名称

调用示例:
  harness_bridge_deploy(adapter="claude-code", profile_name="default")
```

---

## IDE 使用方式

| IDE | MCP 工具调用方式 |
|-----|----------------|
| Claude Code | 直接通过 `mcp__harness-cook__*` 工具名调用 |
| VS Code Copilot | 通过 MCP 协议自动注册 |
| Cursor | 通过 MCP 协议自动注册 |
| Copilot CLI | 通过 `harness_bridge_deploy(adapter="copilot-cli")` |

---

## 相关导航

- 📖 原理 → [MCP Server](/guide/mcp-server) · [Bridge](/guide/bridge)
- 🏃 跑代码 → [examples/mcp-full/](../../examples/mcp-full/)
- 🎓 方法 → [MCP 集成](/tutorial/mcp-integration)

# MCP Server

harness-cook MCP Server 基于 JSON-RPC 2.0 over stdio 协议实现，采用纯手写方式，不依赖任何第三方 MCP SDK。

## 服务器信息

| 属性 | 值 |
|------|----|
| 服务器名称 | `harness-cook` |
| 服务器版本 | `0.1.0` |
| 协议版本 | `2024-11-05` |

## 协议规范

harness-cook MCP Server 严格遵循 JSON-RPC 2.0 规范，通过 stdio 传输层进行通信（每行一个 JSON 对象）。

### 支持的方法

| 方法 | 说明 |
|------|------|
| `initialize` | 初始化连接，返回协议版本与服务器能力声明 |
| `tools/list` | 返回所有可用工具的元数据列表 |
| `tools/call` | 调用指定工具并返回执行结果 |

### JSON-RPC 2.0 错误码

| 错误码 | 常量名 | 说明 |
|--------|--------|------|
| `-32700` | `PARSE_ERROR` | JSON 解析失败 |
| `-32600` | `INVALID_REQUEST` | 请求对象不符合规范 |
| `-32601` | `METHOD_NOT_FOUND` | 方法不存在 |
| `-32602` | `INVALID_PARAMS` | 参数无效 |
| `-32603` | `INTERNAL_ERROR` | 服务器内部错误 |

### 请求/响应示例

**initialize 请求：**

```json
{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
```

**initialize 响应：**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "capabilities": {"tools": {}},
    "serverInfo": {
      "name": "harness-cook",
      "version": "0.1.0"
    }
  }
}
```

**tools/call 请求：**

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "harness_status",
    "arguments": {}
  }
}
```

**tools/call 响应：**

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [{"type": "text", "text": "..."}]
  }
}
```

## 工具列表

harness-cook MCP Server 提供以下 25 个工具：

### harness_check

运行合规扫描，支持指定规则包和引擎路由。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | 是 | 待扫描的文件路径或标识符 |
| `pack_names` | string[] | 否 | 规则包名称列表（`coding`、`security`、`data`、`devops`），默认加载全部 |
| `content` | string | 否 | 待扫描的内容文本 |
| `engine` | string | 否 | 合规引擎选择（`builtin` / `sonarqube` / `opa` / `archunit` / `dep_cruiser`），默认 `builtin` |

返回结果包含扫描路径、已加载/跳过的规则包、通过/失败的规则数及详细合规发现。

### harness_audit

搜索审计日志条目，支持指定后端。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 是 | 搜索关键词 |
| `limit` | integer | 否 | 最大返回条数，默认 50 |
| `backend` | string | 否 | 审计后端选择（`local` / `langfuse` / `arize` / `datadog` / `helicone`），默认 `local` |

返回结果包含查询关键词、匹配条数及每条审计记录的详细信息。

### harness_plan

DAG 工作流拓扑可视化，返回节点的拓扑执行顺序。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `workflow_yaml` | string | 是 | 定义 DAG 工作流的 YAML 字符串（包含 nodes 和 edges） |

返回结果包含执行顺序、节点列表、边列表、节点总数及边总数。

> **注意**：此工具需要 PyYAML 依赖。若未安装 PyYAML，将抛出错误。

### harness_run

执行 DAG 工作流，返回执行上下文结果。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `workflow_yaml` | string | 是 | 定义 DAG 工作流的 YAML 字符串 |

返回结果包含执行 ID、工作流 ID、耗时、已完成节点、失败节点、是否升级及升级原因。

> **注意**：此工具同样需要 PyYAML 依赖。

### harness_status

返回聚合系统状态，涵盖注册表、合规引擎、DAG 引擎及门禁引擎的统计信息。

无输入参数。

返回结果包含 `registry`、`compliance`、`engine`、`gate` 及 `server` 五个维度的状态数据。

### harness_register

在 harness 注册表中注册新 Agent。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `agent_id` | string | 是 | Agent 唯一标识符 |
| `name` | string | 否 | Agent 可读名称，默认取 `agent_id` |
| `capabilities` | string[] | 否 | Agent 能力列表，默认为 `["execute"]` |
| `toolsets` | string[] | 否 | Agent 所需的工具集名称列表 |

### harness_gate_create

创建门禁（Gate）定义。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `gate_type` | string | 是 | 门禁模式：`strict`、`hybrid` 或 `loose` |
| `checks` | object[] | 是 | 门禁检查项列表 |
| `auto_fix` | boolean | 否 | 是否启用自动修复，默认 `false` |

### harness_gate_approve

批准或拒绝一个待审批的门禁请求（E-9：EventBus 回调模式）。当 `GateManager.wait_for_approval()` 发出 `GATE_APPROVAL_REQUEST` 事件并阻塞在 `threading.Event` 上时，此工具通过项目 EventBus 发出对应的 `GATE_APPROVAL_DECISION` 事件唤醒等待线程。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `gate_id` | string | 是 | 待审批的门禁 ID（须匹配一个 pending 的 `GATE_APPROVAL_REQUEST`） |
| `decision` | string | 是 | 审批决策：`approved`、`rejected`、`cancelled` |
| `decided_by` | string | 否 | 决策者（用户名/角色），默认 `human` |
| `reason` | string | 否 | 决策原因，可选 |

### harness_guardrails_check

输入/输出护栏检查，支持引擎选择。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `content` | string | 是 | 待检查的内容文本 |
| `direction` | string | 否 | 检查方向：`input` 或 `output`，默认 `input` |
| `engine` | string | 否 | 护栏引擎选择（`builtin` / `guardrails-ai` / `nemo` / `llama-guard` / `helicone`），默认 `builtin` |

**引擎路由逻辑：**
- `builtin` → 现有 GuardrailsPair（PIIDetector，行为不变）
- `guardrails-ai` → 委托 GuardrailsAIChecker（50+ validators）
- `nemo` → 委托 NeMoGuardrailsChecker（Colang DSL 流控）
- `llama-guard` → 委托 LlamaGuardChecker（安全分类模型）
- `helicone` → 委托 HeliconeMiddlewareChecker
- 不可用时静默回退到 builtin + warning

返回结果包含护栏动作、是否阻断、警告列表、违规列表、脱敏列表。

### harness_hook_trigger

针对生命周期插槽触发治理逻辑并返回治理决策。按插槽类型路由到对应治理层：`pre_tool_use`/`pre_execute` → InputGuardrails；`post_tool_use`/`post_execute`/`on_file_change` → OutputGuardrails；其他插槽 → CONTINUE（不做治理检查）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `slot` | string | 是 | 生命周期插槽名。有效值：`session_start`、`session_end`、`pre_execute`、`post_execute`、`on_error`、`pre_tool_use`、`post_tool_use`、`on_gate_pass`、`on_gate_fail`、`on_file_change`、`pre_commit`、`post_commit`、`on_delegate`、`on_conflict`、`on_decision`、`on_escalation`、`user_prompt_submit` |
| `content` | string | 否 | 待检查的内容（文本/代码/命令输出），护栏检查类插槽必填 |
| `direction` | string | 否 | 检查方向：`input` 或 `output`（默认 `input`），决定使用哪对护栏 |
| `tool_name` | string | 否 | 工具名上下文（如 `Write`、`Edit`、`Bash`），用于基于 matcher 的路由 |

返回治理决策：`BLOCK` / `WARN` / `REDACT` / `CONTINUE`。

### harness_pipeline_run

启动编码流水线（Analyst→Coder→Validator→Committer），带 gate 检查。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task` | string | 是 | 任务描述 |
| `gate_mode` | string | 否 | 门禁模式（`strict` / `hybrid` / `loose`），默认 `hybrid` |
| `max_retries` | integer | 否 | 重试次数，默认 2 |
| `working_directory` | string | 否 | 工作目录，默认当前 |

### harness_pipeline_status

查询当前或最近一次流水线执行状态。

无输入参数。

### harness_agent_list

列出可用 Agent 角色及工具配置。

无输入参数。

### harness_bridge_deploy

部署当前 Profile 配置到 Agent 环境（生成 settings.json 等）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `profile_name` | string | 否 | Profile 名称，默认 `default` |

返回结果包含部署的适配器、hooks 数量、门禁检查项、技能可用数。

### harness_skill_list

列出已注册 Skills，可选按插槽或标签过滤。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `slot` | string | 否 | 按插槽点名称过滤 |
| `tag` | string | 否 | 按标签过滤 |

### harness_skill_register

注册新 Skill。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `skill_id` | string | 是 | Skill 唯一标识 |
| `name` | string | 否 | Skill 可读名称 |
| `entry_point` | string | 否 | Skill 脚本路径 |
| `slot` | string | 否 | 插槽点名称，默认 `post_execute` |

### harness_profile_list

列出所有可用的 Harness Profile 配置。

无输入参数。

### harness_profile_load

加载指定 Profile 配置。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 否 | Profile 名称，默认 `default` |

### harness_rule_import

从外部合规引擎导入规则，返回可加载到合规引擎的 RulePack。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | string | 是 | 规则来源引擎：`sonarqube` / `archunit` / `dep_cruiser` |
| `project_key` | string | 否 | SonarQube 项目 key（SonarQube 时使用）；ArchUnit/DepCruiser 时作为 project_root |
| `languages` | string[] | 否 | SonarQube 语言过滤（如 `["python", "java"]`），仅 SonarQube 时使用 |
| `config` | object | 否 | 来源引擎专属配置（如 `sonarqube_url`、`sonarqube_token`、`config_file` 等），键值对格式 |

**引擎说明：**
- `sonarqube` —— 从 SonarQube 实例导入规则，需配置 `sonarqube_url` 和 `sonarqube_token`
- `archunit` —— 从 ArchUnit Python/Lambda 规则文件导入，`project_key` 为项目根路径
- `dep_cruiser` —— 从 dependency-cruiser 配置文件导入，`project_key` 为项目根路径

### harness_trace_export

导出审计日志为 OTel/Traceloop 兼容的 trace 格式，用于可观测性集成。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 否 | 搜索关键词过滤条目 |
| `limit` | integer | 否 | 最大导出条数，默认 50 |
| `format` | string | 否 | 导出格式：`otel-json`（默认，标准 OTel Span 属性）或 `traceloop`（追加 Traceloop 专属属性映射） |
| `date_from` | string | 否 | 起始日期过滤，ISO 格式（如 `2026-01-01`） |
| `date_to` | string | 否 | 结束日期过滤，ISO 格式（如 `2026-12-31`） |

返回结果为 span 列表，每条包含 `harness.*` 和（可选）`traceloop.*` 属性，可直接送入任何 OTel collector 消费。

### harness_knowledge_query

按过滤器查询知识条目，返回结构化的项目知识（架构决策、已知风险、编码约定等）。在做出决策前用于获取项目上下文——例如选技术栈前查已有 DECISION 条目，写代码前查已知 RISK 和 PATTERN 条目。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 否 | 在 title/content/tags 中搜索的关键词 |
| `type_filter` | string | 否 | 按知识类型过滤：`architecture`/`convention`/`dependency`/`api`/`pattern`/`risk`/`decision`/`task`/`test`/`glossary` |
| `scope_filter` | string | 否 | 按范围过滤：`project`/`module`/`file`/`function` |
| `source_filter` | string | 否 | 按来源过滤：`human`/`ast`/`llm`/`learning`/`compliance`/`guardrail`/`gate` |
| `tags_filter` | string[] | 否 | 按标签过滤 |
| `limit` | integer | 否 | 最大返回条数，默认 20 |
| `project` | string | 否 | 项目名（默认从当前目录自动解析） |

### harness_knowledge_search

按关键词或 TF-IDF 语义搜索知识。关键词搜索匹配 title/content/tags；语义搜索用 TF-IDF 做更宽的相关性匹配。当关键词搜索无结果或需要概念相关条目时用 `method=semantic`。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 是 | 搜索查询——关键词或概念描述 |
| `method` | string | 否 | 搜索方式：`keyword`（默认，精确匹配）或 `semantic`（TF-IDF 相关性） |
| `limit` | integer | 否 | 最大返回条数，默认 10 |
| `project` | string | 否 | 项目名（默认自动解析） |

### harness_knowledge_stats

知识库统计概览——条目总数、类型分布、来源分布、高频条目、已归档条目。用于在查询具体条目前了解可用的知识范围。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `project` | string | 否 | 项目名（默认自动解析） |

### harness_knowledge_activate

将一个 Insight 激活为 ComplianceRule（S-4：一键激活）。把知识条目（Insight）转换为包裹在 RulePack 中的 ComplianceRule 并加载到 ComplianceEngine 进行实时检查。激活过程被记录，可通过 `harness_knowledge_deactivate` 撤销。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `insight_id` | string | 是 | 待激活 Insight 的 KnowledgeEntry ID（先用 `harness_knowledge_query` 或 `harness_knowledge_search` 查找 Insight 条目） |
| `project` | string | 否 | 项目名（默认自动解析） |
| `severity` | string | 否 | 激活规则的严重性级别：`critical`/`high`/`medium`/`low`，默认 `medium` |

### harness_knowledge_deactivate

撤销一个 Insight 的 ComplianceRule 激活（S-4）。从 ComplianceEngine 移除对应 RulePack 并删除激活记录。当某个由 Insight 派生的规则不再需要或被误激活时使用。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `insight_id` | string | 是 | 待撤销激活的 Insight ID（须匹配一个先前激活的 Insight） |
| `project` | string | 否 | 项目名（默认自动解析） |

## 启动方式

### Stdio 模式

直接运行服务器，通过标准输入/输出进行 JSON-RPC 通信：

```bash
python packages/mcp/harness_mcp_server.py
```

### 编程式调用

```python
from harness_mcp_server import HarnessMCPServer

server = HarnessMCPServer()
request = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {}
}
response = server.handle_request(request)
```

### Demo

```bash
python playground/demo_mcp.py
```

## 可选依赖

| 依赖组 | 安装命令 | 说明 |
|------|------|------|
| PyYAML | 已含在默认安装 | 工作流 YAML 解析 |
| guardrails | `pip install harness-cook[guardrails]` | Guardrails AI SDK |
| sonarqube | `pip install harness-cook[sonarqube]` | SonarQube Python API |
| opa | `pip install harness-cook[opa]` | OPA Python SDK |
| integrations | `pip install harness-cook[integrations]` | 所有外部引擎 SDK |

引擎未安装时：
- harness_check(engine="sonarqube") → fallback 到 builtin + warning
- harness_guardrails_check(engine="guardrails-ai") → fallback 到 builtin + warning
- harness_audit(backends="langfuse") → 仅使用 local + warning

## 架构说明

`HarnessMCPServer` 类在初始化时自动构建以下核心组件：

| 组件 | 来源 | 说明 |
|------|------|------|
| `EventBus` | `harness.bus.get_bus()` | 事件总线 |
| `AgentRegistry` | `harness.registry.get_registry()` | Agent 注册表 |
| `ComplianceEngine` | `harness.compliance` | 合规引擎 + MatcherRegistry 引擎路由 |
| `AuditEngine` | `harness.audit` | 审计引擎 + IAuditStore Protocol |
| `GateEngine` | `harness.gates` | 门禁引擎 |
| `DAGEngine` | `harness.engine` | DAG 执行引擎 |
| `GuardrailsPair` | `harness.guardrails.default_guardrails()` | 输入/输出护栏（默认内置） |
| `HarnessBridge` | `harness.bridge` | Bridge 部署（多适配器） |

所有组件通过共享的 `EventBus` 实例协同工作。

## 规则包映射

合规扫描（`harness_check`）支持以下规则包：

| 名称 | 工厂函数 | 说明 |
|------|----------|------|
| `coding` | `get_coding_pack()` | 编码规范 |
| `security` | `get_security_pack()` | 安全合规 |
| `data` | `get_data_pack()` | 数据治理 |
| `devops` | `get_devops_pack()` | DevOps 实践 |

外部引擎规则通过 RuleImporter 导入：`SonarQubeRuleImporter`, `ArchUnitRuleImporter`, `DepCruiserRuleImporter`。

# MCP 全量工具 Demo

> harness-cook MCP Server 的 25 个工具完整调用演示——合规检查、审计追踪、工作流编排、门禁管理、注册/配置、知识管理

**文档介绍**见 VitePress Demo 页面 [MCP 全量](../../playground/docs/demo/mcp-full.md)——代码片段 + 预期输出 + 配置说明。本目录是可运行的脚本。

## 运行

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/mcp-full/demo_mcp_full.py
```

## 工具清单（25 个）

| 序号 | MCP 工具 | 所属分组 | 说明 |
|------|----------|----------|------|
| 1 | `harness_check` | 合规检查 | 合规扫描——支持引擎路由 + 语言路由 |
| 2 | `harness_guardrails_check` | 合规检查 | 输入/输出护栏——PII + 安全检测 |
| 3 | `harness_rule_import` | 合规检查 | 外部规则导入——SonarQube / ArchUnit / DepCruiser |
| 4 | `harness_audit` | 审计追踪 | 搜索审计记录——支持后端选择（local / langfuse / arize / datadog） |
| 5 | `harness_trace_export` | 审计追踪 | 导出审计追踪——OTel JSON / Traceloop 格式 |
| 6 | `harness_status` | 审计追踪 | 系统聚合状态——注册表、合规引擎、审计统计 |
| 7 | `harness_plan` | 工作流编排 | DAG 拓扑可视化——返回执行顺序 |
| 8 | `harness_run` | 工作流编排 | 执行 DAG 工作流——返回执行上下文结果 |
| 9 | `harness_pipeline_run` | 工作流编排 | 编码流水线——Analyst→Coder→Validator→Committer |
| 10 | `harness_pipeline_status` | 工作流编排 | 流水线状态查询 |
| 11 | `harness_gate_create` | 门禁管理 | 创建门禁定义——strict / hybrid / loose |
| 12 | `harness_gate_approve` | 门禁管理 | 审批门禁请求（approved / rejected / cancelled） |
| 13 | `harness_hook_trigger` | 门禁管理 | 触发生命周期槽位的治理逻辑——路由到 InputGuardrails / OutputGuardrails |
| 14 | `harness_register` | 注册/配置 | 注册 Agent 到 harness registry |
| 15 | `harness_agent_list` | 注册/配置 | 列出可用 Agent 角色 |
| 16 | `harness_profile_list` | 注册/配置 | 列出所有可用 Profile |
| 17 | `harness_profile_load` | 注册/配置 | 加载 Profile + Overlay 合并 |
| 18 | `harness_skill_list` | 注册/配置 | 列出已注册 Skill——按槽位/标签过滤 |
| 19 | `harness_skill_register` | 注册/配置 | 注册新 Skill |
| 20 | `harness_bridge_deploy` | 注册/配置 | 部署 Profile 到 Agent 平台——Claude Code / Copilot CLI / Cursor |
| 21 | `harness_knowledge_query` | 知识管理 | 查询知识条目——按类型/范围/来源/标签过滤 |
| 22 | `harness_knowledge_search` | 知识管理 | 搜索知识——关键词或 TF-IDF 语义搜索 |
| 23 | `harness_knowledge_stats` | 知识管理 | 知识库统计——条目数、类型分布、来源分布 |
| 24 | `harness_knowledge_activate` | 知识管理 | 将知识 Insight 激活为 ComplianceRule——一键转规则 |
| 25 | `harness_knowledge_deactivate` | 知识管理 | 停用已激活的 Insight 规则 |

## Demo 分组

### 1. 合规检查工具组（3 个工具）

| Demo | 工具 | 说明 |
|------|------|------|
| 1.1 | `harness_check` | 基本合规扫描——coding + security 规则包 |
| 1.2 | `harness_check` | 语言路由——Java 文件自动路由到 ArchUnit |
| 1.3 | `harness_check` | 外部引擎——archunit（SDK未安装回退 builtin） |
| 1.4 | `harness_guardrails_check` | 输入护栏——PII 检测（手机号、密码等） |
| 1.5 | `harness_guardrails_check` | 输出护栏——敏感信息检测（数据库连接串） |
| 1.6 | `harness_guardrails_check` | Guardrails AI 引擎（SDK未安装回退 builtin） |
| 1.7 | `harness_rule_import` | SonarQube 规则导入 |
| 1.8 | `harness_rule_import` | ArchUnit 规则导入 |
| 1.9 | `harness_rule_import` | DepCruiser 规则导入 |

### 2. 审计追踪工具组（3 个工具）

| Demo | 工具 | 说明 |
|------|------|------|
| 2.1 | `harness_audit` | 搜索审计记录（本地存储） |
| 2.2 | `harness_audit` | Langfuse 后端搜索（标记后端，实际搜索仍从 primary store） |
| 2.3 | `harness_trace_export` | OTel JSON 格式导出 |
| 2.4 | `harness_trace_export` | Traceloop 格式导出（SDK不可用回退 otel-json） |
| 2.5 | `harness_status` | 系统聚合状态——注册表 + 合规 + 审计 + 部署 |

### 3. 工作流编排工具组（4 个工具）

| Demo | 工具 | 说明 |
|------|------|------|
| 3.1 | `harness_plan` | DAG 拓扑可视化（3 节点顺序工作流） |
| 3.2 | `harness_plan` | DAG 拓扑可视化（并行汇聚工作流） |
| 3.3 | `harness_run` | 执行 DAG 工作流 |
| 3.4 | `harness_pipeline_run` | 编码流水线（hybrid 门禁） |
| 3.5 | `harness_pipeline_run` | 编码流水线（strict 门禁模式） |
| 3.6 | `harness_pipeline_status` | 流水线状态查询 |

### 4. 门禁管理工具组（1 个工具）

| Demo | 工具 | 说明 |
|------|------|------|
| 4.1 | `harness_gate_create` | strict 门禁——零容忍 |
| 4.2 | `harness_gate_create` | hybrid 门禁 + 自动修复 |
| 4.3 | `harness_gate_create` | loose 门禁——仅拦截 critical |

### 5. 注册/配置工具组（7 个工具）

| Demo | 工具 | 说明 |
|------|------|------|
| 5.1 | `harness_register` | 注册安全审查 Agent |
| 5.2 | `harness_register` | 注册自动修复 Agent |
| 5.3 | `harness_agent_list` | 列出可用 Agent 角色 |
| 5.4 | `harness_profile_list` | 列出所有 Profile |
| 5.5 | `harness_profile_load` | 加载 default + hybrid Overlay |
| 5.6 | `harness_profile_load` | 自动解析 Profile（环境变量 > marker > default） |
| 5.7 | `harness_profile_load` | 加载 senior-developer + strict Overlay |
| 5.8 | `harness_skill_list` | 列出所有 Skill |
| 5.9 | `harness_skill_list` | 按 post_execute 槽位过滤 |
| 5.10 | `harness_skill_list` | 按 compliance 标签过滤 |
| 5.11 | `harness_skill_register` | 注册自动 lint 修复 Skill |
| 5.12 | `harness_skill_register` | 注册门禁通过通知 Skill |
| 5.13 | `harness_bridge_deploy` | 部署到 Claude Code（自动解析） |
| 5.14 | `harness_bridge_deploy` | 部署到 Copilot CLI（senior-developer + strict） |
| 5.15 | `harness_bridge_deploy` | 部署到 Cursor（default + hybrid） |

## 适用场景

- IDE 中通过 MCP 协议调用 harness-cook 工具——Claude Code、Copilot CLI、Cursor
- 合规检查：代码扫描、PII 检测、外部规则导入
- 审计追踪：不可篡改的审计记录搜索、OTel 可观测性导出
- 工作流编排：DAG 可视化与执行、编码流水线
- 门禁管理：质量门禁定义（strict/hybrid/loose 三级）
- Agent 与 Skill 注册、Profile 配置加载与部署

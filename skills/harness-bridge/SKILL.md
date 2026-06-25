---
name: harness-bridge
description: "Hermes→harness-cook桥接skill: 让Hermes Agent通过terminal执行bridge.py调用harness核心能力"
version: 1.0.0
trigger: "当需要运行合规检查、查看审计日志、执行编排流程时使用。命令: harness check / harness audit / harness run"
---

# harness-bridge

Hermes Agent 与 harness-cook 核心能力的桥接 skill。

## 桥接方式

Hermes skill 通过 `terminal` 执行 `bridge.py` Python 脚本 → 调用 harness-cook 核心 API。

路径链路：
```
Hermes Agent → terminal("python bridge.py <command>") → harness-cook packages/core API
```

`bridge.py` 自动设置 `PYTHONPATH`，优先使用 `$CLAUDE_PROJECT_DIR` 环境变量（Claude Code 自动设置），确保跨机器可移植。

### 多平台适配器

harness-cook 使用适配器模式支持 5 个 Agent 平台：

| 适配器 | 有 hooks？ | 治理强度 | Prompt 强度 |
|--------|----------|---------|-----------|
| ClaudeCodeAdapter | ✅ 原生 hooks | 强制性 | mild |
| CopilotCLIAdapter | ✅ 有 hook 概念 | 强制性 | mild |
| HermesAdapter | ❌ 无原生 hooks（MCP 降级） | 建议性→接近强制 | mandatory |
| CursorAdapter | ❌ 无 hooks | 建议性→接近强制 | mandatory |
| OpenAIAdapter | ❌ 无 hooks | 建议性→接近强制 | mandatory |

- **强制性 Agent**（有 hooks）：hooks 自动触发，gate prompt 使用 mild 强度
- **建议性 Agent**（无 hooks）：hooks 降级为 metadata，gate prompt 使用 mandatory 强度，Agent 通常遵循但理论上可绕过
- **Git Hook 兜底**：所有 Agent 都自动安装 git pre-commit hook，不合规代码无法通过 commit

### MCP 工具直接调用

除了 `bridge.py` 脚本外，harness-cook 还通过 MCP Server 暴露了 25 个工具，可直接在 Claude Code 中调用：

| MCP 工具 | 对应 bridge 命令 | 说明 |
|----------|-----------------|------|
| `harness_check` | `check` | 合规扫描 |
| `harness_audit` | `audit` | 审计记录查询 |
| `harness_guardrails_check` | — | PII/安全护栏检查 |
| `harness_gate_create` | — | 创建门禁定义 |
| `harness_gate_approve` | — | 审批门禁请求 |
| `harness_hook_trigger` | — | 触发生命周期槽位治理逻辑 |
| `harness_pipeline_run` | `run` | 编码管线执行 |
| `harness_pipeline_status` | — | 管线状态查询 |
| `harness_plan` | `plan` | DAG 拓扑可视化 |
| `harness_run` | — | DAG 工作流执行 |
| `harness_register` | — | 注册 Agent |
| `harness_agent_list` | — | 查看注册的 Agent |
| `harness_profile_list` | — | 列出可用 Profile |
| `harness_profile_load` | — | 加载 Profile |
| `harness_skill_list` | — | 列出已注册 Skill |
| `harness_skill_register` | — | 注册新 Skill |
| `harness_bridge_deploy` | — | 部署 Profile 到 Agent 平台 |
| `harness_status` | `status` | 系统状态 |
| `harness_trace_export` | — | 审计追踪导出（OTel/Traceloop） |
| `harness_rule_import` | — | 外部规则导入 |
| `harness_knowledge_query` | — | 查询知识条目 |
| `harness_knowledge_search` | — | 搜索知识（关键词/语义） |
| `harness_knowledge_stats` | — | 知识库统计 |
| `harness_knowledge_activate` | — | 激活 Insight 为 ComplianceRule |
| `harness_knowledge_deactivate` | — | 停用已激活的 Insight 规则 |

在 Claude Code 中，可直接调用 MCP 工具（无需经过 `bridge.py`）：
```
mcp__harness-cook__harness_check path="src/auth.ts" pack_names=["security", "coding"]
mcp__harness-cook__harness_audit query="auth" limit=20
mcp__harness-cook__harness_status
```

## 命令用法

### `harness check [path]`
运行合规检查 + 安全护栏扫描。
- `path`: 要检查的文件或目录路径（可选，默认当前目录）
- 执行: ComplianceEngine 加载所有内置规则包 → 扫描文件 → 输出违规列表
- 同时运行 InputGuardrails + OutputGuardrails 检查

### `harness audit [query]`
查看审计日志。
- `query`: 搜索关键词（可选，空则显示最近记录）
- 执行: AuditStore.search → 输出匹配的审计记录摘要

### `harness run <workflow.yaml>`
执行编排流程。
- `workflow.yaml`: DAG 工作流定义文件路径
- 执行: DAGEngine.execute → 逐步执行节点 + 门禁检查 → 输出执行摘要

### `harness plan <workflow.yaml>`
可视化 DAG 拓扑。
- `workflow.yaml`: DAG 工作流定义文件路径
- 执行: SmartScheduler.plan → 输出并行分组 + 关键路径 + token 预估

### `harness status`
显示 harness 运行状态。
- 已注册 Agent 数、已加载规则包数、审计记录数等

### `harness version`
显示 harness-cook 版本号。

## 执行方式

```bash
# 在项目根目录执行
python skills/harness-bridge/bridge.py <command> [args]

# 或通过绝对路径
python /Users/administrator/ProjectsOnGitlab/harness-cook/skills/harness-bridge/bridge.py <command> [args]
```

## 安装步骤

无需额外依赖，Python 3.9+ 即可运行。

符号链接已自动创建：
- `~/.hermes/skills/harness-bridge` → 项目 `skills/harness-bridge/`
- `~/.claude/skills/harness-bridge` → 项目 `skills/harness-bridge/`

## Pitfalls

1. **PYTHONPATH**: `bridge.py` 内部自动设置，优先使用 `$CLAUDE_PROJECT_DIR`（Claude Code 自动注入），确保跨机器可移植。如手动运行需设置 `PYTHONPATH=packages/core` 或 `CLAUDE_PROJECT_DIR=<项目根目录>`。
2. **审计记录**: `harness audit` 依赖 `.harness/audit/` 目录下的 JSON 文件。首次运行前可能无记录（SessionStart hook 会自动创建该目录）。
3. **工作流文件**: `harness run` 和 `harness plan` 需要 YAML 工作流定义文件。文件不存在时会有友好提示。
4. **Python 版本**: 需 Python 3.9.6+，使用 `list[str]` 等新语法。
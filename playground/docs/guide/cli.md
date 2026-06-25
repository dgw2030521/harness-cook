# CLI 命令行工具

harness-cook 提供 9 个 CLI 子命令，覆盖激活/还原、可观测性、工作流规划、执行、合规检查、审计查询。

## 安装

CLI 依赖核心包，确保 `packages/core` 在 Python 路径中可达：

```bash
# 方式一：从项目根目录运行（推荐）
cd harness-cook
python3 packages/cli/harness_cli.py <subcommand>

# 方式二：安装后运行
pip install -e packages/cli
harness <subcommand>
```

## 可选引擎安装

合规扫描和护栏检查支持外部引擎，需要安装对应的可选依赖：

```bash
pip install harness-cook[guardrails]     # Guardrails AI 护栏引擎
pip install harness-cook[sonarqube]      # SonarQube 合规引擎
pip install harness-cook[opa]            # OPA 策略引擎
pip install harness-cook[integrations]   # 所有外部引擎
```

引擎未安装时自动回退到内置 checker，不影响基本功能。

## harness activate — 一键激活

```bash
harness activate [--profile PROFILE] [--agent AGENT] [--skip-install] [--skip-mcp] [--skip-hooks] [--skip-skills] [--skip-init]
```

一键激活 harness-cook 所有能力，自动完成：

| 步骤 | 说明 | 跳过选项 |
|------|------|---------|
| 安装核心包 | `pip install -e packages/core` | `--skip-install` |
| 配置 MCP Server | 由 `bridge.deploy` 写入各平台配置（claude-code 走 hooks 自动校验，不再写 `~/.claude/settings.json` mcpServers；其他适配器写入各自平台配置） | `--skip-mcp` |
| 部署 Profile | 读取 `default.yaml` → 通过 `bridge.deploy(harness_root=...)` 写入目标平台配置 | `--skip-hooks` |
| 注册 Skills | 符号链接到 `~/.claude/skills/` | `--skip-skills` |
| 初始化目录 | 创建 `.harness/audit/` 等 + 写入 `active_profile` / `active_adapter` / `.harness/env` | `--skip-init` |

### `--agent` 参数：选择部署目标平台

`--agent` 指定将治理配置部署到哪个 Agent 平台。每个平台有不同的适配器，适配器决定了：
- 配置写入哪个文件（如 `.claude/settings.json` / `.cursor/mcp.json` / `~/.hermes/config.yaml`）
- 治理策略（hooks 强制执行 vs MCP 工具建议性）
- MCP 权限是否写入 `.claude/settings.local.json`（仅 `claude-code` 适配器）

| 值 | 目标平台 | 配置文件 | 有 hooks？ | 治理强度 |
|---|---------|---------|----------|---------|
| `claude-code` | Claude Code | `.claude/settings.json` | ✅ 原生 hooks | **强制性** |
| `copilot-cli` | GitHub Copilot CLI | `.copilot/config.json` | ✅ 有 hook 概念 | **强制性** |
| `hermes` | Hermes | `~/.hermes/config.yaml` | ❌ 无原生 hooks | **建议性→接近强制** |
| `cursor` | Cursor IDE | `.cursor/mcp.json` | ❌ 无 hooks | **建议性→接近强制** |
| `openai` | OpenAI/Codex | 无本地配置 | ❌ 无 hooks | **建议性→接近强制** |

不指定 `--agent` 时，系统通过 5 级优先级链自动推导适配器：

| 优先级 | 来源 | 说明 |
|--------|------|------|
| 1️⃣ 最高 | `HARNESS_ADAPTER` 环境变量 | CI/自动化覆盖 |
| 2️⃣ | `.harness/env` 中 `HARNESS_ADAPTER=` | 机器级持久化（activate 写入，gitignored） |
| 3️⃣ | `.harness/active_adapter` 标记文件 | 项目级持久化选择（提交到 Git，团队共享） |
| 4️⃣ | Profile `agent.adapter` 字段 | 配置声明——作为回退默认值 |
| 5️⃣ 最低 | `"claude-code"` 回退 | 无任何配置时的默认值 |

> **Adapter 与 Profile 正交**：Adapter 是运行时/环境决策（"部署到哪"），Profile 是治理决策（"部署什么规则"）。两者独立解析、互不影响。

**示例：**

```bash
# 完全激活（默认 Claude Code 适配器）
harness activate

# 部署到 Hermes 平台
harness activate --agent hermes

# 部署到 Cursor IDE + 使用 enterprise Profile
harness activate --agent cursor --profile enterprise

# 跳过安装（已安装过），只部署 Profile 到 Copilot CLI
harness activate --skip-install --skip-mcp --skip-skills --skip-init --agent copilot-cli
```

## harness deactivate — 还原项目配置

```bash
harness deactivate
```

还原项目配置到激活前的状态——只移除 harness 写入的项目级配置，不影响 pip 包安装。

还原清单：

| 步骤 | 说明 |
|------|------|
| 清理 `.claude/settings.local.json` | 移除 harness hooks 条目 + `env.HARNESS_COOK_ROOT`；空壳文件直接删除 |
| 清理 `.claude/settings.json` | 移除 harness hooks 条目 + MCP 配置 + `env.HARNESS_COOK_ROOT`；空壳文件直接删除 |
| 清理 `.gitignore` | 移除 harness 追加的条目（`.harness/env`、`.harness/audit/` 等） |
| 删除 `.harness/` | 彻底删除整个 `.harness/` 目录（含 profiles、audit、cache 等） |
| 汇总输出 | 显示还原结果摘要 |

::: warning 安全边界
deactivate 只删除 harness 创建的空壳文件和 `.harness/` 目录。如果 `.claude/settings.json` 中还有用户自己的配置（hooks、permissions、mcpServers），这些文件会被保留，绝不会删除用户内容。
:::

## harness log — 查看执行日志

```bash
harness log [query] [--type TYPE] [--limit N] [--follow] [--output FORMAT]
```

查看 harness-cook 的执行记录：hooks 触发、skills 执行、gates 检查。

| 参数 | 说明 |
|------|------|
| `query` | 搜索关键词（可选） |
| `--type` | 按事件类型过滤：`hook` / `skill` / `gate` / `session` / `audit` |
| `--limit` | 显示条数（默认 20） |
| `--follow` | 实时跟踪（类似 `tail -f`） |
| `--output` | 输出格式：`table`（默认）/ `json` |

## harness dashboard — 启动可视化界面

```bash
harness dashboard [--host HOST] [--port PORT] [--reload]
```

启动 FastAPI Dashboard 服务，提供 Web UI 查看审计、Skills、Profile、合规、引擎集成状态等信息。

浏览器访问 `http://localhost:8765` 查看 Dashboard。

## harness plan — 可视化 DAG 工作流

```bash
harness plan <workflow.yaml> [--format tree|dot|json] [--show-gates]
```

解析 YAML 工作流文件，输出 DAG 拓扑图与执行顺序。

三种输出格式：`tree`（默认）、`dot`（Graphviz）、`json`。

## harness run — 执行编排工作流

```bash
harness run <workflow.yaml> [--dry-run] [--gate-mode strict|hybrid|loose] [--max-retries 2]
```

执行 DAG 工作流。

`--dry-run` 只做拓扑验证和 Agent 检查，不实际调用 `execute()`。

`--gate-mode` 选项：`strict`（全阻断）、`hybrid`（高严重性阻断）、`loose`（仅记录）。

## harness check — 合规/质量扫描

```bash
harness check [path] [--pack security|coding|data|devops] [--severity critical|high|medium|low] [--fix]
```

合规/质量扫描——扫描指定路径的文件，执行规则检查。

内置规则包选项：

| 包名 | 检查方向 |
|------|----------|
| `coding` | 代码风格与质量 |
| `security` | 安全漏洞检测 |
| `data` | 数据隐私合规 |
| `devops` | 运维规范约束 |

不指定 `--pack` 时扫描所有包（26 条规则全量检查）。

**引擎路由说明：** ComplianceEngine 内部通过 MatcherRegistry 路由规则到对应 checker。Profile 配置 `compliance.engines` 和 `language_routing` 可指定外部引擎和语言感知路由。

## harness audit — 查看审计记录

```bash
harness audit [--query QUERY] [--session SESSION_ID] [--agent AGENT_ID] [--limit 20] [--format table|json]
```

查看审计记录。

输出格式：表格（默认）或 JSON。

**审计后端说明：** AuditEngine 内部使用 IAuditStore Protocol。默认 AuditStore（本地 SQLite），Profile 配置 `audit.backends` 可叠加 Langfuse/Arize/Datadog/Helicone。

## harness version — 查看版本号

```bash
harness version
```

## 全局选项

| 选项 | 说明 |
|------|------|
| `--verbose` / `-v` | 显示详细日志（DEBUG 级别） |
| `--quiet` / `-q` | 只显示错误日志 |
| `--log-level` | 日志级别：`DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `--log-format` | 日志格式：`text`（默认）/ `json` |
| `--timeout` | 全局超时（秒），0=不限 |

## 退出码

| 退出码 | 含义 |
|--------|------|
| `0` | 成功 |
| `1` | 失败 |
| `2` | 文件不存在 |
| `124` | 趏时 |
| `130` | 用户中断（Ctrl+C） |

## 工作流定义文件格式

CLI 命令接受 YAML 或 JSON 格式的工作流定义。基本结构：

```yaml
workflow:
  id: wf-example
  name: 示例工作流
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

::: tip
YAML 中的边字段使用 `from_node` / `to_node`。旧格式中的 `source` / `target` 也能解析（bridge.py 双兼容），但推荐使用新字段名。
:::

## 下一步

- [Skill 插槽点指南](/guide/skill-slots) —— 17 个插槽点的详细说明
- [Dashboard 指南](/guide/dashboard) —— 可视化界面详解 + 引擎集成状态
- [MCP Server 指南](/guide/mcp-server) —— 25 个 MCP Tools + 引擎路由

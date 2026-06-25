# Adapter 部署

本教程展示如何使用 HarnessBridge 将 Profile 配置一键部署到不同的 Agent 平台，理解 5 个适配器的差异、优先级链选择逻辑、Profile 与 Adapter 的正交关系，以及各平台配置文件的位置。

## Step 1: 理解适配器模式

HarnessBridge 通过适配器模式支持多种 Agent 平台——将 harness 的 hooks/skills/gates 配置翻译为目标平台的原生格式：

```
Profile (hooks + gates + skills)
    ↓ HarnessBridge
    ↓ 适配器选择（优先级链）
    ↓ IAgentAdapter.translate_hooks()
    ↓ IAgentAdapter.merge_settings()
    → 目标平台配置文件
```

配置文件对照表见 [Adapter 快速上手](/guide/adapter-quickstart#配置文件对照表)。

## Step 2: 有-hooks vs 无-hooks Agent

有-hooks vs 无-hooks 的区别见 [Adapter 快速上手](/guide/adapter-quickstart#有-hooks-vs-无-hooks-agent)。部署实操中只需关注：`supports_hooks` 决定了 Gate Prompt 强度——有-hooks 用 mild，无-hooks 用 mandatory。

## Step 3: 一键部署

最常见的方式是通过 MCP 工具 `harness_bridge_deploy` 部署：

```json
// 部署到 Claude Code（默认）
harness_bridge_deploy({
  "adapter": "claude-code"
})
// → 写入 .claude/settings.json，hooks 自动触发

// 部署到 Copilot CLI
harness_bridge_deploy({
  "adapter": "copilot-cli"
})
// → 写入 .copilot/config.json，hooks + MCP server 定义

// 部署到 Cursor
harness_bridge_deploy({
  "adapter": "cursor"
})
// → 写入 .cursor/mcp.json，MCP server 定义 + Gate Prompt
```

返回值：

```json
{
  "success": true,
  "profile": "default",
  "adapter": "claude-code",
  "supports_hooks": true,
  "prompt_strength": "mild",
  "settings_path": "/projects/my-api/.claude/settings.json",
  "hooks_deployed": 5,
  "gate_mode": "hybrid",
  "gate_checks": 3,
  "skills_available": 12,
  "git_hook_installed": true,
  "status": "deployed"
}
```

也可以用 Python API 部署：

```python
from harness.bridge import HarnessBridge, get_bridge
from harness.config import load_profile, resolve_active_profile

# 加载 Profile
profile = load_profile(resolve_active_profile())

# 部署
bridge = get_bridge()
result = bridge.deploy(profile)
print(f"适配器: {result['adapter']}")
print(f"配置路径: {result['settings_path']}")
print(f"hooks 数量: {result['hooks_deployed']}")
```

## Step 4: 适配器优先级链

适配器选择遵循 6 级优先级链（与 [适配器快速开始](/guide/adapter-quickstart)、[CLI 指南](/cli/activate) 一致）：

```
1. --agent CLI 参数（最高优先级，显式覆盖）
   ↓ 如果未指定
2. HARNESS_ADAPTER 环境变量（CI/自动化覆盖）
   ↓ 如果未指定
3. .harness/env 中 HARNESS_ADAPTER=（机器级持久化，activate 写入，gitignored）
   ↓ 如果未指定
4. .harness/active_adapter 标记文件（项目级持久化，提交到 Git 团队共享）
   ↓ 如果未指定
5. Profile.default_agent / Profile.adapter 字段
   ↓ 如果未指定
6. 默认值 "claude-code"
```

> 前 4 级在 CLI 层（`harness activate`）解析为 `adapter_name` 传入 `Bridge.deploy`；deploy 内部仅承担 5-6 级降级（见下方代码）。完整链详见 [CLI 指南](/cli/activate)。

```python
# HarnessBridge.deploy() 中的适配器选择逻辑
if adapter_name:
    # 外部显式指定 → 最高优先级
    resolved_adapter = adapter_name
else:
    # 降级到 Profile 声明 → 最终回退到 claude-code
    resolved_adapter = (
        getattr(profile, 'default_agent', None)
        or getattr(profile, 'adapter', None)
        or "claude-code"
    )
```

这意味着你可以在 Profile 中声明默认适配器，但在部署时用 `--agent` 参数临时切换到其他平台。

## Step 5: Profile 与 Adapter 正交关系

**Profile 和 Adapter 是正交的**——Profile 定义治理规则（hooks/gates/skills），Adapter 定义目标平台格式。同一个 Profile 可以部署到任意平台：

```
Profile "default" (5 hooks, 3 gate checks, hybrid mode)
    ├── deploy(adapter=claude-code) → settings.json + hooks 自动触发
    ├── deploy(adapter=copilot-cli) → config.json + hooks + MCP server
    ├── deploy(adapter=cursor)      → mcp.json + MCP server + 强 Gate Prompt
    ├── deploy(adapter=hermes)      → config.yaml + MCP server + 强 Gate Prompt
    └── deploy(adapter=openai)      → function definitions（无本地配置）
```

同一个治理规则在不同平台上的表现形式不同，但治理效果等价：
- 有-hooks 平台：hooks 自动执行 → 检查在 Agent 行为前触发
- 无-hooks 平台：Gate Prompt 强提示 + git hook → 检查在 Agent 生成内容后拦截

## Step 6: 各平台配置详解

### Claude Code

```python
from harness.adapters import ClaudeCodeAdapter

adapter = ClaudeCodeAdapter()

# 配置路径——项目级
path = adapter.get_settings_path("/projects/my-api")
# → "/projects/my-api/.claude/settings.json"

# supports_hooks = True → hooks 写入 settings.json
# 翻译格式：
# 输入: {"session_start": [{"type": "script", "command": "lint.sh"}]}
# 输出: {"SessionStart": [{"matcher": "", "hooks": [{"type": "command", "command": "..."}]}]}
```

hook 点映射——harness 概念到 Claude Code 原生事件：

| harness hook 点 | Claude Code 原生事件 |
|----------------|---------------------|
| `session_start` | SessionStart |
| `session_end` | SessionEnd |
| `pre_tool_use` | PreToolUse |
| `post_tool_use` | PostToolUse |
| `on_error` | PostToolUseFailure |
| `user_prompt_submit` | UserPromptSubmit |

### Copilot CLI

```python
from harness.adapters import CopilotCLIAdapter

adapter = CopilotCLIAdapter()

# 配置路径——项目级
path = adapter.get_settings_path("/projects/my-api")
# → "/projects/my-api/.copilot/config.json"

# supports_hooks = True → hooks + MCP server 定义同时写入
# 输出格式: {"hooks": {...}, "mcpServers": {"harness-cook": {...}}}
```

hook 点映射：

| harness hook 点 | Copilot CLI hook 点 |
|----------------|---------------------|
| `session_start` | on_session_start |
| `session_end` | on_session_end |
| `pre_tool_use` | on_pre_tool_use |
| `post_tool_use` | on_post_tool_use |
| `pre_execute` | on_pre_execute |

### Hermes

```python
from harness.adapters import HermesAdapter

adapter = HermesAdapter()

# 配置路径——全局级（Hermes 不支持项目级配置）
path = adapter.get_settings_path("/projects/my-api")
# → ~/.hermes/config.yaml（不受 project_dir 影响）

# supports_hooks = False → MCP server 定义 + Gate Prompt
# 输出格式: {"mcpServers": {"harness-cook": {...}}, "harness_metadata": {...}}
# 全局配置是 YAML 格式
```

Hermes 治理路径：全局注册 MCP Server → MCP Server 运行时通过工作目录定位项目 → 读取 `.harness/` 获取项目级治理规则。

配置路径优先级：`HERMES_CONFIG_PATH` 环境变量 > `~/.hermes/config.yaml`

### Cursor

```python
from harness.adapters import CursorAdapter

adapter = CursorAdapter()

# 配置路径——项目级
path = adapter.get_settings_path("/projects/my-api")
# → "/projects/my-api/.cursor/mcp.json"

# supports_hooks = False → MCP server 定义 + Gate Prompt
# 输出格式: {"mcpServers": {"harness-cook": {...}}, "harness_metadata": {...}}
```

Cursor 治理路径与 Hermes 一致：MCP Server + Gate Prompt + git pre-commit hook。

### OpenAI

```python
from harness.adapters import OpenAIAdapter

adapter = OpenAIAdapter()

# 配置路径——无本地配置
path = adapter.get_settings_path("/projects/my-api")
# → "" (空字符串)

# supports_hooks = False → function definitions
# 输出格式: {"functions": [{"name": "hook_session_start", ...}]}
# hooks 被翻译为 OpenAI function calling 格式
```

::: warning
OpenAI 适配器是验证适配器模式可行性的示例实现，不是完整的 OpenAI 集成。实际使用需要 API key 和 HTTP 请求配置。
:::

## Step 7: Gate Prompt 注入

部署时，Bridge 将 Gate 检查指令注入到 `CLAUDE.md`：

**有-hooks Agent（mild）**：

```
[harness gate] 门禁模式=hybrid，检查项: sec-001, sec-002。
未通过检查的产出物不允许提交。
每次代码变更后，运行 `harness check .` 验证合规性。
```

**无-hooks Agent（mandatory）**：

```
[harness gate · MANDATORY] 门禁模式=hybrid，检查项: sec-001, sec-002。
**未通过检查的产出物不允许提交。**
每次代码变更后，你 MUST 运行 `harness check <目标文件路径>` 验证合规性。
文件写入操作前，你 MUST 先调用 `harness_check` 工具对目标路径扫描。
如果 `harness_check` 返回违规，你 MUST 先修复再继续。
违反此规则的产出物将被 git pre-commit hook 拦截。
```

## Step 8: git pre-commit hook

所有适配器都会安装 git pre-commit hook 作为兜底防线——不管谁提交、怎么提交，不合规的变更都会被拦截：

```python
# Bridge 自动安装 git hook
bridge = get_bridge()
result = bridge.deploy(profile)
print(f"git hook 已安装: {result['git_hook_installed']}")  # → True/False
```

安装策略：
- 项目有 `.git/hooks/` → 复制 harness pre-commit hook 脚本
- 已有 pre-commit hook → 在末尾追加 harness 检查（不覆盖原有内容）
- 已有 harness 标记 → 替换旧版本

## Step 9: 配置合并策略

Bridge 写入配置时，不是覆盖而是合并——保留用户已有配置：

| 适配器 | 合并策略 |
|--------|---------|
| ClaudeCodeAdapter | hooks 按 matcher 去重，harness hook 覆盖同 matcher 的旧版本 |
| CopilotCLIAdapter | hooks 附加到末尾（不去重），MCP server 覆盖已有定义 |
| HermesAdapter | MCP server 覆盖已有定义，metadata 追加合并 |
| CursorAdapter | MCP server 覆盖已有定义，metadata 追加合并 |
| OpenAIAdapter | functions 按 name 去重，新 function 附加 |

```python
# 读取现有配置 → 合并 → 写入
existing = bridge._read_settings(settings_path, adapter_name="claude-code")
merged = adapter.merge_settings(existing, hooks_config, harness_root=harness_root)
settings_path.write_text(json.dumps(merged, indent=2))
```

::: warning
Hermes 配置是 YAML 格式，Bridge 使用 `yaml.safe_load` 读取和 `yaml.dump` 写入，不会丢失用户原有的 YAML 字段。其他适配器使用 JSON 格式。
:::

## Step 10: 查看部署状态

```python
bridge = get_bridge()
status = bridge.status()

print(f"已部署: {status['deployed']}")
if status['deployed']:
    print(f"适配器: {status['adapter']}")
    print(f"配置路径: {status['settings_path']}")
    print(f"hook 类型: {status['hook_types']}")
    print(f"总 hooks 数: {status['total_hooks']}")
    print(f"含 harness hooks: {status['has_harness_hooks']}")
```

判断逻辑：
1. 检查 `.harness/` 目录是否存在（所有适配器的通用标记）
2. 对有-hooks 适配器：检查项目级配置文件是否含 harness hooks
3. 对无-hooks 适配器：`.harness/` 目录存在即视为已部署
4. 无 `.harness/` 目录 → 项目未部署

## Step 11: 完整部署流程

```json
// 1. 列出可用 Profile
harness_profile_list({})
// → {"profiles": ["default", "strict", "loose"]}

// 2. 加载 Profile
harness_profile_load({"name": "default"})
// → {"name": "default", "hooks": {...}, "gate_mode": "hybrid", ...}

// 3. 部署到指定平台
harness_bridge_deploy({
  "profile_name": "default",
  "adapter": "claude-code"
})
// → {"success": true, "settings_path": "...", "hooks_deployed": 5, ...}

// 4. 查看部署状态
harness_status({})
// → {"deployment": {"deployed": true, "adapter": "claude-code", ...}}
```

下一步 → [Pipeline 编排](./pipeline) | [降级与回滚](./downgrade-rollback)

# Copilot CLI 使用指南

> harness-cook + Copilot CLI = hooks 自动触发 + MCP 双通道，GitHub 生态开发者首选

**快速导航**：[🆚 各平台对比](./agent-platforms) · [🤖 Claude Code 指南](./agent-claude-code) · [🦅 Hermes 指南](./agent-hermes)

---

## 激活方式

```bash
python3 packages/cli/harness_cli.py activate --agent copilot-cli
```

---

## 部署了什么

### 1. `.copilot/config.json` — hooks + MCP Server（项目级）

Copilot CLI 是强制性 Agent（`supports_hooks=True`），配置包含两部分：

**hooks 部分**——Copilot CLI 原生 hook 格式：
```json
{
  "hooks": {
    "on_session_start": [
      { "type": "command", "command": "python3 /path/to/harness-cook/packages/hooks/hook-session-init.py" }
    ],
    "on_post_execute": [
      { "type": "command", "command": "python3 /path/to/harness-cook/skills/auto-audit/run-skill.py auto-audit" }
    ]
  }
}
```

**mcpServers 部分**——MCP Server 注册：
```json
{
  "mcpServers": {
    "harness-cook": {
      "command": "python3",
      "args": ["-m", "harness_mcp_server"],
      "env": {
        "HARNESS_COOK_ROOT": "/path/to/harness-cook",
        "PYTHONPATH": "/path/to/harness-cook/packages/mcp"
      }
    }
  }
}
```

---

## 治理如何运作

Copilot CLI 是**强制性 Agent**（`supports_hooks=True`），与 Claude Code 策略一致：

- hooks 在 Agent 执行时自动触发
- Prompt 类型 hook 降级为 MCP 工具调用（Copilot CLI 不支持 prompt hook）
- gate prompt 用 mild 强度
- git pre-commit hook 兜底

---

## 与 Claude Code 的差异

| 维度 | Claude Code | Copilot CLI |
|------|-------------|-------------|
| 配置格式 | `settings.json`（hooks）+ `settings.local.json`（权限） | `config.json`（hooks + mcpServers 合一） |
| Hook 格式 | matcher + hooks 数组 | flat 命令列表（无 matcher） |
| Prompt hook | 支持（SessionStart echo） | 不支持（降级为 MCP 调用） |
| Skill hook | `run-skill.py` 命令 | `run-skill.py` 命令 |
| MCP 权限文件 | `.claude/settings.local.json` | 无 |
| Hook 合并策略 | 按 matcher 去重 | 追加（不去重） |
| 配置层级 | 项目级（`.claude/`） | 项目级（`.copilot/`） |

---

## Hook 点映射

| Profile Hook 点 | Copilot CLI Hook | 说明 |
|----------------|-----------------|------|
| `session_start` | `on_session_start` | ✅ 直接映射 |
| `session_end` | `on_session_end` | ✅ 直接映射 |
| `pre_tool_use` | `on_pre_tool_use` | ✅ 直接映射 |
| `post_tool_use` | `on_post_tool_use` | ✅ 直接映射 |
| `user_prompt_submit` | `on_user_prompt` | ✅ 直接映射 |
| `pre_execute` | `on_pre_execute` | ✅ 直接映射 |
| `post_execute` | `on_post_execute` | ✅ 直接映射 |
| `on_file_change` | `on_file_change` | ✅ 直接映射 |

---

## 常见问题

### 如何还原？

```bash
python3 packages/cli/harness_cli.py deactivate
```

### Copilot CLI 的 hooks 合并方式？

追加合并——harness 的 hooks 附加到末尾，不去重（因为 Copilot CLI 不使用 matcher）。

---

## 相关文档

- [🆚 各平台对比总览](./agent-platforms) — 快速选择适合你的 Agent
- [🤖 Claude Code 使用指南](./agent-claude-code) — 与 Copilot CLI 最接近的平台
- [📖 MCP Server](./mcp-server) — 25 个 MCP 工具的完整参数说明

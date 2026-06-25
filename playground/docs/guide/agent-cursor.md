# Cursor IDE 使用指南

> harness-cook + Cursor = MCP 工具驱动，IDE 内 Agent 的治理集成

**快速导航**：[🆚 各平台对比](./agent-platforms) · [🦅 Hermes 指南](./agent-hermes) · [📖 MCP Server](./mcp-server)

---

## 激活方式

```bash
python3 packages/cli/harness_cli.py activate --agent cursor
```

---

## 部署了什么

### 1. `.cursor/mcp.json` — MCP Server + metadata（项目级）

Cursor 是建议性 Agent（`supports_hooks=False`），与 Hermes 策略一致：

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
  },
  "harness_metadata": {
    "hooks_config": { ... },
    "note": "Cursor does not support hook scripts; governance via MCP tools"
  }
}
```

关键理解：
- **MCP Server 注册是核心产出**——让 Cursor 能调用 harness 工具
- **hooks_config 保留为 metadata**——不自动执行，仅供参考
- **不支持 prompt 类型 hook**——prompt hook 直接跳过

---

## 治理如何运作

与 Hermes 策略一致——MCP 工具驱动 + mandatory prompt + git hook 兜底：

1. **MCP 工具调用**——Cursor Agent 通过 MCP 协议调用 `harness_check` 等工具
2. **Mandatory Prompt**——强提示注入，MUST 语气提醒合规检查
3. **Git Pre-commit Hook**——最终兜底拦截

---

## 与 Hermes 的差异

| 维度 | Hermes | Cursor |
|------|--------|--------|
| 配置位置 | `~/.hermes/config.yaml`（全局） | `.cursor/mcp.json`（项目级） |
| 配置格式 | YAML | JSON |
| Hook metadata | 保留 trigger 映射（`on_session_start` 等） | 不保留 trigger（纯 metadata） |
| Skill metadata | 保留 skill_id | 转换为 `run-skill.py` 命令 |
| 配置共享 | 全局配置，所有项目共享 | 项目级配置，每个项目独立 |

---

## 常见问题

### Cursor 配置是项目级的，如何批量配置？

每个项目需要单独执行 `harness activate --agent cursor`。这与 Hermes 的全局配置不同。

### 如何还原？

```bash
python3 packages/cli/harness_cli.py deactivate
```

---

## 相关文档

- [🆚 各平台对比总览](./agent-platforms) — 快速选择适合你的 Agent
- [🦅 Hermes 使用指南](./agent-hermes) — 与 Cursor 策略最接近的平台
- [📖 MCP Server](./mcp-server) — 25 个 MCP 工具的完整参数说明

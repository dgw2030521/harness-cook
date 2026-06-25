# deactivate — 还原项目配置

> 还原项目配置到 activate 前的状态（不卸载 pip 包）

核心原则：只还原项目级配置（activate 创建的东西），不动 harness 软件本身。pip 包是工具，不是项目配置——deactivate 不卸载软件。

## 用法

```bash
harness deactivate
```

## 六步还原流程

| Step | 名称 | 说明 |
|------|------|------|
| 1/6 | 移除 Skills 链接 | 删除 `~/.claude/skills/` 下指向 harness-cook 的符号链接 |
| 2/6 | 清理全局 MCP 配置 | 移除 `~/.claude/settings.json` 中 `mcpServers.harness-cook` + 删除 `scripts/harness-mcp.sh` |
| 3/6 | 清理项目 hooks + MCP 权限 | 移除 `.claude/settings.local.json` 中 harness hooks + MCP 工具权限 + `env.HARNESS_COOK_ROOT`（空壳则删文件） |
| 4/6 | 清理项目 settings.json | 移除 `.claude/settings.json` 中 Bridge 写入的 harness hooks + `env.HARNESS_COOK_ROOT`（空壳则删文件） |
| 5/6 | 清理非 Claude Code 适配器配置 | Hermes: 移除 `~/.hermes/config.yaml` 中 harness 条目；Cursor: 移除 `.cursor/mcp.json` 中 harness 条目；Copilot CLI: 移除 `~/.copilot/config.json` 中 harness 条目 |
| 6/6 | 删除 .harness/ + 清理 .gitignore | 删除整个 `.harness/` 目录 + 移除 `.gitignore` 中 `.harness/env` 和 `.harness/audit/` 条目 |

## 安全边界

- 只删除 harness 写入的条目和 harness 创建的空壳文件
- 绝不动用户原有的内容（其他 MCP 服务器、其他 hooks 等）
- 清理后如果配置文件只剩 `{}`，直接删除文件而非留空壳
- 不卸载 pip 包（`harness` 命令仍可用）

---

← [activate](/cli/activate) · [命令总览](/cli/) · → [update](/cli/update)

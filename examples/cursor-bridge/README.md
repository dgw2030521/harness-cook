# Cursor Bridge 示例

将 harness-cook Profile 配置部署到 Cursor IDE 平台——让 Cursor 也受治理约束。

## 定位

Cursor IDE 是支持 AI 辅助编程的编辑器。通过 `CursorAdapter` 适配器，harness-cook Profile 的 hook 配置可翻译为 Cursor 的 MCP 配置文件，实现治理管控跨平台覆盖。

**注意**：Cursor IDE 不支持 hook 脚本执行，治理检查通过 MCP 工具调用（`harness_check`、`harness_guardrails_check` 等）完成。

## 运行

```bash
cd examples/cursor-bridge
python demo_cursor_adapter.py
```

## 输出内容

| 步骤 | 说明 |
|------|------|
| 1. 适配器基本信息 | adapter name、settings path |
| 2. 翻译 hooks | Profile hooks → Cursor `.cursor/mcp.json` 格式（MCP server 定义 + harness_metadata） |
| 3. 合并到现有配置 | 与已有的 MCP servers 合并，不覆盖 |
| 4. 配置文件路径 | 写入 `.cursor/mcp.json` |

## 核心逻辑

```python
from harness.adapters.cursor import CursorAdapter

adapter = CursorAdapter()
result = adapter.translate_hooks(SAMPLE_HOOKS, harness_root="/opt/harness-cook")
merged = adapter.merge_settings(existing_config, result)
```

## 与 Copilot CLI Bridge 的区别

| 维度 | Copilot CLI Bridge | Cursor Bridge |
|------|-------------------|---------------|
| 配置文件 | `.copilot/config.json` | `.cursor/mcp.json` |
| hook 支持 | ✅ 支持脚本执行 | ❌ 不支持脚本执行，仅 MCP 工具调用 |
| 治理方式 | MCP + hook 脚本 | MCP 工具调用（harness_check 等） |

## 适用场景

- 团队使用 Cursor IDE 作为开发环境，需要注入合规/护栏检查
- 多平台统一治理——Claude Code + Cursor 共用同一套 Profile 配置

# Copilot CLI Bridge 示例

将 harness-cook Profile 配置部署到 GitHub Copilot CLI 平台——让 Copilot CLI 也受治理约束。

## 定位

Copilot CLI 是 GitHub 的命令行 AI 助手。通过 `CopilotCLIAdapter` 适配器，harness-cook Profile 的 hook 配置可翻译为 Copilot CLI 的 MCP server 定义和配置文件，实现治理管控跨平台覆盖。

## 运行

```bash
cd examples/copilot-cli-bridge
python demo_copilot_cli_adapter.py
```

## 输出内容

| 步骤 | 说明 |
|------|------|
| 1. 适配器基本信息 | adapter name、settings path |
| 2. 翻译 hooks | Profile hooks → Copilot CLI config.json 格式（MCP server 定义 + hook 配置映射） |
| 3. 合并到现有配置 | 与已有的 MCP servers 合并，不覆盖 |
| 4. 配置文件路径 | 写入 `.copilot/config.json` |

## 核心逻辑

```python
from harness.adapters.copilot_cli import CopilotCLIAdapter

adapter = CopilotCLIAdapter()
result = adapter.translate_hooks(SAMPLE_HOOKS, harness_root="/opt/harness-cook")
merged = adapter.merge_settings(existing_config, result)
```

## 适用场景

- 团队使用 Copilot CLI 作为 AI 助手，需要注入合规/护栏检查
- 多平台统一治理——Claude Code + Copilot CLI 共用同一套 Profile 配置

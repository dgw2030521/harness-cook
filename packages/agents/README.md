# harness agents

harness-cook 的 Agent 适配器集合。完整介绍见根目录 [README](../../README.md)。

## 设计

采用 S-1 插件机制：每个适配器一个 `.py` 文件，注册到 `AdapterRegistry`。新增平台只需一个文件，无需改动核心。

## 已实现适配器

| 适配器 | 目标平台 | hooks 能力 | 治理强度 |
|--------|---------|-----------|---------|
| `claude-code` | Claude Code | 原生 hooks | 强制 |
| `copilot-cli` | GitHub Copilot CLI | 有 hook 概念 | 强制 |
| `hermes` | Hermes | 无原生 hooks | 经 MCP Server |
| `cursor` | Cursor IDE | 无 hooks | 经 MCP Server |
| `openai` | OpenAI / Codex | 无 hooks | 经 function calling |

## 新增适配器

1. 在本目录新增 `<platform>.py`
2. 实现 Adapter 协议（translate / deploy / undeploy 等）
3. 注册到 `AdapterRegistry`

参考 [docs/35-适配器架构与多Agent部署策略-20260615.md](../../docs/35-适配器架构与多Agent部署策略-20260615.md)。

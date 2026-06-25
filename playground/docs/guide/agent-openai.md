# OpenAI/Codex 使用指南

> ⚠️ **验证性实现**——当前 OpenAI 适配器是架构验证示例，不是完整的 OpenAI 集成。需要 API key、HTTP 请求等配套才能实际使用。

**快速导航**：[🆚 各平台对比](./agent-platforms) · [🦅 Hermes 指南](./agent-hermes) · [📖 MCP Server](./mcp-server)

---

## 当前状态

OpenAI 适配器（`supports_hooks=False`）当前定位为**验证适配器模式可行性的示例实现**，不是完整的 OpenAI/Codex 集成。主要限制：

- 无本地配置文件——function calling 定义需在每次 API 请求中传入
- 无 MCP Server 连接——治理通过 function calling 定义而非 MCP 协议
- 需要手动管理 API key 和 HTTP 请求
- 尚未经过完整的功能验证

---

## 激活方式

```bash
python3 packages/cli/harness_cli.py activate --agent openai
```

---

## 部署了什么

### 无本地配置文件

OpenAI 适配器的 `get_settings_path()` 返回空字符串——没有本地配置文件需要写入。

### Function Calling 定义

`translate_hooks` 将 Profile hooks 转换为 OpenAI function calling 格式：

```json
[
  {
    "name": "hook_session_start",
    "description": "Execute session start hook: python3 init.py",
    "parameters": {
      "type": "object",
      "properties": {},
      "required": []
    },
    "metadata": {
      "original_type": "script",
      "original_command": "python3 init.py",
      "hook_point": "session_start"
    }
  },
  {
    "name": "skill_auto_audit",
    "description": "Execute skill: auto-audit",
    "parameters": {
      "type": "object",
      "properties": { "skill_id": { "type": "string", "const": "auto-audit" } },
      "required": []
    },
    "metadata": {
      "original_type": "skill",
      "skill_id": "auto-audit",
      "hook_point": "post_execute"
    }
  }
]
```

---

## 治理如何运作

建议性 Agent（`supports_hooks=False`），与 Hermes/Cursor 等略一致但形式不同：

- **Function Calling 定义**而非 MCP Server
- Agent 通过 OpenAI API 调用函数时触发治理
- mandatory prompt + git hook 兜底

---

## 与其他适配器的核心差异

| 维度 | Hermes/Cursor | OpenAI |
|------|--------------|--------|
| 工具协议 | MCP Server | function calling（API 请求内嵌） |
| 配置持久化 | 本地文件（YAML/JSON） | 无本地文件 |
| 工具注册 | MCP Server 注册一次 | 每次请求传入 |
| 适用场景 | 本地 Agent 运行 | API 纯编程调用 |

---

## 相关文档

- [🆚 各平台对比总览](./agent-platforms) — 快速选择适合你的 Agent
- [📖 Bridge 指南](./bridge) — 适配器架构和 function calling 翻译内部原理

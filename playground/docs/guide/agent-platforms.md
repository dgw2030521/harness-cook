# Agent 平台使用指南

> 面向用户——选择你的 Agent 平台，快速了解 harness-cook 为你部署了什么、治理如何运作、有哪些能力可用。

**快速导航**：[🆚 对比总览（本页）](#快速选择) · [🤖 Claude Code](./agent-claude-code) · [🦅 Hermes](./agent-hermes) · [🐙 Copilot CLI](./agent-copilot-cli) · [🖱️ Cursor](./agent-cursor) · [🧪 OpenAI](./agent-openai)

---

## 快速选择

| 维度 | Claude Code | Copilot CLI | Hermes | Cursor | OpenAI |
|------|-------------|-------------|--------|--------|--------|
| 适合谁 | Claude Code 用户 | GitHub Copilot CLI 用户 | Hermes Agent 用户 | Cursor IDE 用户 | OpenAI API 用户 |
| 治理强制度 | **强制**（hooks 自动触发） | **强制**（hooks 自动触发） | 建议性→接近强制（MCP + mandatory prompt） | 建议性→接近强制（MCP + mandatory prompt） | 建议性→接近强制（function calling） |
| Hook 自动触发 | ✅ | ✅ | ❌ | ❌ | ❌ |
| MCP 工具调用 | ✅ 双通道（hooks + MCP） | ✅ 双通道（hooks + MCP） | ✅ 主要通道 | ✅ 主要通道 | ❌ |
| 配置文件 | `.claude/settings.json` | `.copilot/config.json` | `~/.hermes/config.yaml` | `.cursor/mcp.json` | 无本地配置 |
| 配置层级 | 项目级 | 项目级 | **全局**（一次配置，所有项目共享） | 项目级 | 无 |
| Prompt 强度 | mild（轻提示） | mild（轻提示） | **mandatory**（强提示，MUST 语气） | mandatory | mandatory |
| 兜底防线 | hooks + git hook | hooks + git hook | mandatory prompt + git hook | mandatory prompt + git hook | function calling + git hook |
| MCP 权限文件 | `.claude/settings.local.json` | 无 | 无 | 无 | 无 |
| 配置格式 | JSON | JSON | **YAML** | JSON | N/A |
| 推荐场景 | 开发者日常编码 | GitHub 生态开发者 | 企业级多 Agent 编排 | IDE 内嵌 Agent | API 纯编程集成 |

---

## 治理路径对比

### 强制性 Agent（Claude Code / Copilot CLI）

Profile → Bridge deploy → **hooks 写入配置** → Agent 运行时 **自动触发** → 不合规代码无法产出 → git hook 兜底

```mermaid
flowchart LR
    P[Profile] --> B[Bridge deploy]
    B --> H[Hooks 写入配置]
    H --> A[Agent 运行时]
    A --> AT[Hooks 自动触发]
    AT --> S1[合规扫描]
    AT --> S2[PII 检测]
    AT --> S3[任务审计]
    S1 & S2 & S3 --> OK[合规 → 继续] | FAIL[违规 → 拦截]
    OK --> G[git commit → hook 兜底]
    FAIL --> G
```

<details>
<summary>ASCII 原图 — 强制性治理路径</summary>

```
Profile → Bridge deploy → Hooks 写入配置 → Agent 运行时自动触发
                                      ↓
                              合规扫描 → OK → 继续
                              PII 检测  → FAIL → 拦截
                              任务审计  ↓
                                    git commit → pre-commit hook 兜底
```
</details>

**关键特征**：hooks 不可绕过——即使 Agent 想忽略合规检查，hooks 仍然自动执行。

### 建议性 Agent（Hermes / Cursor / OpenAI）

Profile → Bridge deploy → **MCP Server 注册 + mandatory prompt** → Agent **主动调用 MCP 工具** → mandatory prompt 提醒 → git hook 兜底

```mermaid
flowchart LR
    P[Profile] --> B[Bridge deploy]
    B --> M[MCP Server 注册]
    B --> MP[Mandatory Prompt 注入]
    M --> A[Agent 运行时]
    MP --> A
    A --> AC[Agent 主动调用 MCP 工具]
    AC --> H[harness_check]
    AC --> G[harness_guardrails_check]
    H & G --> OK[合规 → 继续] | FAIL[违规 → 修复]
    OK --> GH[git commit → pre-commit hook 兜底]
    FAIL --> GH
```

<details>
<summary>ASCII 原图 — 建议性治理路径</summary>

```
Profile → Bridge deploy → MCP Server 注册 + Mandatory Prompt 注入
                                      ↓
                              Agent 主动调用 MCP 工具
                              harness_check → OK → 继续
                              harness_guardrails_check → FAIL → 修复
                              mandatory prompt → MUST 提醒
                                      ↓
                              git commit → pre-commit hook 兜底拦截
```
</details>

**关键特征**：理论上 Agent 可绕过 prompt（不调用 MCP 工具），但 mandatory prompt 以 MUST 语气强烈提醒，且 git pre-commit hook 是最终兜底。

---

## 各平台完整指南

| 平台 | 核心定位 | 治理机制 | 完整指南 |
|------|---------|---------|---------|
| **Claude Code** | 开发者日常编码，hooks 自动治理 | hooks 自动触发 + mild prompt | [Claude Code 使用指南](./agent-claude-code) |
| **Hermes** | 企业级多 Agent 编排 | MCP 工具驱动 + mandatory prompt | [Hermes 使用指南](./agent-hermes) |
| **Copilot CLI** | GitHub 生态开发者 | hooks 自动触发 + MCP 双通道 | [Copilot CLI 使用指南](./agent-copilot-cli) |
| **Cursor** | IDE 内 Agent 治理集成 | MCP 工具驱动 + mandatory prompt | [Cursor IDE 使用指南](./agent-cursor) |
| **OpenAI** | API 纯编程集成（验证性实现） | function calling 定义 | [OpenAI/Codex 使用指南](./agent-openai) |

---

## 相关文档

- [Bridge 指南](./bridge) — 适配器内部机制、翻译流程、编程式调用
- [MCP Server](./mcp-server) — 25 个 MCP 工具的完整参数说明
- [快速开始](./quick-start) — 一键激活流程
- [配置系统](./config-system) — Profile 分层查找、适配器优先级链
- [Skill 插槽点](./skill-slots) — 17 个插槽点详细说明
- [CLI 指南](./cli) — 所有 CLI 命令详解

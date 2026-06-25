# Bridge 指南

harness-cook Bridge 负责将 Profile 配置翻译成 Agent 原生格式，实现一键部署。

## 概述

Bridge 是 harness-cook 的核心组件之一，职责是：

1. **读取 Profile** — 从 `.harness/profiles/default.yaml` 加载配置
2. **翻译配置** — 将 hooks/skills/gates + 引擎配置翻译成 Agent 原生格式
3. **部署配置** — 通过多适配器写入目标平台配置文件
4. **记录审计** — 每次部署都记录到审计日志

```
Profile YAML → Bridge Deploy → 多适配器 → settings.json / Agent 原生配置
```

## 多平台适配器

Bridge 通过 IAgentAdapter Protocol 支持多平台部署。

> 5 适配器的完整对比（目标平台/有hooks/治理强度/退让策略/prompt强度/部署策略）见 [Agent 平台对比](/guide/agent-platforms)。

### 适配器选择优先级链

Bridge deploy 使用哪个适配器，由 5 级优先级链决定：

| 优先级 | 来源 | 说明 |
|--------|------|------|
| 1️⃣ 最高 | `--agent` CLI 参数 | 用户显式指定（最强覆盖） |
| 2️⃣ | `HARNESS_ADAPTER` 环境变量 | CI/自动化覆盖 |
| 3️⃣ | `.harness/env` 中 `HARNESS_ADAPTER=` | 机器级持久化（activate 写入） |
| 4️⃣ | `.harness/active_adapter` 标记文件 | 项目级持久化选择 |
| 5️⃣ | Profile `agent.adapter` 字段 | 配置声明——作为回退默认值 |
| 6️⃣ 最低 | `"claude-code"` 回退 | 无任何配置时的默认值 |

> **Adapter 与 Profile 正交**：Adapter 是运行时/环境决策（"部署到哪"），Profile 是治理决策（"部署什么规则"）。两者独立解析、互不影响。

```bash
# 显式指定适配器（最高优先级）
harness activate --agent hermes

# 通过环境变量覆盖（CI/自动化）
HARNESS_ADAPTER=cursor harness activate

# 标记文件持久化（团队共享）
echo "hermes" > .harness/active_adapter
```

### Hermes 治理路径

Hermes 不支持原生 hooks 自动触发（`supports_hooks=False`），治理通过 MCP Server 实现：

```
Hermes → 调用 harness_check MCP 工具 → ComplianceEngine 扫描 → 返回违规结果
Hermes → 调用 harness_guardrails_check MCP 工具 → PII 检测 → 返回脱敏/阻断建议
Hermes → 调用 harness_audit MCP 工具 → 查询审计记录 → 治理可观测
```

关键差异：
- **强制性 Agent**（Claude Code / Copilot CLI）：hooks 自动触发 → Agent 无需主动调用 → 不合规代码不会产出
- **建议性 Agent**（Hermes / Cursor / OpenAI）：MCP 工具需主动调用 → Agent 通常遵循但理论上可绕过 → mandatory prompt 提醒 + git pre-commit hook 兜底拦截

### 条件分支部署

Bridge deploy 根据适配器的 `supports_hooks` 属性决定治理策略：

```python
# bridge.py deploy 流程
adapter = get_adapter(adapter_name)

# gate prompt —— 条件分支
prompt_strength = "mild" if adapter.supports_hooks else "mandatory"
gate_prompt = self._translate_gates_to_prompt(mode, checks, strength=prompt_strength)

# mild: "[harness] 建议在关键操作后运行 harness check 验证合规性"
# mandatory: "[MANDATORY] Before ANY file write, MUST call harness_check"
```

### Git Pre-commit Hook 兜底

无论 Agent 是否有 hooks，Bridge deploy 都会自动安装 git pre-commit hook：

```bash
# .git/hooks/pre-commit — 自动安装，幂等操作
[harness] 🔍 正在扫描提交的文件...
# 不通过 → commit 被拒绝
# 通过 → 放行
```

- **强制性 Agent**：hooks 自动触发 + git hook 兜底 = 双保险
- **建议性 Agent**：mandatory prompt 提示 + git hook 兜底 = 事前提示 + 事后拦截
- 所有 Agent 的不合规代码都无法通过 git commit

## 一键部署

### 通过 CLI 部署

```bash
# 激活时自动部署（默认使用 ClaudeCodeAdapter）
harness activate

# 或通过 MCP 工具部署
# harness_bridge_deploy(profile_name="default")
```

### 部署结果

```python
{
    "profile": "default",
    "adapter": "claude-code",
    "supports_hooks": True,
    "prompt_strength": "mild",
    "settings_path": ".claude/settings.json",
    "hooks_deployed": 3,
    "gate_checks": 2,
    "skills_available": 4,
    "git_hook_installed": True,
    "status": "deployed"
}
```

## Hook 类型

Bridge 支持三种 hook 类型：

### 1. Script 类型

直接执行 Python 脚本。Bridge deploy 时 `resolve_hook_command()` 将内置路径转换为绝对路径（使用外部传入的 `harness_root`），确保命令指向 harness-cook 正确的安装目录。

```yaml
hooks:
  session_start:
    - type: script
      command: "python3 packages/hooks/hook-session-init.py"
```

部署后实际写入 settings.json 的命令：
```json
{"type": "command", "command": "python3 /absolute/path/to/harness-cook/packages/hooks/hook-session-init.py"}
```

### 2. Skill 类型

通过 Skill Registry 执行 Skill。Bridge deploy 时 `resolve_hook_command()` 将 `run-skill.py` 转换为绝对路径。

```yaml
hooks:
  post_execute:
    - type: skill
      skill_id: auto-audit
```

部署后实际写入的命令：
```json
{"type": "command", "command": "python3 /absolute/path/to/harness-cook/scripts/run-skill.py auto-audit"}
```

### 3. Prompt 类型

注入系统提示词（仅 SessionStart 支持）。

```yaml
hooks:
  session_start:
    - type: prompt
      message: "[harness] 已激活，请注意安全检查"
```

## Hook 点映射

Bridge 将 Profile 中的 hook 点映射到 Agent 平台的原生 hook 类型：

| Profile Hook 点 | Claude Code Hook | 说明 |
|----------------|------------------|------|
| `session_start` | `SessionStart` | ✅ 直接映射 |
| `session_end` | `SessionEnd` | ✅ 直接映射 |
| `pre_tool_use` | `PreToolUse` | ✅ 直接映射 |
| `post_tool_use` | `PostToolUse` | ✅ 直接映射 |
| `user_prompt_submit` | `UserPromptSubmit` | ✅ 直接映射 |
| `pre_execute` | `PreToolUse` | 映射到工具使用前 |
| `post_execute` | `PostToolUse` | 映射到工具使用后 |
| `on_file_change` | `PostToolUse` + matcher | 通过 matcher 过滤 |

## Profile 配置扩展（治理集成总线）

Profile 现在支持引擎配置字段——通过一份 YAML 声明治理策略和引擎选择：

```yaml
# .harness/profiles/default.yaml
profile:
  name: default
  description: 标准开发流程配置

agent:
  adapter: claude-code

# ─── 护栏引擎（可选替换）───
guardrails:
  engine: builtin         # builtin | guardrails-ai | nemo | llama-guard | helicone
  config: {}

# ─── 合规引擎（可选替换或叠加）───
compliance:
  engines: [builtin]      # builtin | sonarqube | opa | archunit | dep_cruiser
  language_routing:
    java: archunit
    javascript: dep_cruiser
    typescript: dep_cruiser
  config: {}

# ─── 审计后端（可叠加）───
audit:
  backends: [local]       # local | langfuse | arize | datadog | helicone
  trace:
    format: builtin       # builtin | otel-json
    collector_url: ""
  config: {}

# ─── 门禁（核心护城河，不委托）───
gates:
  default_mode: hybrid
  checks:
    - id: no-secrets
      enabled: true
    - id: no-eval
      enabled: true

hooks:
  session_start:
    - type: script
      command: "python3 packages/hooks/hook-session-init.py"
  post_execute:
    - type: skill
      skill_id: auto-audit
  session_end:
    - type: script
      command: "python3 packages/hooks/hook-task-audit.py"
```

引擎配置字段全部默认 None → 向后兼容，现有 Profile YAML 无需改动。

## 编程式调用

```python
from harness.config import load_profile
from harness.bridge import HarnessBridge

# 加载 Profile
profile = load_profile('default', profiles_dir='.harness/profiles')

# 创建 Bridge
bridge = HarnessBridge()

# 部署 — harness_root 参数优先外部传入，避免 resolve_harness_root() cwd fallback 不准确
result = bridge.deploy(
    profile,
    project_dir='/path/to/project',
    harness_root='/path/to/harness-cook'  # 优先外部传入，确保 hook 命令路径正确
)

# 查看状态
status = bridge.status(project_dir='/path/to/project')
print(f"Deployed: {status['deployed']}")
print(f"Hooks: {status['hook_types']}")
print(f"Adapter: {status['adapter']}")
```

::: tip harness_root 参数说明
`bridge.deploy()` 的 `harness_root` 参数用于指定 harness-cook 的安装目录。激活时由 `activate.py` 外部传入正确路径，确保 `resolve_hook_command()` 生成的 hook 命令使用绝对路径指向正确的安装目录。不传入时自动通过 `resolve_harness_root()` 检测（依赖 `.harness/env` 文件或 cwd fallback），但在 `.harness/env` 尚未创建的激活流程中不可靠。
:::

## 与 Hermes Bridge 的关系

harness-cook 有两个 Bridge：

| Bridge | 位置 | 职责 |
|--------|------|------|
| **HarnessBridge** | `packages/core/harness/bridge.py` | Profile → 多平台 Agent 原生配置 |
| **Hermes Bridge** | `skills/harness-bridge/bridge.py` | Hermes Agent → harness API |

**HarnessBridge** 是部署工具，负责将 Profile 配置翻译成 Agent 原生格式。

**Hermes Bridge** 是运行时桥接，让 Hermes Agent 通过 CLI 调用 harness API。

两者职责不同，互不冲突。

## 下一步

- [Skill 插槽点指南](/guide/skill-slots) —— 17 个插槽点的详细说明
- [Agent 平台使用指南](/guide/agent-platforms) —— 各 Agent 平台的完整使用参考（激活、治理、工具、流程）
- [快速开始](/guide/quick-start) —— 一键激活流程
- [核心概念](/guide/core-concepts) —— Integrations 子包、IAuditStore、引擎路由

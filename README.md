# harness-cook — Agent 治理集成总线

[简体中文](README.md) | [English](README.en.md)

> **Hooks 定约束，Skills 定步骤，Agents 定角色。**

harness-cook 是一个 **Agent 治理集成总线**——为 Claude Code 等 AI Agent 提供声明式配置、一键部署、可观测的管控能力。

## 支持的 Agent 平台

harness-cook 确实用了适配器模式，5 个适配器覆盖了不同的策略层级：

| 适配器 | 目标平台 | 有 hooks？ | 治理强度 | 退让策略 | Prompt 强度 | 部署策略 |
|--------|---------|----------|---------|---------|-----------|---------|
| `claude-code` | **Claude Code** ✅ | ✅ 原生 hooks | **强制性** | COOPERATIVE | mild | hooks → settings.json 自动触发 |
| `copilot-cli` | **GitHub Copilot CLI** ✅ | ✅ 有 hook 概念 | **强制性** | COOPERATIVE | mild | hooks + MCP 双通道 |
| `hermes` | **Hermes** ✅ | ❌ 无原生 hooks | 建议性→接近强制 | FALLBACK | **mandatory** | 治理通过 MCP Server 工具 |
| `cursor` | **Cursor IDE** 🔶 | ❌ 无 hooks | 建议性→接近强制 | FALLBACK | **mandatory** | 仅 MCP server + metadata |
| `openai` | **OpenAI/Codex** 🔶 | ❌ 无 hooks | 建议性→接近强制 | FALLBACK | **mandatory** | function calling 定义 |

> ✅ = 治理可自动强制执行 🔶 = 治理靠 mandatory prompt + MCP 工具（Agent 通常遵循但理论上可绕过）
> **退让策略（S-5）**：ENHANCEMENT = 平台有完整原生护栏（redact+block），harness 退让为可选增强；COOPERATIVE = 平台有部分能力（如 block），harness 补充不覆盖场景；FALLBACK = 平台无等价能力，harness 完全负责。当前 5 个适配器均 `supports_realtime_redact=False`，实际落入 COOPERATIVE（claude-code/copilot-cli，有 realtime_block）或 FALLBACK（hermes/cursor/openai）；ENHANCEMENT 分支保留作演进预留，待出现支持原生实时脱敏的平台时启用。
> **Git Hook 兜底**：所有 Agent 都自动安装 git pre-commit hook，不合规代码无法通过 commit（双保险）

**Profile 中指定适配器**：

```yaml
agent:
  adapter: claude-code  # 可选: claude-code | copilot-cli | hermes | cursor | openai
```

## 文档

- **在线文档站**：见 `playground/docs/`（VitePress 源码），本地预览 `pnpm dev:docs`
- **设计分析文档**：见 [docs/](docs/) 目录（编号归档的架构与产品分析）
- **变更日志**：见 [CHANGELOG.md](CHANGELOG.md)

## 设计目标

### 问题

AI Agent（如 Claude Code）能力强大，但缺乏结构化的管控：
- hooks/skills 分散在手动编辑的配置文件中，无法统一管理
- 不同项目需要不同的管控策略，但没有可切换的 Profile
- Agent 执行了什么、结果如何，缺乏可观测性
- 没有标准化的"安装/卸载"流程

### 解决方案

harness-cook 提供三件事：

1. **声明式配置** — 通过 YAML 文件定义 hooks/skills/gates，而不是手写 settings.json
2. **一键部署** — 一条命令将配置翻译成 Agent 原生格式并写入
3. **可观测** — 每次执行都有审计日志，可视化界面实时展示

### 核心概念

<p align="center"><img src="docs/images/arch-profile-flow.png" alt="Profile → DAGEngine 架构图" width="548"></p>

<details>
<summary>ASCII 版本</summary>

```
┌─────────────────────────────────────────────────────────────┐
│                    Profile 配置                              │
│  .harness/profiles/default.yaml                             │
│  (hooks + skills + gates 全部声明在一个文件中)                │
└──────────────────────────┬──────────────────────────────────┘
                           │ 加载
┌──────────────────────────▼──────────────────────────────────┐
│                    HarnessConfig                             │
└───────┬──────────────────────────┬──────────────────────────┘
        │                          │
┌───────▼────────┐          ┌──────▼─────────────────────────┐
│ SkillRegistry  │          │     HarnessBridge               │
│ (注册/查找/    │          │     (AdapterRegistry + 协议翻译) │
│  插槽/执行)    │          │     Profile → Agent 原生格式     │
└───────┬────────┘          └──────┬─────────────────────────┘
        │                          │
        │                   ┌──────▼──────────┐
        │                   │  Claude Code    │
        │                   │  settings.json  │
        │                   │  (hooks 段)     │
        │                   └─────────────────┘
        │
┌───────▼──────────────────────────────────────────────────────┐
│                    DAGEngine                                  │
│  _execute_node 流程:                                          │
│    1. run_skill_slot(pre_execute)     ← Skills 定步骤        │
│    2. agent.execute(task)             ← Agents 定角色        │
│    3. gate.check(artifacts)           ← Hooks 定约束         │
│    4. run_skill_slot(post_execute)    ← Skills 定步骤        │
│    5. run_skill_slot(on_gate_fail)    ← Skills 定步骤        │
└───────────────────────────────────────────────────────────────┘
```

</details>

**Hooks 定约束** — 在 Agent 执行的各个阶段设置约束（门禁检查、安全扫描、PII 过滤）

**Skills 定步骤** — 可插拔的能力单元，挂载到 17 个插槽点（三层分层：核心5+扩展2+理论10）

**Agents 定角色** — 通过 AdapterRegistry 管理的 5 个适配器（S-1 插件机制：新增平台只需一个 .py 文件）

---

## 快速开始

### 前置要求

- Python 3.10+
- 一个受支持的 Agent 平台（Claude Code / Copilot CLI / Hermes 强制治理 ✅；Cursor / Codex 建议性治理 🔶）

### 安装

```bash
git clone https://github.com/harness-cook/harness-cook.git
cd harness-cook
./install.sh       # 一键安装（注册 harness 命令）
harness activate   # 一键激活（配置 MCP + hooks + skills）

# 指定部署到其他 Agent 平台
harness activate --agent hermes    # Hermes
harness activate --agent cursor    # Cursor IDE
harness activate --agent copilot-cli  # Copilot CLI
```

重启 Agent 平台即可生效。

### 卸载

```bash
harness deactivate
```

完全还原，不留任何配置残留。

### 自定义配置

harness-cook 预置了三个分级 Profile：

| Profile | Gate 模式 | Pipeline 步骤 | Hooks 数 | 适用场景 |
|---------|-----------|--------------|----------|---------|
| `basic` | LOOSE（仅拦截 critical） | 3 步（analyst→coder→committer） | 2 | 个人项目、快速迭代 |
| `default` | HYBRID（允许 low，拦截 medium+） | 5 步 | 3 | 团队协作、常规开发 |
| `enterprise` | STRICT（零容忍） | 5 步（含 reviewer+validator） | 9 | 生产环境、合规严格 |

#### Profile 选择优先级

系统自动决定使用哪个 Profile，无需手动干预：

| 优先级 | 机制 | 用途 | 示例 |
|--------|------|------|------|
| 1️⃣ 最高 | `HARNESS_PROFILE` 环境变量 | CI/自动化覆盖 | `HARNESS_PROFILE=enterprise` |
| 2️⃣ 中间 | `.harness/env` 文件 `HARNESS_PROFILE=` | 机器级持久化（activate 写入，gitignored） | — |
| 3️⃣ | `.harness/active_profile` 标记文件 | 项目级持久化选择（提交到 Git，团队共享） | 文件内容写 `basic` |
| 4️⃣ 最低 | `"default"` 回退 | 无任何选择时的默认值 | — |

#### 适配器选择优先级

适配器（部署目标平台）的选择也遵循优先级链，与 Profile 正交：

| 优先级 | 机制 | 用途 | 示例 |
|--------|------|------|------|
| 1️⃣ 最高 | `--agent` CLI 参数 | 用户显式指定 | `harness activate --agent hermes` |
| 2️⃣ | `HARNESS_ADAPTER` 环境变量 | CI/自动化覆盖 | `HARNESS_ADAPTER=cursor` |
| 3️⃣ | `.harness/env` 文件 `HARNESS_ADAPTER=` | 机器级持久化（activate 写入，gitignored） | — |
| 4️⃣ | `.harness/active_adapter` 标记文件 | 项目级持久化选择（提交到 Git，团队共享） | 文件内容写 `hermes` |
| 5️⃣ | Profile `agent.adapter` 字段 | 配置声明——作为回退默认值 | — |
| 6️⃣ 最低 | `"claude-code"` 回退 | 无任何配置时的默认值 | — |

> **Adapter 与 Profile 正交**：Adapter 决定"部署到哪"（运行时/环境决策），Profile 决定"部署什么规则"（治理决策）。

```bash
# 环境变量方式（CI/一次性覆盖）
export HARNESS_PROFILE=enterprise

# 标记文件方式（持久化，团队共享）
# 写入 .harness/active_profile 文件
echo "basic" > .harness/active_profile
```

```python
# Python API
from harness.config import switch_profile, load_profile

switch_profile("enterprise")  # 写入标记文件 → 团队共享
profile = load_profile()      # 自动 resolve → enterprise
profile = load_profile("basic")  # 显式指定 → basic（忽略 resolve）
```

#### 自定义 YAML

编辑 `.harness/profiles/default.yaml` 或创建新 Profile：

```yaml
profile:
  name: default
  description: 我的项目配置

agent:
  adapter: claude-code

pipeline:
  agents: [analyst, coder, reviewer, validator, committer]
  steps:
    - name: analyze-requirement
      skill: requirement-analysis
    - name: implement-code
      skill: code-generation
    - name: review-code
      skill: auto-review

hooks:
  session_start:
    - type: script
      command: "python3 packages/hooks/hook-session-init.py"
  post_execute:
    - type: skill
      skill_id: auto-audit

gates:
  default_mode: hybrid
  checks:
    - id: no-secrets
      enabled: true
    - id: no-eval
      enabled: true
```

### CLI 命令

```bash
harness activate              # 一键激活（默认 Claude Code）
harness activate --agent hermes  # 部署到 Hermes
harness activate --agent cursor  # 部署到 Cursor IDE
harness deactivate            # 一键卸载
harness log                   # 查看执行日志
harness log --type skill      # 按类型过滤
harness log --follow          # 实时跟踪
harness dashboard             # 启动可视化看板（自动识别当前项目）
harness dashboard --port 9000 # 指定端口
harness check .               # 合规扫描
harness audit                 # 查看审计记录
harness version               # 版本号
```

**Dashboard 项目自动识别优先级：**

| 优先级 | 检测方式 | 说明 |
|--------|----------|------|
| 1 | `HARNESS_PROJECT_DIR` 环境变量 | CLI 显式传入，最高优先 |
| 2 | `CLAUDE_PROJECT_DIR` 环境变量 | Claude Code 场景自动设置 |
| 3 | 从 CWD 向上查找 `.harness/` | **核心逻辑**：找到含 `.harness` 目录的父目录即识别为项目，搜索到达 home 目录时停止（不匹配 `~/.harness` 全局配置） |
| 4 | `git rev-parse --show-toplevel` | 无 `.harness` 时用 git root 兜底 |
| 5 | 当前工作目录 | 既无 `.harness` 又非 git 仓库 |

> 💡 在项目目录下执行 `harness dashboard`，默认就启动该项目的看板。无论项目是否已 `harness activate`，只要 `.harness/` 目录存在就能识别。

---

## 架构设计

### 分层架构

<p align="center"><img src="docs/images/arch-layers.png" alt="分层架构图" width="541"></p>

<details>
<summary>ASCII 版本</summary>

```
┌─────────────────────────────────────────────────────────────┐
│  用户层                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │  CLI     │  │  MCP     │  │ Dashboard│  │  SDK     │   │
│  │  命令    │  │  Server  │  │ Web UI   │  │ Python/TS│   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘   │
└───────┼──────────────┼──────────────┼──────────────┼────────┘
        │              │              │              │
┌───────▼──────────────▼──────────────▼──────────────▼────────┐
│  核心层                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ Profile  │  │ Skill    │  │ Bridge   │  │ Audit    │   │
│  │ Config   │  │ Registry │  │ Deploy   │  │ Logger   │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘   │
│       │              │              │              │         │
│  ┌────▼──────────────▼──────────────▼──────────────▼─────┐  │
│  │                  DAGEngine                             │  │
│  │  (拓扑排序 + 并行调度 + 门禁检查 + Skill 插槽执行)      │  │
│  └────┬──────────────┬──────────────┬──────────────┬─────┘  │
│       │              │              │              │         │
│  ┌────▼─────┐  ┌─────▼────┐  ┌─────▼────┐  ┌─────▼─────┐  │
│  │ Agent    │  │ Gate     │  │Compliance│  │ EventBus  │  │
│  │ Registry │  │ Engine   │  │ Engine   │  │           │  │
│  └──────────┘  └──────────┘  └──────────┘  └───────────┘  │
└─────────────────────────────────────────────────────────────┘
```

</details>

### 核心模块

| 模块 | 职责 | 关键类 |
|------|------|--------|
| `types.py` | 类型定义 | SkillSlotName(三层分层), ExecutionStrategy, PlatformCapability, merge_profiles, ProfileConfig |
| `config.py` | 配置系统 + 三层合并 | HarnessConfig, ProfileLoader, load_with_layers |
| `skill_registry.py` | Skill 注册表 | SkillRegistry, SkillRecord |
| `bridge.py` | 协议翻译 + 适配器注册 | HarnessBridge, AdapterRegistry(S-1) |
| `audit_logger.py` | 审计日志 | write_audit_log, log_skill_execute |
| `engine.py` | DAG 编排 | DAGEngine, _run_skill_slot |
| `gates.py` | 质量门禁 | GateEngine, GateCheck |
| `compliance.py` | 合规引擎统一入口（re-export） | ComplianceEngine, 6 个规则包 |
| `registry.py` | Agent 注册 | AgentRegistry |
| `bus.py` | 事件总线 | EventBus |
| `pattern_registry.py` | 触发器模式匹配（E-5） | PatternRegistry, PatternDefinition |
| `governance_semantics.py` | 治理语义标准化（S-2） | GovernanceSemanticRegistry, GovernanceSemantic |
| `gate_notification.py` | 门禁审批+降级通知 | GateManager, AutoDowngrade, GateApprovalRecord |
| `knowledge.py` | 知识管理+规则激活（S-4） | LocalKnowledgeProvider, InsightActivationStore |
| `downgrade.py` | 独立降级引擎 | DowngradeEngine, DowngradePolicy |

### Skill 插槽点

**17 个插槽点，三层分层（E-8 重构）：**

| 层级 | 数量 | 插槽 | 说明 |
|------|------|------|------|
| **核心通道** | 6 | SESSION_START, POST_EXECUTE, ON_ERROR, ON_GATE_PASS, ON_GATE_FAIL, ON_ESCALATION | DAGEngine 集成调用；前 5 个 Profile YAML 默认配 hook，ON_ESCALATION 由 gate 升级路径触发（engine.py 集成）、需注册 Skill 消费 |
| **扩展通道** | 2 | SESSION_END, PRE_EXECUTE | 有真实 hook 脚本支持，Profile YAML 可选展示 |
| **理论通道** | 9 | PRE_TOOL_USE, POST_TOOL_USE, ON_FILE_CHANGE, PRE_COMMIT, POST_COMMIT, ON_DELEGATE, ON_CONFLICT, ON_DECISION, USER_PROMPT_SUBMIT | 仅枚举定义，暂无生产集成 |

详细映射见 `docs/45-Slot分层映射表-20260616.md`

---

## 核心实现

### 1. Profile 配置体系

**文件：** `packages/core/harness/config.py`

```python
@dataclass
class HarnessConfig:
    # 传统配置
    project_name: str
    log_level: str
    default_gate_mode: GateMode

    # 脚手架配置（新增）
    active_profile: str              # 当前活跃 Profile
    hooks: dict                      # 声明式 Hook 配置
    skill_slots: dict                # Skill 插槽配置
```

**Profile 加载与自动选择：**

```python
from harness.config import load_profile, list_profiles, resolve_active_profile, switch_profile

# 自动选择：HARNESS_PROFILE env > .harness/active_profile > "default"
profile = load_profile()            # 自动 resolve → 当前活跃 Profile
print(profile.hooks)                 # {"session_start": [...], ...}
print(profile.pipeline_agents)       # ["analyst", "coder", ...]

# 切换 Profile（写入标记文件，持久化）
switch_profile("enterprise")

# 显式指定（忽略自动选择）
profile = load_profile("basic")

# 查看可用 Profile
profiles = list_profiles()           # ["basic", "default", "enterprise"]
```

**三层合并（S-3）——项目级强制、团队/用户级覆盖：**

```python
from harness.config import ProfileLoader
from harness.types import merge_profiles

loader = ProfileLoader()

# 加载带分层合并的 Profile（项目 → 团队 → 用户 三级）
profile = loader.load_with_layers("enterprise")
# 项目级的 forced_keys（hooks, gate_checks, default_gate_mode）不会被团队/用户覆盖
# 团队/用户可覆盖 description, pipeline_agents, workflow 等

# 直接调用合并函数
merged = merge_profiles(project_profile, team_profile, user_profile)
# → 返回合并后的 ProfileConfig，forced_keys 保证项目级强制项不变
```

### 2. Skill Registry

**文件：** `packages/core/harness/skill_registry.py`

```python
from harness.skill_registry import get_skill_registry, register_builtin_skills
from harness.types import SkillDefinition, SkillSlotName

registry = get_skill_registry()

# 注册 Skill
registry.register(SkillDefinition(
    id="my-skill",
    name="自定义检查",
    slot=SkillSlotName.POST_EXECUTE,
    entry_point="skills/my-skill/run.py",
    tags=["custom"],
))

# 按插槽查找
skills = registry.find_by_slot(SkillSlotName.POST_EXECUTE)

# 执行 Skill
result = registry.execute_skill("my-skill", context={"task_id": "t-1"})
```

**DAGEngine 集成：**
```python
# engine.py 的 _execute_node 方法
def _execute_node(self, node, ctx, global_context):
    self._run_skill_slot(node.id, SkillSlotName.PRE_EXECUTE, ctx, global_context)
    # ... agent.execute(task) ...
    self._run_skill_slot(node.id, SkillSlotName.POST_EXECUTE, ctx, global_context)
```

### 3. Bridge Deploy

**文件：** `packages/core/harness/bridge.py`

```python
from harness.bridge import HarnessBridge
from harness.config import load_profile

bridge = HarnessBridge()
profile = load_profile("default")

# 部署——通过 AdapterRegistry 选择适配器，条件分支治理策略
result = bridge.deploy(profile)
# → AdapterRegistry 三层发现：内置 → .harness/adapters/ → 内部扫描
# → hook-capable Agent (COOPERATIVE): mild prompt + hooks 自动触发
# → no-hooks Agent (FALLBACK): mandatory prompt + git hook 兜底
# → 写入配置 + 记录审计日志
```

**翻译规则：**

| Profile hooks | → | Claude Code |
|---------------|---|-------------|
| `session_start` | → | `SessionStart` |
| `pre_execute` | → | `PreToolUse` |
| `post_execute` | → | `PostToolUse` |
| `session_end` | → | `Stop` |

**条件分支策略（含 S-5 退让检测）：**

| 适配器 | `supports_hooks` | 退让策略 | Prompt 强度 | Git Hook |
|--------|-----------------|---------|-----------|---------|
| Claude/Copilot | `True` | COOPERATIVE | mild（轻提示） | ✅ 兜底 |
| Hermes | `False` | FALLBACK | mandatory（强提示，自动升级） | ✅ 兜底 |
| Cursor/OpenAI | `False` | FALLBACK | mandatory（强提示，自动升级） | ✅ 兜底 |

> FALLBACK 策略自动将 prompt_strength 从 mild 升级为 mandatory——这是退让检测的核心：无 hook 能力时必须用强提示补偿

### 4. 可观测性

**审计日志：** 每次 Skill 执行、Bridge deploy 自动写入 `.harness/audit/`

```json
{
  "timestamp": "2026-06-12T11:05:23.456789",
  "event": "skill_execute",
  "skill_id": "auto-audit",
  "status": "completed",
  "duration_ms": 125
}
```

**CLI 查看：**
```bash
harness log --type skill --limit 10
```

**Dashboard 可视化：**
```bash
harness dashboard    # http://localhost:8765
```

### 5. 适配器插件机制（S-1）

**新增平台只需一个 .py 文件：**

```python
# .harness/adapters/my_platform.py
from harness.adapters.base import IAgentAdapter

class MyPlatformAdapter(IAgentAdapter):
    platform_id = "my-platform"
    supports_hooks = False
    
    def translate_hooks(self, hooks: dict) -> dict:
        return {}  # 无 hook 支持
    
    def translate_profile(self, profile) -> dict:
        return {"instructions": self._build_instructions(profile)}
```

**三层发现顺序：** 内置适配器 → `.harness/adapters/` 目录 → `harness.adapters` 内部扫描

### 6. 治理语义标准化（S-2）

**统一治理动作的语义描述，跨适配器翻译一致：**

```python
from harness.governance_semantics import get_governance_semantic_registry

registry = get_governance_semantic_registry()

# 查询语义定义
semantic = registry.get("pii_filter")
# → GovernanceSemantic(id="pii_filter", actions=[BLOCK, WARN], 
#     description="PII内容过滤", patterns=[身份证号, 手机号, 银行卡号])

# 跨适配器翻译
result = registry.translate_governance("pii_filter", adapter="hermes")
# → Hermes 适配器将 pii_filter 翻译为 function_calling 定义
```

### 7. 知识库规则激活（S-4）

**一键将 Insight 激活为合规规则，一键回退：**

```python
from harness.knowledge import get_knowledge_provider

provider = get_knowledge_provider()

# 查询知识库
results = provider.query("no-hardcoded-secrets")

# 一键激活 Insight 为合规规则
activation = provider.activate("insight-no-secrets")
# → Insight → ComplianceRule, 自动写入规则包

# 一键回退
provider.deactivate("insight-no-secrets")
# → 规则移除, Insight 回到未激活状态
```

### 8. 退让检测机制（S-5）

**根据适配器能力自动选择治理策略：**

```python
from harness.types import PlatformCapability, ExecutionStrategy

cap = PlatformCapability(
    adapter_id="hermes",
    supports_realtime_redact=False,
    supports_realtime_block=False,
    supports_pii_detection=False,
    supports_compliance_scan=False,
)

strategy = cap.resolve_execution_strategy()
# → ExecutionStrategy.FALLBACK  (无 hook, 升级为 mandatory prompt)

# Claude Code 的策略（有 realtime_block，无 realtime_redact）
cap_cc = PlatformCapability(adapter_id="claude-code", supports_realtime_redact=False, supports_realtime_block=True, ...)
strategy = cap_cc.resolve_execution_strategy()
# → ExecutionStrategy.COOPERATIVE (有部分能力, mild prompt + hooks 自动触发)
```

---

## 可观测 Dashboard

启动 Dashboard：

```bash
harness dashboard
# 浏览器访问 http://localhost:8765
```

**10 个 Tab：**

| Tab | 内容 |
|-----|------|
| 概览 | 统计卡片 + Hook 执行分布 + Gate 通过率 |
| 审计 | 审计记录搜索（决策链/行动链溯源） |
| Agent | 已注册 Agent 列表 + 最近活动 |
| **Skills** | 已注册 Skills + 执行统计（执行次数/错误次数） |
| **Profile** | 当前 Profile 配置（hooks/gates 详情） |
| **Hooks** | Hook 执行统计（按类型/Slot 分布） |
| 合规 | 合规扫描 + 规则包列表 |
| 门禁 | 门禁检查历史 |
| 事件流 | 实时事件流 |
| **知识** | 知识库条目（按类型/来源浏览） |

---

## MCP Server

harness-cook 通过 MCP Server 暴露 25 个工具：

| 工具 | 功能 |
|------|------|
| `harness_check` | 合规扫描 |
| `harness_guardrails_check` | PII/安全护栏检查 |
| `harness_rule_import` | 规则导入（SonarQube/ArchUnit/DepCruiser） |
| `harness_audit` | 审计记录查询 |
| `harness_trace_export` | OTel/Traceloop 导出 |
| `harness_status` | 系统状态聚合 |
| `harness_plan` | DAG 拓扑可视化 |
| `harness_run` | DAG 工作流执行 |
| `harness_pipeline_run` | 编码管线执行 |
| `harness_pipeline_status` | 管线状态查询 |
| `harness_gate_create` | 创建门禁 |
| `harness_gate_approve` | 门禁审批（E-9） |
| `harness_hook_trigger` | MCP 触发器（E-5，hook 触发后调护栏做模式匹配） |
| `harness_register` | 注册 Agent |
| `harness_agent_list` | Agent 列表 |
| `harness_profile_list` | 列出 Profile |
| `harness_profile_load` | 加载 Profile |
| `harness_skill_list` | 列出 Skills |
| `harness_skill_register` | 注册 Skill |
| `harness_bridge_deploy` | 部署到 Agent 平台（Claude/Copilot/Hermes/Cursor/Codex） |
| `harness_knowledge_query` | 知识库查询 |
| `harness_knowledge_search` | 知识库语义搜索 |
| `harness_knowledge_stats` | 知识库统计 |
| `harness_knowledge_activate` | Insight→规则一键激活（S-4） |
| `harness_knowledge_deactivate` | 规则一键回退（S-4） |

---

## 项目结构

```
harness-cook/
├── packages/
│   ├── core/                        核心框架 (Python)
│   │   ├── harness/
│   │   │   ├── __init__.py          统一导出
│   │   │   ├── types.py             类型定义 (SkillSlotName, ExecutionStrategy, merge_profiles, ...)
│   │   │   ├── config.py            配置系统 + ProfileLoader + 三层合并(S-3)
│   │   │   ├── skill_registry.py    Skill 注册表 + 插槽机制
│   │   │   ├── bridge.py            Bridge Deploy + AdapterRegistry(S-1)
│   │   │   ├── audit_logger.py      审计日志写入
│   │   │   ├── bus.py               事件总线
│   │   │   ├── registry.py          Agent 注册表
│   │   │   ├── engine.py            DAG 编排引擎 (+ Skill 插槽执行)
│   │   │   ├── gates.py             质量门禁
│   │   │   ├── compliance.py        合规引擎统一入口（re-export）
│   │   │   ├── guardrails.py        输入输出护栏
│   │   │   ├── scheduler.py         资源感知调度
│   │   │   ├── negotiation.py       多 Agent 协商
│   │   │   ├── audit.py             审计存储
│   │   │   ├── learning.py          自学习（Insight→规则激活, S-4）
│   │   │   ├── knowledge.py         知识管理 + InsightActivationStore(S-4)
│   │   │   ├── constraints.py       约束系统
│   │   │   ├── decorators.py        @harness_agent 装饰器
│   │   │   ├── llm.py               Agent 资源约束（token预算/模型分级/追踪）
│   │   │   ├── rollback.py          自动回滚
│   │   │   ├── call_graph.py        调用图分析
│   │   │   ├── taint.py             污点追踪
│   │   │   ├── report.py            可视化报告
│   │   │   ├── logging_config.py    日志配置
│   │   │   ├── pattern_registry.py  触发器模式匹配(E-5)
│   │   │   ├── governance_semantics.py 治理语义标准化(S-2)
│   │   │   ├── gate_notification.py 门禁审批+降级通知
│   │   │   ├── downgrade.py         独立降级引擎
│   │   │   ├── adapters/            适配器插件(S-1)
│   │   │   │   ├── base.py          IAgentAdapter 契约
│   │   │   │   ├── claude_code.py   Claude Code 适配器
│   │   │   │   ├── copilot_cli.py   Copilot CLI 适配器
│   │   │   │   ├── hermes.py        Hermes 适配器
│   │   │   │   ├── cursor.py        Cursor 适配器
│   │   │   │   └── openai.py        OpenAI/Codex 适配器
│   │   │   └── rule_packs/          内置合规规则包
│   │   │       ├── coding.py        编码合规
│   │   │       ├── security.py      安全合规
│   │   │       ├── data.py          数据合规
│   │   │       ├── devops.py        运维合规
│   │   │       ├── architecture.py  架构合规
│   │   │       └── legal.py         法律合规（新增）
│   │   ├── tests/                   核心测试 (1644 个)
│   │   └── pyproject.toml
│   │
│   ├── cli/                         CLI 工具
│   │   ├── harness_cli.py           主入口 (14 个子命令)
│   │   ├── cli_commands/
│   │   │   ├── activate.py          一键激活 (Profile → Bridge → settings.json)
│   │   │   ├── deactivate.py        一键卸载 (完全还原)
│   │   │   ├── log.py               查看执行日志
│   │   │   ├── dashboard.py         启动 Dashboard
│   │   │   ├── check.py             合规扫描
│   │   │   ├── audit.py             审计查询
│   │   │   ├── plan.py              DAG 拓扑可视化
│   │   │   ├── run.py               执行工作流
│   │   │   ├── report.py            生成报告
│   │   │   ├── docs.py              启动 VitePress 文档站点
│   │   │   ├── knowledge.py         知识管理（CRUD + 搜索 + 语义搜索）
│   │   │   ├── learn.py             学习引擎（统计/推荐/轨迹/模式）
│   │   │   └── update.py            更新源码和依赖（git pull + pip install）
│   │   └── tests/
│   │
│   ├── mcp/                         MCP Server
│   │   ├── harness_mcp_server.py    25 个 MCP 工具
│   │   └── tests/
│   │
│   ├── dashboard/                   可视化 Dashboard
│   │   ├── app.py                   FastAPI 后端 (35 个 API)
│   │   └── frontend.html            前端 UI (10 个 Tab)
│   │
│   ├── hooks/                       内置 Hooks
│   │   ├── hook-session-init.py     SessionStart hook
│   │   ├── hook-task-audit.py       Stop hook (审计记录)
│   │   ├── hook-compliance-scan.py  PostToolUse hook (合规扫描)
│   │   ├── hook-guardrails-pii.py   PostToolUse hook (PII 检测)
│   │   ├── hook-prompt-guardrails.py UserPromptSubmit hook
│   │   ├── hook-gate-pre-write.py   PreToolUse hook (写文件前门禁拦截)
│   │   └── tests/
│   │
│   ├── agents/                      Agent 模块
│   │   ├── harness_agents/
│   │   │   ├── coding_agents.py     4 种编码角色
│   │   │   ├── orchestrator.py      多 Agent 编排
│   │   │   ├── react_runtime.py     ReAct 推理执行
│   │   │   └── tool_executor.py     工具执行器
│   │   └── tests/
│   │
│   ├── sdk-python/                  Python SDK
│   │   ├── harness_sdk/
│   │   │   ├── decorators.py        @harness_agent / @simple_agent
│   │   │   ├── hooks.py             生命周期钩子
│   │   │   ├── client.py            HarnessClient
│   │   │   └── agent.py             Agent 接口
│   │   └── tests/
│   │
│   ├── sdk-typescript/              TypeScript SDK
│   │   ├── src/
│   │   │   ├── agent.ts             defineAgent / simpleAgent
│   │   │   ├── hooks.ts             生命周期钩子
│   │   │   ├── client.ts            HarnessClient
│   │   │   └── types.ts             类型定义
│   │   └── tests/
│   │
│   └── vscode-extension/            VS Code 扩展
│
├── skills/                          Skills 目录
│   ├── auto-audit/                  自动审计 Skill
│   │   ├── SKILL.md                 Skill 声明
│   │   ├── audit_report.py          执行脚本
│   │   └── tests/
│   ├── auto-review/                 自动审查 Skill
│   │   ├── SKILL.md
│   │   ├── review_gate.py
│   │   └── tests/
│   ├── auto-verify/                 自动验证 Skill
│   │   ├── SKILL.md
│   │   ├── verify.py
│   │   └── tests/
│   └── harness-bridge/              Bridge Skill
│       ├── SKILL.md
│       └── bridge.py
│
├── .harness/
│   ├── active_profile               活跃 Profile 标记（提交到 Git）
│   ├── active_adapter               活跃适配器标记（提交到 Git）
│   ├── profiles/
│   │   ├── basic.yaml               基础 Profile（LOOSE+3步+2hooks）
│   │   ├── default.yaml             默认 Profile（HYBRID+5步+3hooks）
│   │   └── enterprise.yaml          企业级 Profile（STRICT+5步+9hooks）
│   └── audit/                       审计日志 (gitignore)
│
├── examples/                        示例
│   ├── simple-agent/                单 Agent 极简
│   ├── multi-agent/                 多 Agent DAG 编排
│   ├── hermes-bridge/               Hermes 集成
│   └── custom-rules/                自定义规则
│
├── docs/                            文档
│   ├── architecture-design.md       架构设计
│   ├── 12-脚手架化改造差距分析.md
│   ├── 13-脚手架化开发计划.md
│   ├── 14-第一期交付总结.md
│   └── 15-完整实现总结.md
│
├── playground/                      VitePress 文档站
│   ├── docs/                        文档页面
│   └── demo_*.py                    演示脚本
│
├── workflows/                       工作流示例
│   └── basex-examples.yaml
│
├── README.md
├── LICENSE
├── package.json
└── .github/workflows/ci.yml
```

---

## 测试

```bash
# 核心测试
cd packages/core
PYTHONPATH=. pytest tests/ -v

# 新增验收测试（S-1~S-5 + E-1~E-10）
pytest tests/test_adapter_registry_s1.py tests/test_governance_semantics_s2.py \
       tests/test_governance_layering_s3.py tests/test_knowledge_activate_s4.py \
       tests/test_yield_detection_s5.py -v
```

**1644 tests collected, 1576 passed, 18 pre-existing failures, 0 new failures** ✅

---

## License

MIT

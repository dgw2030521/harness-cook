# 快速开始

> 5 分钟从零到上手：安装 → 激活 → 扫描 → 护栏 → Dashboard → 自定义 Profile。

**快速导航**：[⏱ 5 分钟上手流程（本页）](#5分钟上手流程) · [📖 安装详解](#安装详解) · [📖 激活详解](#安装与激活) · [🎓 使用教程](/tutorial/basic-usage) · [🏃 Demo](/demo/)

---

## 系统要求

- Python 3.10+
- Claude Code 已安装（推荐）
- 可选依赖：`pyyaml>=6.0`（工作流 YAML 解析）

---

## 5 分钟上手流程

按顺序执行以下 7 步，即可完成 harness-cook 的安装验证、核心功能体验和个性化配置。

### Step 1：安装

克隆仓库并运行一键安装脚本，将 `harness` 命令注册到 PATH：

```bash
# 克隆仓库
git clone <repo-url> harness-cook
cd harness-cook

# 一键安装（注册 harness 命令到 PATH）
./install.sh
```

`install.sh` 自动完成 3 步：安装核心包 → 安装 CLI 包 → 验证 `harness` 命令可用。

安装成功后可直接使用 `harness` 命令：

```bash
harness version   # 验证安装，输出版本号
```

> 如果 `./install.sh` 不可用（如 Windows 环境），可手动安装：
> ```bash
> pip install -e packages/core
> pip install -e packages/cli
> ```
> 或直接用 Python 模块方式运行：`python3 -m harness_cli <command>`。

### Step 2：激活

安装完成后，一键激活将治理配置部署到 Agent 平台：

```bash
# 一键激活（默认部署到 Claude Code）
harness activate

# 或指定其他 Agent 平台
harness activate --agent hermes      # Hermes
harness activate --agent cursor      # Cursor IDE
harness activate --agent copilot-cli # Copilot CLI
```

> 适配器选择优先级链：`--agent CLI > HARNESS_ADAPTER env > .harness/env > .harness/active_adapter > Profile adapter > claude-code`

激活后重启 Agent 平台即可生效。`activate` 自动完成的详细事项见下方 [安装与激活](#安装与激活) 一节的表格。

> **Adapter 与 Profile 正交**：Adapter 是"部署到哪"（环境决策），Profile 是"部署什么规则"（治理决策），两者独立。

### Step 3：验证安装

确认核心包已正确安装且版本可用：

```bash
python3 -c "import harness; print(harness.__version__)"
# 输出类似：0.2.0
```

如果输出版本号，说明核心包已就绪。如果报 `ModuleNotFoundError`，请重新运行 `./install.sh` 或手动 `pip install -e packages/core`。

### Step 4：第一次合规扫描

对任意源文件运行合规检查，体验内置 checker 的效果：

**CLI 方式：**

```bash
harness check --path packages/core/harness/coordinator.py
```

**MCP 工具方式（在 Claude Code 中直接调用）：**

```
harness_check(path="packages/core/harness/coordinator.py")
```

两种方式均会返回合规结果：违规项、严重级别、规则来源等。默认使用 `builtin` 引擎，无需额外安装。

### Step 5：第一次护栏检查

检查一段文本是否包含 PII（个人身份信息），体验护栏层的防护能力：

**MCP 工具方式（在 Claude Code 中）：**

```
harness_guardrails_check(
  content="我的手机号是 13812345678，邮箱是 zhangsan@example.com",
  direction="input"
)
```

**CLI 方式：**

```bash
harness guardrails \
  --content "我的手机号是 13812345678，邮箱是 zhangsan@example.com" \
  --direction input
```

返回结果会标记检测到的 PII 类型（手机号、邮箱等）及处置建议。默认引擎为 `builtin`；安装 Guardrails AI 后可切换：

```bash
pip install harness-cook[guardrails]  # 安装后 engine="guardrails-ai" 可用
```

### Step 6：查看 Dashboard

启动 Dashboard 查看审计日志、合规统计和系统状态：

```bash
harness dashboard
```

Dashboard 启动后会在本地浏览器打开，展示：

- 审计日志列表（最近扫描/护栏记录）
- 合规违规分布统计
- 系统状态概览（引擎、Profile、Skill 注册情况）

也可通过 MCP 工具查询：

```
harness_status()         # 查看系统聚合状态
harness_audit(query="check")  # 搜索审计日志中的合规扫描记录
```

### Step 7：自定义 Profile

编辑默认 Profile，调整治理规则以适配你的项目：

```bash
# 打开默认 Profile
vim .harness/profiles/default.yaml
```

示例 — 在 `post_execute` 插槽中增加 `auto-review` Skill：

```yaml
hooks:
  session_start:
    - type: script
      command: "python3 packages/hooks/hook-session-init.py"
  post_execute:
    - type: skill
      skill_id: auto-audit
    - type: skill
      skill_id: auto-review      # 新增：每次执行后自动 code review
  session_end:
    - type: script
      command: "python3 packages/hooks/hook-task-audit.py"
```

保存后重新部署生效：

```
harness_bridge_deploy()  # MCP 工具方式，部署当前 Profile 到 Agent 平台
```

或 CLI 方式：

```bash
harness deploy
```

## 安装详解

harness-cook 提供两种安装方式：

### 方式一：一键安装脚本（推荐）

```bash
git clone <repo-url> harness-cook
cd harness-cook
./install.sh
```

`install.sh` 执行 3 步：

| 步骤 | 命令 | 说明 |
|------|------|------|
| 1 | `pip install -e packages/core` | 安装核心包（harness 模块） |
| 2 | `pip install -e packages/cli` | 安装 CLI 包（注册 `harness` 命令到 PATH） |
| 3 | 验证 | 检查 `harness` 命令是否可用 |

安装成功后 `harness` 命令全局可用，后续所有操作直接用 `harness` 而非 `python3 packages/cli/harness_cli.py`。

### 方式二：手动安装

```bash
git clone <repo-url> harness-cook
cd harness-cook
pip install -e packages/core    # 核心包
pip install -e packages/cli     # CLI 包（注册 harness 命令）
```

如遇 `harness` 命令不在 PATH，可改用 Python 模块方式：

```bash
python3 -m harness_cli activate
python3 -m harness_cli check --path <file>
```

### 更新到最新版本

```bash
harness update   # 一键更新源码和依赖（git pull + pip install -e）
```

> 📖 更多 CLI 命令 → [CLI 命令参考](/cli/)

---

## 安装与激活

`activate` 自动完成的详细步骤：

| 步骤 | 说明 |
|------|------|
| 安装核心包 | `pip install -e packages/core` |
| 配置 MCP Server | 由 `bridge.deploy` 写入各平台配置（claude-code 走 hooks 自动校验，不再写 `~/.claude/settings.json` mcpServers；其他适配器写入各自平台配置） |
| 部署 Profile | 读取 `.harness/profiles/default.yaml` → 通过 `bridge.deploy(harness_root=...)` 写入目标平台配置 |
| 注册 Skills | 符号链接到 `~/.claude/skills/` |
| 初始化目录 | 创建 `.harness/audit/` 等运行时目录 + 写入 `active_profile` / `active_adapter` / `.harness/env` |
| 添加权限 | MCP 工具权限（仅 Claude Code 适配器写入 `.claude/settings.local.json`） |

### `--agent` 参数详解

`--agent` 指定将治理配置部署到哪个 Agent 平台，不指定时默认 Claude Code。

适配器选择优先级：`--agent CLI > HARNESS_ADAPTER env > .harness/env > .harness/active_adapter > Profile adapter 字段 > claude-code`

> 📖 各 Agent 平台的完整使用参考——激活、治理、工具、流程——见 [Agent 平台使用指南](./agent-platforms)。

### 还原项目配置

```bash
harness deactivate
# 还原项目配置到激活前的状态（不卸载 pip 包）
```

还原清单：

| 步骤 | 说明 |
|------|------|
| 清理 `.claude/settings.local.json` | 移除 harness hooks + `env.HARNESS_COOK_ROOT`；空壳删除 |
| 清理 `.claude/settings.json` | 移除 harness hooks + MCP + `env.HARNESS_COOK_ROOT`；空壳删除 |
| 清理非 Claude Code 适配器配置 | Hermes: 移除 `~/.hermes/config.yaml` 中 harness 条目；Cursor: 移除 `.cursor/mcp.json` 中 harness 条目；Copilot CLI: 移除 `~/.copilot/config.json` 中 harness 条目 |
| 清理 `.gitignore` | 移除 harness 追加的条目 |
| 删除 `.harness/` | 彻底删除整个目录 |

---

## 默认配置

激活后默认启用 **3 个核心插槽**，覆盖 90% 场景：

```yaml
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

---

## 可选引擎

harness-cook 默认安装不包含外部引擎 SDK。安装后自动生效，未安装时回退到内置 checker：

```bash
pip install harness-cook[guardrails]     # Guardrails AI
pip install harness-cook[sonarqube]      # SonarQube
pip install harness-cook[integrations]   # 所有外部引擎
```

---

## 下一步

- 🎓 [基本使用教程](/tutorial/basic-usage) —— 逐步操作指南
- 📖 [核心概念](./core-concepts) —— Integrations、引擎路由、Protocol
- 📖 [护栏层](./guardrails-layer) · [合规层](./compliance-layer) · [审计层](./audit-layer) · [门禁层](./gate-layer) —— 四层治理原理
- 🏃 [Demo 入口](/demo/) —— 可运行脚本 + 配置示例

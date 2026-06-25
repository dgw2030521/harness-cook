# Adapter 快速上手

> 5 个 Agent 平台的 3 步激活流程，从安装到验证一气呵成。

---

## 适配器选择优先级链

当多个信号同时存在时，harness 按以下优先级决定使用哪个适配器：

```
--agent CLI 参数 > HARNESS_ADAPTER 环境变量 > .harness/env 文件 > .harness/active_adapter 标记 > Profile adapter 字段 > claude-code（默认）
```

显式传入 `--agent=xxx` 会覆盖所有自动推导，其他信号依次降级。

## Adapter 与 Profile 正交

| 维度 | Adapter | Profile |
|------|---------|---------|
| 回答什么 | 部署到哪个 Agent 平台（环境决策） | 部署什么治理规则（治理决策） |
| 切换方式 | `--agent=xxx` 或修改 `.harness/active_adapter` | 编辑 `.harness/profiles/*.yaml` |
| 切换影响 | 配置写入路径和格式变化，规则内容不变 | 规则内容变化，写入路径不变 |
| 正交关系 | 同一个 Profile 可部署到任意 Adapter | 同一个 Adapter 可承载任意 Profile |

> 换 Adapter 只改"输出格式"（Claude Code → JSON、Hermes → YAML、Cursor → MCP JSON），不影响治理规则本身。换 Profile 只改"规则内容"（hooks、gates、skills），不影响配置文件落盘位置。

---

## 有-hooks vs 无-hooks Agent

| 类别 | 平台 | `supports_hooks` | 治理路径 | Gate Prompt 强度 |
|------|------|-------------------|----------|-----------------|
| 有-hooks | Claude Code、Copilot CLI | `True` | hooks 自动强制执行 | mild（轻提示，补充说明） |
| 无-hooks | Hermes、Cursor、OpenAI/Codex | `False` | MCP Server + Gate Prompt + git pre-commit hook 兜底 | mandatory（强提示，唯一事前手段） |

无-hooks Agent 的治理依赖三条防线：
1. **MCP 工具调用**——Agent 通过 `harness_check` 等工具主动检查
2. **Gate Prompt 注入**——在 CLAUDE.md 中写入 MANDATORY 级提示，要求 Agent 每次变更前必须调用检查
3. **git pre-commit hook**——兜底防线，不管谁提交、怎么提交，不合规变更都会被拦截

---

## 1. Claude Code

配置路径：`.claude/settings.json`（项目级）

```bash
# ── Step 1: 安装 ──────────────────────────────────────
git clone <repo-url> harness-cook
cd harness-cook

# ── Step 2: 激活 ──────────────────────────────────────
python3 packages/cli/harness_cli.py activate --agent=claude-code

# ── Step 3: 验证 ──────────────────────────────────────
# 检查项目级配置
cat .claude/settings.json        # 应含 harness hooks 定义
cat .claude/settings.local.json  # 应含 MCP 工具权限

# 检查 MCP 连通
python3 packages/cli/harness_cli.py status

# 重启 Claude Code 使 hooks 和 MCP 生效
```

**Claude Code 特性**：
- `supports_hooks=True`——hooks 在 Agent 执行时自动强制触发（PreToolUse、PostToolUse、SessionStart 等）
- MCP 工具权限写入 `.claude/settings.local.json`，无需手动授权
- Gate Prompt 为轻提示（mild），hooks 已自动执行，prompt 只是补充

---

## 2. Copilot CLI

配置路径：`.copilot/config.json`（项目级）

```bash
# ── Step 1: 安装 ──────────────────────────────────────
git clone <repo-url> harness-cook
cd harness-cook

# ── Step 2: 激活 ──────────────────────────────────────
python3 packages/cli/harness_cli.py activate --agent=copilot-cli

# ── Step 3: 验证 ──────────────────────────────────────
# 检查项目级配置
cat .copilot/config.json  # 应含 hooks + mcpServers 定义

# 检查部署状态
python3 packages/cli/harness_cli.py status

# 重启 Copilot CLI
```

**Copilot CLI 特性**：
- `supports_hooks=True`——hooks 通过 MCP 工具调用实现，Copilot CLI 在配置中声明 hook 脚本和 MCP server
- Hook 映射：`session_start` → `on_session_start`，`post_execute` → `on_post_execute` 等
- MCP server 定义与 Claude Code 类似，但 hook 格式不同（Copilot CLI 不使用 matcher）

---

## 3. Hermes

配置路径：`~/.hermes/config.yaml`（全局级）

```bash
# ── Step 1: 安装 ──────────────────────────────────────
git clone <repo-url> harness-cook
cd harness-cook

# ── Step 2: 激活 ──────────────────────────────────────
python3 packages/cli/harness_cli.py activate --agent=hermes

# ── Step 3: 验证 ──────────────────────────────────────
# 检查全局配置
cat ~/.hermes/config.yaml  # 应含 mcpServers.harness-cook 定义

# 检查项目级标记
ls -la .harness/  # 应含 active_adapter、env、profiles/

# 检查 git hook 兜底
cat .git/hooks/pre-commit | grep harness  # 应含 harness-cook gate 段

# 重启 Hermes
```

**Hermes 特性**：
- `supports_hooks=False`——Hermes 没有原生 hooks 自动触发，治理通过 MCP Server 实现
- 配置为全局 YAML（不是项目级 JSON），写入 `~/.hermes/config.yaml`
- MCP Server 运行时通过工作目录定位项目，读取 `.harness/` 执行治理
- 自定义配置路径：可通过 `HERMES_CONFIG_PATH` 环境变量指定
- Gate Prompt 为强制提示（mandatory），因为 MCP 工具调用是唯一的事前治理手段

---

## 4. Cursor

配置路径：`.cursor/mcp.json`（项目级）

```bash
# ── Step 1: 安装 ──────────────────────────────────────
git clone <repo-url> harness-cook
cd harness-cook

# ── Step 2: 激活 ──────────────────────────────────────
python3 packages/cli/harness_cli.py activate --agent=cursor

# ── Step 3: 验证 ──────────────────────────────────────
# 检查项目级配置
cat .cursor/mcp.json  # 应含 mcpServers.harness-cook 定义

# 检查项目级标记
ls -la .harness/  # 应含 active_adapter、env、profiles/

# 检查 git hook 兜底
cat .git/hooks/pre-commit | grep harness  # 应含 harness-cook gate 段

# 重启 Cursor IDE
```

**Cursor 特性**：
- `supports_hooks=False`——Cursor 不支持 hook 脚本配置，治理通过 MCP 工具调用实现
- 配置只包含 MCP server 定义（`mcpServers`），hook 脚本作为 metadata 附加供参考
- Gate Prompt 为强制提示（mandatory），与 Hermes 同理

---

## 5. OpenAI / Codex

配置路径：无本地配置文件（function calling 在 API 请求中传递）

```bash
# ── Step 1: 安装 ──────────────────────────────────────
git clone <repo-url> harness-cook
cd harness-cook

# ── Step 2: 激活 ──────────────────────────────────────
python3 packages/cli/harness_cli.py activate --agent=openai

# ── Step 3: 验证 ──────────────────────────────────────
# 检查项目级标记
ls -la .harness/  # 应含 active_adapter、env、profiles/

# 检查 Gate Prompt 注入
cat CLAUDE.md | grep "harness gate"  # 应含 MANDATORY 级提示

# 检查 git hook 兜底
cat .git/hooks/pre-commit | grep harness  # 应含 harness-cook gate 段

# OpenAI 配置无本地文件——function definitions 在 API 调用时传入
```

**OpenAI / Codex 特性**：
- `supports_hooks=False`——OpenAI function calling 不支持 hooks 概念，hooks 转换为 function definitions
- 无本地配置文件——`get_settings_path` 返回空字符串，function definitions 在 API 请求中动态传递
- Gate Prompt 为强制提示（mandatory），与 Hermes/Cursor 同理
- 治理完全依赖 Gate Prompt + git pre-commit hook，Agent 需要主动调用 `harness_check` 等工具

---

## 还原配置

所有平台的还原方式相同——`deactivate` 命令会根据当前适配器清理对应配置：

```bash
# 还原 Claude Code：清理 .claude/settings.json + settings.local.json
# 还原 Copilot CLI：清理 .copilot/config.json
# 还原 Hermes：清理 ~/.hermes/config.yaml 中 harness 条目
# 还原 Cursor：清理 .cursor/mcp.json
# 还原 OpenAI：无本地文件，仅清理 .harness/ 目录和 Gate Prompt

python3 packages/cli/harness_cli.py deactivate
```

还原清单：

| 步骤 | 说明 |
|------|------|
| 清理项目级配置 | 移除 harness hooks + MCP + `env.HARNESS_COOK_ROOT`；空壳删除 |
| 清理全局配置 | Hermes: 移除 `~/.hermes/config.yaml` 中 harness 条目（YAML 格式） |
| 清理 Gate Prompt | 移除 CLAUDE.md 中 `[harness gate]` 段 |
| 清理 git hook | 移除 `.git/hooks/pre-commit` 中 harness 段 |
| 清理 `.gitignore` | 移除 harness 追加的条目 |
| 删除 `.harness/` | 彻底删除整个目录 |

---

## 配置文件对照表

| 适配器 | 配置文件路径 | 格式 | 项目级/全局级 | supports_hooks |
|--------|-------------|------|--------------|----------------|
| claude-code | `.claude/settings.json` | JSON | 项目级 | True |
| copilot-cli | `.copilot/config.json` | JSON | 项目级 | True |
| hermes | `~/.hermes/config.yaml` | YAML | 全局级 | False |
| cursor | `.cursor/mcp.json` | JSON | 项目级 | False |
| openai | （无本地文件） | — | — | False |

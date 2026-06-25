# activate — 一键激活

> 安装核心包 + MCP 配置收敛 + 部署 Profile + 注册 Skills + 初始化目录 + 知识库种子注入

## 用法

```bash
# 默认激活（Claude Code 适配器 + default Profile）
harness activate

# 指定 Profile + Agent 适配器
harness activate --profile frontend --agent claude-code

# 指定 Hermes 适配器
harness activate --agent hermes

# 指定 Cursor 适配器
harness activate --agent cursor

# 指定 Copilot CLI 适配器
harness activate --agent copilot-cli

# 跳过部分步骤
harness activate --skip-install --skip-mcp --skip-hooks
```

## 五步执行流程

activate 按以下 5 步依次执行：

| Step | 名称 | 说明 | 可跳过 |
|------|------|------|--------|
| 1/5 | 安装核心包 | `pip install -e packages/core` + `pip install -e packages/cli`（注册 `harness` 命令到 PATH） | `--skip-install` |
| 2/5 | MCP 配置收敛 | claude-code 走 hooks 不写 mcpServers，仅清理 `~/.claude/settings.json` 中遗留的 `harness-cook`；其他 adapter 的 MCP 由 Step 3 写入各自平台配置 | `--skip-mcp` |
| 3/5 | 部署 Profile | ProfileLoader 分层查找 → Bridge deploy 写入目标平台配置 | `--skip-hooks` |
| 4/5 | 注册 Skills | 符号链接 `~/.claude/skills/{name} → harness/skills/{name}` + 初始化 SkillRegistry | `--skip-skills` |
| 5/5 | 初始化目录 | 创建 `.harness/audit/` + 复制内置 Profile 到 `.harness/profiles/` + 写标记文件 + 更新 `.gitignore` + 知识库种子注入 | `--skip-init` |

## 参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--profile` | Profile 职能模板: default/basic/frontend/backend/product/enterprise/ui | `default` |
| `--agent` | Agent 适配器: claude-code/copilot-cli/hermes/cursor/openai | 由优先级链推导 |
| `--skip-install` | 跳过 pip install | ❌ |
| `--skip-mcp` | 跳过 MCP 配置 | ❌ |
| `--skip-hooks` | 跳过 Profile 部署 | ❌ |
| `--skip-skills` | 跳过 Skills 注册 | ❌ |
| `--skip-init` | 跳过目录初始化 | ❌ |

## 适配器选择优先级链

```
--agent CLI 参数  >  HARNESS_ADAPTER env  >  .harness/env  >  .harness/active_adapter  >  Profile adapter 字段  >  claude-code
```

> **Adapter 与 Profile 正交**：Adapter 决定"部署到哪"（环境决策），Profile 决定"部署什么规则"（治理决策），两者独立。

## Profile 分层查找

ProfileLoader 按以下顺序查找 Profile：

1. **项目级** `.harness/profiles/{name}.yaml` → 用户自定义（优先）
2. **内置** `packages/core/harness/profiles/{name}.yaml` → 框架预设（兜底）

> 激活时将内置 Profile 复制到 `.harness/profiles/`。如已存在同名文件，保留用户版本（不覆盖）。用户可直接编辑 `.harness/profiles/` 下的文件——内置只是模板，编排才是目的。

## 知识库种子注入

Step 5 自动从项目结构提取 5 类种子知识，让用户第一次用就不空：

| 类型 | 内容 | 来源 |
|------|------|------|
| 架构 | 项目目录结构概览 | 自动扫描顶层目录 |
| 依赖 | 依赖管理文件（package.json/requirements.txt 等） | 自动检测 |
| 约定 | 编码命名、提交信息规范 | 通用最佳实践 |
| 风险 | XSS/敏感信息/DDoS 风险提醒 | 通用风险提示 |
| 术语表 | harness-cook 专有术语（Gate/Guardrails/Profile 等） | 框架内置 |

> 使用 `harness knowledge list` 查看全部知识条目。

## pip 安装源

安装核心包时自动选择 pip 源：

1. 用户 pip 全局配置（`pip config get global.index-url`）
2. 清华镜像 `https://pypi.tuna.tsinghua.edu.cn/simple`（国内网络降级）

---

← [命令总览](/cli/) · → [deactivate](/cli/deactivate)

# .harness 作为项目配置总目录

> 内置 hook/skill 通过绝对路径直接调用，不复制到项目；`.harness/` 只放项目特有配置

## 两个核心原则

1. **内置 skill/hook 不复制**——harness-cook 已经 git clone 到本地，内置的就在那里，直接调用。复制 = 版本漂移 + 占空间 + 更新不同步。跟 Python 包一样：`import numpy` 不需要把 numpy 复制到项目里。

2. **`.harness/` 只放项目特有的东西**——profiles、项目级 skill、审计日志、环境配置。不放内置的东西。

类比：
- `numpy` 在自己的安装目录，项目通过 `import numpy` 调用
- harness-cook 内置 hook 在自己的仓库目录，项目通过绝对路径直接调用
- 项目的 `.harness/` 只存项目级配置，类似 `.claude/` 只存 Claude Code 项目配置

## 目录结构

### harness-cook 仓库（框架自身，不动）

```
harness-cook/                # 已 git clone 到本地
  packages/hooks/            # ← 内置 hook（不动，直接调用）
    hook-session-init.py
    hook-task-audit.py
    hook-compliance-scan.py
    hook-guardrails-pii.py
    hook-prompt-guardrails.py
    hook-gate-pre-write.py
    git-pre-commit-hook.sh
  skills/                    # ← 内置 skill（不动，直接调用）
    auto-audit/SKILL.md + audit_report.py
    auto-review/SKILL.md + review_gate.py
    auto-verify/SKILL.md + verify.py
    harness-bridge/SKILL.md + bridge.py
```

### 项目 `.harness/`（只有项目特有的）

```
.harness/                    # 项目级配置（只有项目特有的）
  active_profile             # 活跃 Profile
  active_adapter             # 活跃适配器
  env                        # ← activate 时写入的环境变量
  profiles/                  # Profile YAML
    basic.yaml / default.yaml / enterprise.yaml
  skills/                    # ← 只有项目级 skill（用户自建的）
    custom-review/SKILL.md + review.py
  audit/                     # 审计日志 (gitignore)
```

## 路径解析机制

### `resolve_harness_root()` —— 统一路径解析

五级检测策略，优先级从高到低：

1. `.harness/env` 文件 — activate 时已写入，最可靠
2. `HARNESS_COOK_ROOT` 环境变量 — 用户明确指定
3. pip install 路径 — pip install 后可定位
4. `__file__` 推导 — 从代码文件位置推导
5. 当前工作目录 — 最后兜底

**关键**：在激活流程中，bridge deploy 在 `.harness/env` 创建之前执行，因此 cwd fallback 不可靠。`activate.py` 显式传入 `harness_root` 参数绕过自动检测。

### `resolve_hook_command()` —— 路径转换

识别三种路径模式：

- **内置路径**（`packages/hooks/`、`scripts/`、`skills/`）→ 拼接 `harness_root` 生成绝对路径
- **项目路径**（以 `.harness/` 开头）→ 保持原样，不转换
- **其他路径** → 保持原样（用户自管理的脚本）

```python
# 部署前（profile 中）
command: "python3 packages/hooks/hook-task-audit.py"

# 部署后（settings.json 中）
command: "python3 /Users/xxx/harness-cook/packages/hooks/hook-task-audit.py"
```

**为什么不使用 `$HARNESS_COOK_ROOT` 环境变量引用？**
- Claude Code settings.json 不支持 shell 变量展开
- 绝对路径确保每次 hook 触发时路径一致

### Profile YAML 路径区分

```yaml
# 内置 hook → 路径指向 harness-cook 仓库
session_start:
  - type: script
    command: "python3 packages/hooks/hook-session-init.py"

# 项目级 skill → 路径指向项目 .harness/
post_execute:
  - type: skill
    skill_id: custom-review
```

## 与 Claude Code `.claude/` 的类比

| Agent | 项目配置目录 | 内容 | 环境配置 |
|-------|------------|------|---------|
| Claude Code | `.claude/` | settings.json（hooks）+ CLAUDE.md | — |
| Harness | `.harness/` | profiles/ + skills/（项目级）+ audit/ + env | HARNESS_COOK_ROOT 等 |

两者都只放项目特有的配置。框架本身的东西留在框架的安装目录，通过路径机制引用。

## .harness/env 与 gitignore

`.harness/env` 应加入 gitignore——不同开发者的 harness-cook clone 位置可能不同：

```gitignore
.harness/env
.harness/audit/
```

但 `.harness/active_profile` 和 `.harness/profiles/` 不 gitignore——这些是项目团队共享的配置。

## 使用场景

### 场景 1：标准安装

```bash
cd harness-cook
python3 packages/cli/harness_cli.py activate --project /Users/xxx/my-project
```

### 场景 2：多项目共享

多个项目可以共享同一个 harness-cook 安装，每个项目的 `.claude/settings.json` 都指向同一个绝对路径。

### 场景 3：MCP Server 运行时路径

MCP Server 通过 Python 模块路径 (`-m harness_mcp_server`) 启动，由 `pip install` 保证可找到。

## 调试

```bash
# 查看 bridge 检测到的路径
PYTHONPATH=packages/core python3 -c "
from harness.config import resolve_harness_root
print('Detected root:', resolve_harness_root())
"

# 查看路径转换
PYTHONPATH=packages/core python3 -c "
from harness.config import resolve_hook_command, resolve_harness_root
root = resolve_harness_root()
cmd = 'python3 packages/hooks/hook-session-init.py'
print('Before:', cmd)
print('After:', resolve_hook_command(cmd, root))
"
```

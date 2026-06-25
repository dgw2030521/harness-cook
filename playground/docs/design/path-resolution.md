# 路径处理机制

> 内置路径绝对化转换 + 多级检测策略——确保 hooks 在任何项目目录都能正确执行

## 问题背景

harness-cook 的 profile 配置中使用相对路径：

```yaml
hooks:
  session_start:
    - type: script
      command: "python3 packages/hooks/hook-session-init.py"
```

但这些相对路径是相对于 **harness-cook 安装目录**，而不是用户的项目目录。如果直接复制相对路径到用户的 `.claude/settings.json`，hooks 会找不到文件。

## 解决方案：绝对路径转换

`resolve_hook_command()` 将内置路径转换为绝对路径，拼接 `harness_root`：

```python
# 部署前（profile 中）
command: "python3 packages/hooks/hook-task-audit.py"

# 部署后（settings.json 中）
command: "python3 /Users/xxx/harness-cook/packages/hooks/hook-task-audit.py"
```

**为什么不使用 `$HARNESS_COOK_ROOT` 环境变量引用？**
- Claude Code settings.json 不支持 shell 变量展开
- 绝对路径确保每次 hook 触发时路径一致，不依赖环境变量是否设置
- `harness_root` 由 `activate.py` 外部传入，保证始终指向正确的安装目录

## 检测机制

`resolve_harness_root()` 五级检测策略（bridge.deploy 内部备用，外部传入优先）：

1. **外部传入参数**（最可靠，推荐）——activate.py 通过 `bridge.deploy(harness_root=...)` 传入正确路径
2. **`.harness/env` 文件**——项目级持久化（activate Step 5 写入）
3. **环境变量** `HARNESS_COOK_ROOT`
4. **模块位置推导**（从 `__file__` 往上推导）
5. **当前工作目录**（降级方案，不推荐）

**重要**：在激活流程中，bridge deploy（Step 3）在 `.harness/env` 创建（Step 5）之前执行。因此 cwd fallback 此时不可靠。`activate.py` 显式传入 `harness_root` 参数绕过自动检测。

## 路径转换规则

`resolve_hook_command()` 识别以下路径模式：

- **内置路径**（`packages/hooks/`、`packages/core/`、`scripts/`、`skills/`）→ 拼接 `harness_root` 生成绝对路径
- **项目路径**（以 `.harness/` 开头）→ 保持原样，不转换
- **其他路径** → 保持原样（用户自管理的脚本）

```python
def resolve_hook_command(command: str, harness_root: str) -> str:
    builtin_patterns = ["packages/hooks/", "packages/core/", "skills/", "scripts/"]

    if command.startswith(".harness/"):
        return command  # 项目路径

    for pattern in builtin_patterns:
        if pattern in command:
            idx = command.find(pattern)
            relative_part = command[idx:]
            absolute_part = str(Path(harness_root) / relative_part)
            return command[:idx] + absolute_part

    return command  # 用户自管理脚本
```

## 使用场景

### 场景 1：标准安装

```bash
cd harness-cook
python3 packages/cli/harness_cli.py activate --project /Users/xxx/my-project
```

生成的 `.claude/settings.json` 中 hook 命令使用绝对路径，不依赖工作目录。

### 场景 2：多项目共享

多个项目可以共享同一个 harness-cook 安装，每个项目的 settings.json 都指向同一个绝对路径。

### 场景 3：MCP Server 运行时路径

MCP Server 通过 Python 模块路径 (`-m harness_mcp_server`) 启动，由 `pip install` 保证可找到。

## 注意事项

1. **移动 harness-cook 目录**：需要重新运行 `harness activate` 更新路径
2. **符号链接**：bridge 会自动解析为真实路径
3. **多版本共存**：可以在不同位置安装多个 harness-cook 版本，每个项目使用不同版本

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

## 相关文件

- `packages/core/harness/config.py` — `resolve_hook_command()` 和 `resolve_harness_root()`
- `packages/core/harness/bridge.py` — `deploy()` 的 `harness_root` 参数
- `packages/cli/cli_commands/activate.py` — 传入 `harness_root` 给 bridge.deploy()
- `packages/cli/cli_commands/deactivate.py` — 清理 `env.HARNESS_COOK_ROOT`

## 总结

harness-cook 通过绝对路径转换机制确保：

1. ✅ profile 使用相对路径，易于维护
2. ✅ 部署时自动转换为绝对路径（不使用环境变量引用）
3. ✅ `harness_root` 由 activate.py 外部传入，绕过 cwd fallback 的时序问题
4. ✅ 多个项目可以共享同一个安装
5. ✅ 不依赖工作目录，hooks 始终可以执行

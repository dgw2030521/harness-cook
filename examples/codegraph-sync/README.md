# CodeGraph Sync 示例

> 代码变更后自动同步 CodeGraph，保持代码图谱实时更新

**文档介绍**见 VitePress Demo 页面 [CodeGraph Sync](../../playground/docs/demo/codegraph-sync.md)——代码片段 + 预期输出 + 配置说明。本目录是可运行的脚本。

## 概述

此示例演示如何使用 harness-cook 的 hook 机制，在代码文件变更（Write/Edit）后自动执行 `codegraph sync`，无需手动操作。

**解决的问题：**
- ❌ 手动执行 `codegraph sync` 容易遗忘
- ❌ 代码图谱与源代码不同步
- ❌ AI Agent 基于过时的图谱做出错误决策

**解决方案：**
- ✅ 使用 PostToolUse hook 自动触发同步
- ✅ 只在代码变更工具（Write/Edit）后同步
- ✅ 静默执行，不干扰正常工作流

## 工作原理

```
用户修改代码
  ↓
Claude Code 执行 Write/Edit 工具
  ↓
PostToolUse hook 触发
  ↓
hook-codegraph-sync.py 检查 tool_name
  ↓
如果是 Write/Edit → 执行 codegraph sync
  ↓
CodeGraph 更新完成
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `hook-codegraph-sync.py` | Hook 脚本，执行 codegraph sync |
| `profile.yaml` | Profile 配置，定义 hook 触发规则 |
| `README.md` | 本文档 |

## 使用方法

### 1. 安装 CodeGraph

首先确保已安装 CodeGraph CLI：

```bash
npm install -g @codegraph/cli
```

### 2. 初始化 CodeGraph

在项目根目录初始化：

```bash
codegraph init
```

### 3. 使用此 Profile

#### 方式一：复制配置

将 `profile.yaml` 复制到你的项目：

```bash
cp examples/codegraph-sync/profile.yaml .harness/profiles/codegraph-sync.yaml
```

然后激活：

```bash
python3 packages/cli/harness_cli.py activate --profile codegraph-sync
```

#### 方式二：直接部署

在项目目录直接部署：

```bash
cd your-project
python3 /path/to/harness-cook/packages/cli/harness_cli.py activate \
  --profile-path /path/to/harness-cook/examples/codegraph-sync/profile.yaml
```

### 4. 验证

修改任意代码文件，观察是否自动同步：

```bash
# 修改代码
echo "# test" >> test.py

# 查看 CodeGraph 状态
codegraph status
```

## Hook 脚本详解

### 触发条件

```python
def should_sync(tool_name: str) -> bool:
    """只在代码变更工具后同步"""
    code_change_tools = {"Write", "Edit", "Patch", "write_file", "edit_file"}
    return tool_name in code_change_tools
```

### 执行逻辑

```python
def run_codegraph_sync() -> tuple[bool, str]:
    """执行 codegraph sync"""
    result = subprocess.run(
        ["codegraph", "sync"],
        capture_output=True,
        text=True,
        timeout=30
    )
    return result.returncode == 0, result.stdout
```

### 错误处理

- **codegraph 未安装**：输出警告，不阻止主流程
- **同步超时**：30秒超时，输出警告
- **同步失败**：输出错误信息，不阻止主流程

**设计原则**：Hook 失败不应阻止用户正常工作。

## 自定义扩展

### 添加更多触发条件

修改 `should_sync()` 函数：

```python
def should_sync(tool_name: str) -> bool:
    # 也包含 Bash 中的特定命令
    if tool_name == "Bash":
        # 可以通过 tool_input 判断具体命令
        return True
    return tool_name in {"Write", "Edit", "Patch"}
```

### 添加同步前的检查

```python
def pre_sync_check():
    """同步前检查"""
    # 检查是否有未提交的变更
    result = subprocess.run(["git", "status", "--porcelain"], capture_output=True)
    if not result.stdout.strip():
        return False, "没有文件变更，跳过同步"
    return True, "检测到文件变更"
```

### 添加同步后的通知

```python
def post_sync_notify(success: bool):
    """同步后通知"""
    if success:
        # 发送通知到 Slack/Discord
        subprocess.run(["notify-send", "CodeGraph 同步完成"])
```

## 与其他示例结合

### 结合 auto-test

在 codegraph sync 后自动运行测试：

```yaml
hooks:
  post_tool_use:
    # 1. 先同步 CodeGraph
    - type: script
      command: "python3 examples/codegraph-sync/hook-codegraph-sync.py"
    
    # 2. 再运行测试
    - type: script
      command: "python3 examples/auto-test/hook-auto-test.py"
```

### 结合 lint-check

在同步后自动检查代码质量：

```yaml
hooks:
  post_tool_use:
    # 1. 同步 CodeGraph
    - type: script
      command: "python3 examples/codegraph-sync/hook-codegraph-sync.py"
    
    # 2. 运行 lint
    - type: script
      command: "python3 examples/lint-check/hook-lint-check.py"
```

## 故障排查

### 问题：Hook 没有触发

**检查：**
1. 确认 profile 已激活：`cat .claude/settings.json`
2. 确认 hook 路径正确
3. 检查 Claude Code 日志

### 问题：codegraph sync 失败

**检查：**
1. 确认 codegraph 已安装：`which codegraph`
2. 确认已初始化：`codegraph status`
3. 手动测试：`codegraph sync`

### 问题：同步太慢

**优化：**
1. 调整超时时间（默认30秒）
2. 使用增量同步：`codegraph sync --incremental`
3. 只在特定文件类型变更后同步

## 最佳实践

1. **团队共享**：将 `profile.yaml` 提交到 git，团队成员共享配置
2. **CI/CD 集成**：在 CI 中也执行 `codegraph sync`，确保一致性
3. **定期全量同步**：每周执行一次 `codegraph sync --full`
4. **监控同步状态**：使用 `codegraph status` 检查同步状态

## 相关资源

- [CodeGraph 官方文档](https://codegraph.dev)
- [harness-cook Hook 机制](../../docs/13-脚手架化开发计划-20260612.md)
- [其他示例](../)

## License

MIT

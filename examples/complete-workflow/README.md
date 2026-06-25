# Complete Workflow 示例

> 完整的开发工作流自动化示例

**文档介绍**见 VitePress Demo 页面 [Complete Workflow](../../playground/docs/demo/complete-workflow.md)——代码片段 + 预期输出 + 配置说明。本目录是可运行的脚本。

## 概述

此示例展示如何组合多个 hooks，构建完整的自动化开发工作流：

```
代码变更
  ↓
1. Lint 检查（代码质量）
  ↓
2. 自动测试（功能验证）
  ↓
3. CodeGraph 同步（图谱更新）
  ↓
4. 审计记录（变更追踪）
```

## Profile 配置

```yaml
# .harness/profiles/complete-workflow.yaml
profile:
  name: complete-workflow
  description: 完整的开发工作流自动化

agent:
  adapter: claude-code

hooks:
  # 会话开始：初始化环境
  session_start:
    - type: script
      command: "python3 packages/hooks/hook-session-init.py"

  # 工具使用后：执行完整工作流
  post_tool_use:
    # 1. 代码质量检查
    - type: script
      command: "python3 examples/lint-check/hook-lint-check.py"
    
    # 2. 自动测试
    - type: script
      command: "python3 examples/auto-test/hook-auto-test.py"
    
    # 3. CodeGraph 同步
    - type: script
      command: "python3 examples/codegraph-sync/hook-codegraph-sync.py"
  
  # 任务执行后：审计记录
  post_execute:
    - type: skill
      skill_id: auto-audit

  # 会话结束：生成摘要
  session_end:
    - type: script
      command: "python3 packages/hooks/hook-task-audit.py"

gates:
  default_mode: hybrid
  checks:
    - id: no-secrets
      enabled: true
    - id: no-eval
      enabled: true
```

## 使用场景

### 场景 1：日常开发

开发者修改代码后，自动执行：
1. ✅ Lint 检查 - 确保代码质量
2. ✅ 运行测试 - 验证功能正确
3. ✅ 更新图谱 - 保持 CodeGraph 同步
4. ✅ 记录审计 - 追踪所有变更

### 场景 2：代码审查

审查者可以看到：
- 代码是否通过 lint 检查
- 测试是否全部通过
- CodeGraph 是否已更新
- 完整的变更审计日志

### 场景 3：团队协作

团队成员共享此 profile，确保：
- 统一的代码质量标准
- 自动化的测试验证
- 实时的图谱同步
- 完整的审计追踪

## 安装步骤

### 1. 复制 hooks

```bash
cd your-project
mkdir -p hooks

# 复制所有 hooks
cp /path/to/harness-cook/examples/lint-check/hook-lint-check.py hooks/
cp /path/to/harness-cook/examples/auto-test/hook-auto-test.py hooks/
cp /path/to/harness-cook/examples/codegraph-sync/hook-codegraph-sync.py hooks/
```

### 2. 安装依赖

```bash
# Python lint 工具
pip install ruff

# CodeGraph
npm install -g @codegraph/cli

# 初始化 CodeGraph
codegraph init
```

### 3. 激活 Profile

```bash
# 复制 profile
cp /path/to/harness-cook/examples/complete-workflow/profile.yaml \
   .harness/profiles/complete-workflow.yaml

# 激活
python3 /path/to/harness-cook/packages/cli/harness_cli.py activate \
  --profile complete-workflow
```

### 4. 验证

```bash
# 修改代码
echo "def test(): pass" >> test.py

# 观察自动执行的流程
# 应该看到：
# 🔍 检查代码质量: test.py
# ✅ 代码质量检查通过
# 🧪 检测到代码变更: test.py
# ✅ 测试通过
# ✅ CodeGraph 同步成功
```

## 自定义扩展

### 添加 Slack 通知

```yaml
hooks:
  post_tool_use:
    - type: script
      command: "python3 hooks/hook-lint-check.py"
    - type: script
      command: "python3 hooks/hook-auto-test.py"
    - type: script
      command: "python3 hooks/hook-codegraph-sync.py"
    - type: script
      command: "python3 hooks/hook-slack-notify.py"  # 新增
```

### 添加 Git 自动提交

```yaml
hooks:
  post_execute:
    - type: skill
      skill_id: auto-audit
    - type: script
      command: "python3 hooks/hook-git-auto-commit.py"  # 新增
```

### 条件执行

只在特定文件类型变更时执行：

```python
# hook-smart-workflow.py
def should_execute(changed_file: str) -> bool:
    """智能判断是否需要执行完整工作流"""
    # 只处理源代码文件
    code_extensions = {".py", ".js", ".ts", ".go"}
    return Path(changed_file).suffix in code_extensions
```

## 性能优化

### 并行执行

如果 hooks 之间没有依赖，可以并行执行：

```python
# hook-parallel-workflow.py
import concurrent.futures

def run_hooks():
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [
            executor.submit(run_lint),
            executor.submit(run_test),
            executor.submit(run_codegraph_sync),
        ]
        results = [f.result() for f in futures]
    return all(results)
```

### 增量执行

只执行受影响的检查：

```python
# hook-incremental-workflow.py
def detect_affected_tests(changed_file: str) -> list:
    """检测受变更影响的测试"""
    # 使用 CodeGraph 分析依赖关系
    result = subprocess.run(
        ["codegraph", "query", f"tests_that_depend_on:{changed_file}"],
        capture_output=True
    )
    return result.stdout.split('\n')
```

## 故障排查

### 问题：某个 hook 失败导致整个流程中断

**解决**：确保每个 hook 都返回 0 退出码，即使失败也只输出警告。

### 问题：工作流执行太慢

**解决**：
1. 使用并行执行
2. 只执行必要的检查
3. 增加超时时间
4. 使用缓存

### 问题：某些文件类型不需要完整工作流

**解决**：在 hook 中添加文件类型判断，跳过不相关的文件。

## 最佳实践

1. **渐进式采用**：先添加一个 hook，稳定后再添加更多
2. **监控性能**：记录每个 hook 的执行时间
3. **定期审查**：每月审查一次工作流，移除不必要的步骤
4. **团队反馈**：收集团队反馈，持续优化工作流

## 相关资源

- [CodeGraph Sync 示例](../codegraph-sync/)
- [Auto Test 示例](../auto-test/)
- [Lint Check 示例](../lint-check/)
- [Harness Cook 文档](../../docs/)

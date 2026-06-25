# Skill 插槽点完整指南

harness-cook 支持 **17 个插槽点**，覆盖 Agent 执行的完整生命周期。默认启用 3 个核心插槽，按需启用更多。

## 插槽点分类

### 会话级（2个）

| 插槽 | 触发时机 | 典型用途 | 示例 Skills |
|------|---------|---------|------------|
| `SESSION_START` | 会话开始 | 环境初始化、加载配置、显示欢迎信息 | `env-setup`, `welcome-banner` |
| `SESSION_END` | 会话结束 | 清理临时文件、生成会话摘要、保存状态 | `session-summary`, `cleanup` |

**默认启用：** ✅

```yaml
hooks:
  session_start:
    - type: script
      command: "python3 packages/hooks/hook-session-init.py"
  session_end:
    - type: script
      command: "python3 packages/hooks/hook-task-audit.py"
```

### 任务级（3个）

| 插槽 | 触发时机 | 典型用途 | 示例 Skills |
|------|---------|---------|------------|
| `PRE_EXECUTE` | Agent 执行任务前 | 输入验证、权限检查、依赖检查 | `validate-input`, `check-deps` |
| `POST_EXECUTE` | Agent 执行任务后 | 结果验证、审计记录、通知 | `auto-audit`, `notify-result` |
| `ON_ERROR` | 任务执行异常时 | 错误记录、自动恢复、告警 | `error-handler`, `auto-recover` |

**默认启用：** `POST_EXECUTE` ✅

```yaml
hooks:
  post_execute:
    - type: skill
      skill_id: auto-audit
  
  # 可选：启用 PRE_EXECUTE
  # pre_execute:
  #   - type: script
  #     command: "python3 scripts/validate-input.py"
  
  # 可选：启用 ON_ERROR
  # on_error:
  #   - type: script
  #     command: "python3 scripts/error-handler.py"
```

### 工具级（2个）

| 插槽 | 触发时机 | 典型用途 | 示例 Skills |
|------|---------|---------|------------|
| `PRE_TOOL_USE` | 使用工具前（Write/Edit/Bash 等） | 权限检查、内容过滤、风险评估 | `permission-check`, `content-filter` |
| `POST_TOOL_USE` | 使用工具后 | 结果验证、合规扫描、PII 检测 | `compliance-scan`, `pii-detect` |

**默认启用：** ❌

```yaml
hooks:
  pre_tool_use:
    - type: script
      command: "python3 scripts/permission-check.py"
  
  post_tool_use:
    - type: script
      command: "python3 packages/hooks/hook-compliance-scan.py"
```

### 门禁级（2个）

| 插槽 | 触发时机 | 典型用途 | 示例 Skills |
|------|---------|---------|------------|
| `ON_GATE_PASS` | 门禁检查通过后 | 自动部署、生成报告、标记完成 | `auto-deploy`, `generate-report` |
| `ON_GATE_FAIL` | 门禁检查失败时 | 自动修复、升级人工、生成修复建议 | `auto-fix`, `escalate-human` |

**默认启用：** ❌

```yaml
hooks:
  on_gate_pass:
    - type: skill
      skill_id: auto-deploy
  
  on_gate_fail:
    - type: skill
      skill_id: auto-fix
```

### 文件级（1个）

| 插槽 | 触发时机 | 典型用途 | 示例 Skills |
|------|---------|---------|------------|
| `ON_FILE_CHANGE` | 文件变更时（Write/Edit 后） | 自动格式化、lint 检查、同步更新 | `auto-format`, `lint-check`, `sync-deps` |

**默认启用：** ❌

```yaml
hooks:
  on_file_change:
    - type: script
      command: "python3 scripts/auto-format.py"
```

### 提交级（2个）

| 插槽 | 触发时机 | 典型用途 | 示例 Skills |
|------|---------|---------|------------|
| `PRE_COMMIT` | 提交代码前 | 代码审查、测试运行、提交信息检查 | `auto-review`, `run-tests`, `check-commit-msg` |
| `POST_COMMIT` | 提交代码后 | 推送通知、更新看板、触发 CI | `notify-push`, `update-kanban`, `trigger-ci` |

**默认启用：** ❌

```yaml
hooks:
  pre_commit:
    - type: skill
      skill_id: auto-review
  
  post_commit:
    - type: script
      command: "python3 scripts/trigger-ci.py"
```

### 协作级（2个）

| 插槽 | 触发时机 | 典型用途 | 示例 Skills |
|------|---------|---------|------------|
| `ON_DELEGATE` | 委派任务给子 Agent 时 | 记录委派原因、设置超时、监控进度 | `delegate-tracker`, `timeout-watcher` |
| `ON_CONFLICT` | 检测到冲突时（文件冲突/Agent 冲突） | 冲突分析、自动合并、人工仲裁 | `conflict-analyzer`, `auto-merge` |

**默认启用：** ❌

```yaml
hooks:
  on_delegate:
    - type: script
      command: "python3 scripts/delegate-tracker.py"
  
  on_conflict:
    - type: script
      command: "python3 scripts/conflict-analyzer.py"
```

### 决策级（2个）

| 插槽 | 触发时机 | 典型用途 | 示例 Skills |
|------|---------|---------|------------|
| `ON_DECISION` | Agent 做出重要决策时 | 记录决策原因、评估风险、存档 | `decision-logger`, `risk-assessor` |
| `ON_ESCALATION` | 问题升级到人工时 | 通知相关人、生成上下文、暂停等待 | `notify-human`, `context-generator` |

**默认启用：** ❌

```yaml
hooks:
  on_decision:
    - type: script
      command: "python3 scripts/decision-logger.py"
  
  on_escalation:
    - type: script
      command: "python3 scripts/notify-human.py"
```

### 交互级（1个）

| 插槽 | 触发时机 | 典型用途 | 示例 Skills |
|------|---------|---------|------------|
| `USER_PROMPT_SUBMIT` | 用户提交提示词时 | 提示词优化、安全检查、上下文注入 | `prompt-enhancer`, `safety-check` |

**默认启用：** ❌

```yaml
hooks:
  user_prompt_submit:
    - type: script
      command: "python3 scripts/prompt-enhancer.py"
```

## 配置示例

### 最小配置（默认）

```yaml
# .harness/profiles/default.yaml
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

### 标准配置（推荐）

```yaml
hooks:
  # 会话级
  session_start:
    - type: script
      command: "python3 packages/hooks/hook-session-init.py"
  session_end:
    - type: script
      command: "python3 packages/hooks/hook-task-audit.py"
  
  # 任务级
  post_execute:
    - type: skill
      skill_id: auto-audit
  
  # 工具级
  post_tool_use:
    - type: script
      command: "python3 packages/hooks/hook-compliance-scan.py"
  
  # 门禁级
  on_gate_fail:
    - type: skill
      skill_id: auto-fix
```

### 严格配置（生产环境）

```yaml
hooks:
  # 会话级
  session_start: [...]
  session_end: [...]
  
  # 任务级
  pre_execute:
    - type: script
      command: "python3 scripts/validate-input.py"
  post_execute:
    - type: skill
      skill_id: auto-audit
  on_error:
    - type: script
      command: "python3 scripts/error-handler.py"
  
  # 工具级
  pre_tool_use:
    - type: script
      command: "python3 scripts/permission-check.py"
  post_tool_use:
    - type: script
      command: "python3 packages/hooks/hook-compliance-scan.py"
  
  # 文件级
  on_file_change:
    - type: script
      command: "python3 scripts/auto-format.py"
  
  # 提交级
  pre_commit:
    - type: skill
      skill_id: auto-review
  post_commit:
    - type: script
      command: "python3 scripts/trigger-ci.py"
  
  # 决策级
  on_decision:
    - type: script
      command: "python3 scripts/decision-logger.py"
  on_escalation:
    - type: script
      command: "python3 scripts/notify-human.py"
```

## 与 Claude Code Hooks 的映射

Skill 插槽与 Claude Code 原生 Hook 的映射关系：6 个原生 Hook（SessionStart/SessionEnd/PreToolUse/PostToolUse/PostToolUseFailure/UserPromptSubmit）直接映射，其余插槽通过内部实现或 matcher 过滤实现。

> 📖 映射详见 [Claude Code 使用指南](./agent-claude-code#hook-点映射)

## 内置 Skills

| Skill | 插槽 | 功能 |
|-------|------|------|
| `auto-audit` | `POST_EXECUTE` | 任务完成后自动记录审计日志 |
| `auto-review` | `PRE_COMMIT` | 提交前自动代码审查 |
| `auto-verify` | `ON_GATE_PASS` | 门禁通过后自动验证 |

## Superpowers Bridge

通过 Superpowers Bridge 将 Claude Code superpowers 插件的 skills 自动注册到 SkillRegistry，按功能语义映射到对应插槽。所有 superpowers skills 使用 `superpowers:` 前缀，与内置 skills 的 namespace 完全隔离——即使名称冲突也不会覆盖。

> 📖 完整映射表、四步流程、配置示例 → [Superpowers Bridge](./superpowers-bridge#slot-映射)

```python
from harness.superpowers_bridge import register_superpowers_skills
from harness.skill_registry import SkillRegistry

registry = SkillRegistry()
count = register_superpowers_skills(registry)  # 自动发现+注册

# MCP 工具输出包含 source 字段区分来源
# {"id": "auto-audit", "source": "builtin", ...}
# {"id": "superpowers:brainstorming", "source": "superpowers", ...}
```

在 Profile 配置中引用 superpowers skills：

```yaml
hooks:
  pre_execute:
    - type: skill
      skill_id: superpowers:brainstorming
  on_error:
    - type: skill
      skill_id: superpowers:debugging
```

详见项目 `examples/superpowers-bridge/` 目录和 [Superpowers Bridge Demo](/demo/superpowers-bridge)。

## 自定义 Skill

创建自定义 Skill：

```python
# scripts/my-custom-skill.py
#!/usr/bin/env python3
import sys
import os

# 添加 core 包到 PYTHONPATH
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
core_path = os.path.join(project_root, "packages", "core")
if core_path not in sys.path:
    sys.path.insert(0, core_path)

from harness.types import TaskResult, TaskStatus

def main():
    # 你的 Skill 逻辑
    print("✅ My custom skill executed successfully")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

在 Profile 中配置：

```yaml
hooks:
  post_execute:
    - type: script
      command: "python3 scripts/my-custom-skill.py"
```

## 总结

- **17 个插槽点** 覆盖完整生命周期
- **默认 3 个核心插槽** 覆盖 90% 场景
- **按需启用** 更多插槽实现细粒度控制
- **三种 Hook 类型**：script / skill / prompt
- **与 Claude Code 完全兼容**

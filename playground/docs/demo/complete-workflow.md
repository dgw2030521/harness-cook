# Complete Workflow Demo

> 组合所有 hooks，构建完整的自动化开发工作流。

**完整可运行脚本**见项目 `examples/complete-workflow/` 目录（`profile.yaml`）。本页是文档介绍——代码片段 + 预期输出 + 配置说明。

## 问题

需要手动执行多个步骤（lint → test → sync → audit）。

## 解决方案

组合所有 hooks，自动执行完整工作流，统一的配置管理。

## 工作流

```
代码变更 → Lint 检查 → 自动测试 → CodeGraph 同步 → 审计记录
```

## Profile 配置

```yaml
hooks:
  session_start:
    - type: script
      command: "python3 packages/hooks/hook-session-init.py"
  post_tool_use:
    - type: script
      command: "python3 examples/lint-check/hook-lint-check.py"
    - type: script
      command: "python3 examples/auto-test/hook-auto-test.py"
    - type: script
      command: "python3 examples/codegraph-sync/hook-codegraph-sync.py"
  session_end:
    - type: script
      command: "python3 packages/hooks/hook-task-audit.py"
```

## 一键激活

```bash
python3 packages/cli/harness_cli.py activate \
  --profile-path examples/complete-workflow/profile.yaml
```

## 完整代码

完整代码见项目 `examples/complete-workflow/` 目录。

---

## 相关导航

- 📖 架构原理 → [Skill 插槽点](/guide/skill-slots) · [Bridge](/guide/bridge)

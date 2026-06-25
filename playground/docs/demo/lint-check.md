# Lint Check Demo

> 代码变更后自动检测并运行 lint 工具进行质量检查。

**完整可运行脚本**见项目 `examples/lint-check/` 目录（`hook-lint-check.py`）。本页是文档介绍——代码片段 + 预期输出 + 配置说明。

## 问题

代码不符合项目规范，审查时发现大量问题。

## 解决方案

自动检测并运行 lint 工具，实时反馈代码质量问题。

## 支持的工具

| 语言 | Lint 命令 |
|------|---------|
| Python | `ruff check` / `flake8` |
| JavaScript/TypeScript | `eslint` |
| Go | `gofmt` |

## Profile 配置

```yaml
hooks:
  post_tool_use:
    - type: script
      command: "python3 hooks/hook-lint-check.py"
```

## 完整代码

完整代码见项目 `examples/lint-check/` 目录。

---

## 相关导航

- 📖 架构原理 → [Skill 插槽点](/guide/skill-slots)

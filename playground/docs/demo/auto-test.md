# Auto Test Demo

> 代码变更后自动检测文件语言并运行相关测试。

**完整可运行脚本**见项目 `examples/auto-test/` 目录（`hook-auto-test.py`）。本页是文档介绍——代码片段 + 预期输出 + 配置说明。

## 问题

代码修改后忘记运行测试，导致引入 bug。

## 解决方案

智能检测文件类型，自动运行相应的测试命令，快速反馈测试结果。

## 支持的语言

| 语言 | 测试命令 |
|------|---------|
| Python | `pytest` |
| JavaScript/TypeScript | `npm test` |
| Go | `go test` |
| Java/Kotlin | `./gradlew test` |

## Profile 配置

```yaml
hooks:
  post_tool_use:
    - type: script
      command: "python3 hooks/hook-auto-test.py"
```

## 完整代码

完整代码见项目 `examples/auto-test/` 目录。

---

## 相关导航

- 📖 架构原理 → [Skill 插槽点](/guide/skill-slots)

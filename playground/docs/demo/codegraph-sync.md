# CodeGraph Sync Demo

> 代码变更后自动同步 CodeGraph，保持代码图谱实时更新。

**完整可运行脚本**见项目 `examples/codegraph-sync/` 目录（`hook-codegraph-sync.py`）。本页是文档介绍——代码片段 + 预期输出 + 配置说明。

## 问题

手动执行 `codegraph sync` 容易遗忘，导致图谱与代码不同步。

## 解决方案

使用 PostToolUse hook 自动触发同步——只在 Write/Edit 工具后同步，静默执行，不干扰工作流。

## Hook 脚本

```python
#!/usr/bin/env python3
"""hook-codegraph-sync.py — 代码变更后自动同步 CodeGraph"""

import sys, json, subprocess

def main():
    hook_input = json.loads(sys.stdin.read())
    tool_name = hook_input.get("tool_name", "")

    if tool_name in ["Write", "Edit"]:
        try:
            subprocess.run(["codegraph", "sync"], capture_output=True, timeout=30)
            print("✅ CodeGraph synced", file=sys.stderr)
        except Exception as e:
            print(f"⚠️ CodeGraph sync failed: {e}", file=sys.stderr)

    sys.exit(0)

if __name__ == "__main__":
    main()
```

## Profile 配置

```yaml
hooks:
  post_tool_use:
    - type: script
      command: "python3 hooks/hook-codegraph-sync.py"
```

## 完整代码

完整代码见项目 `examples/codegraph-sync/` 目录。

---

## 相关导航

- 📖 架构原理 → [Skill 插槽点](/guide/skill-slots)

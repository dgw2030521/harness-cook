# check — 合规/质量检查

> 扫描指定路径的产出物，执行合规规则检查

```bash
# 检查当前目录
harness check

# 检查指定路径
harness check src/

# 只检查安全类别
harness check --category security

# 自动修复
harness check --fix

# JSON 格式输出
harness check --output json
```

## 参数

| 参数 | 说明 |
|------|------|
| `path` | 要检查的路径（默认当前目录） |
| `--category` | 只检查指定类别: security/coding |
| `--severity` | 只显示指定严重级别: critical/high/medium/low |
| `--fix` | 尝试自动修复（仅 auto_fixable 违规） |
| `--output` | 输出格式: table/json/summary |

---

← [run](/cli/run) · [命令总览](/cli/) · → [audit](/cli/audit)

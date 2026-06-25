# report — 合规报告生成

> 扫描指定路径，生成 HTML/DOT/DSM 格式的合规报告

```bash
# 默认生成 HTML 报告
harness report

# 指定路径
harness report src/

# DOT 格式（依赖关系图）
harness report --format dot

# DSM 格式（依赖结构矩阵）
harness report --format dsm

# 生成后自动打开浏览器
harness report --open

# 指定规则包
harness report --packs security privacy
```

## 参数

| 参数 | 说明 |
|------|------|
| `path` | 要扫描的项目路径（默认当前目录） |
| `--format` | 报告格式: html/dot/dsm |
| `--open` | 生成后自动打开浏览器 |
| `--output` | 报告输出目录（默认 .harness/reports） |
| `--packs` | 指定合规规则包（默认 security+privacy+architecture） |

---

← [audit](/cli/audit) · [命令总览](/cli/) · → [log](/cli/log)

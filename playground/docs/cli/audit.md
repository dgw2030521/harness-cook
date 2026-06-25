# audit — 查看审计记录

> 搜索和展示 Harness 审计日志

```bash
# 列出最近记录
harness audit

# 搜索关键词
harness audit "知识库"

# 按 session 过滤
harness audit --session abc123

# 按日期范围
harness audit --date-from 20260101 --date-to 20260301

# JSON 输出
harness audit --output json
```

## 参数

| 参数 | 说明 |
|------|------|
| `query` | 搜索关键词（空=列出最近记录） |
| `--session` | 按 session_id 过滤 |
| `--agent` | 按 agent_id 过滤 |
| `--date-from` | 起始日期 (YYYYMMDD) |
| `--date-to` | 截止日期 (YYYYMMDD) |
| `--limit` | 最大记录数（默认 20） |
| `--output` | 输出格式: table/json/detail |

---

← [check](/cli/check) · [命令总览](/cli/) · → [report](/cli/report)

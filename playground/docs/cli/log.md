# log — 查看执行记录

> 查看 hooks、skills、gates、session、audit 的执行记录

```bash
# 查看最近的全部记录
harness log

# 搜索关键词
harness log "gate"

# 按类型过滤
harness log --type hook
harness log --type skill
harness log --type gate
harness log --type session

# 实时跟踪（类似 tail -f）
harness log --follow

# JSON 格式
harness log --output json
```

## 参数

| 参数 | 说明 |
|------|------|
| `query` | 搜索关键词 |
| `--type` | 按事件类型过滤: hook/skill/gate/session/audit |
| `--limit / -n` | 显示条数（默认 20） |
| `--follow / -f` | 实时跟踪（类似 tail -f） |
| `--interval` | 跟踪间隔秒数（默认 2） |
| `--output / -o` | 输出格式: table/json |

---

← [report](/cli/report) · [命令总览](/cli/) · → [dashboard](/cli/dashboard)

# dashboard — Web UI

> 启动 Web UI 查看审计、Skills、Profile、合规等信息

```bash
# 默认启动
harness dashboard

# 自定义端口
harness dashboard --port 9000

# 开发模式（自动重载）
harness dashboard --reload
```

## 参数

| 参数 | 说明 |
|------|------|
| `--host` | 监听地址（默认 127.0.0.1） |
| `--port / -p` | 监听端口（默认 8765） |
| `--reload` | 开发模式：文件变更时自动重载 |

---

← [log](/cli/log) · [命令总览](/cli/) · → [docs](/cli/docs)

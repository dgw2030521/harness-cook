# CLI 命令参考

> harness-cook 的全部 CLI 命令——从终端直接操作 Harness 核心能力，不写代码也能体验

**安装方式**：`pip install -e packages/core` 或 `harness activate`

**全局参数**：

| 参数 | 说明 |
|------|------|
| `--verbose / -v` | 显示详细日志(DEBUG级别) |
| `--quiet / -q` | 只显示错误日志 |
| `--log-level` | 日志级别: DEBUG/INFO/WARNING/ERROR |
| `--log-format` | 日志格式: text(可读)/json(结构化) |
| `--timeout` | 全局超时(秒)，0=不限 |

---

## 🚀 快速体验

```bash
# 查看版本
harness version

# 查看全部命令
harness --help

# 查看某命令的帮助
harness knowledge --help
harness learn --help
```

---

## 🗂️ 命令速查表

| 命令 | 说明 | 常用子操作 | 详情 |
|------|------|-----------|------|
| `activate` | 初始化安装 | `--profile`, `--agent` | [→ 详情](/cli/activate) |
| `deactivate` | 移除安装 | — | [→ 详情](/cli/deactivate) |
| `update` | 一键更新 | `--skip-install`, `--verbose` | [→ 详情](/cli/update) |
| `plan` | DAG 可视化 | `--format tree/dot/json`, `--show-gates` | [→ 详情](/cli/plan) |
| `run` | 执行编排 | `--dry-run`, `--gate-mode` | [→ 详情](/cli/run) |
| `check` | 合规检查 | `--category`, `--severity`, `--fix` | [→ 详情](/cli/check) |
| `audit` | 审计查询 | `--session`, `--date-from/to` | [→ 详情](/cli/audit) |
| `report` | 报告生成 | `--format html/dot/dsm`, `--open` | [→ 详情](/cli/report) |
| `log` | 执行记录 | `--type`, `--follow`, `--output` | [→ 详情](/cli/log) |
| `dashboard` | Web UI | `--port`, `--reload` | [→ 详情](/cli/dashboard) |
| `docs` | 文档站点 | `--open`, `--build` | [→ 详情](/cli/docs) |
| `knowledge` | 知识管理 | `types/stats/list/search/semantic/add/get/delete` | [→ 详情](/cli/knowledge) |
| `learn` | 学习引擎 | `stats/recommendations/estimates/patterns/traces` | [→ 详情](/cli/learn) |
| `version` | 版本号 | — | [→ 详情](/cli/version) |

---

## 🔗 相关导航

- 📖 架构 → [Bridge](/guide/bridge) · [CLI 指南](/guide/cli) · [MCP Server](/guide/mcp-server)
- 🏃 Demo → [知识/规则/报告 Demo](/demo/knowledge-rule-report) · [学习+调度 Demo](/demo/learning-scheduler)
- 🎓 教程 → [基础用法](/tutorial/basic-usage) · [合规扫描](/tutorial/compliance-scan)

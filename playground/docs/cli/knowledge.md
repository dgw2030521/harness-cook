# knowledge — 知识管理

> 10 类知识 CRUD + 关键词搜索 + TF-IDF 语义搜索 + 统计

```bash
# 查看 10 种知识类型 + 4 级作用域
harness knowledge types

# 查看知识统计概览
harness knowledge stats

# 列出所有知识条目
harness knowledge list

# 按类型过滤
harness knowledge list --type risk

# 按作用域过滤
harness knowledge list --scope file

# 按标签过滤
harness knowledge list --tags "安全,XSS"

# 关键词搜索
harness knowledge search "认证"

# TF-IDF 语义搜索
harness knowledge semantic "前端技术选型和安全防护"

# 添加一条架构知识
harness knowledge add --title "项目架构" --content "前后端分离+微服务" --type architecture --scope project --tags "架构,微服务"

# 添加一条风险知识（指定来源+置信度）
harness knowledge add --title "XSS风险" --content "用户输入未sanitize" --type risk --scope file --tags "安全,XSS" --source llm --confidence 0.85

# 查看单个条目详情
harness knowledge get <id>

# 删除条目
harness knowledge delete <id>

# JSON 格式输出
harness knowledge stats --output json
harness knowledge list --output json
```

## 10 种知识类型

| 类型 | 值 | 适用场景 |
|------|-----|---------|
| ARCHITECTURE | architecture | 项目架构 — 系统概览、模块关系 |
| CONVENTION | convention | 编码约定 — 命名规则、代码风格 |
| DEPENDENCY | dependency | 依赖关系 — 包依赖、版本约束 |
| API | api | API 定义 — 接口契约、参数签名 |
| PATTERN | pattern | 设计模式 — 常见解法、最佳实践 |
| RISK | risk | 风险记录 — 已知风险、安全漏洞 |
| DECISION | decision | 架构决策 — ADR、技术选型理由 |
| TASK | task | 任务上下文 — 当前任务、工作流 |
| TEST | test | 测试策略 — 测试方案、覆盖率 |
| GLOSSARY | glossary | 术语表 — 项目专有名词、缩写 |

## 4 级作用域

| 作用域 | 值 | 说明 |
|--------|-----|------|
| PROJECT | project | 项目级 — 跨模块通用知识 |
| MODULE | module | 模块级 — 特定模块的知识 |
| FILE | file | 文件级 — 特定文件的知识 |
| FUNCTION | function | 函数级 — 特定函数的知识 |

## 参数

| 参数 | 说明 |
|------|------|
| `action` | 操作类型: list/search/semantic/add/get/delete/stats/types |
| `query_text` | 搜索关键词（search/semantic 操作需要，get/delete 操作为条目ID） |
| `--project` | 项目名（默认 default） |
| `--type` | 按知识类型过滤 |
| `--scope` | 按作用域过滤 |
| `--tags` | 按标签过滤（逗号分隔） |
| `--title` | 条目标题（add 操作需要） |
| `--content` | 条目内容（add 操作需要） |
| `--confidence` | 置信度 0.0-1.0（add 操作可选，默认 1.0） |
| `--source` | 知识来源: human/ast/llm/learning（add 操作可选，默认 human） |
| `--limit / -n` | 显示条数（默认 20） |
| `--output / -o` | 输出格式: table/json/detail |

---

← [docs](/cli/docs) · [命令总览](/cli/) · → [learn](/cli/learn)

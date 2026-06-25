# Dashboard 指南

harness-cook Dashboard 提供可视化界面，实时展示审计、Skills、Profile、合规、引擎集成状态等信息。

## 启动 Dashboard

```bash
# 默认启动
harness dashboard

# 指定端口
harness dashboard --port 9000

# 允许外部访问
harness dashboard --host 0.0.0.0

# 开发模式（自动重载）
harness dashboard --reload
```

浏览器访问 `http://localhost:8765`

## Dashboard Tab

### 概览

统计卡片 + 任务趋势图 + Token 消耗分布 + 引擎集成状态概览。

| 指标 | 说明 |
|------|------|
| 总任务数 | 所有执行的任务总数 |
| 已交付 | 成功完成的任务数 |
| 自动修复 | 门禁自动修复的违规数 |
| 升级人工 | 需要人工介入的任务数 |
| 平均耗时 | 任务平均执行时间 |
| Token 消耗 | 平均每个任务的 Token 消耗 |
| **引擎集成数** | 当前可用的外部引擎适配器数量 |
| **审计后端数** | 当前配置的审计存储后端数量 |

### 审计

审计记录搜索（决策链/行动链溯源）。

- 按关键词搜索
- 按 session 过滤
- 按 Agent 过滤
- 查看决策链和行动链详情
- **显示审计后端信息**（本地 / Langfuse / Arize / Datadog / Helicone）

### Agent

已注册 Agent 列表。

### Skills ⭐

已注册 Skills + 插槽分配 + 执行统计。

### Profile ⭐

当前 Profile 配置（hooks/gates/引擎配置详情）。

**显示内容：**
- 当前 Profile 名称和描述
- 默认 Agent
- Pipeline 步骤
- Gate 模式
- Hooks 配置
- Gate 配置
- **护栏引擎配置**（builtin / guardrails-ai / nemo / llama-guard / helicone）
- **合规引擎配置**（engines 列表 + language_routing）
- **审计后端配置**（backends 列表 + trace.format + collector_url）

### 合规

合规扫描 + 规则包列表 + 引擎路由状态。

- 输入内容进行合规扫描
- 查看所有规则包和规则详情
- 按类别过滤
- **查看引擎路由状态**（哪个引擎可用、fallback 到哪个内置 checker）
- **语言感知路由配置**

### 事件流

实时事件流。

- 任务开始/完成/失败
- 门禁检查
- Agent 注册
- 合规扫描
- **AUDIT_SECONDARY_FAIL 事件**（次存储写入失败）

### 门禁

门禁检查历史。

### 执行追踪

DAG 节点执行详情。

## API 端点

Dashboard 后端提供 REST API：

| 端点 | 说明 |
|------|------|
| `GET /api/stats` | 审计统计概览 |
| `GET /api/audit/search` | 审计记录搜索 |
| `GET /api/agents` | Agent 列表 |
| `GET /api/skills` | Skills 列表 + 插槽分配 |
| `GET /api/profiles` | Profile 列表或详情 |
| `GET /api/deploys` | Deploy 历史 |
| `GET /api/compliance/scan` | 合规扫描 |
| `GET /api/compliance/rules` | 规则包列表 |
| `GET /api/events` | 事件流 |
| `GET /api/gates/history` | 门禁历史 |
| `GET /api/traces` | 执行追踪 |
| `GET /api/health` | 健康检查 |
| **`GET /api/integrations/status`** | **引擎集成状态概览** |

### 示例：获取引擎集成状态

```bash
curl http://localhost:8765/api/integrations/status
```

响应：

```json
{
  "total_engines": 12,
  "available_engines": 8,
  "engines": [
    {"name": "guardrails-ai", "available": false, "fallback": "regex"},
    {"name": "sonarqube", "available": false, "fallback": "regex"},
    {"name": "archunit", "available": false, "fallback": "dependency_graph"},
    {"name": "dep_cruiser", "available": false, "fallback": "dependency_graph"},
    {"name": "helicone", "available": false, "fallback": "regex"}
  ],
  "audit_backends": ["local"],
  "language_routing": {
    "java": "archunit",
    "javascript": "dep_cruiser",
    "typescript": "dep_cruiser"
  }
}
```

## 自定义 Dashboard

### 修改端口

```bash
harness dashboard --port 9000
```

### 允许外部访问

```bash
harness dashboard --host 0.0.0.0
```

::: warning
允许外部访问时，请确保网络安全，Dashboard 没有认证机制。
:::

### 开发模式

```bash
harness dashboard --reload
```

## 技术栈

- **后端：** FastAPI + Python
- **前端：** 原生 HTML + CSS + JavaScript
- **图表：** Chart.js
- **主题：** 暗色主题

## 下一步

- [Skill 插槽点指南](/guide/skill-slots) —— 17 个插槽点的详细说明
- [CLI 指南](/guide/cli) —— 所有 CLI 命令
- [快速开始](/guide/quick-start) —— 一键激活流程 + 可选引擎安装

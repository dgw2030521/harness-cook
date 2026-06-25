# 审计使用教程

> 逐步掌握 harness-cook 审计层——从写入记录到哈希链验证、多后端双写。

**快速导航**：[📖 原理](/guide/audit-layer) · [🎓 教程（本页）](#教程步骤) · [🏃 Demo](/demo/audit)

---

## 前置

```bash
cd harness-cook/packages/core
export PYTHONPATH=.
```

---

## 步骤 1：创建审计存储

```python
from harness.audit import AuditStore

# 默认：自动检测项目根目录，存到 .harness/audit/
store = AuditStore()

# 指定存储目录
store = AuditStore(store_dir="/tmp/my-audit")

# 指定项目目录（会存到 {project_dir}/.harness/audit/）
store = AuditStore(project_dir="/path/to/project")
```

---

## 步骤 2：写入审计记录

```python
from harness.audit import AuditEntry
from datetime import datetime

entry = AuditEntry(
    session_id="session-001",
    agent_id="claude-code",
    action="execute",
    decision="completed",
    timestamp=datetime.now(),
    outcomes=[
        {"rule": "SEC-001", "passed": True, "severity": "high"},
        {"rule": "PII-001", "passed": False, "severity": "critical"},
    ],
)

entry_id = store.save(entry)
print(f"记录 ID: {entry_id}")
```

---

## 步骤 3：查询审计记录

```python
# 按关键词搜索
entries = store.search("session-001")
print(f"找到记录: {len(entries)}")

for e in entries:
    print(f"  session={e.session_id}, action={e.action}, decision={e.decision}")
```

---

## 步骤 4：验证哈希链完整性

```python
# 写入多条记录构建链
for i in range(3):
    store.save(AuditEntry(
        session_id=f"test-{i}",
        agent_id="demo",
        action="execute",
        decision="completed",
        timestamp=datetime.now(),
        outcomes=[],
    ))

# 验证链完整性
result = store.verify_chain()
print(f"链完整: {result['valid']}")
print(f"总记录: {result['total_records']}")
print(f"篡改记录: {result['tampered']}")
print(f"断链位置: {result['broken_links']}")

# 更全面的完整性报告
report = store.integrity_report()
print(f"完整性报告: {report}")
```

---

## 步骤 5：多后端双写

```python
from harness.audit import AuditStore
from harness.integrations.multi_store import MultiAuditStore
from harness.bus import EventBus

bus = EventBus()
primary = AuditStore()
secondary = AuditStore(store_dir="/tmp/secondary")

# 双写——主存必须成功，次存火忘式写入
multi = MultiAuditStore([primary, secondary], bus=bus)

entry_id = multi.save(entry)
print(f"双写成功: {entry_id}")

# 查询只从主存储
entries = multi.search("session-001")
```

---

## 步骤 6：外部审计后端（可选）

### 验证层级

Langfuse 是团队级 LLM 可观测性平台——个人开发环境通常不需要。验证分三个层级：

| 层级 | 前提 | 可验证什么 |
|------|------|-----------|
| 层级 1（单元测试） | 无额外前提 | LangfuseAuditStore 可导入、初始化、Protocol 兼容 |
| 层级 2 | `pip install langfuse` | SDK 可 import、client 可创建（但不连真实服务） |
| 层级 3（远程服务） | Langfuse 账号 + key | 真实写入 trace/spans |

### 安装 SDK

```bash
pip install harness-cook[langfuse]    # 或 pip install langfuse>=2.0
```

### Langfuse 作为次存储

LangfuseAuditStore 通常作为 MultiAuditStore 的**纯写次存储**——主存储用本地 AuditStore，Langfuse 负责火忘式写入：

```python
from harness.integrations.langfuse_store import LangfuseAuditStore

langfuse = LangfuseAuditStore(
    public_key="pk-xxx",                          # 或从 LANGFUSE_PUBLIC_KEY 环境变量读取
    secret_key="sk-xxx",                          # 或从 LANGFUSE_SECRET_KEY 环境变量读取
    host="https://cloud.langfuse.com",            # 或自托管地址
)

# 双写——本地主存 + Langfuse 次存
from harness.integrations.multi_store import MultiAuditStore
multi = MultiAuditStore([primary, langfuse], bus=bus)

# save() 同时写入本地和 Langfuse
# search()/verify_chain() 只从本地主存储
# Langfuse 写入失败 → warning + AUDIT_SECONDARY_FAIL 事件，不阻塞
```

### 数据映射

每个 AuditEntry 映射为 Langfuse 的 trace + spans：

| AuditEntry 字段 | → Langfuse 对象 |
|-----------------|----------------|
| `session_id` | trace ID |
| `agent_id` | trace name + metadata |
| `decisions[]` | decision-{i} spans |
| `actions[]` | action-{i} spans |
| `outcomes[]` | outcome-{i} spans |
| `chain_hash` | trace tags |
| `risk_assessment` | trace metadata |

### 限制

Langfuse SDK 没有搜索/加载 API，所以 LangfuseAuditStore 的读操作受限：

| 操作 | LangfuseAuditStore 行为 | 应该用什么 |
|------|-------------------------|-----------|
| `save()` | ✅ 写入 trace + spans | 正常使用 |
| `search()` | 返回空列表 + warning | 用本地 AuditStore |
| `load()` | 返回空列表 | 用本地 AuditStore |
| `verify_chain()` | 返回 `{valid: True}` | 用本地 AuditStore |
| `integrity_report()` | 简化报告 | 用本地 AuditStore |

**结论**：Langfuse 是**纯写次存储**——写入审计数据到 LLM 可观测性平台，但读取和验证必须用本地主存储。

---

## 步骤 7：OTel 导出

```python
from harness.integrations.traceloop_exporter import TraceloopExporter

exporter = TraceloopExporter()
# 导出审计记录为 OpenTelemetry Span 格式
# 任何 OTel Collector 都能消费（Jaeger/Zipkin/Tempo）
```

---

## 步骤 8：Profile YAML 配置

Profile YAML 段定义见 [审计层原理](/guide/audit-layer#profile-yaml-配置)（`audit.backends` / `trace_format` / `collector_url` 等）。上面步骤 1-7 的 Python 配置即对应 YAML 中 `backends: [local]` + `trace_format: builtin` 的字段；启用 Langfuse 双写时改 `backends: [local, langfuse]`，启用 OTel 导出时改 `trace_format: otel-json` 并填 `collector_url`。

---

## 相关导航

- 📖 [审计层原理](/guide/audit-layer)
- 🏃 [审计 Demo](/demo/audit) —— 可运行脚本 + 预期输出

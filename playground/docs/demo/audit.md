# 审计 Demo

> 跑起来看看审计层的 SHA-256 哈希链、MultiAuditStore 双写、外部后端和 OTel 导出。

## 前置

```bash
cd harness-cook/packages/core
PYTHONPATH=. python3 -c "from harness.audit import AuditStore; print('✅ OK')"
```

---

## Demo 1：审计存储写入与查询

```python
from harness.audit import AuditStore, AuditEntry
from datetime import datetime

store = AuditStore()
entry = AuditEntry(
    session_id="verify-test",
    agent_id="test-agent",
    action="execute",
    decision="completed",
    timestamp=datetime.now(),
    outcomes=[{"rule": "SEC-001", "passed": True}],
)
store.save(entry)

# 查询审计记录
entries = store.search("verify-test")
print(f"记录数: {len(entries)}")
for e in entries:
    print(f"  session={e.session_id}, action={e.action}, decision={e.decision}")
```

### 预期输出

| 观察项 | 期望值 |
|--------|--------|
| `save(entry)` 返回 | entry_id 字符串 |
| `.harness/audit/` 目录 | 新增 JSON 文件 |
| JSON 文件内容 | 包含 chain_hash 字段 |
| `store.chain_head` | 更新为新记录的 hash |

---

## Demo 2：哈希链完整性验证

```python
from harness.audit import AuditStore, AuditEntry
from datetime import datetime

store = AuditStore()

# 写入多条记录构建链
for i in range(3):
    entry = AuditEntry(
        session_id=f"chain-test-{i}",
        agent_id="chain-agent",
        action="execute",
        decision="completed",
        timestamp=datetime.now(),
        outcomes=[],
    )
    store.save(entry)

# 验证链完整性
result = store.verify_chain()
print(f"链完整: {result['valid']}")
print(f"总记录: {result['total_records']}")
print(f"已验证: {result['verified_records']}")
print(f"篡改记录: {result['tampered']}")
print(f"断链位置: {result['broken_links']}")

# integrity_report 更全面的报告
report = store.integrity_report()
print(f"完整性报告: {report}")
```

### 预期输出

| 观察项 | 期望值 |
|--------|--------|
| `result['valid']` | `True` |
| `result['total_records']` | ≥ 3 |
| `result['verified_records']` | ≥ 3 |
| `result['tampered']` | 空列表 `[]` |
| `result['broken_links']` | 空列表 `[]` |

---

## Demo 3：IAuditStore Protocol 兼容性

```python
from harness.integrations.audit_store_protocol import IAuditStore
from harness.audit import AuditStore
from harness.integrations.multi_store import MultiAuditStore

# AuditStore 满足 Protocol
local = AuditStore()
print(f"AuditStore 满足 IAuditStore: {isinstance(local, IAuditStore)}")

# MultiAuditStore 满足 Protocol
multi = MultiAuditStore([local])
print(f"MultiAuditStore 满足 IAuditStore: {isinstance(multi, IAuditStore)}")
```

---

## Demo 4：MultiAuditStore 双写

```python
from harness.audit import AuditStore, AuditEntry
from harness.integrations.multi_store import MultiAuditStore
from harness.bus import EventBus
from datetime import datetime

bus = EventBus()
primary = AuditStore()
secondary = AuditStore(store_dir="/tmp/harness-secondary")

multi = MultiAuditStore([primary, secondary], bus=bus)

entry = AuditEntry(
    session_id="multi-verify",
    agent_id="test",
    action="execute",
    decision="completed",
    timestamp=datetime.now(),
    outcomes=[],
)

# 双写——主存和次存都会写入
result = multi.save(entry)
print(f"写入结果: {result}")

# 查询只从主存储
entries = multi.search("multi-verify")
print(f"主存储记录数: {len(entries)}")
```

### 预期输出

| 操作 | 主存储 | 次存储 |
|------|--------|--------|
| `save(entry)` | 必须成功 | 火忘式写入 |
| `save(entry)` 主存失败 | 整体失败，抛异常 | 不触发 |
| `save(entry)` 次存失败 | 主存成功，整体成功 | warning + AUDIT_SECONDARY_FAIL 事件 |
| `search()` | 仅从主存储 | 不参与 |

---

## Demo 5：外部审计后端导入

```python
from harness.integrations.audit_store_protocol import IAuditStore

# Langfuse
from harness.integrations.langfuse_store import LangfuseAuditStore
langfuse = LangfuseAuditStore(public_key="pk-test", secret_key="sk-test", host="http://localhost")
print(f"LangfuseAuditStore 满足 IAuditStore: {isinstance(langfuse, IAuditStore)}")

# Arize
from harness.integrations.arize_store import ArizeAuditStore
arize = ArizeAuditStore(api_key="test", space_id="test", model_id="test")
print(f"ArizeAuditStore 满足 IAuditStore: {isinstance(arize, IAuditStore)}")

# Datadog
from harness.integrations.datadog_store import DatadogAuditStore
datadog = DatadogAuditStore(api_key="test", site="datadoghq.com")
print(f"DatadogAuditStore 满足 IAuditStore: {isinstance(datadog, IAuditStore)}")

# Helicone
from harness.integrations.helicone_store import HeliconeAuditStore
helicone = HeliconeAuditStore(api_key="test")
print(f"HeliconeAuditStore 满足 IAuditStore: {isinstance(helicone, IAuditStore)}")
```

### 预期输出

所有外部后端 `isinstance(_, IAuditStore)` → `True`，即使 SDK 未安装也能创建（懒初始化）。

---

## Demo 6：TraceloopExporter OTel 导出

```python
from harness.integrations.traceloop_exporter import TraceloopExporter

exporter = TraceloopExporter()
print(f"TraceloopExporter 可创建: ✅")
# 实际导出需要 OTel Collector 或 Traceloop 服务可用
```

---

## Demo 7：MCP 工具调用

```python
from harness_mcp_server import HarnessMCPServer

server = HarnessMCPServer()

# harness_audit 支持 backend 参数
tool = next(t for t in server._TOOL_DEFINITIONS if t['name'] == 'harness_audit')
params = list(tool['inputSchema']['properties'].keys())
print(f"harness_audit 参数: {params}")
# 应包含: query, session, agent, limit, format, backend

# harness_trace_export 支持 OTel 导出
tool2 = next(t for t in server._TOOL_DEFINITIONS if t['name'] == 'harness_trace_export')
params2 = list(tool2['inputSchema']['properties'].keys())
print(f"harness_trace_export 参数: {params2}")
# 应包含: format, collector_url, date_from, date_to
```

---

## Profile YAML 配置示例

Profile YAML 段定义见 [审计层原理](/guide/audit-layer#profile-yaml-配置)（`audit.backends` / `trace_format` / `collector_url` 等），Demo 中的可运行脚本即对应该配置的本地哈希链存储、MultiAuditStore 双写与 TraceloopExporter OTel 导出。

---

## 相关导航

- 📖 架构原理 → [审计层](/guide/audit-layer)
- 🎓 使用方法 → [审计使用](/tutorial/audit-usage)

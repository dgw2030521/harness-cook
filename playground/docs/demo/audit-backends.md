# 审计后端 Demo

> Langfuse + Arize + Datadog + MultiStore 双写 + Traceloop/OTel 导出——五大审计存储后端

**定位**：harness-cook 的审计层支持多后端同时写入——Langfuse/Arize/Datadog 三大可观测性平台 + MultiStore 双写故障降级 + OTel 标准导出。

完整可运行脚本见项目 `examples/audit-backends/` 目录（`demo_audit_backends.py`）。

---

## Demo 1：Langfuse 审计后端

```python
from harness.integrations.langfuse_store import LangfuseAuditStore, LangfuseConfig

config = LangfuseConfig(
    public_key="pk-...",
    secret_key="sk-...",
    host="https://cloud.langfuse.com",
)

store = LangfuseAuditStore(config)

# 写入审计记录
store.write(AuditEntry(
    action="code_generate",
    agent_id="coder-agent",
    content_hash="sha256-...",
    metadata={"model": "gpt-4", "tokens": 1500},
))

# 搜索审计记录
results = store.search(query="code_generate", limit=10)
print(f"Langfuse 审计记录: {len(results)}")
```

### 预期输出

| 观察项 | 说明 |
|--------|------|
| `write()` | 审计记录写入 Langfuse 平台 |
| `search()` | 在 Langfuse 中搜索审计记录 |
| 降级 | Langfuse SDK 未安装 → 自动降级到本地 JSON 存储 |

---

## Demo 2：Arize 审计后端

```python
from harness.integrations.arize_store import ArizeAuditStore, ArizeConfig

config = ArizeConfig(
    api_key="arize-...",
    space_key="space-...",
    model_id="harness-agent",
)

store = ArizeAuditStore(config)

# 写入审计记录
store.write(AuditEntry(
    action="gate_check",
    agent_id="validator-agent",
    content_hash="sha256-...",
))

# 搜索审计记录
results = store.search(query="gate_check")
```

### 预期输出

| 观察项 | 说明 |
|--------|------|
| `write()` | 审计记录写入 Arize ML 可观测平台 |
| `search()` | 在 Arize 中搜索审计记录 |
| 降级 | Arize SDK 未安装 → 自动降级到本地 JSON 存储 |

---

## Demo 3：Datadog 审计后端

```python
from harness.integrations.datadog_store import DatadogAuditStore, DatadogConfig

config = DatadogConfig(
    api_key="dd-...",
    app_key="dd-app-...",
    site="datadoghq.com",
)

store = DatadogAuditStore(config)

# 写入审计记录
store.write(AuditEntry(
    action="compliance_scan",
    agent_id="compliance-agent",
    content_hash="sha256-...",
))

# 搜索审计记录
results = store.search(query="compliance_scan")
```

### 预期输出

| 观察项 | 说明 |
|--------|------|
| `write()` | 审计记录写入 Datadog 企业监控平台 |
| `search()` | 在 Datadog 中搜索审计记录 |
| 降级 | Datadog SDK 未安装 → 自动降级到本地 JSON 存储 |

---

## Demo 4：MultiAuditStore 双写

```python
from harness.integrations.multi_store import MultiAuditStore, MultiStoreConfig
from harness.integrations.langfuse_store import LangfuseAuditStore
from harness.integrations.arize_store import ArizeAuditStore

stores = [
    LangfuseAuditStore(langfuse_config),
    ArizeAuditStore(arize_config),
]

multi = MultiAuditStore(stores, config=MultiStoreConfig(
    failover=True,         # 故障自动降级
    parallel_write=True,   # 并行写入
))

# 双写——同时写入 Langfuse + Arize
result = multi.write(AuditEntry(
    action="code_generate",
    agent_id="coder-agent",
    content_hash="sha256-...",
))

print(f"写入成功数: {result.success_count}")
print(f"降级数: {result.fallback_count}")

# 搜索——优先从主后端搜索
results = multi.search(query="code_generate")
```

### 预期输出

| 观察项 | 期望值 |
|--------|--------|
| `result.success_count` | 成功写入的后端数量 |
| `result.fallback_count` | 降级到本地存储的次数 |
| 搜索优先级 | 主后端 → 备后端 → 本地存储 |

**双写保障**：任一后端故障不影响审计完整性——自动降级到本地存储，事后可回填。

---

## Demo 5：Traceloop / OTel 导出

```python
from harness.integrations.traceloop_exporter import TraceloopExporter
from harness.otel_integration import OTelIntegration, OTelConfig

# OTel 集成
otel = OTelIntegration(OTelConfig(
    service_name="harness-cook",
    otlp_endpoint="http://localhost:4317",
))

# 导出审计记录为 OTel Span
spans = otel.export_audit_entries(entries=[
    AuditEntry(action="code_generate", agent_id="coder", ...),
    AuditEntry(action="gate_check", agent_id="validator", ...),
])

# Traceloop 格式导出
exporter = TraceloopExporter()
traceloop_spans = exporter.export(entries, format="traceloop")

print(f"OTel Span 数: {len(spans)}")
print(f"Traceloop Span 数: {len(traceloop_spans)}")
```

### 预期输出

| 格式 | 说明 |
|------|------|
| OTel JSON | 标准 OpenTelemetry Span 格式 |
| Traceloop | Traceloop 扩展属性映射格式 |

---

## 三大平台对比

| 后端 | 定位 | 适用场景 | 降级 |
|------|------|---------|------|
| Langfuse | LLM 可观测 | Prompt/模型调试、token追踪 | → 本地 JSON |
| Arize | ML 可观测 | 模型评估、漂移检测 | → 本地 JSON |
| Datadog | 企业监控 | 全栈可观测、告警联动 | → 本地 JSON |
| MultiStore | 双写保障 | 生产级多后端冗余 | → 本地 + 自动回填 |
| OTel/Traceloop | 标准导出 | 跨平台审计数据共享 | → 本地 JSON |

---

## 相关导航

- 📖 原理 → [审计层](/guide/audit-layer) · [引擎总线](/guide/engine-bus)
- 🏃 跑代码 → [examples/audit-backends/](../../examples/audit-backends/)
- 🎓 方法 → [审计使用](/tutorial/audit-usage)

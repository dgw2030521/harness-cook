# 审计后端示例

> Langfuse/Arize/Datadog 外部存储集成、MultiAuditStore 双写降级、Traceloop/OTel 标准导出

**文档介绍**见 VitePress Demo 页面 [审计后端](../../playground/docs/demo/audit-backends.md)——代码片段 + 预期输出 + 配置说明。本目录是可运行的脚本。

## 运行

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/audit-backends/demo_audit_backends.py
```

## 输出内容

| Demo | 说明 |
|------|------|
| 1. Langfuse 审计后端 | AuditEntry → Langfuse trace + spans，SDK 不可用时 fallback 降级 |
| 2. Arize 审计后端 | AuditEntry → Arize Phoenix trace + compliance annotations，SDK 不可用时 fallback |
| 3. Datadog 审计后端 | AuditEntry → Datadog APM span + 子 spans，基础设施 + Agent 动作全栈 trace |
| 4. MultiAuditStore 双写 | 主存储写入 + 次存储火忘式写入，次存储失败 → AUDIT_SECONDARY_FAIL 事件（不阻塞） |
| 5. Traceloop/OTel 导出 | AuditEntry → OTel Span 字典 + Traceloop 属性映射，无外部依赖即可导出 |
| 补充. Protocol 一致性 | IAuditStore Protocol 鸭子类型验证，所有后端均满足统一契约 |

## 适用场景

- AI Agent 执行的可观测性——将审计记录同时推送到 LLM 可观测平台（Langfuse）和监控平台（Datadog）
- 合规审计——Arize Phoenix 的 compliance annotation 标注风险等级
- 多后端冗余写入——MultiAuditStore 火忘式双写，确保至少写入主存储
- OTel 标准导出——Traceloop/OTel 属性映射，对接 OTel Collector

## SDK 安装（可选）

外部后端需要安装对应 SDK 才能真正写入。无 SDK 时演示 fallback 机制（惰性探测 + 降级提示）。

```bash
# Langfuse（LLM 可观测性）
pip install harness-cook[langfuse]

# Arize（ML 可观测性）
pip install harness-cook[arize]

# Datadog（企业监控）
pip install harness-cook[datadog]

# Traceloop + OpenTelemetry（标准导出）
pip install harness-cook[integrations]
pip install opentelemetry-api opentelemetry-sdk
```

## Fallback 机制说明

所有外部后端均实现 IAuditStore Protocol，核心设计：

| 方法 | 外部后端行为 | 说明 |
|------|-------------|------|
| `save()` | SDK 可用 → 写入；不可用 → RuntimeError | MultiAuditStore 捕获次存储异常，不阻塞 |
| `load()` | 返回空列表 | 外部 SDK 无按 session 加载 API，读取使用主存储 |
| `search()` | 返回空列表 + warning | 外部 SDK 无搜索 API |
| `verify_chain()` | 返回 `{valid: True}` | 外部存储不维护哈希链，验证使用主存储 |
| `integrity_report()` | 简化报告 | recommendation: 使用主 AuditStore 做完整性验证 |

次存储失败时 MultiAuditStore 发送 `AUDIT_SECONDARY_FAIL` 事件，可观测但不阻塞核心审计功能。

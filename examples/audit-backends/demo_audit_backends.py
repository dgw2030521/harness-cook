"""
审计后端 Demo 示例

演示 harness-cook 外部审计存储后端的 API 调用方式和 fallback 机制：
  1. Langfuse 审计后端——LLM 可观测性平台集成
  2. Arize 审计后端——ML 可观测性平台集成
  3. Datadog 审计后端——企业监控平台集成
  4. MultiAuditStore 双写——多后端同时写入 + 故障降级
  5. Traceloop/OTel 导出——OpenTelemetry 标准格式导出

运行方式:
  cd packages/core
  PYTHONPATH=. python3 ../../examples/audit-backends/demo_audit_backends.py

注意:
  - Langfuse/Arize/Datadog/Traceloop 需安装对应 SDK 才能真正写入
  - 无 SDK 时演示 fallback 机制（惰性探测 + 降级提示）
  - MultiAuditStore 双写需要主存储（AuditStore）可用
"""

from datetime import datetime, timezone
from harness.types import AuditEntry


# ─── 构造测试 AuditEntry ────────────────────────────────────

def make_audit_entry(
    session_id: str = "demo-session-001",
    agent_id: str = "claude-code",
    task: str = "审计后端演示任务",
) -> AuditEntry:
    """构造标准测试 AuditEntry"""
    return AuditEntry(
        timestamp=datetime.now(timezone.utc),
        session_id=session_id,
        agent_id=agent_id,
        task=task,
        decisions=[
            {
                "reasoning": "代码质量检查通过",
                "action": "approve",
                "confidence": 0.92,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            {
                "reasoning": "安全扫描无硬编码密钥",
                "action": "approve",
                "confidence": 0.95,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        ],
        actions=[
            {
                "tool": "code_review",
                "input_summary": "检查 PR #42 代码质量",
                "output_summary": "通过——无硬编码密钥、无注入风险",
                "duration_ms": 3200,
            },
            {
                "tool": "security_scan",
                "input_summary": "扫描敏感信息",
                "output_summary": "通过——0 个 PII 泄露",
                "duration_ms": 1500,
            },
        ],
        outcomes={
            "status": "completed",
            "auto_fixed": False,
            "escalated": False,
            "rules_checked": 3,
            "rules_passed": 3,
            "rules_failed": 0,
        },
        risk_assessment={
            "overall": "low",
            "security": "low",
            "privacy": "low",
            "compliance": "low",
        },
        escalation_history=[],
        chain_hash=None,
    )


# ═══════════════════════════════════════════════════════════════
#  Demo 1: Langfuse 审计后端——LLM 可观测性平台集成
# ═══════════════════════════════════════════════════════════════

def demo_langfuse():
    """Demo 1: Langfuse 审计后端——LLM 可观测性平台集成"""
    print("\n" + "=" * 60)
    print("Demo 1: Langfuse 审计后端——LLM 可观测性平台集成")
    print("=" * 60)

    from harness.integrations.langfuse_store import LangfuseAuditStore

    # 创建 LangfuseAuditStore（无密钥→演示 fallback）
    store = LangfuseAuditStore(
        public_key=None,
        secret_key=None,
        host="https://cloud.langfuse.com",
    )

    entry = make_audit_entry(session_id="langfuse-session-001")

    # ─── 惰性探测 ───
    print("\n  [1] 惰性 SDK 探测")
    available = store._is_available()
    print(f"      langfuse SDK 可用: {available}")
    if not available:
        print("      → LangfuseAuditStore 进入降级模式")
        print("      → 安装方式: pip install harness-cook[langfuse]")

    # ─── save() ───
    print("\n  [2] save() —— AuditEntry → Langfuse trace + spans")
    if available:
        trace_id = store.save(entry)
        print(f"      trace_id: {trace_id}")
        print("      每个 AuditEntry → 一个 Langfuse trace")
        print("      每个 decision → trace 内的 span (name=decision-N)")
        print("      每个 action → trace 内的 span (name=action-N)")
        print("      每个 outcome → trace 内的 span (name=outcome-N)")
        print("      risk_assessment → trace 的 metadata 标注")
        print("      chain_hash → trace 的 tags")
    else:
        try:
            store.save(entry)
        except RuntimeError as e:
            print(f"      RuntimeError: {e}")
            print("      → SDK 不可用时 save() 抛出 RuntimeError")
            print("      → 这是设计行为：次存储失败由 MultiAuditStore 捕获")
        # 模拟有 SDK 时的预期输出
        print("\n      预期输出（有 SDK 时）:")
        print("      trace_id = entry.session_id = 'langfuse-session-001'")
        print("      Langfuse Dashboard 可见:")
        print("        trace: harness.audit.claude-code")
        print("        span:  decision-0 → {reasoning: '代码质量检查通过', ...}")
        print("        span:  decision-1 → {reasoning: '安全扫描无硬编码密钥', ...}")
        print("        span:  action-0   → {tool: 'code_review', ...}")
        print("        span:  action-1   → {tool: 'security_scan', ...}")
        print("        span:  outcome-0  → {status: 'completed', ...}")
        print("        tags: ['harness-audit', 'claude-code']")

    # ─── load() / search() ───
    print("\n  [3] load() / search() —— Langfuse SDK 无数据检索 API")
    loaded = store.load("langfuse-session-001")
    print(f"      load('langfuse-session-001'): {loaded}")
    print("      → 返回空列表（Langfuse SDK 无按 session 加载 API）")
    print("      → 审计数据读取应使用主存储 AuditStore")

    searched = store.search("demo")
    print(f"      search('demo'): {searched}")
    print("      → 返回空列表 + warning 日志")

    # ─── verify_chain() / integrity_report() ───
    print("\n  [4] verify_chain() / integrity_report() —— 链验证降级")
    chain_result = store.verify_chain()
    print(f"      verify_chain(): {chain_result}")
    print("      → {valid: True}（Langfuse 不维护哈希链）")
    print("      → 链验证应使用主存储 AuditStore")

    report = store.integrity_report()
    print(f"      integrity_report(): {report}")
    print("      → 简化报告，recommendation: 使用主 AuditStore 做完整性验证")


# ═══════════════════════════════════════════════════════════════
#  Demo 2: Arize 审计后端——ML 可观测性平台集成
# ═══════════════════════════════════════════════════════════════

def demo_arize():
    """Demo 2: Arize 审计后端——ML 可观测性平台集成"""
    print("\n" + "=" * 60)
    print("Demo 2: Arize 审计后端——ML 可观测性平台集成")
    print("=" * 60)

    from harness.integrations.arize_store import ArizeAuditStore

    store = ArizeAuditStore(
        api_key=None,
        space_id=None,
        space_key=None,
    )

    entry = make_audit_entry(session_id="arize-session-001")

    # ─── 惰性探测 ───
    print("\n  [1] 惰性 SDK 探测")
    available = store._is_available()
    print(f"      arize SDK 可用: {available}")
    if not available:
        print("      → ArizeAuditStore 进入降级模式")
        print("      → 安装方式: pip install harness-cook[arize]")

    # ─── save() ───
    print("\n  [2] save() —— AuditEntry → Arize Phoenix trace + compliance annotations")
    if available:
        trace_id = store.save(entry)
        print(f"      trace_id: {trace_id}")
        print("      AuditEntry → Arize Phoenix trace (prediction_id=session_id)")
        print("      risk_assessment → compliance annotation (compliance=true)")
        print("      attributes 使用 harness.* 前缀")
    else:
        try:
            store.save(entry)
        except RuntimeError as e:
            print(f"      RuntimeError: {e}")
            print("      → SDK 不可用时 save() 抛出 RuntimeError")
        # 模拟预期输出
        print("\n      预期输出（有 SDK 时）:")
        print("      trace_id = 'arize-session-001'")
        print("      Arize Phoenix Dashboard 可见:")
        print("        model_id: harness-audit-claude-code")
        print("        prediction_id: arize-session-001")
        print("        prediction_label: audit_entry")
        print("        features: {task: '审计后端演示任务', agent_id: 'claude-code'}")
        print("        attributes:")
        print("          harness.agent_id: claude-code")
        print("          harness.chain_hash: ''")
        print("          harness.risk_assessment: {overall: 'low', ...}")
        print("        compliance annotation:")
        print("          model_id: harness-governance-claude-code")
        print("          prediction_label: compliance_annotation")
        print("          harness.compliance: true")
        print("          harness.risk_level: {overall: 'low', ...}")

    # ─── load() / search() ───
    print("\n  [3] load() / search() —— Arize SDK 无数据检索 API")
    loaded = store.load("arize-session-001")
    print(f"      load('arize-session-001'): {loaded}")
    searched = store.search("demo")
    print(f"      search('demo'): {searched}")

    # ─── verify_chain() / integrity_report() ───
    print("\n  [4] verify_chain() / integrity_report() —— 链验证降级")
    chain_result = store.verify_chain()
    print(f"      verify_chain(): {chain_result}")
    report = store.integrity_report()
    print(f"      integrity_report(): {report}")


# ═══════════════════════════════════════════════════════════════
#  Demo 3: Datadog 审计后端——企业监控平台集成
# ═══════════════════════════════════════════════════════════════

def demo_datadog():
    """Demo 3: Datadog 审计后端——企业监控平台集成"""
    print("\n" + "=" * 60)
    print("Demo 3: Datadog 审计后端——企业监控平台集成")
    print("=" * 60)

    from harness.integrations.datadog_store import DatadogAuditStore

    store = DatadogAuditStore(
        service_name="harness-cook-demo",
        env="development",
    )

    entry = make_audit_entry(session_id="datadog-session-001")

    # ─── 惰性探测 ───
    print("\n  [1] 惰性 SDK 探测")
    available = store._is_available()
    print(f"      ddtrace SDK 可用: {available}")
    if not available:
        print("      → DatadogAuditStore 进入降级模式")
        print("      → 安装方式: pip install harness-cook[datadog]")

    # ─── save() ───
    print("\n  [2] save() —— AuditEntry → Datadog APM span")
    print("      独特价值：基础设施 + Agent 动作的全栈 trace")
    if available:
        span_id = store.save(entry)
        print(f"      span_id: {span_id}")
        print("      每个 AuditEntry → Datadog APM span")
        print("      每个 decision/action/outcome → 子 span")
        print("      chain_hash → span tag")
        print("      risk_assessment → span tag + metric")
        print("      decisions/actions/outcomes 计数 → span metrics")
    else:
        try:
            store.save(entry)
        except RuntimeError as e:
            print(f"      RuntimeError: {e}")
            print("      → SDK 不可用时 save() 抛出 RuntimeError")
        # 模拟预期输出
        print("\n      预期输出（有 SDK 时）:")
        print("      span_id = str(span.span_id)")
        print("      Datadog APM Dashboard 可见:")
        print("        span: harness.audit.claude-code")
        print("          service: harness-cook-demo")
        print("          resource: 审计后端演示任务")
        print("          tags:")
        print("            harness.session_id: datadog-session-001")
        print("            harness.agent_id: claude-code")
        print("            harness.chain_hash: ''")
        print("            harness.risk_assessment: {overall: 'low', ...}")
        print("            harness.audit_type: governance_trace")
        print("          metrics:")
        print("            harness.decisions_count: 2")
        print("            harness.actions_count: 2")
        print("            harness.outcomes_count: (dict → 1)")
        print("        child spans:")
        print("          harness.decision.0 → {reasoning: '代码质量检查通过', ...}")
        print("          harness.decision.1 → {reasoning: '安全扫描无硬编码密钥', ...}")
        print("          harness.action.0 → {tool: 'code_review', ...}")
        print("          harness.action.1 → {tool: 'security_scan', ...}")
        print("          harness.outcome.0 → {status: 'completed', ...}")

    # ─── load() / search() ───
    print("\n  [3] load() / search() —— Datadog SDK 无数据检索 API")
    loaded = store.load("datadog-session-001")
    print(f"      load('datadog-session-001'): {loaded}")
    searched = store.search("demo")
    print(f"      search('demo'): {searched}")

    # ─── verify_chain() / integrity_report() ───
    print("\n  [4] verify_chain() / integrity_report() —— 链验证降级")
    chain_result = store.verify_chain()
    print(f"      verify_chain(): {chain_result}")
    report = store.integrity_report()
    print(f"      integrity_report(): {report}")


# ═══════════════════════════════════════════════════════════════
#  Demo 4: MultiAuditStore 双写——多后端同时写入 + 故障降级
# ═══════════════════════════════════════════════════════════════

def demo_multi_store():
    """Demo 4: MultiAuditStore 双写——多后端同时写入 + 故障降级"""
    print("\n" + "=" * 60)
    print("Demo 4: MultiAuditStore 双写——多后端同时写入 + 故障降级")
    print("=" * 60)

    from harness.audit import AuditStore
    from harness.integrations.multi_store import MultiAuditStore
    from harness.integrations.langfuse_store import LangfuseAuditStore
    from harness.integrations.arize_store import ArizeAuditStore

    # ─── 主存储 + 次存储 ───
    print("\n  [1] 创建 MultiAuditStore（主存储 + 2 个次存储）")
    print("      stores[0] = AuditStore（本地 JSON，必须成功）")
    print("      stores[1] = LangfuseAuditStore（火忘式写入）")
    print("      stores[2] = ArizeAuditStore（火忘式写入）")

    primary = AuditStore(store_dir="/tmp/harness-audit-backends-demo")
    langfuse_secondary = LangfuseAuditStore()
    arize_secondary = ArizeAuditStore()

    multi = MultiAuditStore(
        stores=[primary, langfuse_secondary, arize_secondary],
    )

    print(f"      primary: {type(multi.primary).__name__}")
    print(f"      secondary: {[type(s).__name__ for s in multi.secondary_stores]}")

    # ─── save() 双写 ───
    print("\n  [2] save() —— 主存储写入 + 次存储写入（火忘式）")
    entry = make_audit_entry(session_id="multi-session-001")

    result = multi.save(entry)
    print(f"      主存储写入结果: {result}")
    print("      次存储写入:")
    print("        Langfuse → RuntimeError（SDK 不可用）→ 不阻塞")
    print("        Arize   → RuntimeError（SDK 不可用）→ 不阻塞")
    print("      → MultiAuditStore 捕获次存储异常，发送 AUDIT_SECONDARY_FAIL 事件")

    # ─── 故障降级演示 ───
    print("\n  [3] 故障降级机制")
    print("      主存储失败 → 抛异常（不尝试次存储）")
    print("      次存储失败 → warning 日志 + AUDIT_SECONDARY_FAIL 事件（不阻塞）")
    print("      → 确保审计记录至少写入主存储（本地 JSON 哈希链）")
    print("      → 次存储失败可观测但不妨碍核心审计功能")

    # ─── load/search/verify 从主存储 ───
    print("\n  [4] load/search/verify_chain/integrity_report → 仅从主存储")
    loaded = multi.load("multi-session-001")
    print(f"      load: 找到 {len(loaded)} 条记录（来自主存储 AuditStore）")
    print(f"      chain_head: {multi.chain_head}")

    chain_result = multi.verify_chain()
    print(f"      verify_chain(): valid={chain_result['valid']}, "
          f"total={chain_result['total_records']}")

    report = multi.integrity_report()
    print(f"      integrity_report(): status={report.get('status')}, "
          f"total={report.get('total_records')}")

    # ─── 连续双写 + 降级不阻塞 ───
    print("\n  [5] 连续双写——次存储故障不阻塞主存储")
    for i in range(3):
        entry = make_audit_entry(
            session_id=f"multi-session-{i+2:03d}",
            task=f"连续写入测试-{i}",
        )
        result = multi.save(entry)
        print(f"      写入 {i}: result={result}, chain_head={multi.chain_head}")
    print("      → 即使次存储全部失败，主存储的哈希链仍然正常推进")


# ═══════════════════════════════════════════════════════════════
#  Demo 5: Traceloop/OTel 导出——OpenTelemetry 标准格式导出
# ═══════════════════════════════════════════════════════════════

def demo_traceloop_otel():
    """Demo 5: Traceloop/OTel 导出——OpenTelemetry 标准格式导出"""
    print("\n" + "=" * 60)
    print("Demo 5: Traceloop/OTel 导出——OpenTelemetry 标准格式导出")
    print("=" * 60)

    from harness.otel_integration import OTelBridge, _audit_entry_to_span_dict
    from harness.integrations.traceloop_exporter import TraceloopExporter, TRACELOOP_ATTR_MAP

    entry = make_audit_entry(session_id="otel-session-001")

    # ─── OTelBridge 基础导出 ───
    print("\n  [1] OTelBridge —— AuditEntry → OTel Span 字典")
    print("      无需安装 opentelemetry SDK 也可导出 Span 字典")
    print("      _audit_entry_to_span_dict() 是纯 Python 函数，无外部依赖")

    span_dict = _audit_entry_to_span_dict(entry)
    print(f"      span name: {span_dict['name']}")
    print(f"      span status: {span_dict['status']}")
    print(f"      span kind: {span_dict['kind']}")
    print("      attributes:")
    for k, v in span_dict["attributes"].items():
        print(f"        {k}: {v}")

    # ─── OTelBridge 完整实例 ───
    print("\n  [2] OTelBridge 完整实例")
    bridge = OTelBridge(service_name="harness-cook-demo")

    # 检查是否有 opentelemetry SDK
    from harness.otel_integration import HAS_OTEL
    print(f"      opentelemetry SDK 可用: {HAS_OTEL}")

    exported = bridge.export_audit_entry(entry)
    print(f"      export_audit_entry() → Span 字典:")
    print(f"        name: {exported['name']}")
    print(f"        status: {exported['status']}")
    print(f"        attributes: {list(exported['attributes'].keys())}")
    if not HAS_OTEL:
        print("      → 无 opentelemetry SDK 时，仅返回字典（不创建真实 Span）")
        print("      → 安装方式: pip install opentelemetry-api opentelemetry-sdk")

    # ─── Traceloop 属性映射 ───
    print("\n  [3] Traceloop 属性命名映射")
    print("      harness.* → traceloop.* 属性映射:")
    for harness_attr, traceloop_attr in TRACELOOP_ATTR_MAP.items():
        print(f"        {harness_attr} → {traceloop_attr}")
    print("      → 合并两种属性命名（兼容 OTel Collector + Traceloop Dashboard）")

    # ─── TraceloopExporter 导出 ───
    print("\n  [4] TraceloopExporter —— 合并 harness + traceloop 属性")
    exporter = TraceloopExporter(otel_bridge=bridge)

    traceloop_span = exporter.export_audit_entry(entry)
    print(f"      traceloop_compatible: {traceloop_span.get('traceloop_compatible')}")
    print("      合并后的 attributes:")
    for k, v in traceloop_span["attributes"].items():
        print(f"        {k}: {v}")

    # ─── Traceloop SDK 可用性 ───
    print("\n  [5] Traceloop SDK 可用性")
    available = exporter._is_traceloop_available()
    print(f"      traceloop SDK 可用: {available}")
    if not available:
        print("      → 无 traceloop SDK 时，仅做属性映射导出（纯 Python）")
        print("      → 不影响核心导出功能——OTel Span 字典始终可用")
        print("      → 安装方式: pip install harness-cook[integrations]")

    # ─── OTel 指标说明 ───
    print("\n  [6] OTel 指标（opentelemetry SDK 可用时自动采集）")
    print("      harness.workflow.duration      — Histogram — 工作流执行时间(ms)")
    print("      harness.workflow.node.duration  — Histogram — 节点执行时间(ms)")
    print("      harness.workflow.node.count     — Counter  — 节点执行次数")
    print("      harness.workflow.node.error     — Counter  — 节点错误次数")
    print("      harness.gate.check.count        — Counter  — 门禁检查次数")
    print("      harness.gate.check.passed       — Counter  — 门禁通过次数")
    print("      harness.gate.check.failed       — Counter  — 门禁失败次数")
    print("      harness.agent.tokens.used       — Counter  — Agent 消耗 token 数")


# ═══════════════════════════════════════════════════════════════
#  IAuditStore Protocol 一致性验证
# ═══════════════════════════════════════════════════════════════

def demo_protocol_consistency():
    """补充演示: IAuditStore Protocol 一致性验证"""
    print("\n" + "=" * 60)
    print("补充: IAuditStore Protocol 一致性验证")
    print("=" * 60)

    from harness.integrations.audit_store_protocol import IAuditStore
    from harness.audit import AuditStore
    from harness.integrations.langfuse_store import LangfuseAuditStore
    from harness.integrations.arize_store import ArizeAuditStore
    from harness.integrations.datadog_store import DatadogAuditStore
    from harness.integrations.multi_store import MultiAuditStore

    stores = {
        "AuditStore": AuditStore(store_dir="/tmp/harness-protocol-demo"),
        "LangfuseAuditStore": LangfuseAuditStore(),
        "ArizeAuditStore": ArizeAuditStore(),
        "DatadogAuditStore": DatadogAuditStore(),
        "MultiAuditStore": MultiAuditStore(
            stores=[AuditStore(store_dir="/tmp/harness-protocol-demo")]
        ),
    }

    print("\n  各存储后端是否满足 IAuditStore Protocol:")
    for name, store in stores.items():
        # runtime_checkable Protocol 支持 isinstance 检查
        is_compliant = isinstance(store, IAuditStore)
        methods = ["save", "load", "search", "verify_chain", "integrity_report"]
        has_all = all(hasattr(store, m) for m in methods)
        print(f"      {name}: isinstance={is_compliant}, 方法齐全={has_all}")

    print("\n  Protocol 是鸭子类型契约——不需要继承")
    print("  新的外部存储只需实现 save/load/search/verify_chain/integrity_report 即可接入")


# ═══════════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("Harness Audit Backends Demo")
    print("审计后端——外部存储集成 + fallback 机制 + OTel 导出")
    print("=" * 60)

    demo_langfuse()
    demo_arize()
    demo_datadog()
    demo_multi_store()
    demo_traceloop_otel()
    demo_protocol_consistency()

    print("\n" + "=" * 60)
    print("所有审计后端 Demo 完成")
    print("=" * 60)

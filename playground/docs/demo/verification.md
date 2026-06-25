# 全面验证指南 Demo

> 所有 harness-cook 能力的可运行验证脚本——复制执行即可确认每项能力是否正常工作。

## 前置

```bash
cd harness-cook/packages/core
export PYTHONPATH=.
```

---

## 一、引擎集成总线验证

### 1.1 MatcherRegistry 12 引擎注册

```python
from harness.rule_checker import MatcherRegistry

MatcherRegistry.default()
print(f"注册引擎数: {len(MatcherRegistry._matchers)}")
for k in sorted(MatcherRegistry._matchers.keys()):
    print(f"  {k}: {MatcherRegistry._matchers[k].__class__.__name__}")
```

**预期**：注册引擎数 = 12

### 1.2 ExternalEngineChecker 降级路径

```python
from harness.integrations.guardrails_ai_checker import GuardrailsAIChecker

checker = GuardrailsAIChecker()
available = checker._is_engine_available()
print(f"Guardrails AI 可用: {available}")  # False（SDK 未安装）
```

### 1.3 IAuditStore Protocol 兼容性

```python
from harness.integrations.audit_store_protocol import IAuditStore
from harness.audit import AuditStore
from harness.integrations.multi_store import MultiAuditStore

local_store = AuditStore()
print(f"AuditStore 满足 IAuditStore: {isinstance(local_store, IAuditStore)}")

multi = MultiAuditStore([local_store])
print(f"MultiAuditStore 满足 IAuditStore: {isinstance(multi, IAuditStore)}")
```

---

## 二、护栏层验证

### 2.1 内置 PII 检测

```python
from harness.guardrails import GuardrailsPair
from harness.types import InputGuardrailConfig, OutputGuardrailConfig, GuardrailAction

pair = GuardrailsPair(
    input_config=InputGuardrailConfig(
        detect_pii_types=["email", "phone_cn", "id_card_cn"],
        pii_action=GuardrailAction.REDACT,
    ),
    output_config=OutputGuardrailConfig(
        detect_pii_in_output=True,
        output_pii_action=GuardrailAction.REDACT,
    ),
)

result = pair.check_input("用户张三的手机号13812345678，身份证410105199001011234")
print(f"违规: {result.violations}")
print(f"红脱: {result.redactions}")
print(f"处理后: {result.processed_content}")
```

### 2.2 4 个外部护栏适配器导入

```python
from harness.integrations.guardrails_ai_checker import GuardrailsAIChecker
from harness.integrations.nemo_guardrails_checker import NeMoGuardrailsChecker
from harness.integrations.llama_guard_checker import LlamaGuardChecker
from harness.integrations.helicone_checker import HeliconeMiddlewareChecker

for cls in [GuardrailsAIChecker, NeMoGuardrailsChecker, LlamaGuardChecker, HeliconeMiddlewareChecker]:
    checker = cls()
    print(f"{cls.__name__}: 可用={checker._is_engine_available()}, fallback={checker._fallback_checker.__class__.__name__}")
```

---

## 三、合规层验证

### 3.1 ComplianceEngine 基础扫描

```python
from harness.compliance import ComplianceEngine
from harness.rule_packs import get_security_pack

engine = ComplianceEngine()
engine.load_pack(get_security_pack())

results = engine.scan_quick('password = "hardcoded_secret_123"', "config.py")
for r in results:
    print(f"{r.rule_id}: passed={r.passed}")
```

### 3.2 语言感知路由

```python
from harness.rule_checker import MatcherRegistry
MatcherRegistry.default()
mr = MatcherRegistry()

for lang in ["java", "javascript", "typescript", "python"]:
    rec = mr.get_by_language(lang)
    print(f"{lang} → {rec.__class__.__name__ if rec else '无推荐'}")
```

### 3.3 合规引擎适配器

```python
from harness.integrations.sonarqube_checker import SonarQubeChecker
from harness.integrations.opa_checker import OPAChecker
from harness.integrations.archunit_checker import ArchUnitChecker
from harness.integrations.dep_cruiser_checker import DepCruiserChecker

for cls in [SonarQubeChecker, OPAChecker, ArchUnitChecker, DepCruiserChecker]:
    checker = cls()
    print(f"{cls.__name__}: 可用={checker._is_engine_available()}, fallback={checker._fallback_checker.__class__.__name__}")
```

---

## 四、审计层验证

### 4.1 SHA-256 链完整性

```python
from harness.audit import AuditStore, AuditEntry
from datetime import datetime

store = AuditStore()
for i in range(3):
    store.save(AuditEntry(session_id=f"v{i}", agent_id="test", action="execute",
                          decision="completed", timestamp=datetime.now(), outcomes=[]))

result = store.verify_chain()
print(f"链完整: {result['valid']}, 总记录: {result['total_records']}")
```

### 4.2 MultiAuditStore 双写

```python
from harness.audit import AuditStore, AuditEntry
from harness.integrations.multi_store import MultiAuditStore
from harness.bus import EventBus
from datetime import datetime

bus = EventBus()
primary = AuditStore()
secondary = AuditStore(store_dir="/tmp/harness-secondary")
multi = MultiAuditStore([primary, secondary], bus=bus)

entry = AuditEntry(session_id="dual", agent_id="test", action="execute",
                   decision="completed", timestamp=datetime.now(), outcomes=[])
multi.save(entry)
entries = multi.search("dual")
print(f"主存储记录数: {len(entries)}")
```

### 4.3 外部审计后端导入

```python
from harness.integrations.audit_store_protocol import IAuditStore
from harness.integrations.langfuse_store import LangfuseAuditStore
from harness.integrations.arize_store import ArizeAuditStore
from harness.integrations.datadog_store import DatadogAuditStore
from harness.integrations.helicone_store import HeliconeAuditStore

for cls, kwargs in [
    (LangfuseAuditStore, {"public_key": "pk-t", "secret_key": "sk-t", "host": "http://localhost"}),
    (ArizeAuditStore, {"api_key": "t", "space_id": "t", "model_id": "t"}),
    (DatadogAuditStore, {"api_key": "t", "site": "datadoghq.com"}),
    (HeliconeAuditStore, {"api_key": "t"}),
]:
    store = cls(**kwargs)
    print(f"{cls.__name__}: isinstance IAuditStore={isinstance(store, IAuditStore)}")
```

---

## 五、门禁层验证

### 5.1 三档模式

```python
from harness.gates import GateEngine
from harness.types import GateDefinition, GateMode, GateCheck, CheckResult, Artifact
from harness.bus import EventBus

bus = EventBus()
engine = GateEngine(bus=bus)

def fail(artifact):
    return CheckResult(passed=False, severity="medium", message="测试违规")

for mode in [GateMode.STRICT, GateMode.HYBRID, GateMode.LOOSE]:
    gate = GateDefinition(id=f"test-{mode.value}", mode=mode,
                          checks=[GateCheck(id="t", category="security", severity="medium",
                                            description="test", check_fn=fail)])
    engine.register(gate)
    result = engine.evaluate(f"test-{mode.value}", Artifact(type="code", path="t.py", content="t"))
    print(f"{mode.value}: passed={result.passed}, blocked={result.blocked}")
```

---

## 六、编排平台中间件

### 6.1 LangGraphGovernanceNode

```python
from harness.integrations.langgraph_node import LangGraphGovernanceNode
node = LangGraphGovernanceNode(bus=EventBus())
print(f"LangGraphGovernanceNode 可创建: ✅")
```

### 6.2 DeerFlowBridge

```python
from harness.integrations.deerflow_bridge import DeerFlowBridge
bridge = DeerFlowBridge()
print(f"DeerFlowBridge 可创建: ✅")
```

---

## 七、Bridge 多平台适配器

```python
from harness.bridge import ClaudeCodeAdapter, OpenAIAdapter, HermesAdapter

for cls in [ClaudeCodeAdapter, OpenAIAdapter, HermesAdapter]:
    adapter = cls()
    print(f"{cls.__name__}: ✅ 可创建")
```

---

## 八、MCP Server 工具

```python
from harness_mcp_server import HarnessMCPServer

server = HarnessMCPServer()
print(f"MCP 工具数: {len(server._TOOL_DEFINITIONS)}")
for tool in server._TOOL_DEFINITIONS:
    print(f"  {tool['name']}")
```

---

## 速查表

| # | 能力 | 默认可验证 | 需外部 SDK |
|---|------|-----------|-----------|
| 1 | MatcherRegistry 12 引擎 | ✅ | — |
| 2 | ExternalEngineChecker 降级 | ✅ | — |
| 3 | IAuditStore Protocol | ✅ | — |
| 4 | PII 检测 + 红脱/阻断 | ✅ | — |
| 5 | ComplianceEngine 扫描 | ✅ | — |
| 6 | 语言感知路由 | ✅ | — |
| 7 | SHA-256 链完整性 | ✅ | — |
| 8 | MultiAuditStore 双写 | ✅ | — |
| 9 | 外部审计后端导入 | ✅ | — |
| 10 | 三档门禁 | ✅ | — |
| 11 | LangGraphGovernanceNode | ✅ | — |
| 12 | DeerFlowBridge | ✅ | — |
| 13 | Bridge 多平台适配器 | ✅ | — |
| 14 | MCP Server 25 工具 | ✅ | — |
| 15 | 规则导入器 | ✅ | — |
| 16 | DepCruiser 端到端 | ✅ | — |
| 17 | TraceloopExporter | ✅ | — |
| 18 | 合规引擎适配器 | ✅ | — |
| 19 | GuardrailsAI 真实调用 | — | ✅ 需 `pip install guardrails-ai` |
| 20 | SonarQube 真实调用 | — | ✅ 需 SonarQube 服务 |
| 21 | Langfuse 真实写入 | — | ✅ 需 `pip install langfuse` + 服务 |

---

## 相关导航

- 📖 架构原理 → [引擎集成总线](/guide/engine-bus) · [护栏层](/guide/guardrails-layer) · [合规层](/guide/compliance-layer) · [审计层](/guide/audit-layer) · [门禁层](/guide/gate-layer)

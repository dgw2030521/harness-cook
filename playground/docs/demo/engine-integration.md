# 引擎集成 Demo

> 跑起来看看引擎集成总线的 MatcherRegistry 12 引擎注册、引擎可用性探测、DepCruiser 端到端和降级路径。

## 前置

```bash
cd harness-cook/packages/core
PYTHONPATH=. python3 -c "from harness.rule_checker import MatcherRegistry; print('✅ OK')"
```

---

## Demo 1：MatcherRegistry 12 引擎注册

**原理**：MatcherRegistry.default() 通过 try/except ImportError 注册所有引擎适配器。不装 → 不注册 → 规则回退内置 checker。

```python
from harness.rule_checker import MatcherRegistry

MatcherRegistry.default()
print(f"注册引擎数: {len(MatcherRegistry._matchers)}")
for k in sorted(MatcherRegistry._matchers.keys()):
    print(f"  {k}: {MatcherRegistry._matchers[k].__class__.__name__}")
```

### 预期输出

```
注册引擎数: 12
  archunit: ArchUnitChecker
  ast: ASTChecker
  cross_file: CrossFileChecker
  dep_cruiser: DepCruiserChecker
  dependency_graph: DependencyGraphChecker
  guardrails_ai: GuardrailsAIChecker
  helicone: HeliconeMiddlewareChecker
  llama-guard: LlamaGuardChecker
  nemo: NeMoGuardrailsChecker
  opa: OPAChecker
  regex: RegexChecker
  sonarqube: SonarQubeChecker
```

**关键观察**：
- 12 个引擎全部注册 → 说明所有适配器文件可导入
- 未安装外部 SDK 时，引擎适配器仍注册（只是 `_is_engine_available()` 返回 False）

---

## Demo 2：ExternalEngineChecker 降级路径

**原理**：模板方法模式——探测引擎可用性 → 不可用则 fallback → 翻译请求 → 调用引擎 → 翻译响应。出错 catch 回退。

```python
from harness.integrations.guardrails_ai_checker import GuardrailsAIChecker

checker = GuardrailsAIChecker()
available = checker._is_engine_available()
print(f"Guardrails AI 可用: {available}")
# 应返回 False（SDK 未安装），但 checker 本身可导入和初始化
```

### 预期输出

```
Guardrails AI 可用: False
```

**关键观察**：
- `_is_engine_available()` 缓存式惰性探测——第一次调用后才检测，后续复用缓存
- 可用性检测不阻塞初始化——适配器始终可创建
- 实际 `check()` 时自动 fallback 到 RegexChecker

---

## Demo 3：全引擎可用性探测

```python
from harness.integrations.guardrails_ai_checker import GuardrailsAIChecker
from harness.integrations.nemo_guardrails_checker import NeMoGuardrailsChecker
from harness.integrations.llama_guard_checker import LlamaGuardChecker
from harness.integrations.helicone_checker import HeliconeMiddlewareChecker
from harness.integrations.sonarqube_checker import SonarQubeChecker
from harness.integrations.opa_checker import OPAChecker
from harness.integrations.archunit_checker import ArchUnitChecker
from harness.integrations.dep_cruiser_checker import DepCruiserChecker

for cls in [GuardrailsAIChecker, NeMoGuardrailsChecker, LlamaGuardChecker,
            HeliconeMiddlewareChecker, SonarQubeChecker, OPAChecker,
            ArchUnitChecker, DepCruiserChecker]:
    checker = cls()
    print(f"{cls.__name__}: engine可用={checker._is_engine_available()}, fallback={checker._fallback_checker.__class__.__name__}")
```

### 预期输出（macOS 环境）

```
GuardrailsAIChecker: engine可用=False, fallback=RegexChecker
NeMoGuardrailsChecker: engine可用=False, fallback=RegexChecker
LlamaGuardChecker: engine可用=False, fallback=RegexChecker
HeliconeMiddlewareChecker: engine可用=False, fallback=RegexChecker
SonarQubeChecker: engine可用=False, fallback=RegexChecker
OPAChecker: engine可用=False, fallback=RegexChecker
ArchUnitChecker: engine可用=False, fallback=DependencyGraphChecker
DepCruiserChecker: engine可用=True, fallback=DependencyGraphChecker
```

**注意**：DepCruiserChecker 可用是因为本机安装了 npx + dependency-cruiser。

---

## Demo 4：DepCruiser 端到端扫描

```python
from harness.integrations.dep_cruiser_checker import DepCruiserChecker
from harness.types import ComplianceRule, ComplianceCategory, Artifact

# DepCruiserChecker 可用时，可以端到端扫描
checker = DepCruiserChecker()

if checker._is_engine_available():
    rule = ComplianceRule(
        id="DEP-001",
        category=ComplianceCategory.ARCHITECTURE,
        pattern="no-cycle",
        severity="high",
        description="禁止循环依赖",
        matcher_type="dep_cruiser",
    )

    artifact = Artifact(type="code", path="packages/core/harness/__init__.py", content="")
    result = checker.check(rule, artifact)
    print(f"DepCruiser 端到端: {result.passed}, findings={result.findings}")
else:
    print("DepCruiser 不可用，fallback 到 DependencyGraphChecker")
```

---

## Demo 5：IAuditStore Protocol 兼容性

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

## Demo 6：语言感知路由

```python
from harness.rule_checker import MatcherRegistry

MatcherRegistry.default()
mr = MatcherRegistry()

for lang in ["java", "javascript", "typescript", "python"]:
    rec = mr.get_by_language(lang)
    print(f"{lang} → {rec.__class__.__name__ if rec else '无推荐'}")
```

### 预期输出

| 语言 | 推荐引擎 | 推荐不可用时 |
|------|---------|-------------|
| Java | ArchUnitChecker | 回退到规则指定的 matcher_type |
| JavaScript | DepCruiserChecker | 回退到 DependencyGraphChecker |
| TypeScript | DepCruiserChecker | 回退到 DependencyGraphChecker |
| Python | 无特定推荐 | 使用规则指定的 matcher_type |

---

## 相关导航

- 📖 架构原理 → [引擎集成总线](/guide/engine-bus)
- 🎓 使用方法 → [合规扫描](/tutorial/compliance-scan)

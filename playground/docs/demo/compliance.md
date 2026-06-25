# 合规 Demo

> 跑起来看看合规层的规则包扫描、自定义规则、MatcherRegistry 路由和引擎适配器。

## 前置

```bash
cd harness-cook/packages/core
PYTHONPATH=. python3 -c "from harness.compliance import ComplianceEngine; print('✅ OK')"
```

---

## Demo 1：内置规则包扫描

```python
from harness.compliance import ComplianceEngine
from harness.rule_packs import get_security_pack

engine = ComplianceEngine()
engine.load_pack(get_security_pack())

# 快速扫描——检测硬编码密钥
results = engine.scan_quick('password = "hardcoded_secret_123"', "config.py")
for r in results:
    print(f"规则 {r.rule_id}: 通过={r.passed}")
    if not r.passed:
        print(f"  发现: {r.findings}")
```

### 预期输出

| 观察项 | 期望值 |
|--------|--------|
| `r.passed` | `False`（至少一条规则违规） |
| `r.rule_id` | `"SEC-001"` 或类似安全规则 ID |
| `r.findings` | 非空列表，包含违规位置信息 |

---

## Demo 2：自定义规则

```python
from harness.compliance import ComplianceEngine, RulePack
from harness.types import ComplianceRule, ComplianceCategory

engine = ComplianceEngine()
pack = RulePack("test", ComplianceCategory.SECURITY, [
    ComplianceRule(
        id="TEST-001", category=ComplianceCategory.SECURITY,
        pattern=r'eval\s*\(', severity="critical",
        description="禁止 eval()", matcher_type="regex",
    ),
])
engine.load_pack(pack)

results = engine.scan_quick('result = eval("1+2")', "test.py")
# TEST-001 应检测到 eval() → passed=False
for r in results:
    print(f"{r.rule_id}: passed={r.passed}")
```

---

## Demo 3：MatcherRegistry 路由

```python
from harness.rule_checker import MatcherRegistry

MatcherRegistry.default()
mr = MatcherRegistry()

# 查询所有已注册引擎
print(f"引擎数: {len(mr._matchers)}")
for k, v in sorted(mr._matchers.items()):
    print(f"  {k}: {v.__class__.__name__}")

# 语言感知路由
for lang in ["java", "javascript", "typescript", "python"]:
    rec = mr.get_by_language(lang)
    print(f"{lang} → {rec.__class__.__name__ if rec else '无推荐'}")
```

### 预期输出

```
引擎数: 12
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

语言路由：

| 语言 | 推荐引擎 | 推荐不可用时 |
|------|---------|-------------|
| Java | ArchUnitChecker | 回退到规则指定的 matcher_type |
| JavaScript | DepCruiserChecker | 回退到 DependencyGraphChecker |
| TypeScript | DepCruiserChecker | 回退到 DependencyGraphChecker |
| Python | 无特定推荐 | 使用规则指定的 matcher_type |

---

## Demo 4：合规引擎适配器

```python
from harness.integrations.sonarqube_checker import SonarQubeChecker
from harness.integrations.opa_checker import OPAChecker
from harness.integrations.archunit_checker import ArchUnitChecker
from harness.integrations.dep_cruiser_checker import DepCruiserChecker

for cls, fallback_expected in [
    (SonarQubeChecker, "RegexChecker"),
    (OPAChecker, "RegexChecker"),
    (ArchUnitChecker, "DependencyGraphChecker"),
    (DepCruiserChecker, "DependencyGraphChecker"),
]:
    checker = cls()
    fb = checker._fallback_checker.__class__.__name__
    print(f"{cls.__name__}: 可用={checker._is_engine_available()}, fallback={fb}")
```

### 预期输出

| 引擎 | 可用性检测 | fallback |
|------|-----------|---------|
| SonarQubeChecker | `False`（无 SonarQube 服务器） | `RegexChecker` |
| OPAChecker | `False` | `RegexChecker` |
| ArchUnitChecker | `False`（无 JVM） | `DependencyGraphChecker` |
| DepCruiserChecker | `True`（npx + dep-cruiser 可用） | `DependencyGraphChecker` |

---

## Demo 5：规则导入器

```python
from harness.integrations.rule_importer import (
    SonarQubeRuleImporter, OPARuleImporter,
    ArchUnitRuleImporter, DepCruiserRuleImporter,
)

# 导入器可创建（不需要外部引擎可用）
sq_importer = SonarQubeRuleImporter(sonarqube_url="http://localhost:9000", token="test")
opa_importer = OPARuleImporter(opa_url="http://localhost:8181")
arch_importer = ArchUnitRuleImporter()
dep_importer = DepCruiserRuleImporter(config_file=".dependency-cruiser.js")

for name, imp in [
    ("SonarQube", sq_importer), ("OPA", opa_importer),
    ("ArchUnit", arch_importer), ("DepCruiser", dep_importer),
]:
    print(f"{name}RuleImporter: ✅ 可创建")
```

---

## Demo 6：MCP 工具调用

```python
from harness_mcp_server import HarnessMCPServer

server = HarnessMCPServer()

# harness_check 工具支持 engine + language_routing 参数
tool = next(t for t in server._TOOL_DEFINITIONS if t['name'] == 'harness_check')
params = list(tool['inputSchema']['properties'].keys())
print(f"harness_check 参数: {params}")
# 应包含: path, pack_names, severity, fix, engine, language_routing

# harness_rule_import 工具
tool2 = next(t for t in server._TOOL_DEFINITIONS if t['name'] == 'harness_rule_import')
params2 = list(tool2['inputSchema']['properties'].keys())
print(f"harness_rule_import 参数: {params2}")
# 应包含: source, project_key, config
```

---

## Profile YAML 配置示例

Profile YAML 段定义见 [合规层原理](/guide/compliance-layer#profile-yaml-配置)（`compliance.engines` / `language_routing` / `packs` 等），Demo 中的可运行脚本即对应该配置的规则包扫描、MatcherRegistry 路由与引擎适配器。

---

## 相关导航

- 📖 架构原理 → [合规层](/guide/compliance-layer)
- 🎓 使用方法 → [合规扫描](/tutorial/compliance-scan)

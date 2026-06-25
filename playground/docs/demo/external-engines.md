# 外部引擎集成 Demo

> SonarQube + ArchUnit + DepCruiser + OPA + 规则导入器——五大外部合规引擎的接入与降级

**定位**：harness-cook 的引擎集成总线支持接入业界主流合规引擎，通过 MatcherRegistry 自动路由、降级回退，实现「不装不影响，装了自动增强」。

完整可运行脚本见项目 `examples/external-engines/` 目录（`demo_external_engines.py`）。

---

## Demo 1：SonarQube 引擎集成

```python
from harness.integrations.sonarqube_checker import SonarQubeChecker, SonarQubeConfig

config = SonarQubeConfig(
    url="http://localhost:9000",
    token="your-token",
    project_key="my-project",
)

checker = SonarQubeChecker(config)
result = checker.check("src/main.py")

print(f"违规数: {len(result.violations)}")
for v in result.violations:
    print(f"  [{v.severity}] {v.rule}: {v.message}")
```

### 预期输出

| 观察项 | 期望值 |
|--------|--------|
| `result.violations` | SonarQube 规则违规列表 |
| `v.severity` | BLOCKER / CRITICAL / MAJOR / MINOR / INFO |
| `v.rule` | SonarQube 规则 ID（如 `python:S1172`） |

**降级机制**：SonarQube 不可用时自动降级到 builtin 引擎，不影响合规检查流程。

---

## Demo 2：ArchUnit 架构规则检查

```python
from harness.integrations.archunit_checker import ArchUnitChecker, ArchUnitConfig

config = ArchUnitConfig(
    project_root="/path/to/java/project",
    rules=["no_cycle_in_packages", "no_public_field"],
)

checker = ArchUnitChecker(config)
result = checker.check("src/main/java/")

print(f"架构违规: {len(result.violations)}")
for v in result.violations:
    print(f"  {v.type}: {v.description}")
```

### 预期输出

| 观察项 | 期望值 |
|--------|--------|
| `result.violations` | 架构规则违规（包循环、公共字段暴露等） |
| 降级 | ArchUnit 未安装 → builtin 架构规则自动接管 |

---

## Demo 3：DepCruiser 依赖约束检查

```python
from harness.integrations.dep_cruiser_checker import DepCruiserChecker, DepCruiserConfig

config = DepCruiserConfig(
    project_root="/path/to/js/project",
    rules_file=".dependency-cruiser.js",
)

checker = DepCruiserChecker(config)
result = checker.check("src/")

print(f"依赖违规: {len(result.violations)}")
for v in result.violations:
    print(f"  {v.from} → {v.to}: {v.rule_name}")
```

### 预期输出

| 观察项 | 期望值 |
|--------|--------|
| `result.violations` | 依赖关系违规（循环依赖、越层访问等） |
| 降级 | DepCruiser 未安装 → builtin 依赖规则自动接管 |

---

## Demo 4：OPA 策略引擎检查

```python
from harness.integrations.opa_checker import OPAChecker, OPAConfig

config = OPAConfig(
    opa_url="http://localhost:8181",
    policy_file="policies/compliance.rego",
    data_file="policies/data.json",
)

checker = OPAChecker(config)
result = checker.check("src/main.py")

print(f"OPA 评估结果: {result.decision}")
print(f"违规项: {result.violations}")
```

### 预期输出

| 观察项 | 期望值 |
|--------|--------|
| `result.decision` | `allow` / `deny`（OPA 策略决策） |
| `result.violations` | 策略违规详情 |
| 降级 | OPA 服务不可用 → builtin 策略规则自动接管 |

---

## Demo 5：规则导入器

```python
from harness.integrations.rule_importer import RuleImporter

# 从 SonarQube 导入规则包
importer = RuleImporter()
rule_pack = importer.import_rules(
    source="sonarqube",
    config={"url": "http://localhost:9000", "token": "..."},
    languages=["python", "java"],
)

print(f"导入规则数: {len(rule_pack.rules)}")
print(f"规则包名称: {rule_pack.name}")

# 从 ArchUnit / DepCruiser 导入
arch_pack = importer.import_rules(source="archunit", config={"project_root": "."})
dep_pack = importer.import_rules(source="dep_cruiser", config={"project_root": "."})
```

### 预期输出

| 来源 | 导入内容 |
|------|---------|
| SonarQube | Python/Java 代码质量规则包 |
| ArchUnit | Java 架构约束规则包 |
| DepCruiser | JS/TS 依赖约束规则包 |

---

## 降级与替换机制

| 外部引擎 | 降级引擎 | 降级条件 |
|---------|---------|---------|
| SonarQube | builtin (coding/security) | SonarQube 服务不可用或 token 无效 |
| ArchUnit | builtin (archunit 仿真) | ArchUnit 未安装或规则文件缺失 |
| DepCruiser | builtin (dep_cruiser 仿真) | DepCruiser 未安装或配置缺失 |
| OPA | builtin (策略规则) | OPA 服务不可用或 Rego 文件缺失 |

**核心设计**：「不装不影响，装了自动增强」——外部引擎不可用时自动降级到 builtin，永远不阻塞合规流程。

---

## MatcherRegistry 路由示例

```python
from harness.compliance import ComplianceEngine, MatcherRegistry

registry = MatcherRegistry()
registry.register("sonarqube", SonarQubeChecker, config)
registry.register("builtin", BuiltinChecker, builtin_config)

engine = ComplianceEngine(registry=registry)
# 自动路由: 有 SonarQube → 用 SonarQube; 无 → 用 builtin
result = engine.check("src/main.py", pack_names=["coding"])
```

---

## 相关导航

- 📖 原理 → [引擎集成总线](/guide/engine-bus) · [规则包](/guide/rule-packs)
- 🏃 跑代码 → [examples/external-engines/](../../examples/external-engines/)
- 🎓 方法 → [合规扫描](/tutorial/compliance-scan) · [引擎集成](/demo/engine-integration)

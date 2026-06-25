# 合规层

> Agent 安全的第二道防线——在代码/文本产出后，检查是否违反安全、隐私、许可证、架构等规则。

**快速导航**：[📖 原理（本页）](#原理) · [🎓 使用方法](/tutorial/compliance-scan) · [🏃 可运行 Demo](/demo/compliance)

---

## 原理

### ComplianceEngine 架构

ComplianceEngine 是合规扫描的核心引擎，采用**规则包驱动**设计：

1. **加载规则包**：`load_pack(RulePack)` 将一组 ComplianceRule 注册到引擎
2. **扫描执行**：对 Artifact 逐条应用规则，通过 MatcherRegistry 路由到最优 checker
3. **结果聚合**：返回 ComplianceResult 列表，每条包含 passed/rule_id/findings

### 两种扫描模式

| 模式 | 方法 | 适用场景 | 输入 |
|------|------|---------|------|
| 快速扫描 | `scan_quick(content, path)` | 单文件、即时检查 | 字符串 + 路径 |
| 全量扫描 | `scan(artifacts, categories, ...)` | 项目级、批量检查 | Artifact 列表 + 筛选条件 |

### ComplianceRule 结构

每条规则定义一个合规约束：

```python
ComplianceRule(
    id="SEC-001",                    # 规则唯一标识
    category=ComplianceCategory.SECURITY,  # 类别：security/privacy/license/style/architecture
    pattern=r'password\s*=\s*["\']...',    # 正则/AST 模式
    severity="high",                 # 严重性：critical/high/medium/low/info
    description="禁止硬编码密码",    # 规则描述
    matcher_type="regex",            # 检查器类型：regex/ast/cross_file/...
    remediation="使用环境变量",      # 修复建议
    auto_fixable=False,              # 是否可自动修复
)
```

### MatcherRegistry 路由机制

规则通过 `matcher_type` 字段路由到最优 checker：

```
规则 matcher_type → MatcherRegistry.get(matcher_type) → 对应 Checker 实例
```

已注册引擎的 matcher_type 映射（含内置与外部，按类别列举）：

| matcher_type | Checker | 检查能力 |
|-------------|---------|---------|
| `regex` | RegexChecker | 正则模式匹配（最通用） |
| `ast` | ASTChecker | Python AST 结构分析 |
| `cross_file` | CrossFileChecker | 跨文件依赖/引用检查 |
| `dependency_graph` | DependencyGraphChecker | 模块依赖图分析 |
| `guardrails_ai` | GuardrailsAIChecker | Guardrails AI validator |
| `helicone` | HeliconeMiddlewareChecker | Helicone 代理护栏 |
| `llama-guard` | LlamaGuardChecker | Llama Guard LLM 安全分类 |
| `nemo` | NeMoGuardrailsChecker | NeMo Guardrails 多轮护栏 |
| `opa` | OPAChecker | OPA 策略评估 |
| `sonarqube` | SonarQubeChecker | SonarQube CI 扫描引用 |
| `archunit` | ArchUnitChecker | Java 架构约束验证 |
| `dep_cruiser` | DepCruiserChecker | JS/TS 依赖巡航 |

### 语言感知路由

MatcherRegistry 支持 `get_by_language(language)` 方法——根据文件语言推荐最优引擎：

- **Java** → ArchUnitChecker（架构合规最强）
- **JavaScript/TypeScript** → DepCruiserChecker（依赖合规最强）
- **通用语言** → 无特定推荐，使用规则指定的 matcher_type

语言路由是**建议性**的——用户可通过 `matcher_type` 显式覆盖。

### 规则导入器

4 个规则导入器将外部引擎的规则翻译为 ComplianceRule 格式：

| 导入器 | 来源 | 翻译方式 |
|--------|------|---------|
| SonarQubeRuleImporter | SonarQube `/api/rules/search` | HTTP API → ComplianceRule |
| OPARuleImporter | OPA Rego 策略文件 | Rego → ComplianceRule（pattern 为策略路径） |
| ArchUnitRuleImporter | Java 测试类 | 测试注解 → ComplianceRule |
| DepCruiserRuleImporter | `.dependency-cruiser.js` | 配置规则 → ComplianceRule |

导入后返回 `RulePack`，可直接 `engine.load_pack(pack)` 加载使用。

### ComplianceCategory 五大类

| 类别 | 枚举值 | 典型规则 |
|------|--------|---------|
| 安全 | `SECURITY` | 硬编码密钥、SQL 注入、XSS |
| 隐私 | `PRIVACY` | PII 泄露、日志脱敏 |
| 许可证 | `LICENSE` | GPL 传染性、未声明许可证 |
| 代码风格 | `STYLE` | naming convention、magic number |
| 架构 | `ARCHITECTURE` | 依赖方向、分层违规 |

---

## 配置

### ComplianceEngine 基础配置

```python
from harness.compliance_engine import ComplianceEngine

engine = ComplianceEngine(
    bus=event_bus,  # Optional[EventBus]，用于合规事件通知
)
```

### 规则包加载

```python
from harness.rule_packs import get_security_pack, get_privacy_pack

# 加载内置规则包
engine.load_pack(get_security_pack())
engine.load_pack(get_privacy_pack())

# 查看已加载规则包
print(engine.list_packs())
# ['security-rules', 'privacy-rules']
```

### 自定义规则包

```python
from harness.compliance_engine import RulePack
from harness.types import ComplianceRule, ComplianceCategory

custom_rules = RulePack(
    name="my-team-rules",
    category=ComplianceCategory.SECURITY,
    rules=[
        ComplianceRule(
            id="CUSTOM-001",
            category=ComplianceCategory.SECURITY,
            pattern=r'eval\s*\(',
            severity="critical",
            description="禁止使用 eval()",
            matcher_type="regex",
            remediation="使用 ast.literal_eval() 替代",
            auto_fixable=False,
        ),
    ],
)
engine.load_pack(custom_rules)
```

### 语言路由配置

```python
# 全量扫描时启用语言路由
results = engine.scan(
    artifacts=artifact_list,
    language_routing={"java": "archunit", "javascript": "dep_cruiser"},
)

# MatcherRegistry 直接查询
from harness.rule_checker import MatcherRegistry
MatcherRegistry.default()
recommended = MatcherRegistry().get_by_language("java")
# → ArchUnitChecker 实例
```

### Profile YAML 配置

```yaml
compliance:
  engines: [builtin]            # builtin / sonarqube / opa / archunit / dep_cruiser
  language_routing:
    java: archunit
    javascript: dep_cruiser
    typescript: dep_cruiser
  packs: [security, privacy]    # 加载哪些规则包
```

---

更多配置细节见 [合规扫描教程](/tutorial/compliance-scan)，可运行 Demo 见 [合规 Demo](/demo/compliance)。

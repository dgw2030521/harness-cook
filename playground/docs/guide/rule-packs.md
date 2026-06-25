# 规则包

harness-cook 提供五种内置合规规则包 + 外部引擎规则导入，覆盖代码风格、安全漏洞、数据隐私、运维规范、AI法律风险。每条规则声明式定义「什么可以做、什么不可以做」，引擎自动执行扫描。

## 规则包总览

### 内置规则包

| 规则包 | 工厂函数 | 规则数 | ID 前缀 | 类别映射 |
|--------|----------|--------|---------|----------|
| Coding | `get_coding_pack()` | 7 | `CODE-` | STYLE |
| Security | `get_security_pack()` | 7 | `SEC-` | SECURITY |
| Data | `get_data_pack()` | 6 | `DATA-` | PRIVACY |
| DevOps | `get_devops_pack()` | 6 | `OPS-` | ARCHITECTURE |
| Legal | `get_legal_pack()` | 14 | `LEGAL-` | LEGAL |

共 40 条内置规则，按正则模式匹配 + 严重性分级 + 修复建议的结构组织。

### 外部引擎规则导入

通过 RuleImporter 从外部引擎导入规则到 ComplianceRule 格式：

| 导入器 | 来源 | 规则数（典型） | 说明 |
|--------|------|----------------|------|
| SonarQubeRuleImporter | SonarQube API `/api/rules/search` | 900+ | 离线扫描规则 → ComplianceRule |
| ArchUnitRuleImporter | Java 测试类解析 | 视项目 | Java 架构规则 → ComplianceRule |
| DepCruiserRuleImporter | `.dependency-cruiser.js` 解析 | 视项目 | JS/TS 依赖规则 → ComplianceRule |

```python
from harness.integrations.rule_importer import SonarQubeRuleImporter, RulePack

importer = SonarQubeRuleImporter(
    sonarqube_url="http://sonar:9000",
    token="your-token"
)
pack = importer.import_rules(project_key="my-project")
engine.load_pack(pack)  # SonarQube 规则 → ComplianceEngine 可扫描
```

## 加载与扫描

```python
from harness.compliance import ComplianceEngine
from harness.rule_packs import get_coding_pack, get_security_pack, get_legal_pack

engine = ComplianceEngine()

# 加载内置规则包
engine.load_pack(get_coding_pack())
engine.load_pack(get_security_pack())
engine.load_pack(get_legal_pack())

# 加载外部引擎导入的规则包
# engine.load_pack(sonarqube_pack)

# 查看已加载的包
print(engine.list_packs())      # → ['coding', 'security', 'legal']
print(engine.stats())           # → {'total_rules': 28, 'packs': 3, ...}

# 扫描产出物（Artifact 列表）
results = engine.scan(artifacts)

# 快速扫描代码片段
results = engine.scan_quick(code_string, "path/to/file.py")
```

卸载规则包：`engine.unload_pack('coding')`——后续扫描不再应用该包的规则。

## 语言感知路由

ComplianceEngine.scan() 可根据文件语言自动路由最优引擎：

| 语言 | 推荐引擎 | fallback |
|---|---|---|
| Java | ArchUnitChecker | DependencyGraphChecker |
| JavaScript / TypeScript | DepCruiserChecker | DependencyGraphChecker |
| 通用策略 | OPAChecker | RegexChecker |

```yaml
# Profile 配置语言路由
compliance:
  language_routing:
    java: archunit
    javascript: dep_cruiser
    typescript: dep_cruiser
```

语言路由是建议性的——用户可通过 `matcher_type` 显式覆盖。

## Coding 规则包

编码风格与质量检查，`CODE-001` ~ `CODE-007`：

| ID | 检查项 | 严重性 |
|----|--------|--------|
| CODE-001 | 禁止 `TODO`/`FIXME` 未解决标记 | low |
| CODE-002 | 函数命名不符合 snake_case | medium |
| CODE-003 | 函数过长（超过 50 行） | medium |
| CODE-004 | 深度嵌套（超过 3 层） | medium |
| CODE-005 | 缺少类型注解 | low |
| CODE-006 | 禁止 bare `except` | high |
| CODE-007 | 禁止 `print()` 调试残留 | low |

## Security 规则包

常见安全违规检测，`SEC-001` ~ `SEC-007`：

| ID | 检查项 | 严重性 |
|----|--------|--------|
| SEC-001 | 硬编码密钥/密码/API token | critical |
| SEC-002 | SQL 注入风险（字符串拼接 SQL） | critical |
| SEC-003 | XSS 风险（未转义 HTML 输出） | high |
| SEC-004 | 不安全的反序列化（`pickle.load`） | high |
| SEC-005 | 不安全的文件操作（路径拼接） | medium |
| SEC-006 | 禁止 `eval()`/`exec()` 动态执行 | critical |
| SEC-007 | 弱哈希算法（MD5/SHA1 用于密码） | high |

::: warning
SEC-001（硬编码密钥）严重性为 `critical`——即使在 HYBRID 门禁模式下也会阻断执行。
:::

## Data 规则包

数据隐私与合规检查，`DATA-001` ~ `DATA-006`：

| ID | 检查项 | 严重性 |
|----|--------|--------|
| DATA-001 | PII 泄露（邮箱/手机号明文） | critical |
| DATA-002 | 日志中的敏感数据 | high |
| DATA-003 | 未加密的数据传输 | high |
| DATA-004 | 数据保留策略缺失 | medium |
| DATA-005 | 禁止全表 SELECT | medium |
| DATA-006 | GDPR 合规标识缺失 | low |

## DevOps 规则包

运维规范与架构约束，`OPS-001` ~ `OPS-006`：

| ID | 检查项 | 严重性 |
|----|--------|--------|
| OPS-001 | Docker 容器 root 运行 | high |
| OPS-002 | 缺少健康检查配置 | medium |
| OPS-003 | 端口暴露范围过大 | medium |
| OPS-004 | 缺少资源限制（CPU/Memory） | medium |
| OPS-005 | 禁止 `latest` 镜像标签 | high |
| OPS-006 | CI 缺少安全扫描步骤 | low |

## Legal 规则包

AI 生成内容的法律风险检测，`LEGAL-001` ~ `LEGAL-014`，覆盖中国法规和国际合规：

| ID | 检查项 | 严重性 | 法律依据 |
|----|--------|--------|----------|
| LEGAL-001 | AI 生成文件缺少免责声明 | medium | AI 生成内容声明义务 |
| LEGAL-002 | AI 免责声明包含保证性语言 | critical | 消费者权益保护 |
| LEGAL-003 | 版权归属 AI 模型 | high | 版权法 |
| LEGAL-004 | GPL/AGPL 在 import 链中 | high | GPL 许可证条款 |
| LEGAL-005 | 许可证归属被删除/修改 | high | 许可证法 |
| LEGAL-006 | 硬性保证/担保声明 | critical | 消费者权益保护法 |
| LEGAL-007 | 赔偿条款引用 AI | high | 合同法 |
| LEGAL-008 | 个人数据由 AI/LLM 处理 | high | 个人信息保护法 |
| LEGAL-009 | 数据保护法规缺少必要同意 | critical | 个人信息保护法 |
| LEGAL-010 | 重要数据交给外部/AI | critical | 数据安全法 |
| LEGAL-011 | 受知识产权保护的内容进入 AI 上下文 | high | 知识产权法 |
| LEGAL-012 | 代码抄袭语言检测 | high | 知识产权法 |
| LEGAL-013 | 生成式 AI 内容缺少标注 | high | 生成式AI暂行办法 |
| LEGAL-014 | Deepfake 生成能力 | critical | 刑法 |

::: warning
LEGAL-002/006/009/010/014 严重性为 `critical`——即使在 HYBRID 门禁模式下也会阻断执行。这些规则涉及中国个人信息保护法、数据安全法和刑法风险，不可忽视。
:::

```python
from harness.rule_packs import get_legal_pack

engine.load_pack(get_legal_pack())

# 中文硬性保证检测
artifact = Artifact(type="code", path="service.py",
                    content="# 本公司保证100%安全处理用户数据")
results = engine.scan([artifact])
# → LEGAL-006 (critical): 包含硬性保证声明
```

## 自定义规则

通过 `ComplianceRule` 定义自己的规则，然后封装为 `RulePack`：

```python
from harness.types import ComplianceRule, ComplianceCategory
from harness.compliance import RulePack

custom_rule = ComplianceRule(
    id="CUSTOM-001",
    category=ComplianceCategory.SECURITY,
    pattern=r"password\s*=\s*['\"].+['\"]",   # 正则模式
    severity="critical",
    description="禁止明文密码赋值",
    remediation="使用环境变量或密钥管理服务",
    auto_fixable=False,
    languages=["python", "javascript"],
)

custom_pack = RulePack(
    name="custom",
    description="团队自定义规则",
    rules=[custom_rule],
)

engine.load_pack(custom_pack)
```

ComplianceCategory 六种：`SECURITY`, `PRIVACY`, `LICENSE`, `LEGAL`, `STYLE`, `ARCHITECTURE`。

severity 四级：`low` → `medium` → `high` → `critical`。HYBRID 门禁模式下，`critical` 和 `high` 级违规阻断执行，`medium` 和 `low` 仅记录。

## ExternalEngineChecker 集成规则

外部引擎适配器中的规则通过 MatcherRegistry 路由：

```python
# MatcherRegistry.default() 注册引擎
registry.register("guardrails_ai", GuardrailsAIChecker())
registry.register("sonarqube", SonarQubeChecker())

# ComplianceEngine.scan() 中路由
result = registry.get(matcher_type).check(rule, artifact, context)
# matcher_type="guardrails_ai" → GuardrailsAIChecker
# matcher_type="regex" → RegexChecker（内置 fallback）
```

引擎不可用时自动降级——ExternalEngineChecker.check() 在 _call_engine 抛异常时 catch 回退到内置 checker。

## 扫描结果解读

每条扫描结果是一个 `ComplianceResult`，字段：

| 字段 | 含义 |
|------|------|
| `rule_id` | 触发的规则 ID |
| `passed` | 是否通过（True=合规） |
| `severity` | 严重性等级 |
| `findings` | 具体发现描述 |
| `remediation` | 修复建议 |
| `auto_fixable` | 是否可自动修复 |

```python
results = engine.scan(artifacts)
for r in results:
    if not r.passed:
        print(f"违规: {r.rule_id} ({r.severity})")
        print(f"  发现: {r.findings}")
        print(f"  修复: {r.remediation}")
```

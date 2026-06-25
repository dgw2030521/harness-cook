# 合规扫描

本教程展示如何加载规则包、扫描代码/文档、解读违规结果。

## Step 1: 创建合规引擎

ComplianceEngine 的架构（规则包驱动、MatcherRegistry 路由、两种扫描模式）见 [合规层原理](/guide/compliance-layer)。实操：创建引擎并加载规则包。

```python
from harness.compliance import ComplianceEngine
from harness.bus import EventBus

bus = EventBus()
engine = ComplianceEngine(bus=bus)
```

## Step 2: 加载规则包

四种内置规则包，按需加载：

```python
from harness.rule_packs import get_security_pack, get_coding_pack

engine.load_pack(get_security_pack())   # SEC-001 ~ SEC-007
engine.load_pack(get_coding_pack())     # CODE-001 ~ CODE-007

# 查看已加载状态
print(engine.list_packs())   # → ['security', 'coding']
print(engine.stats())        # → {'total_rules': 14, 'packs': 2, ...}
```

如果不需要某个包了，可以卸载：

```python
engine.unload_pack('coding')  # 后续扫描不再检查 CODE 规则
```

## Step 3: 快速扫描代码片段

`scan_quick()` 直接扫描字符串，无需构造 Artifact 对象：

```python
unsafe_code = '''
API_KEY = "sk-abc123def456"
password = "admin123"
user_email = "admin@company.com"
os.system("rm -rf /tmp")
'''

results = engine.scan_quick(unsafe_code, "config.py")

for r in results:
    if not r.passed:
        print(f"违规 {r.rule_id} ({r.severity}): {r.findings}")
        print(f"  → 修复: {r.remediation}")
```

预期输出：

```
违规 SEC-001 (critical): 硬编码密钥/API token
  → 修复: 使用环境变量或密钥管理服务
违规 DATA-001 (critical): PII 明文泄露
  → 修复: 脱敏处理或加密存储
```

::: warning
SEC-001 和 DATA-001 严重性为 `critical`——在 HYBRID 门禁模式下会阻断执行。
:::

## Step 4: 扫描工作流产出物

DAGEngine 执行完工作流后，产出物存储在 `ExecutionContext.node_artifacts` 中：

```python
# 假设 context 是 engine.execute(workflow) 的返回值
all_artifacts = []
for node_id, artifacts in context.node_artifacts.items():
    all_artifacts.extend(artifacts)

results = engine.scan(all_artifacts)

passed = sum(1 for r in results if r.passed)
failed = sum(1 for r in results if not r.passed)
print(f"扫描结果: {len(results)} 条检查, 通过 {passed}, 违规 {failed}")
```

## Step 5: 过滤与处理

按严重性分级处理违规：

```python
for r in results:
    if not r.passed:
        if r.severity == "critical":
            # 阻断——必须修复才能继续
            print(f"阻断: {r.rule_id} - {r.findings}")
        elif r.severity == "high":
            # 警告——建议修复
            print(f"警告: {r.rule_id} - {r.findings}")
        else:
            # 记录——低优先级
            print(f"记录: {r.rule_id} - {r.findings}")
```

## Step 6: 自定义规则

ComplianceRule 字段定义（`id` / `category` / `pattern` / `severity` / `matcher_type` / `remediation` / `auto_fixable`）见 [合规层原理](/guide/compliance-layer#compliancerule-结构)。团队可以定义自己的规则并封装为 RulePack：

```python
from harness.types import ComplianceRule, ComplianceCategory
from harness.compliance import RulePack

no_print_rule = ComplianceRule(
    id="TEAM-001",
    category=ComplianceCategory.STYLE,
    pattern=r"print\s*\(",
    severity="low",
    description="禁止 print() 调试残留",
    remediation="使用 logging 替代 print()",
    auto_fixable=False,
    languages=["python"],
)

team_pack = RulePack(
    name="team",
    description="团队规范规则",
    rules=[no_print_rule],
)

engine.load_pack(team_pack)
```

自定义规则与内置规则一起参与扫描，`engine.scan()` 返回的结果包含所有已加载包的检查。

---

## Step 7: SonarQube 引用模式（可选）

### 验证层级

SonarQube 是团队级代码质量基础设施——不是个人开发环境必须有的。验证分三个层级：

| 层级 | 前提 | 可验证什么 |
|------|------|-----------|
| 层级 1（单元测试） | 无额外前提 | SonarQubeChecker 可导入、初始化、fallback → RegexChecker |
| 层级 2 | 无本地 SDK（SonarQube 是 HTTP API 服务） | 无法本地验证 |
| 层级 3（远程服务） | SonarQube 服务器 + API token | 真实引用 CI 扫描结果 |

### 如何使用

SonarQubeChecker 采用**引用模式**——不触发新扫描，从最近 CI 扫描读取已有 issue：

```python
from harness.integrations.sonarqube_checker import SonarQubeChecker

# 配置连接信息
checker = SonarQubeChecker(config={
    "sonarqube_url": "https://sonar.example.com",  # 团队 SonarQube 服务器
    "sonarqube_token": "squ_xxxx...",               # API token
    "project_key": "my-project",                    # SonarQube 项目 key
})

# 检查可用性（会 HTTP GET /api/system/status）
print(f"SonarQube 可用: {checker._is_engine_available()}")

# 引用最近 CI 扫描结果
rule = ComplianceRule(
    id="SQ-PY-001",
    category=ComplianceCategory.SECURITY,
    pattern="python:S1234",        # SonarQube 规则 key
    severity="high",
    description="SonarQube 规则引用",
    matcher_type="sonarqube",
)
result = checker.check(rule, artifact, ScanContext(project_root="."))
```

**关键理解**：
- `_call_engine()` 通过 HTTP API 从 SonarQube 服务器读取已有扫描结果
- harness-cook **不替代 SonarQube 的扫描能力**——只引用其结果
- 没有 SonarQube 服务 → 自动 fallback 到 RegexChecker

### 规则导入

团队可从 SonarQube 导入 900+ 规则到 harness-cook：

```python
from harness.integrations.rule_importer import SonarQubeRuleImporter

importer = SonarQubeRuleImporter(
    sonarqube_url="https://sonar.example.com",
    sonarqube_token="squ_xxxx...",
    project_key="my-project",
)

# 导入规则 → RulePack（可直接 load_pack）
pack = importer.import_rules()
print(f"导入规则数: {len(pack.rules)}")

# 加载到合规引擎
engine.load_pack(pack)
```

### CI 环境验证

团队在 CI 流水线中验证 SonarQube 真实调用：

1. CI 先运行 `sonar-scanner` 扫描代码
2. harness-cook 合规层引用 SonarQube 扫描结果
3. 门禁根据 SonarQube issue 严重性做阻断/放行决策

下一步 → [门禁审批](./gate-approval)
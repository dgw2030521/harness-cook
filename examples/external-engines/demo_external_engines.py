"""
外部合规引擎集成 Demo

演示 harness-cook 的 4 种外部引擎集成 + 规则导入器：

1. SonarQube 引擎集成（引用模式——从 CI 缓存检索结果）
2. ArchUnit 架构规则检查（Java 分层违规/循环依赖）
3. DepCruiser 依赖约束检查（JS/TS 依赖规则）
4. OPA 策略引擎检查（Rego 实时策略评估）
5. 规则导入器——从外部引擎导入合规规则包

所有引擎在不可用时自动降级到内置 RegexChecker / DependencyGraphChecker，
不阻塞主流程。

运行方式:
  cd packages/core
  PYTHONPATH=. python3 ../../examples/external-engines/demo_external_engines.py
"""

import sys
sys.path.insert(0, "../../packages/core")

from harness.types import (
    Artifact, ComplianceRule, ComplianceResult, ScanContext,
    ComplianceCategory,
)
from harness.integrations.sonarqube_checker import SonarQubeChecker
from harness.integrations.archunit_checker import ArchUnitChecker
from harness.integrations.dep_cruiser_checker import DepCruiserChecker
from harness.integrations.opa_checker import OPAChecker
from harness.integrations.rule_importer import (
    SonarQubeRuleImporter,
    ArchUnitRuleImporter,
    DepCruiserRuleImporter,
    RulePack,
)
from harness.integrations.engine_config import (
    GuardrailsEngineConfig,
    ComplianceEngineConfig,
    AuditEngineConfig,
)


# ═══════════════════════════════════════════════════════════
#  公共数据
# ═══════════════════════════════════════════════════════════

# 模拟一个 Python 产出物——包含硬编码密钥的代码片段
ARTIFACT_PY = Artifact(
    type="code",
    path="src/auth/login.py",
    content="""
import hashlib

API_KEY = "sk-abc123def456"  # 硬编码密钥
DB_PASSWORD = "root_password"  # 硬编码数据库密码

def authenticate(username, password):
    # TODO: 使用环境变量替换硬编码密钥
    hashed = hashlib.sha256(password.encode()).hexdigest()
    return hashed == DB_PASSWORD
""",
)

# 模拟一个 Java 产出物——controller 直接访问 repository（分层违规）
ARTIFACT_JAVA = Artifact(
    type="code",
    path="src/main/java/com/example/controller/UserController.java",
    content="""
package com.example.controller;

import com.example.repository.UserRepository;

public class UserController {
    private UserRepository userRepo;  // controller 直接依赖 repository — 分层违规

    public User getUser(String id) {
        return userRepo.findById(id);
    }
}
""",
)

# 模拟一个 JS 产出物——组件直接导入 API 层（依赖方向违规）
ARTIFACT_JS = Artifact(
    type="code",
    path="src/components/LoginForm.jsx",
    content="""
import { loginUser } from '../api/auth';  // 组件直接导入 API 层 — 依赖违规

export function LoginForm() {
    const handleSubmit = (e) => {
        loginUser(credentials);
    };
}
""",
)

# 扫描上下文
CONTEXT = ScanContext(
    artifacts=[ARTIFACT_PY, ARTIFACT_JAVA, ARTIFACT_JS],
    project_root="/tmp/demo-project",
)


def print_result(result: ComplianceResult, label: str):
    """统一输出 ComplianceResult"""
    print(f"\n  [{label}] 结果:")
    print(f"    rule_id    = {result.rule_id}")
    print(f"    passed     = {result.passed}")
    print(f"    severity   = {result.severity}")
    if result.findings:
        for f in result.findings:
            print(f"    finding    = {f}")
    if result.remediation:
        print(f"    remediation = {result.remediation}")
    if result.locations:
        for loc in result.locations:
            print(f"    location   = {loc}")


# ═══════════════════════════════════════════════════════════
#  Demo 1: SonarQube 引擎集成
# ═══════════════════════════════════════════════════════════

def demo_sonarqube():
    """SonarQube 引擎集成——引用模式

    工作流程：
    1. _probe_engine: HTTP GET /api/system/status → 检查连接
    2. _translate_request: rule → SonarQube API 查询参数
    3. _call_engine: HTTP GET /api/issues/search → 检索缓存结果
    4. _translate_response: SonarQube issue → ComplianceResult

    降级：SonarQube 不可用时回退到 RegexChecker
    """
    print("\n" + "=" * 60)
    print("Demo 1: SonarQube 引擎集成（引用模式）")
    print("=" * 60)

    # ─── 1.1 创建 SonarQubeChecker ───
    print("\n  1.1 创建 checker（模拟配置）")
    checker = SonarQubeChecker(config={
        "sonarqube_url": "https://sonar.example.com",
        "sonarqube_token": "squ_demo_token_xxxx",
        "project_key": "demo-project",
    })
    print(f"    engine_name = {checker.engine_name}")
    print(f"    fallback    = {type(checker.fallback_checker).__name__}")

    # ─── 1.2 定义 SonarQube 规则 ───
    print("\n  1.2 定义规则")
    rule_s1234 = ComplianceRule(
        id="sonar-s1234",
        category=ComplianceCategory.SECURITY,
        pattern="python:S1234",
        severity="high",
        description="硬编码密钥不应出现在源码中",
        remediation="使用环境变量或密钥管理系统替代硬编码密钥",
        matcher_type="sonarqube",
        matcher_config={"rule_key": "python:S1234"},
    )
    print(f"    rule_id     = {rule_s1234.id}")
    print(f"    matcher_type = {rule_s1234.matcher_type}")
    print(f"    matcher_config.rule_key = {rule_s1234.matcher_config.get('rule_key')}")

    # ─── 1.3 执行检查 ───
    print("\n  1.3 执行检查（SonarQube 不可用 → 自动降级到 RegexChecker）")
    result = checker.check(rule_s1234, ARTIFACT_PY, CONTEXT)
    print_result(result, "SonarQube→降级RegexChecker")

    # ─── 1.4 严重性映射说明 ───
    print("\n  1.4 SonarQube 严重性映射")
    from harness.integrations.sonarqube_checker import SEVERITY_MAP
    for sq, harness in SEVERITY_MAP.items():
        print(f"    {sq} → {harness}")

    # ─── 1.5 可用性探测 ───
    print("\n  1.5 可用性探测（缓存机制）")
    print(f"    首次探测结果缓存，进程生命周期内不再重复")
    print(f"    reset_availability_cache() → 强制重新探测")
    checker.reset_availability_cache()
    print(f"    已重置缓存，下次 check 会重新探测")


# ═══════════════════════════════════════════════════════════
#  Demo 2: ArchUnit 架构规则检查
# ═══════════════════════════════════════════════════════════

def demo_archunit():
    """ArchUnit 架构规则检查——Java 项目分层/循环依赖

    工作流程：
    1. _probe_engine: 检查 JVM + ArchUnit jar
    2. _translate_request: matcher_config → ArchUnit 测试参数
    3. _call_engine: 子进程执行 ArchUnit Java 测试
    4. _translate_response: 测试结果 → ComplianceResult

    降级：JVM/ArchUnit jar 不存在时回退到 DependencyGraphChecker
    """
    print("\n" + "=" * 60)
    print("Demo 2: ArchUnit 架构规则检查")
    print("=" * 60)

    # ─── 2.1 创建 ArchUnitChecker ───
    print("\n  2.1 创建 checker（模拟配置）")
    checker = ArchUnitChecker(config={
        "java_home": "/usr/lib/jvm/java-11",
        "archunit_jar": "/opt/archunit/archunit.jar",
        "project_root": "/tmp/demo-project",
    })
    print(f"    engine_name  = {checker.engine_name}")
    print(f"    fallback     = {type(checker.fallback_checker).__name__}")

    # ─── 2.2 定义分层违规规则 ───
    print("\n  2.2 定义分层违规规则")
    rule_layer = ComplianceRule(
        id="arch-layer-violation",
        category=ComplianceCategory.ARCHITECTURE,
        pattern="controller→repository",
        severity="medium",
        description="Controller 不应直接依赖 Repository——应通过 Service 中间层",
        remediation="将 Repository 调用移到 Service 层",
        matcher_type="archunit",
        matcher_config={
            "check": "layer_violation",
            "layer_mapping": {
                "controller": "com.example.controller..",
                "service": "com.example.service..",
                "repository": "com.example.repository..",
            },
            "forbidden_directions": [
                {"from_layer": "controller", "to_layer": "repository"},
            ],
        },
    )
    print(f"    rule_id      = {rule_layer.id}")
    print(f"    matcher_type = {rule_layer.matcher_type}")
    print(f"    matcher_config.check = {rule_layer.matcher_config.get('check')}")

    # ─── 2.3 定义循环依赖规则 ───
    print("\n  2.3 定义循环依赖规则")
    rule_cycle = ComplianceRule(
        id="arch-no-cycles",
        category=ComplianceCategory.ARCHITECTURE,
        pattern="no_cycles",
        severity="high",
        description="包之间不应存在循环依赖",
        remediation="引入接口层或事件机制打破循环",
        matcher_type="archunit",
        matcher_config={"check": "no_cycles"},
    )
    print(f"    rule_id      = {rule_cycle.id}")
    print(f"    matcher_config.check = {rule_cycle.matcher_config.get('check')}")

    # ─── 2.4 执行检查 ───
    print("\n  2.4 执行检查（JVM/ArchUnit jar 不存在 → 降级到 DependencyGraphChecker）")
    result = checker.check(rule_layer, ARTIFACT_JAVA, CONTEXT)
    print_result(result, "ArchUnit→降级DependencyGraph")

    # ─── 2.5 说明：ArchUnit 支持的检查类型 ───
    print("\n  2.5 ArchUnit 支持的检查类型")
    print("    layer_violation   — 分层违规（controller→repository 等）")
    print("    no_cycles         — 包循环依赖")
    print("    naming_convention — 命名规范检查")


# ═══════════════════════════════════════════════════════════
#  Demo 3: DepCruiser 依赖约束检查
# ═══════════════════════════════════════════════════════════

def demo_dep_cruiser():
    """DepCruiser 依赖约束检查——JS/TS 依赖规则

    工作流程：
    1. _probe_engine: 检查 dependency-cruiser CLI
    2. _translate_request: matcher_config → depcruise 参数
    3. _call_engine: 子进程执行 depcruise --validate --output-type json
    4. _translate_response: 验证结果 → ComplianceResult

    降级：CLI 不存在时回退到 DependencyGraphChecker
    """
    print("\n" + "=" * 60)
    print("Demo 3: DepCruiser 依赖约束检查")
    print("=" * 60)

    # ─── 3.1 创建 DepCruiserChecker ───
    print("\n  3.1 创建 checker（模拟配置）")
    checker = DepCruiserChecker(config={
        "depcruise_cmd": "depcruise",
        "cruise_config": ".dependency-cruiser.js",
    })
    print(f"    engine_name  = {checker.engine_name}")
    print(f"    fallback     = {type(checker.fallback_checker).__name__}")

    # ─── 3.2 定义依赖违规规则 ───
    print("\n  3.2 定义依赖违规规则")
    rule_dep = ComplianceRule(
        id="dep-violation",
        category=ComplianceCategory.ARCHITECTURE,
        pattern="dependency_violation",
        severity="medium",
        description="组件不应直接导入 API 层——应通过 service/hook 中间层",
        remediation="将 API 调用抽到 service/hook 层",
        matcher_type="dep_cruiser",
        matcher_config={
            "check": "dependency_violation",
            "cruise_config": ".dependency-cruiser.js",
        },
    )
    print(f"    rule_id      = {rule_dep.id}")
    print(f"    matcher_type = {rule_dep.matcher_type}")
    print(f"    matcher_config.check = {rule_dep.matcher_config.get('check')}")

    # ─── 3.3 执行检查 ───
    print("\n  3.3 执行检查（depcruise CLI 不存在 → 降级到 DependencyGraphChecker）")
    result = checker.check(rule_dep, ARTIFACT_JS, CONTEXT)
    print_result(result, "DepCruiser→降级DependencyGraph")

    # ─── 3.4 说明：dep-cruise 输出格式 ───
    print("\n  3.4 dep-cruise 输出格式")
    print("    JSON 输出结构：")
    print("      {")
    print("        'violations': [")
    print("          {'rule': {'name': '...'}, 'from': 'src/components/...', 'to': 'src/api/...'}")
    print("        ]")
    print("      }")
    print("    非 JSON 输出 → 自动回退到文本解析模式")


# ═══════════════════════════════════════════════════════════
#  Demo 4: OPA 策略引擎检查
# ═══════════════════════════════════════════════════════════

def demo_opa():
    """OPA 策略引擎检查——Rego 实时策略评估

    工作流程：
    1. _probe_engine: HTTP GET /health 或嵌入式 SDK 检测
    2. _translate_request: matcher_config → OPA Rego 查询输入 JSON
    3. _call_engine: POST /v1/data/{policy_path} 或嵌入式调用
    4. _translate_response: OPA result → ComplianceResult

    降级：OPA 不可用时回退到 RegexChecker
    """
    print("\n" + "=" * 60)
    print("Demo 4: OPA 策略引擎检查")
    print("=" * 60)

    # ─── 4.1 创建 OPAChecker ───
    print("\n  4.1 创建 checker（HTTP 模式）")
    checker_http = OPAChecker(config={
        "opa_url": "http://localhost:8181",
        "policy_path": "harness/compliance/no_pii",
        "mode": "http",
    })
    print(f"    engine_name  = {checker_http.engine_name}")
    print(f"    fallback     = {type(checker_http.fallback_checker).__name__}")
    print(f"    mode         = http")

    # ─── 4.2 创建 OPAChecker（嵌入式模式）───
    print("\n  4.2 创建 checker（嵌入式模式）")
    checker_embedded = OPAChecker(config={
        "policy_path": "harness/compliance/no_pii",
        "mode": "embedded",
    })
    print(f"    engine_name  = {checker_embedded.engine_name}")
    print(f"    mode         = embedded")

    # ─── 4.3 定义 OPA 规则 ───
    print("\n  4.3 定义 OPA 规则")
    rule_opa = ComplianceRule(
        id="opa-no-pii",
        category=ComplianceCategory.PRIVACY,
        pattern="no_pii",
        severity="high",
        description="代码中不应包含 PII（个人身份信息）",
        remediation="移除或脱敏处理 PII 数据",
        matcher_type="opa",
        matcher_config={
            "policy_path": "harness/compliance/no_pii",
            "input_data": {"scan_depth": "full"},
        },
    )
    print(f"    rule_id      = {rule_opa.id}")
    print(f"    matcher_type = {rule_opa.matcher_type}")
    print(f"    matcher_config.policy_path = {rule_opa.matcher_config.get('policy_path')}")

    # ─── 4.4 执行检查 ───
    print("\n  4.4 执行检查（OPA 服务不可用 → 降级到 RegexChecker）")
    result = checker_http.check(rule_opa, ARTIFACT_PY, CONTEXT)
    print_result(result, "OPA→降级RegexChecker")

    # ─── 4.5 policy_path 解析说明 ───
    print("\n  4.5 OPA policy_path 解析优先级")
    print("    1. matcher_config.policy_path — 直接指定")
    print("    2. pattern → harness/compliance/{pattern}")
    print("    3. 默认 → harness/compliance/{rule.id}")

    # ─── 4.6 OPA 响应格式说明 ───
    print("\n  4.6 OPA 响应格式")
    print("    简单策略: {result: true/false}")
    print("    结构化策略: {result: {allowed: bool, violations: [{msg: '...'}]}}")


# ═══════════════════════════════════════════════════════════
#  Demo 5: 规则导入器
# ═══════════════════════════════════════════════════════════

def demo_rule_importer():
    """规则导入器——从外部引擎导入合规规则包

    3 种导入器：
    - SonarQubeRuleImporter → 从 SonarQube API 导入规则
    - ArchUnitRuleImporter  → 从 Java 测试文件/JSON 配置导入规则
    - DepCruiserRuleImporter → 从 .dependency-cruiser.json 导入规则

    所有导入器返回 RulePack，可直接加载到 ComplianceEngine
    """
    print("\n" + "=" * 60)
    print("Demo 5: 规则导入器——从外部引擎导入合规规则包")
    print("=" * 60)

    # ─── 5.1 SonarQube 规则导入 ───
    print("\n  5.1 SonarQube 规则导入")
    sq_importer = SonarQubeRuleImporter(config={
        "sonarqube_url": "https://sonar.example.com",
        "sonarqube_token": "squ_demo_token_xxxx",
    })
    # 未连接 SonarQube → 返回空 RulePack（不阻塞）
    sq_pack = sq_importer.import_rules(
        project_key="demo-project",
        languages=["python", "java"],
    )
    print(f"    pack  = {sq_pack}")
    print(f"    name  = {sq_pack.name}")
    print(f"    source = {sq_pack.source}")
    print(f"    rules = {len(sq_pack.rules)} 条")
    if sq_pack.metadata:
        print(f"    metadata = {sq_pack.metadata}")

    # ─── 5.2 ArchUnit 规则导入（从 JSON 配置）───
    print("\n  5.2 ArchUnit 规则导入（从 JSON 配置）")

    # 创建模拟的 ArchUnit JSON 配置
    import json, tempfile, os
    archunit_config = {
        "checks": [
            {
                "type": "layer_violation",
                "name": "controller-no-repository",
                "severity": "medium",
                "description": "Controller 不应直接访问 Repository",
                "config": {
                    "layer_mapping": {
                        "controller": "com.example.controller..",
                        "service": "com.example.service..",
                        "repository": "com.example.repository..",
                    },
                    "forbidden_directions": [
                        {"from_layer": "controller", "to_layer": "repository"},
                    ],
                },
            },
            {
                "type": "no_cycles",
                "name": "no-package-cycles",
                "severity": "high",
                "description": "包之间不应存在循环依赖",
                "config": {},
            },
        ],
    }
    config_path = os.path.join(tempfile.mkdtemp(), "archunit-config.json")
    with open(config_path, "w") as f:
        json.dump(archunit_config, f)

    au_importer = ArchUnitRuleImporter()
    au_pack = au_importer.import_rules_from_config(config_file=config_path)
    print(f"    pack  = {au_pack}")
    print(f"    name  = {au_pack.name}")
    print(f"    source = {au_pack.source}")
    print(f"    rules = {len(au_pack.rules)} 条")
    for rule in au_pack.rules:
        print(f"      - id={rule.id}, matcher_type={rule.matcher_type}, "
              f"severity={rule.severity}, check={rule.matcher_config.get('check', rule.pattern)}")
    if au_pack.metadata:
        print(f"    metadata = {au_pack.metadata}")

    # ─── 5.3 DepCruiser 规则导入（从 JSON 配置）───
    print("\n  5.3 DepCruiser 规则导入（从 JSON 配置）")

    # 创建模拟的 .dependency-cruiser.json 配置
    dep_cruiser_config = {
        "forbidden": [
            {
                "name": "no-components-to-api",
                "comment": "组件不应直接导入 API 层",
                "severity": "error",
                "from": {"path": "src/components/[^/]+\\.jsx"},
                "to": {"path": "src/api/"},
            },
            {
                "name": "no-api-to-components",
                "comment": "API 层不应导入组件",
                "severity": "warn",
                "from": {"path": "src/api/"},
                "to": {"path": "src/components/"},
            },
        ],
        "allowed": [
            {
                "name": "components-to-hooks",
                "comment": "组件可以通过 hooks 间接访问数据层",
                "from": {"path": "src/components/"},
                "to": {"path": "src/hooks/"},
            },
        ],
    }
    dep_config_path = os.path.join(tempfile.mkdtemp(), ".dependency-cruiser.json")
    with open(dep_config_path, "w") as f:
        json.dump(dep_cruiser_config, f)

    dc_importer = DepCruiserRuleImporter()
    dc_pack = dc_importer.import_rules(config_file=dep_config_path)
    print(f"    pack  = {dc_pack}")
    print(f"    name  = {dc_pack.name}")
    print(f"    source = {dc_pack.source}")
    print(f"    rules = {len(dc_pack.rules)} 条")
    for rule in dc_pack.rules:
        print(f"      - id={rule.id}, pattern={rule.pattern}, severity={rule.severity}, "
              f"matcher_type={rule.matcher_type}")
    if dc_pack.metadata:
        print(f"    metadata = {dc_pack.metadata}")

    # ─── 5.4 RulePack 可直接加载到 ComplianceEngine ───
    print("\n  5.4 RulePack → ComplianceEngine 加载方式")
    print("    engine.load_pack(au_pack)  # 直接加载 ArchUnit 导入的规则包")
    print("    engine.load_pack(dc_pack) # 直接加载 DepCruiser 导入的规则包")
    print("    导入的规则 matcher_type 对应引擎名，引擎可用时自动路由")

    # ─── 5.5 治理引擎配置 dataclass ───
    print("\n  5.5 治理引擎配置（三层架构）")

    guardrails_cfg = GuardrailsEngineConfig(
        engine="guardrails-ai",
        config={"api_key": "demo_key"},
    )
    print(f"    GuardrailsEngineConfig: engine={guardrails_cfg.engine}")

    compliance_cfg = ComplianceEngineConfig(
        engines=["builtin", "sonarqube", "opa"],
        language_routing={"java": "archunit", "javascript": "dep_cruiser"},
        config={
            "sonarqube_url": "https://sonar.example.com",
            "sonarqube_token": "squ_xxxx",
            "opa_url": "http://localhost:8181",
        },
    )
    print(f"    ComplianceEngineConfig: engines={compliance_cfg.engines}")
    print(f"    language_routing={compliance_cfg.language_routing}")

    audit_cfg = AuditEngineConfig(
        backends=["local", "langfuse"],
        trace_format="otel-json",
        collector_url="http://localhost:4318",
    )
    print(f"    AuditEngineConfig: backends={audit_cfg.backends}")
    print(f"    trace_format={audit_cfg.trace_format}")


# ═══════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("Harness External Engines Demo")
    print("=" * 60)

    demo_sonarqube()
    demo_archunit()
    demo_dep_cruiser()
    demo_opa()
    demo_rule_importer()

    print("\n" + "=" * 60)
    print("所有外部引擎 Demo 完成")
    print("=" * 60)

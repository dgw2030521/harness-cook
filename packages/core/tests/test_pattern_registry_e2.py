"""
E-2 验收测试：PatternRegistry 统一规则源

验收标准：
1. API Key 泄露只报一次——同一正则不在三层重复定义
2. 新增 PII 模式只改一处——只需在 PatternRegistry 注册，各层自动获取
3. 护栏/合规/门禁三层从同一 Registry 获取模式
4. 向后兼容——PIIDetector.PATTERNS 属性仍可用，旧键名 "api_key_generic" 仍兼容
5. 模式数量完整——PatternRegistry 覆盖三层所有原有模式
"""

import sys
import os

# 确保可以 import harness 包
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.pattern_registry import PatternRegistry, get_pattern_registry
from harness.types import (
    ComplianceCategory, PatternDefinition, Artifact,
    CheckResult, GateMode,
)
from harness.gates import check_no_secrets, check_no_eval, check_no_sql_injection
from harness.guardrails import PIIDetector
from harness.compliance_engine import security_rule_pack, privacy_rule_pack


def test_pattern_registry_has_all_security_patterns():
    """PatternRegistry 包含所有 SECURITY 类别模式"""
    registry = get_pattern_registry()
    security_defs = registry.get_by_category(ComplianceCategory.SECURITY)

    # 原三层 SECURITY 模式总数：
    # 护栏 OutputGuardrails: 6 (eval/exec/__import__/os.system/subprocess/pickle)
    # 合规 security_rule_pack: 8 (hardcoded-secret/openai-key/github-token/eval/exec/sql-injection/unsafe-regex/http-url)
    # 门禁 check_no_secrets: 5 (password/api_key/secret/token/openai/github)
    # 门禁 check_no_eval: 3 (eval/exec/compile)
    # 门禁 check_no_sql_injection: 5 (4 f-string + 1 concat)
    # 合并后应有：secret(5) + code_injection(7) + sql_injection(5) + unsafe_code(2) = 19
    assert len(security_defs) >= 19, \
        f"SECURITY 模式数量不足：应有 ≥19，实际 {len(security_defs)}"

    # 检查关键模式 ID
    expected_ids = [
        "hardcoded-password", "hardcoded-api-key", "hardcoded-secret-token",
        "openai-api-key", "github-token",
        "code-injection-eval", "code-injection-exec",
        "sql-injection-fstring-select",
    ]
    for id in expected_ids:
        assert registry.get(id) is not None, \
            f"缺少 SECURITY 模式: {id}"


def test_pattern_registry_has_all_privacy_patterns():
    """PatternRegistry 包含所有 PRIVACY 类别模式"""
    registry = get_pattern_registry()
    privacy_defs = registry.get_by_category(ComplianceCategory.PRIVACY)

    # 原两层 PRIVACY 模式总数：
    # 护栏 PIIDetector: 9 (email/phone_us/phone_intl/ssn/credit_card/ip_address/id_card_cn/phone_cn/bank_card_cn)
    # 合规 privacy_rule_pack: 3 (email/phone/ip-private)
    # 合并后应有：email + phone_us + phone_intl + ssn + credit_card + ip_address + ip_private
    #             + id_card_cn + phone_cn + bank_card_cn = 10
    assert len(privacy_defs) >= 10, \
        f"PRIVACY 模式数量不足：应有 ≥10，实际 {len(privacy_defs)}"

    # 检查关键模式 ID
    expected_ids = [
        "pii-email", "pii-phone-us", "pii-ssn", "pii-credit-card",
        "pii-id-card-cn", "pii-phone-cn", "pii-bank-card-cn",
    ]
    for id in expected_ids:
        assert registry.get(id) is not None, \
            f"缺少 PRIVACY 模式: {id}"


def test_api_key_no_duplicate_definition():
    """验收标准1：API Key 泄露只报一次——同一正则不在三层重复定义

    验证方式：检查 PatternRegistry 中 secret 模式数量，
    确保 API Key 检测正则只有一个定义源。
    """
    registry = get_pattern_registry()

    # 搜索所有包含 "api_key" 或 "apikey" 的模式
    api_key_patterns = []
    for defn in registry.all_patterns():
        if "api_key" in defn.pattern.lower() or "apikey" in defn.pattern.lower():
            api_key_patterns.append(defn)

    # 应只有 1 个 api_key 模式定义（hardcoded-api-key）
    # 旧代码有 3 处：护栏 api_key_generic、合规 sec-hardcoded-secret（合并版）、门禁（阈值16版）
    # 统一后只有 1 处
    assert len(api_key_patterns) == 1, \
        f"API Key 模式定义重复：应有 1 处，实际 {len(api_key_patterns)} 处（{[d.id for d in api_key_patterns]}）"

    # 验证各层都从 PatternRegistry 获取
    # 护栏层：PIIDetector 的 PATTERNS 属性应包含 api_key
    detector = PIIDetector()
    assert "api_key" in detector.PATTERNS, \
        f"护栏层 PIIDetector.PATTERNS 缺少 api_key sub_type"

    # 合规层：security_rule_pack 应包含 api_key 模式
    sec_rules = security_rule_pack().rules
    api_key_rules = [r for r in sec_rules if "api_key" in r.pattern.lower() or "apikey" in r.pattern.lower()]
    assert len(api_key_rules) >= 1, \
        f"合规层 security_rule_pack 缺少 API Key 规则"

    # 门禁层：check_no_secrets 应能检测 api_key
    artifact_with_api_key = Artifact(
        path="test.py",
        content="api_key = \"sk-abcd1234efgh5678\"",
        type="file",
    )
    result = check_no_secrets(artifact_with_api_key)
    assert result.passed is False, \
        "门禁层 check_no_secrets 应检测到 api_key 泄露"


def test_new_pii_only_change_one_place():
    """验收标准2：新增 PII 模式只改一处

    验证方式：在 PatternRegistry 注册一个新的 PII 模式，
    确认护栏层自动获取（不需修改 guardrails.py）。
    """
    # 重置 Registry 以注册测试模式
    PatternRegistry.reset_instance()
    registry = PatternRegistry.get_instance()

    # 注册一个测试用的"中国驾照号"模式
    test_pattern = PatternDefinition(
        id="pii-driver-license-cn-test",
        pattern=r'\b\d{12}\b',  # 中国驾照号（12位）
        category=ComplianceCategory.PRIVACY,
        target_type="pii",
        canonical_severity="high",
        sub_type="driver_license_cn",
        description="中国驾照号暴露——12位驾照号码",
        remediation="驾照号属于个人隐私信息，不应出现在代码或输出中",
    )
    registry.register(test_pattern)

    # 验证护栏层自动获取新模式
    detector = PIIDetector()
    assert "driver_license_cn" in detector.PATTERNS, \
        "护栏层应自动获取 PatternRegistry 中新增的 PII 模式"

    # 验证合规层自动获取新模式
    priv_rules = privacy_rule_pack().rules
    driver_license_rules = [r for r in priv_rules if r.id == "pii-driver-license-cn-test"]
    assert len(driver_license_rules) >= 1, \
        "合规层应自动获取 PatternRegistry 中新增的 PII 模式"

    # 验证新模式可检测
    test_content = "My driver license is 123456789012"
    findings = detector.detect(test_content, ["driver_license_cn"])
    assert len(findings) > 0, \
        "新增的 PII 模式应能正确检测"

    # 清理测试模式
    PatternRegistry.reset_instance()


def test_guardrails_backward_compat():
    """验收标准4：向后兼容——PIIDetector.PATTERNS 属性和旧键名仍可用"""
    detector = PIIDetector()

    # PATTERNS 属性应返回 dict
    patterns = detector.PATTERNS
    assert isinstance(patterns, dict), \
        f"PIIDetector.PATTERNS 应返回 dict，实际返回 {type(patterns)}"

    # 旧键名 "api_key_generic" 应仍能检测（映射到新 sub_type "api_key"）
    content = "api_key = \"sk-abcd1234efgh5678\""
    findings = detector.detect(content, ["api_key_generic"])
    assert len(findings) > 0, \
        "旧键名 api_key_generic 应仍能检测 API Key 泄露"

    # 新键名 "api_key" 也应能检测
    findings_new = detector.detect(content, ["api_key"])
    assert len(findings_new) > 0, \
        "新键名 api_key 应能检测 API Key 泄露"


def test_gates_use_pattern_registry():
    """门禁层从 PatternRegistry 获取模式"""
    # check_no_secrets 应能检测所有 secret 模式
    # 测试密码泄露
    artifact_password = Artifact(
        path="test.py",
        content="password = \"mysecret123\"",
        type="file",
    )
    result = check_no_secrets(artifact_password)
    assert result.passed is False, \
        "门禁 check_no_secrets 应检测到密码泄露"

    # 测试 OpenAI API Key
    artifact_openai = Artifact(
        path="test.py",
        content="key = sk-abcdefghijklmnopqrstuvwxyz123456",
        type="file",
    )
    result = check_no_secrets(artifact_openai)
    assert result.passed is False, \
        "门禁 check_no_secrets 应检测到 OpenAI API Key"

    # 测试 GitHub Token
    artifact_github = Artifact(
        path="test.py",
        content="token = ghp_abcdefghijklmnopqrstuvwxyz1234567890AB",
        type="file",
    )
    result = check_no_secrets(artifact_github)
    assert result.passed is False, \
        "门禁 check_no_secrets 应检测到 GitHub Token"

    # check_no_eval 应能检测所有 code_injection 模式
    artifact_eval = Artifact(
        path="test.py",
        content="result = eval(user_input)",
        type="file",
    )
    result = check_no_eval(artifact_eval)
    assert result.passed is False, \
        "门禁 check_no_eval 应检测到 eval()"

    # check_no_sql_injection 应能检测所有 sql_injection 模式
    artifact_sql = Artifact(
        path="test.py",
        content="query = f\"SELECT * FROM users WHERE id = {user_id}\"",
        type="file",
    )
    result = check_no_sql_injection(artifact_sql)
    assert result.passed is False, \
        "门禁 check_no_sql_injection 应检测到 SQL 注入"


def test_compliance_use_pattern_registry():
    """合规层从 PatternRegistry 获取模式"""
    sec_pack = security_rule_pack()
    priv_pack = privacy_rule_pack()

    # security_rule_pack 应包含所有 SECURITY 模式
    assert len(sec_pack.rules) >= 19, \
        f"security_rule_pack 规则数量不足：应有 ≥19，实际 {len(sec_pack.rules)}"

    # privacy_rule_pack 应包含所有 PRIVACY 模式
    assert len(priv_pack.rules) >= 10, \
        f"privacy_rule_pack 规则数量不足：应有 ≥10，实际 {len(priv_pack.rules)}"

    # 检查关键规则 ID
    sec_rule_ids = [r.id for r in sec_pack.rules]
    assert "hardcoded-password" in sec_rule_ids, \
        f"security_rule_pack 缺少 hardcoded-password 规则"
    assert "openai-api-key" in sec_rule_ids, \
        f"security_rule_pack 缺少 openai-api-key 规则"

    priv_rule_ids = [r.id for r in priv_pack.rules]
    assert "pii-email" in priv_rule_ids, \
        f"privacy_rule_pack 缺少 pii-email 规则"
    assert "pii-id-card-cn" in priv_rule_ids, \
        f"privacy_rule_pack 缺少 pii-id-card-cn 规则（新增覆盖）"


def test_password_threshold_unified():
    """密码检测阈值统一——从三层不一致（6/8/8）统一为 8"""
    # 统一后的密码模式阈值应为 8
    registry = get_pattern_registry()
    password_def = registry.get("hardcoded-password")
    assert password_def is not None, "缺少 hardcoded-password 模式"

    # 长度 8 的密码应被检测到
    detector = PIIDetector()
    content_8 = "password = \"mysecret\""
    findings = detector.detect(content_8, ["password"])
    assert len(findings) > 0, \
        "阈值 8 的密码应被检测到"

    # 长度 6 的密码不再被检测（旧护栏阈值 6，统一后阈值 8）
    content_6 = "pwd = \"abc12\""
    findings_short = detector.detect(content_6, ["password"])
    assert len(findings_short) == 0, \
        "阈值 6 的短密码不再被检测（统一阈值 8 后的行为变更）"


def test_no_inline_patterns_in_layers():
    """验收：三层模块中不再有硬编码正则模式定义

    验证方式：搜索三层模块中是否仍有内联正则列表。
    """
    import harness.guardrails as guardrails_mod
    import harness.gates as gates_mod

    # guardrails.py 中不应再有 unsafe_patterns 内联列表
    # 检查 OutputGuardrails.check 方法中不再有硬编码正则
    source_lines = open(guardrails_mod.__file__, "r").readlines()
    for i, line in enumerate(source_lines):
        # 不应有 r'\beval\s*\(' 等内联正则（已迁移到 PatternRegistry）
        if "r'\\beval" in line or "r\"\\beval" in line:
            assert False, \
                f"guardrails.py 第{i+1}行仍有内联正则定义: {line.strip()}"

    # gates.py 中不应再有 secret_patterns 内联列表
    source_lines = open(gates_mod.__file__, "r").readlines()
    for i, line in enumerate(source_lines):
        # 不应有 "secret_patterns = [" 或 "eval_patterns = [" 等内联列表
        if "secret_patterns = [" in line or "eval_patterns = [" in line:
            assert False, \
                f"gates.py 第{i+1}行仍有内联正则列表: {line.strip()}"


# ─── 运行所有测试 ────────────────────────────────────────

def run_all_tests():
    tests = [
        test_pattern_registry_has_all_security_patterns,
        test_pattern_registry_has_all_privacy_patterns,
        test_api_key_no_duplicate_definition,
        test_new_pii_only_change_one_place,
        test_guardrails_backward_compat,
        test_gates_use_pattern_registry,
        test_compliance_use_pattern_registry,
        test_password_threshold_unified,
        test_no_inline_patterns_in_layers,
    ]

    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
            print(f"✅ {test_fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"❌ {test_fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"❌ {test_fn.__name__}: 异常 {type(e).__name__}: {e}")

    print(f"\n结果：{passed} 通过，{failed} 失败")
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

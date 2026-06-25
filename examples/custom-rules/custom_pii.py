"""自定义 PII 合规规则包示例

展示如何创建自定义合规规则包。
此规则包检测中文特定 PII 信息（身份证、手机号）。

将此文件复制到项目的 .harness/rules/ 目录，
harness-cook 会自动发现并加载。
"""

from harness.compliance import ComplianceCategory, ComplianceRule, RulePack


def get_custom_pii_pack() -> RulePack:
    """返回自定义 PII 规则包"""
    rules = [
        ComplianceRule(
            id="CUSTOM-PII-001",
            category=ComplianceCategory.PRIVACY,
            pattern=r"\b\d{17}[\dXx]\b",
            severity="critical",
            description="中国身份证号泄露（18位）",
            remediation="使用脱敏处理: 只显示前3位和后4位，中间用*替换",
            languages=["python", "javascript", "typescript", "java"],
        ),
        ComplianceRule(
            id="CUSTOM-PII-002",
            category=ComplianceCategory.PRIVACY,
            pattern=r"\b1[3-9]\d{9}\b",
            severity="high",
            description="中国手机号泄露（11位）",
            remediation="使用脱敏处理: 只显示前3位和后4位，中间用*替换",
            languages=["python", "javascript", "typescript", "java"],
        ),
        ComplianceRule(
            id="CUSTOM-PII-003",
            category=ComplianceCategory.PRIVACY,
            pattern=r"姓名[：:]\s*[^\s]{2,4}",
            severity="medium",
            description="中文姓名标注可能泄露个人信息",
            remediation="避免在日志或代码中标注真实姓名",
            languages=["python", "javascript"],
        ),
    ]
    return RulePack("custom_pii", ComplianceCategory.PRIVACY, rules)
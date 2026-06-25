"""
护栏 Demo 示例

演示 harness-cook 护栏层的 PII 检测、红脱/阻断、中国特定 PII。

运行方式:
  cd packages/core
  PYTHONPATH=. python3 ../../examples/guardrails/demo_guardrails.py

输出:
  - PII 检测与红脱
  - PII 阻断模式
  - 中国特定 PII（手机号/身份证/银行卡）
  - 无 PII 内容
"""

import sys
sys.path.insert(0, "../../packages/core")

from harness.guardrails import GuardrailsPair
from harness.types import (
    InputGuardrailConfig, OutputGuardrailConfig, GuardrailAction,
)


def demo_pii_redact():
    """Demo 1: PII 检测与红脱"""
    print("\n" + "=" * 60)
    print("Demo 1: PII 检测与红脱")
    print("=" * 60)

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

    result = pair.check_input(
        "用户张三的手机号13812345678，身份证410105199001011234"
    )
    print(f"  违规: {result.violations}")
    print(f"  红脱: {result.redactions}")
    print(f"  阻断: {result.blocked}")
    print(f"  处理后: {result.processed_content}")


def demo_pii_block():
    """Demo 2: PII 阻断模式"""
    print("\n" + "=" * 60)
    print("Demo 2: PII 阻断模式")
    print("=" * 60)

    pair = GuardrailsPair(
        input_config=InputGuardrailConfig(
            detect_pii_types=["ssn"],
            pii_action=GuardrailAction.BLOCK,
        ),
        output_config=OutputGuardrailConfig(detect_pii_in_output=False),
    )

    result = pair.check_input("SSN: 123-45-6789")
    print(f"  阻断: {result.blocked}")
    print(f"  动作: {result.action}")
    print(f"  违规: {result.violations}")


def demo_chinese_pii():
    """Demo 3: 中国特定 PII"""
    print("\n" + "=" * 60)
    print("Demo 3: 中国特定 PII")
    print("=" * 60)

    pair = GuardrailsPair(
        input_config=InputGuardrailConfig(
            detect_pii_types=["phone_cn", "id_card_cn", "bank_card_cn"],
            pii_action=GuardrailAction.REDACT,
        ),
        output_config=OutputGuardrailConfig(detect_pii_in_output=False),
    )

    # 中国手机号
    r1 = pair.check_input("联系电话：13912345678")
    print(f"  中国手机号红脱: {'[REDACTED_phone_cn]' in r1.processed_content}")

    # 中国身份证号
    r2 = pair.check_input("身份证号410105199001011234")
    print(f"  中国身份证红脱: {'[REDACTED_id_card_cn]' in r2.processed_content}")

    # 银行卡号
    r3 = pair.check_input("银行卡6222021234567890123")
    print(f"  银行卡红脱: {'[REDACTED_bank_card_cn]' in r3.processed_content}")


def demo_no_pii():
    """Demo 4: 无 PII 内容"""
    print("\n" + "=" * 60)
    print("Demo 4: 无 PII 内容")
    print("=" * 60)

    pair = GuardrailsPair(
        input_config=InputGuardrailConfig(
            detect_pii_types=["email", "phone_cn"],
            pii_action=GuardrailAction.REDACT,
        ),
        output_config=OutputGuardrailConfig(detect_pii_in_output=False),
    )

    result = pair.check_input("这是一段正常的文本")
    print(f"  违规: {result.violations}")
    print(f"  红脱: {result.redactions}")
    print(f"  阻断: {result.blocked}")


def demo_output_guardrails():
    """Demo 5: 输出护栏"""
    print("\n" + "=" * 60)
    print("Demo 5: 输出护栏——检测 AI 输出中的 PII")
    print("=" * 60)

    pair = GuardrailsPair(
        input_config=InputGuardrailConfig(detect_pii_types=[]),
        output_config=OutputGuardrailConfig(
            detect_pii_in_output=True,
            output_pii_action=GuardrailAction.REDACT,
        ),
    )

    result = pair.check_output(
        "分析完成：用户邮箱 admin@company.com，建议联系 13912345678"
    )
    print(f"  违规: {result.violations}")
    print(f"  处理后: {result.processed_content}")


if __name__ == "__main__":
    print("=" * 60)
    print("Harness Guardrails Demo")
    print("=" * 60)
    demo_pii_redact()
    demo_pii_block()
    demo_chinese_pii()
    demo_no_pii()
    demo_output_guardrails()
    print("\n✅ 所有护栏 Demo 完成")

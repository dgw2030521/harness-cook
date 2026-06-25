#!/usr/bin/env python3
"""
声明式规则使用示例

展示如何通过 YAML 配置定义质量门禁规则
"""

import sys
import json
from pathlib import Path

# 添加 harness-cook 到 Python 路径
harness_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(harness_root / "packages" / "core"))

from harness.declarative_rules import (
    load_rules_from_yaml,
    create_gate_from_rules,
    load_and_create_gate,
    list_checkers,
)
from harness.gates import GateEngine
from harness.types import Artifact


def demo_list_checkers():
    """列出所有可用的 Checker"""
    print("=" * 60)
    print("声明式规则 - 可用 Checker 列表")
    print("=" * 60)

    checkers = list_checkers()
    print(f"\n✓ 已注册 {len(checkers)} 个 Checker:")
    for checker in checkers:
        print(f"  - {checker}")


def demo_load_rules():
    """从 YAML 加载规则"""
    print("\n" + "=" * 60)
    print("声明式规则 - 从 YAML 加载")
    print("=" * 60)

    yaml_path = Path(__file__).parent / "rules" / "example-rules.yaml"

    print(f"\n✓ 加载规则文件: {yaml_path}")
    rules = load_rules_from_yaml(str(yaml_path))

    print(f"\n✓ 加载了 {len(rules)} 条规则:")
    for rule in rules:
        print(f"  - [{rule.severity}] {rule.id}: {rule.description}")
        print(f"    Checker: {rule.checker}")

    return rules


def demo_create_gate(rules):
    """创建 Gate"""
    print("\n" + "=" * 60)
    print("声明式规则 - 创建 Gate")
    print("=" * 60)

    gate = create_gate_from_rules(rules, gate_id="demo-gate")

    print(f"\n✓ 创建 Gate: {gate.id}")
    print(f"  - 检查项数量: {len(gate.checks)}")
    print(f"  - 模式: {gate.mode.value}")

    return gate


def demo_check_clean_artifact(gate):
    """检查干净的 Artifact"""
    print("\n" + "=" * 60)
    print("声明式规则 - 检查干净的代码")
    print("=" * 60)

    engine = GateEngine()

    artifact = Artifact(
        type="code",
        path="clean_code.py",
        content="""
def calculate_sum(a, b):
    \"\"\"计算两个数的和\"\"\"
    return a + b

def calculate_product(a, b):
    \"\"\"计算两个数的积\"\"\"
    return a * b

print("Hello, world!")
""",
    )

    print(f"\n✓ 检查 Artifact: {artifact.path}")
    result = engine.check([artifact], gate)

    if result.passed:
        print(f"\n✅ 检查通过！")
        print(f"  - 总检查数: {result.total_checks}")
        print(f"  - 通过数: {result.passed_checks}")
    else:
        print(f"\n❌ 检查失败！")
        print(f"  - 总检查数: {result.total_checks}")
        print(f"  - 失败数: {result.failed_checks}")
        for check_result in result.check_results:
            if not check_result.passed:
                print(f"  - {check_result.severity}: {check_result.message}")

    return result


def demo_check_dirty_artifact(gate):
    """检查有问题的 Artifact"""
    print("\n" + "=" * 60)
    print("声明式规则 - 检查有问题的代码")
    print("=" * 60)

    engine = GateEngine()

    artifact = Artifact(
        type="code",
        path="dirty_code.py",
        content="""
def my_function():
    # TODO: implement this
    result = eval('1 + 1')  # 不安全的 eval

    api_key = "sk-1234567890abcdefghijklmnopqrstuvwxyz"  # 硬编码密钥

    query = f"SELECT * FROM users WHERE id={user_id}"  # SQL 注入风险

    return result
""",
    )

    print(f"\n✓ 检查 Artifact: {artifact.path}")
    result = engine.check([artifact], gate)

    if result.passed:
        print(f"\n✅ 检查通过！")
    else:
        print(f"\n❌ 检查失败！")
        print(f"  - 总检查数: {result.total_checks}")
        print(f"  - 失败数: {result.failed_checks}")
        print(f"\n发现的问题:")
        for check_result in result.check_results:
            if not check_result.passed:
                print(f"  [{check_result.severity.upper()}] {check_result.message}")

    return result


def demo_custom_checker():
    """自定义 Checker 示例"""
    print("\n" + "=" * 60)
    print("声明式规则 - 自定义 Checker")
    print("=" * 60)

    from harness.declarative_rules import register_checker
    from harness.types import CheckResult

    # 定义自定义 Checker
    class CopyrightChecker:
        """版权检查器"""
        name = "copyright_check"

        def check(self, artifact: Artifact, config: dict) -> CheckResult:
            if "Copyright" not in artifact.content and "©" not in artifact.content:
                return CheckResult(
                    passed=False,
                    severity=config.get("severity", "medium"),
                    message="Missing copyright notice",
                )
            return CheckResult(
                passed=True,
                severity=config.get("severity", "medium"),
                message="Copyright notice found",
            )

    # 注册
    register_checker(CopyrightChecker())
    print("\n✓ 注册自定义 Checker: copyright_check")
    print(f"  - 可用 Checker 列表: {list_checkers()}")


def main():
    """主函数"""
    print("\n🚀 声明式规则使用示例\n")

    # 1. 列出可用 Checker
    demo_list_checkers()

    # 2. 从 YAML 加载规则
    rules = demo_load_rules()

    # 3. 创建 Gate
    gate = demo_create_gate(rules)

    # 4. 检查干净的 Artifact
    demo_check_clean_artifact(gate)

    # 5. 检查有问题的 Artifact
    demo_check_dirty_artifact(gate)

    # 6. 自定义 Checker
    demo_custom_checker()

    print("\n" + "=" * 60)
    print("✅ 所有示例运行完成")
    print("=" * 60)
    print("\n💡 提示:")
    print("  - 声明式规则通过 YAML 配置，无需修改代码")
    print("  - 可以使用内置 Checker，也可以自定义")
    print("  - 规则可以动态加载和更新")
    print("\n📚 更多信息请查看 examples/declarative-rules/README.md")


if __name__ == "__main__":
    main()

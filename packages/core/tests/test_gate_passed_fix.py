"""
E-1 验收测试：GateEngine.passed 判断逻辑 bug fix

验收标准：
1. 4条检查3条失败1条通过 → passed=False（任何模式）
2. STRICT 下1条失败 → passed=False
3. LOOSE 下只有 low 失败 → passed=True
4. HYBRID 下有 high 失败 → passed=False
5. HYBRID 下只有 medium/low 失败 → passed=True
6. 无 escalated + 全部通过 → passed=True
7. escalated=True → passed=False（无论检查结果如何）
"""

import sys
import os

# 确保可以 import harness 包
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.gates import GateEngine, GateResult
from harness.types import (
    Artifact, GateDefinition, GateCheck, GateMode,
    CheckResult, RetryStrategy,
)


def _make_check_result(passed: bool, severity: str) -> CheckResult:
    """快速构造 CheckResult"""
    return CheckResult(
        passed=passed,
        severity=severity,
        message=f"Test check: passed={passed}, severity={severity}",
        auto_fixable=False,
    )


def _make_artifact(content: str = "safe content") -> Artifact:
    """快速构造 Artifact"""
    return Artifact(
        path="test.py",
        content=content,
        type="file",
    )


def test_effective_pass_strict_all_pass():
    """STRICT: 全部通过 → passed=True"""
    engine = GateEngine.__new__(GateEngine)  # 不触发 __init__ 的 bus subscribe
    results = [
        _make_check_result(True, "critical"),
        _make_check_result(True, "high"),
        _make_check_result(True, "medium"),
    ]
    assert engine._is_effective_pass(results, GateMode.STRICT) is True, \
        "STRICT: 全部通过应该 passed=True"


def test_effective_pass_strict_one_fail():
    """STRICT: 1条失败 → passed=False"""
    engine = GateEngine.__new__(GateEngine)
    results = [
        _make_check_result(True, "critical"),
        _make_check_result(False, "medium"),  # 1条 medium 失败
        _make_check_result(True, "high"),
    ]
    assert engine._is_effective_pass(results, GateMode.STRICT) is False, \
        "STRICT: 1条失败应该 passed=False"


def test_effective_pass_strict_most_fail():
    """STRICT: 4条检查3条失败1条通过 → passed=False"""
    engine = GateEngine.__new__(GateEngine)
    results = [
        _make_check_result(False, "critical"),
        _make_check_result(False, "high"),
        _make_check_result(False, "medium"),
        _make_check_result(True, "low"),
    ]
    assert engine._is_effective_pass(results, GateMode.STRICT) is False, \
        "STRICT: 4检查3失败1通过应该 passed=False"


def test_effective_pass_loose_no_critical_fail():
    """LOOSE: 只有 low 失败，无 critical 失败 → passed=True"""
    engine = GateEngine.__new__(GateEngine)
    results = [
        _make_check_result(True, "critical"),
        _make_check_result(False, "low"),  # low 失败不影响
        _make_check_result(False, "medium"),
    ]
    assert engine._is_effective_pass(results, GateMode.LOOSE) is True, \
        "LOOSE: 只有 medium/low 失败应该 passed=True"


def test_effective_pass_loose_critical_fail():
    """LOOSE: 有 critical 失败 → passed=False"""
    engine = GateEngine.__new__(GateEngine)
    results = [
        _make_check_result(False, "critical"),  # critical 失败
        _make_check_result(True, "low"),
    ]
    assert engine._is_effective_pass(results, GateMode.LOOSE) is False, \
        "LOOSE: 有 critical 失败应该 passed=False"


def test_effective_pass_hybrid_no_high_fail():
    """HYBRID: 只有 medium/low 失败，无 critical/high → passed=True"""
    engine = GateEngine.__new__(GateEngine)
    results = [
        _make_check_result(True, "critical"),
        _make_check_result(True, "high"),
        _make_check_result(False, "medium"),  # medium 失败不影响
        _make_check_result(False, "low"),
    ]
    assert engine._is_effective_pass(results, GateMode.HYBRID) is True, \
        "HYBRID: 只有 medium/low 失败应该 passed=True"


def test_effective_pass_hybrid_high_fail():
    """HYBRID: 有 high 失败 → passed=False"""
    engine = GateEngine.__new__(GateEngine)
    results = [
        _make_check_result(True, "critical"),
        _make_check_result(False, "high"),  # high 失败
        _make_check_result(True, "medium"),
    ]
    assert engine._is_effective_pass(results, GateMode.HYBRID) is False, \
        "HYBRID: 有 high 失败应该 passed=False"


def test_effective_pass_hybrid_critical_fail():
    """HYBRID: 有 critical 失败 → passed=False"""
    engine = GateEngine.__new__(GateEngine)
    results = [
        _make_check_result(False, "critical"),  # critical 失败
        _make_check_result(True, "medium"),
    ]
    assert engine._is_effective_pass(results, GateMode.HYBRID) is False, \
        "HYBRID: 有 critical 失败应该 passed=False"


def test_effective_pass_empty_results():
    """空检查结果 → passed=True（无失败项）"""
    engine = GateEngine.__new__(GateEngine)
    results = []
    assert engine._is_effective_pass(results, GateMode.STRICT) is True, \
        "STRICT: 空检查结果应该 passed=True（all() of empty = True）"


def test_effective_pass_all_pass():
    """所有模式：全部通过 → passed=True"""
    engine = GateEngine.__new__(GateEngine)
    results = [
        _make_check_result(True, "critical"),
        _make_check_result(True, "high"),
        _make_check_result(True, "medium"),
        _make_check_result(True, "low"),
    ]
    for mode in (GateMode.STRICT, GateMode.HYBRID, GateMode.LOOSE):
        assert engine._is_effective_pass(results, mode) is True, \
            f"{mode.value}: 全部通过应该 passed=True"


def test_bug_regression_4_checks_3_fail_1_pass():
    """回归测试：原 bug 场景——4检查3失败1通过→passed=False"""
    engine = GateEngine.__new__(GateEngine)
    results = [
        _make_check_result(False, "critical"),
        _make_check_result(False, "high"),
        _make_check_result(False, "medium"),
        _make_check_result(True, "low"),
    ]
    # 原代码 any(r.passed) 会返回 True（因为 low 通过了）
    # 修正后应该返回 False
    for mode in (GateMode.STRICT, GateMode.HYBRID, GateMode.LOOSE):
        result = engine._is_effective_pass(results, mode)
        assert result is False, \
            f"回归测试失败：{mode.value} 模式下 4检查3失败1通过应该是 False，但得到了 {result}"


# ─── 运行所有测试 ────────────────────────────────────────

def run_all_tests():
    tests = [
        test_effective_pass_strict_all_pass,
        test_effective_pass_strict_one_fail,
        test_effective_pass_strict_most_fail,
        test_effective_pass_loose_no_critical_fail,
        test_effective_pass_loose_critical_fail,
        test_effective_pass_hybrid_no_high_fail,
        test_effective_pass_hybrid_high_fail,
        test_effective_pass_hybrid_critical_fail,
        test_effective_pass_empty_results,
        test_effective_pass_all_pass,
        test_bug_regression_4_checks_3_fail_1_pass,
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

    print(f"\n结果：{passed} 通过，{failed} 失败")
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

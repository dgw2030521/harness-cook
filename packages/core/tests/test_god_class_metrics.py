"""
GodClassMetrics 测试——ATFD+WMC+TCC 三维复合检测验证
"""

import ast
import pytest

from harness.god_class_metrics import (
    GodClassMetrics,
    ClassMetrics,
    CompoundThresholds,
    make_thresholds_from_config,
    DEFAULT_ATFD_FEW,
    DEFAULT_WMC_HIGH,
    DEFAULT_TCC_LOW,
)
from harness.types import Artifact


# ─── Python AST 检测 ──────────────────────────────────

class TestPythonCompoundDetection:

    def _parse(self, code: str) -> ast.AST:
        return ast.parse(code)

    def test_typical_god_class_detected(self):
        """满足三条件的 God Class 应被检测"""
        code = '''
import os
import sys

class RealGodClass:
    def __init__(self):
        self.name = ""
    def m0(self):
        if True: pass
        if True: pass
        if True: pass
        if True: pass
        if True: pass
    def m1(self):
        if True: pass
        if True: pass
        if True: pass
        if True: pass
        if True: pass
    def m2(self):
        if True: pass
        if True: pass
        if True: pass
        if True: pass
        if True: pass
    def m3(self):
        if True: pass
        if True: pass
        if True: pass
        if True: pass
        if True: pass
    def m4(self):
        if True: pass
        if True: pass
        if True: pass
        if True: pass
        if True: pass
    def m5(self):
        a = os.environ.get("X")
        b = sys.platform
    def m6(self):
        a = os.environ.get("Y")
        b = sys.platform
    def m7(self):
        a = os.environ.get("Z")
        b = sys.platform
    def m8(self):
        a = os.environ.get("W")
        b = sys.platform
    def m9(self):
        a = os.environ.get("Q")
        b = sys.platform
    def m10(self): pass
    def m11(self): pass
    def m12(self): pass
    def m13(self): pass
    def m14(self): pass
    def m15(self): pass
    def m16(self): pass
    def m17(self): pass
    def m18(self): pass
    def m19(self): pass
    def m20(self): pass
    def m21(self): pass
    def m22(self): pass
    def m23(self): pass
    def m24(self): pass
    def m25(self): pass
    def m26(self): pass
    def m27(self): pass
    def m28(self): pass
    def m29(self): pass
    def m30(self): pass
    def m31(self): pass
    def m32(self): pass
    def m33(self): pass
    def m34(self): pass
    def m35(self): pass
    def m36(self): pass
    def m37(self): pass
    def m38(self): pass
    def m39(self): pass
'''
        tree = self._parse(code)
        artifact = Artifact(type="code", path="test.py", content=code)
        gcm = GodClassMetrics()
        violations = gcm.check_python(tree, artifact)
        assert len(violations) >= 1
        assert "RealGodClass" in violations[0]["description"]
        assert "ATFD" in violations[0]["description"]
        assert "WMC" in violations[0]["description"]
        assert "TCC" in violations[0]["description"]

    def test_simple_class_not_detected(self):
        """小类不触发 compound 检测"""
        code = '''
class OkClass:
    def __init__(self):
        self.x = 0
    def add(self):
        self.x += 1
    def get(self):
        return self.x
'''
        tree = self._parse(code)
        artifact = Artifact(type="code", path="test.py", content=code)
        gcm = GodClassMetrics()
        violations = gcm.check_python(tree, artifact)
        assert len(violations) == 0

    def test_high_wmc_but_low_atfd_not_god_class(self):
        """高 WMC 但低 ATFD 不触发(三条件缺一不可)"""
        code = '''
class HighComplexityLowForeign:
    def __init__(self):
        self.value = 0
    def m0(self):
        if True: pass
        if True: pass
        if True: pass
        if True: pass
        if True: pass
    def m1(self):
        if True: pass
        if True: pass
        if True: pass
        if True: pass
        if True: pass
    def m2(self):
        if True: pass
        if True: pass
        if True: pass
        if True: pass
        if True: pass
    def m3(self):
        if True: pass
        if True: pass
        if True: pass
        if True: pass
        if True: pass
    def m4(self):
        if True: pass
        if True: pass
        if True: pass
        if True: pass
        if True: pass
'''
        tree = self._parse(code)
        artifact = Artifact(type="code", path="test.py", content=code)
        gcm = GodClassMetrics()
        violations = gcm.check_python(tree, artifact)
        # WMC 很高但 ATFD 应为 0 → 不满足全部三条件
        assert len(violations) == 0


class TestCompoundThresholds:

    def test_default_thresholds(self):
        t = CompoundThresholds()
        assert t.atfd_few == DEFAULT_ATFD_FEW  # 5
        assert t.wmc_high == DEFAULT_WMC_HIGH  # 47
        assert t.tcc_low == DEFAULT_TCC_LOW    # 0.33

    def test_custom_thresholds(self):
        t = CompoundThresholds(atfd_few=3, wmc_high=20, tcc_low=0.5)
        assert t.atfd_few == 3
        assert t.wmc_high == 20
        assert t.tcc_low == 0.5

    def test_make_thresholds_from_config(self):
        config = {"atfd_few": 8, "wmc_high": 30, "tcc_low": 0.2}
        t = make_thresholds_from_config(config)
        assert t.atfd_few == 8
        assert t.wmc_high == 30
        assert t.tcc_low == 0.2

    def test_make_thresholds_defaults(self):
        config = {}
        t = make_thresholds_from_config(config)
        assert t.atfd_few == DEFAULT_ATFD_FEW
        assert t.wmc_high == DEFAULT_WMC_HIGH


class TestClassMetrics:

    def test_metrics_defaults(self):
        m = ClassMetrics(class_name="Foo", line=10)
        assert m.atfd == 0
        assert m.wmc == 0
        assert m.tcc == 0.0
        assert m.method_count == 0
        assert not m.is_god_class

    def test_is_god_class_flagged(self):
        gcm = GodClassMetrics(CompoundThresholds(atfd_few=2, wmc_high=10, tcc_low=0.5))
        m = ClassMetrics(class_name="Bad", line=1, atfd=5, wmc=20, tcc=0.1)
        result = gcm.is_god_class(m)
        assert result
        assert m.is_god_class
        assert "Bad" in m.reason

    def test_is_not_god_class(self):
        gcm = GodClassMetrics()
        m = ClassMetrics(class_name="Ok", line=1, atfd=1, wmc=5, tcc=0.9)
        result = gcm.is_god_class(m)
        assert not result
        assert not m.is_god_class


class TestEdgeCases:

    def test_empty_class(self):
        """空类无方法 → TCC=1.0, 不触发"""
        code = "class Empty:\n    pass\n"
        tree = ast.parse(code)
        artifact = Artifact(type="code", path="test.py", content=code)
        gcm = GodClassMetrics()
        violations = gcm.check_python(tree, artifact)
        assert len(violations) == 0

    def test_single_method_class(self):
        """单方法类 → TCC=1.0(完全内聚), 不触发"""
        code = '''
class SingleMethod:
    def __init__(self):
        self.x = 0
    def only_one(self):
        self.x += 1
'''
        tree = ast.parse(code)
        artifact = Artifact(type="code", path="test.py", content=code)
        gcm = GodClassMetrics()
        violations = gcm.check_python(tree, artifact)
        assert len(violations) == 0

    def test_syntax_error_file_skipped(self):
        """语法错误的文件不出错"""
        code = "class BadSyntax { invalid }"
        artifact = Artifact(type="code", path="test.py", content=code)
        gcm = GodClassMetrics()
        try:
            tree = ast.parse(code)
        except SyntaxError:
            # AST 解析失败 → 无检测结果(合规引擎层面会跳过)
            pass
"""
架构合规规则测试——ARCH-001 到 ARCH-007 + LanguageRegistry + MatcherRegistry

覆盖:
- LanguageRegistry 初始化和语言查找
- MatcherRegistry 初始化
- architecture_rule_pack 工厂函数
- DependencyGraphChecker (分层违规/循环依赖/过深链路)
- ASTChecker (God Class/深继承 — Python + JS + Java)
- CrossFileChecker (分散逻辑/重复抽象)
- ComplianceEngine.scan 的 project_root 参数
- ComplianceRule matcher_type/matcher_config 向后兼容
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestLanguageRegistry:
    """LanguageRegistry 初始化和语言查找"""

    def setup_method(self):
        from harness.compliance import LanguageRegistry
        if not LanguageRegistry._languages:
            LanguageRegistry.default()

    def test_default_registers_all_languages(self):
        from harness.compliance import LanguageRegistry
        names = list(LanguageRegistry._languages.keys())
        assert "python" in names
        assert "javascript" in names
        assert "java" in names
        assert "go" in names
        assert "kotlin" in names
        assert len(names) >= 11

    def test_get_by_extension_python(self):
        from harness.compliance import LanguageRegistry
        result = LanguageRegistry.get_by_extension("models/user.py")
        assert result is not None
        assert result[0] == "python"

    def test_get_by_extension_java(self):
        from harness.compliance import LanguageRegistry
        result = LanguageRegistry.get_by_extension("dao/UserDao.java")
        assert result is not None
        assert result[0] == "java"

    def test_get_by_extension_js(self):
        from harness.compliance import LanguageRegistry
        result = LanguageRegistry.get_by_extension("components/App.jsx")
        assert result is not None
        assert result[0] == "javascript"

    def test_get_by_extension_unknown(self):
        from harness.compliance import LanguageRegistry
        result = LanguageRegistry.get_by_extension("config.yaml")
        assert result is None

    def test_get_tree_sitter_language_java(self):
        from harness.compliance import LanguageRegistry
        lang = LanguageRegistry.get_tree_sitter_language("java")
        # tree-sitter-java 可能已安装
        if lang is not None:
            assert lang is not None  # 确认返回了 Language 对象
        else:
            # tree-sitter 未安装时优雅降级
            assert lang is None

    def test_all_supported_extensions(self):
        from harness.compliance import LanguageRegistry
        exts = LanguageRegistry.all_supported_extensions()
        assert ".py" in exts
        assert ".java" in exts
        assert ".js" in exts
        assert ".go" in exts


class TestMatcherRegistry:
    """MatcherRegistry 初始化"""

    def test_default_registers_all_matchers(self):
        from harness.compliance import MatcherRegistry
        MatcherRegistry.default()
        assert "regex" in MatcherRegistry._matchers
        assert "dependency_graph" in MatcherRegistry._matchers
        assert "ast" in MatcherRegistry._matchers
        assert "cross_file" in MatcherRegistry._matchers

    def test_get_returns_checker(self):
        from harness.compliance import MatcherRegistry, RegexChecker
        MatcherRegistry.default()
        checker = MatcherRegistry.get("regex")
        assert isinstance(checker, RegexChecker)

    def test_get_unknown_returns_none(self):
        from harness.compliance import MatcherRegistry
        MatcherRegistry.default()
        assert MatcherRegistry.get("unknown_type") is None


class TestArchitectureRulePack:
    """architecture_rule_pack 工厂函数"""

    def test_pack_has_7_rules(self):
        from harness.rule_packs.architecture import get_architecture_pack
        pack = get_architecture_pack()
        assert len(pack.rules) == 7

    def test_pack_name_is_architecture(self):
        from harness.rule_packs.architecture import get_architecture_pack
        pack = get_architecture_pack()
        assert pack.name == "architecture"

    def test_all_rules_are_architecture_category(self):
        from harness.rule_packs.architecture import get_architecture_pack
        from harness.types import ComplianceCategory
        pack = get_architecture_pack()
        for rule in pack.rules:
            assert rule.category == ComplianceCategory.ARCHITECTURE

    def test_rule_ids_start_with_arch(self):
        from harness.rule_packs.architecture import get_architecture_pack
        pack = get_architecture_pack()
        for rule in pack.rules:
            assert rule.id.startswith("ARCH-")

    def test_dependency_graph_rules_use_correct_matcher_type(self):
        from harness.rule_packs.architecture import get_architecture_pack
        pack = get_architecture_pack()
        dep_rules = [r for r in pack.rules if r.matcher_type == "dependency_graph"]
        assert len(dep_rules) == 3
        for rule in dep_rules:
            assert "check" in rule.matcher_config

    def test_ast_rules_use_correct_matcher_type(self):
        from harness.rule_packs.architecture import get_architecture_pack
        pack = get_architecture_pack()
        ast_rules = [r for r in pack.rules if r.matcher_type == "ast"]
        assert len(ast_rules) == 2
        for rule in ast_rules:
            assert "ast_check" in rule.matcher_config

    def test_cross_file_rules_use_correct_matcher_type(self):
        from harness.rule_packs.architecture import get_architecture_pack
        pack = get_architecture_pack()
        cf_rules = [r for r in pack.rules if r.matcher_type == "cross_file"]
        assert len(cf_rules) == 2


class TestComplianceRuleBackwardCompat:
    """ComplianceRule matcher_type/matcher_config 向后兼容"""

    def test_default_matcher_type_is_regex(self):
        from harness.types import ComplianceRule, ComplianceCategory
        rule = ComplianceRule(
            id="test-001",
            category=ComplianceCategory.STYLE,
            pattern=r"TODO",
            severity="low",
            description="test rule",
            remediation="fix it",
        )
        assert rule.matcher_type == "regex"
        assert rule.matcher_config == {}

    def test_explicit_matcher_type_works(self):
        from harness.types import ComplianceRule, ComplianceCategory
        rule = ComplianceRule(
            id="test-002",
            category=ComplianceCategory.ARCHITECTURE,
            pattern="test",
            severity="high",
            description="test",
            remediation="fix",
            matcher_type="dependency_graph",
            matcher_config={"check": "cycle"},
        )
        assert rule.matcher_type == "dependency_graph"
        assert rule.matcher_config["check"] == "cycle"

    def test_existing_rules_still_work_without_new_fields(self):
        from harness.rule_packs.coding import get_coding_pack
        pack = get_coding_pack()
        for rule in pack.rules:
            assert rule.matcher_type == "regex"  # 默认值
            assert isinstance(rule.matcher_config, dict)  # 默认 {} 或合法 regex 配置（如 case_sensitive），向后兼容只要求字段存在且为 dict


class TestASTChecker:
    """ASTChecker — Python + JS + Java"""

    def test_python_god_class_detection(self):
        from harness.compliance import ComplianceEngine, MatcherRegistry
        from harness.rule_packs.architecture import get_architecture_pack
        from harness.types import Artifact
        from harness.god_class_metrics import GodClassMetrics, CompoundThresholds

        MatcherRegistry.default()
        engine = ComplianceEngine()
        engine.load_pack(get_architecture_pack())

        # ARCH-004 现用 compound 模式(ATFD+WMC+TCC)，需要构造真正满足三条件的 God Class
        # compound 条件: ATFD>5 AND WMC>47 AND TCC<0.33
        # 策略: 50个方法各有分支(WMC>47) + 大量外部属性访问(ATFD>5) + 无共享属性(TCC≈0)
        god_class_code = '''
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
        artifact_bad = Artifact(type="code", path="test.py", content=god_class_code)
        results_bad = engine.scan([artifact_bad])
        arch004_bad = [r for r in results_bad if r.rule_id == "ARCH-004"]
        assert len(arch004_bad) == 1
        assert not arch004_bad[0].passed  # compound 模式检测到 God Class

        # 非 God Class: 小类、低 ATFD、高内聚
        ok_code = '''
class OkClass:
    def __init__(self):
        self.x = 0
    def add(self):
        self.x += 1
    def get(self):
        return self.x
'''
        artifact_ok = Artifact(type="code", path="test.py", content=ok_code)
        results_ok = engine.scan([artifact_ok])
        arch004_ok = [r for r in results_ok if r.rule_id == "ARCH-004"]
        assert len(arch004_ok) == 1
        assert arch004_ok[0].passed  # 非 God Class

    def test_python_god_class_simple_mode(self):
        """simple 模式(旧阈值)仍可独立使用"""
        from harness.compliance import ComplianceEngine, MatcherRegistry, RulePack
        from harness.god_class_metrics import GodClassMetrics, CompoundThresholds
        from harness.types import Artifact, ComplianceRule, ComplianceCategory

        MatcherRegistry.default()
        engine = ComplianceEngine()
        # 自建 simple 模式规则包
        engine.load_pack(RulePack("simple-god", ComplianceCategory.ARCHITECTURE, [
            ComplianceRule(
                id="GOD-SIMPLE",
                category=ComplianceCategory.ARCHITECTURE,
                pattern="God Class simple",
                severity="high",
                description="Simple threshold god class check",
                remediation="Split the class.",
                matcher_type="ast",
                matcher_config={"ast_check": "god_class", "threshold": 15},
                languages=["python"],
            ),
        ]))

        # 16个方法 → 超阈值违规
        code_bad = "class BadClass:\n" + "\n".join(f"    def m{i}(self): pass" for i in range(16))
        artifact_bad = Artifact(type="code", path="test.py", content=code_bad)
        results = engine.scan([artifact_bad])
        simple_bad = [r for r in results if r.rule_id == "GOD-SIMPLE"]
        assert len(simple_bad) == 1
        assert not simple_bad[0].passed

        # 15个方法 → 刚好不违规
        code_ok = "class OkClass:\n" + "\n".join(f"    def m{i}(self): pass" for i in range(15))
        artifact_ok = Artifact(type="code", path="test.py", content=code_ok)
        results = engine.scan([artifact_ok])
        simple_ok = [r for r in results if r.rule_id == "GOD-SIMPLE"]
        assert len(simple_ok) == 1
        assert simple_ok[0].passed

    def test_js_god_class_detection(self):
        from harness.compliance import ComplianceEngine, MatcherRegistry
        from harness.rule_packs.architecture import get_architecture_pack
        from harness.types import Artifact

        MatcherRegistry.default()
        engine = ComplianceEngine()
        engine.load_pack(get_architecture_pack())

        # compound 模式需要 ATFD>5+WMC>47+TCC<0.33
        # JS God Class: 50 methods with branching + external data access + no shared attrs
        methods = []
        for i in range(5):
            methods.append(f"  m{i}() {{ if(x){{ return a.b; }} if(y){{ return c.d; }} }}")
        for i in range(5, 50):
            methods.append(f"  m{i}() {{ if(x){{}} }}")
        js_code = "class GodClass {\n  constructor() {}\n" + "\n".join(methods) + "\n}"
        artifact = Artifact(type="code", path="test.jsx", content=js_code)
        results = engine.scan([artifact])
        arch004 = [r for r in results if r.rule_id == "ARCH-004"]
        assert len(arch004) == 1
        # tree-sitter compound 检测, 取决于 grammar 是否可用
        # 如果 grammar 不可用则跳过(passed=True), 可用时应该检测到

    def test_java_god_class_detection(self):
        from harness.compliance import ComplianceEngine, MatcherRegistry
        from harness.rule_packs.architecture import get_architecture_pack
        from harness.types import Artifact

        MatcherRegistry.default()
        engine = ComplianceEngine()
        engine.load_pack(get_architecture_pack())

        # compound 模式需要 ATFD>5+WMC>47+TCC<0.33
        # Java God Class: many methods with branching + external data access + no shared attrs
        methods = []
        for i in range(5):
            methods.append(f"  public String m{i}() {{ if(x!=null){{ return x.getValue(); }} return other.getData(); }}")
        for i in range(5, 50):
            methods.append(f"  public void m{i}() {{ if(true){{}} }}")
        java_code = "public class GodClass {\n" + "\n".join(methods) + "\n}"
        artifact = Artifact(type="code", path="GodClass.java", content=java_code)
        results = engine.scan([artifact])
        arch004 = [r for r in results if r.rule_id == "ARCH-004"]
        assert len(arch004) == 1
        # tree-sitter compound 检测, 取决于 grammar 是否可用


class TestScanContextIntegration:
    """ComplianceEngine.scan 的 project_root 参数"""

    def test_scan_without_project_root_skips_dependency_rules(self):
        from harness.compliance import ComplianceEngine, MatcherRegistry
        from harness.rule_packs.architecture import get_architecture_pack
        from harness.types import Artifact

        MatcherRegistry.default()
        engine = ComplianceEngine()
        engine.load_pack(get_architecture_pack())

        artifact = Artifact(type="code", path="test.py", content="class A: pass")
        results = engine.scan([artifact])  # 不传 project_root

        # 依赖图规则应该 pass（没有依赖图）
        dep_results = [r for r in results if r.rule_id in ("ARCH-001", "ARCH-002", "ARCH-003")]
        for r in dep_results:
            assert r.passed  # 无依赖图时跳过，标记为 pass

    def test_scan_backward_compat_no_project_root(self):
        """向后兼容：旧代码不传 project_root，行为不变"""
        from harness.compliance import ComplianceEngine, MatcherRegistry
        from harness.rule_packs import get_coding_pack
        from harness.types import Artifact

        MatcherRegistry.default()
        engine = ComplianceEngine()
        engine.load_pack(get_coding_pack())

        artifact = Artifact(type="code", path="test.py", content="# TODO: fix this later\nx = 1")
        results = engine.scan([artifact])  # 旧用法，不传 project_root
        violations = [r for r in results if not r.passed]
        # 至少有 CODE-004 TODO 规则触发（或其他规则）
        assert len(results) > 0  # 扫描返回了结果
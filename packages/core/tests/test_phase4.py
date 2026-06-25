"""
Phase 4 测试: Validator + 影响分析适配层

从 nextX IValidator/IImpactAnalyzer 提取的设计模式,
在 harness-cook 中适配为 Python 实现。

测试覆盖:
- IssueSeverity: 4级枚举
- RequirementPriority: must/should/could
- CodeLocation: 构造+display
- ValidationIssue: 构造+is_blocking
- Requirement: is_mandatory
- ChangeDescription: is_destructive
- ValidationContext: has_destructive_changes/affected_files/mandatory_requirements
- ValidationResult: blocking_issues/warnings/auto_fixable/summary
- ValidatorRegistry: register/unregister/run_validation/run_auto_fix/judge_results
- DestructiveChangeValidator: validate+auto_fix
- MaxChangesValidator: validate+auto_fix
- DependencyNode: add_dependency/add_dependent
- CallGraphNode: 构造
- ImpactRisk: 构造
- ImpactAnalysis: summary/total_impact_count
- DependencyGraph: add_node/add_edge/get_dependencies/get_dependents/get_transitive_dependents/entry_points
- FileImpactAnalyzer: build_graph/analyze_impact/get_dependencies
"""

import unittest
import os
import tempfile
import shutil
from harness.validator_types import (
    IssueSeverity, RequirementPriority,
    CodeLocation, ValidationIssue, Requirement,
    ChangeDescription, ValidationContext, ValidationResult,
    ValidatorRegistry, DestructiveChangeValidator, MaxChangesValidator,
    get_validator_registry,
)
from harness.impact_types import (
    ImpactRiskLevel, DependencyNode, CallGraphNode,
    ImpactRisk, ImpactAnalysis, DependencyGraph,
    FileImpactAnalyzer, get_impact_analyzer,
)


class TestIssueSeverity(unittest.TestCase):
    """4级严重度枚举"""

    def test_all_severities(self):
        severities = list(IssueSeverity)
        assert len(severities) == 4
        assert IssueSeverity.CRITICAL.value == "critical"
        assert IssueSeverity.HIGH.value == "high"
        assert IssueSeverity.MEDIUM.value == "medium"
        assert IssueSeverity.LOW.value == "low"


class TestRequirementPriority(unittest.TestCase):
    """需求优先级枚举"""

    def test_all_priorities(self):
        priorities = list(RequirementPriority)
        assert len(priorities) == 3
        assert RequirementPriority.MUST.value == "must"
        assert RequirementPriority.SHOULD.value == "should"
        assert RequirementPriority.COULD.value == "could"


class TestCodeLocation(unittest.TestCase):
    """代码定位"""

    def test_basic_location(self):
        loc = CodeLocation(file_path="src/main.py", line_number=42)
        assert loc.file_path == "src/main.py"
        assert loc.line_number == 42

    def test_display(self):
        loc = CodeLocation(file_path="src/main.py", line_number=42, symbol_name="run()")
        display = loc.display()
        assert "src/main.py" in display
        assert "42" in display
        assert "run()" in display

    def test_display_no_line(self):
        loc = CodeLocation(file_path="src/main.py")
        assert loc.display() == "src/main.py"


class TestValidationIssue(unittest.TestCase):
    """验证问题"""

    def test_creation(self):
        issue = ValidationIssue(
            rule_id="destructive-change:large-delete",
            severity=IssueSeverity.CRITICAL,
            message="破坏性变更",
            autoFixable=False,
        )
        assert issue.rule_id == "destructive-change:large-delete"
        assert issue.severity == IssueSeverity.CRITICAL
        assert issue.autoFixable is False

    def test_is_blocking(self):
        critical = ValidationIssue(severity=IssueSeverity.CRITICAL)
        high = ValidationIssue(severity=IssueSeverity.HIGH)
        medium = ValidationIssue(severity=IssueSeverity.MEDIUM)
        low = ValidationIssue(severity=IssueSeverity.LOW)
        assert critical.is_blocking() is True
        assert high.is_blocking() is True
        assert medium.is_blocking() is False
        assert low.is_blocking() is False

    def test_auto_fixable(self):
        issue = ValidationIssue(autoFixable=True, fix_hint="减少删除范围")
        assert issue.autoFixable is True
        assert issue.fix_hint == "减少删除范围"


class TestRequirement(unittest.TestCase):
    """验证需求"""

    def test_mandatory(self):
        req = Requirement(priority=RequirementPriority.MUST)
        assert req.is_mandatory() is True

    def test_not_mandatory(self):
        req = Requirement(priority=RequirementPriority.SHOULD)
        assert req.is_mandatory() is False

    def test_with_criteria(self):
        req = Requirement(
            id="REQ-001",
            title="安全验证",
            acceptance_criteria=["不得删除超过50行"],
        )
        assert len(req.acceptance_criteria) == 1


class TestChangeDescription(unittest.TestCase):
    """变更描述"""

    def test_is_destructive_delete(self):
        change = ChangeDescription(file_path="a.py", change_type="delete")
        assert change.is_destructive() is True

    def test_is_destructive_large_removal(self):
        change = ChangeDescription(file_path="a.py", lines_removed=100)
        assert change.is_destructive() is True

    def test_not_destructive(self):
        change = ChangeDescription(file_path="a.py", change_type="modify", lines_removed=10)
        assert change.is_destructive() is False


class TestValidationContext(unittest.TestCase):
    """验证上下文"""

    def test_has_destructive_changes(self):
        ctx = ValidationContext(
            changes=[
                ChangeDescription(file_path="a.py", change_type="delete"),
                ChangeDescription(file_path="b.py", change_type="modify"),
            ]
        )
        assert ctx.has_destructive_changes() is True

    def test_no_destructive_changes(self):
        ctx = ValidationContext(
            changes=[ChangeDescription(file_path="a.py", change_type="modify")]
        )
        assert ctx.has_destructive_changes() is False

    def test_affected_files(self):
        ctx = ValidationContext(
            changes=[
                ChangeDescription(file_path="a.py"),
                ChangeDescription(file_path="b.py"),
            ]
        )
        assert ctx.affected_files() == ["a.py", "b.py"]

    def test_mandatory_requirements(self):
        ctx = ValidationContext(
            requirements=[
                Requirement(priority=RequirementPriority.MUST),
                Requirement(priority=RequirementPriority.SHOULD),
            ]
        )
        musts = ctx.mandatory_requirements()
        assert len(musts) == 1


class TestValidationResult(unittest.TestCase):
    """验证结果"""

    def test_pass(self):
        result = ValidationResult(validator_id="test", passed=True)
        assert result.passed is True

    def test_blocking_issues(self):
        result = ValidationResult(
            validator_id="test",
            passed=False,
            issues=[
                ValidationIssue(severity=IssueSeverity.CRITICAL),
                ValidationIssue(severity=IssueSeverity.MEDIUM),
            ]
        )
        assert len(result.blocking_issues()) == 1

    def test_warnings(self):
        result = ValidationResult(
            issues=[ValidationIssue(severity=IssueSeverity.MEDIUM)]
        )
        assert len(result.warnings()) == 1

    def test_auto_fixable_issues(self):
        result = ValidationResult(
            issues=[
                ValidationIssue(autoFixable=True),
                ValidationIssue(autoFixable=False),
            ]
        )
        assert len(result.auto_fixable_issues()) == 1

    def test_summary(self):
        result = ValidationResult(
            validator_id="test-validator",
            passed=True,
            issues=[ValidationIssue(severity=IssueSeverity.LOW)],
        )
        s = result.summary()
        assert "PASS" in s
        assert "test-validator" in s


class TestValidatorRegistry(unittest.TestCase):
    """Validator注册器"""

    def test_register_and_list(self):
        registry = ValidatorRegistry()
        v = DestructiveChangeValidator()
        registry.register_validator(v)
        assert v.id() in registry.list_validators()

    def test_unregister(self):
        registry = ValidatorRegistry()
        v = DestructiveChangeValidator()
        registry.register_validator(v)
        assert registry.unregister_validator(v.id()) is True
        assert v.id() not in registry.list_validators()

    def test_unregister_nonexistent(self):
        registry = ValidatorRegistry()
        assert registry.unregister_validator("no-such") is False

    def test_run_validation(self):
        registry = ValidatorRegistry()
        registry.register_validator(DestructiveChangeValidator())
        ctx = ValidationContext(
            changes=[ChangeDescription(file_path="a.py", change_type="delete")]
        )
        results = registry.run_validation(ctx)
        assert len(results) == 1
        assert results[0].passed is False

    def test_run_validation_pass(self):
        registry = ValidatorRegistry()
        registry.register_validator(DestructiveChangeValidator())
        ctx = ValidationContext(
            changes=[ChangeDescription(file_path="a.py", change_type="modify")]
        )
        results = registry.run_validation(ctx)
        assert len(results) == 1
        assert results[0].passed is True

    def test_run_auto_fix(self):
        registry = ValidatorRegistry()
        registry.register_validator(DestructiveChangeValidator())
        ctx = ValidationContext()
        issues = [ValidationIssue(
            rule_id="destructive-change:large-delete",
            autoFixable=False,
        )]
        results = registry.run_auto_fix(ctx, issues)
        # 破坏性变更不可autoFix → auto_fixable=False不触发修复
        assert len(results) == 0

    def test_judge_results_pass(self):
        registry = ValidatorRegistry()
        results = [ValidationResult(validator_id="test", passed=True)]
        assert registry.judge_results(results) is True

    def test_judge_results_fail(self):
        registry = ValidatorRegistry()
        results = [ValidationResult(
            validator_id="test",
            passed=False,
            issues=[ValidationIssue(severity=IssueSeverity.CRITICAL)],
        )]
        assert registry.judge_results(results) is False

    def test_stats(self):
        registry = ValidatorRegistry()
        registry.register_validator(DestructiveChangeValidator())
        stats = registry.stats()
        assert stats["total_validators"] == 1

    def test_multiple_validators(self):
        registry = ValidatorRegistry()
        registry.register_validator(DestructiveChangeValidator())
        registry.register_validator(MaxChangesValidator())
        ctx = ValidationContext(
            changes=[ChangeDescription(file_path="a.py", change_type="modify")]
        )
        results = registry.run_validation(ctx)
        assert len(results) == 2


class TestDestructiveChangeValidator(unittest.TestCase):
    """破坏性变更检测Validator"""

    def test_detect_delete(self):
        v = DestructiveChangeValidator()
        ctx = ValidationContext(
            changes=[ChangeDescription(file_path="a.py", change_type="delete")]
        )
        result = v.validate(ctx)
        assert result.passed is False
        assert len(result.issues) == 1

    def test_pass_modify(self):
        v = DestructiveChangeValidator()
        ctx = ValidationContext(
            changes=[ChangeDescription(file_path="a.py", change_type="modify")]
        )
        result = v.validate(ctx)
        assert result.passed is True
        assert len(result.issues) == 0

    def test_detect_large_removal(self):
        v = DestructiveChangeValidator()
        ctx = ValidationContext(
            changes=[ChangeDescription(file_path="a.py", lines_removed=100)]
        )
        result = v.validate(ctx)
        assert result.passed is False


class TestMaxChangesValidator(unittest.TestCase):
    """变更数量限制Validator"""

    def test_within_limits(self):
        v = MaxChangesValidator(max_changes=50, max_files=10)
        ctx = ValidationContext(
            changes=[ChangeDescription(file_path="a.py", lines_added=5)]
        )
        result = v.validate(ctx)
        assert result.passed is True

    def test_exceed_lines(self):
        v = MaxChangesValidator(max_changes=10)
        ctx = ValidationContext(
            changes=[ChangeDescription(file_path="a.py", lines_added=50)]
        )
        result = v.validate(ctx)
        assert len(result.issues) >= 1
        assert any("变更行数超限" in i.message for i in result.issues)

    def test_exceed_files(self):
        v = MaxChangesValidator(max_changes=1000, max_files=2)
        ctx = ValidationContext(
            changes=[
                ChangeDescription(file_path="a.py"),
                ChangeDescription(file_path="b.py"),
                ChangeDescription(file_path="c.py"),
            ]
        )
        result = v.validate(ctx)
        assert any("变更文件数超限" in i.message for i in result.issues)


class TestDependencyNode(unittest.TestCase):
    """依赖图节点"""

    def test_add_dependency(self):
        node = DependencyNode(id="main.py")
        node.add_dependency("utils.py")
        assert "utils.py" in node.dependencies

    def test_add_dependent(self):
        node = DependencyNode(id="utils.py")
        node.add_dependent("main.py")
        assert "main.py" in node.dependents

    def test_entry_point(self):
        node = DependencyNode(id="main.py", is_entry_point=True)
        assert node.is_entry_point is True


class TestCallGraphNode(unittest.TestCase):
    """调用图节点"""

    def test_creation(self):
        node = CallGraphNode(id="main.py", calls={"utils.py"})
        assert "utils.py" in node.calls


class TestImpactRisk(unittest.TestCase):
    """影响风险"""

    def test_high_requires_review(self):
        risk = ImpactRisk(level=ImpactRiskLevel.HIGH, requires_review=True)
        assert risk.requires_review is True

    def test_low_no_review(self):
        risk = ImpactRisk(level=ImpactRiskLevel.LOW)
        assert risk.requires_review is False


class TestImpactAnalysis(unittest.TestCase):
    """影响分析结果"""

    def test_total_impact_count(self):
        analysis = ImpactAnalysis(
            change_files=["a.py"],
            direct_impacts=["b.py", "c.py"],
            indirect_impacts=["d.py"],
        )
        assert analysis.total_impact_count() == 3

    def test_summary(self):
        analysis = ImpactAnalysis(
            change_files=["a.py"],
            direct_impacts=["b.py"],
            risk=ImpactRisk(level=ImpactRiskLevel.MEDIUM),
        )
        s = analysis.summary()
        assert "medium" in s
        assert "1" in s

    def test_requires_review(self):
        analysis = ImpactAnalysis(
            risk=ImpactRisk(level=ImpactRiskLevel.HIGH, requires_review=True),
            requires_review=True,
        )
        assert analysis.requires_review is True


class TestDependencyGraph(unittest.TestCase):
    """依赖图"""

    def test_add_node(self):
        graph = DependencyGraph()
        node = graph.add_node("main.py")
        assert node.id == "main.py"

    def test_add_edge(self):
        graph = DependencyGraph()
        graph.add_edge("main.py", "utils.py")
        deps = graph.get_dependencies("main.py")
        assert "utils.py" in deps
        dependents = graph.get_dependents("utils.py")
        assert "main.py" in dependents

    def test_get_node(self):
        graph = DependencyGraph()
        graph.add_node("main.py")
        node = graph.get_node("main.py")
        assert node is not None
        assert node.id == "main.py"

    def test_transitive_dependents(self):
        graph = DependencyGraph()
        graph.add_edge("main.py", "utils.py")
        graph.add_edge("app.py", "main.py")
        graph.add_edge("test.py", "app.py")
        
        # utils.py变更 → main.py受影响(直接) → app.py(间接) → test.py(间接)
        transitive = graph.get_transitive_dependents("utils.py", max_depth=3)
        assert "main.py" in transitive
        assert "app.py" in transitive
        assert "test.py" in transitive

    def test_entry_points(self):
        graph = DependencyGraph()
        graph.add_node("main.py", is_entry_point=True)
        graph.add_node("utils.py")
        entries = graph.entry_points()
        assert "main.py" in entries

    def test_stats(self):
        graph = DependencyGraph()
        graph.add_edge("main.py", "utils.py")
        stats = graph.stats()
        assert stats["total_nodes"] == 2
        assert stats["total_edges"] == 1


class TestFileImpactAnalyzer(unittest.TestCase):
    """文件级影响分析器"""

    def test_analyze_impact_simple(self):
        analyzer = FileImpactAnalyzer()
        # 手动构建简单依赖图
        graph = analyzer.get_graph()
        graph.add_edge("app.py", "utils.py")
        graph.add_edge("main.py", "app.py")
        analyzer._built = True
        
        # utils.py变更 → app.py受影响(直接) → main.py(间接)
        result = analyzer.analyze_impact(["utils.py"])
        assert "app.py" in result.direct_impacts
        assert result.risk.level in (ImpactRiskLevel.MEDIUM, ImpactRiskLevel.HIGH)

    def test_analyze_impact_low_risk(self):
        analyzer = FileImpactAnalyzer()
        graph = analyzer.get_graph()
        graph.add_node("isolated.py")
        analyzer._built = True
        
        result = analyzer.analyze_impact(["isolated.py"])
        assert result.risk.level == ImpactRiskLevel.LOW

    def test_analyze_impact_entry_point(self):
        analyzer = FileImpactAnalyzer()
        graph = analyzer.get_graph()
        graph.add_node("main.py", is_entry_point=True)
        graph.add_edge("app.py", "main.py")
        analyzer._built = True
        
        result = analyzer.analyze_impact(["main.py"])
        # 入口文件变更 → HIGH risk
        assert result.risk.level == ImpactRiskLevel.HIGH
        assert result.requires_review is True

    def test_get_dependencies(self):
        analyzer = FileImpactAnalyzer()
        graph = analyzer.get_graph()
        graph.add_edge("app.py", "utils.py")
        analyzer._built = True
        
        node = analyzer.get_dependencies("app.py")
        assert "utils.py" in node.dependencies

    def test_get_call_graph(self):
        analyzer = FileImpactAnalyzer()
        graph = analyzer.get_graph()
        graph.add_edge("app.py", "utils.py")
        analyzer._built = True
        
        node = analyzer.get_call_graph("app.py")
        assert "utils.py" in node.calls

    def test_stats(self):
        analyzer = FileImpactAnalyzer()
        assert analyzer.stats()["built"] is False


class TestGetValidatorRegistry(unittest.TestCase):
    """全局Validator注册器工厂"""

    def test_get_registry_with_defaults(self):
        registry = get_validator_registry()
        assert len(registry.list_validators()) >= 2  # DestructiveChange + MaxChanges


class TestGetImpactAnalyzer(unittest.TestCase):
    """全局影响分析器工厂"""

    def test_get_analyzer(self):
        analyzer = get_impact_analyzer("/tmp/test_project")
        assert isinstance(analyzer, FileImpactAnalyzer)


if __name__ == "__main__":
    unittest.main()
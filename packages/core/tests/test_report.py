"""
可视化报告测试——HTMLReportGenerator + DOTReportGenerator + DSMReport
"""

import os
import tempfile
import pytest

from harness.report import HTMLReportGenerator, DOTReportGenerator, DSMReport
from harness.types import ComplianceResult


# ─── Mock 数据 ────────────────────────────────────────

class MockDepGraph:
    """模拟依赖图"""
    def __init__(self):
        self.nodes = {"mod_a": "ModuleA", "mod_b": "ModuleB", "mod_c": "ModuleC"}
        self.edges = {"mod_a": ["mod_b", "mod_c"], "mod_b": ["mod_c"]}


class MockCallGraph:
    """模拟调用图"""
    def __init__(self):
        self.calls = {"func_a": ["func_b", "func_c"], "func_b": ["func_c"]}


class MockAuditStats:
    """模拟审计统计"""
    total_tasks = 50
    delivered = 40
    escalated = 5
    auto_fixed = 10
    verification_pass_rate = 0.85


MOCK_RESULTS = [
    ComplianceResult(rule_id="ARCH-004", passed=False, severity="high",
                     findings=["God Class detected"]),
    ComplianceResult(rule_id="ARCH-001", passed=True, severity="high",
                     findings=[]),
    ComplianceResult(rule_id="ARCH-005", passed=False, severity="medium",
                     findings=["Deep inheritance chain"]),
]


# ─── HTMLReportGenerator ──────────────────────────────

class TestHTMLReportGenerator:

    def test_compliance_report_returns_html(self):
        gen = HTMLReportGenerator()
        html = gen.generate_compliance_report(MOCK_RESULTS)
        assert "<html" in html
        assert "ARCH-004" in html
        assert "FAIL" in html
        assert "PASS" in html

    def test_compliance_report_writes_file(self):
        gen = HTMLReportGenerator()
        with tempfile.TemporaryDirectory() as tmp:
            path = gen.generate_compliance_report(MOCK_RESULTS, output_dir=tmp)
            assert os.path.exists(path)
            content = open(path).read()
            assert "ARCH-004" in content

    def test_compliance_report_counts(self):
        gen = HTMLReportGenerator()
        html = gen.generate_compliance_report(MOCK_RESULTS)
        assert "1" in html  # 1 passed
        assert "2" in html  # 2 failed

    def test_dependency_graph_returns_html(self):
        gen = HTMLReportGenerator()
        dep = MockDepGraph()
        html = gen.generate_dependency_graph(dep)
        assert "<svg" in html
        assert "dep-node" in html

    def test_dependency_graph_writes_file(self):
        gen = HTMLReportGenerator()
        dep = MockDepGraph()
        with tempfile.TemporaryDirectory() as tmp:
            path = gen.generate_dependency_graph(dep, output_dir=tmp)
            assert os.path.exists(path)

    def test_audit_dashboard_returns_html(self):
        gen = HTMLReportGenerator()
        stats = MockAuditStats()
        html = gen.generate_audit_dashboard(stats)
        assert "50" in html  # total tasks
        assert "85%" in html or "0.85" in html  # pass rate

    def test_audit_dashboard_writes_file(self):
        gen = HTMLReportGenerator()
        stats = MockAuditStats()
        with tempfile.TemporaryDirectory() as tmp:
            path = gen.generate_audit_dashboard(stats, output_dir=tmp)
            assert os.path.exists(path)

    def test_html_is_self_contained(self):
        """HTML 不依赖外部资源"""
        gen = HTMLReportGenerator()
        html = gen.generate_compliance_report(MOCK_RESULTS)
        assert "<link" not in html  # 无外部 CSS
        assert "<script src" not in html  # 无外部 JS


# ─── DOTReportGenerator ──────────────────────────────

class TestDOTReportGenerator:

    def test_dependency_dot(self):
        gen = DOTReportGenerator()
        dep = MockDepGraph()
        dot = gen.generate_dependency_dot(dep)
        assert "digraph" in dot
        assert "mod_a" in dot
        assert "->" in dot

    def test_call_graph_dot(self):
        gen = DOTReportGenerator()
        cg = MockCallGraph()
        dot = gen.generate_call_graph_dot(cg)
        assert "digraph" in dot
        assert "func_a" in dot
        assert "->" in dot

    def test_empty_graph(self):
        gen = DOTReportGenerator()
        class EmptyDep:
            nodes = {}
            edges = {}
        dot = gen.generate_dependency_dot(EmptyDep())
        assert "digraph" in dot


# ─── DSMReport ────────────────────────────────────────

class TestDSMReport:

    def test_dsm_text_format(self):
        dsm = DSMReport()
        dep = MockDepGraph()
        text = dsm.generate_dsm(dep, output_format="text")
        assert "mod_a" in text or "mod" in text.lower()

    def test_dsm_html_format(self):
        dsm = DSMReport()
        dep = MockDepGraph()
        html_out = dsm.generate_dsm(dep, output_format="html")
        assert "<table" in html_out
        assert "dep" in html_out

    def test_dsm_json_format(self):
        dsm = DSMReport()
        dep = MockDepGraph()
        json_out = dsm.generate_dsm(dep, output_format="json")
        import json
        data = json.loads(json_out)
        assert "modules" in data
        assert "matrix" in data

    def test_dsm_empty_graph(self):
        dsm = DSMReport()
        class EmptyDep:
            nodes = {}
            edges = {}
        text = dsm.generate_dsm(EmptyDep(), output_format="text")
        assert "empty" in text
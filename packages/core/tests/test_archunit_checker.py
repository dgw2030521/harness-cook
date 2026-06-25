"""
ArchUnitChecker 测试 — Java 架构合规引擎集成

覆盖范围：
1. _probe_engine — JVM 检测、jar 检测、常见路径查找
2. _translate_request — matcher_config → ArchUnit 测试参数
3. _call_engine — 子进程执行（成功/失败场景）
4. _parse_java_output — JUnit 格式输出解析
5. fallback 回退 — DependencyGraphChecker 降级
6. 完整 check 流程 — 探测→翻译→调用→响应翻译
7. 集成测试 — @pytest.mark.archunit 标记
"""

import os
import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from harness.types import (
    Artifact, ComplianceRule, ComplianceResult, ScanContext,
    ComplianceCategory,
)
from harness.integrations.archunit_checker import ArchUnitChecker
from harness.rule_checker import DependencyGraphChecker


# ═══════════════════════════════════════════════════════════
#  测试辅助 — 构造规则、产出物、上下文
# ═══════════════════════════════════════════════════════════

def _make_rule(
    matcher_type: str = "archunit",
    matcher_config: dict = None,
    severity: str = "high",
) -> ComplianceRule:
    """构造一条 ArchUnit 合规规则"""
    config = matcher_config or {
        "check": "layer_violation",
        "layer_mapping": {
            "controller": "com.example.controller..",
            "service": "com.example.service..",
            "repository": "com.example.repository..",
        },
        "forbidden_directions": [
            {"from_layer": "controller", "to_layer": "repository"},
        ],
    }
    return ComplianceRule(
        id="arch-test-001",
        category=ComplianceCategory.ARCHITECTURE,
        pattern="archunit_layer_violation",
        severity=severity,
        description="ArchUnit 分层违规检查",
        remediation="修复分层违规依赖方向",
        auto_fixable=False,
        languages=["java"],
        matcher_type=matcher_type,
        matcher_config=config,
    )


def _make_artifact(path: str = "src/main/java/com/example/App.java") -> Artifact:
    """构造一个 Java 产出物"""
    return Artifact(
        type="code",
        path=path,
        content="package com.example;\npublic class App {}\n",
        metadata={"language": "java"},
    )


def _make_context(
    project_root: str = "/project/java-app",
) -> ScanContext:
    """构造扫描上下文"""
    return ScanContext(
        artifacts=[_make_artifact()],
        dependency_graph=None,
        project_root=project_root,
        metadata={},
    )


# ═══════════════════════════════════════════════════════════
#  1. _probe_engine 测试 — JVM 检测 + jar 检测
# ═══════════════════════════════════════════════════════════

class TestProbeEngine:
    """引擎可用性探测测试"""

    def test_jvm_available_jar_configured(self):
        """JVM 可用 + jar 在 config 中指定 → 探测成功"""
        checker = ArchUnitChecker(config={
            "java_home": "/usr/lib/jvm/java-11",
            "archunit_jar": "/opt/archunit/archunit.jar",
        })
        # mock subprocess.run: JVM 检测返回成功
        mock_run = MagicMock(returncode=0)
        # mock os.path.isfile: jar 路径存在
        with patch("harness.integrations.archunit_checker.subprocess.run", return_value=mock_run), \
             patch("harness.integrations.archunit_checker.os.path.isfile", return_value=True):
            result = checker._probe_engine()
            assert result is True
            # jar_path 应缓存到 config
            assert checker._config["archunit_jar"] == "/opt/archunit/archunit.jar"

    def test_jvm_not_available(self):
        """JVM 不可用（java -version 返回非0）→ 探测失败"""
        checker = ArchUnitChecker(config={})
        mock_run = MagicMock(returncode=1)
        with patch("harness.integrations.archunit_checker.subprocess.run", return_value=mock_run):
            result = checker._probe_engine()
            assert result is False

    def test_jvm_not_found_file_not_found_error(self):
        """JVM 不安装（FileNotFoundError）→ 探测失败"""
        checker = ArchUnitChecker(config={})
        with patch("harness.integrations.archunit_checker.subprocess.run",
                   side_effect=FileNotFoundError("java not found")):
            result = checker._probe_engine()
            assert result is False

    def test_jvm_timeout_expired(self):
        """JVM 检测超时 → 探测失败"""
        import subprocess
        checker = ArchUnitChecker(config={})
        with patch("harness.integrations.archunit_checker.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="java", timeout=5)):
            result = checker._probe_engine()
            assert result is False

    def test_jvm_available_with_java_home(self):
        """config 指定 java_home 时，java_cmd 使用 java_home/bin/java"""
        checker = ArchUnitChecker(config={
            "java_home": "/custom/jvm",
            "archunit_jar": "/opt/archunit/archunit.jar",
        })
        mock_run = MagicMock(returncode=0)
        with patch("harness.integrations.archunit_checker.subprocess.run", return_value=mock_run) as mock_sub, \
             patch("harness.integrations.archunit_checker.os.path.isfile", return_value=True):
            result = checker._probe_engine()
            assert result is True
            # 检查 subprocess.run 被调用时的 java_cmd 参数
            call_args = mock_sub.call_args_list[0]
            java_cmd = call_args[0][0][0]
            assert java_cmd == os.path.join("/custom/jvm", "bin", "java")

    def test_jar_found_in_common_path(self):
        """JVM 可用 + config 中无 jar + 常见路径找到 jar → 探测成功"""
        checker = ArchUnitChecker(config={"java_home": ""})
        mock_run = MagicMock(returncode=0)
        # os.path.isfile 调用顺序：
        # 1) ~/.archunit/archunit.jar → False
        # 2) /opt/archunit/archunit.jar → True（找到 jar，跳出循环）
        # 3) 最终验证 os.path.isfile(jar_path) → True（第111行）
        with patch("harness.integrations.archunit_checker.subprocess.run", return_value=mock_run), \
             patch("harness.integrations.archunit_checker.os.path.isfile",
                   side_effect=[False, True, True]), \
             patch("harness.integrations.archunit_checker.os.getcwd", return_value="/project"):
            result = checker._probe_engine()
            assert result is True
            # jar_path 应缓存到 config
            assert "archunit_jar" in checker._config

    def test_jar_not_found_anywhere(self):
        """JVM 可用 + jar 在 config 中未指定 + 常见路径都找不到 → 探测失败"""
        checker = ArchUnitChecker(config={})
        mock_run = MagicMock(returncode=0)
        with patch("harness.integrations.archunit_checker.subprocess.run", return_value=mock_run), \
             patch("harness.integrations.archunit_checker.os.path.isfile", return_value=False):
            result = checker._probe_engine()
            assert result is False


# ═══════════════════════════════════════════════════════════
#  2. _translate_request 测试
# ═══════════════════════════════════════════════════════════

class TestTranslateRequest:
    """请求翻译测试 — matcher_config → ArchUnit 测试参数"""

    def test_check_type_from_matcher_config(self):
        """matcher_config.check 正确提取 check_type"""
        checker = ArchUnitChecker(config={
            "java_home": "/usr/lib/jvm/java-11",
            "archunit_jar": "/opt/archunit/archunit.jar",
        })
        rule = _make_rule(matcher_config={"check": "no_cycles"})
        artifact = _make_artifact()
        context = _make_context(project_root="/java-project")

        request = checker._translate_request(rule, artifact, context)
        assert request["check_type"] == "no_cycles"

    def test_check_type_default_layer_violation(self):
        """matcher_config 无 check 字段 → 默认 check_type=layer_violation"""
        checker = ArchUnitChecker(config={
            "java_home": "/usr/lib/jvm/java-11",
            "archunit_jar": "/opt/archunit/archunit.jar",
        })
        rule = _make_rule(matcher_config={})  # 无 check 字段
        artifact = _make_artifact()
        context = _make_context(project_root="/java-project")

        request = checker._translate_request(rule, artifact, context)
        assert request["check_type"] == "layer_violation"

    def test_project_root_from_context(self):
        """project_root 优先从 ScanContext 获取"""
        checker = ArchUnitChecker(config={"project_root": "/config-root"})
        rule = _make_rule()
        artifact = _make_artifact()
        context = _make_context(project_root="/context-root")

        request = checker._translate_request(rule, artifact, context)
        assert request["project_root"] == "/context-root"

    def test_project_root_from_config_fallback(self):
        """ScanContext.project_root 为 None → 回退到 config.project_root"""
        checker = ArchUnitChecker(config={"project_root": "/config-root"})
        rule = _make_rule()
        artifact = _make_artifact()
        context = ScanContext(
            artifacts=[artifact],
            dependency_graph=None,
            project_root=None,
            metadata={},
        )

        request = checker._translate_request(rule, artifact, context)
        assert request["project_root"] == "/config-root"

    def test_request_contains_all_required_fields(self):
        """翻译结果包含所有必要字段"""
        checker = ArchUnitChecker(config={
            "java_home": "/usr/lib/jvm/java-11",
            "archunit_jar": "/opt/archunit/archunit.jar",
        })
        rule = _make_rule(matcher_config={"check": "naming_convention"})
        artifact = _make_artifact()
        context = _make_context()

        request = checker._translate_request(rule, artifact, context)
        # 验证所有必需字段存在
        expected_keys = [
            "check_type", "project_root", "matcher_config",
            "artifact_path", "rule_id", "severity",
            "java_home", "archunit_jar",
        ]
        for key in expected_keys:
            assert key in request, f"缺少字段: {key}"
        assert request["check_type"] == "naming_convention"
        assert request["artifact_path"] == artifact.path
        assert request["rule_id"] == rule.id
        assert request["severity"] == rule.severity


# ═══════════════════════════════════════════════════════════
#  3. _call_engine 测试 — 子进程执行
# ═══════════════════════════════════════════════════════════

class TestCallEngine:
    """引擎调用测试 — subprocess.run 执行 ArchUnit Java 测试"""

    def test_call_engine_success(self):
        """ArchUnit 测试通过（returncode=0）→ 返回 passed=True"""
        checker = ArchUnitChecker(config={
            "java_home": "/usr/lib/jvm/java-11",
            "archunit_jar": "/opt/archunit/archunit.jar",
        })
        request = {
            "check_type": "layer_violation",
            "project_root": "/java-project",
            "matcher_config": {"check": "layer_violation"},
            "artifact_path": "App.java",
            "java_home": "/usr/lib/jvm/java-11",
            "archunit_jar": "/opt/archunit/archunit.jar",
            "severity": "high",
        }

        mock_run = MagicMock(returncode=0, stdout="", stderr="")
        with patch("harness.integrations.archunit_checker.subprocess.run", return_value=mock_run):
            response = checker._call_engine(request)
            assert response["passed"] is True
            assert response["findings"] == []
            assert response["severity"] == "high"

    def test_call_engine_failure_returns_parsed_output(self):
        """ArchUnit 测试失败（returncode≠0）→ 解析 Java 输出"""
        checker = ArchUnitChecker(config={
            "java_home": "/usr/lib/jvm/java-11",
            "archunit_jar": "/opt/archunit/archunit.jar",
        })
        request = {
            "check_type": "layer_violation",
            "project_root": "/java-project",
            "matcher_config": {"check": "layer_violation"},
            "artifact_path": "App.java",
            "java_home": "/usr/lib/jvm/java-11",
            "archunit_jar": "/opt/archunit/archunit.jar",
            "severity": "critical",
        }

        java_output = (
            "Architecture Violation: Controller imports Repository\n"
            "at com.example.controller.UserController.java:15\n"
            "at com.example.service.UserService.java:22\n"
        )
        mock_run = MagicMock(returncode=1, stdout=java_output, stderr="")
        with patch("harness.integrations.archunit_checker.subprocess.run", return_value=mock_run):
            response = checker._call_engine(request)
            assert response["passed"] is False
            # "at " 行被过滤，只剩非 "at " 行
            assert len(response["findings"]) > 0
            assert response["severity"] == "critical"

    def test_call_engine_no_jar_raises_runtime_error(self):
        """archunit_jar 为空 → RuntimeError"""
        checker = ArchUnitChecker(config={})
        request = {
            "check_type": "layer_violation",
            "project_root": "/java-project",
            "matcher_config": {},
            "artifact_path": "App.java",
            "java_home": "",
            "archunit_jar": "",
            "severity": "high",
        }

        with pytest.raises(RuntimeError, match="jar path not resolved"):
            checker._call_engine(request)

    def test_call_engine_timeout_raises(self):
        """ArchUnit 执行超时 → TimeoutExpired 异常抛出"""
        import subprocess
        checker = ArchUnitChecker(config={
            "java_home": "/usr/lib/jvm/java-11",
            "archunit_jar": "/opt/archunit/archunit.jar",
        })
        request = {
            "check_type": "layer_violation",
            "project_root": "/java-project",
            "matcher_config": {},
            "artifact_path": "App.java",
            "java_home": "/usr/lib/jvm/java-11",
            "archunit_jar": "/opt/archunit/archunit.jar",
            "severity": "high",
        }

        with patch("harness.integrations.archunit_checker.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd=["java", "-jar"], timeout=30)):
            with pytest.raises(subprocess.TimeoutExpired):
                checker._call_engine(request)

    def test_call_engine_java_cmd_with_java_home(self):
        """request 中指定 java_home → java_cmd 使用 java_home/bin/java"""
        checker = ArchUnitChecker(config={})
        request = {
            "check_type": "layer_violation",
            "project_root": "/java-project",
            "matcher_config": {},
            "artifact_path": "App.java",
            "java_home": "/custom/jvm",
            "archunit_jar": "/opt/archunit/archunit.jar",
            "severity": "high",
        }

        mock_run = MagicMock(returncode=0, stdout="", stderr="")
        with patch("harness.integrations.archunit_checker.subprocess.run", return_value=mock_run) as mock_sub:
            checker._call_engine(request)
            # 检查 subprocess.run 被调用时的命令
            call_args = mock_sub.call_args
            cmd = call_args[0][0]
            assert cmd[0] == os.path.join("/custom/jvm", "bin", "java")
            assert cmd[1] == "-jar"
            assert cmd[2] == "/opt/archunit/archunit.jar"

    def test_call_engine_stderr_used_when_stdout_empty(self):
        """stdout 为空时使用 stderr 输出"""
        checker = ArchUnitChecker(config={
            "archunit_jar": "/opt/archunit/archunit.jar",
        })
        request = {
            "check_type": "layer_violation",
            "project_root": "/java-project",
            "matcher_config": {},
            "artifact_path": "App.java",
            "java_home": "",
            "archunit_jar": "/opt/archunit/archunit.jar",
            "severity": "high",
        }

        stderr_output = "Violation: Service depends on Repository directly\n"
        mock_run = MagicMock(returncode=1, stdout=None, stderr=stderr_output)
        with patch("harness.integrations.archunit_checker.subprocess.run", return_value=mock_run):
            response = checker._call_engine(request)
            assert response["passed"] is False
            assert any("Violation" in f for f in response["findings"])


# ═══════════════════════════════════════════════════════════
#  4. _parse_java_output 测试
# ═══════════════════════════════════════════════════════════

class TestParseJavaOutput:
    """JUnit 格式输出解析测试"""

    def test_parse_violation_lines(self):
        """解析非 'at ' 和非 'Exception' 行作为 findings"""
        checker = ArchUnitChecker(config={})
        output = (
            "Architecture Violation: Controller imports Repository\n"
            "at com.example.controller.UserController.java:15\n"
            "at com.example.service.UserService.java:22\n"
        )
        request = {
            "check_type": "layer_violation",
            "severity": "high",
        }

        result = checker._parse_java_output(output, request)
        assert result["passed"] is False
        # 只提取非 "at " 行和非 "Exception" 行
        assert len(result["findings"]) == 1
        assert "Architecture Violation" in result["findings"][0]

    def test_parse_exception_lines_filtered(self):
        """以 'Exception' 开头的行被过滤"""
        checker = ArchUnitChecker(config={})
        output = (
            "Exception: java.lang.AssertionError\n"
            "at com.example.Test.run(Test.java:10)\n"
            "Architecture Violation detected\n"
        )
        request = {
            "check_type": "layer_violation",
            "severity": "high",
        }

        result = checker._parse_java_output(output, request)
        # Exception 行被过滤，at 行被过滤，只剩 violation 行
        findings_text = " ".join(result["findings"])
        assert "Exception" not in findings_text
        assert "Architecture Violation" in findings_text

    def test_parse_empty_output_generates_default_finding(self):
        """空输出 → 生成默认的 architecture violation finding"""
        checker = ArchUnitChecker(config={})
        output = ""
        request = {
            "check_type": "no_cycles",
            "severity": "high",
        }

        result = checker._parse_java_output(output, request)
        assert result["passed"] is False
        assert len(result["findings"]) == 1
        assert "no_cycles" in result["findings"][0]
        assert "architecture violation detected" in result["findings"][0]

    def test_parse_finding_count_limited_to_10(self):
        """findings 数量上限为 10"""
        checker = ArchUnitChecker(config={})
        # 生成 15 行非 at/Exception 内容
        lines = [f"Violation line {i}" for i in range(15)]
        output = "\n".join(lines)
        request = {
            "check_type": "layer_violation",
            "severity": "high",
        }

        result = checker._parse_java_output(output, request)
        assert len(result["findings"]) <= 10

    def test_parse_locations_extracted(self):
        """locations 从 findings 中提取，包含 engine 字段"""
        checker = ArchUnitChecker(config={})
        output = "Architecture Violation: Controller imports Repository\n"
        request = {
            "check_type": "layer_violation",
            "severity": "critical",
        }

        result = checker._parse_java_output(output, request)
        assert len(result["locations"]) > 0
        loc = result["locations"][0]
        assert "engine" in loc
        assert loc["engine"] == "archunit"

    def test_parse_remediation_generated(self):
        """remediation 包含 check_type 信息"""
        checker = ArchUnitChecker(config={})
        output = "Architecture Violation detected\n"
        request = {
            "check_type": "naming_convention",
            "severity": "medium",
        }

        result = checker._parse_java_output(output, request)
        assert result["remediation"] is not None
        assert "naming_convention" in result["remediation"]

    def test_parse_all_at_lines_filtered(self):
        """所有 'at ' 行都被过滤掉"""
        checker = ArchUnitChecker(config={})
        output = (
            "at com.example.A.java:1\n"
            "at com.example.B.java:2\n"
            "at com.example.C.java:3\n"
        )
        request = {
            "check_type": "layer_violation",
            "severity": "high",
        }

        result = checker._parse_java_output(output, request)
        # 全是 at 行 → fallback 到默认 finding
        assert len(result["findings"]) == 1
        assert "architecture violation" in result["findings"][0]


# ═══════════════════════════════════════════════════════════
#  5. fallback 回退测试
# ═══════════════════════════════════════════════════════════

class TestFallback:
    """降级回退到 DependencyGraphChecker 的测试"""

    def test_fallback_when_jvm_not_available(self):
        """JVM 不可用 → 自动回退到 DependencyGraphChecker"""
        checker = ArchUnitChecker(config={})
        # 强制探测失败
        with patch.object(checker, "_probe_engine", return_value=False):
            checker._availability_cache = False

            rule = _make_rule()
            artifact = _make_artifact()
            context = _make_context()

            result = checker.check(rule, artifact, context)
            # 回退到 DependencyGraphChecker，其 check 方法被执行
            assert result.rule_id == rule.id
            # DependencyGraphChecker 对 dependency_graph=None 返回 passed=True
            assert result.passed is True
            assert "no dependency graph" in result.findings[0].lower() or "skipped" in result.findings[0].lower()

    def test_fallback_when_probe_raises_exception(self):
        """探测过程抛出异常 → 自动回退"""
        checker = ArchUnitChecker(config={})
        checker._availability_cache = None  # 重置缓存，触发重新探测

        with patch.object(checker, "_probe_engine", side_effect=Exception("probe error")):
            rule = _make_rule()
            artifact = _make_artifact()
            context = _make_context()

            result = checker.check(rule, artifact, context)
            # 探测异常 → _is_engine_available 返回 False → 回退
            assert result.rule_id == rule.id

    def test_fallback_when_call_engine_fails(self):
        """引擎调用失败 → 回退到 DependencyGraphChecker"""
        checker = ArchUnitChecker(config={
            "java_home": "/usr/lib/jvm/java-11",
            "archunit_jar": "/opt/archunit/archunit.jar",
        })
        # 探测成功
        checker._availability_cache = True

        rule = _make_rule()
        artifact = _make_artifact()
        context = _make_context()

        # _call_engine 抛出异常 → 回退
        with patch.object(checker, "_call_engine", side_effect=RuntimeError("engine crash")):
            result = checker.check(rule, artifact, context)
            assert result.rule_id == rule.id
            # 回退到 DependencyGraphChecker（无依赖图→passed=True）
            assert result.passed is True

    def test_fallback_checker_is_dependency_graph_checker(self):
        """fallback_checker 应为 DependencyGraphChecker 实例"""
        checker = ArchUnitChecker(config={})
        assert isinstance(checker.fallback_checker, DependencyGraphChecker)

    def test_fallback_when_translate_request_fails(self):
        """请求翻译失败 → 回退到 DependencyGraphChecker"""
        checker = ArchUnitChecker(config={
            "java_home": "/usr/lib/jvm/java-11",
            "archunit_jar": "/opt/archunit/archunit.jar",
        })
        checker._availability_cache = True

        rule = _make_rule()
        artifact = _make_artifact()
        context = _make_context()

        with patch.object(checker, "_translate_request", side_effect=ValueError("bad request")):
            result = checker.check(rule, artifact, context)
            assert result.rule_id == rule.id
            # 回退到 DependencyGraphChecker
            assert result.passed is True


# ═══════════════════════════════════════════════════════════
#  6. 完整 check 流程测试
# ═══════════════════════════════════════════════════════════

class TestCheckFlow:
    """完整 check 流程测试 — 探测→翻译→调用→响应翻译"""

    def test_full_flow_archunit_passes(self):
        """完整流程：引擎可用 → 翻译 → 调用（通过）→ 返回 ComplianceResult"""
        checker = ArchUnitChecker(config={
            "java_home": "/usr/lib/jvm/java-11",
            "archunit_jar": "/opt/archunit/archunit.jar",
        })

        rule = _make_rule(severity="high")
        artifact = _make_artifact()
        context = _make_context()

        # mock _probe_engine → True
        # mock subprocess.run → returncode=0（测试通过）
        mock_run = MagicMock(returncode=0, stdout="", stderr="")
        with patch("harness.integrations.archunit_checker.subprocess.run", return_value=mock_run), \
             patch("harness.integrations.archunit_checker.os.path.isfile", return_value=True):
            result = checker.check(rule, artifact, context)

        assert isinstance(result, ComplianceResult)
        assert result.rule_id == "arch-test-001"
        assert result.passed is True
        assert result.severity == "high"
        assert result.findings == []

    def test_full_flow_archunit_fails(self):
        """完整流程：引擎可用 → 翻译 → 调用（失败）→ 解析输出 → ComplianceResult"""
        checker = ArchUnitChecker(config={
            "java_home": "/usr/lib/jvm/java-11",
            "archunit_jar": "/opt/archunit/archunit.jar",
        })

        rule = _make_rule(severity="critical")
        artifact = _make_artifact()
        context = _make_context()

        java_output = "Architecture Violation: Controller imports Repository\n"
        mock_probe_run = MagicMock(returncode=0)  # JVM 检测通过
        mock_call_run = MagicMock(returncode=1, stdout=java_output, stderr="")

        # 探测阶段和调用阶段的 subprocess.run 调用不同
        with patch("harness.integrations.archunit_checker.subprocess.run",
                   side_effect=[mock_probe_run, mock_call_run]), \
             patch("harness.integrations.archunit_checker.os.path.isfile", return_value=True):
            result = checker.check(rule, artifact, context)

        assert isinstance(result, ComplianceResult)
        assert result.rule_id == "arch-test-001"
        assert result.passed is False
        assert result.severity == "critical"
        assert len(result.findings) > 0
        assert result.remediation is not None

    def test_check_result_locations_marked_with_engine(self):
        """结果中的 locations 应标记 engine=archunit"""
        checker = ArchUnitChecker(config={
            "java_home": "/usr/lib/jvm/java-11",
            "archunit_jar": "/opt/archunit/archunit.jar",
        })
        checker._availability_cache = True

        rule = _make_rule()
        artifact = _make_artifact()
        context = _make_context()

        # mock _call_engine 返回失败结果带 locations
        with patch.object(checker, "_call_engine", return_value={
            "passed": False,
            "findings": ["Architecture violation detected"],
            "severity": "high",
            "remediation": "Fix violations",
            "locations": [{"line": 0, "match": "violation", "start": 0, "end": 0}],
        }):
            result = checker.check(rule, artifact, context)

        # 基类 check 方法会对 locations 设置 engine 字段
        if result.locations:
            for loc in result.locations:
                assert loc.get("engine") == "archunit"

    def test_engine_name_property(self):
        """engine_name 属性返回 'archunit'"""
        checker = ArchUnitChecker(config={})
        assert checker.engine_name == "archunit"


# ═══════════════════════════════════════════════════════════
#  7. 集成测试 — @pytest.mark.archunit
# ═══════════════════════════════════════════════════════════

@pytest.mark.archunit
class TestArchUnitIntegration:
    """ArchUnit 集成测试 — 需要真实 JVM 和 ArchUnit jar 环境

    这些测试默认会被 skip，除非环境中有真实的 JVM 和 ArchUnit jar。
    通过 pytest -m archunit 可单独运行。
    """

    @pytest.fixture
    def real_checker(self):
        """真实环境的 ArchUnitChecker"""
        return ArchUnitChecker(config={
            "java_home": os.environ.get("JAVA_HOME", ""),
            "archunit_jar": os.environ.get("ARCHUNIT_JAR", ""),
            "project_root": os.environ.get("PROJECT_ROOT", "/tmp/test-project"),
        })

    def test_probe_real_jvm(self, real_checker):
        """探测真实 JVM 可用性"""
        result = real_checker._probe_engine()
        # 在有 JVM 的环境中应为 True，否则为 False
        # 不会断言具体值，只确认不抛异常
        assert isinstance(result, bool)

    def test_translate_request_real_rule(self, real_checker):
        """翻译真实规则"""
        rule = _make_rule(matcher_config={
            "check": "layer_violation",
            "layer_mapping": {
                "controller": "com.example.controller..",
            },
        })
        artifact = _make_artifact()
        context = _make_context()

        request = real_checker._translate_request(rule, artifact, context)
        assert "check_type" in request
        assert request["check_type"] == "layer_violation"

    def test_parse_java_output_real_format(self, real_checker):
        """解析真实 JUnit 输出格式"""
        output = (
            "java.lang.AssertionError: Architecture violation\n"
            "Rule 'no classes in controller layer should access repository layer' was violated:\n"
            "ControllerClass accesses RepositoryClass\n"
            "at com.example.Test.checkArchitecture(Test.java:25)\n"
        )
        request = {"check_type": "layer_violation", "severity": "high"}

        result = real_checker._parse_java_output(output, request)
        assert result["passed"] is False
        # "at " 行被过滤
        assert not any(f.startswith("at ") for f in result["findings"])

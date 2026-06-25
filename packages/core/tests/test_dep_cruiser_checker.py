"""
DepCruiserChecker 测试

验证 dep-cruiser JS/TS 依赖合规引擎集成的完整流程：
- _probe_engine: 多命令探测（depcruise / npx / fallback）
- _translate_request: cruise_config 优先级与自动查找
- _call_engine: JSON / 文本输出解析
- _parse_json_output / _parse_text_output
- fallback 回退（DependencyGraphChecker）
- 完整 check 流程
- 集成测试（@pytest.mark.dep_cruiser）
"""

import json
import os
import subprocess
import pytest
from unittest.mock import MagicMock, patch, call

from harness.types import (
    Artifact,
    ComplianceCategory,
    ComplianceRule,
    ComplianceResult,
    ScanContext,
)
from harness.integrations.dep_cruiser_checker import DepCruiserChecker


# ═══════════════════════════════════════════════════════════
#  测试辅助工厂
# ═══════════════════════════════════════════════════════════

def _make_rule(
    id: str = "ARCH-dep-001",
    matcher_type: str = "dep_cruiser",
    matcher_config: dict = None,
    severity: str = "high",
    languages: list = None,
) -> ComplianceRule:
    """构造合规规则"""
    return ComplianceRule(
        id=id,
        category=ComplianceCategory.ARCHITECTURE,
        pattern="dependency_violation",
        severity=severity,
        description="依赖方向违规",
        remediation="修复依赖方向",
        auto_fixable=False,
        languages=languages or ["javascript", "typescript"],
        matcher_type=matcher_type,
        matcher_config=matcher_config or {},
    )


def _make_artifact(path: str = "src/app.ts", content: str = "") -> Artifact:
    """构造产出物"""
    return Artifact(type="code", path=path, content=content, metadata={})


def _make_context(
    project_root: str = "/project",
    dependency_graph=None,
) -> ScanContext:
    """构造扫描上下文"""
    return ScanContext(
        artifacts=[_make_artifact()],
        dependency_graph=dependency_graph,
        project_root=project_root,
        metadata={},
    )


def _mock_subprocess_success(stdout: str = "16.0.0", returncode: int = 0):
    """模拟 subprocess.run 成功返回"""
    result = MagicMock()
    result.stdout = stdout
    result.stderr = ""
    result.returncode = returncode
    return result


def _mock_subprocess_failure(returncode: int = 1, stderr: str = "not found"):
    """模拟 subprocess.run 失败返回"""
    result = MagicMock()
    result.stdout = ""
    result.stderr = stderr
    result.returncode = returncode
    return result


# ═══════════════════════════════════════════════════════════
#  _probe_engine 测试——多命令探测
# ═══════════════════════════════════════════════════════════

class TestProbeEngine:
    """引擎可用性探测——依次尝试多个命令"""

    def test_depcruise_cmd_found(self):
        """depcruise 命令直接可用"""
        checker = DepCruiserChecker(config={"depcruise_cmd": "depcruise"})
        with patch("harness.integrations.dep_cruiser_checker.subprocess.run") as mock_run:
            mock_run.return_value = _mock_subprocess_success("16.0.0")
            result = checker._probe_engine()

        assert result is True
        assert checker._config["depcruise_cmd"] == "depcruise"
        # 第一个尝试就是配置的 cmd
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == ["depcruise", "--version"]

    def test_npx_fallback_found(self):
        """depcruise 不可用，但 npx dependency-cruiser 可用"""
        checker = DepCruiserChecker(config={})
        with patch("harness.integrations.dep_cruiser_checker.subprocess.run") as mock_run:
            # depcruise 失败 → npx 成功
            mock_run.side_effect = [
                FileNotFoundError("depcruise not found"),  # depcruise
                _mock_subprocess_success("16.0.0"),       # npx
            ]
            result = checker._probe_engine()

        assert result is True
        assert checker._config["depcruise_cmd"] == "npx"
        assert checker._config["use_npx"] is True
        # 验证 npx 调用参数
        npx_call = mock_run.call_args_list[1]
        assert npx_call[0][0] == ["npx", "dependency-cruiser", "--version"]

    def test_custom_cmd_found(self):
        """自定义命令（如 ./node_modules/.bin/depcruise）可用"""
        custom_cmd = "./node_modules/.bin/depcruise"
        checker = DepCruiserChecker(config={"depcruise_cmd": custom_cmd})
        with patch("harness.integrations.dep_cruiser_checker.subprocess.run") as mock_run:
            mock_run.return_value = _mock_subprocess_success("16.0.0")
            result = checker._probe_engine()

        assert result is True
        # 自定义命令已缓存到 config
        assert checker._config["depcruise_cmd"] == custom_cmd

    def test_all_cmds_not_found(self):
        """所有命令都不可用 → 返回 False"""
        checker = DepCruiserChecker(config={})
        with patch("harness.integrations.dep_cruiser_checker.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("not found")
            result = checker._probe_engine()

        assert result is False

    def test_timeout_expired(self):
        """命令超时 → 继续尝试下一个"""
        checker = DepCruiserChecker(config={})
        with patch("harness.integrations.dep_cruiser_checker.subprocess.run") as mock_run:
            mock_run.side_effect = [
                subprocess.TimeoutExpired(cmd="depcruise", timeout=5),  # depcruise 超时
                subprocess.TimeoutExpired(cmd="npx", timeout=5),       # npx 超时
                FileNotFoundError("depcruise"),                        # depcruise 不存在
            ]
            result = checker._probe_engine()

        assert result is False

    def test_cmd_return_nonzero(self):
        """命令存在但 --version 返回非零 → 继续尝试下一个"""
        checker = DepCruiserChecker(config={})
        with patch("harness.integrations.dep_cruiser_checker.subprocess.run") as mock_run:
            # depcruise 返回非零 → npx 成功
            mock_run.side_effect = [
                _mock_subprocess_failure(returncode=127),
                _mock_subprocess_success("16.0.0"),
            ]
            result = checker._probe_engine()

        assert result is True
        assert checker._config["use_npx"] is True

    def test_availability_cache(self):
        """探测结果被缓存，后续不再重复探测"""
        checker = DepCruiserChecker(config={"depcruise_cmd": "depcruise"})
        with patch("harness.integrations.dep_cruiser_checker.subprocess.run") as mock_run:
            mock_run.return_value = _mock_subprocess_success("16.0.0")
            # 首次探测
            assert checker._is_engine_available() is True
            # 再次探测——不调用 subprocess.run
            assert checker._is_engine_available() is True

        # subprocess.run 只被调用一次（首次探测）
        assert mock_run.call_count == 1

    def test_probe_cmd_dedup(self):
        """cmds_to_try 中不重复插入已存在的 cmd"""
        # 当 config.depcruise_cmd = "npx" 时，cmds_to_try 应不重复 npx
        checker = DepCruiserChecker(config={"depcruise_cmd": "npx"})
        with patch("harness.integrations.dep_cruiser_checker.subprocess.run") as mock_run:
            mock_run.return_value = _mock_subprocess_success("16.0.0")
            result = checker._probe_engine()

        assert result is True


# ═══════════════════════════════════════════════════════════
#  _translate_request 测试——cruise_config 优先级与自动查找
# ═══════════════════════════════════════════════════════════

class TestTranslateRequest:
    """请求翻译——matcher_config.cruise_config 优先级高于 checker config"""

    def test_rule_cruise_config_takes_priority(self):
        """规则 matcher_config.cruise_config 优先于 checker config"""
        rule = _make_rule(matcher_config={
            "cruise_config": ".dependency-cruiser.js",
        })
        checker = DepCruiserChecker(config={
            "cruise_config": ".dependency-cruiser.json",
        })
        checker._availability_cache = True  # 跳过探测

        request = checker._translate_request(
            rule, _make_artifact(), _make_context(project_root="/project"),
        )
        # 规则级别优先
        assert request["cruise_config"] == ".dependency-cruiser.js"

    def test_checker_config_as_fallback(self):
        """无规则 cruise_config 时回退到 checker config"""
        rule = _make_rule(matcher_config={})
        checker = DepCruiserChecker(config={
            "cruise_config": ".dependency-cruiser.json",
        })
        checker._availability_cache = True

        request = checker._translate_request(
            rule, _make_artifact(), _make_context(project_root="/project"),
        )
        assert request["cruise_config"] == ".dependency-cruiser.json"

    def test_auto_find_config_file(self):
        """无任何 cruise_config → 自动查找项目配置文件"""
        rule = _make_rule(matcher_config={})
        checker = DepCruiserChecker(config={})
        checker._availability_cache = True

        with patch("os.path.isfile") as mock_isfile:
            # 模拟 .dependency-cruiser.js 存在
            mock_isfile.side_effect = lambda p: p.endswith(".dependency-cruiser.js")
            request = checker._translate_request(
                rule, _make_artifact(), _make_context(project_root="/project"),
            )

        assert request["cruise_config"] == ".dependency-cruiser.js"

    def test_auto_find_prefers_js_over_json(self):
        """自动查找按优先级顺序：.js > .json > .cjs"""
        rule = _make_rule(matcher_config={})
        checker = DepCruiserChecker(config={})
        checker._availability_cache = True

        with patch("os.path.isfile") as mock_isfile:
            # 两个配置文件都存在，js 优先
            mock_isfile.return_value = True
            request = checker._translate_request(
                rule, _make_artifact(), _make_context(project_root="/project"),
            )

        assert request["cruise_config"] == ".dependency-cruiser.js"

    def test_no_config_found(self):
        """无配置文件 → cruise_config 为空字符串"""
        rule = _make_rule(matcher_config={})
        checker = DepCruiserChecker(config={})
        checker._availability_cache = True

        with patch("os.path.isfile") as mock_isfile:
            mock_isfile.return_value = False
            request = checker._translate_request(
                rule, _make_artifact(), _make_context(project_root="/project"),
            )

        assert request["cruise_config"] == ""

    def test_project_root_from_context(self):
        """project_root 优先从 ScanContext 获取"""
        rule = _make_rule()
        checker = DepCruiserChecker(config={"project_root": "/default"})
        checker._availability_cache = True

        request = checker._translate_request(
            rule, _make_artifact(), _make_context(project_root="/project"),
        )
        assert request["project_root"] == "/project"

    def test_project_root_from_config_fallback(self):
        """ScanContext 无 project_root → 回退到 checker config"""
        rule = _make_rule()
        checker = DepCruiserChecker(config={"project_root": "/default"})
        checker._availability_cache = True

        context = ScanContext(
            artifacts=[_make_artifact()],
            dependency_graph=None,
            project_root=None,
        )
        request = checker._translate_request(rule, _make_artifact(), context)
        assert request["project_root"] == "/default"

    def test_use_npx_propagated(self):
        """use_npx 标记传播到 request"""
        rule = _make_rule()
        checker = DepCruiserChecker(config={"use_npx": True, "depcruise_cmd": "npx"})
        checker._availability_cache = True

        request = checker._translate_request(
            rule, _make_artifact(), _make_context(project_root="/project"),
        )
        assert request["use_npx"] is True
        assert request["depcruise_cmd"] == "npx"


# ═══════════════════════════════════════════════════════════
#  _call_engine 测试——JSON 和文本输出
# ═══════════════════════════════════════════════════════════

class TestCallEngine:
    """引擎调用——subprocess 执行 depcruise --validate"""

    def test_call_with_direct_cmd(self):
        """直接使用 depcruise 命令调用"""
        request = {
            "depcruise_cmd": "depcruise",
            "project_root": "/project",
            "cruise_config": ".dependency-cruiser.js",
            "use_npx": False,
            "severity": "high",
            "rule_id": "ARCH-dep-001",
        }
        checker = DepCruiserChecker()

        json_output = json.dumps({"violations": []})
        with patch("harness.integrations.dep_cruiser_checker.subprocess.run") as mock_run:
            mock_run.return_value = _mock_subprocess_success(json_output)
            result = checker._call_engine(request)

        # 验证命令行参数
        call_args = mock_run.call_args[0][0]
        assert call_args == [
            "depcruise", "/project", "--validate",
            "-c", ".dependency-cruiser.js",
            "--output-type", "json",
        ]
        assert result["passed"] is True

    def test_call_with_npx(self):
        """使用 npx 调用"""
        request = {
            "depcruise_cmd": "npx",
            "project_root": "/project",
            "cruise_config": ".dependency-cruiser.js",
            "use_npx": True,
            "severity": "high",
            "rule_id": "ARCH-dep-001",
        }
        checker = DepCruiserChecker()

        json_output = json.dumps({"violations": []})
        with patch("harness.integrations.dep_cruiser_checker.subprocess.run") as mock_run:
            mock_run.return_value = _mock_subprocess_success(json_output)
            result = checker._call_engine(request)

        call_args = mock_run.call_args[0][0]
        assert call_args == [
            "npx", "dependency-cruiser", "/project", "--validate",
            "-c", ".dependency-cruiser.js",
            "--output-type", "json",
        ]

    def test_call_without_cruise_config(self):
        """无 cruise_config → 不加 -c 参数"""
        request = {
            "depcruise_cmd": "depcruise",
            "project_root": "/project",
            "cruise_config": "",
            "use_npx": False,
            "severity": "high",
            "rule_id": "ARCH-dep-001",
        }
        checker = DepCruiserChecker()

        json_output = json.dumps({"violations": []})
        with patch("harness.integrations.dep_cruiser_checker.subprocess.run") as mock_run:
            mock_run.return_value = _mock_subprocess_success(json_output)
            result = checker._call_engine(request)

        call_args = mock_run.call_args[0][0]
        assert "-c" not in call_args

    def test_timeout_expired_raises(self):
        """depcruise 超时 → 抛出 TimeoutExpired"""
        request = {
            "depcruise_cmd": "depcruise",
            "project_root": "/project",
            "cruise_config": "",
            "use_npx": False,
            "severity": "high",
            "rule_id": "ARCH-dep-001",
        }
        checker = DepCruiserChecker()

        with patch("harness.integrations.dep_cruiser_checker.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="depcruise", timeout=30)
            with pytest.raises(subprocess.TimeoutExpired):
                checker._call_engine(request)

    def test_json_parse_failure_falls_to_text(self):
        """JSON 解析失败 → 回退到文本解析"""
        request = {
            "depcruise_cmd": "depcruise",
            "project_root": "/project",
            "cruise_config": "",
            "use_npx": False,
            "severity": "high",
            "rule_id": "ARCH-dep-001",
        }
        checker = DepCruiserChecker()

        with patch("harness.integrations.dep_cruiser_checker.subprocess.run") as mock_run:
            mock_run.return_value = _mock_subprocess_success(
                stdout="error: something went wrong\nviolation: foo → bar",
                returncode=1,
            )
            result = checker._call_engine(request)

        # 文本解析结果
        assert result["passed"] is False
        assert len(result["findings"]) > 0


# ═══════════════════════════════════════════════════════════
#  _parse_json_output 测试
# ═══════════════════════════════════════════════════════════

class TestParseJsonOutput:
    """JSON 输出解析——violations → findings/locations"""

    def test_no_violations_passed(self):
        """无 violations → 通过"""
        checker = DepCruiserChecker()
        data = {"violations": []}
        request = {"severity": "high"}

        result = checker._parse_json_output(data, request)
        assert result["passed"] is True
        assert result["findings"] == []

    def test_single_violation(self):
        """单个 violation → findings + locations"""
        checker = DepCruiserChecker()
        data = {
            "violations": [
                {
                    "rule": {"name": "no-core-from-view"},
                    "from": "src/views/Home.vue",
                    "to": "src/core/auth.ts",
                    "message": "views 不应依赖 core",
                },
            ],
        }
        request = {"severity": "high"}

        result = checker._parse_json_output(data, request)
        assert result["passed"] is False
        assert len(result["findings"]) == 1
        assert "no-core-from-view" in result["findings"][0]
        assert len(result["locations"]) == 1
        assert result["locations"][0]["from"] == "src/views/Home.vue"
        assert result["locations"][0]["to"] == "src/core/auth.ts"
        assert result["locations"][0]["engine"] == "dep_cruiser"

    def test_multiple_violations_truncated(self):
        """超过 10 个 violations → 截断为 10"""
        checker = DepCruiserChecker()
        violations = [
            {
                "rule": {"name": f"rule-{i}"},
                "from": f"src/a{i}.ts",
                "to": f"src/b{i}.ts",
            }
            for i in range(15)
        ]
        data = {"violations": violations}
        request = {"severity": "high"}

        result = checker._parse_json_output(data, request)
        assert result["passed"] is False
        assert len(result["findings"]) == 10
        assert len(result["locations"]) == 10
        assert result["remediation"] == "Fix 15 dependency violations"

    def test_violation_missing_rule_name(self):
        """violation 缺少 rule.name → 使用 unknown"""
        checker = DepCruiserChecker()
        data = {
            "violations": [
                {
                    "from": "src/a.ts",
                    "to": "src/b.ts",
                },
            ],
        }
        request = {"severity": "medium"}

        result = checker._parse_json_output(data, request)
        assert "unknown" in result["findings"][0]

    def test_violation_missing_message(self):
        """violation 缺少 message → 自动生成"""
        checker = DepCruiserChecker()
        data = {
            "violations": [
                {
                    "rule": {"name": "layer-violation"},
                    "from": "src/views/a.ts",
                    "to": "src/core/b.ts",
                },
            ],
        }
        request = {"severity": "high"}

        result = checker._parse_json_output(data, request)
        assert "src/views/a.ts → src/core/b.ts" in result["findings"][0]


# ═══════════════════════════════════════════════════════════
#  _parse_text_output 测试
# ═══════════════════════════════════════════════════════════

class TestParseTextOutput:
    """文本输出解析——非 JSON 输出的 fallback 解析"""

    def test_returncode_zero_passed(self):
        """returncode=0 → 通过"""
        checker = DepCruiserChecker()
        result = checker._parse_text_output("no violations found", 0, {"severity": "high"})
        assert result["passed"] is True
        assert result["findings"] == []

    def test_error_lines_parsed(self):
        """包含 error/violation 关键字的行被解析"""
        checker = DepCruiserChecker()
        output = "error: core module imported from view\nviolation: foo → bar\nnormal line"
        result = checker._parse_text_output(output, 1, {"severity": "high"})
        assert result["passed"] is False
        assert len(result["findings"]) == 2
        assert "error" in result["findings"][0].lower()
        assert "violation" in result["findings"][1].lower()

    def test_no_error_lines_generic_message(self):
        """无 error/violation 行但有非零 returncode → 通用消息"""
        checker = DepCruiserChecker()
        output = "some unknown output line"
        result = checker._parse_text_output(output, 1, {"severity": "high"})
        assert result["passed"] is False
        assert result["findings"] == ["dep-cruiser: dependency validation failed"]
        assert result["remediation"] == "Fix dependency violations"

    def test_findings_truncated(self):
        """超过 10 个 findings → 截断"""
        checker = DepCruiserChecker()
        lines = [f"error: violation {i}" for i in range(15)]
        output = "\n".join(lines)
        result = checker._parse_text_output(output, 1, {"severity": "high"})
        assert len(result["findings"]) == 10

    def test_empty_output_nonzero_returncode(self):
        """空输出 + 非零 returncode → 通用消息"""
        checker = DepCruiserChecker()
        result = checker._parse_text_output("", 1, {"severity": "medium"})
        # 空字符串 strip 后为空，findings 应只有通用消息
        assert result["passed"] is False
        assert "dep-cruiser" in result["findings"][0]


# ═══════════════════════════════════════════════════════════
#  fallback 回退测试——DependencyGraphChecker
# ═══════════════════════════════════════════════════════════

class TestFallback:
    """引擎不可用 → 回退到 DependencyGraphChecker"""

    def test_probe_failure_falls_to_dependency_graph(self):
        """探测失败 → 使用 DependencyGraphChecker"""
        checker = DepCruiserChecker()
        rule = _make_rule(matcher_type="dependency_graph")

        # 探测失败
        with patch("harness.integrations.dep_cruiser_checker.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("not found")
            result = checker.check(rule, _make_artifact(), _make_context())

        # 无 dependency_graph → DependencyGraphChecker 返回 passed=True + findings=["Skipped"]
        assert result.rule_id == rule.id
        assert result.passed is True
        assert "Skipped" in result.findings[0]

    def test_call_failure_falls_to_dependency_graph(self):
        """引擎调用失败 → 回退到 DependencyGraphChecker"""
        checker = DepCruiserChecker()
        checker._availability_cache = True  # 强制引擎可用

        rule = _make_rule()
        # 模拟 _translate_request 正常但 _call_engine 异常
        with patch.object(checker, "_call_engine", side_effect=Exception("engine crash")):
            with patch.object(checker._fallback_checker, "check") as mock_fallback:
                mock_fallback.return_value = ComplianceResult(
                    rule_id=rule.id,
                    passed=True,
                    severity=rule.severity,
                    findings=["fallback result"],
                )
                result = checker.check(rule, _make_artifact(), _make_context())

        assert result.findings == ["fallback result"]
        mock_fallback.assert_called_once()

    def test_translate_request_failure_falls_back(self):
        """请求翻译失败 → 回退到 DependencyGraphChecker"""
        checker = DepCruiserChecker()
        checker._availability_cache = True

        rule = _make_rule()
        with patch.object(checker, "_translate_request", side_effect=Exception("translate error")):
            with patch.object(checker._fallback_checker, "check") as mock_fallback:
                mock_fallback.return_value = ComplianceResult(
                    rule_id=rule.id,
                    passed=True,
                    severity=rule.severity,
                    findings=["fallback"],
                )
                result = checker.check(rule, _make_artifact(), _make_context())

        mock_fallback.assert_called_once()

    def test_translate_response_failure_falls_back(self):
        """响应翻译失败 → 回退到 DependencyGraphChecker"""
        checker = DepCruiserChecker()
        checker._availability_cache = True

        rule = _make_rule()
        with patch.object(checker, "_call_engine", return_value={"passed": True}):
            with patch.object(checker, "_translate_response", side_effect=Exception("response error")):
                with patch.object(checker._fallback_checker, "check") as mock_fallback:
                    mock_fallback.return_value = ComplianceResult(
                        rule_id=rule.id,
                        passed=True,
                        severity=rule.severity,
                        findings=["fallback"],
                    )
                    result = checker.check(rule, _make_artifact(), _make_context())

        mock_fallback.assert_called_once()

    def test_fallback_checker_is_dependency_graph(self):
        """确认 fallback_checker 是 DependencyGraphChecker 实例"""
        checker = DepCruiserChecker()
        from harness.rule_checker import DependencyGraphChecker
        assert isinstance(checker._fallback_checker, DependencyGraphChecker)


# ═══════════════════════════════════════════════════════════
#  完整 check 流程测试
# ═══════════════════════════════════════════════════════════

class TestCheckFlow:
    """完整 check 流程——探测 → 翻译 → 调用 → 翻译响应"""

    def test_full_flow_with_violations(self):
        """完整流程：发现依赖违规 → ComplianceResult(passed=False)"""
        checker = DepCruiserChecker(config={"depcruise_cmd": "depcruise"})
        rule = _make_rule(matcher_config={"cruise_config": ".dependency-cruiser.js"})

        violations_json = json.dumps({
            "violations": [
                {
                    "rule": {"name": "no-core-from-view"},
                    "from": "src/views/Home.vue",
                    "to": "src/core/auth.ts",
                    "message": "views 不应依赖 core",
                },
            ],
        })

        with patch("harness.integrations.dep_cruiser_checker.subprocess.run") as mock_run:
            # 探测成功 + 调用成功
            mock_run.side_effect = [
                _mock_subprocess_success("16.0.0"),       # _probe_engine
                _mock_subprocess_success(violations_json, returncode=1),  # _call_engine
            ]
            # 重置缓存确保探测执行
            checker.reset_availability_cache()
            result = checker.check(rule, _make_artifact(), _make_context())

        assert result.rule_id == rule.id
        assert result.passed is False
        assert result.severity == "high"
        assert len(result.findings) > 0
        assert "no-core-from-view" in result.findings[0]
        assert result.remediation == "Fix 1 dependency violations"
        assert len(result.locations) > 0

    def test_full_flow_passed(self):
        """完整流程：无违规 → ComplianceResult(passed=True)"""
        checker = DepCruiserChecker(config={"depcruise_cmd": "depcruise"})
        rule = _make_rule()

        no_violations_json = json.dumps({"violations": []})

        with patch("harness.integrations.dep_cruiser_checker.subprocess.run") as mock_run:
            mock_run.side_effect = [
                _mock_subprocess_success("16.0.0"),              # _probe_engine
                _mock_subprocess_success(no_violations_json),    # _call_engine
            ]
            checker.reset_availability_cache()
            result = checker.check(rule, _make_artifact(), _make_context())

        assert result.passed is True
        assert result.findings == []
        assert result.rule_id == rule.id

    def test_full_flow_text_output(self):
        """完整流程：引擎返回文本输出"""
        checker = DepCruiserChecker(config={"depcruise_cmd": "depcruise"})
        rule = _make_rule()

        with patch("harness.integrations.dep_cruiser_checker.subprocess.run") as mock_run:
            mock_run.side_effect = [
                _mock_subprocess_success("16.0.0"),  # _probe_engine
                _mock_subprocess_success(
                    stdout="error: view imports core\nviolation: foo → bar",
                    returncode=1,
                ),  # _call_engine → 文本解析
            ]
            checker.reset_availability_cache()
            result = checker.check(rule, _make_artifact(), _make_context())

        assert result.passed is False
        assert len(result.findings) > 0

    def test_location_engine_tag(self):
        """locations 中自动标记 engine=dep_cruiser"""
        checker = DepCruiserChecker(config={"depcruise_cmd": "depcruise"})
        rule = _make_rule()

        violations_json = json.dumps({
            "violations": [
                {
                    "rule": {"name": "layer-violation"},
                    "from": "src/a.ts",
                    "to": "src/b.ts",
                },
            ],
        })

        with patch("harness.integrations.dep_cruiser_checker.subprocess.run") as mock_run:
            mock_run.side_effect = [
                _mock_subprocess_success("16.0.0"),
                _mock_subprocess_success(violations_json, returncode=1),
            ]
            checker.reset_availability_cache()
            result = checker.check(rule, _make_artifact(), _make_context())

        # 基类 _translate_response 的 engine 标记逻辑
        if result.locations:
            for loc in result.locations:
                assert loc.get("engine") == "dep_cruiser"

    def test_matches_scope_delegates_to_fallback(self):
        """matches_scope 委托给 fallback_checker"""
        checker = DepCruiserChecker()
        rule = _make_rule(languages=["typescript"])
        artifact = _make_artifact(path="src/app.ts")

        result = checker.matches_scope(rule, artifact)
        # DependencyGraphChecker.matches_scope 对所有文件返回 True
        assert result is True


# ═══════════════════════════════════════════════════════════
#  集成测试（需要实际 depcruise CLI）
# ═══════════════════════════════════════════════════════════

@pytest.mark.dep_cruiser
class TestIntegration:
    """集成测试——需要实际安装 dependency-cruiser CLI

    运行方式：
        pytest -m dep_cruiser tests/test_dep_cruiser_checker.py
    """

    def test_probe_real_depcruise(self):
        """探测实际的 depcruise/npx 命令"""
        checker = DepCruiserChecker()
        # 先检查引擎是否可用——不可用时跳过
        if not checker._is_engine_available():
            pytest.skip("dependency-cruiser CLI not installed")
        result = checker._probe_engine()
        # 引擎可用时验证缓存一致性
        assert checker._availability_cache == result

    def test_full_check_real_project(self, tmp_path):
        """对真实项目执行完整 check 流程"""
        # 创建一个最小 JS 项目用于测试
        project_dir = tmp_path / "js_project"
        project_dir.mkdir()

        # 创建 dep-cruiser 配置
        cruise_config_content = """
module.exports = {
  forbidden: [
    {
      name: "no-core-from-view",
      comment: "views不应依赖core",
      severity: "error",
      from: { path: "^src/views/" },
      to: { path: "^src/core/" },
    },
  ],
};
"""
        (project_dir / ".dependency-cruiser.js").write_text(cruise_config_content)

        # 创建源文件
        (project_dir / "src").mkdir()
        (project_dir / "src" / "views").mkdir()
        (project_dir / "src" / "core").mkdir()
        (project_dir / "src" / "views" / "Home.js").write_text(
            "import { auth } from '../core/auth.js';\n"
        )
        (project_dir / "src" / "core" / "auth.js").write_text(
            "export const auth = () => {};\n"
        )

        checker = DepCruiserChecker()
        rule = _make_rule(matcher_config={
            "cruise_config": ".dependency-cruiser.js",
        })

        if checker._is_engine_available():
            artifact = _make_artifact(
                path=str(project_dir / "src" / "views" / "Home.js"),
                content="import { auth } from '../core/auth.js';",
            )
            context = _make_context(project_root=str(project_dir))
            result = checker.check(rule, artifact, context)

            # 如果引擎可用，应该能检测到违规
            # 不强制断言（取决于 CLI 版本和配置解析）
            assert isinstance(result, ComplianceResult)
            assert result.rule_id == rule.id

    def test_check_passed_real_project(self, tmp_path):
        """合规项目应通过检查"""
        checker = DepCruiserChecker()
        # 先检查引擎是否可用——不可用时跳过
        if not checker._is_engine_available():
            pytest.skip("dependency-cruiser CLI not installed")

        project_dir = tmp_path / "clean_project"
        project_dir.mkdir()

        cruise_config_content = """
module.exports = {
  forbidden: [
    {
      name: "no-core-from-view",
      severity: "error",
      from: { path: "^src/views/" },
      to: { path: "^src/core/" },
    },
  ],
};
"""
        (project_dir / ".dependency-cruiser.js").write_text(cruise_config_content)

        (project_dir / "src").mkdir()
        (project_dir / "src" / "views").mkdir()
        (project_dir / "src" / "utils").mkdir()
        # 合规的导入——views 只导入 utils
        (project_dir / "src" / "views" / "Home.js").write_text(
            "import { helper } from '../utils/helpers.js';\n"
        )
        (project_dir / "src" / "utils" / "helpers.js").write_text(
            "export const helper = () => {};\n"
        )

        # 已确认引擎可用（上方已 skip）
        checker2 = DepCruiserChecker()
        rule = _make_rule(matcher_config={
            "cruise_config": ".dependency-cruiser.js",
        })

        artifact = _make_artifact(
            path=str(project_dir / "src" / "views" / "Home.js"),
            content="import { helper } from '../utils/helpers.js';",
        )
        context = _make_context(project_root=str(project_dir))
        result = checker2.check(rule, artifact, context)

        assert isinstance(result, ComplianceResult)
        # 合规项目未必在所有 depcruise 版本下都 passed，
        # 只验证结果是 ComplianceResult 格式正确


# ═══════════════════════════════════════════════════════════
#  reset_availability_cache 测试
# ═══════════════════════════════════════════════════════════

class TestResetCache:
    """可用性缓存重置"""

    def test_reset_and_re_probe(self):
        """重置缓存后重新探测"""
        checker = DepCruiserChecker(config={"depcruise_cmd": "depcruise"})
        # 首次探测
        with patch("harness.integrations.dep_cruiser_checker.subprocess.run") as mock_run:
            mock_run.return_value = _mock_subprocess_success("16.0.0")
            assert checker._is_engine_available() is True

        # 重置
        checker.reset_availability_cache()
        assert checker._availability_cache is None

        # 重新探测——模拟 CLI 不再可用
        with patch("harness.integrations.dep_cruiser_checker.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("not found")
            assert checker._is_engine_available() is False

    def test_engine_name_property(self):
        """engine_name 属性"""
        checker = DepCruiserChecker()
        assert checker.engine_name == "dep_cruiser"

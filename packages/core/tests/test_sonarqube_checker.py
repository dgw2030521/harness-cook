"""
SonarQubeChecker 单元测试与集成测试

测试覆盖：
- SEVERITY_MAP 正确映射
- _resolve_rule_key 优先级
- _parse_sonarqube_response 解析逻辑
- _max_severity 逻辑
- _probe_engine HTTP 调用（mock urllib）
- _call_engine HTTP 调用（mock urllib）
- 引擎不可用时的降级回退
- 完整 check 流程
- @pytest.mark.sonarqube 集成测试
"""

import base64
import json
import urllib.error
import urllib.request
from unittest.mock import MagicMock, Mock, patch

import pytest

from harness.integrations.sonarqube_checker import (
    SEVERITY_MAP,
    SonarQubeChecker,
)
from harness.types import (
    Artifact,
    ComplianceCategory,
    ComplianceResult,
    ComplianceRule,
    ScanContext,
)


# ─── 通用 fixtures ──────────────────────────────────────────────


@pytest.fixture
def checker() -> SonarQubeChecker:
    """创建默认配置的 SonarQubeChecker 实例"""
    return SonarQubeChecker(config={
        "sonarqube_url": "https://sonar.example.com",
        "sonarqube_token": "squ_test_token",
        "project_key": "my-project",
    })


@pytest.fixture
def checker_no_url() -> SonarQubeChecker:
    """创建缺少 sonarqube_url 的 checker——不可用"""
    return SonarQubeChecker(config={
        "sonarqube_token": "squ_test_token",
    })


@pytest.fixture
def checker_no_token() -> SonarQubeChecker:
    """创建缺少 sonarqube_token 的 checker——可用但无鉴权"""
    return SonarQubeChecker(config={
        "sonarqube_url": "https://sonar.example.com",
    })


@pytest.fixture
def rule_with_matcher_config() -> ComplianceRule:
    """matcher_config 中指定 rule_key 的规则"""
    return ComplianceRule(
        id="SQ-001",
        category=ComplianceCategory.SECURITY,
        pattern="python:S2209",
        severity="high",
        description="SonarQube 安全规则",
        remediation="修复安全隐患",
        auto_fixable=False,
        languages=["python"],
        matcher_type="sonarqube",
        matcher_config={"rule_key": "python:S1234"},
    )


@pytest.fixture
def rule_without_matcher_config() -> ComplianceRule:
    """matcher_config 中没有 rule_key，仅靠 pattern 的规则"""
    return ComplianceRule(
        id="SQ-002",
        category=ComplianceCategory.STYLE,
        pattern="python:S2209",
        severity="medium",
        description="SonarQube 风格规则",
        remediation="修复代码风格",
        auto_fixable=False,
        languages=["python"],
        matcher_type="sonarqube",
        matcher_config={},
    )


@pytest.fixture
def artifact() -> Artifact:
    """测试用代码产出物"""
    return Artifact(
        type="code",
        path="src/main.py",
        content="def main(): pass",
        metadata={"language": "python"},
    )


@pytest.fixture
def context() -> ScanContext:
    """测试用扫描上下文"""
    return ScanContext(
        artifacts=[],
        dependency_graph=None,
        project_root="/projects/my-project",
        metadata={},
    )


# ─── 1. SEVERITY_MAP 测试 ───────────────────────────────────────


class TestSeverityMap:
    """SEVERITY_MAP 映射正确性"""

    def test_all_sonarqube_severity_mapped(self):
        """SonarQube 全部 5 个严重级别都有映射"""
        expected_keys = {"BLOCKER", "CRITICAL", "MAJOR", "MINOR", "INFO"}
        assert set(SEVERITY_MAP.keys()) == expected_keys

    def test_blocker_maps_to_critical(self):
        assert SEVERITY_MAP["BLOCKER"] == "critical"

    def test_critical_maps_to_high(self):
        assert SEVERITY_MAP["CRITICAL"] == "high"

    def test_major_maps_to_medium(self):
        assert SEVERITY_MAP["MAJOR"] == "medium"

    def test_minor_maps_to_low(self):
        assert SEVERITY_MAP["MINOR"] == "low"

    def test_info_maps_to_info(self):
        assert SEVERITY_MAP["INFO"] == "info"

    def test_unknown_severity_defaults_to_medium(self):
        """SEVERITY_MAP.get(unknown, "medium") 的降级行为"""
        assert SEVERITY_MAP.get("UNKNOWN", "medium") == "medium"


# ─── 2. _resolve_rule_key 测试 ──────────────────────────────────


class TestResolveRuleKey:
    """_resolve_rule_key 优先级：matcher_config.rule_key > rule.pattern"""

    def test_matcher_config_rule_key_takes_priority(
        self, checker, rule_with_matcher_config,
    ):
        """matcher_config 中的 rule_key 优先于 pattern"""
        result = checker._resolve_rule_key(rule_with_matcher_config)
        assert result == "python:S1234"

    def test_pattern_as_fallback(
        self, checker, rule_without_matcher_config,
    ):
        """matcher_config 无 rule_key 时使用 pattern"""
        result = checker._resolve_rule_key(rule_without_matcher_config)
        assert result == "python:S2209"

    def test_empty_matcher_config_uses_pattern(self, checker):
        """matcher_config 为空字典时使用 pattern"""
        rule = ComplianceRule(
            id="SQ-003",
            category=ComplianceCategory.SECURITY,
            pattern="java:S1111",
            severity="low",
            description="测试",
            remediation="修复",
            matcher_type="sonarqube",
            matcher_config={},
        )
        assert checker._resolve_rule_key(rule) == "java:S1111"

    def test_matcher_config_rule_key_not_string(self, checker):
        """matcher_config.rule_key 为非字符串但非空——仍优先"""
        rule = ComplianceRule(
            id="SQ-004",
            category=ComplianceCategory.SECURITY,
            pattern="fallback-pattern",
            severity="low",
            description="测试",
            remediation="修复",
            matcher_type="sonarqube",
            matcher_config={"rule_key": 12345},
        )
        # rule_key=12345 是 truthy，所以优先返回
        result = checker._resolve_rule_key(rule)
        assert result == 12345


# ─── 3. _parse_sonarqube_response 测试 ───────────────────────────


class TestParseSonarQubeResponse:
    """_parse_sonarqube_response 解析逻辑"""

    def test_no_issues_returns_passed(
        self, checker, rule_with_matcher_config,
    ):
        """无 issues 时返回 passed=True"""
        request = {
            "severity": "high",
            "rule_id": "SQ-001",
        }
        data = {"issues": [], "total": 0}
        result = checker._parse_sonarqube_response(data, request)
        assert result["passed"] is True
        assert result["findings"] == []
        assert result["severity"] == "high"

    def test_single_issue_parsed_correctly(
        self, checker, rule_with_matcher_config,
    ):
        """单个 issue 正确解析"""
        request = {
            "severity": "medium",
            "rule_id": "SQ-001",
        }
        data = {
            "issues": [{
                "rule": "python:S1234",
                "severity": "MAJOR",
                "message": "Remove this unused variable",
                "component": "my-project:src/main.py",
                "line": 42,
            }],
            "total": 1,
        }
        result = checker._parse_sonarqube_response(data, request)
        assert result["passed"] is False
        assert len(result["findings"]) == 1
        assert "python:S1234" in result["findings"][0]
        assert "Remove this unused variable" in result["findings"][0]

    def test_multiple_issues_parsed(
        self, checker, rule_with_matcher_config,
    ):
        """多个 issues 全部解析到 findings 和 locations"""
        request = {
            "severity": "medium",
            "rule_id": "SQ-001",
        }
        data = {
            "issues": [
                {
                    "rule": "python:S1234",
                    "severity": "BLOCKER",
                    "message": "Critical bug",
                    "component": "my-project:src/main.py",
                    "line": 10,
                },
                {
                    "rule": "python:S5678",
                    "severity": "MINOR",
                    "message": "Style issue",
                    "component": "my-project:src/utils.py",
                    "line": 20,
                },
            ],
            "total": 2,
        }
        result = checker._parse_sonarqube_response(data, request)
        assert result["passed"] is False
        assert len(result["findings"]) == 2
        assert len(result["locations"]) == 2

    def test_issue_with_missing_message_defaults(
        self, checker,
    ):
        """issue 缺少 message 时使用默认文本"""
        request = {"severity": "low", "rule_id": "SQ-005"}
        data = {
            "issues": [{
                "rule": "java:S111",
                "severity": "INFO",
                "component": "proj:src/Foo.java",
                "line": 5,
            }],
            "total": 1,
        }
        result = checker._parse_sonarqube_response(data, request)
        assert "SonarQube issue" in result["findings"][0]

    def test_issue_with_unknown_severity_maps_to_medium(
        self, checker,
    ):
        """未知 SonarQube severity 映射为 medium"""
        request = {"severity": "medium", "rule_id": "SQ-006"}
        data = {
            "issues": [{
                "rule": "custom:R001",
                "severity": "UNKNOWN_LEVEL",
                "message": "自定义规则",
                "component": "proj:src/bar.py",
                "line": 1,
            }],
            "total": 1,
        }
        result = checker._parse_sonarqube_response(data, request)
        loc = result["locations"][0]
        assert loc["sonarqube_severity"] == "medium"

    def test_locations_include_engine_and_sonarqube_severity(
        self, checker,
    ):
        """locations 中包含 engine 和 sonarqube_severity 字段"""
        request = {"severity": "high", "rule_id": "SQ-007"}
        data = {
            "issues": [{
                "rule": "python:S100",
                "severity": "CRITICAL",
                "message": "Bug",
                "component": "my-project:src/app.py",
                "line": 30,
            }],
            "total": 1,
        }
        result = checker._parse_sonarqube_response(data, request)
        loc = result["locations"][0]
        assert loc["engine"] == "sonarqube"
        assert loc["sonarqube_severity"] == "high"

    def test_remediation_includes_total_count(
        self, checker,
    ):
        """remediation 消息中包含 issue 总数"""
        request = {"severity": "low", "rule_id": "SQ-008"}
        data = {
            "issues": [
                {"rule": "r1", "severity": "MINOR", "message": "m1", "component": "c1", "line": 1},
                {"rule": "r2", "severity": "INFO", "message": "m2", "component": "c2", "line": 2},
            ],
            "total": 5,
        }
        result = checker._parse_sonarqube_response(data, request)
        assert "5 SonarQube issues" in result["remediation"]

    def test_empty_issues_list_uses_total_zero(
        self, checker,
    ):
        """issues 为空列表，total 缺失时默认 0"""
        request = {"severity": "low", "rule_id": "SQ-009"}
        data = {"issues": []}
        result = checker._parse_sonarqube_response(data, request)
        assert result["passed"] is True
        assert result["findings"] == []


# ─── 4. _max_severity 测试 ──────────────────────────────────────


class TestMaxSeverity:
    """_max_severity 取最严重级别"""

    def test_single_blocker_issue(self, checker):
        """单个 BLOCKER issue → critical"""
        issues = [{"severity": "BLOCKER"}]
        assert checker._max_severity(issues) == "critical"

    def test_single_info_issue(self, checker):
        """单个 INFO issue → info"""
        issues = [{"severity": "INFO"}]
        assert checker._max_severity(issues) == "info"

    def test_mixed_severity_picks_most_severe(self, checker):
        """混合严重级别取最严重的"""
        issues = [
            {"severity": "MINOR"},
            {"severity": "CRITICAL"},
            {"severity": "INFO"},
            {"severity": "MAJOR"},
        ]
        assert checker._max_severity(issues) == "high"  # CRITICAL → high

    def test_all_same_severity(self, checker):
        """所有 issue 同级别 → 该级别"""
        issues = [{"severity": "MAJOR"}, {"severity": "MAJOR"}]
        assert checker._max_severity(issues) == "medium"

    def test_unknown_severity_treated_as_medium(self, checker):
        """未知 severity 映射为 medium（SEVERITY_MAP 降级）"""
        issues = [{"severity": "CUSTOM_LEVEL"}]
        assert checker._max_severity(issues) == "medium"

    def test_blocker_overrides_everything(self, checker):
        """BLOCKER 是最高级别，覆盖所有其他"""
        issues = [
            {"severity": "INFO"},
            {"severity": "MINOR"},
            {"severity": "MAJOR"},
            {"severity": "CRITICAL"},
            {"severity": "BLOCKER"},
        ]
        assert checker._max_severity(issues) == "critical"

    def test_missing_severity_defaults_to_medium(self, checker):
        """issue 缺少 severity 字段 → 默认 medium"""
        issues = [{"rule": "r1"}]  # 无 severity 字段
        assert checker._max_severity(issues) == "medium"


# ─── 5. _probe_engine 测试 ──────────────────────────────────────


class TestProbeEngine:
    """_probe_engine HTTP 可用性探测"""

    def test_no_url_returns_false(self, checker_no_url):
        """缺少 sonarqube_url → 返回 False"""
        assert checker_no_url._probe_engine() is False

    def test_successful_probe_with_token(self, checker):
        """SonarQube 返回 UP 状态 + token 鉴权 → True"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "UP"}).encode()
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch("urllib.request.Request") as mock_req_cls:
                mock_req = MagicMock()
                mock_req_cls.return_value = mock_req
                result = checker._probe_engine()

        assert result is True
        # 验证 Authorization header 设置了 Basic auth
        mock_req.add_header.assert_called()
        auth_call_args = mock_req.add_header.call_args_list
        auth_found = any(
            call[0][0] == "Authorization" and "Basic" in call[0][1]
            for call in auth_call_args
        )
        assert auth_found

    def test_probe_without_token(self, checker_no_token):
        """无 token 时不设置 Authorization header"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "UP"}).encode()
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch("urllib.request.Request") as mock_req_cls:
                mock_req = MagicMock()
                mock_req_cls.return_value = mock_req
                result = checker_no_token._probe_engine()

        assert result is True
        # 不应设置 Authorization header
        auth_found = any(
            call[0][0] == "Authorization"
            for call in mock_req.add_header.call_args_list
        )
        assert auth_found is False

    def test_probe_starting_status(self, checker):
        """SonarQube STARTING 状态 → True"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "STARTING"}).encode()
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch("urllib.request.Request", return_value=MagicMock()):
                assert checker._probe_engine() is True

    def test_probe_restarting_status(self, checker):
        """SonarQube RESTARTING 状态 → True"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "RESTARTING"}).encode()
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch("urllib.request.Request", return_value=MagicMock()):
                assert checker._probe_engine() is True

    def test_probe_down_status(self, checker):
        """SonarQube DOWN 状态 → False"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "DOWN"}).encode()
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch("urllib.request.Request", return_value=MagicMock()):
                assert checker._probe_engine() is False

    def test_probe_url_error(self, checker):
        """连接失败 (URLError) → False"""
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            with patch("urllib.request.Request", return_value=MagicMock()):
                assert checker._probe_engine() is False

    def test_probe_generic_exception(self, checker):
        """通用异常 → False"""
        with patch(
            "urllib.request.urlopen",
            side_effect=Exception("Unexpected error"),
        ):
            with patch("urllib.request.Request", return_value=MagicMock()):
                assert checker._probe_engine() is False

    def test_probe_status_url_includes_api_path(self, checker):
        """_probe_engine 拼接了正确的 /api/system/status 路径"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "UP"}).encode()
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            with patch("urllib.request.Request") as mock_req_cls:
                mock_req = MagicMock()
                mock_req_cls.return_value = mock_req
                checker._probe_engine()

        # Request 应使用包含 /api/system/status 的 URL
        called_url = mock_req_cls.call_args[0][0]
        assert "/api/system/status" in called_url

    def test_probe_trailing_slash_handled(self):
        """sonarqube_url 带尾部斜杠时正确拼接"""
        checker = SonarQubeChecker(config={
            "sonarqube_url": "https://sonar.example.com/",
            "sonarqube_token": "squ_token",
        })
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "UP"}).encode()
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch("urllib.request.Request") as mock_req_cls:
                mock_req = MagicMock()
                mock_req_cls.return_value = mock_req
                checker._probe_engine()

        called_url = mock_req_cls.call_args[0][0]
        # rstrip('/') 处理后不应有双斜杠
        assert "sonar.example.com/api/system/status" in called_url


# ─── 6. _call_engine 测试 ───────────────────────────────────────


class TestCallEngine:
    """_call_engine HTTP API 调用"""

    def test_successful_call_returns_parsed_data(self, checker):
        """成功调用返回 _parse_sonarqube_response 的结果"""
        request = {
            "url": "https://sonar.example.com",
            "token": "squ_test_token",
            "project_key": "my-project",
            "rule_key": "python:S1234",
            "severity": "high",
            "rule_id": "SQ-001",
            "file_path": "src/main.py",
        }
        sonarqube_data = {
            "issues": [{
                "rule": "python:S1234",
                "severity": "CRITICAL",
                "message": "Security vulnerability",
                "component": "my-project:src/main.py",
                "line": 15,
            }],
            "total": 1,
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(sonarqube_data).encode()
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch("urllib.request.Request") as mock_req_cls:
                mock_req = MagicMock()
                mock_req_cls.return_value = mock_req
                result = checker._call_engine(request)

        assert result["passed"] is False
        assert len(result["findings"]) == 1

    def test_api_url_includes_correct_query_params(self, checker):
        """API URL 包含 projectKey、rules、ps 参数"""
        request = {
            "url": "https://sonar.example.com",
            "token": "squ_test_token",
            "project_key": "my-project",
            "rule_key": "python:S1234",
            "severity": "high",
            "rule_id": "SQ-001",
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"issues": [], "total": 0}).encode()
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            with patch("urllib.request.Request") as mock_req_cls:
                mock_req = MagicMock()
                mock_req_cls.return_value = mock_req
                checker._call_engine(request)

        called_url = mock_req_cls.call_args[0][0]
        assert "projectKey=my-project" in called_url
        assert "rules=python:S1234" in called_url
        assert "ps=100" in called_url

    def test_api_url_includes_file_path_filter(self, checker):
        """file_path 非空时添加 componentKeys 参数"""
        request = {
            "url": "https://sonar.example.com",
            "token": "squ_test_token",
            "project_key": "my-project",
            "rule_key": "python:S1234",
            "severity": "high",
            "rule_id": "SQ-001",
            "file_path": "src/main.py",
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"issues": [], "total": 0}).encode()
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch("urllib.request.Request") as mock_req_cls:
                mock_req = MagicMock()
                mock_req_cls.return_value = mock_req
                checker._call_engine(request)

        called_url = mock_req_cls.call_args[0][0]
        assert "componentKeys=my-project:src/main.py" in called_url

    def test_api_url_no_file_path_no_component_keys(self, checker):
        """file_path 为空时不添加 componentKeys 参数"""
        request = {
            "url": "https://sonar.example.com",
            "token": "squ_test_token",
            "project_key": "my-project",
            "rule_key": "python:S1234",
            "severity": "high",
            "rule_id": "SQ-001",
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"issues": [], "total": 0}).encode()
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch("urllib.request.Request") as mock_req_cls:
                mock_req = MagicMock()
                mock_req_cls.return_value = mock_req
                checker._call_engine(request)

        called_url = mock_req_cls.call_args[0][0]
        assert "componentKeys" not in called_url

    def test_call_engine_raises_on_url_error(self, checker):
        """URLError 时抛出异常（让基类回退）"""
        request = {
            "url": "https://sonar.example.com",
            "token": "squ_test_token",
            "project_key": "my-project",
            "rule_key": "python:S1234",
            "severity": "high",
            "rule_id": "SQ-001",
        }

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            with patch("urllib.request.Request", return_value=MagicMock()):
                with pytest.raises(urllib.error.URLError):
                    checker._call_engine(request)

    def test_call_engine_raises_on_generic_exception(self, checker):
        """通用异常时抛出（让基类回退）"""
        request = {
            "url": "https://sonar.example.com",
            "token": "squ_test_token",
            "project_key": "my-project",
            "rule_key": "python:S1234",
            "severity": "high",
            "rule_id": "SQ-001",
        }

        with patch(
            "urllib.request.urlopen",
            side_effect=Exception("Unexpected"),
        ):
            with patch("urllib.request.Request", return_value=MagicMock()):
                with pytest.raises(Exception):
                    checker._call_engine(request)

    def test_call_engine_sets_basic_auth_header(self, checker):
        """有 token 时设置 Basic Authorization header"""
        request = {
            "url": "https://sonar.example.com",
            "token": "squ_test_token",
            "project_key": "my-project",
            "rule_key": "python:S1234",
            "severity": "high",
            "rule_id": "SQ-001",
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"issues": [], "total": 0}).encode()
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch("urllib.request.Request") as mock_req_cls:
                mock_req = MagicMock()
                mock_req_cls.return_value = mock_req
                checker._call_engine(request)

        # 验证 Basic auth 使用 token: 格式
        expected_creds = base64.b64encode("squ_test_token:".encode()).decode()
        auth_calls = [
            call for call in mock_req.add_header.call_args_list
            if call[0][0] == "Authorization"
        ]
        assert len(auth_calls) == 1
        assert f"Basic {expected_creds}" in auth_calls[0][0][1]


# ─── 7. 降级回退测试 ────────────────────────────────────────────


class TestFallback:
    """引擎不可用时回退到 fallback_checker"""

    def test_engine_unavailable_falls_back(
        self, checker_no_url, rule_with_matcher_config, artifact, context,
    ):
        """引擎不可用时，check() 回退到 RegexChecker"""
        # checker_no_url 没有 sonarqube_url，_probe_engine 返回 False
        # 强制重置缓存确保探测执行
        checker_no_url.reset_availability_cache()

        result = checker_no_url.check(
            rule_with_matcher_config, artifact, context,
        )
        # 回退到 RegexChecker，RegexChecker 用 pattern 做正则匹配
        # artifact.content 不匹配 pattern="python:S2209" → passed=True
        assert isinstance(result, ComplianceResult)
        assert result.rule_id == rule_with_matcher_config.id

    def test_probe_failure_falls_back(
        self, checker, rule_with_matcher_config, artifact, context,
    ):
        """_probe_engine 连接失败 → 回退"""
        checker.reset_availability_cache()

        with patch.object(checker, "_probe_engine", return_value=False):
            result = checker.check(
                rule_with_matcher_config, artifact, context,
            )
        assert isinstance(result, ComplianceResult)
        assert result.rule_id == rule_with_matcher_config.id

    def test_call_engine_failure_falls_back(
        self, checker, rule_with_matcher_config, artifact, context,
    ):
        """_call_engine 异常 → 回退到 fallback"""
        checker.reset_availability_cache()

        with patch.object(checker, "_probe_engine", return_value=True):
            with patch.object(
                checker, "_call_engine",
                side_effect=urllib.error.URLError("Connection lost"),
            ):
                result = checker.check(
                    rule_with_matcher_config, artifact, context,
                )
        assert isinstance(result, ComplianceResult)
        assert result.rule_id == rule_with_matcher_config.id

    def test_translate_response_failure_falls_back(
        self, checker, rule_with_matcher_config, artifact, context,
    ):
        """_translate_response 异常 → 回退"""
        checker.reset_availability_cache()

        engine_response = {"passed": True, "findings": [], "severity": "high"}

        with patch.object(checker, "_probe_engine", return_value=True):
            with patch.object(checker, "_call_engine", return_value=engine_response):
                with patch.object(
                    checker, "_translate_response",
                    side_effect=ValueError("Translation error"),
                ):
                    result = checker.check(
                        rule_with_matcher_config, artifact, context,
                    )
        assert isinstance(result, ComplianceResult)
        assert result.rule_id == rule_with_matcher_config.id


# ─── 8. 完整 check 流程测试 ──────────────────────────────────────


class TestCheckFlow:
    """完整 check 流程：探测 → 翻译 → 调用 → 翻译响应"""

    def test_full_check_passed_no_issues(
        self, checker, rule_with_matcher_config, artifact, context,
    ):
        """完整流程：无 issues → passed=True"""
        checker.reset_availability_cache()

        engine_response = {
            "passed": True,
            "findings": [],
            "severity": "high",
        }

        with patch.object(checker, "_probe_engine", return_value=True):
            with patch.object(checker, "_call_engine", return_value=engine_response):
                result = checker.check(
                    rule_with_matcher_config, artifact, context,
                )

        assert result.rule_id == "SQ-001"
        assert result.passed is True
        assert result.findings == []
        assert result.severity == "high"

    def test_full_check_with_issues(
        self, checker, rule_with_matcher_config, artifact, context,
    ):
        """完整流程：有 issues → passed=False"""
        checker.reset_availability_cache()

        engine_response = {
            "passed": False,
            "findings": ["SonarQube (python:S1234): Security vulnerability"],
            "severity": "critical",
            "remediation": "Fix 1 SonarQube issues (reference mode)",
            "locations": [
                {
                    "line": 15,
                    "match": "Security vulnerability",
                    "start": 0,
                    "end": 0,
                    "file": "my-project:src/main.py",
                    "sonarqube_severity": "high",
                    "engine": "sonarqube",
                },
            ],
        }

        with patch.object(checker, "_probe_engine", return_value=True):
            with patch.object(checker, "_call_engine", return_value=engine_response):
                result = checker.check(
                    rule_with_matcher_config, artifact, context,
                )

        assert result.rule_id == "SQ-001"
        assert result.passed is False
        assert len(result.findings) == 1
        assert result.severity == "critical"
        assert result.remediation is not None
        assert len(result.locations) == 1

    def test_check_caches_availability(
        self, checker, rule_with_matcher_config, artifact, context,
    ):
        """check() 只探测一次，后续调用使用缓存"""
        checker.reset_availability_cache()

        engine_response = {
            "passed": True,
            "findings": [],
            "severity": "high",
        }

        with patch.object(checker, "_probe_engine", return_value=True) as mock_probe:
            with patch.object(checker, "_call_engine", return_value=engine_response):
                # 第一次 check
                checker.check(rule_with_matcher_config, artifact, context)
                # 第二次 check
                checker.check(rule_with_matcher_config, artifact, context)

        # _probe_engine 只调用一次（第二次用缓存）
        assert mock_probe.call_count == 1

    def test_translate_request_with_project_key_from_config(
        self, checker, rule_with_matcher_config, artifact, context,
    ):
        """_translate_request 使用 config 中的 project_key"""
        request = checker._translate_request(
            rule_with_matcher_config, artifact, context,
        )
        assert request["project_key"] == "my-project"
        assert request["rule_key"] == "python:S1234"

    def test_translate_request_infers_project_key_from_root(
        self, checker, rule_without_matcher_config, artifact,
    ):
        """config 无 project_key 时从 context.project_root 推断"""
        # checker 有 project_key 配置，创建一个没有的
        checker_no_pk = SonarQubeChecker(config={
            "sonarqube_url": "https://sonar.example.com",
            "sonarqube_token": "squ_token",
        })
        ctx = ScanContext(
            artifacts=[],
            project_root="/projects/my-inferred-project",
        )
        request = checker_no_pk._translate_request(
            rule_without_matcher_config, artifact, ctx,
        )
        assert request["project_key"] == "my-inferred-project"

    def test_translate_request_no_project_key_no_root(
        self, checker_no_url, rule_without_matcher_config, artifact,
    ):
        """config 无 project_key 且 context 无 project_root → project_key 为空"""
        ctx = ScanContext(artifacts=[], project_root=None)
        request = checker_no_url._translate_request(
            rule_without_matcher_config, artifact, ctx,
        )
        assert request["project_key"] == ""

    def test_translate_response_produces_correct_result(
        self, checker, rule_with_matcher_config,
    ):
        """_translate_response 使用基类默认实现，正确构造 ComplianceResult"""
        response = {
            "passed": False,
            "findings": ["Issue found"],
            "severity": "critical",
            "remediation": "Fix the issue",
            "locations": [{"line": 10, "match": "bug", "start": 0, "end": 0}],
        }
        result = checker._translate_response(response, rule_with_matcher_config)
        assert result.rule_id == "SQ-001"
        assert result.passed is False
        assert result.severity == "critical"
        assert result.findings == ["Issue found"]
        assert result.remediation == "Fix the issue"
        assert len(result.locations) == 1

    def test_translate_response_remediation_fallback(
        self, checker, rule_with_matcher_config,
    ):
        """response 无 remediation 时回退到 rule.remediation"""
        response = {
            "passed": True,
            "findings": [],
            "severity": "high",
        }
        result = checker._translate_response(response, rule_with_matcher_config)
        assert result.remediation == rule_with_matcher_config.remediation

    def test_translate_response_severity_fallback(
        self, checker, rule_with_matcher_config,
    ):
        """response 无 severity 时回退到 rule.severity"""
        response = {
            "passed": True,
            "findings": [],
        }
        result = checker._translate_response(response, rule_with_matcher_config)
        assert result.severity == rule_with_matcher_config.severity

    def test_engine_name_property(self, checker):
        """engine_name 属性返回 'sonarqube'"""
        assert checker.engine_name == "sonarqube"


# ─── 9. 默认构造测试 ────────────────────────────────────────────


class TestDefaultConstruction:
    """默认构造器行为"""

    def test_default_config_is_empty_dict(self):
        """无参数构造时 config 默认为空字典"""
        checker = SonarQubeChecker()
        assert checker._config == {}

    def test_none_config_becomes_empty_dict(self):
        """config=None 时转为空字典"""
        checker = SonarQubeChecker(config=None)
        assert checker._config == {}

    def test_custom_config_preserved(self):
        """自定义 config 正确保存"""
        config = {"sonarqube_url": "https://custom.com", "custom_key": "value"}
        checker = SonarQubeChecker(config=config)
        assert checker._config == config


# ─── 10. @pytest.mark.sonarqube 集成测试 ──────────────────────────


@pytest.mark.sonarqube
class TestSonarQubeIntegration:
    """集成测试标记——需要真实 SonarQube 实例

    运行方式：pytest -m sonarqube（仅在 SonarQube 可用时运行）

    这些测试默认 mock HTTP 调用，但验证端到端流程的一致性。
    如需测试真实 SonarQube，取消 mock 并配置环境变量。
    """

    @pytest.mark.sonarqube
    def test_integration_full_flow_mocked(
        self, checker, rule_with_matcher_config, artifact, context,
    ):
        """端到端流程（mock HTTP）——从 check 到 ComplianceResult"""
        checker.reset_availability_cache()

        # 模拟 SonarQube 返回 2 个 issues
        sonarqube_raw = {
            "issues": [
                {
                    "rule": "python:S1234",
                    "severity": "BLOCKER",
                    "message": "Critical SQL injection",
                    "component": "my-project:src/main.py",
                    "line": 42,
                },
                {
                    "rule": "python:S1234",
                    "severity": "MAJOR",
                    "message": "Unused local variable",
                    "component": "my-project:src/main.py",
                    "line": 58,
                },
            ],
            "total": 2,
        }

        # 模拟 _probe_engine 返回 True
        # 模拟 urlopen 返回 SonarQube API 响应（_call_engine 内部调用）
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(sonarqube_raw).encode()
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)

        with patch.object(checker, "_probe_engine", return_value=True):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                with patch("urllib.request.Request", return_value=MagicMock()):
                    result = checker.check(
                        rule_with_matcher_config, artifact, context,
                    )

        # 验证结果
        assert isinstance(result, ComplianceResult)
        assert result.rule_id == "SQ-001"
        assert result.passed is False
        assert len(result.findings) == 2
        assert result.severity == "critical"  # BLOCKER → critical
        assert "python:S1234" in result.findings[0]
        assert result.remediation is not None
        assert len(result.locations) == 2
        # locations 中每个都有 engine 标记
        for loc in result.locations:
            assert loc.get("engine") == "sonarqube"

    @pytest.mark.sonarqube
    def test_integration_passed_flow_mocked(
        self, checker, rule_with_matcher_config, artifact, context,
    ):
        """端到端流程（mock HTTP）——无 issues → passed"""
        checker.reset_availability_cache()

        sonarqube_raw = {"issues": [], "total": 0}

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(sonarqube_raw).encode()
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)

        with patch.object(checker, "_probe_engine", return_value=True):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                with patch("urllib.request.Request", return_value=MagicMock()):
                    result = checker.check(
                        rule_with_matcher_config, artifact, context,
                    )

        assert result.passed is True
        assert result.findings == []
        assert result.severity == "high"

    @pytest.mark.sonarqube
    def test_integration_fallback_flow_mocked(
        self, checker_no_url, rule_with_matcher_config, artifact, context,
    ):
        """端到端流程（mock HTTP）——引擎不可用 → 回退"""
        checker_no_url.reset_availability_cache()

        result = checker_no_url.check(
            rule_with_matcher_config, artifact, context,
        )

        assert isinstance(result, ComplianceResult)
        assert result.rule_id == rule_with_matcher_config.id

    @pytest.mark.sonarqube
    def test_integration_multiple_categories(
        self, checker, artifact, context,
    ):
        """端到端流程（mock HTTP）——多种 ComplianceCategory"""
        checker.reset_availability_cache()

        # 不同 category 的规则
        rules = [
            ComplianceRule(
                id="SQ-SEC",
                category=ComplianceCategory.SECURITY,
                pattern="python:S1234",
                severity="critical",
                description="安全",
                remediation="修复安全",
                matcher_type="sonarqube",
                matcher_config={"rule_key": "python:S1234"},
            ),
            ComplianceRule(
                id="SQ-STYLE",
                category=ComplianceCategory.STYLE,
                pattern="python:S2209",
                severity="low",
                description="风格",
                remediation="修复风格",
                matcher_type="sonarqube",
                matcher_config={"rule_key": "python:S2209"},
            ),
        ]

        engine_response = {
            "passed": True,
            "findings": [],
            "severity": "medium",
        }

        with patch.object(checker, "_probe_engine", return_value=True):
            with patch.object(checker, "_call_engine", return_value=engine_response):
                results = [
                    checker.check(rule, artifact, context)
                    for rule in rules
                ]

        for result in results:
            assert isinstance(result, ComplianceResult)
            assert result.passed is True

    @pytest.mark.sonarqube
    def test_integration_availability_cache_persists(
        self, checker, rule_with_matcher_config, artifact, context,
    ):
        """端到端流程——可用性缓存跨多次 check 保持"""
        checker.reset_availability_cache()

        engine_response = {
            "passed": True,
            "findings": [],
            "severity": "high",
        }

        with patch.object(checker, "_probe_engine", return_value=True) as mock_probe:
            with patch.object(checker, "_call_engine", return_value=engine_response):
                for _ in range(5):
                    checker.check(rule_with_matcher_config, artifact, context)

        # _probe_engine 只在首次 check 时调用
        assert mock_probe.call_count == 1


# ─── 11. ComplianceResult 字段完整性验证 ──────────────────────────


class TestComplianceResultFields:
    """确保只使用 ComplianceResult 的合法字段"""

    def test_result_has_exactly_six_fields(
        self, checker, rule_with_matcher_config, artifact, context,
    ):
        """ComplianceResult 只包含 6 个合法字段"""
        checker.reset_availability_cache()

        engine_response = {
            "passed": False,
            "findings": ["Issue 1"],
            "severity": "high",
            "remediation": "Fix it",
            "locations": [{"line": 10, "match": "x", "start": 0, "end": 0}],
        }

        with patch.object(checker, "_probe_engine", return_value=True):
            with patch.object(checker, "_call_engine", return_value=engine_response):
                result = checker.check(
                    rule_with_matcher_config, artifact, context,
                )

        # ComplianceResult 的合法字段
        expected_fields = {"rule_id", "passed", "severity", "findings", "remediation", "locations"}
        actual_fields = {f for f in result.__dataclass_fields__}
        assert actual_fields == expected_fields

    def test_result_no_extra_fields(
        self, checker, rule_with_matcher_config, artifact, context,
    ):
        """ComplianceResult 不包含非法字段（如 message, details）"""
        checker.reset_availability_cache()

        engine_response = {
            "passed": True,
            "findings": [],
            "severity": "high",
        }

        with patch.object(checker, "_probe_engine", return_value=True):
            with patch.object(checker, "_call_engine", return_value=engine_response):
                result = checker.check(
                    rule_with_matcher_config, artifact, context,
                )

        # 确认没有非法字段
        assert not hasattr(result, "message")
        assert not hasattr(result, "details")

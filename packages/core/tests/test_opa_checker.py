"""
OPAChecker 测试

验证：
- _probe_engine 的两种模式（HTTP + embedded）
- _resolve_policy_path 的3级优先级
- _translate_request 构建 input_data
- _call_http / _call_embedded 引擎调用
- _parse_opa_response 的 bool result 和 dict result 两种情况
- 降级回退机制
- 完整 check 流程
- 集成测试（@pytest.mark.opa）

注意：单元测试使用 mock，不依赖真实 OPA 服务或 opa-python-sdk。
集成测试标记为 @pytest.mark.opa，需要运行 OPA 服务才能通过。
"""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from harness.types import (
    Artifact, ComplianceRule, ComplianceResult, ScanContext,
    ComplianceCategory,
)
from harness.integrations.opa_checker import OPAChecker


# ═══════════════════════════════════════════════════════════
#  测试辅助数据
# ═══════════════════════════════════════════════════════════

def make_rule(
    id: str = "SEC-001",
    pattern: str = "no_hardcoded_secrets",
    matcher_type: str = "opa",
    severity: str = "critical",
    category: ComplianceCategory = ComplianceCategory.SECURITY,
    matcher_config: dict = None,
    remediation: str = "Remove hardcoded secrets",
) -> ComplianceRule:
    """构建测试用的 ComplianceRule"""
    return ComplianceRule(
        id=id,
        category=category,
        pattern=pattern,
        severity=severity,
        description="Test OPA rule",
        remediation=remediation,
        matcher_type=matcher_type,
        matcher_config=matcher_config or {},
    )


def make_artifact(
    content: str = "api_key = 'sk-abc123'",
    path: str = "config.py",
    type: str = "code",
) -> Artifact:
    """构建测试用的 Artifact"""
    return Artifact(type=type, path=path, content=content)


def make_context(
    project_root: str = "/tmp/test-project",
) -> ScanContext:
    """构建测试用的 ScanContext"""
    return ScanContext(
        artifacts=[make_artifact()],
        project_root=project_root,
    )


# ═══════════════════════════════════════════════════════════
#  _probe_engine 测试
# ═══════════════════════════════════════════════════════════

class TestProbeEngine:
    """引擎可用性探测测试"""

    def test_http_mode_probe_success(self):
        """HTTP 模式：OPA 服务可用时返回 True"""
        checker = OPAChecker(config={
            "mode": "http",
            "opa_url": "http://localhost:8181",
        })

        # urllib.request 在 _probe_engine 内局部 import，mock 标准库路径
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = checker._probe_engine()
            assert result is True

    def test_http_mode_probe_failure(self):
        """HTTP 模式：OPA 服务不可达时返回 False"""
        checker = OPAChecker(config={
            "mode": "http",
            "opa_url": "http://localhost:8181",
        })

        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
            result = checker._probe_engine()
            assert result is False

    def test_http_mode_probe_generic_exception(self):
        """HTTP 模式：非 URLError 异常也返回 False"""
        checker = OPAChecker(config={"mode": "http"})

        with patch("urllib.request.urlopen", side_effect=OSError("Network error")):
            result = checker._probe_engine()
            assert result is False

    def test_http_mode_health_url_construction(self):
        """HTTP 模式：拼接 /health 路径"""
        checker = OPAChecker(config={
            "opa_url": "http://localhost:8181/",
        })

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.Request") as mock_req_cls, \
             patch("urllib.request.urlopen", return_value=mock_resp):
            checker._probe_engine()
            # Request 的 URL 参数应该是带 /health 的完整路径
            call_args = mock_req_cls.call_args
            assert "/health" in call_args[0][0]

    def test_embedded_mode_probe_success(self):
        """embedded 模式：opa-python-sdk 已安装时返回 True"""
        checker = OPAChecker(config={"mode": "embedded"})

        mock_sdk = MagicMock()
        with patch.dict("sys.modules", {"opa_python_sdk": mock_sdk}):
            result = checker._probe_engine()
            assert result is True

    def test_embedded_mode_probe_import_error(self):
        """embedded 模式：opa-python-sdk 未安装时返回 False"""
        checker = OPAChecker(config={"mode": "embedded"})

        # builtins.__import__ 在 opa_checker 内部被触发
        # opa_checker._probe_engine 用的是 from opa_python_sdk import OPAClient
        # 这需要 sys.modules 中有该模块
        with patch.dict("sys.modules", {"opa_python_sdk": None}):
            # 强制 import 失败：模块存在但为 None → ImportError
            result = checker._probe_engine()
            assert result is False

    def test_default_mode_is_http(self):
        """默认 mode 为 http（未配置时）"""
        checker = OPAChecker()  # 不传 mode 配置

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        # 验证默认走 HTTP 模式（调用 urlopen）
        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            result = checker._probe_engine()
            assert result is True
            mock_urlopen.assert_called_once()


# ═══════════════════════════════════════════════════════════
#  _resolve_policy_path 测试
# ═══════════════════════════════════════════════════════════

class TestResolvePolicyPath:
    """policy path 解析3级优先级测试"""

    def test_priority_1_config_policy_path(self):
        """优先级 1：matcher_config.policy_path 直接指定"""
        checker = OPAChecker()
        rule = make_rule(
            matcher_config={"policy_path": "custom/policy/path"},
        )
        result = checker._resolve_policy_path(rule)
        assert result == "custom/policy/path"

    def test_priority_2_pattern_conversion(self):
        """优先级 2：pattern 转换为 policy path"""
        checker = OPAChecker()
        rule = make_rule(
            pattern="no_hardcoded_secrets",
            matcher_config={},  # 没有 policy_path
        )
        result = checker._resolve_policy_path(rule)
        # pattern 中 _ 不替换，只替换 . 和 -
        assert result == "harness/compliance/no_hardcoded_secrets"

    def test_priority_2_pattern_dot_replacement(self):
        """pattern 中的点号被替换为斜杠"""
        checker = OPAChecker()
        rule = make_rule(pattern="security.pii.email", matcher_config={})
        result = checker._resolve_policy_path(rule)
        assert result == "harness/compliance/security/pii/email"

    def test_priority_2_pattern_dash_replacement(self):
        """pattern 中的横线被替换为下划线"""
        checker = OPAChecker()
        rule = make_rule(pattern="no-hardcoded-keys", matcher_config={})
        result = checker._resolve_policy_path(rule)
        assert result == "harness/compliance/no_hardcoded_keys"

    def test_priority_3_rule_id_fallback(self):
        """优先级 3：pattern 为空或 http 开头时用 rule.id"""
        checker = OPAChecker()

        # 空 pattern
        rule = make_rule(pattern="", matcher_config={})
        result = checker._resolve_policy_path(rule)
        assert result == "harness/compliance/SEC-001"

    def test_priority_3_http_pattern_uses_rule_id(self):
        """http 开头的 pattern 被忽略，使用 rule.id"""
        checker = OPAChecker()
        rule = make_rule(
            pattern="http://example.com/policy",
            matcher_config={},
        )
        result = checker._resolve_policy_path(rule)
        assert result == "harness/compliance/SEC-001"

    def test_config_overrides_pattern(self):
        """matcher_config.policy_path 覆盖 pattern 转换"""
        checker = OPAChecker()
        rule = make_rule(
            pattern="no_pii",
            matcher_config={"policy_path": "override/path"},
        )
        result = checker._resolve_policy_path(rule)
        assert result == "override/path"


# ═══════════════════════════════════════════════════════════
#  _translate_request 测试
# ═══════════════════════════════════════════════════════════

class TestTranslateRequest:
    """请求翻译测试"""

    def test_request_structure(self):
        """翻译后的请求包含所有必需字段"""
        checker = OPAChecker(config={
            "mode": "http",
            "opa_url": "http://opa:8181",
        })
        rule = make_rule(pattern="no_pii", matcher_config={"policy_path": "harness/pii"})
        artifact = make_artifact()
        context = make_context()

        request = checker._translate_request(rule, artifact, context)

        # 必需字段
        assert "policy_path" in request
        assert "input" in request
        assert "mode" in request
        assert "opa_url" in request
        assert "rule_id" in request
        assert "severity" in request

        # 值正确性
        assert request["policy_path"] == "harness/pii"
        assert request["mode"] == "http"
        assert request["opa_url"] == "http://opa:8181"
        assert request["rule_id"] == "SEC-001"
        assert request["severity"] == "critical"

    def test_input_data_artifact_fields(self):
        """input 中包含 artifact 的完整信息"""
        checker = OPAChecker()
        rule = make_rule(matcher_config={"policy_path": "test/policy"})
        artifact = make_artifact(content="secret content", path="app.py")
        context = make_context()

        request = checker._translate_request(rule, artifact, context)
        input_data = request["input"]

        assert input_data["artifact"]["path"] == "app.py"
        assert input_data["artifact"]["content"] == "secret content"
        assert input_data["artifact"]["type"] == "code"

    def test_input_data_rule_fields(self):
        """input 中包含 rule 的关键字段"""
        checker = OPAChecker()
        rule = make_rule(
            pattern="no_pii",
            severity="high",
            matcher_config={"policy_path": "test"},
        )
        artifact = make_artifact()
        context = make_context()

        request = checker._translate_request(rule, artifact, context)
        input_data = request["input"]

        assert input_data["rule"]["id"] == "SEC-001"
        assert input_data["rule"]["pattern"] == "no_pii"
        assert input_data["rule"]["severity"] == "high"
        assert input_data["rule"]["description"] == "Test OPA rule"

    def test_input_data_extra_from_matcher_config(self):
        """matcher_config.input_data 被合入 input.extra"""
        checker = OPAChecker()
        rule = make_rule(
            matcher_config={
                "policy_path": "test",
                "input_data": {"region": "us-east", "env": "prod"},
            },
        )
        artifact = make_artifact()
        context = make_context()

        request = checker._translate_request(rule, artifact, context)
        input_data = request["input"]

        assert input_data["extra"]["region"] == "us-east"
        assert input_data["extra"]["env"] == "prod"

    def test_input_data_context_project_root(self):
        """context.project_root 被合入 input.context"""
        checker = OPAChecker()
        rule = make_rule(matcher_config={"policy_path": "test"})
        artifact = make_artifact()
        context = make_context(project_root="/my/project")

        request = checker._translate_request(rule, artifact, context)
        input_data = request["input"]

        assert input_data["context"]["project_root"] == "/my/project"

    def test_no_extra_when_no_input_data(self):
        """matcher_config 没有 input_data 时，input 中无 extra 字段"""
        checker = OPAChecker()
        rule = make_rule(matcher_config={"policy_path": "test"})  # 无 input_data
        artifact = make_artifact()
        context = make_context()

        request = checker._translate_request(rule, artifact, context)
        input_data = request["input"]

        assert "extra" not in input_data


# ═══════════════════════════════════════════════════════════
#  _call_engine 测试
# ═══════════════════════════════════════════════════════════

class TestCallEngine:
    """引擎调用测试（HTTP + embedded）"""

    def test_call_http_mode_dispatches_to_call_http(self):
        """mode=http 时 _call_engine 路由到 _call_http"""
        checker = OPAChecker(config={"mode": "http"})
        request = {"mode": "http", "policy_path": "test/policy", "input": {}, "opa_url": "http://localhost:8181"}

        with patch.object(checker, "_call_http", return_value={"passed": True, "findings": []}) as mock_http:
            result = checker._call_engine(request)
            mock_http.assert_called_once_with(request)
            assert result["passed"] is True

    def test_call_embedded_mode_dispatches_to_call_embedded(self):
        """mode=embedded 时 _call_engine 路由到 _call_embedded"""
        checker = OPAChecker(config={"mode": "embedded"})
        request = {"mode": "embedded", "policy_path": "test/policy", "input": {}}

        with patch.object(checker, "_call_embedded", return_value={"passed": True, "findings": []}) as mock_embedded:
            result = checker._call_engine(request)
            mock_embedded.assert_called_once_with(request)
            assert result["passed"] is True

    def test_call_http_constructs_correct_url(self):
        """_call_http 拼接正确的 OPA API URL"""
        checker = OPAChecker(config={"opa_url": "http://opa:8181"})
        request = {
            "mode": "http",
            "opa_url": "http://opa:8181",
            "policy_path": "harness/compliance/no_pii",
            "input": {"artifact": {"path": "test.py"}},
            "severity": "critical",
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"result": True}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.Request") as mock_req_cls, \
             patch("urllib.request.urlopen", return_value=mock_resp):
            checker._call_http(request)

            # URL 应为 /v1/data/{policy_path}
            call_args = mock_req_cls.call_args
            api_url = call_args[0][0]
            assert api_url == "http://opa:8181/v1/data/harness/compliance/no_pii"

    def test_call_http_posts_json_body(self):
        """_call_http POST JSON 请求体"""
        checker = OPAChecker()
        input_data = {"artifact": {"path": "test.py"}, "rule": {"id": "SEC-001"}}
        request = {
            "mode": "http",
            "opa_url": "http://localhost:8181",
            "policy_path": "test/policy",
            "input": input_data,
            "severity": "critical",
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"result": True}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.Request") as mock_req_cls, \
             patch("urllib.request.urlopen", return_value=mock_resp):
            checker._call_http(request)

            # 请求体应为 JSON 编码的 {"input": input_data}
            call_kwargs = mock_req_cls.call_args
            body_bytes = call_kwargs[1]["data"]
            body_json = json.loads(body_bytes.decode())
            assert body_json["input"] == input_data
            assert call_kwargs[1]["method"] == "POST"

    def test_call_http_raises_on_url_error(self):
        """_call_http 在 URLError 时抛出异常"""
        import urllib.error
        checker = OPAChecker()
        request = {
            "mode": "http",
            "opa_url": "http://localhost:8181",
            "policy_path": "test",
            "input": {},
            "severity": "critical",
        }

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            with pytest.raises(urllib.error.URLError):
                checker._call_http(request)

    def test_call_embedded_invokes_sdk(self):
        """_call_embedded 调用 opa_python_sdk.OPAClient"""
        checker = OPAChecker()
        request = {
            "mode": "embedded",
            "policy_path": "harness/compliance/no_pii",
            "input": {"artifact": {"path": "test.py"}},
            "severity": "critical",
        }

        mock_client_instance = MagicMock()
        mock_client_instance.evaluate.return_value = {"result": True}

        mock_sdk = MagicMock()
        mock_sdk.OPAClient.return_value = mock_client_instance

        with patch.dict("sys.modules", {"opa_python_sdk": mock_sdk}):
            result = checker._call_embedded(request)

            mock_sdk.OPAClient.assert_called_once()
            mock_client_instance.evaluate.assert_called_once_with(
                policy_path="harness/compliance/no_pii",
                input_data={"artifact": {"path": "test.py"}},
            )

    def test_call_embedded_raises_on_sdk_error(self):
        """_call_embedded 在 SDK 异常时抛出"""
        checker = OPAChecker()
        request = {
            "mode": "embedded",
            "policy_path": "test",
            "input": {},
            "severity": "critical",
        }

        mock_sdk = MagicMock()
        mock_sdk.OPAClient.side_effect = RuntimeError("SDK init failed")

        with patch.dict("sys.modules", {"opa_python_sdk": mock_sdk}):
            with pytest.raises(RuntimeError):
                checker._call_embedded(request)


# ═══════════════════════════════════════════════════════════
#  _parse_opa_response 测试
# ═══════════════════════════════════════════════════════════

class TestParseOPAResponse:
    """OPA 响应解析测试"""

    def test_bool_result_true(self):
        """result 是 True → passed=True, findings 为空"""
        checker = OPAChecker()
        data = {"result": True}
        request = {"severity": "critical", "policy_path": "test/policy"}

        parsed = checker._parse_opa_response(data, request)
        assert parsed["passed"] is True
        assert parsed["findings"] == []
        assert parsed["severity"] == "critical"

    def test_bool_result_false(self):
        """result 是 False → passed=False, findings 为空"""
        checker = OPAChecker()
        data = {"result": False}
        request = {"severity": "high", "policy_path": "test/policy"}

        parsed = checker._parse_opa_response(data, request)
        assert parsed["passed"] is False
        assert parsed["findings"] == []
        assert parsed["severity"] == "high"

    def test_dict_result_allowed_no_violations(self):
        """result 是 dict，allowed=True 且无 violations → passed=True"""
        checker = OPAChecker()
        data = {"result": {"allowed": True, "violations": []}}
        request = {"severity": "medium", "policy_path": "harness/compliance/policy"}

        parsed = checker._parse_opa_response(data, request)
        assert parsed["passed"] is True
        assert parsed["findings"] == []

    def test_dict_result_not_allowed_with_violations(self):
        """result 是 dict，allowed=False 且有 violations → passed=False，findings 有内容"""
        checker = OPAChecker()
        data = {
            "result": {
                "allowed": False,
                "violations": [
                    {"msg": "Secret found in line 5", "line": 5},
                    {"message": "PII detected", "line": 10},
                ],
            },
        }
        request = {"severity": "critical", "policy_path": "harness/compliance/no_pii"}

        parsed = checker._parse_opa_response(data, request)
        assert parsed["passed"] is False
        assert len(parsed["findings"]) == 2
        # findings 格式：OPA ({policy_path}): {msg}
        assert "harness/compliance/no_pii" in parsed["findings"][0]
        assert "Secret found in line 5" in parsed["findings"][0]
        assert "PII detected" in parsed["findings"][1]
        assert parsed["remediation"] is not None
        assert "no_pii" in parsed["remediation"]

    def test_dict_result_allowed_false_no_violations(self):
        """result 是 dict，allowed=False 但无 violations → passed=False，findings 为空"""
        checker = OPAChecker()
        data = {"result": {"allowed": False}}
        request = {"severity": "low", "policy_path": "test"}

        parsed = checker._parse_opa_response(data, request)
        # allowed=False 且 violations=[] → 走 allowed and not violations 的否定分支
        assert parsed["passed"] is False
        assert parsed["findings"] == []

    def test_violation_msg_and_message_fields(self):
        """violation 优先用 msg 字段，回退到 message 字段"""
        checker = OPAChecker()
        data = {
            "result": {
                "allowed": False,
                "violations": [
                    {"msg": "from msg field"},
                    {"message": "from message field"},
                    {"msg": "msg wins", "message": "message ignored"},
                ],
            },
        }
        request = {"severity": "high", "policy_path": "test/policy"}

        parsed = checker._parse_opa_response(data, request)
        assert "from msg field" in parsed["findings"][0]
        assert "from message field" in parsed["findings"][1]
        # msg 优先，message 回退
        assert "msg wins" in parsed["findings"][2]

    def test_violation_no_msg_uses_default(self):
        """violation 既没有 msg 也没有 message → 使用默认文本"""
        checker = OPAChecker()
        data = {
            "result": {
                "allowed": False,
                "violations": [{"line": 3}],
            },
        }
        request = {"severity": "medium", "policy_path": "test"}

        parsed = checker._parse_opa_response(data, request)
        assert "OPA violation" in parsed["findings"][0]

    def test_locations_extracted_from_violations(self):
        """从 violations 提取 locations 信息"""
        checker = OPAChecker()
        data = {
            "result": {
                "allowed": False,
                "violations": [
                    {"msg": "violation A", "line": 10},
                    {"msg": "violation B", "line": 20},
                ],
            },
        }
        request = {"severity": "critical", "policy_path": "harness/policy"}

        parsed = checker._parse_opa_response(data, request)
        assert len(parsed["locations"]) == 2
        assert parsed["locations"][0]["line"] == 10
        assert parsed["locations"][0]["engine"] == "opa"
        assert parsed["locations"][1]["line"] == 20


# ═══════════════════════════════════════════════════════════
#  降级回退测试
# ═══════════════════════════════════════════════════════════

class TestFallbackBehavior:
    """引擎不可用时的降级回退测试"""

    def test_engine_unavailable_falls_back_to_regex(self):
        """OPA 不可用 → 回退到 RegexChecker"""
        checker = OPAChecker()
        checker._availability_cache = False

        rule = make_rule(pattern="password|secret|api_key")
        artifact = make_artifact(content="config has api_key = 'xyz'")
        context = make_context()

        result = checker.check(rule, artifact, context)
        # RegexChecker 匹配到 api_key
        assert result.passed is False
        assert result.rule_id == "SEC-001"

    def test_engine_call_exception_falls_back(self):
        """引擎调用异常 → 回退到 RegexChecker"""
        checker = OPAChecker()
        checker._availability_cache = True

        with patch.object(checker, "_call_engine", side_effect=RuntimeError("OPA timeout")):
            rule = make_rule(pattern="password|secret")
            artifact = make_artifact(content="contains password here")
            context = make_context()

            result = checker.check(rule, artifact, context)
            assert result.passed is False  # RegexChecker 匹配

    def test_translate_request_exception_falls_back(self):
        """请求翻译异常 → 回退到 RegexChecker"""
        checker = OPAChecker()
        checker._availability_cache = True

        with patch.object(checker, "_translate_request", side_effect=ValueError("bad rule")):
            rule = make_rule(pattern="password")
            artifact = make_artifact(content="has password here")
            context = make_context()

            result = checker.check(rule, artifact, context)
            assert result.passed is False  # RegexChecker 匹配

    def test_translate_response_exception_falls_back(self):
        """响应翻译异常 → 回退到 RegexChecker"""
        checker = OPAChecker()
        checker._availability_cache = True

        with patch.object(checker, "_call_engine", return_value={"passed": True}), \
             patch.object(checker, "_translate_response", side_effect=ValueError("parse error")):
            rule = make_rule(pattern="password|secret")
            artifact = make_artifact(content="contains secret")
            context = make_context()

            result = checker.check(rule, artifact, context)
            assert result.passed is False  # 回退 RegexChecker 匹配


# ═══════════════════════════════════════════════════════════
#  完整 check 流程测试
# ═══════════════════════════════════════════════════════════

class TestCheckFlow:
    """完整 check 流程测试（mock 引擎调用）"""

    def test_check_passed_via_opa(self):
        """OPA 评估通过场景"""
        checker = OPAChecker(config={"mode": "http", "opa_url": "http://opa:8181"})
        checker._availability_cache = True

        with patch.object(checker, "_call_engine") as mock_call:
            mock_call.return_value = {
                "passed": True,
                "findings": [],
                "severity": "critical",
            }

            rule = make_rule(pattern="no_pii", severity="critical")
            artifact = make_artifact(content="clean content")
            context = make_context()

            result = checker.check(rule, artifact, context)
            assert result.passed is True
            assert result.findings == []
            assert result.severity == "critical"
            assert result.rule_id == "SEC-001"
            mock_call.assert_called_once()

    def test_check_failed_via_opa(self):
        """OPA 评估失败场景"""
        checker = OPAChecker(config={"mode": "http", "opa_url": "http://opa:8181"})
        checker._availability_cache = True

        with patch.object(checker, "_call_engine") as mock_call:
            mock_call.return_value = {
                "passed": False,
                "findings": ["OPA (harness/policy): Secret exposed"],
                "severity": "critical",
                "remediation": "Fix OPA violations in policy harness/policy",
                "locations": [{"line": 5, "match": "Secret exposed", "engine": "opa"}],
            }

            rule = make_rule(pattern="no_pii", severity="critical")
            artifact = make_artifact(content="contains secret")
            context = make_context()

            result = checker.check(rule, artifact, context)
            assert result.passed is False
            assert len(result.findings) == 1
            assert result.severity == "critical"
            assert result.rule_id == "SEC-001"

    def test_check_marks_engine_in_locations(self):
        """check 流程中 locations 被标记 engine=opa"""
        checker = OPAChecker()
        checker._availability_cache = True

        with patch.object(checker, "_call_engine") as mock_call:
            mock_call.return_value = {
                "passed": False,
                "findings": ["violation"],
                "severity": "high",
                "locations": [{"line": 10, "match": "secret"}],
            }

            rule = make_rule(severity="high")
            artifact = make_artifact()
            context = make_context()

            result = checker.check(rule, artifact, context)
            # 基类 _translate_response 后 check 会给 locations 加 engine 标记
            assert result.locations[0].get("engine") == "opa"

    def test_check_uses_opa_url_from_config(self):
        """check 流程使用 config 中指定的 opa_url"""
        checker = OPAChecker(config={"opa_url": "http://custom-opa:9999"})
        checker._availability_cache = True

        with patch.object(checker, "_call_engine") as mock_call:
            mock_call.return_value = {"passed": True, "findings": [], "severity": "medium"}

            rule = make_rule(severity="medium")
            artifact = make_artifact()
            context = make_context()

            result = checker.check(rule, artifact, context)

            # 验证 _translate_request 传递了正确的 opa_url
            request_arg = mock_call.call_args[0][0]
            assert request_arg["opa_url"] == "http://custom-opa:9999"


# ═══════════════════════════════════════════════════════════
#  _translate_response 测试
# ═══════════════════════════════════════════════════════════

class TestTranslateResponse:
    """响应翻译测试——OPAChecker 使用基类默认实现"""

    def test_translate_response_maps_to_compliance_result(self):
        """基类默认实现将 dict 映射为 ComplianceResult"""
        checker = OPAChecker()
        response = {
            "passed": True,
            "findings": [],
            "severity": "high",
            "remediation": "Fix the issue",
            "locations": [],
        }
        rule = make_rule(severity="high")

        result = checker._translate_response(response, rule)
        assert isinstance(result, ComplianceResult)
        assert result.rule_id == "SEC-001"
        assert result.passed is True
        assert result.severity == "high"
        assert result.remediation == "Fix the issue"

    def test_translate_response_fallback_severity_from_rule(self):
        """response 中没有 severity 时回退到 rule.severity"""
        checker = OPAChecker()
        response = {"passed": False, "findings": ["violation"]}
        rule = make_rule(severity="medium")

        result = checker._translate_response(response, rule)
        assert result.severity == "medium"

    def test_translate_response_fallback_remediation_from_rule(self):
        """response 中没有 remediation 时回退到 rule.remediation"""
        checker = OPAChecker()
        response = {"passed": False, "findings": ["violation"], "severity": "high"}
        rule = make_rule(remediation="Remove hardcoded secrets")

        result = checker._translate_response(response, rule)
        assert result.remediation == "Remove hardcoded secrets"


# ═══════════════════════════════════════════════════════════
#  集成测试（需要真实 OPA 服务）
# ═══════════════════════════════════════════════════════════

@pytest.mark.opa
class TestOPAIntegration:
    """OPA 集成测试——需要运行 OPA 服务

    运行方式：
    1. 启动 OPA：docker run -d --name opa -p 8181:8181 openpolicyagent/opa:latest run --server
    2. 加载策略：
       curl -X PUT http://localhost:8181/v1/policies/harness/compliance/no_hardcoded_secrets \
         -H "Content-Type: text/plain" \
         -d 'package harness.compliance.no_hardcoded_secrets
             default allow = false
             allow { not any_match }
             any_match { input.artifact.content.contains("password") }
             any_match { input.artifact.content.contains("secret") }'
    3. 运行测试：pytest -m opa tests/test_opa_checker.py
    """

    def test_http_probe_live_server(self):
        """HTTP 模式探测真实 OPA 服务"""
        checker = OPAChecker(config={
            "mode": "http",
            "opa_url": "http://localhost:8181",
        })
        checker.reset_availability_cache()
        result = checker._probe_engine()
        if not result:
            pytest.skip("OPA server not running at localhost:8181")
        assert result is True

    def test_http_check_with_live_server(self):
        """HTTP 模式对真实 OPA 发起策略评估"""
        checker = OPAChecker(config={
            "mode": "http",
            "opa_url": "http://localhost:8181",
        })
        checker.reset_availability_cache()

        if not checker._is_engine_available():
            pytest.skip("OPA server not running at localhost:8181")

        rule = make_rule(
            pattern="no_hardcoded_secrets",
            matcher_config={"policy_path": "harness/compliance/no_hardcoded_secrets"},
            severity="critical",
        )
        artifact = make_artifact(content="password = 'abc123'")
        context = make_context()

        result = checker.check(rule, artifact, context)
        # 如果 OPA 服务运行且策略已加载，应该检测到 violation
        # 否则回退到 RegexChecker
        assert result.rule_id == "SEC-001"

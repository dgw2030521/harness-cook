"""
OPAChecker — OPA 实时策略评估合规引擎集成

OPA (Open Policy Agent) 作为实时策略评估引擎接入 harness-cook，
通过 HTTP API 或嵌入式 SDK 执行 Rego 策略评估。

工作流程：
1. _probe_engine: HTTP GET /health 或嵌入式 SDK 检测
2. _translate_request: matcher_config → OPA Rego 查询输入 JSON
3. _call_engine: POST /v1/data/{policy_path} 或嵌入式调用
4. _translate_response: OPA {result: [{allowed, violations}] → ComplianceResult

安装：pip install harness-cook[opa]
"""

import json
import logging
from typing import Optional

from harness.types import (
    Artifact, ComplianceRule, ComplianceResult, ScanContext,
)
from harness.integrations.base import ExternalEngineChecker

logger = logging.getLogger("harness.integrations.opa")


class OPAChecker(ExternalEngineChecker):
    """OPA 实时策略评估合规引擎

    用法：
        checker = OPAChecker(config={
            "opa_url": "http://localhost:8181",
            "policy_path": "harness/compliance",
            "mode": "http",  # "http" 或 "embedded"
        })
        result = checker.check(rule, artifact, context)

    规则 matcher_config 配置示例：
        matcher_type: "opa"
        matcher_config:
          policy_path: "harness/compliance/no_pii"
          # 或由 pattern 自动映射为 policy_path
          input_data:
            additional_key: value

    降级行为：
        OPA 不可连接 → 回退到 RegexChecker
        Rego 策略评估失败 → 回退到 RegexChecker
    """

    def __init__(
        self,
        config: Optional[dict] = None,
    ):
        super().__init__(
            engine_name="opa",
            config=config or {},
        )

    # ─── 可用性探测 ──────────────────────────────────

    def _probe_engine(self) -> bool:
        """探测 OPA 可用性"""
        mode = self._config.get("mode", "http")

        if mode == "embedded":
            try:
                from opa_python_sdk import OPAClient
                return True
            except ImportError:
                logger.debug("opa-python-sdk not installed — embedded mode unavailable")
                return False

        # HTTP 模式
        import urllib.request
        import urllib.error

        url = self._config.get("opa_url", "http://localhost:8181")
        health_url = f"{url.rstrip('/')}/health"

        try:
            req = urllib.request.Request(health_url)
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except urllib.error.URLError:
            logger.debug(f"OPA server at {url} not reachable")
            return False
        except Exception as e:
            logger.debug(f"OPA probe failed: {e}")
            return False

    # ─── 请求翻译 ────────────────────────────────────

    def _translate_request(
        self,
        rule: ComplianceRule,
        artifact: Artifact,
        context: ScanContext,
    ) -> dict:
        """将 harness 规则翻译为 OPA 查询输入"""
        # 确定 policy path
        policy_path = self._resolve_policy_path(rule)

        # 构建 OPA 输入数据
        input_data = {
            "artifact": {
                "path": artifact.path,
                "content": artifact.content,
                "type": artifact.type,
            },
            "rule": {
                "id": rule.id,
                "pattern": rule.pattern,
                "severity": rule.severity,
                "description": rule.description,
            },
        }

        # 合入 matcher_config 中的额外输入数据
        extra_input = rule.matcher_config.get("input_data", {})
        if extra_input:
            input_data["extra"] = extra_input

        # 合入 context 信息
        if context.project_root:
            input_data["context"] = {
                "project_root": context.project_root,
            }

        return {
            "policy_path": policy_path,
            "input": input_data,
            "mode": self._config.get("mode", "http"),
            "opa_url": self._config.get("opa_url", "http://localhost:8181"),
            "rule_id": rule.id,
            "severity": rule.severity,
        }

    def _resolve_policy_path(self, rule: ComplianceRule) -> str:
        """确定 OPA policy path

        优先级：
        1. matcher_config.policy_path — 直接指定
        2. pattern → 转换为 policy path（harness/compliance/{pattern}）
        3. 默认 → harness/compliance/{rule.id}
        """
        config_path = rule.matcher_config.get("policy_path")
        if config_path:
            return config_path

        # pattern → policy path
        pattern = rule.pattern.strip()
        if pattern and not pattern.startswith("http"):
            # 将 pattern 转为合法的 Rego package path
            sanitized = pattern.replace(".", "/").replace("-", "_")
            return f"harness/compliance/{sanitized}"

        return f"harness/compliance/{rule.id}"

    # ─── 引擎调用 ────────────────────────────────────

    def _call_engine(self, request: dict) -> dict:
        """调用 OPA 执行策略评估"""
        mode = request.get("mode", "http")

        if mode == "embedded":
            return self._call_embedded(request)

        return self._call_http(request)

    def _call_http(self, request: dict) -> dict:
        """HTTP API 调用 OPA"""
        import urllib.request
        import urllib.error

        url = request["opa_url"].rstrip("/")
        policy_path = request["policy_path"]
        api_url = f"{url}/v1/data/{policy_path}"

        # 构建请求体
        body = json.dumps({"input": request["input"]}).encode()

        try:
            req = urllib.request.Request(
                api_url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return self._parse_opa_response(data, request)
        except urllib.error.URLError as e:
            logger.warning(f"OPA HTTP call failed: {e}")
            raise
        except Exception as e:
            logger.warning(f"OPA HTTP call failed: {e}")
            raise

    def _call_embedded(self, request: dict) -> dict:
        """嵌入式 SDK 调用 OPA"""
        try:
            from opa_python_sdk import OPAClient

            client = OPAClient()
            result = client.evaluate(
                policy_path=request["policy_path"],
                input_data=request["input"],
            )
            return self._parse_opa_response(result, request)
        except Exception as e:
            logger.warning(f"OPA embedded call failed: {e}")
            raise

    def _parse_opa_response(self, data: dict, request: dict) -> dict:
        """解析 OPA 响应"""
        result = data.get("result", {})

        # OPA 响应格式：{result: {allowed: bool, violations: [...]}}
        # 或 {result: bool}（简单 allow/deny 策略）
        if isinstance(result, bool):
            return {
                "passed": result,
                "findings": [],
                "severity": request["severity"],
            }

        allowed = result.get("allowed", True)
        violations = result.get("violations", [])

        if allowed and not violations:
            return {
                "passed": True,
                "findings": [],
                "severity": request["severity"],
            }

        findings = []
        locations = []
        for v in violations:
            msg = v.get("msg", v.get("message", "OPA violation"))
            findings.append(f"OPA ({request['policy_path']}): {msg}")
            locations.append({
                "line": v.get("line", 0),
                "match": msg[:50],
                "start": 0,
                "end": 0,
                "engine": "opa",
            })

        return {
            "passed": False,
            "findings": findings,
            "severity": request["severity"],
            "remediation": f"Fix OPA violations in policy {request['policy_path']}",
            "locations": locations,
        }

    # ─── 响应翻译 ────────────────────────────────────

    def _translate_response(
        self,
        response: dict,
        rule: ComplianceRule,
    ) -> ComplianceResult:
        """使用基类默认实现"""
        return super()._translate_response(response, rule)

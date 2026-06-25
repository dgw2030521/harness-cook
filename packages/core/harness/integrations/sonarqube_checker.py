"""
SonarQubeChecker — SonarQube 引用模式合规引擎集成

引用模式：不触发新扫描，从最近 CI 扫描检索缓存结果。

工作流程：
1. _probe_engine: HTTP GET /api/system/status → 检查 SonarQube 连接
2. _translate_request: rule → SonarQube API 查询参数
3. _call_engine: HTTP GET /api/issues/search?projectKey=...&rules=...
4. _translate_response: SonarQube issue → ComplianceResult

严重性映射：
- BLOCKER → critical
- CRITICAL → high
- MAJOR → medium
- MINOR → low
- INFO → info

安装：pip install harness-cook[sonarqube]
"""

import json
import logging
from typing import Optional

from harness.types import (
    Artifact, ComplianceRule, ComplianceResult, ScanContext,
)
from harness.integrations.base import ExternalEngineChecker

logger = logging.getLogger("harness.integrations.sonarqube")


# ─── SonarQube 严重性映射 ──────────────────────────────────────

SEVERITY_MAP = {
    "BLOCKER": "critical",
    "CRITICAL": "high",
    "MAJOR": "medium",
    "MINOR": "low",
    "INFO": "info",
}


class SonarQubeChecker(ExternalEngineChecker):
    """SonarQube 引用模式合规引擎

    用法：
        checker = SonarQubeChecker(config={
            "sonarqube_url": "https://sonar.example.com",
            "sonarqube_token": "squ_xxxx...",
            "project_key": "my-project",
        })
        result = checker.check(rule, artifact, context)

    规则 matcher_config 配置示例：
        matcher_type: "sonarqube"
        matcher_config:
          rule_key: "python:S1234"       # SonarQube 规则键
          # 或 pattern 关键词自动映射

    降级行为：
        SonarQube 不可连接 → 回退到 RegexChecker
        API 调用失败 → 回退到 RegexChecker
    """

    def __init__(
        self,
        config: Optional[dict] = None,
    ):
        super().__init__(
            engine_name="sonarqube",
            config=config or {},
        )

    # ─── 可用性探测 ──────────────────────────────────

    def _probe_engine(self) -> bool:
        """探测 SonarQube 连接可用性"""
        import urllib.request
        import urllib.error

        url = self._config.get("sonarqube_url", "")
        if not url:
            logger.debug("sonarqube_url not configured — checker disabled")
            return False

        token = self._config.get("sonarqube_token", "")
        status_url = f"{url.rstrip('/')}/api/system/status"

        try:
            req = urllib.request.Request(status_url)
            if token:
                # Basic auth: token as username, empty password
                import base64
                credentials = base64.b64encode(f"{token}:".encode()).decode()
                req.add_header("Authorization", f"Basic {credentials}")

            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                if data.get("status") in ("UP", "STARTING", "RESTARTING"):
                    return True
                logger.debug(f"SonarQube status: {data.get('status')}")
                return False
        except urllib.error.URLError as e:
            logger.debug(f"SonarQube connection failed: {e}")
            return False
        except Exception as e:
            logger.debug(f"SonarQube probe failed: {e}")
            return False

    # ─── 请求翻译 ────────────────────────────────────

    def _translate_request(
        self,
        rule: ComplianceRule,
        artifact: Artifact,
        context: ScanContext,
    ) -> dict:
        """将 harness 规则翻译为 SonarQube API 查询参数"""
        # 确定 SonarQube 规则键
        rule_key = self._resolve_rule_key(rule)

        project_key = self._config.get("project_key", "")
        # 从 context 获取 project_root，尝试推断 project_key
        if not project_key and context.project_root:
            # 使用目录名作为 project_key 的 fallback
            import os
            project_key = os.path.basename(context.project_root)

        return {
            "url": self._config.get("sonarqube_url", ""),
            "token": self._config.get("sonarqube_token", ""),
            "project_key": project_key,
            "rule_key": rule_key,
            "file_path": artifact.path,
            "severity": rule.severity,
            "rule_id": rule.id,
        }

    def _resolve_rule_key(self, rule: ComplianceRule) -> str:
        """确定 SonarQube 规则键

        优先级：
        1. matcher_config.rule_key — 直接指定
        2. pattern 作为规则键透传
        """
        config_key = rule.matcher_config.get("rule_key")
        if config_key:
            return config_key
        return rule.pattern

    # ─── 引擎调用 ────────────────────────────────────

    def _call_engine(self, request: dict) -> dict:
        """调用 SonarQube API 检索缓存结果（引用模式）"""
        import urllib.request
        import urllib.error
        import base64

        url = request["url"].rstrip("/")
        token = request["token"]
        project_key = request["project_key"]
        rule_key = request["rule_key"]

        # 构建 API URL
        api_url = f"{url}/api/issues/search"
        params = f"projectKey={project_key}&rules={rule_key}&ps=100"

        if request.get("file_path"):
            # 添加文件路径过滤
            file_path = request["file_path"]
            params += f"&componentKeys={project_key}:{file_path}"

        full_url = f"{api_url}?{params}"

        try:
            req = urllib.request.Request(full_url)
            if token:
                credentials = base64.b64encode(f"{token}:".encode()).decode()
                req.add_header("Authorization", f"Basic {credentials}")

            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return self._parse_sonarqube_response(data, request)
        except urllib.error.URLError as e:
            logger.warning(f"SonarQube API call failed: {e}")
            raise  # 让 ExternalEngineChecker.check() 的 catch 回退
        except Exception as e:
            logger.warning(f"SonarQube API call failed: {e}")
            raise

    def _parse_sonarqube_response(self, data: dict, request: dict) -> dict:
        """解析 SonarQube API 响应"""
        issues = data.get("issues", [])
        total = data.get("total", len(issues))

        if not issues:
            return {
                "passed": True,
                "findings": [],
                "severity": request["severity"],
            }

        findings = []
        locations = []
        for issue in issues:
            severity_str = SEVERITY_MAP.get(issue.get("severity", ""), "medium")
            message = issue.get("message", "SonarQube issue")
            component = issue.get("component", "")
            line = issue.get("line", 0)

            findings.append(
                f"SonarQube ({issue.get('rule', 'unknown')}): {message}"
            )
            locations.append({
                "line": line,
                "match": message[:50],
                "start": 0,
                "end": 0,
                "file": component,
                "sonarqube_severity": severity_str,
                "engine": "sonarqube",
            })

        # 使用最严重的问题级别
        max_severity = self._max_severity(issues)

        return {
            "passed": False,
            "findings": findings,
            "severity": max_severity,
            "remediation": f"Fix {total} SonarQube issues (reference mode)",
            "locations": locations,
        }

    def _max_severity(self, issues: list) -> str:
        """从 issues 中取最严重级别"""
        severity_order = ["critical", "high", "medium", "low", "info"]
        max_idx = len(severity_order) - 1
        for issue in issues:
            mapped = SEVERITY_MAP.get(issue.get("severity", ""), "medium")
            idx = severity_order.index(mapped) if mapped in severity_order else max_idx
            if idx < max_idx:
                max_idx = idx
        return severity_order[max_idx]

    # ─── 响应翻译 ────────────────────────────────────

    def _translate_response(
        self,
        response: dict,
        rule: ComplianceRule,
    ) -> ComplianceResult:
        """使用基类默认实现——SonarQube 返回的字典格式兼容"""
        return super()._translate_response(response, rule)

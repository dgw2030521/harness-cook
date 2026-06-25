"""
harness-cook HeliconeMiddlewareChecker —— Helicone 护栏检查器

继承 ExternalEngineChecker，engine_name="helicone"，作为护栏级检查器
（matcher_type="helicone"），与 guardrails_ai 并列。

Helicone 是 LLM 监控和护栏平台，提供：
  - PII 检测和过滤
  - 内容毒性检测
  - 自定义护栏策略（通过 Helicone Dashboard 配置）

回退到内置 RegexChecker（helicone SDK 未安装时）。

依赖：
  - pip install harness-cook[helicone] → 安装 helicone SDK
  - SDK import 在方法级别
"""

import logging
from typing import Optional

from harness.integrations.base import ExternalEngineChecker
from harness.types import ComplianceRule, Artifact, ScanContext, ComplianceResult, ComplianceCategory


logger = logging.getLogger("harness.helicone_checker")


# ─── Helicone 规则映射 ────────────────────────────────────

HELICONE_RULE_MAP = {
    "no_pii": "pii_filter",
    "no_toxicity": "toxicity_filter",
    "no_hallucination": "hallucination_filter",
    "valid_json": "json_validation",
    "valid_python": "python_validation",
    "no_sql_injection": "sql_injection_filter",
}


class HeliconeMiddlewareChecker(ExternalEngineChecker):
    """
    Helicone 护栏检查器

    继承 ExternalEngineChecker，engine_name="helicone"
    matcher_type="helicone" → 与 guardrails_ai 并列的护栏级检查器
    """

    def __init__(self):
        super().__init__(
            engine_name="helicone",
            fallback_checker=None,  # 不指定 fallback → _call_engine 失败时用默认回退
        )
        self._helicone_client = None

    def matches_scope(self, rule: ComplianceRule, artifact: Artifact) -> bool:
        """matcher_type=helicone 或映射规则匹配"""
        if rule.matcher_type == "helicone":
            return True
        # 也匹配内置 PII/toxicity 规则（当用户指定 helicone 引擎时）
        if rule.matcher_type in ("regex", "pii", "toxicity"):
            return rule.id in HELICONE_RULE_MAP or rule.matcher_config.get("helicone_enabled", False)
        return False

    def _probe_engine(self) -> bool:
        """探测 Helicone SDK 是否可用"""
        try:
            import helicone
            return True
        except ImportError:
            logger.debug("helicone SDK not installed — HeliconeMiddlewareChecker unavailable")
            return False

    def _translate_request(
        self,
        rule: ComplianceRule,
        artifact: Artifact,
        context: ScanContext,
    ) -> dict:
        """翻译 harness 规则 → Helicone 检查请求"""
        helicone_rule = HELICONE_RULE_MAP.get(rule.id, rule.id)

        return {
            "rule_id": rule.id,
            "helicone_rule": helicone_rule,
            "content": artifact.content,
            "file_path": artifact.path,
            "severity": rule.severity,
            "matcher_config": rule.matcher_config,
        }

    def _call_engine(self, request: dict) -> dict:
        """调用 Helicone SDK 检查"""
        try:
            import helicone
        except ImportError:
            raise RuntimeError("helicone SDK not installed")

        # 初始化客户端
        if self._helicone_client is None:
            self._helicone_client = helicone.Helicone()

        helicone_rule = request["helicone_rule"]
        content = request["content"]

        # 调用 Helicone 检查
        result = self._helicone_client.check(
            content=content,
            rules=[helicone_rule],
        )

        return {
            "passed": result.get("passed", True),
            "findings": result.get("findings", []),
            "severity": request.get("severity", "medium"),
            "helicone_rule": helicone_rule,
        }

    def _translate_response(self, response: dict, rule: ComplianceRule) -> ComplianceResult:
        """翻译 Helicone 响应 → ComplianceResult"""
        passed = response.get("passed", True)
        findings = response.get("findings", [])

        if passed:
            return ComplianceResult(
                rule_id=rule.id,
                passed=True,
                severity="info",
                findings=[],
            )

        # 构建违规发现
        finding_msgs = [f.get("message", str(f)) for f in findings]
        severity = response.get("severity", rule.severity)

        return ComplianceResult(
            rule_id=rule.id,
            passed=False,
            severity=severity,
            findings=finding_msgs,
            remediation="Review content and apply Helicone filter recommendations",
        )

"""
GuardrailsAIChecker — Guardrails AI 外部护栏引擎集成

将 Guardrails AI 的验证器能力接入 harness-cook 治理框架，
作为护栏层（guardrails layer）的吸收式集成。

Guardrails AI 提供的验证器：
- PII: 个人隐私信息检测
- Toxicity: 有害内容检测
- Relevance: 相关性/幻觉检测
- ValidJSON: JSON 格式验证
- ValidPython: Python 代码验证
- SqlInjection: SQL 注入检测

harness 规则 → Guardrails AI validator 映射：
- matcher_config.validator 或 pattern 关键词自动映射

安装：pip install harness-cook[guardrails]
"""

import logging
from typing import Optional

from harness.types import (
    Artifact, ComplianceRule, ComplianceResult, ScanContext,
)
from harness.integrations.base import ExternalEngineChecker

logger = logging.getLogger("harness.integrations.guardrails_ai")


# ─── Validator 映射表 ──────────────────────────────────────

# harness 规则 pattern/关键词 → Guardrails AI validator 名称
VALIDATOR_MAP = {
    # 内置关键词映射
    "no_pii": "PII",
    "pii": "PII",
    "no_toxicity": "Toxicity",
    "toxicity": "Toxicity",
    "no_hallucination": "Relevance",
    "hallucination": "Relevance",
    "relevance": "Relevance",
    "valid_json": "ValidJSON",
    "json_validation": "ValidJSON",
    "valid_python": "ValidPython",
    "python_validation": "ValidPython",
    "no_sql_injection": "SqlInjection",
    "sql_injection": "SqlInjection",
    "no_code_safety": "CodeSafety",
    "code_safety": "CodeSafety",
}

# 严重性映射：Guardrails AI → harness
SEVERITY_MAP = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "info": "info",
}


class GuardrailsAIChecker(ExternalEngineChecker):
    """Guardrails AI 护栏引擎集成

    用法：
        checker = GuardrailsAIChecker()
        result = checker.check(rule, artifact, context)

    规则 matcher_config 配置示例：
        matcher_type: "guardrails_ai"
        matcher_config:
          validator: "PII"          # 直接指定 validator 名称
          # 或用 pattern 关键词自动映射（如 pattern="no_pii" → PII validator）

    降级行为：
        Guardrails AI SDK 未安装 → 自动回退到 RegexChecker
        SDK import 失败 → 回退到 RegexChecker
        验证器调用失败 → 回退到 RegexChecker
    """

    def __init__(
        self,
        config: Optional[dict] = None,
    ):
        super().__init__(
            engine_name="guardrails-ai",
            config=config or {},
        )

    # ─── 可用性探测 ──────────────────────────────────

    def _probe_engine(self) -> bool:
        """探测 Guardrails AI SDK 可用性"""
        try:
            import guardrails
            # 创建轻量 Guard 实例验证 SDK 可用
            guardrails.Guard()
            return True
        except ImportError:
            logger.debug("guardrails-ai SDK not installed — checker disabled")
            return False
        except Exception as e:
            logger.debug(f"guardrails-ai probe failed: {e}")
            return False

    # ─── 请求翻译 ────────────────────────────────────

    def _translate_request(
        self,
        rule: ComplianceRule,
        artifact: Artifact,
        context: ScanContext,
    ) -> dict:
        """将 harness 规则翻译为 Guardrails AI 验证请求

        validator 名称确定逻辑（优先级从高到低）：
        1. matcher_config.validator — 直接指定
        2. pattern 关键词自动映射（VALIDATOR_MAP）
        3. pattern 原值 — 透传给 Guardrails AI
        """
        # 确定 validator 名称
        validator_name = self._resolve_validator(rule)

        return {
            "validator": validator_name,
            "content": artifact.content,
            "path": artifact.path,
            "rule_id": rule.id,
            "severity": rule.severity,
            "metadata": {
                "rule_description": rule.description,
                "rule_languages": rule.languages,
                "artifact_type": artifact.type,
            },
        }

    def _resolve_validator(self, rule: ComplianceRule) -> str:
        """确定 Guardrails AI validator 名称

        Args:
            rule: harness 合规规则

        Returns:
            Guardrails AI validator 名称字符串
        """
        # 优先级1: matcher_config 直接指定
        config_validator = rule.matcher_config.get("validator")
        if config_validator:
            return config_validator

        # 优先级2: pattern 关键词自动映射
        pattern_lower = rule.pattern.lower().strip()
        mapped = VALIDATOR_MAP.get(pattern_lower)
        if mapped:
            return mapped

        # 优先级3: pattern 原值透传（用户可能指定任意 validator）
        return rule.pattern

    # ─── 引擎调用 ────────────────────────────────────

    def _call_engine(self, request: dict) -> dict:
        """调用 Guardrails AI 执行验证

        方法级 import——确保默认安装不受影响。
        """
        import guardrails

        validator = request["validator"]
        content = request["content"]

        # 创建 Guard 并使用指定 validator
        guard = guardrails.Guard()

        try:
            # Guardrails AI 的验证调用
            result = guard.use(validator).validate(content)

            # 解析验证结果
            if result.validation_passed:
                return {
                    "passed": True,
                    "findings": [],
                    "severity": request["severity"],
                }
            else:
                # 提取验证失败信息
                findings = []
                if result.validated_output != content:
                    findings.append(
                        f"Guardrails AI ({validator}): content modified/filtered"
                    )
                if hasattr(result, 'response') and result.response:
                    findings.append(str(result.response))

                return {
                    "passed": False,
                    "findings": findings or [
                        f"Guardrails AI ({validator}): validation failed"
                    ],
                    "severity": request["severity"],
                    "remediation": f"Content flagged by {validator} validator",
                    "locations": [
                        {"line": 0, "match": "full_content", "validator": validator}
                    ],
                }
        except Exception as e:
            logger.warning(f"Guardrails AI validation call failed: {e}")
            raise  # 让 ExternalEngineChecker.check() 的 catch 回退

    # ─── 响应翻译 ────────────────────────────────────

    def _translate_response(
        self,
        response: dict,
        rule: ComplianceRule,
    ) -> ComplianceResult:
        """将 Guardrails AI 响应翻译为 ComplianceResult

        使用基类默认实现——Guardrails AI 返回的字典格式
        已包含 passed/findings/severity/remediation/locations，
        与基类 _translate_response 的字段提取逻辑完全兼容。
        """
        return super()._translate_response(response, rule)

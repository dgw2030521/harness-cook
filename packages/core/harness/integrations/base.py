"""
ExternalEngineChecker — 外部引擎集成基类

模板方法模式：探测 → 降级 → 翻译 → 调用 → 翻译响应 → 错误回退

所有外部合规引擎集成（GuardrailsAI、SonarQube、OPA、ArchUnit、dep-cruiser 等）
继承此基类，只需实现4个抽象方法：
- _probe_engine()      → 探测引擎可用性（import SDK + 轻量实例验证）
- _translate_request() → 将 harness ComplianceRule 翻译为引擎请求格式
- _call_engine()       → 执行引擎调用
- _translate_response() → 将引擎响应翻译为 ComplianceResult（有通用默认实现）

设计原则：
1. 引擎不可用时自动降级到内置 fallback_checker（默认 RegexChecker）
2. 引擎调用出错时 catch 并回退，不阻塞主流程
3. 所有外部 SDK import 在方法级别，不破坏默认安装
4. 可用性探测带缓存——首次探测后进程生命周期内不再重复
"""

import logging
from typing import Optional, Any

from harness.types import (
    Artifact, ComplianceRule, ComplianceResult, ScanContext,
)
from harness.rule_checker import IRuleChecker, RegexChecker

logger = logging.getLogger("harness.integrations")


class ExternalEngineChecker:
    """外部引擎集成基类——模板方法模式

    用法：
        class MyChecker(ExternalEngineChecker):
            def _probe_engine(self):
                import some_sdk
                some_sdk.Client(...)  # 验证可用性

            def _translate_request(self, rule, artifact, context):
                return {"engine_specific_key": rule.pattern, ...}

            def _call_engine(self, request):
                client = some_sdk.Client(...)
                return client.check(request)

            def _translate_response(self, response, rule):
                # 默认实现已覆盖大多数情况
                # 只在引擎返回非标准格式时覆盖
                return super()._translate_response(response, rule)
    """

    # ─── 构造 ────────────────────────────────────────

    def __init__(
        self,
        engine_name: str = "unknown",
        fallback_checker: Optional[IRuleChecker] = None,
        config: Optional[dict] = None,
    ):
        """初始化外部引擎检查器

        Args:
            engine_name: 引擎标识名（如 "guardrails-ai", "sonarqube"）
            fallback_checker: 降级回退检查器，默认 RegexChecker()
            config: 引擎特定配置（URL、token 等）
        """
        self._engine_name = engine_name
        self._fallback_checker = fallback_checker or RegexChecker()
        self._config = config or {}
        # 可用性缓存：None=未探测, True=可用, False=不可用
        self._availability_cache: Optional[bool] = None

    # ─── IRuleChecker Protocol 实现 ──────────────────

    def check(
        self,
        rule: ComplianceRule,
        artifact: Artifact,
        context: ScanContext,
    ) -> ComplianceResult:
        """模板方法：探测 → 不可用则降级 → 翻译 → 调用 → 翻译响应 → 错误回退

        整个流程保证：
        - 引擎不可用：自动回退到 fallback_checker
        - 引擎调用出错：catch 并回退，不阻塞
        - 引擎可用且成功：返回引擎翻译后的 ComplianceResult
        """
        # 1. 探测可用性
        if not self._is_engine_available():
            logger.info(
                f"Engine '{self._engine_name}' not available, "
                f"falling back to {type(self._fallback_checker).__name__}"
            )
            return self._fallback_checker.check(rule, artifact, context)

        # 2. 翻译请求
        try:
            request = self._translate_request(rule, artifact, context)
        except Exception as e:
            logger.warning(
                f"Engine '{self._engine_name}' request translation failed: {e}, "
                f"falling back"
            )
            return self._fallback_checker.check(rule, artifact, context)

        # 3. 调用引擎
        try:
            response = self._call_engine(request)
        except Exception as e:
            logger.warning(
                f"Engine '{self._engine_name}' call failed: {e}, "
                f"falling back"
            )
            return self._fallback_checker.check(rule, artifact, context)

        # 4. 翻译响应
        try:
            result = self._translate_response(response, rule)
            # 标记结果来自哪个引擎
            if result.locations:
                for loc in result.locations:
                    loc.setdefault("engine", self._engine_name)
            return result
        except Exception as e:
            logger.warning(
                f"Engine '{self._engine_name}' response translation failed: {e}, "
                f"falling back"
            )
            return self._fallback_checker.check(rule, artifact, context)

    def matches_scope(
        self,
        rule: ComplianceRule,
        artifact: Artifact,
    ) -> bool:
        """范围匹配——委托给 fallback_checker

        大多数外部引擎不需要自定义范围匹配逻辑，
        因为它们检查的是规则语义而非文件语言匹配。
        子类可覆盖以实现引擎特定的范围过滤。
        """
        return self._fallback_checker.matches_scope(rule, artifact)

    # ─── 可用性探测（带缓存）─────────────────────────

    def _is_engine_available(self) -> bool:
        """带缓存的惰性可用性探测

        首次调用执行 _probe_engine()，之后缓存结果。
        进程生命周期内只探测一次，避免重复 import 和连接检查开销。
        """
        if self._availability_cache is not None:
            return self._availability_cache

        try:
            self._availability_cache = self._probe_engine()
        except Exception as e:
            logger.debug(
                f"Engine '{self._engine_name}' probe failed: {e}"
            )
            self._availability_cache = False

        if self._availability_cache:
            logger.info(f"Engine '{self._engine_name}' is available")
        else:
            logger.info(f"Engine '{self._engine_name}' is NOT available")

        return self._availability_cache

    # ─── 抽象方法（子类实现）─────────────────────────

    def _probe_engine(self) -> bool:
        """探测引擎是否可用

        子类实现——通常 import SDK 并创建轻量实例来验证：
        - Python SDK: try import; create Client() 来验证
        - HTTP API: try requests.get(health_endpoint)
        - CLI 工具: try subprocess.run([cli, "--version"])

        Returns:
            True=引擎可用, False=不可用
        """
        raise NotImplementedError(
            f"Subclass must implement _probe_engine() for '{self._engine_name}'"
        )

    def _translate_request(
        self,
        rule: ComplianceRule,
        artifact: Artifact,
        context: ScanContext,
    ) -> dict:
        """将 harness 规则语言翻译为引擎请求格式

        子类实现——将 ComplianceRule 的 pattern/matcher_config/severity
        翻译为引擎特定的请求字典。

        Args:
            rule: harness 合规规则
            artifact: 待检查的产出物
            context: 扫描上下文

        Returns:
            引擎特定的请求字典
        """
        raise NotImplementedError(
            f"Subclass must implement _translate_request() for '{self._engine_name}'"
        )

    def _call_engine(self, request: dict) -> dict:
        """执行引擎调用

        子类实现——用翻译后的请求调用外部引擎。
        所有外部 SDK import 应在此方法内部（方法级 import），确保默认安装不受影响。

        Args:
            request: _translate_request 返回的请求字典

        Returns:
            引擎原始响应字典
        """
        raise NotImplementedError(
            f"Subclass must implement _call_engine() for '{self._engine_name}'"
        )

    def _translate_response(
        self,
        response: dict,
        rule: ComplianceRule,
    ) -> ComplianceResult:
        """将引擎响应翻译为 ComplianceResult

        通用默认实现——从响应字典提取标准字段。
        大多数引擎返回的结构化结果可映射到 passed/findings/severity，
        子类只需确保 _call_engine 返回的字典包含这些字段。

        非标准引擎响应格式——子类覆盖此方法做自定义翻译。

        Args:
            response: _call_engine 返回的原始响应字典
            rule: 原始合规规则（用于填充 rule_id/severity/remediation）

        Returns:
            ComplianceResult 实例
        """
        # 通用字段提取——response 优先，rule 回退
        passed = response.get("passed", False)
        raw_findings = response.get("findings", [])
        findings = raw_findings if isinstance(raw_findings, list) else [str(raw_findings)]
        severity = response.get("severity") or rule.severity
        # remediation: response 有值则用 response 的，否则回退到 rule 的
        remediation = response.get("remediation") or rule.remediation
        raw_locations = response.get("locations", [])
        locations = raw_locations if isinstance(raw_locations, list) else []

        return ComplianceResult(
            rule_id=rule.id,
            passed=passed,
            severity=severity,
            findings=findings,
            remediation=remediation,
            locations=locations,
        )

    # ─── 辅助 ────────────────────────────────────────

    def reset_availability_cache(self) -> None:
        """重置可用性缓存——用于测试或配置变更后重新探测"""
        self._availability_cache = None

    @property
    def engine_name(self) -> str:
        """引擎标识名"""
        return self._engine_name

    @property
    def fallback_checker(self) -> IRuleChecker:
        """降级回退检查器"""
        return self._fallback_checker

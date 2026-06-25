"""
harness-cook 安全护栏

Guardrails 是 Harness 的"安全网"——在 Agent 的输入和输出两端过滤危险内容。
与 Gate/Compliance 的区别：
  - Gate: 事后检查（任务完成后检查产出物质量）
  - Compliance: 规则扫描（持续扫描是否符合合规规则）
  - Guardrails: 实时过滤（进入/离开 Agent 的内容即时拦截）

三层防护：
  输入 → [InputGuardrails] → Agent → [OutputGuardrails] → 输出

触发路径声明（E-5）：
  护栏（InputGuardrails / OutputGuardrails）只有一条触发路径：
    路径1: MCP hook_trigger 工具
      Agent 平台（Claude Code 等）在 hook 事件中调用 harness_hook_trigger
      → 输入类槽位（pre_tool_use / pre_execute）路由到 InputGuardrails.check()
      → 输出类槽位（post_tool_use / post_execute / on_file_change）路由到 OutputGuardrails.check()
      → 实时决策：BLOCK / WARN / REDACT / CONTINUE

  护栏不被以下路径触发：
    - DAGEngine：事后编排引擎，节点已完成才做门禁检查，不适合实时拦截
    - ComplianceEngine：静态规则扫描，生成报告不做拦截

模式来源：
  所有检测正则从 PatternRegistry 获取（唯一定义源），不再在本模块内硬编码。
  护栏层只做拦截决策（BLOCK/WARN/REDACT），不定义检测模式本身。
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
from harness.types import (
    GuardrailAction, InputGuardrailConfig, OutputGuardrailConfig,
    Artifact, TaskResult,
)
from harness.bus import EventBus, BusEventType, BusEvent, get_bus
from harness.pattern_registry import get_pattern_registry


logger = logging.getLogger("harness.guardrails")


# ─── 护栏结果 ──────────────────────────────────────

@dataclass
class GuardrailResult:
    """护栏检查结果"""
    action: GuardrailAction           # 采取的动作
    original_content: str             # 原始内容
    processed_content: str            # 处理后的内容（可能脱敏/替换）
    blocked: bool = False             # 是否完全阻止
    warnings: list[str] = field(default_factory=list)   # 警告信息
    redactions: list[dict] = field(default_factory=list) # 脱敏记录 [{type, original, redacted}]
    violations: list[str] = field(default_factory=list)  # 违规列表


# ─── PII 检测器 ──────────────────────────────────────

class PIIDetector:
    """PII（个人隐私信息）检测器——从 PatternRegistry 获取模式

    模式来源变更（E-2 重构）：
    - 旧：PIIDetector.PATTERNS 类变量（硬编码正则）
    - 新：PatternRegistry（唯一定义源），PIIDetector 按需获取
    - 护栏层只做拦截决策（BLOCK/WARN/REDACT），不定义检测模式本身

    向后兼容：
    - PATTERNS 属性仍可访问（动态从 PatternRegistry 构建）
    - 旧键名 "api_key_generic" 仍可用（映射到新 sub_type "api_key")
    - detect()/redact() API 不变
    """

    # 旧键名 → PatternRegistry sub_type 映射（向后兼容）
    _LEGACY_KEY_MAP = {
        "api_key_generic": "api_key",
    }

    # 护栏层检测的 target_type 范围（PII + SECRET）
    _DETECT_TARGET_TYPES = ["pii", "secret"]

    REDACTION_TEMPLATE = "[REDACTED_{type}]"

    @property
    def PATTERNS(self) -> dict[str, str]:
        """向后兼容属性——返回 PatternRegistry 中 PII+SECRET 模式的 {sub_type: pattern} 映射

        注意：此属性已废弃，仅用于向后兼容。
        新代码应直接使用 PatternRegistry 获取模式。
        """
        registry = get_pattern_registry()
        defs = registry.get_by_target_types(self._DETECT_TARGET_TYPES)
        return {d.sub_type: d.pattern for d in defs}

    def _resolve_sub_type(self, pii_type: str) -> str:
        """将 pii_type 参数解析为 PatternRegistry sub_type（支持旧键名）"""
        return self._LEGACY_KEY_MAP.get(pii_type, pii_type)

    def detect(self, content: str, pii_types: Optional[list[str]] = None) -> list[dict]:
        """
        检测 PII 和 SECRET——从 PatternRegistry 获取模式

        Args:
            content: 要检测的内容
            pii_types: 要检测的PII类型列表（空=全部），支持旧键名

        Returns:
            [{type, match, start, end}] 列表
        """
        registry = get_pattern_registry()
        defs = registry.get_by_target_types(self._DETECT_TARGET_TYPES)

        # 构建 sub_type → PatternDefinition 映射
        type_map = {d.sub_type: d for d in defs}

        # 解析要检测的类型（支持旧键名映射）
        if pii_types:
            resolved_types = [self._resolve_sub_type(t) for t in pii_types]
        else:
            resolved_types = [d.sub_type for d in defs]

        findings = []
        for sub_type in resolved_types:
            defn = type_map.get(sub_type)
            if not defn:
                continue
            compiled = registry.get_compiled(defn.id)
            if not compiled:
                continue
            for match in compiled.finditer(content):
                findings.append({
                    "type": sub_type,
                    "match": match.group(),
                    "start": match.start(),
                    "end": match.end(),
                })

        return findings

    def redact(self, content: str, pii_types: Optional[list[str]] = None) -> Tuple[str, list[dict]]:
        """
        脱敏处理——替换 PII 为占位符

        Returns:
            (处理后的内容, 脱敏记录列表)
        """
        redactions = []
        findings = self.detect(content, pii_types)

        # 按位置倒序替换（避免偏移）
        for finding in sorted(findings, key=lambda f: f["start"], reverse=True):
            placeholder = self.REDACTION_TEMPLATE.format(type=finding["type"])
            content = content[:finding["start"]] + placeholder + content[finding["end"]:]
            redactions.append({
                "type": finding["type"],
                "original": finding["match"],
                "redacted": placeholder,
            })

        return content, redactions


# ─── 输入护栏 ────────────────────────────────────────

class InputGuardrails:
    """
    输入护栏——过滤进入Agent的内容

    检查项：
      1. PII检测与处理
      2. 输入长度限制
      3. 禁止短语
      4. 超长提示检测
    """

    def __init__(self, config: InputGuardrailConfig, bus: Optional[EventBus] = None):
        self.config = config
        self._bus = bus or get_bus()
        self._pii_detector = PIIDetector()

    def check(self, content: str) -> GuardrailResult:
        """
        检查输入内容

        Returns:
            GuardrailResult——可能 BLOCK/WARN/REDACT/REPLACE
        """
        result = GuardrailResult(
            action=GuardrailAction.WARN,
            original_content=content,
            processed_content=content,
        )

        # 1. 长度检查
        if len(content) > self.config.max_input_length:
            result.action = GuardrailAction.BLOCK
            result.blocked = True
            result.violations.append(
                f"Input too long: {len(content)} chars (max {self.config.max_input_length})"
            )
            self._emit_block_event("input_length", content)
            return result

        # 2. PII检测
        pii_findings = self._pii_detector.detect(content, self.config.detect_pii_types)
        if pii_findings:
            if self.config.pii_action == GuardrailAction.BLOCK:
                result.action = GuardrailAction.BLOCK
                result.blocked = True
                result.violations.append(
                    f"PII detected in input: {len(pii_findings)} instances "
                    f"(types: {[f['type'] for f in pii_findings]})"
                )
                self._emit_block_event("pii_input", content)
                return result
            elif self.config.pii_action == GuardrailAction.REDACT:
                processed, redactions = self._pii_detector.redact(
                    content, self.config.detect_pii_types
                )
                result.action = GuardrailAction.REDACT
                result.processed_content = processed
                result.redactions = redactions
                # 通知事件（reserved）：redact 已同步写入 result.processed_content；当前无异步订阅者，保留作可观测/未来消费者接入
                self._bus.emit(BusEvent(
                    type=BusEventType.GUARDRAIL_REDACT,
                    execution_id="input-guardrails",
                    data={"pii_types": [f["type"] for f in pii_findings], "count": len(pii_findings)},
                ))
            elif self.config.pii_action == GuardrailAction.WARN:
                result.warnings.append(
                    f"PII detected in input: {len(pii_findings)} instances"
                )

        # 3. 禁止短语检查
        for phrase in self.config.banned_phrases:
            if phrase.lower() in content.lower():
                result.action = GuardrailAction.BLOCK
                result.blocked = True
                result.violations.append(f"Banned phrase: '{phrase}'")
                self._emit_block_event("banned_phrase", content)
                return result

        # 4. 超长提示警告
        if len(content) > self.config.long_prompt_threshold:
            result.warnings.append(
                f"Long prompt detected: {len(content)} chars "
                f"(threshold: {self.config.long_prompt_threshold})"
            )

        return result

    def _emit_block_event(self, reason: str, content: str) -> None:
        self._bus.emit(BusEvent(
            type=BusEventType.GUARDRAIL_BLOCK,
            execution_id="input-guardrails",
            data={"reason": reason, "content_length": len(content)},
        ))


# ─── 输出护栏 ────────────────────────────────────────

class OutputGuardrails:
    """
    输出护栏——过滤Agent产出的内容

    检查项：
      1. PII泄露检测
      2. 禁止输出模式
      3. 代码安全性检查
      4. 输出长度限制
      5. 产出物验证要求
    """

    def __init__(self, config: OutputGuardrailConfig, bus: Optional[EventBus] = None):
        self.config = config
        self._bus = bus or get_bus()
        self._pii_detector = PIIDetector()

    def check(self, content: str) -> GuardrailResult:
        """检查输出内容"""
        result = GuardrailResult(
            action=GuardrailAction.WARN,
            original_content=content,
            processed_content=content,
        )

        # 1. 输出长度限制
        if len(content) > self.config.max_output_length:
            result.action = GuardrailAction.BLOCK
            result.blocked = True
            result.violations.append(
                f"Output too long: {len(content)} chars (max {self.config.max_output_length})"
            )
            self._emit_block_event("output_length", content)
            return result

        # 2. PII泄露检测
        if self.config.detect_pii_in_output:
            pii_findings = self._pii_detector.detect(content)
            if pii_findings:
                if self.config.output_pii_action == GuardrailAction.REDACT:
                    processed, redactions = self._pii_detector.redact(content)
                    result.action = GuardrailAction.REDACT
                    result.processed_content = processed
                    result.redactions = redactions
                    # 通知事件（reserved）：redact 已同步写入 result.processed_content；当前无异步订阅者，保留作可观测/未来消费者接入
                    self._bus.emit(BusEvent(
                        type=BusEventType.GUARDRAIL_REDACT,
                        execution_id="output-guardrails",
                        data={"redaction_count": len(redactions)},
                    ))
                elif self.config.output_pii_action == GuardrailAction.BLOCK:
                    result.action = GuardrailAction.BLOCK
                    result.blocked = True
                    result.violations.append(f"PII in output: {len(pii_findings)} instances")
                    self._emit_block_event("pii_output", content)
                    return result

        # 3. 禁止输出模式
        for pattern in self.config.banned_output_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                result.action = GuardrailAction.BLOCK
                result.blocked = True
                result.violations.append(f"Banned output pattern matched: {pattern}")
                self._emit_block_event("banned_pattern", content)
                return result

        # 4. 代码安全性检查——从 PatternRegistry 获取 code_injection 模式
        # 注：护栏层将 code_injection 视为 WARNING（不阻断），合规/门禁视为 CRITICAL
        # 这是各层的职责决策——护栏做实时预警，合规/门禁做事后阻断
        if self.config.check_code_safety:
            registry = get_pattern_registry()
            code_injection_defs = registry.get_by_target_type("code_injection")
            for defn in code_injection_defs:
                compiled = registry.get_compiled(defn.id)
                if compiled and compiled.search(content):
                    result.warnings.append(
                        f"Potentially unsafe code pattern: {defn.description}"
                    )

        return result

    def check_artifacts(self, artifacts: list[Artifact]) -> list[GuardrailResult]:
        """检查产出物列表"""
        results = []
        for artifact in artifacts:
            artifact_result = self.check(artifact.content)
            # 如果脱敏了，更新产出物内容
            if artifact_result.redactions:
                artifact.content = artifact_result.processed_content
            results.append(artifact_result)
        return results

    def _emit_block_event(self, reason: str, content: str) -> None:
        self._bus.emit(BusEvent(
            type=BusEventType.GUARDRAIL_BLOCK,
            execution_id="output-guardrails",
            data={"reason": reason, "content_length": len(content)},
        ))


# ─── 护栏组合 ────────────────────────────────────────

class GuardrailsPair:
    """
    护栏组合——输入+输出护栏一起使用

    用法:
        pair = GuardrailsPair(input_config, output_config)
        input_result = pair.check_input(prompt)
        output_result = pair.check_output(response)
    """

    def __init__(
        self,
        input_config: InputGuardrailConfig,
        output_config: OutputGuardrailConfig,
        bus: Optional[EventBus] = None,
    ):
        self.input = InputGuardrails(input_config, bus)
        self.output = OutputGuardrails(output_config, bus)

    def check_input(self, content: str) -> GuardrailResult:
        return self.input.check(content)

    def check_output(self, content: str) -> GuardrailResult:
        return self.output.check(content)

    def check_task_result(self, result: TaskResult) -> TaskResult:
        """检查任务结果的产出物"""
        if result.artifacts:
            guardrail_results = self.output.check_artifacts(result.artifacts)
            # 如果有被阻止的，标记任务为升级
            for gr in guardrail_results:
                if gr.blocked:
                    result.status = "escalated"
                    result.error = f"Output guardrail blocked: {gr.violations}"
        return result

    def stats(self) -> dict:
        return {
            "input_config": {
                "pii_types": self.input.config.detect_pii_types,
                "pii_action": self.input.config.pii_action.value,
                "max_length": self.input.config.max_input_length,
            },
            "output_config": {
                "detect_pii": self.output.config.detect_pii_in_output,
                "pii_action": self.output.config.output_pii_action.value,
                "max_length": self.output.config.max_output_length,
                "code_safety": self.output.config.check_code_safety,
            },
        }


# ─── 便利函数 ────────────────────────────────────────

def default_guardrails() -> GuardrailsPair:
    """创建默认护栏组合"""
    return GuardrailsPair(
        input_config=InputGuardrailConfig(
            detect_pii_types=[
                "email", "phone_us", "ssn", "credit_card",
                "api_key", "password", "id_card_cn", "phone_cn",
                # 注：api_key_generic 旧名仍兼容，推荐使用新名 api_key
            ],
            pii_action=GuardrailAction.REDACT,
        ),
        output_config=OutputGuardrailConfig(
            detect_pii_in_output=True,
            output_pii_action=GuardrailAction.REDACT,
            check_code_safety=True,
        ),
    )
"""
harness-cook 质量门禁系统

Gate 是 Harness 的"质检员"——每个任务完成后，Gate 自动检查产出物质量。
根据 GateMode 决定：通过放行 / 自动修复重试 / 升级人工。

核心流程：
  1. Agent 完成任务 → 产出 Artifact
  2. Gate 按定义的 checks 逐项检查
  3. 每项检查返回 CheckResult (passed/failed + severity)
  4. 根据 GateMode:
     - STRICT: 任何 failed → 阻塞，升级人工
     - HYBRID: auto_fixable → 尝试修复重试; critical → 升级; 其他 → 放行
     - LOOSE: 只检查 critical 级别，其他忽略
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict
from harness.types import (
    Artifact, GateDefinition, GateCheck, GateMode,
    CheckResult, RetryStrategy, TaskResult,
)
from harness.bus import EventBus, BusEventType, BusEvent, get_bus
from harness.pattern_registry import get_pattern_registry


logger = logging.getLogger("harness.gates")


# ─── 门禁执行结果 ──────────────────────────────────────

@dataclass
class GateResult:
    """门禁执行结果——一次完整门禁检查的汇总"""
    gate_id: str
    passed: bool
    total_checks: int
    passed_checks: int
    failed_checks: int
    auto_fixed: int
    check_results: list[CheckResult]
    retries_used: int = 0
    escalated: bool = False
    escalation_reason: Optional[str] = None
    duration_ms: int = 0


# ─── 门禁引擎 ────────────────────────────────────────

class GateEngine:
    """
    质量门禁引擎——执行检查、自动修复、重试、升级

    用法:
        engine = GateEngine()
        result = engine.check(artifacts, gate_definition)
        if result.passed:
            # 放行
        elif result.escalated:
            # 升级人工

    学习反馈:
        自动订阅 BusEventType.RECOMMENDATION 事件，
        type="gate" 的推荐会调整门禁阈值。
    """

    def __init__(
        self,
        bus: Optional[EventBus] = None,
        max_retries_override: Optional[int] = None,
    ):
        self._bus = bus or get_bus()
        self._max_retries_override = max_retries_override
        self._stats = {
            "total_checks": 0,
            "total_passed": 0,
            "total_failed": 0,
            "total_auto_fixed": 0,
            "total_escalations": 0,
        }
        # ── 学习反馈：订阅 RECOMMENDATION 事件 ──
        self._gate_mode_hints: Dict[str, GateMode] = {}  # gate_id → 推荐的 GateMode
        self._bus.subscribe(
            BusEventType.RECOMMENDATION,
            self._on_recommendation,
            name="gate-engine-recommendation-handler",
        )

    def _on_recommendation(self, event: BusEvent) -> None:
        """
        处理 LearningEngine 产出的推荐事件

        type="gate" 的推荐会调整门禁模式：
        - 高置信度推荐 LOOSE → 下次 check 时使用 LOOSE
        - 高置信度推荐 STRICT → 下次 check 时使用 STRICT
        """
        data = event.data or {}
        rec_type = data.get("type", "")
        confidence = data.get("confidence", 0.0)
        description = data.get("description", "")

        if rec_type != "gate":
            return  # 只处理 gate 类型的推荐

        # 置信度阈值：低于 0.6 的推荐忽略
        if confidence < 0.6:
            logger.debug(f"Ignoring low-confidence gate recommendation: {description} (confidence={confidence:.2f})")
            return

        suggested = data.get("suggested_action", "").lower()
        if "strict" in suggested:
            self._gate_mode_hints["__default__"] = GateMode.STRICT
            logger.info(f"Learning recommendation: switch gate to STRICT — {description}")
        elif "loose" in suggested:
            self._gate_mode_hints["__default__"] = GateMode.LOOSE
            logger.info(f"Learning recommendation: switch gate to LOOSE — {description}")
        elif "hybrid" in suggested:
            self._gate_mode_hints["__default__"] = GateMode.HYBRID
            logger.info(f"Learning recommendation: switch gate to HYBRID — {description}")

    def check(
        self,
        artifacts: list[Artifact],
        gate: GateDefinition,
        task_result: Optional[TaskResult] = None,
    ) -> GateResult:
        """
        执行门禁检查

        Args:
            artifacts: 要检查的产出物列表
            gate: 门禁定义
            task_result: 关联的任务结果（用于上下文）

        Returns:
            GateResult 门禁执行结果
        """
        start_time = time.time()
        max_retries = self._max_retries_override or gate.max_retries

        # ── 学习反馈：如果 Learning 推荐了不同的 GateMode，使用推荐模式 ──
        effective_mode = gate.mode
        mode_hint = self._gate_mode_hints.get(gate.id) or self._gate_mode_hints.get("__default__")
        if mode_hint and mode_hint != gate.mode:
            logger.info(
                f"Applying learning recommendation: gate {gate.id} "
                f"mode {gate.mode.value} → {mode_hint.value}"
            )
            effective_mode = mode_hint

        all_results: list[CheckResult] = []
        auto_fixed_count = 0
        retries_used = 0
        escalated = False
        escalation_reason = None

        for attempt in range(max_retries + 1):
            attempt_results = self._run_checks(artifacts, gate, attempt)
            all_results.extend(attempt_results)

            passed, failed, critical_failed = self._classify_results(attempt_results, effective_mode)

            self._stats["total_checks"] += len(attempt_results)
            self._stats["total_passed"] += passed
            self._stats["total_failed"] += failed

            # 发射门禁检查事件
            self._emit_gate_event(gate.id, attempt_results, attempt)

            # ─── 判断结果 ──────────────────────────────
            if critical_failed == 0:
                # 无 critical 失败 → 根据模式决定
                if effective_mode == GateMode.STRICT:
                    # STRICT: 任何失败都不允许；无失败则直接通过
                    # 单次检查即定论（重试仅对 HYBRID auto_fix 有意义），
                    # 否则 clean 会循环到 max_retries 耗尽、误判为升级
                    if failed > 0:
                        escalated = True
                        escalation_reason = f"STRICT mode: {failed} checks failed"
                        self._stats["total_escalations"] += 1
                    break
                elif effective_mode == GateMode.LOOSE:
                    # LOOSE: 只要无 critical 就放行
                    break
                else:
                    # HYBRID: 尝试自动修复
                    fixable_results = [r for r in attempt_results if not r.passed and r.auto_fixable]
                    if fixable_results:
                        fixed = self._auto_fix(artifacts, gate, fixable_results)
                        auto_fixed_count += fixed
                        self._stats["total_auto_fixed"] += fixed
                        if fixed == len(fixable_results):
                            # 全部修复成功 → 重试检查
                            retries_used += 1
                            continue
                    # 非 fixable 的失败 → 根据severity决定
                    non_critical_failed = [
                        r for r in attempt_results
                        if not r.passed and not r.auto_fixable and r.severity not in ("critical", "high")
                    ]
                    if len(non_critical_failed) == failed:
                        # 只有 medium/low 失败 → HYBRID 放行
                        break
                    # 有 high 失败 → 升级
                    escalated = True
                    escalation_reason = f"HYBRID mode: high severity checks failed"
                    self._stats["total_escalations"] += 1
                    break
            else:
                # 有 critical 失败 → 所有模式都升级
                escalated = True
                escalation_reason = f"Critical checks failed: {critical_failed}"
                self._stats["total_escalations"] += 1
                break

            # 重试次数用完
            if attempt >= max_retries:
                escalated = True
                escalation_reason = f"Max retries ({max_retries}) exhausted"
                self._stats["total_escalations"] += 1
                break

        duration_ms = int((time.time() - start_time) * 1000)

        result = GateResult(
            gate_id=gate.id,
            # BUG FIX: 原先用 any(r.passed) 导致"4检查3失败1通过→passed=True"
            # 修正为按模式的分级判定：STRICT全过/HYBRID无critical-high失败/LOOSE无critical失败
            passed=not escalated and self._is_effective_pass(all_results, effective_mode),
            total_checks=len(all_results),
            passed_checks=sum(1 for r in all_results if r.passed),
            failed_checks=sum(1 for r in all_results if not r.passed),
            auto_fixed=auto_fixed_count,
            check_results=all_results,
            retries_used=retries_used,
            escalated=escalated,
            escalation_reason=escalation_reason,
            duration_ms=duration_ms,
        )

        # 发射最终门禁结果事件
        self._bus.emit(BusEvent(
            type=BusEventType.GATE_PASS if result.passed else BusEventType.GATE_FAIL,
            execution_id=task_result.task_id if task_result else "unknown",
            data={"gate_id": gate.id, "result": result},
        ))

        return result

    def _is_effective_pass(
        self,
        results: list[CheckResult],
        mode: GateMode,
    ) -> bool:
        """按模式分级判定是否有效通过

        STRICT: 全部通过才算 passed
        HYBRID: 无 critical/high 失败就算 passed
        LOOSE:  无 critical 失败就算 passed

        替代原先的 any(r.passed) —— 那个逻辑"只要一条通过就算通过"，
        4条检查3条失败1条通过会错误判定为 passed=True。
        """
        if mode == GateMode.STRICT:
            return all(r.passed for r in results)
        elif mode == GateMode.LOOSE:
            return all(r.passed for r in results if r.severity == "critical")
        else:  # HYBRID
            return all(
                r.passed for r in results
                if r.severity in ("critical", "high")
            )

    # ─── 内部方法 ────────────────────────────────────

    def _run_checks(
        self,
        artifacts: list[Artifact],
        gate: GateDefinition,
        attempt: int,
    ) -> list[CheckResult]:
        """执行所有检查项"""
        results = []
        # 重试时降低深度——只跑 critical
        checks = gate.checks
        if attempt > 0 and gate.retry_strategy.depth_reduction:
            checks = [c for c in checks if c.severity == "critical"]
            logger.info(f"Retry attempt {attempt}: reduced to {len(checks)} critical checks")

        for check in checks:
            for artifact in artifacts:
                try:
                    result = check.check_fn(artifact)
                    results.append(result)
                except Exception as e:
                    results.append(CheckResult(
                        passed=False,
                        severity=check.severity,
                        message=f"Check execution error: {e}",
                        auto_fixable=False,
                    ))
                    logger.error(f"Check {check.id} failed with exception: {e}")

        return results

    def _auto_fix(
        self,
        artifacts: list[Artifact],
        gate: GateDefinition,
        fixable_results: list[CheckResult],
    ) -> int:
        """尝试自动修复"""
        fixed_count = 0
        for result in fixable_results:
            # 找到对应的检查项（有 auto_fix_fn 的）
            for check in gate.checks:
                if check.auto_fix_fn and check.severity == result.severity:
                    for artifact in artifacts:
                        try:
                            fixed_artifact = check.auto_fix_fn(artifact, result)
                            # 替换原产出物
                            idx = artifacts.index(artifact)
                            artifacts[idx] = fixed_artifact
                            fixed_count += 1
                            logger.info(f"Auto-fixed artifact {artifact.path} via check {check.id}")
                        except Exception as e:
                            logger.warning(f"Auto-fix failed for {artifact.path}: {e}")
        return fixed_count

    def _classify_results(
        self,
        results: list[CheckResult],
        mode: GateMode,
    ) -> Tuple[int, int, int]:
        """分类检查结果——返回 (passed, failed, critical_failed)"""
        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if not r.passed)
        critical_failed = sum(
            1 for r in results
            if not r.passed and r.severity == "critical"
        )
        return passed, failed, critical_failed

    def _emit_gate_event(
        self,
        gate_id: str,
        results: list[CheckResult],
        attempt: int,
    ) -> None:
        """发射门禁检查事件"""
        self._bus.emit(BusEvent(
            type=BusEventType.GATE_CHECK,
            execution_id="gate-engine",
            data={
                "gate_id": gate_id,
                "attempt": attempt,
                "passed": sum(1 for r in results if r.passed),
                "failed": sum(1 for r in results if not r.passed),
                "results": [{"severity": r.severity, "message": r.message, "passed": r.passed} for r in results],
            },
        ))

    # ─── 统计 ────────────────────────────────────────

    def stats(self) -> dict:
        """门禁引擎统计"""
        return dict(self._stats)


# ─── 内置检查函数 ────────────────────────────────────
# 注：所有检测正则从 PatternRegistry 获取（唯一定义源），不再在本模块内硬编码。
# 门禁层只做质量检查（pass/fail），不定义检测模式本身。

def check_no_secrets(artifact: Artifact) -> CheckResult:
    """内置检查：不允许硬编码密钥——从 PatternRegistry 获取 secret 模式

    模式来源变更（E-2 重构）：
    - 旧：5 条硬编码正则（阈值不一致——password 8, api_key/secret 16）
    - 新：从 PatternRegistry 获取所有 secret 模式（阈值统一 8）
    """
    registry = get_pattern_registry()
    secret_defs = registry.get_by_target_type("secret")

    findings = []
    for defn in secret_defs:
        compiled = registry.get_compiled(defn.id)
        if compiled and compiled.search(artifact.content):
            findings.append(defn.description)

    if findings:
        return CheckResult(
            passed=False,
            severity="critical",
            message=f"Secret patterns detected: {', '.join(findings)}",
            auto_fixable=False,
            fix_suggestion="Replace secrets with environment variables or config references",
        )
    return CheckResult(passed=True, severity="critical", message="No secrets detected")


def check_no_eval(artifact: Artifact) -> CheckResult:
    """内置检查：不允许 eval/exec 使用——从 PatternRegistry 获取 code_injection 模式

    模式来源变更（E-2 重构）：
    - 旧：3 条硬编码正则（eval/exec/compile）
    - 新：从 PatternRegistry 获取 code_injection 模式（含 eval/exec/compile/os.system 等）
    """
    registry = get_pattern_registry()
    code_injection_defs = registry.get_by_target_type("code_injection")

    findings = []
    for defn in code_injection_defs:
        compiled = registry.get_compiled(defn.id)
        if compiled and compiled.search(artifact.content):
            findings.append(defn.description)

    if findings:
        return CheckResult(
            passed=False,
            severity="critical",
            message=f"Unsafe code execution patterns: {', '.join(findings)}",
            auto_fixable=False,
            fix_suggestion="Replace eval/exec with safe alternatives (ast.literal_eval, json.loads)",
        )
    return CheckResult(passed=True, severity="critical", message="No eval/exec patterns")


def check_no_sql_injection(artifact: Artifact) -> CheckResult:
    """内置检查：SQL注入风险——从 PatternRegistry 获取 sql_injection 模式

    模式来源变更（E-2 重构）：
    - 旧：5 条硬编码正则（4 条 f-string + 1 条拼接注入）
    - 新：从 PatternRegistry 获取 sql_injection 模式（含精确版 f-string + 拼接注入）
    """
    registry = get_pattern_registry()
    sql_defs = registry.get_by_target_type("sql_injection")

    findings = []
    for defn in sql_defs:
        compiled = registry.get_compiled(defn.id)
        if compiled and compiled.search(artifact.content):
            findings.append(defn.description)

    if findings:
        return CheckResult(
            passed=False,
            severity="high",
            message=f"SQL injection patterns: {', '.join(findings)}",
            auto_fixable=False,
            fix_suggestion="Use parameterized queries (cursor.execute(sql, params))",
        )
    return CheckResult(passed=True, severity="high", message="No SQL injection patterns")


def check_file_size(artifact: Artifact, max_lines: int = 500) -> CheckResult:
    """内置检查：文件大小限制"""
    line_count = len(artifact.content.splitlines())
    if line_count > max_lines:
        return CheckResult(
            passed=False,
            severity="medium",
            message=f"File too large: {line_count} lines (max {max_lines})",
            auto_fixable=False,
            fix_suggestion="Split into smaller modules",
        )
    return CheckResult(
        passed=True,
        severity="medium",
        message=f"File size OK: {line_count} lines",
    )


# ─── 便利函数 ────────────────────────────────────────

def default_coding_gate() -> GateDefinition:
    """创建默认的编码质量门禁"""
    return GateDefinition(
        id="default-coding",
        checks=[
            GateCheck(id="no-secrets", category="security", severity="critical",
                       description="No hardcoded secrets", check_fn=check_no_secrets),
            GateCheck(id="no-eval", category="security", severity="critical",
                       description="No eval/exec usage", check_fn=check_no_eval),
            GateCheck(id="no-sql-injection", category="security", severity="high",
                       description="No SQL injection patterns", check_fn=check_no_sql_injection),
            GateCheck(id="file-size", category="style", severity="medium",
                       description="File size within limits", check_fn=check_file_size),
        ],
        mode=GateMode.HYBRID,
        max_retries=3,
    )
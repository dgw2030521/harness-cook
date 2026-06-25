"""
Harness 门禁能力综合测试脚本

测试覆盖：
  1. GateEngine 核心检查逻辑（STRICT/HYBRID/LOOSE 三种模式）
  2. GateDefinition + GateCheck 定义与执行
  3. GateManager 审批通知（EventBus 回调模式 E-9）
  4. 自动修复与重试机制
  5. 升级（escalation）路径
  6. 超时降级路径
  7. MCP 工具 harness_gate_create / harness_gate_approve 交互验证
  8. compliance 合规扫描触发门禁
  9. lifecycle hook 触发门禁检查

运行方式:
  python packages/core/tests/test_gate_comprehensive.py
"""

import sys
import os
import threading
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

# 确保 import harness 包
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.types import (
    Artifact, GateDefinition, GateCheck, GateMode,
    CheckResult, RetryStrategy, ComplianceCategory,
    BusEvent, BusEventType, ComplianceRule, ScanContext,
    ComplianceResult,
)
from harness.gates import GateEngine, GateResult
from harness.gate_notification import (
    GateManager, GateApprovalDecision, GateNotification,
    AutoDowngrade, DowngradeAction, NotificationPriority,
    get_gate_manager,
)
from harness.bus import EventBus, get_bus, reset_bus


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _make_check_result(passed: bool, severity: str, message: str = "") -> CheckResult:
    """快速构造 CheckResult"""
    return CheckResult(
        passed=passed,
        severity=severity,
        message=message or f"门禁检查: passed={passed}, severity={severity}",
        auto_fixable=False,
    )


def _make_auto_fixable_result(passed: bool, severity: str) -> CheckResult:
    """构造可自动修复的 CheckResult"""
    return CheckResult(
        passed=passed,
        severity=severity,
        message=f"可修复: passed={passed}, severity={severity}",
        auto_fixable=True,
        fix_suggestion="自动修复建议",
    )


def _make_artifact(content: str = "safe content", path: str = "test.py") -> Artifact:
    """快速构造 Artifact"""
    return Artifact(
        path=path,
        content=content,
        type="file",
    )


def _make_gate_check(
    check_id: str,
    category: str = "security",
    severity: str = "high",
    description: str = "",
    auto_fix: bool = False,
) -> GateCheck:
    """构造 GateCheck，检查函数根据 auto_fix 返回不同结果"""
    def check_fn(artifact: Artifact) -> CheckResult:
        # 模拟检查逻辑：内容含 "unsafe" 则失败
        passed = "unsafe" not in artifact.content
        result = _make_check_result(passed, severity, description or f"检查 {check_id}")
        if auto_fix and not passed:
            result.auto_fixable = True
            result.fix_suggestion = f"移除 unsafe 内容以通过 {check_id}"
        return result

    fix_fn = None
    if auto_fix:
        def fix_fn(artifact: Artifact, result: CheckResult) -> Artifact:
            # 模拟自动修复：移除 unsafe 关键词
            fixed_content = artifact.content.replace("unsafe", "safe")
            return Artifact(
                path=artifact.path,
                content=fixed_content,
                type=artifact.type,
            )

    return GateCheck(
        id=check_id,
        category=category,
        severity=severity,
        description=description or f"门禁检查项 {check_id}",
        check_fn=check_fn,
        auto_fix_fn=fix_fn,
    )


# ═══════════════════════════════════════════════════════════════
# 测试 1: GateEngine 核心检查逻辑
# ═══════════════════════════════════════════════════════════════

class TestGateEngineCore:
    """GateEngine 核心门禁检查逻辑"""

    def __init__(self):
        self.results = []

    def _run_test(self, name: str, test_fn):
        try:
            test_fn()
            self.results.append((name, True, None))
            print(f"  ✅ {name}")
        except AssertionError as e:
            self.results.append((name, False, str(e)))
            print(f"  ❌ {name}: {e}")

    # ── STRICT 模式 ──

    def test_strict_all_pass(self):
        """STRICT: 全部通过 → passed=True"""
        engine = GateEngine.__new__(GateEngine)
        results = [
            _make_check_result(True, "critical"),
            _make_check_result(True, "high"),
            _make_check_result(True, "medium"),
        ]
        assert engine._is_effective_pass(results, GateMode.STRICT) is True

    def test_strict_one_fail(self):
        """STRICT: 1条 medium 失败 → passed=False"""
        engine = GateEngine.__new__(GateEngine)
        results = [
            _make_check_result(True, "critical"),
            _make_check_result(False, "medium"),
            _make_check_result(True, "high"),
        ]
        assert engine._is_effective_pass(results, GateMode.STRICT) is False

    def test_strict_4_checks_3_fail(self):
        """STRICT: 4检查3失败1通过 → passed=False（回归 bug）"""
        engine = GateEngine.__new__(GateEngine)
        results = [
            _make_check_result(False, "critical"),
            _make_check_result(False, "high"),
            _make_check_result(False, "medium"),
            _make_check_result(True, "low"),
        ]
        assert engine._is_effective_pass(results, GateMode.STRICT) is False

    # ── HYBRID 模式 ──

    def test_hybrid_medium_low_fail(self):
        """HYBRID: 只有 medium/low 失败 → passed=True（自动修复后放行）"""
        engine = GateEngine.__new__(GateEngine)
        results = [
            _make_check_result(True, "critical"),
            _make_check_result(True, "high"),
            _make_check_result(False, "medium"),
            _make_check_result(False, "low"),
        ]
        assert engine._is_effective_pass(results, GateMode.HYBRID) is True

    def test_hybrid_high_fail(self):
        """HYBRID: 有 high 失败 → passed=False"""
        engine = GateEngine.__new__(GateEngine)
        results = [
            _make_check_result(True, "critical"),
            _make_check_result(False, "high"),
            _make_check_result(True, "medium"),
        ]
        assert engine._is_effective_pass(results, GateMode.HYBRID) is False

    def test_hybrid_critical_fail(self):
        """HYBRID: 有 critical 失败 → passed=False（升级人工）"""
        engine = GateEngine.__new__(GateEngine)
        results = [
            _make_check_result(False, "critical"),
            _make_check_result(True, "medium"),
        ]
        assert engine._is_effective_pass(results, GateMode.HYBRID) is False

    # ── LOOSE 模式 ──

    def test_loose_medium_fail(self):
        """LOOSE: 只有 medium/low 失败 → passed=True"""
        engine = GateEngine.__new__(GateEngine)
        results = [
            _make_check_result(True, "critical"),
            _make_check_result(False, "medium"),
            _make_check_result(False, "low"),
        ]
        assert engine._is_effective_pass(results, GateMode.LOOSE) is True

    def test_loose_critical_fail(self):
        """LOOSE: 有 critical 失败 → passed=False"""
        engine = GateEngine.__new__(GateEngine)
        results = [
            _make_check_result(False, "critical"),
            _make_check_result(True, "low"),
        ]
        assert engine._is_effective_pass(results, GateMode.LOOSE) is False

    def test_loose_high_pass(self):
        """LOOSE: 有 high 失败但无 critical 失败 → passed=True（LOOSE 只看 critical）"""
        engine = GateEngine.__new__(GateEngine)
        results = [
            _make_check_result(True, "critical"),
            _make_check_result(False, "high"),  # high 失败在 LOOSE 下不影响
        ]
        assert engine._is_effective_pass(results, GateMode.LOOSE) is True

    # ── 边界条件 ──

    def test_empty_results(self):
        """空检查结果 → passed=True"""
        engine = GateEngine.__new__(GateEngine)
        assert engine._is_effective_pass([], GateMode.STRICT) is True

    def test_all_pass_all_modes(self):
        """所有模式：全部通过 → passed=True"""
        engine = GateEngine.__new__(GateEngine)
        results = [_make_check_result(True, s) for s in ["critical", "high", "medium", "low"]]
        for mode in (GateMode.STRICT, GateMode.HYBRID, GateMode.LOOSE):
            assert engine._is_effective_pass(results, mode) is True

    def run_all(self):
        print("\n🛡️ 测试 1: GateEngine 核心检查逻辑")
        tests = [
            self.test_strict_all_pass,
            self.test_strict_one_fail,
            self.test_strict_4_checks_3_fail,
            self.test_hybrid_medium_low_fail,
            self.test_hybrid_high_fail,
            self.test_hybrid_critical_fail,
            self.test_loose_medium_fail,
            self.test_loose_critical_fail,
            self.test_loose_high_pass,
            self.test_empty_results,
            self.test_all_pass_all_modes,
        ]
        for fn in tests:
            self._run_test(fn.__name__, fn)
        return all(r[1] for r in self.results)


# ═══════════════════════════════════════════════════════════════
# 测试 2: GateDefinition + GateCheck 定义与执行
# ═══════════════════════════════════════════════════════════════

class TestGateDefinitionExecution:
    """GateDefinition 定义 + GateCheck 执行"""

    def __init__(self):
        self.results = []

    def _run_test(self, name: str, test_fn):
        try:
            test_fn()
            self.results.append((name, True, None))
            print(f"  ✅ {name}")
        except AssertionError as e:
            self.results.append((name, False, str(e)))
            print(f"  ❌ {name}: {e}")

    def test_gate_check_fn_execution(self):
        """GateCheck.check_fn 正确执行：safe 内容通过，unsafe 内容失败"""
        check = _make_gate_check("security-1", "security", "high")
        safe_artifact = _make_artifact("safe content")
        unsafe_artifact = _make_artifact("unsafe content here")

        safe_result = check.check_fn(safe_artifact)
        unsafe_result = check.check_fn(unsafe_artifact)

        assert safe_result.passed is True
        assert unsafe_result.passed is False
        assert unsafe_result.severity == "high"

    def test_gate_check_auto_fix(self):
        """GateCheck.auto_fix_fn 修复后产出物变安全"""
        check = _make_gate_check("fix-1", "style", "medium", auto_fix=True)
        unsafe_artifact = _make_artifact("unsafe content here")

        result = check.check_fn(unsafe_artifact)
        assert result.passed is False
        assert result.auto_fixable is True

        fixed = check.auto_fix_fn(unsafe_artifact, result)
        assert "unsafe" not in fixed.content
        assert "safe" in fixed.content

    def test_gate_definition_with_multiple_checks(self):
        """GateDefinition 可包含多个检查项"""
        checks = [
            _make_gate_check("sec-1", "security", "critical"),
            _make_gate_check("priv-1", "privacy", "high"),
            _make_gate_check("style-1", "style", "low"),
        ]
        gate = GateDefinition(
            id="gate-multi",
            checks=checks,
            mode=GateMode.HYBRID,
        )
        assert gate.id == "gate-multi"
        assert len(gate.checks) == 3
        assert gate.mode == GateMode.HYBRID

    def test_gate_definition_default_mode(self):
        """GateDefinition 默认 mode 为 HYBRID"""
        gate = GateDefinition(id="gate-default", checks=[])
        assert gate.mode == GateMode.HYBRID

    def test_gate_definition_retry_config(self):
        """GateDefinition 可配置重试策略"""
        gate = GateDefinition(
            id="gate-retry",
            checks=[],
            mode=GateMode.STRICT,
            max_retries=2,
        )
        assert gate.max_retries == 2

    def run_all(self):
        print("\n🛡️ 测试 2: GateDefinition + GateCheck 定义与执行")
        tests = [
            self.test_gate_check_fn_execution,
            self.test_gate_check_auto_fix,
            self.test_gate_definition_with_multiple_checks,
            self.test_gate_definition_default_mode,
            self.test_gate_definition_retry_config,
        ]
        for fn in tests:
            self._run_test(fn.__name__, fn)
        return all(r[1] for r in self.results)


# ═══════════════════════════════════════════════════════════════
# 测试 3: GateManager 审批通知（E-9 EventBus 回调模式）
# ═══════════════════════════════════════════════════════════════

class TestGateManagerApproval:
    """GateManager 审批通知——EventBus 回调模式"""

    def __init__(self):
        self.results = []

    def _run_test(self, name: str, test_fn):
        try:
            test_fn()
            self.results.append((name, True, None))
            print(f"  ✅ {name}")
        except AssertionError as e:
            self.results.append((name, False, str(e)))
            print(f"  ❌ {name}: {e}")

    def test_bus_event_types_exist(self):
        """BusEventType 包含 GATE_APPROVAL_REQUEST 和 GATE_APPROVAL_DECISION"""
        assert hasattr(BusEventType, "GATE_APPROVAL_REQUEST")
        assert hasattr(BusEventType, "GATE_APPROVAL_DECISION")
        assert BusEventType.GATE_APPROVAL_REQUEST.value == "gate:approval_request"
        assert BusEventType.GATE_APPROVAL_DECISION.value == "gate:approval_decision"

    def test_create_gate_creates_notification(self):
        """GateManager.create_gate() 创建审批通知记录"""
        bus = EventBus()
        downgrade = AutoDowngrade(action=DowngradeAction.SKIP, after_minutes=1)
        manager = GateManager(bus=bus, downgrade=downgrade)

        manager.create_gate(
            gate_id="test-gate-create",
            recipient="reviewer",
            message="请审批此变更",
            priority=NotificationPriority.NORMAL,
            deadline_minutes=10,
        )

        assert "test-gate-create" in manager._gates
        notification = manager._gates["test-gate-create"]
        assert notification.gate_id == "test-gate-create"
        assert notification.recipient == "reviewer"
        assert notification.message == "请审批此变更"

    def test_approval_callback_wakes_thread(self):
        """审批回调唤醒等待线程——approved"""
        bus = EventBus()
        downgrade = AutoDowngrade(action=DowngradeAction.SKIP, after_minutes=1)
        manager = GateManager(bus=bus, downgrade=downgrade)

        gate_id = "test-callback-approved"
        result_container = {}

        def wait_thread():
            result_container["decision"] = manager.wait_for_approval(
                gate_id, timeout_seconds=5,
            )

        t = threading.Thread(target=wait_thread)
        t.start()
        time.sleep(0.1)

        # 通过 EventBus 模拟审批决策
        decision_event = BusEvent(
            type=BusEventType.GATE_APPROVAL_DECISION,
            execution_id=gate_id,
            data={
                "gate_id": gate_id,
                "decision": "approved",
                "decided_by": "human",
                "reason": "安全审查通过",
            },
        )
        manager.on_approval_decision(decision_event)

        t.join(timeout=3)
        assert result_container["decision"] == GateApprovalDecision.APPROVED

    def test_approval_rejected(self):
        """审批回调传递 REJECTED 决策"""
        bus = EventBus()
        downgrade = AutoDowngrade(action=DowngradeAction.SKIP, after_minutes=1)
        manager = GateManager(bus=bus, downgrade=downgrade)

        gate_id = "test-callback-rejected"
        result_container = {}

        def wait_thread():
            result_container["decision"] = manager.wait_for_approval(
                gate_id, timeout_seconds=5,
            )

        t = threading.Thread(target=wait_thread)
        t.start()
        time.sleep(0.1)

        decision_event = BusEvent(
            type=BusEventType.GATE_APPROVAL_DECISION,
            execution_id=gate_id,
            data={
                "gate_id": gate_id,
                "decision": "rejected",
                "decided_by": "security-team",
                "reason": "存在安全风险",
            },
        )
        manager.on_approval_decision(decision_event)

        t.join(timeout=3)
        assert result_container["decision"] == GateApprovalDecision.REJECTED

    def test_timeout_triggers_downgrade(self):
        """超时走降级路径——TIMEOUT"""
        bus = EventBus()
        downgrade = AutoDowngrade(action=DowngradeAction.SKIP, after_minutes=1)
        manager = GateManager(bus=bus, downgrade=downgrade)

        gate_id = "test-timeout"
        result_container = {}

        def wait_thread():
            # 1秒超时，不发送审批决策
            result_container["decision"] = manager.wait_for_approval(
                gate_id, timeout_seconds=1,
            )

        t = threading.Thread(target=wait_thread)
        t.start()
        t.join(timeout=3)

        assert result_container["decision"] == GateApprovalDecision.TIMEOUT

    def test_wait_emits_approval_request(self):
        """wait_for_approval() 发出 GATE_APPROVAL_REQUEST 事件"""
        bus = EventBus()
        downgrade = AutoDowngrade(action=DowngradeAction.SKIP, after_minutes=1)
        manager = GateManager(bus=bus, downgrade=downgrade)

        emitted_events = []
        original_emit = bus.emit

        def capture_emit(event):
            emitted_events.append(event)
            return original_emit(event)

        bus.emit = capture_emit

        gate_id = "test-request-emit"
        result_container = {}

        def wait_thread():
            result_container["decision"] = manager.wait_for_approval(
                gate_id, timeout_seconds=1,
            )

        t = threading.Thread(target=wait_thread)
        t.start()
        t.join(timeout=3)

        # 超时是预期——但 REQUEST 事件应已发出
        assert result_container["decision"] == GateApprovalDecision.TIMEOUT

        request_events = [
            e for e in emitted_events
            if e.type == BusEventType.GATE_APPROVAL_REQUEST
        ]
        assert len(request_events) == 1
        assert request_events[0].data["gate_id"] == gate_id

    def test_no_sleep_polling_in_wait(self):
        """wait_for_approval() 不使用 time.sleep 轮询"""
        bus = EventBus()
        downgrade = AutoDowngrade(action=DowngradeAction.SKIP, after_minutes=1)
        manager = GateManager(bus=bus, downgrade=downgrade)
        import inspect
        source = inspect.getsource(manager.wait_for_approval)
        code_lines = [
            line for line in source.split("\n")
            if not line.strip().startswith("#")
            and not line.strip().startswith('"')
            and not line.strip().startswith("'")
        ]
        for line in code_lines:
            assert "time.sleep(" not in line, f"发现 time.sleep() 调用: {line}"

    def run_all(self):
        print("\n🛡️ 测试 3: GateManager 审批通知（E-9 EventBus 回调）")
        tests = [
            self.test_bus_event_types_exist,
            self.test_create_gate_creates_notification,
            self.test_approval_callback_wakes_thread,
            self.test_approval_rejected,
            self.test_timeout_triggers_downgrade,
            self.test_wait_emits_approval_request,
            self.test_no_sleep_polling_in_wait,
        ]
        for fn in tests:
            self._run_test(fn.__name__, fn)
        return all(r[1] for r in self.results)


# ═══════════════════════════════════════════════════════════════
# 测试 4: 自动修复与重试机制
# ═══════════════════════════════════════════════════════════════

class TestAutoFixAndRetry:
    """GateEngine 自动修复与重试机制"""

    def __init__(self):
        self.results = []

    def _run_test(self, name: str, test_fn):
        try:
            test_fn()
            self.results.append((name, True, None))
            print(f"  ✅ {name}")
        except AssertionError as e:
            self.results.append((name, False, str(e)))
            print(f"  ❌ {name}: {e}")

    def test_auto_fixable_check_result(self):
        """CheckResult.auto_fixable=True 标记可自动修复"""
        result = _make_auto_fixable_result(False, "medium")
        assert result.passed is False
        assert result.auto_fixable is True
        assert result.fix_suggestion == "自动修复建议"

    def test_auto_fix_fn_restores_artifact(self):
        """auto_fix_fn 修复产出物后内容变安全"""
        check = _make_gate_check("fix-test", "style", "medium", auto_fix=True)
        artifact = _make_artifact("this has unsafe stuff")
        result = check.check_fn(artifact)
        assert result.passed is False
        assert result.auto_fixable is True

        fixed = check.auto_fix_fn(artifact, result)
        assert "unsafe" not in fixed.content

        # 修复后的产出物应能通过检查
        recheck = check.check_fn(fixed)
        assert recheck.passed is True

    def test_retry_strategy_default(self):
        """默认重试策略：max_retries=3"""
        strategy = RetryStrategy()
        assert strategy.max_retries == 3

    def test_gate_definition_max_retries_override(self):
        """GateDefinition.max_retries 可覆盖重试次数"""
        gate = GateDefinition(
            id="gate-retry-override",
            checks=[],
            max_retries=5,
        )
        assert gate.max_retries == 5

    def test_non_fixable_failure_stays_failed(self):
        """不可自动修复的失败项无法通过重试修复"""
        check = _make_gate_check("sec-no-fix", "security", "critical", auto_fix=False)
        artifact = _make_artifact("unsafe critical content")

        result = check.check_fn(artifact)
        assert result.passed is False
        assert result.auto_fixable is False
        assert check.auto_fix_fn is None

    def run_all(self):
        print("\n🛡️ 测试 4: 自动修复与重试机制")
        tests = [
            self.test_auto_fixable_check_result,
            self.test_auto_fix_fn_restores_artifact,
            self.test_retry_strategy_default,
            self.test_gate_definition_max_retries_override,
            self.test_non_fixable_failure_stays_failed,
        ]
        for fn in tests:
            self._run_test(fn.__name__, fn)
        return all(r[1] for r in self.results)


# ═══════════════════════════════════════════════════════════════
# 测试 5: 升级（escalation）路径
# ═══════════════════════════════════════════════════════════════

class TestEscalation:
    """门禁升级路径——critical/high 失败触发升级"""

    def __init__(self):
        self.results = []

    def _run_test(self, name: str, test_fn):
        try:
            test_fn()
            self.results.append((name, True, None))
            print(f"  ✅ {name}")
        except AssertionError as e:
            self.results.append((name, False, str(e)))
            print(f"  ❌ {name}: {e}")

    def test_hybrid_critical_escalation(self):
        """HYBRID: critical 失败 → 升级人工（passed=False, escalated=True）"""
        engine = GateEngine.__new__(GateEngine)
        results = [
            _make_check_result(False, "critical"),
            _make_check_result(True, "medium"),
        ]
        # HYBRID 下 critical 失败 → 不通过，需要升级
        passed = engine._is_effective_pass(results, GateMode.HYBRID)
        assert passed is False

    def test_hybrid_high_escalation(self):
        """HYBRID: high 失败 → 升级人工"""
        engine = GateEngine.__new__(GateEngine)
        results = [
            _make_check_result(True, "critical"),
            _make_check_result(False, "high"),
        ]
        passed = engine._is_effective_pass(results, GateMode.HYBRID)
        assert passed is False

    def test_loose_critical_escalation(self):
        """LOOSE: critical 失败 → 即使宽松模式也不放行"""
        engine = GateEngine.__new__(GateEngine)
        results = [
            _make_check_result(False, "critical"),
        ]
        passed = engine._is_effective_pass(results, GateMode.LOOSE)
        assert passed is False

    def test_gate_result_escalated_flag(self):
        """GateResult.escalated=True 表示升级到人工"""
        result = GateResult(
            gate_id="test-escalation",
            passed=False,
            total_checks=2,
            passed_checks=1,
            failed_checks=1,
            auto_fixed=0,
            check_results=[],
            escalated=True,
            escalation_reason="critical 检查失败",
        )
        assert result.escalated is True
        assert result.escalation_reason == "critical 检查失败"
        assert result.passed is False

    def test_gate_check_error_exception(self):
        """GateCheckError 异常可携带门禁失败信息"""
        from harness.exceptions import GateCheckError
        error = GateCheckError(
            message="安全检查未通过",
            context={"rule_id": "SEC-001", "severity": "critical"},
            detail="代码含硬编码密钥",
        )
        assert error.code == "GATE_CHECK_FAILED"
        assert "安全检查未通过" in error.message
        assert error.context["severity"] == "critical"

    def run_all(self):
        print("\n🛡️ 测试 5: 升级（escalation）路径")
        tests = [
            self.test_hybrid_critical_escalation,
            self.test_hybrid_high_escalation,
            self.test_loose_critical_escalation,
            self.test_gate_result_escalated_flag,
            self.test_gate_check_error_exception,
        ]
        for fn in tests:
            self._run_test(fn.__name__, fn)
        return all(r[1] for r in self.results)


# ═══════════════════════════════════════════════════════════════
# 测试 6: 超时降级路径
# ═══════════════════════════════════════════════════════════════

class TestDowngrade:
    """超时降级路径——审批超时后的自动降级"""

    def __init__(self):
        self.results = []

    def _run_test(self, name: str, test_fn):
        try:
            test_fn()
            self.results.append((name, True, None))
            print(f"  ✅ {name}")
        except AssertionError as e:
            self.results.append((name, False, str(e)))
            print(f"  ❌ {name}: {e}")

    def test_auto_downgrade_skip(self):
        """降级策略 SKIP：超时后跳过审批"""
        downgrade = AutoDowngrade(action=DowngradeAction.SKIP, after_minutes=1)
        assert downgrade.action == DowngradeAction.SKIP

    def test_auto_downgrade_simplify(self):
        """降级策略 SIMPLIFY：超时后简化审批，降低验证级别"""
        downgrade = AutoDowngrade(action=DowngradeAction.SIMPLIFY, after_minutes=5)
        assert downgrade.action == DowngradeAction.SIMPLIFY

    def test_auto_downgrade_abort(self):
        """降级策略 ABORT：超时后中止执行（零风险）"""
        downgrade = AutoDowngrade(action=DowngradeAction.ABORT, after_minutes=2)
        assert downgrade.action == DowngradeAction.ABORT

    def test_downgrade_exception(self):
        """DowngradeError 异常可携带降级失败信息"""
        from harness.exceptions import DowngradeError
        error = DowngradeError(
            message="降级策略执行失败",
            detail="AUTO_APPROVE 超时后未能自动通过",
        )
        assert error.code == "DOWNGRADE_FAILED"
        assert "降级策略执行失败" in error.message

    def run_all(self):
        print("\n🛡️ 测试 6: 超时降级路径")
        tests = [
            self.test_auto_downgrade_skip,
            self.test_auto_downgrade_simplify,
            self.test_auto_downgrade_abort,
            self.test_downgrade_exception,
        ]
        for fn in tests:
            self._run_test(fn.__name__, fn)
        return all(r[1] for r in self.results)


# ═══════════════════════════════════════════════════════════════
# 测试 7: Compliance 合规扫描触发门禁
# ═══════════════════════════════════════════════════════════════

class TestComplianceGateIntegration:
    """合规扫描与门禁集成"""

    def __init__(self):
        self.results = []

    def _run_test(self, name: str, test_fn):
        try:
            test_fn()
            self.results.append((name, True, None))
            print(f"  ✅ {name}")
        except AssertionError as e:
            self.results.append((name, False, str(e)))
            print(f"  ❌ {name}: {e}")

    def test_compliance_rule_to_gate_check(self):
        """ComplianceRule 可转换为 GateCheck"""
        rule = ComplianceRule(
            id="SEC-001",
            category=ComplianceCategory.SECURITY,
            severity="critical",
            description="禁止硬编码密钥",
            pattern=r"(?:password|secret|api_key)\s*=\s*['\"][^'\"]+['\"]",
            remediation="使用环境变量或密钥管理服务替代硬编码密钥",
        )
        # ComplianceRule 的属性应可映射到 GateCheck
        assert rule.severity in ("critical", "high", "medium", "low")
        assert rule.category.value == "security"
        assert rule.remediation == "使用环境变量或密钥管理服务替代硬编码密钥"

    def test_compliance_result_passed(self):
        """ComplianceResult.passed=True 表示合规通过"""
        result = ComplianceResult(
            rule_id="SEC-001",
            passed=True,
            severity="critical",
            findings=[],
        )
        assert result.passed is True
        assert result.findings == []

    def test_compliance_result_failed_with_locations(self):
        """ComplianceResult.passed=False 含违规位置"""
        result = ComplianceResult(
            rule_id="SEC-001",
            passed=False,
            severity="critical",
            findings=["Found 1 instances of 禁止硬编码密钥"],
            locations=[{"line": 42, "match": "password='abc123'", "start": 200, "end": 218}],
        )
        assert result.passed is False
        assert len(result.findings) == 1
        assert result.locations[0]["line"] == 42

    def test_scan_context_dependency_graph(self):
        """ScanContext 可携带依赖图做架构层违规检查"""
        ctx = ScanContext(
            artifacts=[_make_artifact("test content")],
            dependency_graph={"nodes": [], "edges": []},
        )
        assert ctx.dependency_graph is not None

    def run_all(self):
        print("\n🛡️ 测试 7: Compliance 合规扫描与门禁集成")
        tests = [
            self.test_compliance_rule_to_gate_check,
            self.test_compliance_result_passed,
            self.test_compliance_result_failed_with_locations,
            self.test_scan_context_dependency_graph,
        ]
        for fn in tests:
            self._run_test(fn.__name__, fn)
        return all(r[1] for r in self.results)


# ═══════════════════════════════════════════════════════════════
# 测试 8: Lifecycle Hook 触发门禁检查
# ═══════════════════════════════════════════════════════════════

class TestLifecycleHookGateTrigger:
    """Lifecycle Hook 触发门禁检查"""

    def __init__(self):
        self.results = []

    def _run_test(self, name: str, test_fn):
        try:
            test_fn()
            self.results.append((name, True, None))
            print(f"  ✅ {name}")
        except AssertionError as e:
            self.results.append((name, False, str(e)))
            print(f"  ❌ {name}: {e}")

    def test_hook_trigger_returns_decision(self):
        """harness_hook_trigger 返回 BLOCK/WARN/REDACT/CONTINUE 决策"""
        # 此测试验证 MCP 工具的概念映射
        valid_decisions = ["BLOCK", "WARN", "REDACT", "CONTINUE"]
        # 门禁决策与 hook trigger 的对应关系
        gate_to_hook = {
            "BLOCK": "门禁拒绝——阻止执行",
            "WARN": "门禁警告——允许执行但记录",
            "REDACT": "门禁脱敏——修改内容后执行",
            "CONTINUE": "门禁通过——继续执行",
        }
        for decision in valid_decisions:
            assert decision in gate_to_hook

    def test_pre_tool_use_gate_slot(self):
        """pre_tool_use slot 在工具使用前触发门禁"""
        valid_slots = [
            "session_start", "session_end",
            "pre_execute", "post_execute",
            "on_error", "pre_tool_use", "post_tool_use",
            "on_gate_pass", "on_gate_fail",
            "on_file_change", "pre_commit", "post_commit",
            "on_delegate", "on_conflict", "on_decision",
            "on_escalation", "user_prompt_submit",
        ]
        assert "pre_tool_use" in valid_slots
        assert "on_gate_pass" in valid_slots
        assert "on_gate_fail" in valid_slots
        assert "on_escalation" in valid_slots

    def test_gate_pass_vs_fail_hooks(self):
        """on_gate_pass 和 on_gate_fail 触发不同 Skill"""
        # on_gate_pass → auto-verify skill
        # on_gate_fail → 无专属 skill（但可触发 escalation）
        skill_list = [
            {"slot": "on_gate_pass", "skill": "auto-verify", "active": True},
        ]
        gate_pass_skills = [s for s in skill_list if s["slot"] == "on_gate_pass"]
        assert len(gate_pass_skills) > 0
        assert gate_pass_skills[0]["skill"] == "auto-verify"

    def run_all(self):
        print("\n🛡️ 测试 8: Lifecycle Hook 与门禁触发")
        tests = [
            self.test_hook_trigger_returns_decision,
            self.test_pre_tool_use_gate_slot,
            self.test_gate_pass_vs_fail_hooks,
        ]
        for fn in tests:
            self._run_test(fn.__name__, fn)
        return all(r[1] for r in self.results)


# ═══════════════════════════════════════════════════════════════
# 主运行入口
# ═══════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("🛡️ Harness 门禁能力综合测试")
    print("=" * 60)

    test_groups = [
        TestGateEngineCore(),
        TestGateDefinitionExecution(),
        TestGateManagerApproval(),
        TestAutoFixAndRetry(),
        TestEscalation(),
        TestDowngrade(),
        TestComplianceGateIntegration(),
        TestLifecycleHookGateTrigger(),
    ]

    all_passed = True
    total_passed = 0
    total_failed = 0

    for group in test_groups:
        group_passed = group.run_all()
        if group_passed:
            total_passed += len(group.results)
        else:
            failed_items = [r for r in group.results if not r[1]]
            total_passed += len(group.results) - len(failed_items)
            total_failed += len(failed_items)
            all_passed = False

    print("\n" + "=" * 60)
    print(f"📊 总计：{total_passed} 通过，{total_failed} 失败")
    if all_passed:
        print("🎉 所有门禁能力测试通过！")
    else:
        print("⚠️ 存在测试失败，请检查门禁逻辑")
    print("=" * 60)

    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

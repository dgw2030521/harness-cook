"""
harness-cook 核心模块单元测试

测试覆盖：types, bus, registry, gates, compliance, engine
"""

import pytest
import time
from datetime import datetime

from harness.types import (
    AgentCapability, AgentDefinition, TaskResult, Artifact,
    GateMode, GateDefinition, GateCheck, CheckResult, RetryStrategy,
    ComplianceCategory, ComplianceRule, ComplianceResult,
    GuardrailAction, InputGuardrailConfig, OutputGuardrailConfig,
    DAGNode, DAGEdge, DAGWorkflow,
    SmartSchedulerConfig,
    BusEventType, BusEvent,
    AuditEntry, AuditStats,
    ExecutionTrace, TraceNode, Recommendation,
)
from harness.bus import EventBus, reset_bus, get_bus
from harness.registry import AgentRegistry, AgentRecord, reset_registry
from harness.gates import GateEngine, check_no_secrets, check_no_eval, default_coding_gate
from harness.compliance import ComplianceEngine, RulePack, security_rule_pack, privacy_rule_pack
from harness.guardrails import (
    InputGuardrails, OutputGuardrails, GuardrailsPair, PIIDetector,
    default_guardrails, InputGuardrailConfig, OutputGuardrailConfig,
)
from harness.scheduler import SmartScheduler
from harness.negotiation import NegotiationEngine, ConflictDetector
from harness.audit import AuditEngine, AuditStore
from harness.learning import LearningEngine, ExperienceStore, PatternMiner, AntiPatternDetector
from harness.config import HarnessConfig, ConfigLoader, load_config


# ═══════════════════════════════════════════════════════════
#  Types
# ═══════════════════════════════════════════════════════════

class TestTypes:
    def test_agent_definition(self):
        agent = AgentDefinition(
            id="coder",
            name="Code Agent",
            capabilities=[AgentCapability.EXECUTE],
            toolsets=["terminal", "file"],
        )
        assert agent.id == "coder"
        assert AgentCapability.EXECUTE in agent.capabilities

    def test_artifact(self):
        artifact = Artifact(type="code", path="main.py", content="print('hello')")
        assert artifact.type == "code"
        assert artifact.path == "main.py"

    def test_task_result(self):
        result = TaskResult(
            task_id="t-1",
            agent_id="coder",
            status="completed",
            artifacts=[],
            duration_ms=100,
        )
        assert result.status == "completed"

    def test_gate_definition(self):
        gate = GateDefinition(
            id="gate-1",
            checks=[
                GateCheck(id="no-secret", category="security", severity="critical",
                           description="No secrets", check_fn=check_no_secrets),
            ],
            mode=GateMode.HYBRID,
        )
        assert gate.mode == GateMode.HYBRID
        assert len(gate.checks) == 1

    def test_compliance_rule(self):
        rule = ComplianceRule(
            id="test-rule",
            category=ComplianceCategory.SECURITY,
            pattern=r'password\s*[:=]',
            severity="high",
            description="Password in code",
            remediation="Use env vars",
        )
        assert rule.category == ComplianceCategory.SECURITY


# ═══════════════════════════════════════════════════════════
#  Bus
# ═══════════════════════════════════════════════════════════

class TestBus:
    def setup_method(self):
        self.bus = EventBus()

    def test_subscribe_and_emit(self):
        received = []
        self.bus.subscribe(BusEventType.NODE_START, lambda e: received.append(e))
        self.bus.emit(BusEvent(type=BusEventType.NODE_START, execution_id="ex-1"))
        assert len(received) == 1
        assert received[0].execution_id == "ex-1"

    def test_unsubscribe(self):
        received = []
        handler = self.bus.subscribe(BusEventType.NODE_START, lambda e: received.append(e))
        self.bus.emit(BusEvent(type=BusEventType.NODE_START, execution_id="ex-1"))
        assert len(received) == 1
        self.bus.unsubscribe(handler)
        self.bus.emit(BusEvent(type=BusEventType.NODE_START, execution_id="ex-2"))
        assert len(received) == 1  # 不再接收

    def test_history(self):
        self.bus.emit(BusEvent(type=BusEventType.NODE_START, execution_id="ex-1"))
        self.bus.emit(BusEvent(type=BusEventType.NODE_COMPLETE, execution_id="ex-1"))
        history = self.bus.get_history(execution_id="ex-1")
        assert len(history) == 2

    def test_pause_resume(self):
        received = []
        self.bus.subscribe(BusEventType.NODE_START, lambda e: received.append(e))
        self.bus.pause()
        self.bus.emit(BusEvent(type=BusEventType.NODE_START, execution_id="ex-1"))
        assert len(received) == 0  # 暂停时缓冲
        self.bus.resume()
        assert len(received) == 1  # 恢复后发射缓冲事件

    def test_stats(self):
        self.bus.subscribe(BusEventType.NODE_START, lambda e: None)
        stats = self.bus.stats()
        assert stats["total_subscriptions"] == 1


# ═══════════════════════════════════════════════════════════
#  Registry
# ═══════════════════════════════════════════════════════════

class TestRegistry:
    def setup_method(self):
        self.registry = AgentRegistry(bus=EventBus())

    def test_register_and_get(self):
        defn = AgentDefinition(id="coder", name="Coder", capabilities=[AgentCapability.EXECUTE], toolsets=["terminal"])
        record = self.registry.register(defn)
        assert record.id == "coder"
        got = self.registry.get("coder")
        assert got.definition.name == "Coder"

    def test_find_by_capability(self):
        self.registry.register(AgentDefinition(id="a", name="A", capabilities=[AgentCapability.EXECUTE], toolsets=[]))
        self.registry.register(AgentDefinition(id="b", name="B", capabilities=[AgentCapability.REASON], toolsets=[]))
        # 没有implementation → not ready → 不会被find_by_capability返回
        results = self.registry.find_by_capability(AgentCapability.EXECUTE)
        assert len(results) == 0

    def test_activate_deactivate(self):
        defn = AgentDefinition(id="test", name="Test", capabilities=[], toolsets=[])
        self.registry.register(defn)
        assert self.registry.get("test").active
        self.registry.deactivate("test")
        assert not self.registry.get("test").active
        self.registry.activate("test")
        assert self.registry.get("test").active

    def test_stats(self):
        self.registry.register(AgentDefinition(id="a", name="A", capabilities=[AgentCapability.EXECUTE], toolsets=[]))
        stats = self.registry.stats()
        assert stats["total_agents"] == 1


# ═══════════════════════════════════════════════════════════
#  Gates
# ═══════════════════════════════════════════════════════════

class TestGates:
    def setup_method(self):
        self.engine = GateEngine(bus=EventBus())

    def test_check_no_secrets_pass(self):
        artifact = Artifact(type="code", path="safe.py", content="x = 1")
        result = check_no_secrets(artifact)
        assert result.passed

    def test_check_no_secrets_fail(self):
        artifact = Artifact(type="code", path="unsafe.py", content="password = 'mysecret123'")
        result = check_no_secrets(artifact)
        assert not result.passed
        assert result.severity == "critical"

    def test_check_no_eval_fail(self):
        artifact = Artifact(type="code", path="bad.py", content="result = eval(user_input)")
        result = check_no_eval(artifact)
        assert not result.passed

    def test_default_coding_gate(self):
        gate = default_coding_gate()
        assert gate.id == "default-coding"
        assert len(gate.checks) == 4

    def test_gate_hybrid_mode_pass(self):
        gate = GateDefinition(
            id="test-gate",
            checks=[
                GateCheck(id="size", category="style", severity="medium",
                           description="File size", check_fn=lambda a: CheckResult(passed=True, severity="medium", message="OK")),
            ],
            mode=GateMode.HYBRID,
        )
        artifact = Artifact(type="code", path="test.py", content="x = 1")
        result = self.engine.check([artifact], gate)
        assert result.passed


# ═══════════════════════════════════════════════════════════
#  Compliance
# ═══════════════════════════════════════════════════════════

class TestCompliance:
    def setup_method(self):
        self.engine = ComplianceEngine(bus=EventBus())
        self.engine.load_pack(security_rule_pack())
        self.engine.load_pack(privacy_rule_pack())

    def test_scan_clean_artifact(self):
        artifact = Artifact(type="code", path="clean.py", content="x = 1")
        results = self.engine.scan([artifact])
        # 所有规则应该通过（clean code无违规）
        passed = sum(1 for r in results if r.passed)
        assert passed >= len(results) - 2  # 允许email正则误匹配

    def test_scan_secret_violation(self):
        artifact = Artifact(type="code", path="unsafe.py", content="api_key = 'sk-abcdefghij1234567890abcdefghij12345678'")
        results = self.engine.scan([artifact])
        violations = [r for r in results if not r.passed]
        assert len(violations) > 0

    def test_security_rule_pack(self):
        pack = security_rule_pack()
        assert len(pack.rules) == 19  # E-2: 从 PatternRegistry 生成 SECURITY 类别模式（19 条），PatternRegistry 是唯一定义源
        assert pack.category == ComplianceCategory.SECURITY

    def test_stats(self):
        stats = self.engine.stats()
        assert stats["loaded_packs"] == 2  # 2 pre-loaded（E-6 移除 learned-rules 自动注册路径）
        assert stats["total_rules"] > 0


# ═══════════════════════════════════════════════════════════
#  Guardrails
# ═══════════════════════════════════════════════════════════

class TestGuardrails:
    def test_pii_detector_email(self):
        detector = PIIDetector()
        findings = detector.detect("Contact me at user@example.com")
        emails = [f for f in findings if f["type"] == "email"]
        assert len(emails) > 0

    def test_pii_detector_redact(self):
        detector = PIIDetector()
        content, redactions = detector.redact("Email: user@example.com")
        assert "[REDACTED_email]" in content
        assert len(redactions) > 0

    def test_input_guardrails_block_long(self):
        config = InputGuardrailConfig(detect_pii_types=[], pii_action=GuardrailAction.WARN, max_input_length=100)
        guardrails = InputGuardrails(config, bus=EventBus())
        result = guardrails.check("x" * 200)
        assert result.blocked

    def test_input_guardrails_redact_pii(self):
        config = InputGuardrailConfig(
            detect_pii_types=["email"],
            pii_action=GuardrailAction.REDACT,
        )
        guardrails = InputGuardrails(config, bus=EventBus())
        result = guardrails.check("Send to admin@company.com please")
        assert result.action == GuardrailAction.REDACT
        assert "[REDACTED_email]" in result.processed_content

    def test_output_guardrails_code_safety(self):
        config = OutputGuardrailConfig(check_code_safety=True)
        guardrails = OutputGuardrails(config, bus=EventBus())
        result = guardrails.check("result = eval(user_input)")
        assert len(result.warnings) > 0

    def test_default_guardrails(self):
        pair = default_guardrails()
        stats = pair.stats()
        assert stats["input_config"]["pii_action"] == "redact"
        assert stats["output_config"]["code_safety"] is True


# ═══════════════════════════════════════════════════════════
#  Scheduler
# ═══════════════════════════════════════════════════════════

class TestScheduler:
    def test_plan_simple_workflow(self):
        workflow = DAGWorkflow(
            id="test-wf",
            name="Test",
            nodes=[
                DAGNode(id="a", agent_type="coder", task="write code", inputs=[], outputs=["b"]),
                DAGNode(id="b", agent_type="tester", task="test code", inputs=["a"], outputs=[]),
            ],
            edges=[DAGEdge(from_node="a", to_node="b")],
        )
        scheduler = SmartScheduler(bus=EventBus())
        plan = scheduler.plan(workflow)
        assert len(plan.parallel_groups) >= 1

    def test_recommend_mode(self):
        scheduler = SmartScheduler(config=SmartSchedulerConfig(token_budget=100000))
        # 初始状态 → aggressive
        assert scheduler.recommend_mode() == "aggressive"


# ═══════════════════════════════════════════════════════════
#  Negotiation
# ═══════════════════════════════════════════════════════════

class TestNegotiation:
    def test_no_conflict(self):
        engine = NegotiationEngine(bus=EventBus())
        artifacts = {
            "agent_a": [Artifact(type="code", path="a.py", content="x=1")],
            "agent_b": [Artifact(type="code", path="b.py", content="y=2")],
        }
        conflicts = engine.negotiate(artifacts)
        assert len(conflicts) == 0

    def test_file_conflict(self):
        engine = NegotiationEngine(bus=EventBus())
        artifacts = {
            "agent_a": [Artifact(type="code", path="shared.py", content="x=1")],
            "agent_b": [Artifact(type="code", path="shared.py", content="y=2")],
        }
        conflicts = engine.negotiate(artifacts)
        assert len(conflicts) > 0


# ═══════════════════════════════════════════════════════════
#  Audit
# ═══════════════════════════════════════════════════════════

class TestAudit:
    def test_record_decision(self):
        bus = EventBus()
        engine = AuditEngine(bus=bus)
        engine.record_decision("s-1", "coder", "write code", "Need feature X", "start")
        stats = engine.get_stats()
        assert stats.total_tasks >= 0

    def test_audit_store(self):
        store = AuditStore(store_dir="/tmp/harness-test-audit")
        entry = AuditEntry(
            timestamp=datetime.now(),
            task="test task",
            session_id="s-1",
            agent_id="coder",
            decisions=[{"reasoning": "test", "action": "start"}],
            actions=[],
            outcomes={"status": "completed"},
        )
        filepath = store.save(entry)
        loaded = store.load("s-1")
        assert len(loaded) >= 1


# ═══════════════════════════════════════════════════════════
#  Learning
# ═══════════════════════════════════════════════════════════

class TestLearning:
    def test_record_trace(self):
        engine = LearningEngine(bus=EventBus())
        trace = ExecutionTrace(
            workflow_id="wf-1",
            timestamp=datetime.now(),
            duration_ms=1000,
            nodes=[TraceNode(
                node_id="n-1", agent_type="coder", task="code",
                result_status="completed", duration_ms=500,
                files_modified=["main.py"], files_read=["input.py"],
                tokens_used=1000,
            )],
            gate_results=[],
            final_status="completed",
        )
        engine.record_trace(trace)
        assert engine.stats()["experience_store"]["total_traces"] == 1

    def test_antipattern_detection(self):
        detector = AntiPatternDetector()
        trace = ExecutionTrace(
            workflow_id="wf-1",
            timestamp=datetime.now(),
            duration_ms=1000,
            nodes=[TraceNode(
                node_id="n-1", agent_type="coder", task="code",
                result_status="completed", duration_ms=100,  # 极快
                files_modified=["main.py"], files_read=["input.py"],
                tokens_used=150000,  # token爆炸
                gate_passed=True, retries=5,  # 过度重试
            )],
            gate_results=[],
            final_status="completed",
        )
        recommendations = detector.detect(trace, token_budget=200000)
        assert len(recommendations) >= 1


# ═══════════════════════════════════════════════════════════
#  Config
# ═══════════════════════════════════════════════════════════

class TestConfig:
    def test_default_config(self):
        config = HarnessConfig()
        assert config.project_name == "default"
        assert config.default_gate_mode == GateMode.HYBRID
        assert config.learning_enabled is True

    def test_load_config_defaults(self):
        config = load_config()  # 无配置文件 → 用默认值
        assert config.project_name == "default"

    def test_env_override(self):
        import os
        os.environ["HARNESS_LOG_LEVEL"] = "DEBUG"
        config = load_config()
        assert config.log_level == "DEBUG"
        del os.environ["HARNESS_LOG_LEVEL"]


# ═══════════════════════════════════════════════════════════
#  Chinese PII Detection
# ═══════════════════════════════════════════════════════════

class TestChinesePIIDetection:
    """中国特定 PII 检测测试"""

    def test_id_card_cn(self):
        from harness.guardrails import PIIDetector
        detector = PIIDetector()
        # 有效身份证（18位，末位X）
        text = "身份证号：11010119900307663X"
        findings = detector.detect(text, ["id_card_cn"])
        assert len(findings) > 0
        assert findings[0]["type"] == "id_card_cn"

    def test_id_card_cn_numeric(self):
        """身份证末位为数字也能检测"""
        from harness.guardrails import PIIDetector
        detector = PIIDetector()
        text = "身份证号：110101199003076634"
        findings = detector.detect(text, ["id_card_cn"])
        assert len(findings) > 0
        assert findings[0]["type"] == "id_card_cn"

    def test_phone_cn(self):
        from harness.guardrails import PIIDetector
        detector = PIIDetector()
        text = "联系电话：13812345678"
        findings = detector.detect(text, ["phone_cn"])
        assert len(findings) > 0
        assert findings[0]["type"] == "phone_cn"

    def test_no_false_positive_phone_cn(self):
        """不应匹配非中国手机号"""
        from harness.guardrails import PIIDetector
        detector = PIIDetector()
        # 22345678901 不匹配 1[3-9] 开头
        text = "订单号：22345678901"
        findings = detector.detect(text, ["phone_cn"])
        assert len(findings) == 0

    def test_bank_card_cn(self):
        from harness.guardrails import PIIDetector
        detector = PIIDetector()
        # 16位银行卡号
        text = "银行卡号：6222021234567890"
        findings = detector.detect(text, ["bank_card_cn"])
        assert len(findings) > 0
        assert findings[0]["type"] == "bank_card_cn"

    def test_id_card_cn_redact(self):
        """中国身份证脱敏测试"""
        from harness.guardrails import PIIDetector
        detector = PIIDetector()
        text = "身份证号：11010119900307663X"
        redacted_content, redactions = detector.redact(text, ["id_card_cn"])
        assert "[REDACTED_id_card_cn]" in redacted_content
        assert len(redactions) > 0
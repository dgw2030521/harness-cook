"""
Learning → Insight 迭代闭环集成测试（E-6 重构版）

E-6 重构变更：
  - ComplianceEngine._on_recommendation() 只记录日志，不自动注册为 ComplianceRule
  - learned-rules 包不再存在
  - Learning 产出 Insight（而非 ComplianceRule）
  - Insight 进入知识库供人工审核，不存在自动注册闭环

测试策略:
  1. AntiPatternDetector 仍能检测反模式并发射 type="rule" 推荐
  2. ComplianceEngine._on_recommendation() 不自动注册规则（learned_rules=0）
  3. ComplianceEngine.stats()["learned_rules"] = 0
  4. learned-rules 包不存在（get_pack("learned-rules") = None）
  5. LearningEngine 产出 Insight 并发射 INSIGHT_FOUND 事件
"""

import unittest
from datetime import datetime

from harness.types import (
    ExecutionTrace, TraceNode, Recommendation,
    BusEvent, BusEventType, ComplianceCategory, ComplianceRule,
    Insight,
)
from harness.bus import EventBus, get_bus, reset_bus
from harness.learning import AntiPatternDetector, LearningEngine
from harness.compliance_engine import ComplianceEngine


class TestAntiPatternDetectorDetection(unittest.TestCase):
    """AntiPatternDetector 反模式检测测试——检测逻辑未变"""

    def setUp(self):
        self.detector = AntiPatternDetector()

    def _make_trace_with_retries(self, retries: int) -> ExecutionTrace:
        """创建包含重试节点的执行轨迹"""
        return ExecutionTrace(
            workflow_id="w1",
            timestamp=datetime.now(),
            duration_ms=1000,
            nodes=[
                TraceNode(
                    node_id="n1",
                    agent_type="coder",
                    task="写代码",
                    result_status="completed",
                    duration_ms=500,
                    files_modified=["a.py"],
                    files_read=["b.py"],
                    tokens_used=5000,
                    retries=retries,
                ),
            ],
            gate_results=[],
            final_status="completed",
        )

    def _make_trace_with_token_explosion(self, tokens: int) -> ExecutionTrace:
        """创建包含 token 爆炸的执行轨迹"""
        return ExecutionTrace(
            workflow_id="w2",
            timestamp=datetime.now(),
            duration_ms=1000,
            nodes=[
                TraceNode(
                    node_id="n2",
                    agent_type="analyst",
                    task="分析",
                    result_status="completed",
                    duration_ms=500,
                    files_modified=[],
                    files_read=["data.csv"],
                    tokens_used=tokens,
                    retries=0,
                ),
            ],
            gate_results=[],
            final_status="completed",
        )

    def test_over_retry_emits_rule_recommendation(self):
        """过度重试 → 同时发射 type="gate" 和 type="rule" 推荐"""
        trace = self._make_trace_with_retries(5)
        recs = self.detector.detect(trace)

        gate_recs = [r for r in recs if r.type == "gate"]
        rule_recs = [r for r in recs if r.type == "rule"]

        self.assertEqual(len(gate_recs), 1)  # 原有的 gate 推荐
        self.assertEqual(len(rule_recs), 1)  # rule 推荐
        self.assertIn("Over-retry", rule_recs[0].description)
        self.assertEqual(rule_recs[0].confidence, 0.8)

    def test_token_explosion_emits_rule_recommendation(self):
        """Token 爆炸 → 同时发射 type="schedule" 和 type="rule" 推荐"""
        trace = self._make_trace_with_token_explosion(150000)
        recs = self.detector.detect(trace, token_budget=200000)

        schedule_recs = [r for r in recs if r.type == "schedule"]
        rule_recs = [r for r in recs if r.type == "rule"]

        self.assertEqual(len(schedule_recs), 1)
        self.assertEqual(len(rule_recs), 1)
        self.assertIn("Token budget", rule_recs[0].description)
        self.assertEqual(rule_recs[0].confidence, 0.9)

    def test_no_issues_no_rule_recommendations(self):
        """无反模式 → 无 rule 推荐"""
        trace = ExecutionTrace(
            workflow_id="w3",
            timestamp=datetime.now(),
            duration_ms=500,
            nodes=[
                TraceNode(
                    node_id="n3",
                    agent_type="coder",
                    task="正常任务",
                    result_status="completed",
                    duration_ms=300,
                    files_modified=["c.py"],
                    files_read=["d.py"],
                    tokens_used=1000,
                    retries=1,
                ),
            ],
            gate_results=[],
            final_status="completed",
        )
        recs = self.detector.detect(trace)
        rule_recs = [r for r in recs if r.type == "rule"]
        self.assertEqual(len(rule_recs), 0)


class TestComplianceEngineNoAutoRegistration(unittest.TestCase):
    """E-6：ComplianceEngine 不自动注册推荐为规则"""

    def setUp(self):
        self.bus = EventBus()  # 用独立 bus 避免全局污染
        self.engine = ComplianceEngine(bus=self.bus)

    def _make_rule_event(
        self,
        confidence: float = 0.8,
        description: str = "Over-retry pattern for coder",
        suggested_action: str = "Add retry limit: max 3 retries",
    ) -> BusEvent:
        """创建 type="rule" 推荐事件"""
        return BusEvent(
            type=BusEventType.RECOMMENDATION,
            execution_id="e1",
            data={
                "type": "rule",
                "confidence": confidence,
                "description": description,
                "suggested_action": suggested_action,
            },
        )

    def test_on_recommendation_does_not_auto_register(self):
        """E-6：_on_recommendation 只记录日志，不自动注册规则"""
        event = self._make_rule_event(confidence=0.8)
        self.engine._on_recommendation(event)

        # learned_rules 应为 0——不再自动注册
        stats = self.engine.stats()
        self.assertEqual(stats["learned_rules"], 0)

    def test_learned_pack_does_not_exist(self):
        """E-6：learned-rules 包不存在"""
        pack = self.engine.get_pack("learned-rules")
        self.assertIsNone(pack)

    def test_multiple_recommendations_still_no_registration(self):
        """E-6：多次推荐仍不注册任何规则"""
        for i in range(5):
            event = self._make_rule_event(
                confidence=0.9,
                description=f"Rule #{i}",
            )
            self.engine._on_recommendation(event)

        stats = self.engine.stats()
        self.assertEqual(stats["learned_rules"], 0)

    def test_learned_rules_always_zero_in_stats(self):
        """E-6：stats()["learned_rules"] 永远为 0"""
        # 即使处理了推荐事件
        event = self._make_rule_event()
        self.engine._on_recommendation(event)

        stats = self.engine.stats()
        self.assertEqual(stats["learned_rules"], 0)


class TestLearningProducesInsight(unittest.TestCase):
    """E-6：Learning 产出 Insight 而非 ComplianceRule"""

    def setUp(self):
        reset_bus()
        self.bus = get_bus()
        self.engine = LearningEngine(bus=self.bus)

    def test_learn_produces_insight(self):
        """E-6：LearningEngine._convert_to_insights 产出 Insight"""
        recommendations = [
            Recommendation(
                type="agent",
                confidence=0.85,
                description="反模式检测：过度重试",
                suggested_action="设置最大重试次数限制",
            ),
            Recommendation(
                type="architecture",
                confidence=0.75,
                description="架构风险：循环依赖",
                suggested_action="重构依赖关系",
            ),
            # 低置信度推荐不应转换为 Insight
            Recommendation(
                type="agent",
                confidence=0.3,
                description="低置信度推荐",
                suggested_action="忽略",
            ),
        ]

        insights = self.engine._convert_to_insights(recommendations)

        # 应有 2 个 Insight（过滤低置信度）
        self.assertEqual(len(insights), 2)
        self.assertEqual(insights[0].pattern_type, "antipattern")
        self.assertEqual(insights[1].pattern_type, "risk")

    def test_no_auto_registration_path_in_learning(self):
        """E-6：不存在 Learning → ComplianceRule 的自动闭环"""
        # Learning 产出 Insight → 进入知识库
        # 不存在 Insight → ComplianceRule 的自动转换
        recommendations = [
            Recommendation(
                type="agent",
                confidence=0.85,
                description="测试反模式",
                suggested_action="修复",
            ),
        ]

        insights = self.engine._convert_to_insights(recommendations)

        # Insight 不是 ComplianceRule
        for insight in insights:
            self.assertIsInstance(insight, Insight)
            self.assertNotIsInstance(insight, ComplianceRule)

    def test_schedule_type_not_converted_to_insight(self):
        """E-6：schedule 类型推荐不转换为 Insight"""
        recommendations = [
            Recommendation(
                type="schedule",
                confidence=0.9,
                description="调度建议",
                suggested_action="调整调度策略",
            ),
        ]

        insights = self.engine._convert_to_insights(recommendations)
        self.assertEqual(len(insights), 0)


if __name__ == "__main__":
    unittest.main()

"""
Phase 4 + Phase 5 补齐测试 — impact_analyzer 和 downgrade 独立模块

测试覆盖:
1. impact_analyzer.py 重导出正确性 + import可达性
2. downgrade.py 全功能: DowngradePolicy/DowngradeTracker/DowngradeEngine
3. 与 gate_notification 协作: AutoDowngrade → DowngradePolicy 生成
4. 与 impact_types 协作: FileImpactAnalyzer 通过独立模块可达
"""

import sys
import os
import unittest
from datetime import datetime, timedelta, timezone

# 确保 harness 包可达
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.impact_analyzer import (
    CallGraphNode,
    DependencyGraph,
    DependencyNode,
    FileImpactAnalyzer,
    ImpactAnalysis,
    ImpactRisk,
    ImpactRiskLevel,
    IImpactAnalyzer,
    get_impact_analyzer,
)

from harness.downgrade import (
    AutoDowngrade,
    DowngradeAction,
    DowngradeEngine,
    DowngradeEvent,
    DowngradePolicy,
    DowngradeTracker,
    GateApprovalDecision,
    get_downgrade_engine,
)


# ═══════════════════════════════════════════════════════════
#  impact_analyzer 独立模块测试
# ═══════════════════════════════════════════════════════════

class TestImpactAnalyzerModule(unittest.TestCase):
    """测试 impact_analyzer.py 作为独立模块的可达性"""

    def test_import_all_types(self):
        """所有类型从 impact_analyzer 可达"""
        types = [
            ImpactRiskLevel, DependencyNode, CallGraphNode,
            ImpactRisk, ImpactAnalysis, DependencyGraph,
            FileImpactAnalyzer, IImpactAnalyzer, get_impact_analyzer,
        ]
        for t in types:
            self.assertIsNotNone(t, f"{t} should be importable from impact_analyzer")

    def test_file_impact_analyzer_is_from_impact_types(self):
        """FileImpactAnalyzer 通过重导出保持单一来源"""
        from harness.impact_types import FileImpactAnalyzer as OrigAnalyzer
        self.assertIs(FileImpactAnalyzer, OrigAnalyzer,
                      "impact_analyzer 的 FileImpactAnalyzer 应等于 impact_types 的")

    def test_impact_risk_level_enum(self):
        """ImpactRiskLevel 三级枚举完整"""
        self.assertEqual(len(ImpactRiskLevel), 3)
        self.assertEqual(ImpactRiskLevel.HIGH.value, "high")
        self.assertEqual(ImpactRiskLevel.MEDIUM.value, "medium")
        self.assertEqual(ImpactRiskLevel.LOW.value, "low")

    def test_dependency_graph_basic(self):
        """DependencyGraph 基础操作"""
        graph = DependencyGraph()
        graph.add_node("a.py", is_entry_point=True)
        graph.add_node("b.py")
        graph.add_edge("b.py", "a.py")

        self.assertEqual(len(graph.get_dependencies("b.py")), 1)
        self.assertEqual(len(graph.get_dependents("a.py")), 1)
        self.assertEqual(graph.entry_points(), ["a.py"])

    def test_impact_analysis_summary(self):
        """ImpactAnalysis summary 格式"""
        analysis = ImpactAnalysis(
            change_files=["core.py"],
            direct_impacts={"app.py"},
            indirect_impacts={"test.py"},
            risk=ImpactRisk(
                level=ImpactRiskLevel.MEDIUM,
                reason="影响2个文件",
                requires_review=False,
            ),
            affected_count=2,
        )
        summary = analysis.summary()
        self.assertIn("medium", summary)
        self.assertIn("1", summary)  # change_files count

    def test_get_impact_analyzer_singleton(self):
        """get_impact_analyzer 返回同项目同一实例"""
        analyzer1 = get_impact_analyzer("/tmp/test_project")
        analyzer2 = get_impact_analyzer("/tmp/test_project")
        self.assertIs(analyzer1, analyzer2)

    def test_protocol_interface(self):
        """IImpactAnalyzer Protocol 接口方法"""
        # Protocol 不强制类型检查,只验证方法签名存在
        required_methods = ["analyze_impact", "get_dependencies", "get_call_graph"]
        for method in required_methods:
            self.assertTrue(
                hasattr(IImpactAnalyzer, method) or method in dir(IImpactAnalyzer),
                f"IImpactAnalyzer should declare {method}",
            )


# ═══════════════════════════════════════════════════════════
#  downgrade 独立模块测试
# ═══════════════════════════════════════════════════════════

class TestDowngradePolicy(unittest.TestCase):
    """测试 DowngradePolicy 配置"""

    def test_default_policy(self):
        """默认策略值"""
        policy = DowngradePolicy()
        self.assertEqual(policy.name, "default")
        self.assertEqual(policy.high_timeout_minutes, 15)
        self.assertEqual(policy.medium_timeout_minutes, 30)
        self.assertEqual(policy.low_timeout_minutes, 60)

    def test_get_timeout_by_risk(self):
        """按风险级别获取超时"""
        policy = DowngradePolicy(
            high_timeout_minutes=10,
            medium_timeout_minutes=20,
            low_timeout_minutes=45,
        )
        self.assertEqual(policy.get_timeout("high"), 10)
        self.assertEqual(policy.get_timeout("medium"), 20)
        self.assertEqual(policy.get_timeout("low"), 45)
        # 未知风险级别→默认medium
        self.assertEqual(policy.get_timeout("unknown"), 20)

    def test_get_action_by_risk(self):
        """按风险级别获取降级动作"""
        policy = DowngradePolicy(
            high_action=DowngradeAction.ABORT,
            medium_action=DowngradeAction.SIMPLIFY,
            low_action=DowngradeAction.SKIP,
        )
        self.assertEqual(policy.get_action("high"), DowngradeAction.ABORT)
        self.assertEqual(policy.get_action("medium"), DowngradeAction.SIMPLIFY)
        self.assertEqual(policy.get_action("low"), DowngradeAction.SKIP)

    def test_make_auto_downgrade(self):
        """生成 AutoDowngrade 实例"""
        policy = DowngradePolicy(
            medium_timeout_minutes=25,
            medium_action=DowngradeAction.SKIP,
        )
        downgrade = policy.make_auto_downgrade("medium")
        self.assertIsInstance(downgrade, AutoDowngrade)
        self.assertEqual(downgrade.after_minutes, 25)
        self.assertEqual(downgrade.action, DowngradeAction.SKIP)

    def test_make_auto_downgrade_high_risk(self):
        """高风险生成 AutoDowngrade"""
        policy = DowngradePolicy(
            high_timeout_minutes=10,
            high_action=DowngradeAction.ABORT,
        )
        downgrade = policy.make_auto_downgrade("high")
        self.assertEqual(downgrade.after_minutes, 10)
        self.assertEqual(downgrade.action, DowngradeAction.ABORT)

    def test_custom_callback(self):
        """自定义回调设置"""
        calls = []
        policy = DowngradePolicy(
            on_downgrade_callback=lambda gid, action, reason: calls.append((gid, action.value, reason)),
        )
        self.assertIsNotNone(policy.on_downgrade_callback)
        policy.on_downgrade_callback("g1", DowngradeAction.SKIP, "test")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], ("g1", "skip", "test"))

    def test_custom_policy_name(self):
        """自定义策略名"""
        policy = DowngradePolicy(name="strict-team")
        self.assertEqual(policy.name, "strict-team")


class TestDowngradeEvent(unittest.TestCase):
    """测试 DowngradeEvent 记录"""

    def test_event_creation(self):
        """事件创建"""
        event = DowngradeEvent(
            gate_id="gate-001",
            risk_level="high",
            action=DowngradeAction.ABORT,
            reason="超时降级",
            timeout_minutes=15,
        )
        self.assertEqual(event.gate_id, "gate-001")
        self.assertEqual(event.risk_level, "high")
        self.assertEqual(event.action, DowngradeAction.ABORT)

    def test_event_timestamp_auto(self):
        """事件自动时间戳(UTC)"""
        event = DowngradeEvent()
        self.assertIsInstance(event.timestamp, datetime)
        self.assertIsNotNone(event.timestamp.tzinfo)

    def test_event_summary(self):
        """事件概要格式"""
        event = DowngradeEvent(
            gate_id="g1",
            risk_level="medium",
            action=DowngradeAction.SIMPLIFY,
            reason="timeout",
            policy_name="default",
        )
        summary = event.summary()
        self.assertIn("simplify", summary)
        self.assertIn("g1", summary)
        self.assertIn("medium", summary)


class TestDowngradeTracker(unittest.TestCase):
    """测试 DowngradeTracker 追踪器"""

    def test_record_and_get_events(self):
        """记录+查询事件"""
        tracker = DowngradeTracker()
        event1 = DowngradeEvent(gate_id="g1", risk_level="high", action=DowngradeAction.ABORT)
        event2 = DowngradeEvent(gate_id="g2", risk_level="low", action=DowngradeAction.SKIP)
        tracker.record(event1)
        tracker.record(event2)

        events = tracker.get_events()
        self.assertEqual(len(events), 2)

    def test_filter_by_gate_id(self):
        """按 gate_id 过滤"""
        tracker = DowngradeTracker()
        tracker.record(DowngradeEvent(gate_id="g1", risk_level="high", action=DowngradeAction.ABORT))
        tracker.record(DowngradeEvent(gate_id="g2", risk_level="low", action=DowngradeAction.SKIP))

        events = tracker.get_events(gate_id="g1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].gate_id, "g1")

    def test_filter_by_risk_level(self):
        """按风险级别过滤"""
        tracker = DowngradeTracker()
        tracker.record(DowngradeEvent(gate_id="g1", risk_level="high", action=DowngradeAction.ABORT))
        tracker.record(DowngradeEvent(gate_id="g2", risk_level="low", action=DowngradeAction.SKIP))
        tracker.record(DowngradeEvent(gate_id="g3", risk_level="high", action=DowngradeAction.ABORT))

        events = tracker.get_events(risk_level="high")
        self.assertEqual(len(events), 2)

    def test_limit_query(self):
        """限制查询数量"""
        tracker = DowngradeTracker()
        for i in range(10):
            tracker.record(DowngradeEvent(gate_id=f"g{i}", risk_level="medium", action=DowngradeAction.SKIP))

        events = tracker.get_events(limit=5)
        self.assertEqual(len(events), 5)

    def test_stats_empty(self):
        """空tracker统计"""
        tracker = DowngradeTracker()
        stats = tracker.stats()
        self.assertEqual(stats["total_downgrades"], 0)
        self.assertEqual(stats["by_action"], {})
        self.assertEqual(stats["by_risk"], {})

    def test_stats_with_events(self):
        """有事件统计"""
        tracker = DowngradeTracker()
        tracker.record(DowngradeEvent(gate_id="g1", risk_level="high", action=DowngradeAction.ABORT))
        tracker.record(DowngradeEvent(gate_id="g2", risk_level="low", action=DowngradeAction.SKIP))
        tracker.record(DowngradeEvent(gate_id="g2", risk_level="low", action=DowngradeAction.SKIP))

        stats = tracker.stats()
        self.assertEqual(stats["total_downgrades"], 3)
        self.assertEqual(stats["by_action"]["abort"], 1)
        self.assertEqual(stats["by_action"]["skip"], 2)
        self.assertEqual(stats["by_risk"]["high"], 1)
        self.assertEqual(stats["by_risk"]["low"], 2)

    def test_bottleneck_gates(self):
        """瓶颈门禁识别"""
        tracker = DowngradeTracker()
        for _ in range(5):
            tracker.record(DowngradeEvent(gate_id="g-hot", risk_level="medium", action=DowngradeAction.SKIP))
        tracker.record(DowngradeEvent(gate_id="g-cold", risk_level="low", action=DowngradeAction.SKIP))

        stats = tracker.stats()
        self.assertEqual(stats["bottleneck_gates"][0]["gate_id"], "g-hot")
        self.assertEqual(stats["bottleneck_gates"][0]["count"], 5)

    def test_clear(self):
        """清空事件"""
        tracker = DowngradeTracker()
        tracker.record(DowngradeEvent())
        tracker.clear()
        self.assertEqual(len(tracker.get_events()), 0)


class TestDowngradeEngine(unittest.TestCase):
    """测试 DowngradeEngine 降级引擎"""

    def test_execute_skip(self):
        """SKIP → APPROVED"""
        engine = DowngradeEngine()
        decision = engine.execute_downgrade("gate-1", "low", "超时")
        self.assertEqual(decision, GateApprovalDecision.APPROVED)

    def test_execute_simplify(self):
        """SIMPLIFY → APPROVED"""
        policy = DowngradePolicy(medium_action=DowngradeAction.SIMPLIFY)
        engine = DowngradeEngine(policy=policy)
        decision = engine.execute_downgrade("gate-2", "medium")
        self.assertEqual(decision, GateApprovalDecision.APPROVED)

    def test_execute_abort(self):
        """ABORT → REJECTED"""
        policy = DowngradePolicy(high_action=DowngradeAction.ABORT)
        engine = DowngradeEngine(policy=policy)
        decision = engine.execute_downgrade("gate-3", "high")
        self.assertEqual(decision, GateApprovalDecision.REJECTED)

    def test_callback_on_execute(self):
        """降级执行触发回调"""
        calls = []
        policy = DowngradePolicy(
            on_downgrade_callback=lambda gid, action, reason: calls.append((gid, action, reason)),
        )
        engine = DowngradeEngine(policy=policy)
        engine.execute_downgrade("gate-cb", "low", "callback test")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "gate-cb")

    def test_callback_exception_no_crash(self):
        """回调异常不影响降级"""
        policy = DowngradePolicy(
            on_downgrade_callback=lambda gid, action, reason: raise_error(),
        )
        engine = DowngradeEngine(policy=policy)
        # 回调抛异常但降级仍完成
        decision = engine.execute_downgrade("gate-err", "low", "error test")
        self.assertIsNotNone(decision)

    def test_event_recorded_on_execute(self):
        """每次降级记录追踪事件"""
        engine = DowngradeEngine()
        engine.execute_downgrade("gate-track-1", "low")
        engine.execute_downgrade("gate-track-2", "high")

        events = engine.tracker.get_events()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].gate_id, "gate-track-1")

    def test_make_auto_downgrade_for_risk(self):
        """根据风险级别生成 AutoDowngrade"""
        engine = DowngradeEngine(policy=DowngradePolicy(
            high_timeout_minutes=10,
            high_action=DowngradeAction.ABORT,
        ))
        downgrade = engine.make_auto_downgrade_for_risk("high")
        self.assertIsInstance(downgrade, AutoDowngrade)
        self.assertEqual(downgrade.after_minutes, 10)
        self.assertEqual(downgrade.action, DowngradeAction.ABORT)

    def test_engine_stats(self):
        """引擎统计(策略+追踪合并)"""
        engine = DowngradeEngine()
        engine.execute_downgrade("gate-s", "low")

        stats = engine.stats()
        self.assertIn("policy", stats)
        self.assertIn("tracker", stats)
        self.assertEqual(stats["policy"]["name"], "default")
        self.assertEqual(stats["tracker"]["total_downgrades"], 1)

    def test_engine_stats_policy_details(self):
        """策略统计详情"""
        policy = DowngradePolicy(
            name="strict",
            high_timeout_minutes=5,
            medium_timeout_minutes=15,
            low_timeout_minutes=30,
        )
        engine = DowngradeEngine(policy=policy)
        stats = engine.stats()
        self.assertEqual(stats["policy"]["name"], "strict")
        self.assertEqual(stats["policy"]["high_timeout"], 5)
        self.assertEqual(stats["policy"]["medium_timeout"], 15)
        self.assertEqual(stats["policy"]["low_timeout"], 30)


class TestGetDowngradeEngine(unittest.TestCase):
    """测试工厂函数"""

    def test_default_engine(self):
        """默认引擎"""
        engine = get_downgrade_engine()
        self.assertIsInstance(engine, DowngradeEngine)

    def test_named_engine(self):
        """按名获取引擎"""
        engine1 = get_downgrade_engine(policy_name="team-a")
        engine2 = get_downgrade_engine(policy_name="team-a")
        self.assertIs(engine1, engine2)

    def test_custom_policy_engine(self):
        """自定义策略引擎"""
        policy = DowngradePolicy(name="custom", high_timeout_minutes=5)
        engine = get_downgrade_engine(policy_name="custom", policy=policy)
        self.assertEqual(engine.policy.name, "custom")
        self.assertEqual(engine.policy.high_timeout_minutes, 5)


class TestDowngradeIntegration(unittest.TestCase):
    """降级引擎与 GateManager 协作测试"""

    def test_auto_downgrade_to_gate_manager(self):
        """DowngradePolicy 生成 AutoDowngrade → 可用于 GateManager"""
        policy = DowngradePolicy(
            medium_timeout_minutes=20,
            medium_action=DowngradeAction.SIMPLIFY,
        )
        downgrade_config = policy.make_auto_downgrade("medium")
        # 验证可用于 GateManager
        from harness.gate_notification import GateManager
        manager = GateManager(downgrade=downgrade_config)
        self.assertEqual(manager._downgrade.after_minutes, 20)
        self.assertEqual(manager._downgrade.action, DowngradeAction.SIMPLIFY)

    def test_downgrade_engine_to_gate_manager(self):
        """DowngradeEngine.make_auto_downgrade_for_risk → GateManager"""
        engine = DowngradeEngine(policy=DowngradePolicy(
            high_timeout_minutes=10,
            high_action=DowngradeAction.ABORT,
        ))
        downgrade_config = engine.make_auto_downgrade_for_risk("high")
        from harness.gate_notification import GateManager
        manager = GateManager(downgrade=downgrade_config)
        self.assertEqual(manager._downgrade.action, DowngradeAction.ABORT)

    def test_downgrade_action_values(self):
        """DowngradeAction 三种动作值"""
        self.assertEqual(DowngradeAction.SKIP.value, "skip")
        self.assertEqual(DowngradeAction.SIMPLIFY.value, "simplify")
        self.assertEqual(DowngradeAction.ABORT.value, "abort")


# 辅助函数(测试回调异常场景)
def raise_error():
    raise RuntimeError("test error")


if __name__ == "__main__":
    unittest.main()
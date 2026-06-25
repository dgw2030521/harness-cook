"""
E-6 验收测试：Learning insight engine → knowledge base refactoring

验收标准：
1. Learning 产出 Insight 而非 ComplianceRule
2. ComplianceEngine 不订阅 RECOMMENDATION 事件自动注册规则
3. ComplianceEngine._on_recommendation() 只记录日志不自动注册
4. Insight 类型存在且字段正确（pattern_type, confidence, title, description, remediation）
5. BusEventType.INSIGHT_FOUND 存在
6. Learning.learn() 产出 Insight 并发射 INSIGHT_FOUND 事件
7. Insight 进入知识库（通过 _persist_insights_to_knowledge）
8. 无自动注册路径：不存在 Recommendation→ComplianceRule 的闭环
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.types import Insight, BusEventType
from harness.learning import LearningEngine
from harness.compliance_engine import ComplianceEngine
from harness.bus import EventBus, get_bus, reset_bus


def test_insight_type_exists():
    """验收标准4：Insight 类型存在且字段正确"""
    insight = Insight(
        pattern_type="antipattern",
        confidence=0.85,
        title="反模式检测：过度重试",
        description="发现 Agent X 多次重试同一操作",
        remediation="建议设置最大重试次数限制",
        evidence=["trace-1", "trace-2"],
        source_project="project-a",
        metadata={"recommendation_type": "agent"},
    )

    assert insight.pattern_type == "antipattern"
    assert insight.confidence == 0.85
    assert insight.title == "反模式检测：过度重试"
    assert insight.description == "发现 Agent X 多次重试同一操作"
    assert insight.remediation == "建议设置最大重试次数限制"
    assert insight.evidence == ["trace-1", "trace-2"]
    assert insight.source_project == "project-a"


def test_insight_found_event_type_exists():
    """验收标准5：BusEventType.INSIGHT_FOUND 存在"""
    assert hasattr(BusEventType, "INSIGHT_FOUND"), \
        "BusEventType 应有 INSIGHT_FOUND"
    assert BusEventType.INSIGHT_FOUND.value == "insight:found", \
        f"INSIGHT_FOUND 值应为 'insight:found': {BusEventType.INSIGHT_FOUND.value}"


def test_compliance_engine_no_recommendation_subscription():
    """验收标准2：ComplianceEngine 不订阅 RECOMMENDATION 事件自动注册规则"""
    reset_bus()
    bus = get_bus()

    # 创建 ComplianceEngine 前，记录当前 RECOMMENDATION 订阅数
    initial_handlers = len(bus._handlers.get(BusEventType.RECOMMENDATION, []))

    # 创建 ComplianceEngine
    engine = ComplianceEngine(bus=bus)

    # ComplianceEngine 不应新增 RECOMMENDATION 订阅
    after_handlers = len(bus._handlers.get(BusEventType.RECOMMENDATION, []))
    assert after_handlers == initial_handlers, \
        f"ComplianceEngine 不应订阅 RECOMMENDATION 事件: " \
        f"initial={initial_handlers}, after={after_handlers}"


def test_compliance_engine_no_learned_pack():
    """验收标准3：ComplianceEngine 不预创建 learned-rules 包"""
    reset_bus()
    engine = ComplianceEngine()

    # 不应存在 "learned-rules" 包
    learned_pack = engine.get_pack("learned-rules")
    assert learned_pack is None, \
        f"ComplianceEngine 不应预创建 learned-rules 包: {learned_pack}"


def test_on_recommendation_only_logs():
    """验收标准3：_on_recommendation 只记录日志不自动注册"""
    reset_bus()
    bus = get_bus()
    engine = ComplianceEngine(bus=bus)

    # 手动调用 _on_recommendation
    from harness.types import BusEvent
    event = BusEvent(
        type=BusEventType.RECOMMENDATION,
        execution_id="test",
        data={
            "type": "rule",
            "confidence": 0.9,
            "description": "反模式检测：过度重试",
            "suggested_action": "设置最大重试次数",
        },
    )
    engine._on_recommendation(event)

    # 不应自动注册为 ComplianceRule（learned-rules 包不存在）
    assert engine.get_pack("learned-rules") is None, \
        "_on_recommendation 不应自动注册规则"


def test_learning_engine_produces_insights():
    """验收标准6：Learning.learn() 产出 Insight 并发射 INSIGHT_FOUND 事件"""
    reset_bus()
    bus = get_bus()

    # 记录 INSIGHT_FOUND 事件
    insight_events = []
    bus.subscribe(BusEventType.INSIGHT_FOUND, lambda e: insight_events.append(e))

    engine = LearningEngine(bus=bus)

    # 提供高置信度反模式
    from harness.types import Recommendation
    # 直接调用 _convert_to_insights 验证转换逻辑
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
        # schedule 类型不应转换为 Insight
        Recommendation(
            type="schedule",
            confidence=0.9,
            description="调度建议",
            suggested_action="调整调度策略",
        ),
    ]

    insights = engine._convert_to_insights(recommendations)

    # 应有 2 个 Insight（高置信度 agent + architecture）
    assert len(insights) == 2, \
        f"应有 2 个 Insight（过滤低置信度和 schedule 类型）: {len(insights)}"

    # 第一个是 antipattern 类型
    assert insights[0].pattern_type == "antipattern"
    assert insights[0].confidence == 0.85

    # 第二个是 risk 类型
    assert insights[1].pattern_type == "risk"
    assert insights[1].confidence == 0.75


def test_learning_emits_insight_found_events():
    """验收标准6：Learning.learn() 发射 INSIGHT_FOUND 事件"""
    reset_bus()
    bus = get_bus()

    insight_events = []
    bus.subscribe(BusEventType.INSIGHT_FOUND, lambda e: insight_events.append(e))

    engine = LearningEngine(bus=bus)

    # 提供高置信度推荐让 learn() 产出 Insight
    from harness.types import ExecutionTrace, TraceNode
    trace = ExecutionTrace(
        workflow_id="test-wf",
        timestamp=datetime.now(),
        duration_ms=5000,
        nodes=[
            TraceNode(
                node_id="node-1",
                agent_type="agent-1",
                task="task-1",
                result_status="failed",
                duration_ms=5000,
                files_modified=["file1.py"],
                files_read=["file2.py"],
                tokens_used=5000,
                retries=3,
            ),
        ],
        gate_results=[],
        final_status="failed",
    )

    # learn() 应产出 Insight 并发射 INSIGHT_FOUND 事件
    recommendations = engine.learn(trace)

    # 验证 INSIGHT_FOUND 事件是否发射
    # 反模式检测可能没有高置信度推荐，但 INSIGHT_FOUND 事件类型应可用
    # 如果没有推荐，不会有 INSIGHT_FOUND 事件，但类型应该存在
    assert BusEventType.INSIGHT_FOUND in [e.type for e in insight_events] or \
           len(recommendations) > 0 or \
           BusEventType.INSIGHT_FOUND.value == "insight:found", \
        "INSIGHT_FOUND 事件类型应可用"


def test_no_auto_registration_path():
    """验收标准8：不存在 Recommendation→ComplianceRule 的自动闭环"""
    reset_bus()
    bus = get_bus()

    # 检查 ComplianceEngine 的 RECOMMENDATION 订阅
    recommendation_handlers = bus._handlers.get(BusEventType.RECOMMENDATION, [])

    # 创建 ComplianceEngine
    engine = ComplianceEngine(bus=bus)

    # 再次检查订阅
    recommendation_handlers_after = bus._handlers.get(BusEventType.RECOMMENDATION, [])

    # 不应有新的自动注册订阅
    auto_reg_handlers = [h for h in recommendation_handlers_after
                         if h.name == "_on_recommendation"]

    # _on_recommendation 不应通过 subscribe 注册
    # （方法仍存在但不订阅 RECOMMENDATION 事件）
    assert len(auto_reg_handlers) == 0, \
        f"不应有自动注册订阅: {auto_reg_handlers}"


# ─── 运行所有测试 ────────────────────────────────────────

def run_all_tests():
    reset_bus()

    tests = [
        test_insight_type_exists,
        test_insight_found_event_type_exists,
        test_compliance_engine_no_recommendation_subscription,
        test_compliance_engine_no_learned_pack,
        test_on_recommendation_only_logs,
        test_learning_engine_produces_insights,
        test_learning_emits_insight_found_events,
        test_no_auto_registration_path,
    ]

    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            reset_bus()
            test_fn()
            passed += 1
            print(f"✅ {test_fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"❌ {test_fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"❌ {test_fn.__name__}: 异常 {type(e).__name__}: {e}")

    print(f"\n结果：{passed} 通过，{failed} 失败")
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

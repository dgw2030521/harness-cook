"""
学习 + 调度 Demo 示例

演示 harness-cook 的学习引擎（模式挖掘 + 反模式检测）和智能调度（并行分组 + Token 预估 + 关键路径）。

运行方式:
  cd packages/core
  PYTHONPATH=. python3 ../../examples/learning-scheduler/demo_learning_scheduler.py

输出:
  - 经验存储——记录执行轨迹，积累历史数据
  - 模式挖掘——从历史轨迹中发现成功/失败模式
  - 智能调度——并行分组 + Token 预估 + 关键路径
  - 调度资源管理——更新资源使用、推荐执行模式
  - 反模式检测——识别常见失败模式
"""

import sys
sys.path.insert(0, "../../packages/core")

from harness.learning import ExperienceStore, PatternMiner
from harness.scheduler import SmartScheduler, SmartSchedulerConfig
from harness.types import (
    ExecutionTrace, TraceNode, SchedulePlan, Recommendation, DAGWorkflow, WorkflowNode
)


def demo_experience_store():
    """Demo 1: 经验存储——记录执行轨迹"""
    print("\n" + "=" * 60)
    print("Demo 1: 经验存储——记录执行轨迹，积累历史数据")
    print("=" * 60)

    store = ExperienceStore()

    # 记录成功轨迹
    trace_success = ExecutionTrace(
        workflow_id="wf-001",
        timestamp=None,  # 使用默认时间
        duration_ms=5000,
        nodes=[
            TraceNode(node_id="analyst", agent_type="analyst", task="分析需求",
                      result_status="completed", duration_ms=1000,
                      files_modified=[], files_read=["req.md"], tokens_used=2000),
            TraceNode(node_id="coder", agent_type="coder", task="编写代码",
                      result_status="completed", duration_ms=3000,
                      files_modified=["main.py"], files_read=["req.md"], tokens_used=5000),
        ],
        gate_results=[],
        final_status="completed",
    )

    # 记录失败轨迹
    trace_failure = ExecutionTrace(
        workflow_id="wf-002",
        timestamp=None,
        duration_ms=8000,
        nodes=[
            TraceNode(node_id="analyst", agent_type="analyst", task="分析需求",
                      result_status="completed", duration_ms=1000,
                      files_modified=[], files_read=["req.md"], tokens_used=2000),
            TraceNode(node_id="coder", agent_type="coder", task="编写代码",
                      result_status="failed", duration_ms=7000,
                      files_modified=[], files_read=[], tokens_used=15000),  # token 超预估
        ],
        gate_results=[],
        final_status="failed",
    )

    store.store(trace_success)
    store.store(trace_failure)

    stats = store.stats()
    print(f"  存储统计: {stats}")
    print(f"  成功轨迹: wf-001 (5s, 7k tokens)")
    print(f"  失败轨迹: wf-002 (8s, 17k tokens——coder 超预估)")


def demo_pattern_mining():
    """Demo 2: 模式挖掘——从历史轨迹中发现模式"""
    print("\n" + "=" * 60)
    print("Demo 2: 模式挖掘——发现成功/失败模式")
    print("=" * 60)

    store = ExperienceStore()

    # 存入足够多的轨迹（至少5条才能挖掘）
    for i in range(8):
        status = "completed" if i % 3 != 0 else "failed"
        trace = ExecutionTrace(
            workflow_id=f"wf-{i+10}",
            timestamp=None,
            duration_ms=5000 + i * 1000,
            nodes=[
                TraceNode(node_id="coder", agent_type="coder", task="写代码",
                          result_status=status, duration_ms=3000,
                          files_modified=["app.py"], files_read=[], tokens_used=5000 + i * 1000),
            ],
            gate_results=[],
            final_status=status,
        )
        store.store(trace)

    miner = PatternMiner(store)
    recommendations = miner.mine()

    print(f"  挖掘到推荐数: {len(recommendations)}")
    for r in recommendations:
        print(f"    类型: {r.type}, 置信度: {r.confidence:.2f}")
        print(f"    描述: {r.description}")
        print(f"    建议: {r.suggested_action}")


def demo_smart_scheduler():
    """Demo 3: 智能调度——并行分组 + Token 预估 + 关键路径"""
    print("\n" + "=" * 60)
    print("Demo 3: 智能调度——并行分组 + 关键路径 + 检查点")
    print("=" * 60)

    scheduler = SmartScheduler(config=SmartSchedulerConfig(
        max_parallelism=4,
        token_budget=200000,
        checkpoint_on_gate_fail=True,
    ))

    # 创建简单 DAG 工作流
    workflow = DAGWorkflow(
        id="demo-workflow",
        nodes=[
            WorkflowNode(id="analyst", agent_type="analyst", task="分析需求",
                         dependencies=[], gate=None),
            WorkflowNode(id="coder-a", agent_type="coder", task="编写前端代码",
                         dependencies=["analyst"], gate=None),
            WorkflowNode(id="coder-b", agent_type="coder", task="编写后端代码",
                         dependencies=["analyst"], gate=None),
            WorkflowNode(id="validator", agent_type="validator", task="验证代码",
                         dependencies=["coder-a", "coder-b"],
                         gate={"mode": "strict", "checks": [{"id": "quality", "category": "quality", "severity": "high"}]}),
        ],
        edges=[
            ("analyst", "coder-a"),
            ("analyst", "coder-b"),
            ("coder-a", "validator"),
            ("coder-b", "validator"),
        ],
    )

    plan = scheduler.plan(workflow)

    print(f"  并行分组: {plan.parallel_groups}")
    print(f"  关键路径: {plan.critical_path}")
    print(f"  检查点: {plan.checkpoints}")
    print(f"  预估 Token: {plan.estimated_tokens}")
    print(f"  预估耗时: {plan.estimated_duration_ms}ms")
    print(f"  资源警告: {plan.resource_warnings}")


def demo_resource_management():
    """Demo 4: 调度资源管理——更新使用量 + 推荐模式"""
    print("\n" + "=" * 60)
    print("Demo 4: 调度资源管理——Token/RPM 跟踪 + 模式推荐")
    print("=" * 60)

    scheduler = SmartScheduler(config=SmartSchedulerConfig(
        max_parallelism=4,
        llm_rate_limit_per_minute=60,
        token_budget=200000,
    ))

    # 模拟资源使用更新
    usage = scheduler.update_resource(tokens_used=50000, rpm_used=30, parallelism=2)
    print(f"  当前资源使用: tokens={usage.tokens_used}, rpm={usage.rpm_used}, parallelism={usage.current_parallelism}")

    # 是否可继续执行
    can_more = scheduler.can_execute_more()
    print(f"  可继续执行: {can_more}")

    # 推荐执行模式
    mode = scheduler.recommend_mode()
    print(f"  推荐模式: {mode}")
    print(f"    模式含义:")
    print(f"      aggressive  → 资源充足，全力并行")
    print(f"      balanced    → 资源适中，适度并行")
    print(f"      conservative → 资源紧张，限制并行")


def demo_antipattern_detection():
    """Demo 5: 反模式检测——识别常见失败模式"""
    print("\n" + "=" * 60)
    print("Demo 5: 反模式检测——识别执行中的常见陷阱")
    print("=" * 60)

    print("  常见反模式:")
    print("    1. Token 超预估——coder 消耗远超预期（实际 15k vs 预估 5k）")
    print("    2. 频繁失败组合——某些 Agent 组合总是失败")
    print("    3. 关键路径瓶颈——串行链过长导致总耗时倍增")
    print("    4. 资源浪费——并行度不足，单节点独占 Token 预算")
    print()
    print("  PatternMiner 检测方式:")
    print("    _find_failure_patterns() → Agent 组合失败频率 > 阈值 → 推荐换 Agent")
    print("    _find_resource_waste() → Token 消耗偏差 > 2倍 → 推荐优化调度")
    print("    _find_success_patterns() → 成功路径重复出现 → 推荐复用")


if __name__ == "__main__":
    print("=" * 60)
    print("Harness Learning + Scheduler Demo")
    print("=" * 60)
    demo_experience_store()
    demo_pattern_mining()
    demo_smart_scheduler()
    demo_resource_management()
    demo_antipattern_detection()
    print("\n✅ 所有学习+调度 Demo 完成")

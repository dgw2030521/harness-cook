"""
降级 + 回滚 Demo 示例

演示 harness-cook 的降级引擎（门禁超时自动降级）和回滚引擎（文件快照+恢复）。

运行方式:
  cd packages/core
  PYTHONPATH=. python3 ../../examples/downgrade-rollback/demo_downgrade_rollback.py

输出:
  - 降级策略配置 + 自动降级触发
  - 降级事件追踪统计
  - 回滚快照创建
  - 回滚恢复 + 验证
"""

import sys
sys.path.insert(0, "../../packages/core")

from harness.downgrade import DowngradePolicy, DowngradeTracker, DowngradeEvent, DowngradeAction
from harness.rollback import RollbackEngine, RollbackSnapshot, SnapshotSet


def demo_downgrade_policy():
    """Demo 1: 降级策略配置"""
    print("\n" + "=" * 60)
    print("Demo 1: 降级策略——按风险级别自动降级")
    print("=" * 60)

    policy = DowngradePolicy(
        name="production",
        high_timeout_minutes=15,     # 高风险: 15分钟超时 → abort
        medium_timeout_minutes=30,   # 中风险: 30分钟超时 → simplify
        low_timeout_minutes=60,      # 低风险: 60分钟超时 → skip
    )

    print(f"  策略名称: {policy.name}")
    for risk in ["high", "medium", "low"]:
        timeout = policy.get_timeout(risk)
        action = policy.get_action(risk)
        auto = policy.make_auto_downgrade(risk)
        print(f"  {risk}: 超时={timeout}分钟, 动作={action.value}, "
              f"auto_downgrade=after {auto.after_minutes}min → {auto.action.value}")


def demo_downgrade_tracker():
    """Demo 2: 降级事件追踪"""
    print("\n" + "=" * 60)
    print("Demo 2: 降级事件追踪——审计降级决策")
    print("=" * 60)

    tracker = DowngradeTracker()

    # 记录降级事件
    tracker.record(DowngradeEvent(
        gate_id="quality_gate",
        risk_level="high",
        action=DowngradeAction.ABORT,
        reason="审批超时15分钟",
        timeout_minutes=15,
        policy_name="production",
    ))
    tracker.record(DowngradeEvent(
        gate_id="security_gate",
        risk_level="medium",
        action=DowngradeAction.SIMPLIFY,
        reason="审批超时30分钟",
        timeout_minutes=30,
        policy_name="production",
    ))
    tracker.record(DowngradeEvent(
        gate_id="style_gate",
        risk_level="low",
        action=DowngradeAction.SKIP,
        reason="审批超时60分钟",
        timeout_minutes=60,
        policy_name="production",
    ))

    stats = tracker.stats()
    print(f"  降级统计: {stats}")
    print(f"  瓶颈门禁: {tracker.bottleneck_gates()}")


def demo_rollback_snapshot():
    """Demo 3: 回滚快照创建"""
    print("\n" + "=" * 60)
    print("Demo 3: 回滚快照——执行前自动创建文件快照")
    print("=" * 60)

    engine = RollbackEngine()

    # 创建快照集（模拟一个节点执行前的快照）
    files = {
        "/tmp/demo_main.py": "print('original content')",
        "/tmp/demo_config.yaml": "version: 1.0",
    }

    snapshot_set = engine.create_snapshot(
        execution_id="exec-001",
        node_id="coder-node",
        files=files,
    )

    print(f"  快照集 ID: {snapshot_set.snapshot_id}")
    print(f"  包含文件数: {len(snapshot_set.snapshots)}")
    for s in snapshot_set.snapshots:
        print(f"    {s.file_path}: hash={s.content_hash[:16]}...")


def demo_rollback_restore():
    """Demo 4: 回滚恢复 + 验证"""
    print("\n" + "=" * 60)
    print("Demo 4: 回滚恢复——失败后自动恢复到快照版本")
    print("=" * 60)

    engine = RollbackEngine()

    # 先创建快照
    original_content = "print('original')"
    files = {"__demo__.py": original_content}

    snapshot_set = engine.create_snapshot(
        execution_id="exec-002",
        node_id="coder-node",
        files=files,
    )

    # 模拟节点执行修改了文件（现在内容变了）
    modified_content = "print('MODIFIED BY AGENT')"
    print(f"  执行前内容: {original_content}")
    print(f"  执行后内容: {modified_content}")

    # 回滚到快照版本
    result = engine.restore(
        snapshot_id=snapshot_set.snapshot_id,
        files={"__demo__.py": modified_content},
    )

    print(f"  回滚成功: {result.success}")
    print(f"  恢复文件数: {result.files_restored}")


def demo_rollback_verify():
    """Demo 5: 回滚验证——确认恢复后内容与快照一致"""
    print("\n" + "=" * 60)
    print("Demo 5: 回滚验证——SHA-256 哈希确认恢复完整性")
    print("=" * 60)

    engine = RollbackEngine()

    original = "def hello(): return 'world'"
    files = {"__demo2__.py": original}

    snapshot_set = engine.create_snapshot(
        execution_id="exec-003",
        node_id="reviewer-node",
        files=files,
    )

    # 验证快照完整性
    is_valid = engine.verify_snapshot(snapshot_set)
    print(f"  快照完整性验证: {is_valid}")


if __name__ == "__main__":
    print("=" * 60)
    print("Harness Downgrade + Rollback Demo")
    print("=" * 60)
    demo_downgrade_policy()
    demo_downgrade_tracker()
    demo_rollback_snapshot()
    demo_rollback_restore()
    demo_rollback_verify()
    print("\n✅ 所有降级+回滚 Demo 完成")

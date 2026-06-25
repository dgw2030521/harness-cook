"""
审计 Demo 示例

演示 harness-cook 审计层的 SHA-256 哈希链验证、搜索、完整性报告。

运行方式:
  cd packages/core
  PYTHONPATH=. python3 ../../examples/audit/demo_audit.py

输出:
  - 写入审计记录 + 哈希链构建
  - 搜索审计记录
  - 验证哈希链完整性
  - 完整性报告
"""

import sys
sys.path.insert(0, "../../packages/core")

from harness.audit import AuditStore, AuditEntry
from harness.types import AuditStats
from datetime import datetime, timezone


def demo_save_and_chain():
    """Demo 1: 写入审计记录 + 哈希链构建"""
    print("\n" + "=" * 60)
    print("Demo 1: 写入审计记录 + 哈希链构建")
    print("=" * 60)

    store = AuditStore(store_dir="/tmp/harness-audit-demo")

    # 写入 3 条记录
    ids = []
    for i in range(3):
        entry = AuditEntry(
            session_id="session-001",
            agent_id="claude-code",
            task=f"task-{i}",
            timestamp=datetime.now(timezone.utc),
            decisions=[{"gate": "quality", "result": "pass"}],
            actions=[{"type": "execute", "detail": f"step-{i}"}],
            outcomes=[{"rule": "SEC-001", "passed": True, "severity": "high"}],
        )
        entry_id = store.save(entry)
        ids.append(entry_id)
        print(f"  记录 {i}: id={entry_id}, chain_head={store.chain_head}")

    print(f"\n  总记录数: 3")
    print(f"  哈希链最新: {store.chain_head}")


def demo_search():
    """Demo 2: 搜索审计记录"""
    print("\n" + "=" * 60)
    print("Demo 2: 搜索审计记录")
    print("=" * 60)

    store = AuditStore(store_dir="/tmp/harness-audit-demo")

    # 搜索
    entries = store.search("session-001")
    print(f"  搜索 'session-001': 找到 {len(entries)} 条记录")

    for e in entries:
        print(f"    session={e.session_id}, task={e.task}, agent={e.agent_id}")


def demo_verify_chain():
    """Demo 3: 验证哈希链完整性"""
    print("\n" + "=" * 60)
    print("Demo 3: 验证哈希链完整性")
    print("=" * 60)

    store = AuditStore(store_dir="/tmp/harness-audit-demo")

    result = store.verify_chain()
    print(f"  链完整: {result['valid']}")
    print(f"  总记录: {result['total_records']}")
    print(f"  篡改记录: {result['tampered']}")
    print(f"  断链位置: {result['broken_links']}")


def demo_integrity_report():
    """Demo 4: 完整性报告"""
    print("\n" + "=" * 60)
    print("Demo 4: 完整性报告")
    print("=" * 60)

    store = AuditStore(store_dir="/tmp/harness-audit-demo")

    report = store.integrity_report()
    print(f"  完整性报告: {report}")


def demo_stats():
    """Demo 5: 审计统计"""
    print("\n" + "=" * 60)
    print("Demo 5: 审计统计")
    print("=" * 60)

    store = AuditStore(store_dir="/tmp/harness-audit-demo")

    stats = store.stats()
    print(f"  统计: {stats}")


if __name__ == "__main__":
    print("=" * 60)
    print("Harness Audit Demo")
    print("=" * 60)
    demo_save_and_chain()
    demo_search()
    demo_verify_chain()
    demo_integrity_report()
    demo_stats()
    print("\n✅ 所有审计 Demo 完成")

"""
多 Agent 协商 Demo 示例

演示 harness-cook 的协商引擎——冲突检测、自动合并、辩论解决。

运行方式:
  cd packages/core
  PYTHONPATH=. python3 ../../examples/negotiation/demo_negotiation.py

输出:
  - 冲突检测——多 Agent 修改同一文件
  - 自动合并——非重叠区域自动合并
  - 辩论解决——重叠区域 Agent A/B 各出理由，评判者裁决
"""

import sys
sys.path.insert(0, "../../packages/core")

from harness.negotiation import ConflictDetector, NegotiationEngine
from harness.types import Artifact, IExecutableAgent, AgentDefinition


def demo_conflict_detection():
    """Demo 1: 冲突检测——多 Agent 修改同一文件"""
    print("\n" + "=" * 60)
    print("Demo 1: 冲突检测——多 Agent 修改同一文件")
    print("=" * 60)

    detector = ConflictDetector()

    # Agent A 和 B 都修改了 config.py
    artifacts_a = [
        Artifact(type="code", path="config.py", content="API_KEY = 'new-key-a'\nPORT = 8080"),
    ]
    artifacts_b = [
        Artifact(type="code", path="config.py", content="API_KEY = 'new-key-b'\nPORT = 8080"),
    ]

    conflicts = detector.detect({
        "coder-a": artifacts_a,
        "coder-b": artifacts_b,
    })

    print(f"  检测到冲突数: {len(conflicts)}")
    for c in conflicts:
        print(f"    文件: {c.file_path}")
        print(f"    Agent A: {c.agent_a}")
        print(f"    Agent B: {c.agent_b}")


def demo_auto_merge():
    """Demo 2: 自动合并——非重叠区域"""
    print("\n" + "=" * 60)
    print("Demo 2: 自动合并——非重叠修改可自动合并")
    print("=" * 60)

    engine = NegotiationEngine()

    # Agent A 修改文件顶部，Agent B 修改文件底部——非重叠
    artifacts_a = [
        Artifact(type="code", path="app.py", content="# header by A\nimport os\n\ndef main():\n    pass"),
    ]
    artifacts_b = [
        Artifact(type="code", path="utils.py", content="# header by B\ndef helper():\n    pass"),
    ]

    # utils.py 只有 Agent B 修改，无冲突 → 自动合并
    conflicts = engine.conflict_detector.detect({
        "coder-a": artifacts_a,
        "coder-b": artifacts_b,
    })

    print(f"  不同文件修改 → 冲突数: {len(conflicts)} (无冲突)")
    print(f"  非重叠修改 → 可以自动合并")


def demo_debate():
    """Demo 3: 辩论解决——重叠区域协商"""
    print("\n" + "=" * 60)
    print("Demo 3: 辩论解决——Agent 各出理由，评判者裁决")
    print("=" * 60)

    engine = NegotiationEngine()

    # 创建冲突
    artifacts_a = [
        Artifact(type="code", path="config.py", content="timeout = 30  # Agent A: 30秒足够"),
    ]
    artifacts_b = [
        Artifact(type="code", path="config.py", content="timeout = 120  # Agent B: 需要更长超时"),
    ]

    conflicts = engine.conflict_detector.detect({
        "coder-a": artifacts_a,
        "coder-b": artifacts_b,
    })

    print(f"  冲突文件: {conflicts[0].file_path}")
    print(f"  Agent A 理由: '30秒足够'"
          f"  Agent B 理由: '需要更长超时'")
    print(f"  协商流程: detect → debate → resolve → merge/escalate")


def demo_negotiation_flow():
    """Demo 4: 协商流程概览"""
    print("\n" + "=" * 60)
    print("Demo 4: 协商流程概览")
    print("=" * 60)

    print("  完整协商流程:")
    print("  1. ConflictDetector.detect() → 发现文件冲突")
    print("  2. NegotiationEngine._try_auto_merge() → 非重叠区域自动合并")
    print("  3. NegotiationEngine._debate() → 重叠区域辩论解决")
    print("  4. 升级人工 → 无法自动解决时通知人类审批")
    print()
    print("  三种解决方式:")
    print("    auto_merge  → 非重叠修改自动合并（零人工干预）")
    print("    debate      → Agent 各出理由，评判者裁决")
    print("    escalate    → 升级人类审批（最终保障）")


if __name__ == "__main__":
    print("=" * 60)
    print("Harness Negotiation Demo")
    print("=" * 60)
    demo_conflict_detection()
    demo_auto_merge()
    demo_debate()
    demo_negotiation_flow()
    print("\n✅ 所有协商 Demo 完成")

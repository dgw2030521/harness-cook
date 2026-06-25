"""
E-7 验收测试：EventBus per-project isolation

验收标准：
1. get_bus(project_name="A") 和 get_bus(project_name="B") 返回不同实例
2. 项目A事件不出现在项目B bus history
3. get_bus()（无参数）返回全局 Bus（向后兼容）
4. BusEvent.project_name 字段存在且可选
5. EventBus.stats() 包含 project_name
6. reset_bus(project_name) 只重置指定项目
7. list_project_buses() 返回所有项目级 Bus 名称
8. 全局 Bus 事件不出现在项目级 Bus history
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.bus import EventBus, get_bus, reset_bus, list_project_buses
from harness.types import BusEvent, BusEventType


def test_different_projects_return_different_bus():
    """验收标准1：不同项目名返回不同 Bus 实例"""
    reset_bus()  # 清理全局状态

    bus_a = get_bus(project_name="project-a")
    bus_b = get_bus(project_name="project-b")

    assert bus_a is not bus_b, \
        "不同项目名应返回不同 Bus 实例"


def test_project_a_events_not_in_project_b_history():
    """验收标准2：项目A事件不出现在项目B bus history"""
    reset_bus()

    bus_a = get_bus(project_name="project-a")
    bus_b = get_bus(project_name="project-b")

    # 项目A发射事件
    event_a = BusEvent(
        type=BusEventType.NODE_START,
        execution_id="ex-a-1",
        project_name="project-a",
    )
    bus_a.emit(event_a)

    # 项目B发射事件
    event_b = BusEvent(
        type=BusEventType.NODE_START,
        execution_id="ex-b-1",
        project_name="project-b",
    )
    bus_b.emit(event_b)

    # 项目A history 应只有项目A的事件
    history_a = bus_a.get_history()
    assert len(history_a) == 1, \
        f"项目A history 应只有1条事件: {len(history_a)}"
    assert history_a[0].execution_id == "ex-a-1", \
        f"项目A history 应只有项目A事件: {history_a[0].execution_id}"

    # 项目B history 应只有项目B的事件
    history_b = bus_b.get_history()
    assert len(history_b) == 1, \
        f"项目B history 应只有1条事件: {len(history_b)}"
    assert history_b[0].execution_id == "ex-b-1", \
        f"项目B history 应只有项目B事件: {history_b[0].execution_id}"


def test_get_bus_no_args_returns_global():
    """验收标准3：get_bus() 无参数返回全局 Bus（向后兼容）"""
    reset_bus()

    bus_global = get_bus()
    bus_global2 = get_bus()

    assert bus_global is bus_global2, \
        "get_bus() 多次调用应返回同一全局实例"
    assert bus_global._project_name is None, \
        "全局 Bus 的 project_name 应为 None"


def test_bus_event_project_name_field():
    """验收标准4：BusEvent.project_name 字段存在且可选"""
    # 无 project_name
    event1 = BusEvent(
        type=BusEventType.NODE_START,
        execution_id="ex-1",
    )
    assert event1.project_name is None, \
        "BusEvent.project_name 默认应为 None"

    # 有 project_name
    event2 = BusEvent(
        type=BusEventType.NODE_START,
        execution_id="ex-2",
        project_name="my-project",
    )
    assert event2.project_name == "my-project", \
        "BusEvent.project_name 应可设置"


def test_stats_contains_project_name():
    """验收标准5：EventBus.stats() 包含 project_name"""
    bus_global = get_bus()
    stats_global = bus_global.stats()
    assert "project_name" in stats_global, \
        f"stats 应包含 project_name 字段: {stats_global}"
    assert stats_global["project_name"] == "__global__", \
        f"全局 Bus stats 的 project_name 应为 __global__: {stats_global['project_name']}"

    bus_proj = get_bus(project_name="test-proj")
    stats_proj = bus_proj.stats()
    assert stats_proj["project_name"] == "test-proj", \
        f"项目级 Bus stats 的 project_name 应为项目名: {stats_proj['project_name']}"


def test_reset_bus_specific_project():
    """验收标准6：reset_bus(project_name) 只重置指定项目"""
    reset_bus()

    bus_a = get_bus(project_name="project-a")
    bus_a.emit(BusEvent(
        type=BusEventType.NODE_START,
        execution_id="ex-a-1",
        project_name="project-a",
    ))

    bus_b = get_bus(project_name="project-b")
    bus_b.emit(BusEvent(
        type=BusEventType.NODE_START,
        execution_id="ex-b-1",
        project_name="project-b",
    ))

    # 只重置项目A
    reset_bus(project_name="project-a")

    # 项目A history 应为空（重置后）
    bus_a_new = get_bus(project_name="project-a")
    assert len(bus_a_new.get_history()) == 0, \
        f"重置后项目A history 应为空: {len(bus_a_new.get_history())}"

    # 项目B history 应保持不变
    bus_b_existing = get_bus(project_name="project-b")
    assert len(bus_b_existing.get_history()) == 1, \
        f"项目B history 应保持不变: {len(bus_b_existing.get_history())}"


def test_list_project_buses():
    """验收标准7：list_project_buses() 返回所有项目级 Bus 名称"""
    reset_bus()

    get_bus(project_name="alpha")
    get_bus(project_name="beta")

    names = list_project_buses()
    assert "alpha" in names, f"alpha 应在项目列表中: {names}"
    assert "beta" in names, f"beta 应在项目列表中: {names}"
    assert len(names) == 2, f"应有2个项目级 Bus: {names}"


def test_global_bus_events_not_in_project_history():
    """验收标准8：全局 Bus 事件不出现在项目级 Bus history"""
    reset_bus()

    bus_global = get_bus()
    bus_proj = get_bus(project_name="isolated")

    # 全局 Bus 发射事件
    bus_global.emit(BusEvent(
        type=BusEventType.NODE_START,
        execution_id="ex-global-1",
    ))

    # 项目级 Bus history 应为空
    assert len(bus_proj.get_history()) == 0, \
        f"项目级 Bus history 不应包含全局事件: {len(bus_proj.get_history())}"


# ─── 运行所有测试 ────────────────────────────────────────

def run_all_tests():
    reset_bus()  # 全局清理

    tests = [
        test_different_projects_return_different_bus,
        test_project_a_events_not_in_project_b_history,
        test_get_bus_no_args_returns_global,
        test_bus_event_project_name_field,
        test_stats_contains_project_name,
        test_reset_bus_specific_project,
        test_list_project_buses,
        test_global_bus_events_not_in_project_history,
    ]

    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            reset_bus()  # 每个测试前清理
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

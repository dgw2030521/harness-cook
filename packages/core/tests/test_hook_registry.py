"""
HookPointRegistry 测试

测试覆盖：
- 注册映射表
- 验证非法槽位名
- 覆盖度报告
- 清空注册
- 与适配器集成（ClaudeCode + Hermes 映射已注册）
"""

import pytest

from harness.hook_registry import HookPointRegistry
from harness.types import SkillSlotName


class TestHookPointRegistry:
    """HookPointRegistry 注册与覆盖度测试"""

    def setup_method(self):
        """每个测试前清空注册，避免其他适配器模块加载的注册影响"""
        HookPointRegistry.clear()

    def test_register_mapping(self):
        """测试注册映射表"""
        mapping = {
            "session_start": "SessionStart",
            "pre_execute": "PreToolUse",
        }
        HookPointRegistry.register("test-adapter", mapping)

        assert HookPointRegistry.get_mapping("test-adapter") == mapping
        assert "test-adapter" in HookPointRegistry.all_registered_adapters()

    def test_register_invalid_slot_name_rejected(self):
        """测试拒绝非法槽位名"""
        mapping = {
            "invalid_slot": "SomeEvent",
        }
        with pytest.raises(ValueError, match="Invalid slot names"):
            HookPointRegistry.register("bad-adapter", mapping)

    def test_register_valid_slot_name_accepted(self):
        """测试合法槽位名全部通过"""
        all_valid_slots = set(SkillSlotName._value2member_map_.keys())
        # 只注册一部分即可验证合法性检查通过
        mapping = {
            "session_start": "SomeEvent",
            "pre_execute": "AnotherEvent",
        }
        HookPointRegistry.register("valid-adapter", mapping)
        assert "valid-adapter" in HookPointRegistry.all_registered_adapters()

    def test_coverage_report(self):
        """测试覆盖度报告"""
        # 只注册覆盖 3 个槽位的映射
        mapping = {
            "session_start": "SessionStart",
            "pre_execute": "PreToolUse",
            "post_execute": "PostToolUse",
        }
        HookPointRegistry.register("partial-adapter", mapping)

        report = HookPointRegistry.coverage_report()
        assert "partial-adapter" in report

        info = report["partial-adapter"]
        assert "session_start" in info["covered"]
        assert "pre_execute" in info["covered"]
        assert "post_execute" in info["covered"]
        assert "on_gate_pass" in info["uncovered"]  # 未覆盖的槽位
        assert info["coverage_pct"] > 0

    def test_coverage_report_percentage(self):
        """测试覆盖度百分比计算"""
        total_slots = len(SkillSlotName._value2member_map_)
        mapping = {
            "session_start": "SessionStart",
            "session_end": "SessionEnd",
            "pre_execute": "PreToolUse",
        }
        HookPointRegistry.register("pct-adapter", mapping)

        report = HookPointRegistry.coverage_report()
        expected_pct = round(3 / total_slots * 100, 1)
        assert report["pct-adapter"]["coverage_pct"] == expected_pct

    def test_get_mapping_unregistered_adapter(self):
        """测试获取未注册适配器的映射——返回空字典"""
        result = HookPointRegistry.get_mapping("nonexistent")
        assert result == {}

    def test_clear(self):
        """测试清空注册"""
        HookPointRegistry.register("temp-adapter", {"session_start": "SessionStart"})
        assert "temp-adapter" in HookPointRegistry.all_registered_adapters()

        HookPointRegistry.clear()
        assert len(HookPointRegistry.all_registered_adapters()) == 0

    def test_validate_all_valid(self):
        """测试 validate_all——所有映射合法时返回 True"""
        HookPointRegistry.register("good-1", {"session_start": "SessionStart"})
        HookPointRegistry.register("good-2", {"pre_execute": "BeforeTask"})

        assert HookPointRegistry.validate_all() is True

    def test_multiple_adapters_coverage(self):
        """测试多适配器的覆盖度交叉视图"""
        HookPointRegistry.register("adapter-a", {
            "session_start": "EventA",
            "pre_execute": "EventB",
        })
        HookPointRegistry.register("adapter-b", {
            "session_start": "EventX",
            "post_execute": "EventY",
            "on_error": "EventZ",
        })

        report = HookPointRegistry.coverage_report()
        # 两个适配器都覆盖了 session_start
        assert "session_start" in report["adapter-a"]["covered"]
        assert "session_start" in report["adapter-b"]["covered"]
        # adapter-a 未覆盖 post_execute
        assert "post_execute" in report["adapter-a"]["uncovered"]


class TestAdapterIntegration:
    """适配器映射注册集成测试

    验证 ClaudeCode 和 Hermes 适配器的映射能正确注册到 HookPointRegistry。
    由于单元测试类的 setup_method 会清空注册，这里需要显式重新注册
    以保证测试独立性（不依赖其他测试类的执行顺序）。
    """

    def setup_method(self):
        """显式注册适配器映射——保证独立性"""
        from harness.adapters.claude_code import HOOK_POINT_MAP
        from harness.adapters.hermes import HERMES_HOOK_POINT_MAP

        HookPointRegistry.clear()
        HookPointRegistry.register("claude-code", HOOK_POINT_MAP)
        HookPointRegistry.register("hermes", HERMES_HOOK_POINT_MAP)

    def test_claude_code_mapping_registered(self):
        """验证 ClaudeCode 映射已注册"""
        from harness.adapters.claude_code import HOOK_POINT_MAP

        mapping = HookPointRegistry.get_mapping("claude-code")
        assert mapping == HOOK_POINT_MAP
        assert "session_start" in mapping
        assert mapping["session_end"] == "SessionEnd"
        assert mapping["on_error"] == "PostToolUseFailure"

    def test_hermes_mapping_registered(self):
        """验证 Hermes 映射已注册"""
        from harness.adapters.hermes import HERMES_HOOK_POINT_MAP

        mapping = HookPointRegistry.get_mapping("hermes")
        assert mapping == HERMES_HOOK_POINT_MAP
        assert mapping["session_start"] == "on_session_start"
        assert mapping["pre_execute"] == "before_task"
        assert mapping["on_error"] == "on_error"

    def test_both_adapters_in_registered_set(self):
        """验证两个适配器都在已注册集合中"""
        adapters = HookPointRegistry.all_registered_adapters()
        assert "claude-code" in adapters
        assert "hermes" in adapters

    def test_claude_code_coverage(self):
        """ClaudeCode 映射覆盖了 9 个槽位"""
        report = HookPointRegistry.coverage_report()
        claude_info = report["claude-code"]
        # 9 个有映射的槽位
        assert len(claude_info["covered"]) == 9
        # 8 个无映射的槽位
        assert len(claude_info["uncovered"]) == 8

    def test_hermes_coverage(self):
        """Hermes 映射覆盖了 7 个槽位"""
        report = HookPointRegistry.coverage_report()
        hermes_info = report["hermes"]
        # 7 个有映射的槽位
        assert len(hermes_info["covered"]) == 7

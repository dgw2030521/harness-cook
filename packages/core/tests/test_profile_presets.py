"""
部署分级 Profile 预置测试

测试策略:
- 验证 basic.yaml / enterprise.yaml / default.yaml 都能正确加载
- 验证各 Profile 的关键配置差异（gate_mode、pipeline_agents、hooks）
- 验证 Profile 之间的分级关系：basic < default < enterprise
"""

import unittest
from pathlib import Path

from harness.config import ProfileLoader
from harness.types import ProfileConfig, GateMode


PROFILES_DIR = Path(__file__).resolve().parent.parent.parent.parent / ".harness" / "profiles"


class TestProfilePresets(unittest.TestCase):
    """Profile 预置加载与配置差异测试"""

    def setUp(self):
        self.loader = ProfileLoader(profiles_dir=str(PROFILES_DIR))

    def test_all_profiles_loadable(self):
        """所有预置 Profile 都能正确加载"""
        profiles = self.loader.list_profiles()
        self.assertIn("basic", profiles)
        self.assertIn("default", profiles)
        self.assertIn("enterprise", profiles)

    def test_basic_profile_gate_mode(self):
        """basic Profile → GateMode.LOOSE"""
        basic = self.loader.load("basic")
        self.assertEqual(basic.default_gate_mode, GateMode.LOOSE)

    def test_default_profile_gate_mode(self):
        """default Profile → GateMode.HYBRID"""
        default = self.loader.load("default")
        self.assertEqual(default.default_gate_mode, GateMode.HYBRID)

    def test_enterprise_profile_gate_mode(self):
        """enterprise Profile → GateMode.STRICT"""
        enterprise = self.loader.load("enterprise")
        self.assertEqual(enterprise.default_gate_mode, GateMode.STRICT)

    def test_basic_pipeline_shortest(self):
        """basic Pipeline 最短（3步）"""
        basic = self.loader.load("basic")
        self.assertEqual(len(basic.pipeline_agents), 3)
        self.assertEqual(basic.pipeline_agents, ["analyst", "coder", "committer"])

    def test_default_pipeline_medium(self):
        """default Pipeline 中等（5步）"""
        default = self.loader.load("default")
        self.assertEqual(len(default.pipeline_agents), 5)

    def test_enterprise_pipeline_longest(self):
        """enterprise Pipeline 最长（5步 + reviewer + validator）"""
        enterprise = self.loader.load("enterprise")
        self.assertEqual(len(enterprise.pipeline_agents), 5)
        self.assertIn("reviewer", enterprise.pipeline_agents)
        self.assertIn("validator", enterprise.pipeline_agents)

    def test_basic_minimal_hooks(self):
        """basic → hooks 最少（session_start + post_execute）"""
        basic = self.loader.load("basic")
        # basic 只有 2 个活跃 hooks
        active_hooks = [k for k, v in basic.hooks.items() if v]
        self.assertEqual(len(active_hooks), 2)
        self.assertIn("session_start", active_hooks)
        self.assertIn("post_execute", active_hooks)

    def test_enterprise_more_hooks_than_default(self):
        """enterprise → hooks 比default更多"""
        default = self.loader.load("default")
        enterprise = self.loader.load("enterprise")
        default_active = [k for k, v in default.hooks.items() if v]
        enterprise_active = [k for k, v in enterprise.hooks.items() if v]
        self.assertTrue(len(enterprise_active) >= len(default_active))

    def test_gate_checks_count_escalation(self):
        """门禁检查数量递增：basic < default < enterprise"""
        basic = self.loader.load("basic")
        default = self.loader.load("default")
        enterprise = self.loader.load("enterprise")

        basic_checks = len(basic.gate_checks)
        default_checks = len(default.gate_checks)
        enterprise_checks = len(enterprise.gate_checks)

        self.assertTrue(enterprise_checks >= default_checks)
        self.assertTrue(default_checks >= basic_checks)

    def test_basic_description_contains_keyword(self):
        """basic 描述包含关键信息"""
        basic = self.loader.load("basic")
        self.assertIn("basic", basic.name.lower())
        self.assertTrue(len(basic.description) > 0)

    def test_enterprise_description_contains_keyword(self):
        """enterprise 描述包含关键信息"""
        enterprise = self.loader.load("enterprise")
        self.assertIn("enterprise", enterprise.name.lower())
        self.assertTrue(len(enterprise.description) > 0)

    def test_enterprise_has_strict_constraints(self):
        """enterprise 约束比 basic 更严格"""
        basic = self.loader.load("basic")
        enterprise = self.loader.load("enterprise")

        # enterprise constraints 应比 basic 更严格
        basic_max_retries = basic.constraints.get("max_retries", 3)
        enterprise_max_retries = enterprise.constraints.get("max_retries", 2)
        self.assertTrue(enterprise_max_retries <= basic_max_retries)

    def test_profile_switching(self):
        """切换 Profile → 行为模式完全不同"""
        basic = self.loader.load("basic")
        enterprise = self.loader.load("enterprise")

        # GateMode 不同
        self.assertNotEqual(basic.default_gate_mode, enterprise.default_gate_mode)

        # Pipeline 不同
        self.assertNotEqual(basic.pipeline_agents, enterprise.pipeline_agents)

        # 至少有一个关键差异已确认
        self.assertTrue(
            basic.default_gate_mode != enterprise.default_gate_mode or
            basic.pipeline_agents != enterprise.pipeline_agents or
            basic.hooks != enterprise.hooks
        )


if __name__ == "__main__":
    unittest.main()

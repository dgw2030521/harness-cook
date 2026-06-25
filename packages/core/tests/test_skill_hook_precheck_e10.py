"""
E-10：skill hook 预检查验收测试

验证要点:
  1. SkillRegistry.has() 方法存在且正确工作
  2. ProfileLoader._validate_hooks_skill_ids() 方法存在
  3. 不存在的 skill_id → warning 日志 + 返回 missing_ids 列表
  4. 已注册的 skill_id → 不报错
  5. type="script" 的 hook → 不校验 skill_id
  6. ProfileLoader.load() 自动调用校验
  7. SkillRegistry 不可用时 → 跳过校验
"""

import logging
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from harness.skill_registry import SkillRegistry, SkillDefinition, SkillRecord
from harness.types import SkillSlotName, ProfileConfig
from harness.config import ProfileLoader


class TestSkillRegistryHas(unittest.TestCase):
    """E-10：SkillRegistry.has() 方法"""

    def setUp(self):
        self.registry = SkillRegistry()

    def test_has_method_exists(self):
        """E-10：SkillRegistry 有 has() 方法"""
        self.assertTrue(hasattr(self.registry, "has"))

    def test_has_returns_true_for_registered_skill(self):
        """E-10：已注册的 skill_id → has() 返回 True"""
        skill = SkillDefinition(
            id="auto-audit",
            name="自动审计",
            slot=SkillSlotName.POST_EXECUTE,
            entry_point="skills/auto-audit/audit_report.py",
        )
        self.registry.register(skill)
        self.assertTrue(self.registry.has("auto-audit"))

    def test_has_returns_false_for_missing_skill(self):
        """E-10：不存在的 skill_id → has() 返回 False"""
        self.assertFalse(self.registry.has("non-existent-skill"))

    def test_has_returns_false_for_empty_id(self):
        """E-10：空字符串 → has() 返回 False"""
        self.assertFalse(self.registry.has(""))


class TestValidateHooksSkillIds(unittest.TestCase):
    """E-10：ProfileLoader._validate_hooks_skill_ids() 校验逻辑"""

    def setUp(self):
        self.loader = ProfileLoader()
        self.registry = SkillRegistry()

    def _mock_registry(self, registry):
        """返回一个 mock 函数让 get_skill_registry 返回指定 registry"""
        return patch("harness.skill_registry.get_skill_registry", return_value=registry)

    def test_method_exists(self):
        """E-10：ProfileLoader 有 _validate_hooks_skill_ids 方法"""
        self.assertTrue(hasattr(self.loader, "_validate_hooks_skill_ids"))

    def test_missing_skill_id_returns_list(self):
        """E-10：不存在的 skill_id → 返回包含该 ID 的列表"""
        profile = ProfileConfig(
            name="test",
            hooks={
                "post_execute": [
                    {"type": "skill", "skill_id": "ghost-skill"},
                ],
            },
        )

        with self._mock_registry(self.registry):
            missing = self.loader._validate_hooks_skill_ids(profile)

        self.assertIn("ghost-skill", missing)
        self.assertEqual(len(missing), 1)

    def test_registered_skill_id_returns_empty_list(self):
        """E-10：已注册的 skill_id → 返回空列表"""
        skill = SkillDefinition(
            id="auto-audit",
            name="自动审计",
            slot=SkillSlotName.POST_EXECUTE,
            entry_point="skills/auto-audit/audit_report.py",
        )
        self.registry.register(skill)

        profile = ProfileConfig(
            name="test",
            hooks={
                "post_execute": [
                    {"type": "skill", "skill_id": "auto-audit"},
                ],
            },
        )

        with self._mock_registry(self.registry):
            missing = self.loader._validate_hooks_skill_ids(profile)

        self.assertEqual(len(missing), 0)

    def test_script_hooks_not_checked(self):
        """E-10：type="script" 的 hook → 不校验 skill_id"""
        profile = ProfileConfig(
            name="test",
            hooks={
                "session_start": [
                    {"type": "script", "command": "python3 scripts/init.py"},
                ],
            },
        )

        with self._mock_registry(self.registry):
            missing = self.loader._validate_hooks_skill_ids(profile)

        self.assertEqual(len(missing), 0)

    def test_multiple_missing_ids(self):
        """E-10：多个不存在的 skill_id → 全部返回"""
        profile = ProfileConfig(
            name="test",
            hooks={
                "post_execute": [
                    {"type": "skill", "skill_id": "ghost-1"},
                    {"type": "skill", "skill_id": "ghost-2"},
                ],
                "on_gate_fail": [
                    {"type": "skill", "skill_id": "ghost-3"},
                ],
            },
        )

        with self._mock_registry(self.registry):
            missing = self.loader._validate_hooks_skill_ids(profile)

        self.assertEqual(len(missing), 3)
        self.assertIn("ghost-1", missing)
        self.assertIn("ghost-2", missing)
        self.assertIn("ghost-3", missing)

    def test_empty_hooks_returns_empty(self):
        """E-10：空 hooks → 返回空列表"""
        profile = ProfileConfig(name="test", hooks={})

        missing = self.loader._validate_hooks_skill_ids(profile)
        self.assertEqual(len(missing), 0)

    def test_skill_registry_unavailable_skips_validation(self):
        """E-10：SkillRegistry 不可用 → 跳过校验，返回空列表"""
        profile = ProfileConfig(
            name="test",
            hooks={
                "post_execute": [
                    {"type": "skill", "skill_id": "ghost-skill"},
                ],
            },
        )

        # 直接调用方法，但让 get_skill_registry 在方法内部导入时抛异常
        with patch("harness.skill_registry.get_skill_registry", side_effect=Exception("Registry unavailable")):
            missing = self.loader._validate_hooks_skill_ids(profile)

        self.assertEqual(len(missing), 0)

    def test_warning_log_on_missing_skill_id(self):
        """E-10：不存在 skill_id → warning 日志"""
        profile = ProfileConfig(
            name="test-profile",
            hooks={
                "on_gate_pass": [
                    {"type": "skill", "skill_id": "phantom"},
                ],
            },
        )

        with self._mock_registry(self.registry):
            with self.assertLogs("harness.config", level=logging.WARNING) as cm:
                self.loader._validate_hooks_skill_ids(profile)

        # 应有包含 phantom 的 warning 日志
        phantom_warnings = [msg for msg in cm.output if "phantom" in msg]
        self.assertTrue(len(phantom_warnings) > 0,
                        f"Expected warning about 'phantom', got: {cm.output}")

    def test_no_warning_on_valid_skill_id(self):
        """E-10：已注册 skill_id → 无 warning 日志"""
        skill = SkillDefinition(
            id="auto-fix",
            name="自动修复",
            slot=SkillSlotName.ON_GATE_FAIL,
            entry_point="skills/auto-fix/fix.py",
        )
        self.registry.register(skill)

        profile = ProfileConfig(
            name="test",
            hooks={
                "on_gate_fail": [
                    {"type": "skill", "skill_id": "auto-fix"},
                ],
            },
        )

        with self._mock_registry(self.registry):
            # DEBUG 级别不应有 skill_id 相关 WARNING
            with self.assertLogs("harness.config", level=logging.DEBUG) as cm:
                missing = self.loader._validate_hooks_skill_ids(profile)

        self.assertEqual(len(missing), 0)
        # 没有 skill_id 不存在的 warning
        skill_warnings = [msg for msg in cm.output if "WARNING" in msg and "skill_id" in msg]
        self.assertEqual(len(skill_warnings), 0)


class TestProfileLoaderLoadCallsValidation(unittest.TestCase):
    """E-10：ProfileLoader.load() 自动调用校验"""

    def test_load_calls_validate_hooks_skill_ids(self):
        """E-10：load() 加载 Profile 后自动调用 _validate_hooks_skill_ids"""
        loader = ProfileLoader()

        with patch.object(loader, "_validate_hooks_skill_ids", return_value=[]) as mock_validate:
            # 让 _read_file 返回包含 skill hook 的配置
            test_data = {
                "profile": {"name": "test"},
                "hooks": {
                    "post_execute": [{"type": "skill", "skill_id": "auto-audit"}],
                },
            }
            with patch.object(loader, "_read_file", return_value=test_data):
                # 让项目级 profile 文件存在
                with patch.object(Path, "exists", return_value=True):
                    loader.load("test")

        mock_validate.assert_called_once()


if __name__ == "__main__":
    unittest.main()

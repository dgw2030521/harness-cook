"""
Profile 选择机制测试

测试策略:
- resolve_active(): 环境变量优先 > marker file > "default" 回退
- switch(): 写入 marker file + 校验合法性
- load(None): 自动调用 resolve_active()
- 边界: 环境变量值无效 → 降级到 marker file
"""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from harness.config import ProfileLoader, resolve_active_profile, switch_profile


PROFILES_DIR = Path(__file__).resolve().parent.parent.parent.parent / ".harness" / "profiles"
HARNESS_DIR = PROFILES_DIR.parent


class TestResolveActive(unittest.TestCase):
    """resolve_active() 三级优先级测试"""

    def setUp(self):
        self.loader = ProfileLoader(profiles_dir=str(PROFILES_DIR))
        # 清理 marker file
        marker = HARNESS_DIR / "active_profile"
        if marker.exists():
            marker.unlink()
        # 清理环境变量
        os.environ.pop("HARNESS_PROFILE", None)

    def tearDown(self):
        marker = HARNESS_DIR / "active_profile"
        if marker.exists():
            marker.unlink()
        os.environ.pop("HARNESS_PROFILE", None)

    def test_default_fallback(self):
        """无环境变量、无 marker file → 回退 default"""
        result = self.loader.resolve_active()
        self.assertEqual(result, "default")

    def test_env_var_overrides_marker(self):
        """HARNESS_PROFILE 环境变量优先于 marker file"""
        # 设置 marker file
        marker = HARNESS_DIR / "active_profile"
        marker.write_text("basic", encoding="utf-8")
        # 设置环境变量
        with patch.dict(os.environ, {"HARNESS_PROFILE": "enterprise"}):
            result = self.loader.resolve_active()
        self.assertEqual(result, "enterprise")

    def test_marker_file_without_env(self):
        """无环境变量时，marker file 生效"""
        marker = HARNESS_DIR / "active_profile"
        marker.write_text("basic", encoding="utf-8")
        result = self.loader.resolve_active()
        self.assertEqual(result, "basic")

    def test_env_var_invalid_falls_to_marker(self):
        """HARNESS_PROFILE 值不在可用列表 → 降级到 marker file"""
        marker = HARNESS_DIR / "active_profile"
        marker.write_text("basic", encoding="utf-8")
        with patch.dict(os.environ, {"HARNESS_PROFILE": "nonexistent"}):
            result = self.loader.resolve_active()
        self.assertEqual(result, "basic")

    def test_env_var_invalid_no_marker(self):
        """HARNESS_PROFILE 无效且无 marker → 回退 default"""
        with patch.dict(os.environ, {"HARNESS_PROFILE": "nonexistent"}):
            result = self.loader.resolve_active()
        self.assertEqual(result, "default")

    def test_marker_invalid_falls_to_default(self):
        """marker file 值无效 → 回退 default"""
        marker = HARNESS_DIR / "active_profile"
        marker.write_text("nonexistent", encoding="utf-8")
        result = self.loader.resolve_active()
        self.assertEqual(result, "default")

    def test_marker_file_empty_falls_to_default(self):
        """marker file 内容为空 → 回退 default"""
        marker = HARNESS_DIR / "active_profile"
        marker.write_text("", encoding="utf-8")
        result = self.loader.resolve_active()
        self.assertEqual(result, "default")


class TestSwitch(unittest.TestCase):
    """switch() 写入 marker file + 校验测试"""

    def setUp(self):
        self.loader = ProfileLoader(profiles_dir=str(PROFILES_DIR))
        marker = HARNESS_DIR / "active_profile"
        if marker.exists():
            marker.unlink()
        os.environ.pop("HARNESS_PROFILE", None)

    def tearDown(self):
        marker = HARNESS_DIR / "active_profile"
        if marker.exists():
            marker.unlink()
        os.environ.pop("HARNESS_PROFILE", None)

    def test_switch_to_basic(self):
        """switch basic → marker file 写入 basic"""
        result = self.loader.switch("basic")
        self.assertEqual(result, "basic")
        marker = HARNESS_DIR / "active_profile"
        self.assertEqual(marker.read_text(encoding="utf-8"), "basic")

    def test_switch_to_enterprise(self):
        """switch enterprise → marker file 写入 enterprise"""
        result = self.loader.switch("enterprise")
        self.assertEqual(result, "enterprise")
        marker = HARNESS_DIR / "active_profile"
        self.assertEqual(marker.read_text(encoding="utf-8"), "enterprise")

    def test_switch_invalid_raises(self):
        """switch("nonexistent") → ValueError"""
        with self.assertRaises(ValueError):
            self.loader.switch("nonexistent")

    def test_switch_then_resolve(self):
        """switch → resolve_active 返回新值"""
        self.loader.switch("basic")
        result = self.loader.resolve_active()
        self.assertEqual(result, "basic")

    def test_switch_then_load(self):
        """switch → load(None) 自动加载新 Profile"""
        self.loader.switch("basic")
        profile = self.loader.load(None)
        self.assertEqual(profile.name, "basic")
        self.assertEqual(profile.default_gate_mode.value, "loose")


class TestLoadWithAutoResolve(unittest.TestCase):
    """load(None) 自动 resolve_active 测试"""

    def setUp(self):
        self.loader = ProfileLoader(profiles_dir=str(PROFILES_DIR))
        marker = HARNESS_DIR / "active_profile"
        if marker.exists():
            marker.unlink()
        os.environ.pop("HARNESS_PROFILE", None)

    def tearDown(self):
        marker = HARNESS_DIR / "active_profile"
        if marker.exists():
            marker.unlink()
        os.environ.pop("HARNESS_PROFILE", None)

    def test_load_none_default(self):
        """load(None) 无选择 → 默认 default Profile"""
        profile = self.loader.load(None)
        self.assertEqual(profile.name, "default")

    def test_load_none_with_marker(self):
        """load(None) + marker file → 加载 marker 指定的 Profile"""
        marker = HARNESS_DIR / "active_profile"
        marker.write_text("enterprise", encoding="utf-8")
        profile = self.loader.load(None)
        self.assertEqual(profile.name, "enterprise")

    def test_load_explicit_ignores_resolve(self):
        """load 显式指定 basic → 不依赖 resolve"""
        # 设置 marker 为 enterprise
        marker = HARNESS_DIR / "active_profile"
        marker.write_text("enterprise", encoding="utf-8")
        # 但显式加载 basic
        profile = self.loader.load("basic")
        self.assertEqual(profile.name, "basic")


class TestConvenienceFunctions(unittest.TestCase):
    """resolve_active_profile / switch_profile 便利函数测试"""

    def setUp(self):
        marker = HARNESS_DIR / "active_profile"
        if marker.exists():
            marker.unlink()
        os.environ.pop("HARNESS_PROFILE", None)

    def tearDown(self):
        marker = HARNESS_DIR / "active_profile"
        if marker.exists():
            marker.unlink()
        os.environ.pop("HARNESS_PROFILE", None)

    def test_resolve_active_profile_default(self):
        """resolve_active_profile → 回退 default"""
        result = resolve_active_profile()
        self.assertEqual(result, "default")

    def test_switch_profile_basic(self):
        """switch_profile basic → 切换成功"""
        result = switch_profile("basic")
        self.assertEqual(result, "basic")
        # 验证 resolve 也返回 basic
        self.assertEqual(resolve_active_profile(), "basic")


if __name__ == "__main__":
    unittest.main()

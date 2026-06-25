"""Profile Loader 单元测试"""

import sys
import os
import pytest
import tempfile
import yaml
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.types import ProfileConfig, GateMode
from harness.config import ProfileLoader, builtin_profiles_dir


class TestProfileLoader:
    """ProfileLoader 测试"""

    def _create_profile_dir(self, tmpdir, name="default", content=None):
        """辅助：在临时目录创建 profile 文件"""
        profiles_dir = Path(tmpdir) / ".harness" / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        if content is None:
            content = {
                "profile": {"name": name, "description": "测试 Profile"},
                "agent": {"adapter": "claude-code"},
                "hooks": {
                    "session_start": [{"type": "script", "command": "echo hello"}],
                },
                "gates": {"default_mode": "strict"},
            }
        profile_path = profiles_dir / f"{name}.yaml"
        profile_path.write_text(yaml.dump(content, allow_unicode=True), encoding="utf-8")
        return str(profiles_dir)

    def test_load_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profiles_dir = self._create_profile_dir(tmpdir)
            loader = ProfileLoader(profiles_dir)
            profile = loader.load("default")
            assert profile.name == "default"
            assert profile.default_agent == "claude-code"
            assert "session_start" in profile.hooks
            assert profile.default_gate_mode == GateMode.STRICT

    def test_load_nonexistent_returns_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = ProfileLoader(str(Path(tmpdir) / "nonexistent"))
            profile = loader.load("missing")
            assert profile.name == "missing"
            assert profile.default_agent == "claude-code"

    def test_list_profiles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profiles_dir = self._create_profile_dir(tmpdir)
            loader = ProfileLoader(profiles_dir)
            profiles = loader.list_profiles()
            assert "default" in profiles

    def test_list_profiles_empty_dir(self):
        """项目级 profiles 目录为空时，内置 profiles 仍然可用"""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = ProfileLoader(tmpdir)
            profiles = loader.list_profiles()
            # 即使项目级为空，内置 preset profiles 依然可用
            assert "default" in profiles
            # 内置 presets 也包含在内
            if loader._builtin_profiles_dir:
                assert "frontend" in profiles

    def test_load_with_workflow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            content = {
                "profile": {"name": "with-workflow"},
                "agent": {"adapter": "claude-code"},
                "pipeline": {
                    "agents": ["analyst", "coder"],
                    "steps": [
                        {"name": "analyze", "skill": "requirement-analysis"},
                        {"name": "implement", "skill": "code-generation", "condition": "complexity == 'high'"},
                    ],
                },
                "hooks": {},
                "gates": {"default_mode": "hybrid"},
            }
            profiles_dir = self._create_profile_dir(tmpdir, "with-workflow", content)
            loader = ProfileLoader(profiles_dir)
            profile = loader.load("with-workflow")

            assert profile.workflow is not None
            assert len(profile.workflow.steps) == 2
            assert profile.workflow.steps[0].name == "analyze"
            assert profile.workflow.steps[1].condition == "complexity == 'high'"

    def test_save_and_reload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = ProfileLoader(tmpdir)
            profile = ProfileConfig(
                name="custom",
                description="自定义 Profile",
                default_agent="claude-code",
                hooks={"session_start": [{"type": "script", "command": "echo test"}]},
            )
            loader.save(profile)

            # 重新加载
            loaded = loader.load("custom")
            assert loaded.name == "custom"
            assert loaded.description == "自定义 Profile"
            assert "session_start" in loaded.hooks

    def test_gate_mode_parsing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for mode_str, expected in [("strict", GateMode.STRICT), ("hybrid", GateMode.HYBRID), ("loose", GateMode.LOOSE)]:
                content = {
                    "profile": {"name": mode_str},
                    "hooks": {},
                    "gates": {"default_mode": mode_str},
                }
                profiles_dir = self._create_profile_dir(tmpdir, mode_str, content)
                loader = ProfileLoader(profiles_dir)
                profile = loader.load(mode_str)
                assert profile.default_gate_mode == expected

    def test_skill_slots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            content = {
                "profile": {"name": "with-slots"},
                "hooks": {},
                "skill_slots": {
                    "coder": {"post_execute": ["custom-lint"]},
                },
                "gates": {"default_mode": "hybrid"},
            }
            profiles_dir = self._create_profile_dir(tmpdir, "with-slots", content)
            loader = ProfileLoader(profiles_dir)
            profile = loader.load("with-slots")
            assert profile.skill_slots == {"coder": {"post_execute": ["custom-lint"]}}


class TestBuiltinProfilesDir:
    """builtin_profiles_dir() 定位测试"""

    def test_builtin_profiles_dir_found(self):
        """验证 builtin_profiles_dir() 能定位到 packages/core/harness/profiles/"""
        builtin_dir = builtin_profiles_dir()
        # 在源码 clone 场景下，应该能找到
        assert builtin_dir is not None
        assert builtin_dir.exists()
        assert (builtin_dir / "default.yaml").exists()

    def test_builtin_profiles_dir_contains_all_presets(self):
        """验证内置 profiles 包含所有预设"""
        builtin_dir = builtin_profiles_dir()
        if builtin_dir is None:
            pytest.skip("内置 profiles 目录不存在（非源码 clone 场景）")

        expected_profiles = ["default", "basic", "frontend", "backend", "product", "enterprise", "ui"]
        for name in expected_profiles:
            assert (builtin_dir / f"{name}.yaml").exists(), f"缺少内置 profile: {name}.yaml"



class TestLayeredProfileLookup:
    """分层查找测试：项目级优先 → 内置兜底"""

    def _create_builtin_dir(self, tmpdir):
        """辅助：模拟内置 profiles 目录"""
        builtin_dir = Path(tmpdir) / "builtin_profiles"
        builtin_dir.mkdir(parents=True, exist_ok=True)

        # 创建内置 default profile
        default_content = {
            "profile": {"name": "default", "description": "内置默认 Profile"},
            "agent": {"adapter": "claude-code"},
            "hooks": {},
            "gates": {"default_mode": "hybrid"},
        }
        (builtin_dir / "default.yaml").write_text(
            yaml.dump(default_content, allow_unicode=True), encoding="utf-8")

        return builtin_dir

    def _create_project_dir(self, tmpdir):
        """辅助：创建项目级 .harness/profiles/ 目录"""
        project_profiles = Path(tmpdir) / "project" / ".harness" / "profiles"
        project_profiles.mkdir(parents=True, exist_ok=True)
        return project_profiles

    def test_builtin_fallback_when_project_empty(self):
        """项目级 .harness/profiles/ 为空时，从内置加载"""
        with tempfile.TemporaryDirectory() as tmpdir:
            builtin_dir = self._create_builtin_dir(tmpdir)
            project_profiles = self._create_project_dir(tmpdir)

            loader = ProfileLoader(str(project_profiles))
            # 手动注入内置目录（模拟 builtin_profiles_dir 的返回值）
            loader._builtin_profiles_dir = builtin_dir

            profile = loader.load("default")
            assert profile.name == "default"
            assert profile.description == "内置默认 Profile"

    def test_project_overrides_builtin(self):
        """项目级同名 profile 覆盖内置"""
        with tempfile.TemporaryDirectory() as tmpdir:
            builtin_dir = self._create_builtin_dir(tmpdir)
            project_profiles = self._create_project_dir(tmpdir)

            # 项目级 default.yaml——描述不同，证明来自项目级
            project_default = {
                "profile": {"name": "default", "description": "项目自定义默认"},
                "agent": {"adapter": "claude-code"},
                "hooks": {},
                "gates": {"default_mode": "loose"},
            }
            (project_profiles / "default.yaml").write_text(
                yaml.dump(project_default, allow_unicode=True), encoding="utf-8")

            loader = ProfileLoader(str(project_profiles))
            loader._builtin_profiles_dir = builtin_dir

            profile = loader.load("default")
            assert profile.name == "default"
            # 项目级覆盖了内置——描述和 gate mode 不同
            assert profile.description == "项目自定义默认"
            assert profile.default_gate_mode == GateMode.LOOSE

    def test_list_profiles_merges_builtin_and_project(self):
        """list_profiles() 合并两层目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            builtin_dir = self._create_builtin_dir(tmpdir)
            project_profiles = self._create_project_dir(tmpdir)

            # 项目级有一个自定义 profile（不在内置中）
            custom_content = {
                "profile": {"name": "my-custom", "description": "项目特有"},
                "hooks": {},
                "gates": {"default_mode": "hybrid"},
            }
            (project_profiles / "my-custom.yaml").write_text(
                yaml.dump(custom_content, allow_unicode=True), encoding="utf-8")

            loader = ProfileLoader(str(project_profiles))
            loader._builtin_profiles_dir = builtin_dir

            profiles = loader.list_profiles()
            # 包含内置的 default + 项目级的 default 和 my-custom
            assert "default" in profiles
            assert "my-custom" in profiles



class TestReadEnvVar:
    """_read_env_var() 和 resolve_active 读取 .harness/env 测试"""

    def _create_harness_env(self, tmpdir, entries: dict):
        """辅助：在 tmpdir 下创建 .harness/env 文件"""
        harness_dir = Path(tmpdir) / ".harness"
        harness_dir.mkdir(parents=True, exist_ok=True)
        content = "\n".join(f"{k}={v}" for k, v in entries.items())
        (harness_dir / "env").write_text(content, encoding="utf-8")
        return harness_dir

    def test_read_env_var_basic(self):
        """_read_env_var 正确读取 KEY=VALUE"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = self._create_harness_env(tmpdir, {
                "HARNESS_COOK_ROOT": "/path/to/harness",
                "HARNESS_PROFILE": "frontend",
            })
            loader = ProfileLoader(str(harness_dir / "profiles"))
            assert loader._read_env_var("HARNESS_COOK_ROOT") == "/path/to/harness"
            assert loader._read_env_var("HARNESS_PROFILE") == "frontend"

    def test_read_env_var_missing_key(self):
        """_read_env_var 对不存在 key 返回 None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = self._create_harness_env(tmpdir, {
                "HARNESS_PROFILE": "backend",
            })
            loader = ProfileLoader(str(harness_dir / "profiles"))
            assert loader._read_env_var("HARNESS_COOK_ROOT") is None

    def test_read_env_var_empty_file(self):
        """_read_env_var 对空 env 文件返回 None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            harness_dir.mkdir(parents=True, exist_ok=True)
            (harness_dir / "env").write_text("", encoding="utf-8")
            loader = ProfileLoader(str(harness_dir / "profiles"))
            assert loader._read_env_var("HARNESS_PROFILE") is None

    def test_read_env_var_no_env_file(self):
        """_read_env_var 对不存在 env 文件返回 None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            harness_dir.mkdir(parents=True, exist_ok=True)
            loader = ProfileLoader(str(harness_dir / "profiles"))
            assert loader._read_env_var("HARNESS_PROFILE") is None

    def test_read_env_var_empty_value(self):
        """_read_env_var 对 KEY=（空值）返回 None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = self._create_harness_env(tmpdir, {
                "HARNESS_PROFILE": "",
            })
            loader = ProfileLoader(str(harness_dir / "profiles"))
            assert loader._read_env_var("HARNESS_PROFILE") is None

    def test_resolve_active_reads_env_file(self):
        """resolve_active() 从 .harness/env 读取 HARNESS_PROFILE"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = self._create_harness_env(tmpdir, {
                "HARNESS_PROFILE": "frontend",
            })
            # 确保 frontend profile 在内置目录存在（分层查找兜底）
            loader = ProfileLoader(str(harness_dir / "profiles"))
            profile = loader.resolve_active()
            assert profile == "frontend"


    def test_resolve_active_os_env_overrides_env_file(self):
        """OS 环境变量优先级高于 .harness/env 文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = self._create_harness_env(tmpdir, {
                "HARNESS_PROFILE": "frontend",
            })
            loader = ProfileLoader(str(harness_dir / "profiles"))
            # OS 环境变量优先
            os.environ["HARNESS_PROFILE"] = "backend"
            try:
                profile = loader.resolve_active()
                assert profile == "backend"
            finally:
                del os.environ["HARNESS_PROFILE"]

    def test_resolve_active_env_file_overrides_marker(self):
        """.harness/env 文件优先级高于标记文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = self._create_harness_env(tmpdir, {
                "HARNESS_PROFILE": "frontend",
            })
            # 标记文件写 basic
            (harness_dir / "active_profile").write_text("basic", encoding="utf-8")
            loader = ProfileLoader(str(harness_dir / "profiles"))
            # env 文件优先于标记文件
            profile = loader.resolve_active()
            assert profile == "frontend"


    def test_read_env_var_skips_comment_lines(self):
        """_read_env_var 跳过 # 注释行"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            harness_dir.mkdir(parents=True, exist_ok=True)
            env_content = "# harness-cook 运行时配置\nHARNESS_PROFILE=frontend\n# 这是注释\n"
            (harness_dir / "env").write_text(env_content, encoding="utf-8")
            loader = ProfileLoader(str(harness_dir / "profiles"))
            assert loader._read_env_var("HARNESS_PROFILE") == "frontend"

    def test_read_env_var_strips_inline_comment(self):
        """_read_env_var 去掉行尾 # 注释"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            harness_dir.mkdir(parents=True, exist_ok=True)
            env_content = "HARNESS_PROFILE=frontend  # 仅初始化时生效\n"
            (harness_dir / "env").write_text(env_content, encoding="utf-8")
            loader = ProfileLoader(str(harness_dir / "profiles"))
            assert loader._read_env_var("HARNESS_PROFILE") == "frontend"

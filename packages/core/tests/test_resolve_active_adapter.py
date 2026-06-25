"""
resolve_active_adapter 测试

测试覆盖：
- 优先级链：HARNESS_ADAPTER env > .harness/env > .harness/active_adapter marker > profile_adapter > claude-code
- 环境变量覆盖（最高优先级）
- .harness/env 文件读取（含注释和行尾注释）
- 标记文件读取
- Profile adapter 字段回退
- 最终回退到 claude-code
- 无效 adapter 名称的处理（降级到下一层）
- write_adapter_marker 写入
- write_adapter_marker 拒绝无效 adapter
"""

import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from harness.config import (
    resolve_active_adapter,
    write_adapter_marker,
    _read_adapter_marker,
    _read_adapter_from_env_file,
    _BUILTIN_ADAPTERS,
    _get_valid_adapters,
    _DEFAULT_ADAPTER,
)


class TestResolveActiveAdapter:
    """resolve_active_adapter 优先级链测试"""

    def test_default_fallback(self):
        """无任何配置时，回退到 claude-code"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            with patch.dict(os.environ, {}, clear=True):
                result = resolve_active_adapter(harness_dir=harness_dir)
            assert result == "claude-code"

    def test_env_var_highest_priority(self):
        """HARNESS_ADAPTER 环境变量优先级最高"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            # 同时设置 env、env file、marker、profile——env 应胜出
            harness_dir.mkdir(parents=True, exist_ok=True)
            (harness_dir / "env").write_text("HARNESS_ADAPTER=cursor\n")
            (harness_dir / "active_adapter").write_text("hermes")
            with patch.dict(os.environ, {"HARNESS_ADAPTER": "hermes"}, clear=False):
                result = resolve_active_adapter(
                    harness_dir=harness_dir,
                    profile_adapter="openai",
                )
            assert result == "hermes"

    def test_env_file_second_priority(self):
        """.harness/env 文件是第二优先级"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            harness_dir.mkdir(parents=True, exist_ok=True)
            (harness_dir / "env").write_text(
                "# harness config\n"
                "HARNESS_ADAPTER=hermes  # 用 Hermes 部署\n"
            )
            # 同时设置 marker 和 profile——env file 应胜出
            (harness_dir / "active_adapter").write_text("cursor")
            with patch.dict(os.environ, {}, clear=True):
                result = resolve_active_adapter(
                    harness_dir=harness_dir,
                    profile_adapter="openai",
                )
            assert result == "hermes"

    def test_marker_third_priority(self):
        """标记文件是第三优先级"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            harness_dir.mkdir(parents=True, exist_ok=True)
            (harness_dir / "active_adapter").write_text("cursor")
            with patch.dict(os.environ, {}, clear=True):
                result = resolve_active_adapter(
                    harness_dir=harness_dir,
                    profile_adapter="openai",
                )
            assert result == "cursor"

    def test_profile_adapter_fourth_priority(self):
        """Profile adapter 字段是第四优先级"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            # 无 env、无 env file、无 marker
            with patch.dict(os.environ, {}, clear=True):
                result = resolve_active_adapter(
                    harness_dir=harness_dir,
                    profile_adapter="hermes",
                )
            assert result == "hermes"

    def test_invalid_env_var_falls_through(self):
        """无效的环境变量值降级到下一层"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            harness_dir.mkdir(parents=True, exist_ok=True)
            (harness_dir / "active_adapter").write_text("hermes")
            with patch.dict(os.environ, {"HARNESS_ADAPTER": "invalid-adapter"}, clear=False):
                result = resolve_active_adapter(harness_dir=harness_dir)
            assert result == "hermes"  # 降级到 marker

    def test_invalid_marker_falls_through(self):
        """无效的标记文件内容降级到下一层"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            harness_dir.mkdir(parents=True, exist_ok=True)
            (harness_dir / "active_adapter").write_text("unknown-adapter")
            with patch.dict(os.environ, {}, clear=True):
                result = resolve_active_adapter(
                    harness_dir=harness_dir,
                    profile_adapter="hermes",
                )
            assert result == "hermes"  # 降级到 profile adapter

    def test_invalid_everything_falls_to_default(self):
        """所有层都无效时，回退到 claude-code"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            harness_dir.mkdir(parents=True, exist_ok=True)
            (harness_dir / "active_adapter").write_text("bad")
            with patch.dict(os.environ, {"HARNESS_ADAPTER": "also-bad"}, clear=False):
                result = resolve_active_adapter(
                    harness_dir=harness_dir,
                    profile_adapter="also-bad",
                )
            assert result == "claude-code"


class TestReadAdapterMarker:
    """标记文件读取测试"""

    def test_read_existing_marker(self):
        """读取存在的标记文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            harness_dir.mkdir(parents=True, exist_ok=True)
            (harness_dir / "active_adapter").write_text("hermes")
            result = _read_adapter_marker(harness_dir)
            assert result == "hermes"

    def test_read_missing_marker(self):
        """标记文件不存在时返回 None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            result = _read_adapter_marker(harness_dir)
            assert result is None

    def test_read_empty_marker(self):
        """标记文件为空时返回 None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            harness_dir.mkdir(parents=True, exist_ok=True)
            (harness_dir / "active_adapter").write_text("")
            result = _read_adapter_marker(harness_dir)
            assert result is None


class TestReadAdapterFromEnvFile:
    """env 文件读取测试"""

    def test_read_adapter_from_env(self):
        """从 .harness/env 读取 HARNESS_ADAPTER"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            harness_dir.mkdir(parents=True, exist_ok=True)
            (harness_dir / "env").write_text(
                "# harness-cook config\n"
                "HARNESS_ADAPTER=hermes  # Hermes 部署\n"
                "HARNESS_PROFILE=default\n"
            )
            result = _read_adapter_from_env_file(harness_dir)
            assert result == "hermes"

    def test_env_file_no_adapter(self):
        """env 文件没有 HARNESS_ADAPTER 行时返回 None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            harness_dir.mkdir(parents=True, exist_ok=True)
            (harness_dir / "env").write_text(
                "HARNESS_PROFILE=default\n"
                "HARNESS_COOK_ROOT=/path\n"
            )
            result = _read_adapter_from_env_file(harness_dir)
            assert result is None

    def test_env_file_missing(self):
        """env 文件不存在时返回 None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            result = _read_adapter_from_env_file(harness_dir)
            assert result is None


class TestWriteAdapterMarker:
    """标记文件写入测试"""

    def test_write_valid_adapter(self):
        """写入有效 adapter 名称"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            write_adapter_marker(harness_dir, "hermes")
            content = (harness_dir / "active_adapter").read_text()
            assert content == "hermes"

    def test_write_creates_harness_dir(self):
        """自动创建 .harness/ 目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            assert not harness_dir.exists()
            write_adapter_marker(harness_dir, "hermes")
            assert harness_dir.is_dir()

    def test_write_rejects_invalid_adapter(self):
        """拒绝无效 adapter 名称"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            with pytest.raises(ValueError, match="not valid"):
                write_adapter_marker(harness_dir, "invalid-adapter")

    def test_overwrite_existing_marker(self):
        """覆盖已有的标记文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            harness_dir.mkdir(parents=True, exist_ok=True)
            (harness_dir / "active_adapter").write_text("claude-code")
            write_adapter_marker(harness_dir, "hermes")
            content = (harness_dir / "active_adapter").read_text()
            assert content == "hermes"


class TestValidAdapters:
    """有效适配器列表测试"""

    def test_all_expected_adapters_valid(self):
        """所有预期适配器名称都有效"""
        expected = ["claude-code", "copilot-cli", "hermes", "cursor", "openai"]
        valid = _get_valid_adapters()
        for name in expected:
            assert name in valid

    def test_default_adapter_is_valid(self):
        """默认适配器是有效列表中的成员"""
        valid = _get_valid_adapters()
        assert _DEFAULT_ADAPTER in valid
        assert _DEFAULT_ADAPTER == "claude-code"

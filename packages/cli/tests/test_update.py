"""
harness update 命令测试

验证 update.py 的核心逻辑：
- 源码目录定位 (_get_harness_root)
- 工作区检查 (_check_uncommitted_changes)
- 分支获取 (_get_current_branch)
- git pull (_git_pull)
- pip install (_pip_install)
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 设置导入路径
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent)
CORE_PATH = str(Path(PROJECT_ROOT) / "packages" / "core")
CLI_COMMANDS_PATH = str(Path(PROJECT_ROOT) / "packages" / "cli" / "cli_commands")
sys.path.insert(0, CORE_PATH)
sys.path.insert(0, CLI_COMMANDS_PATH)


class TestGetHarnessRoot:
    """_get_harness_root 测试"""

    def test_env_variable_priority(self):
        """HARNESS_COOK_ROOT 环变量优先"""
        from update import _get_harness_root
        with tempfile.TemporaryDirectory() as tmp:
            # 创建 packages/core 子目录让校验通过
            os.makedirs(Path(tmp) / "packages" / "core")
            with patch.dict(os.environ, {"HARNESS_COOK_ROOT": tmp}):
                assert _get_harness_root() == tmp

    def test_path_inference_fallback(self):
        """无环境变量时从脚本位置推导"""
        from update import _get_harness_root
        # 不设置 HARNESS_COOK_ROOT 环变量，推导应返回脚本位置推导的路径
        env = os.environ.copy()
        env.pop("HARNESS_COOK_ROOT", None)
        with patch.dict(os.environ, env, clear=True):
            result = _get_harness_root()
            # 结果应该是一个有效路径（包含 harness-cook）
            assert "harness-cook" in result


class TestCheckUncommittedChanges:
    """_check_uncommitted_changes 测试"""

    def test_clean_workdir(self):
        """干净工作区返回空列表"""
        from update import _check_uncommitted_changes
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init"], cwd=tmp, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, capture_output=True)
            Path(tmp, "test.txt").write_text("hello")
            subprocess.run(["git", "add", "."], cwd=tmp, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, capture_output=True)
            result = _check_uncommitted_changes(tmp)
            assert result == []

    def test_dirty_workdir(self):
        """有修改的工作区返回文件列表"""
        from update import _check_uncommitted_changes
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init"], cwd=tmp, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, capture_output=True)
            Path(tmp, "test.txt").write_text("hello")
            subprocess.run(["git", "add", "."], cwd=tmp, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, capture_output=True)
            # 修改文件（不提交）
            Path(tmp, "test.txt").write_text("modified")
            result = _check_uncommitted_changes(tmp)
            assert result is not None
            assert len(result) > 0
            assert "test.txt" in result

    def test_non_git_directory(self):
        """非 git 目录返回 None"""
        from update import _check_uncommitted_changes
        with tempfile.TemporaryDirectory() as tmp:
            # 不初始化 git 仓库
            result = _check_uncommitted_changes(tmp)
            assert result is None


class TestGetCurrentBranch:
    """_get_current_branch 测试"""

    def test_returns_branch_name(self):
        """返回当前分支名"""
        from update import _get_current_branch
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init"], cwd=tmp, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, capture_output=True)
            Path(tmp, "test.txt").write_text("hello")
            subprocess.run(["git", "add", "."], cwd=tmp, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, capture_output=True)
            result = _get_current_branch(tmp)
            # 默认分支可能是 main 或 master
            assert result in ("main", "master")


class TestGitPull:
    """_git_pull 测试"""

    def test_pull_success_with_changes(self):
        """模拟 git pull 成功且有变化"""
        from update import _git_pull
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Fast-forward\n  3 files changed"
        mock_result.stderr = ""

        with patch("update.subprocess.run", return_value=mock_result):
            success, has_changes = _git_pull("/fake/path", "v2", False)
            assert success is True
            assert has_changes is True

    def test_pull_success_no_changes(self):
        """模拟 git pull 成功但无变化"""
        from update import _git_pull
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Already up to date."
        mock_result.stderr = ""

        with patch("update.subprocess.run", return_value=mock_result):
            success, has_changes = _git_pull("/fake/path", "v2", False)
            assert success is True
            assert has_changes is False

    def test_pull_failure(self):
        """模拟 git pull 失败"""
        from update import _git_pull
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error: cannot connect to origin"

        with patch("update.subprocess.run", return_value=mock_result):
            success, has_changes = _git_pull("/fake/path", "v2", False)
            assert success is False
            assert has_changes is False


class TestPipInstall:
    """_pip_install 测试"""

    def test_install_success(self):
        """模拟 pip install 成功"""
        from update import _pip_install
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Successfully installed harness-cook"
        mock_result.stderr = ""

        with patch("update.subprocess.run", return_value=mock_result):
            result = _pip_install("/fake/path", False)
            assert result is True

    def test_core_install_failure(self):
        """模拟核心包安装失败"""
        from update import _pip_install
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error: package not found"

        with patch("update.subprocess.run", return_value=mock_result):
            result = _pip_install("/fake/path", False)
            assert result is False

    def test_cli_install_failure(self):
        """模拟核心包成功但 CLI 包失败"""
        from update import _pip_install
        success_result = MagicMock()
        success_result.returncode = 0
        success_result.stdout = "Successfully installed"
        success_result.stderr = ""

        fail_result = MagicMock()
        fail_result.returncode = 1
        fail_result.stdout = ""
        fail_result.stderr = "error: CLI package not found"

        with patch("update.subprocess.run", side_effect=[success_result, fail_result]):
            result = _pip_install("/fake/path", False)
            assert result is False

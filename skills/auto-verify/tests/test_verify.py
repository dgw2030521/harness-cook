"""
auto-verify Skill 可执行脚本测试

用 subprocess 执行脚本，验证基本功能。
使用临时 git 仓库，避免对项目目录做全量扫描导致超时。
"""

import json
import subprocess
import sys
import os
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent)
SCRIPT_PATH = str(Path(PROJECT_ROOT) / "skills" / "auto-verify" / "verify.py")


@pytest.fixture
def empty_git_repo():
    """创建一个空的临时 git 仓库，避免对项目目录做全量扫描"""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["git", "init"], cwd=tmp, capture_output=True, timeout=5)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp, capture_output=True, timeout=5)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, capture_output=True, timeout=5)
        # 创建并提交一个文件，使 HEAD 存在
        readme = Path(tmp) / "README.md"
        readme.write_text("# test project")
        subprocess.run(["git", "add", "."], cwd=tmp, capture_output=True, timeout=5)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, timeout=5)
        yield tmp


def _run_verify(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """执行 verify.py"""
    return subprocess.run(
        [sys.executable, SCRIPT_PATH] + args,
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "CLAUDE_PROJECT_DIR": PROJECT_ROOT,
             "PYTHONPATH": str(Path(PROJECT_ROOT) / "packages" / "core")},
    )


class TestVerifyScript:

    def test_no_changes_json_output(self, empty_git_repo):
        """无变更文件 → JSON 输出包含 status 字段"""
        result = _run_verify(["--path", empty_git_repo, "--output", "json"])
        output = json.loads(result.stdout)
        assert "status" in output
        assert output["status"] in ("no_changes", "PASS", "FAIL")

    def test_no_changes_table_output(self, empty_git_repo):
        """无变更文件 → 表格输出"""
        result = _run_verify(["--path", empty_git_repo, "--output", "table"])
        assert result.returncode in (0, 1)
        assert "harness auto-verify" in result.stdout or "无变更" in result.stdout

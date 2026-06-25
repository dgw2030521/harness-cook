"""
auto-review Skill 可执行脚本测试

用 subprocess 执行脚本，验证基本功能。
"""

import json
import subprocess
import sys
import os
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent)
SCRIPT_PATH = str(Path(PROJECT_ROOT) / "skills" / "auto-review" / "review_gate.py")


def _run_review(args: list[str]) -> subprocess.CompletedProcess:
    """执行 review_gate.py"""
    return subprocess.run(
        [sys.executable, SCRIPT_PATH] + args,
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "CLAUDE_PROJECT_DIR": PROJECT_ROOT},
    )


class TestReviewGateScript:

    def test_no_changes_json_output(self):
        """无变更文件 → JSON 输出 gate_passed=True"""
        result = _run_review(["--path", PROJECT_ROOT, "--output", "json"])
        output = json.loads(result.stdout)
        assert "gate_passed" in output
        assert result.returncode == 0

    def test_no_changes_table_output(self):
        """无变更文件 → 表格输出有通过提示"""
        result = _run_review(["--path", PROJECT_ROOT, "--output", "table"])
        assert result.returncode == 0
        assert "通过" in result.stdout
"""
auto-audit Skill 可执行脚本测试

用 subprocess 执行脚本，验证基本功能。
"""

import json
import subprocess
import sys
import os
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent)
SCRIPT_PATH = str(Path(PROJECT_ROOT) / "skills" / "auto-audit" / "audit_report.py")


def _run_audit(args: list[str]) -> subprocess.CompletedProcess:
    """执行 audit_report.py"""
    return subprocess.run(
        [sys.executable, SCRIPT_PATH] + args,
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "CLAUDE_PROJECT_DIR": PROJECT_ROOT},
    )


class TestAuditReportScript:

    def test_json_output_has_count(self):
        """JSON 输出包含 count 字段"""
        result = _run_audit(["--output", "json"])
        output = json.loads(result.stdout)
        assert "count" in output
        assert result.returncode == 0

    def test_table_output_contains_text(self):
        """表格输出包含审计相关文字"""
        result = _run_audit(["--output", "table"])
        assert result.returncode == 0
        assert "审计" in result.stdout

    def test_detail_output_format(self):
        """detail 输出格式"""
        result = _run_audit(["--output", "detail"])
        assert result.returncode == 0
        assert "审计" in result.stdout
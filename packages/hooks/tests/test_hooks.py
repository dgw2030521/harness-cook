"""
Hook 脚本单元测试 — 用 subprocess 执行脚本，验证 stdin→stdout JSON

测试方法：构造 stdin JSON → 执行 hook 脚本 → 解析 stdout JSON → 验证格式。
所有 hook 必须：1) 输出 JSON；2) 包含 continue=True；3) 异常时不阻断。
"""

import json
import subprocess
import sys
import os
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent)  # packages/hooks/tests → 项目根
SCRIPTS_DIR = str(Path(PROJECT_ROOT) / "packages" / "hooks")


def _run_hook(script_name: str, input_data: dict) -> dict:
    """执行 hook 脚本，返回 stdout JSON"""
    script_path = os.path.join(SCRIPTS_DIR, script_name)
    result = subprocess.run(
        [sys.executable, script_path],
        input=json.dumps(input_data),
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "CLAUDE_PROJECT_DIR": PROJECT_ROOT},
    )
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return {"raw_stdout": result.stdout, "raw_stderr": result.stderr, "returncode": result.returncode}


class TestComplianceScanHook:
    """hook-compliance-scan.py 测试"""

    def test_no_file_path_returns_continue(self):
        """无 file_path → continue=True"""
        output = _run_hook("hook-compliance-scan.py", {"tool_name": "Write", "tool_input": {}})
        assert output.get("continue") is True

    def test_nonexistent_file_returns_continue(self):
        """文件不存在 → continue=True"""
        output = _run_hook("hook-compliance-scan.py", {"tool_name": "Write", "tool_input": {"file_path": "/nonexistent/file.py"}})
        assert output.get("continue") is True

    def test_invalid_json_returns_continue(self):
        """stdin JSON 解析失败 → continue=True"""
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "hook-compliance-scan.py")],
            input="invalid json",
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "CLAUDE_PROJECT_DIR": PROJECT_ROOT},
        )
        output = json.loads(result.stdout.strip())
        assert output.get("continue") is True


class TestGuardrailsPIIHook:
    """hook-guardrails-pii.py 测试"""

    def test_no_tool_result_returns_continue(self):
        """空 tool_result → continue=True"""
        output = _run_hook("hook-guardrails-pii.py", {"tool_name": "Bash", "tool_result": ""})
        assert output.get("continue") is True

    def test_clean_output_returns_continue(self):
        """无 PII 的 Bash 输出 → continue=True"""
        output = _run_hook("hook-guardrails-pii.py", {"tool_name": "Bash", "tool_result": "ls -la\nfile1.txt"})
        assert output.get("continue") is True

    def test_invalid_json_returns_continue(self):
        """stdin JSON 解析失败 → continue=True"""
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "hook-guardrails-pii.py")],
            input="invalid",
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "CLAUDE_PROJECT_DIR": PROJECT_ROOT},
        )
        output = json.loads(result.stdout.strip())
        assert output.get("continue") is True


class TestPromptGuardrailsHook:
    """hook-prompt-guardrails.py 测试"""

    def test_empty_prompt_returns_continue(self):
        """空 prompt → continue=True"""
        output = _run_hook("hook-prompt-guardrails.py", {"user_prompt": ""})
        assert output.get("continue") is True

    def test_clean_prompt_returns_continue(self):
        """无 PII 的 prompt → continue=True"""
        output = _run_hook("hook-prompt-guardrails.py", {"user_prompt": "帮我写一个排序函数"})
        assert output.get("continue") is True


class TestSessionInitHook:
    """hook-session-init.py 测试"""

    def test_returns_continue(self):
        """正常启动 → continue=True"""
        output = _run_hook("hook-session-init.py", {"session_id": "test-session"})
        assert output.get("continue") is True


class TestTaskAuditHook:
    """hook-task-audit.py 测试"""

    def test_returns_continue(self):
        """正常停止 → continue=True"""
        output = _run_hook("hook-task-audit.py", {"session_id": "test-session"})
        assert output.get("continue") is True
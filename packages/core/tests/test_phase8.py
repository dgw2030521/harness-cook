"""
Phase 8 测试: Hermes 桥接 skill 和 bridge.py 脚本

测试覆盖:
- bridge.py 各子命令执行 (通过 subprocess)
- SKILL.md 格式正确性 (YAML frontmatter 可解析)
- 符号链接存在性验证
- bridge.py PYTHONPATH 设置正确性
"""

from __future__ import annotations

import subprocess
import pytest
import sys
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False
from pathlib import Path

# ─── 路径常量 ──────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SKILL_DIR = PROJECT_ROOT / "skills" / "harness-bridge"
SKILL_MD = SKILL_DIR / "SKILL.md"
BRIDGE_PY = SKILL_DIR / "bridge.py"

HERMES_SKILL_LINK = Path.home() / ".hermes" / "skills" / "harness-bridge"
CLAUDE_SKILL_LINK = Path.home() / ".claude" / "skills" / "harness-bridge"

PYTHON_EXEC = sys.executable


# ═══════════════════════════════════════════════════════════
#  SKILL.md 格式测试
# ═══════════════════════════════════════════════════════════

class TestSkillMDFormat:
    """SKILL.md YAML frontmatter + markdown body 格式验证"""

    def test_skill_md_exists(self):
        """SKILL.md 文件应存在"""
        assert SKILL_MD.exists(), f"SKILL.md not found at {SKILL_MD}"

    def test_skill_md_readable(self):
        """SKILL.md 应可读取"""
        content = SKILL_MD.read_text(encoding="utf-8")
        assert len(content) > 0, "SKILL.md is empty"

    def test_yaml_frontmatter_delimiters(self):
        """SKILL.md 应有 YAML frontmatter (---开头和结尾)"""
        content = SKILL_MD.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        assert lines[0] == "---", "SKILL.md should start with ---"
        # 找到第二个 ---
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i] == "---":
                end_idx = i
                break
        assert end_idx is not None, "SKILL.md should have closing ---"

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_yaml_frontmatter_parseable(self):
        """YAML frontmatter 应可解析"""
        content = SKILL_MD.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i] == "---":
                end_idx = i
                break
        frontmatter_text = "\n".join(lines[1:end_idx])
        frontmatter = yaml.safe_load(frontmatter_text)
        assert isinstance(frontmatter, dict), "Frontmatter should be a dict"

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_frontmatter_required_fields(self):
        """Frontmatter 应包含 name, description, version, trigger"""
        content = SKILL_MD.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i] == "---":
                end_idx = i
                break
        frontmatter_text = "\n".join(lines[1:end_idx])
        frontmatter = yaml.safe_load(frontmatter_text)

        assert "name" in frontmatter, "Frontmatter missing 'name'"
        assert "description" in frontmatter, "Frontmatter missing 'description'"
        assert "version" in frontmatter, "Frontmatter missing 'version'"
        assert "trigger" in frontmatter, "Frontmatter missing 'trigger'"

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_frontmatter_name_value(self):
        """Frontmatter name 应为 harness-bridge"""
        content = SKILL_MD.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i] == "---":
                end_idx = i
                break
        frontmatter = yaml.safe_load("\n".join(lines[1:end_idx]))
        assert frontmatter["name"] == "harness-bridge"

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_frontmatter_version_format(self):
        """Frontmatter version 应为 1.0.0"""
        content = SKILL_MD.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i] == "---":
                end_idx = i
                break
        frontmatter = yaml.safe_load("\n".join(lines[1:end_idx]))
        assert frontmatter["version"] == "1.0.0"

    def test_markdown_body_has_command_usage(self):
        """Markdown body 应包含命令用法章节"""
        content = SKILL_MD.read_text(encoding="utf-8")
        # 在 frontmatter 之后的内容
        lines = content.strip().split("\n")
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i] == "---":
                end_idx = i
                break
        body = "\n".join(lines[end_idx + 1:])
        assert "命令用法" in body or "Command" in body.lower() or "`harness" in body

    def test_markdown_body_has_pitfalls(self):
        """Markdown body 应包含 Pitfalls 章节"""
        content = SKILL_MD.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i] == "---":
                end_idx = i
                break
        body = "\n".join(lines[end_idx + 1:])
        assert "Pitfalls" in body or "PYTHONPATH" in body


# ═══════════════════════════════════════════════════════════
#  bridge.py 基本验证测试
# ═══════════════════════════════════════════════════════════

class TestBridgePyBasic:
    """bridge.py 脚本基本验证"""

    def test_bridge_py_exists(self):
        """bridge.py 文件应存在"""
        assert BRIDGE_PY.exists(), f"bridge.py not found at {BRIDGE_PY}"

    def test_bridge_py_readable(self):
        """bridge.py 应可读取"""
        content = BRIDGE_PY.read_text(encoding="utf-8")
        assert len(content) > 0, "bridge.py is empty"

    def test_bridge_py_python_syntax(self):
        """bridge.py 应为合法 Python 语法"""
        content = BRIDGE_PY.read_text(encoding="utf-8")
        compile(content, str(BRIDGE_PY), "exec")  # 语法检查

    def test_bridge_py_has_subcommands(self):
        """bridge.py 应定义所有子命令函数"""
        content = BRIDGE_PY.read_text(encoding="utf-8")
        for cmd in ["cmd_check", "cmd_audit", "cmd_run", "cmd_plan", "cmd_status", "cmd_version"]:
            assert cmd in content, f"bridge.py missing function {cmd}"

    def test_bridge_py_has_argparse(self):
        """bridge.py 应使用 argparse"""
        content = BRIDGE_PY.read_text(encoding="utf-8")
        assert "argparse" in content
        assert "ArgumentParser" in content
        assert "add_subparsers" in content

    def test_bridge_py_has_pythonpath_setup(self):
        """bridge.py 应设置 PYTHONPATH"""
        content = BRIDGE_PY.read_text(encoding="utf-8")
        assert "HARNESS_CORE" in content
        assert "sys.path.insert" in content or "sys.path" in content
        assert "packages/core" in content or "packages" in content


# ═══════════════════════════════════════════════════════════
#  bridge.py 子命令执行测试
# ═══════════════════════════════════════════════════════════

class TestBridgePyVersion:
    """bridge.py version 子命令测试"""

    def test_version_command(self):
        """python bridge.py version 应输出版本号"""
        result = subprocess.run(
            [PYTHON_EXEC, str(BRIDGE_PY), "version"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=10,
        )
        assert result.returncode == 0, f"version failed: {result.stderr}"
        assert "0.1.0" in result.stdout, f"Expected version in output: {result.stdout}"


class TestBridgePyStatus:
    """bridge.py status 子命令测试"""

    def test_status_command(self):
        """python bridge.py status 应输出状态信息"""
        result = subprocess.run(
            [PYTHON_EXEC, str(BRIDGE_PY), "status"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=10,
        )
        assert result.returncode == 0, f"status failed: {result.stderr}"
        # 应包含关键状态信息
        assert "Agent" in result.stdout or "agent" in result.stdout.lower()
        assert "规则" in result.stdout or "rule" in result.stdout.lower() or "pack" in result.stdout.lower()

    def test_status_shows_version(self):
        """status 命令应显示版本号"""
        result = subprocess.run(
            [PYTHON_EXEC, str(BRIDGE_PY), "status"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=10,
        )
        assert "0.1.0" in result.stdout


class TestBridgePyCheck:
    """bridge.py check 子命令测试"""

    def test_check_clean_file(self):
        """check 命令扫描干净文件应通过"""
        # 创建临时干净文件
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, dir=str(PROJECT_ROOT)) as f:
            f.write("def hello():\n    return 'world'\n")
            tmp_path = f.name

        try:
            result = subprocess.run(
                [PYTHON_EXEC, str(BRIDGE_PY), "check", tmp_path],
                capture_output=True,
                text=True,
                cwd=str(PROJECT_ROOT),
                timeout=15,
            )
            assert result.returncode == 0, f"check failed: {result.stderr}"
            # 应有检查输出
            assert "合规" in result.stdout or "Compliance" in result.stdout or "PASS" in result.stdout or "FAIL" in result.stdout
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_check_nonexistent_path(self):
        """check 命令对不存在路径应有友好提示"""
        result = subprocess.run(
            [PYTHON_EXEC, str(BRIDGE_PY), "check", "/nonexistent/path/file.py"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=10,
        )
        # 应有友好提示（不是 traceback）
        assert "Traceback" not in result.stdout
        assert "❌" in result.stdout or "不存在" in result.stdout or "not found" in result.stdout.lower()


class TestBridgePyAudit:
    """bridge.py audit 子命令测试"""

    def test_audit_command_no_query(self):
        """audit 命令无查询参数应执行成功"""
        result = subprocess.run(
            [PYTHON_EXEC, str(BRIDGE_PY), "audit"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=10,
        )
        # 即使没有记录也不应崩溃
        assert "Traceback" not in result.stdout, f"Unexpected traceback: {result.stdout}"
        assert result.returncode == 0, f"audit failed: {result.stderr}"

    def test_audit_command_with_query(self):
        """audit 命令带查询参数应执行成功"""
        result = subprocess.run(
            [PYTHON_EXEC, str(BRIDGE_PY), "audit", "test_query"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=10,
        )
        assert "Traceback" not in result.stdout
        assert result.returncode == 0


class TestBridgePyRunPlan:
    """bridge.py run/plan 子命令测试"""

    def test_run_nonexistent_workflow(self):
        """run 命令对不存在文件应有友好提示"""
        result = subprocess.run(
            [PYTHON_EXEC, str(BRIDGE_PY), "run", "/nonexistent/workflow.yaml"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=10,
        )
        assert "Traceback" not in result.stdout
        # 应提示文件不存在
        assert "❌" in result.stdout or "不存在" in result.stdout or "not exist" in result.stdout.lower()

    def test_plan_nonexistent_workflow(self):
        """plan 命令对不存在文件应有友好提示"""
        result = subprocess.run(
            [PYTHON_EXEC, str(BRIDGE_PY), "plan", "/nonexistent/workflow.yaml"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=10,
        )
        assert "Traceback" not in result.stdout
        assert "❌" in result.stdout or "不存在" in result.stdout or "not exist" in result.stdout.lower()


class TestBridgePyNoCommand:
    """bridge.py 无子命令时应输出帮助"""

    def test_no_command_shows_help(self):
        """无子命令应显示帮助信息"""
        result = subprocess.run(
            [PYTHON_EXEC, str(BRIDGE_PY)],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=10,
        )
        # 应输出帮助或 exit code 0
        assert "subcommand" in result.stdout.lower() or "command" in result.stdout.lower() or result.returncode == 0


# ═══════════════════════════════════════════════════════════
#  符号链接验证测试
# ═══════════════════════════════════════════════════════════

class TestSymlinks:
    """符号链接存在性验证"""

    def test_hermes_skill_symlink_exists(self):
        """~/.hermes/skills/harness-bridge 应存在"""
        assert HERMES_SKILL_LINK.exists(), f"Hermes skill symlink not found: {HERMES_SKILL_LINK}"

    def test_hermes_skill_symlink_is_link(self):
        """~/.hermes/skills/harness-bridge 应为符号链接"""
        assert HERMES_SKILL_LINK.is_symlink(), f"Not a symlink: {HERMES_SKILL_LINK}"

    def test_hermes_skill_symlink_points_to_skill_dir(self):
        """Hermes skill symlink 应指向项目 skills/harness-bridge/"""
        target = HERMES_SKILL_LINK.resolve()
        assert target == SKILL_DIR.resolve(), f"Symlink target {target} != {SKILL_DIR.resolve()}"

    def test_claude_skill_symlink_exists(self):
        """~/.claude/skills/harness-bridge 应存在"""
        assert CLAUDE_SKILL_LINK.exists(), f"Claude skill symlink not found: {CLAUDE_SKILL_LINK}"

    def test_claude_skill_symlink_is_link(self):
        """~/.claude/skills/harness-bridge 应为符号链接"""
        assert CLAUDE_SKILL_LINK.is_symlink(), f"Not a symlink: {CLAUDE_SKILL_LINK}"

    def test_claude_skill_symlink_points_to_skill_dir(self):
        """Claude skill symlink 应指向项目 skills/harness-bridge/"""
        target = CLAUDE_SKILL_LINK.resolve()
        assert target == SKILL_DIR.resolve(), f"Symlink target {target} != {SKILL_DIR.resolve()}"


# ═══════════════════════════════════════════════════════════
#  bridge.py PYTHONPATH 正确性测试
# ═══════════════════════════════════════════════════════════

class TestBridgePyPythonPath:
    """bridge.py PYTHONPATH 设置正确性"""

    def test_harness_core_path_derived_correctly(self):
        """HARNESS_CORE 应指向 packages/core/"""
        # 验证路径推导逻辑
        bridge_path = BRIDGE_PY.resolve()
        expected_core = bridge_path.parent.parent.parent / "packages" / "core"
        assert expected_core.exists(), f"Derived core path does not exist: {expected_core}"

    def test_harness_package_importable_with_pythonpath(self):
        """设置 PYTHONPATH 后 harness 包应可导入"""
        result = subprocess.run(
            [PYTHON_EXEC, "-c", "import harness; print(harness.__version__)"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT / "packages" / "core"),
            env={
                **dict(__import__("os").environ),
                "PYTHONPATH": str(PROJECT_ROOT / "packages" / "core"),
            },
            timeout=10,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"
        assert "0.1.0" in result.stdout
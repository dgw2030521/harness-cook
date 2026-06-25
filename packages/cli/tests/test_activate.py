"""
harness activate 命令测试

验证 activate.py 的核心逻辑：
- JSON 合并逻辑
- 符号链接创建
- MCP 残留清理（收敛错配，claude-code 走 hooks 不依赖 MCP）
- 项目根目录推导
"""

import json
import os
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


class TestActivateCommand:
    """activate.py 测试"""

    def test_get_project_root_with_env(self):
        """$CLAUDE_PROJECT_DIR 设置时优先使用"""
        from activate import _get_project_root
        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": "/custom/path"}):
            assert _get_project_root() == "/custom/path"

    def test_step_configure_mcp_cleans_stale_mcpserver(self, monkeypatch):
        """claude-code: 清理 ~/.claude/settings.json 中遗留的 harness-cook mcpServers"""
        from activate import _step_configure_mcp
        with tempfile.TemporaryDirectory() as tmp:
            monkeypatch.setattr(Path, "home", lambda: Path(tmp))
            claude_dir = Path(tmp) / ".claude"
            claude_dir.mkdir()
            settings_path = claude_dir / "settings.json"
            settings_path.write_text(json.dumps({
                "mcpServers": {
                    "harness-cook": {"command": "/old/harness-mcp.sh"},
                    "other-mcp": {"command": "keep"},
                },
                "permissions": {"allow": ["Bash(ls)"]},
            }))

            result = _step_configure_mcp(tmp, tmp, "claude-code")
            assert result is True

            merged = json.loads(settings_path.read_text())
            # harness-cook 被清，其他 mcp 与无关配置保留
            assert "harness-cook" not in merged["mcpServers"]
            assert "other-mcp" in merged["mcpServers"]
            assert "permissions" in merged

    def test_step_configure_mcp_skips_non_claude_adapter(self, monkeypatch):
        """非 claude-code adapter: 不动 ~/.claude/settings.json（MCP 由各自 adapter 写各自平台）"""
        from activate import _step_configure_mcp
        with tempfile.TemporaryDirectory() as tmp:
            monkeypatch.setattr(Path, "home", lambda: Path(tmp))
            claude_dir = Path(tmp) / ".claude"
            claude_dir.mkdir()
            settings_path = claude_dir / "settings.json"
            original = {"mcpServers": {"harness-cook": {"command": "/old/harness-mcp.sh"}}}
            settings_path.write_text(json.dumps(original))

            result = _step_configure_mcp(tmp, tmp, "hermes")
            assert result is True
            # hermes 不读 claude 配置，原样不动
            assert json.loads(settings_path.read_text()) == original

    def test_step_configure_mcp_no_stale_noop(self, monkeypatch):
        """claude-code 且无残留: 不改文件"""
        from activate import _step_configure_mcp
        with tempfile.TemporaryDirectory() as tmp:
            monkeypatch.setattr(Path, "home", lambda: Path(tmp))
            claude_dir = Path(tmp) / ".claude"
            claude_dir.mkdir()
            settings_path = claude_dir / "settings.json"
            original = {"permissions": {"allow": ["Bash(ls)"]}}
            settings_path.write_text(json.dumps(original))

            result = _step_configure_mcp(tmp, tmp, "claude-code")
            assert result is True
            assert json.loads(settings_path.read_text()) == original

    def test_step_initialize_creates_dirs(self):
        """初始化步骤创建 .harness/audit/ 目录"""
        from activate import _step_initialize
        with tempfile.TemporaryDirectory() as tmp:
            result = _step_initialize(tmp)
            assert result is True
            assert (Path(tmp) / ".harness" / "audit").exists()

    def test_step_configure_hooks_merges_permissions(self):
        """hooks 配置步骤合并 MCP 权限"""
        from activate import _step_configure_hooks
        with tempfile.TemporaryDirectory() as tmp:
            # 创建 .claude 目录
            claude_dir = Path(tmp) / ".claude"
            claude_dir.mkdir()
            settings_path = claude_dir / "settings.local.json"

            # 写入已有配置
            existing = {"permissions": {"allow": ["Bash(ls)"]}}
            settings_path.write_text(json.dumps(existing))

            # 创建空的 packages/hooks 目录
            hooks_dir = Path(tmp) / "packages" / "hooks"
            hooks_dir.mkdir(parents=True)
            for name in ["hook-compliance-scan.py", "hook-guardrails-pii.py",
                         "hook-session-init.py", "hook-task-audit.py",
                         "hook-prompt-guardrails.py"]:
                (hooks_dir / name).write_text("# mock")

            result = _step_configure_hooks(tmp)
            assert result is True

            # 验证合并后的配置
            merged = json.loads(settings_path.read_text())
            assert "hooks" in merged
            assert "permissions" in merged
            assert "allow" in merged["permissions"]
            # 原有权限应保留
            assert "Bash(ls)" in merged["permissions"]["allow"]
            # MCP 权限应添加
            assert "mcp__harness-cook__harness_check" in merged["permissions"]["allow"]

    def test_cmd_activate_skip_all(self):
        """全部跳过时的汇总"""
        from activate import cmd_activate
        args = MagicMock()
        args.skip_install = True
        args.skip_mcp = True
        args.skip_hooks = True
        args.skip_skills = True
        args.skip_init = True
        result = cmd_activate(args)
        # 全部跳过 → 无 results → all([]) = True → 返回 0
        assert result == 0
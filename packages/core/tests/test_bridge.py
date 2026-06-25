"""Bridge Deploy 单元测试"""

import sys
import os
import json
import pytest
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.types import ProfileConfig, GateMode
from harness.bridge import HarnessBridge
from harness.adapters.claude_code import ClaudeCodeAdapter, HOOK_POINT_MAP
from harness.adapters.cursor import CursorAdapter
from harness.adapters.openai import OpenAIAdapter
from harness.adapters.copilot_cli import CopilotCLIAdapter
from harness.adapters.hermes import HermesAdapter


class TestHookTranslation:
    """Hook 翻译测试"""

    def setup_method(self):
        self.bridge = HarnessBridge()
        self.bridge._bus._handlers.clear()
        self.adapter = ClaudeCodeAdapter()

    def test_script_hook_translation(self):
        hooks = {
            "session_start": [{"type": "script", "command": "python3 init.py"}],
        }
        result = self.adapter.translate_hooks(hooks)
        assert "SessionStart" in result
        # 新格式：matcher + hooks 数组
        assert "matcher" in result["SessionStart"][0]
        assert "hooks" in result["SessionStart"][0]
        assert result["SessionStart"][0]["hooks"][0]["type"] == "command"
        assert result["SessionStart"][0]["hooks"][0]["command"] == "python3 init.py"

    def test_skill_hook_translation(self):
        hooks = {
            "post_execute": [{"type": "skill", "skill_id": "auto-audit"}],
        }
        result = self.adapter.translate_hooks(hooks)
        assert "PostToolUse" in result
        # 新格式：matcher + hooks 数组
        assert "matcher" in result["PostToolUse"][0]
        assert "hooks" in result["PostToolUse"][0]
        assert "auto-audit" in result["PostToolUse"][0]["hooks"][0]["command"]

    def test_unknown_hook_point_skipped(self):
        hooks = {
            "unknown_point": [{"type": "script", "command": "echo hi"}],
        }
        result = self.adapter.translate_hooks(hooks)
        assert len(result) == 0

    def test_multiple_hooks_same_point(self):
        hooks = {
            "session_start": [
                {"type": "script", "command": "python3 init.py"},
                {"type": "script", "command": "python3 check.py"},
            ],
        }
        result = self.adapter.translate_hooks(hooks)
        # 新格式：同一个 hook 点的所有 hooks 放在一个 matcher 组的 hooks 数组中
        assert len(result["SessionStart"]) == 1  # 一个 matcher 组
        assert len(result["SessionStart"][0]["hooks"]) == 2  # 组内有两个 hooks

    def test_session_end_mapping(self):
        hooks = {
            "session_end": [{"type": "script", "command": "python3 audit.py"}],
        }
        result = self.adapter.translate_hooks(hooks)
        assert "SessionEnd" in result


class TestSupportsHooks:
    """适配器 supports_hooks 属性测试"""

    def test_claude_code_supports_hooks(self):
        adapter = ClaudeCodeAdapter()
        assert adapter.supports_hooks is True

    def test_copilot_cli_supports_hooks(self):
        adapter = CopilotCLIAdapter()
        assert adapter.supports_hooks is True

    def test_hermes_does_not_support_hooks(self):
        """Hermes 不支持原生 hooks，治理通过 MCP Server 实现"""
        adapter = HermesAdapter()
        assert adapter.supports_hooks is False

    def test_cursor_does_not_support_hooks(self):
        adapter = CursorAdapter()
        assert adapter.supports_hooks is False

    def test_openai_does_not_support_hooks(self):
        adapter = OpenAIAdapter()
        assert adapter.supports_hooks is False


class TestGatePrompt:
    """Gate prompt 翻译测试"""

    def setup_method(self):
        self.bridge = HarnessBridge()

    def test_generate_gate_prompt_mild(self):
        checks = [
            {"id": "no-secrets", "enabled": True},
            {"id": "no-eval", "enabled": True},
        ]
        prompt = self.bridge._translate_gates_to_prompt(GateMode.HYBRID, checks, strength="mild")
        assert "hybrid" in prompt
        assert "no-secrets" in prompt
        assert "no-eval" in prompt
        assert "MANDATORY" not in prompt
        assert "MUST" not in prompt

    def test_generate_gate_prompt_mandatory(self):
        checks = [
            {"id": "no-secrets", "enabled": True},
            {"id": "no-eval", "enabled": True},
        ]
        prompt = self.bridge._translate_gates_to_prompt(GateMode.STRICT, checks, strength="mandatory")
        assert "strict" in prompt
        assert "no-secrets" in prompt
        assert "MANDATORY" in prompt
        assert "MUST" in prompt
        assert "harness_check" in prompt

    def test_generate_gate_prompt_default_mild(self):
        """默认 strength=mild"""
        checks = [{"id": "no-secrets", "enabled": True}]
        prompt = self.bridge._translate_gates_to_prompt(GateMode.HYBRID, checks)
        assert "MANDATORY" not in prompt

    def test_empty_checks_no_prompt(self):
        prompt = self.bridge._translate_gates_to_prompt(GateMode.HYBRID, [])
        assert prompt == ""

    def test_all_disabled_no_prompt(self):
        checks = [{"id": "x", "enabled": False}]
        prompt = self.bridge._translate_gates_to_prompt(GateMode.HYBRID, checks)
        assert prompt == ""

    def test_mandatory_prompt_mentions_git_hook(self):
        """强提示必须提及 git hook 兜底"""
        checks = [{"id": "no-secrets", "enabled": True}]
        prompt = self.bridge._translate_gates_to_prompt(GateMode.STRICT, checks, strength="mandatory")
        assert "git pre-commit hook" in prompt


class TestGitHookInstallation:
    """git hook 安装测试"""

    def setup_method(self):
        self.bridge = HarnessBridge()

    def test_install_git_hooks_no_git_dir(self):
        """没有 .git/hooks/ 目录 → 返回 False"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.bridge._install_git_hooks(Path(tmpdir))
            assert result is False

    def test_install_git_hooks_creates_pre_commit(self):
        """有 .git/hooks/ → 创建 pre-commit"""
        with tempfile.TemporaryDirectory() as tmpdir:
            git_hooks_dir = Path(tmpdir) / ".git" / "hooks"
            git_hooks_dir.mkdir(parents=True)

            result = self.bridge._install_git_hooks(Path(tmpdir))
            assert result is True
            pre_commit = git_hooks_dir / "pre-commit"
            assert pre_commit.exists()

            content = pre_commit.read_text()
            assert "harness-cook gate" in content

    def test_install_git_hooks_appends_to_existing(self):
        """已有 pre-commit hook → 追加 harness 段，不覆盖"""
        with tempfile.TemporaryDirectory() as tmpdir:
            git_hooks_dir = Path(tmpdir) / ".git" / "hooks"
            git_hooks_dir.mkdir(parents=True)
            pre_commit = git_hooks_dir / "pre-commit"
            pre_commit.write_text("# existing hook\necho 'existing'\n")

            self.bridge._install_git_hooks(Path(tmpdir))

            content = pre_commit.read_text()
            assert "# existing hook" in content
            assert "harness-cook gate" in content

    def test_install_git_hooks_replaces_old_harness_section(self):
        """已有 harness 段 → 替换旧版本"""
        with tempfile.TemporaryDirectory() as tmpdir:
            git_hooks_dir = Path(tmpdir) / ".git" / "hooks"
            git_hooks_dir.mkdir(parents=True)
            pre_commit = git_hooks_dir / "pre-commit"
            pre_commit.write_text("# existing\n# ── harness-cook gate ──\nOLD CONTENT\n# ── harness-cook gate end ──\n")

            self.bridge._install_git_hooks(Path(tmpdir))

            content = pre_commit.read_text()
            assert "# existing" in content
            assert "OLD CONTENT" not in content
            assert "harness-cook gate" in content

    def test_install_git_hooks_idempotent(self):
        """重复安装 → 不产生重复段"""
        with tempfile.TemporaryDirectory() as tmpdir:
            git_hooks_dir = Path(tmpdir) / ".git" / "hooks"
            git_hooks_dir.mkdir(parents=True)

            self.bridge._install_git_hooks(Path(tmpdir))
            first_content = (git_hooks_dir / "pre-commit").read_text()

            self.bridge._install_git_hooks(Path(tmpdir))
            second_content = (git_hooks_dir / "pre-commit").read_text()

            # harness 段只出现一次（替换而非追加）
            assert second_content.count("# ── harness-cook gate ──") == 1


class TestDeploy:
    """完整 Deploy 测试"""

    def setup_method(self):
        self.bridge = HarnessBridge()
        self.bridge._bus._handlers.clear()

    def test_deploy_creates_settings_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建 .git/hooks 以便 git hook 安装测试
            git_hooks_dir = Path(tmpdir) / ".git" / "hooks"
            git_hooks_dir.mkdir(parents=True)

            profile = ProfileConfig(
                name="test",
                hooks={
                    "session_start": [{"type": "script", "command": "python3 init.py"}],
                    "session_end": [{"type": "script", "command": "python3 audit.py"}],
                },
                default_gate_mode=GateMode.HYBRID,
                gate_checks=[{"id": "no-secrets", "enabled": True}],
            )
            result = self.bridge.deploy(profile, project_dir=tmpdir)

            assert result["status"] == "deployed"
            # 2 个 profile hooks + 1 个 gate hook（gate_checks 非空 →
            # translate_gates_to_hooks 自动产出 PreToolUse[Write|Edit]→gate 脚本，
            # 兑现"gates 由 hooks 自动强制执行"的设计意图）
            assert result["hooks_deployed"] == 3
            assert result["supports_hooks"] is True
            assert result["prompt_strength"] == "mild"

            # 验证 settings.json
            settings_path = Path(tmpdir) / ".claude" / "settings.json"
            assert settings_path.exists()
            settings = json.loads(settings_path.read_text())
            assert "hooks" in settings
            assert "SessionStart" in settings["hooks"]
            assert "SessionEnd" in settings["hooks"]
            # F 方案：gate_checks 非空 → 自动产出 PreToolUse[Write|Edit]→gate 脚本
            assert "PreToolUse" in settings["hooks"]
            gate_entry = next(
                (e for e in settings["hooks"]["PreToolUse"] if e.get("matcher") == "Write|Edit"),
                None,
            )
            assert gate_entry is not None, "应产出 matcher=Write|Edit 的 gate hook"
            assert gate_entry["hooks"][0]["command"].endswith("hook-gate-pre-write.py")

            # 验证 git hook 安装
            assert result["git_hook_installed"] is True
            pre_commit = git_hooks_dir / "pre-commit"
            assert pre_commit.exists()

    def test_deploy_preserves_existing_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # 先创建已有 settings
            settings_dir = Path(tmpdir) / ".claude"
            settings_dir.mkdir()
            existing = {"permissions": {"allow": ["tool1"]}, "hooks": {"PreToolUse": [{"type": "command", "command": "old"}]}}
            (settings_dir / "settings.json").write_text(json.dumps(existing))

            profile = ProfileConfig(
                name="test",
                hooks={"session_start": [{"type": "script", "command": "init.py"}]},
            )
            self.bridge.deploy(profile, project_dir=tmpdir)

            settings = json.loads((settings_dir / "settings.json").read_text())
            assert "permissions" in settings  # 保留原有字段
            assert "PreToolUse" in settings["hooks"]  # 保留原有 hooks
            assert "SessionStart" in settings["hooks"]  # 新增 hooks

    def test_deploy_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile = ProfileConfig(
                name="test",
                hooks={"session_start": [{"type": "script", "command": "init.py"}]},
            )
            self.bridge.deploy(profile, project_dir=tmpdir)
            self.bridge.deploy(profile, project_dir=tmpdir)

            settings = json.loads((Path(tmpdir) / ".claude" / "settings.json").read_text())
            # SessionStart 只有一组 hooks（不是重复追加）
            assert len(settings["hooks"]["SessionStart"]) == 1

    def test_deploy_no_hooks_adapter_uses_mandatory_strength(self):
        """无-hooks Agent 部署时 prompt_strength 应为 mandatory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            git_hooks_dir = Path(tmpdir) / ".git" / "hooks"
            git_hooks_dir.mkdir(parents=True)

            profile = ProfileConfig(
                name="test",
                default_agent="cursor",
                hooks={"session_start": [{"type": "script", "command": "init.py"}]},
                default_gate_mode=GateMode.STRICT,
                gate_checks=[{"id": "no-secrets", "enabled": True}],
            )
            result = self.bridge.deploy(profile, project_dir=tmpdir)

            assert result["supports_hooks"] is False
            assert result["prompt_strength"] == "mandatory"

    def test_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # 未部署——既没有 .harness/ 目录，也没有 settings 文件
            status = self.bridge.status(project_dir=tmpdir)
            assert status["deployed"] is False

            # 部署后——deploy 会写 settings.json，但 status 以 .harness/ 为部署标记
            # 所以需要创建 .harness/ 目录（真实流程由 activate 命令创建）
            profile = ProfileConfig(name="test", hooks={"session_start": [{"type": "script", "command": "init.py"}]})
            self.bridge.deploy(profile, project_dir=tmpdir)

            # deploy 只写 settings.json，不创建 .harness/
            # status 现在以 .harness/ 目录为部署标记
            status = self.bridge.status(project_dir=tmpdir)
            assert status["deployed"] is False  # 无 .harness/ → 视为未部署

            # 模拟 activate 创建 .harness/ 目录
            Path(tmpdir, ".harness").mkdir(exist_ok=True)
            status = self.bridge.status(project_dir=tmpdir)
            assert status["deployed"] is True
            assert status["total_hooks"] > 0


class TestReadSettingsFormat:
    """_read_settings 按适配器格式读取——修复 Hermes YAML 被 json.loads 清除的 bug"""

    def setup_method(self):
        self.bridge = HarnessBridge()
        self.bridge._bus._handlers.clear()

    def test_read_json_settings(self):
        """JSON 格式配置（Claude Code / Copilot CLI / Cursor）正常读取"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            original = {"hooks": {"SessionStart": [{"type": "command", "command": "echo hello"}]}, "permissions": {"allow": ["harness_check"]}}
            settings_path.write_text(json.dumps(original, indent=2), encoding="utf-8")

            result = self.bridge._read_settings(settings_path, adapter_name="claude-code")
            assert result == original
            assert "hooks" in result
            assert "permissions" in result

    def test_read_yaml_settings_hermes(self):
        """YAML 格式配置（Hermes）用 yaml.safe_load 正确读取，保留用户原有字段"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "config.yaml"
            # 用户的真实配置：包含 harness-cook 条目 + 用户自有配置（onboarding 等）
            yaml_content = """mcpServers:
  harness-cook:
    command: python3
    args:
      - -m
      - harness_mcp_server
    env:
      HARNESS_COOK_ROOT: /path/to/harness-cook
      PYTHONPATH: /path/to/harness-cook/packages/mcp
  other-agent:
    command: node
    args:
      - server.js
harness_metadata:
  hooks_config:
    session_start:
      - type: command
        command: python3 init.py
        trigger: on_session_start
  note: Hermes governance via MCP tools; no native hook execution
onboarding:
  seen:
    openclaw_residue_cleanup: true
    busy_input_prompt: true
"""
            settings_path.write_text(yaml_content, encoding="utf-8")

            result = self.bridge._read_settings(settings_path, adapter_name="hermes")
            assert "mcpServers" in result
            assert "other-agent" in result["mcpServers"]  # 用户原有 MCP server 保留
            assert "onboarding" in result  # 用户原有字段保留
            assert result["onboarding"]["seen"]["openclaw_residue_cleanup"] is True

    def test_yaml_fails_with_json_parser(self):
        """验证 bug 根因：json.loads 无法解析 YAML → 返回空字典 → 用户配置丢失"""
        import json as json_module
        yaml_content = """mcpServers:
  other-agent:
    command: node
onboarding:
  seen:
    busy_input_prompt: true
"""
        # json.loads 解析 YAML 必定失败
        with pytest.raises(json_module.JSONDecodeError):
            json_module.loads(yaml_content)

    def test_read_json_with_hermes_adapter_fails_gracefully(self):
        """如果 Hermes 配置文件意外是 JSON 格式，仍然能读取"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "config.yaml"
            # JSON 格式内容意外写在 YAML 文件中
            json_content = '{"mcpServers": {"other-agent": {"command": "node"}}}'
            settings_path.write_text(json_content, encoding="utf-8")

            # yaml.safe_load 可以解析 JSON（JSON 是 YAML 子集）
            result = self.bridge._read_settings(settings_path, adapter_name="hermes")
            assert "mcpServers" in result
            assert "other-agent" in result["mcpServers"]

    def test_read_nonexistent_file(self):
        """不存在文件返回空字典"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "nonexistent.json"
            result = self.bridge._read_settings(settings_path, adapter_name="claude-code")
            assert result == {}

    def test_read_corrupted_file(self):
        """损坏文件返回空字典（不抛异常）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            settings_path.write_text("{{{{corrupted", encoding="utf-8")
            result = self.bridge._read_settings(settings_path, adapter_name="claude-code")
            assert result == {}


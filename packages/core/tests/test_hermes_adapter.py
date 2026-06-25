"""
Hermes 适配器测试

测试覆盖：
- supports_hooks = False（Hermes 不支持原生 hooks）
- translate_hooks 输出 MCP Server 注册 + metadata
- Settings 合并（MCP Server + metadata）
- YAML 导出
- 全局配置路径
- 适配器名称
"""

import pytest
import os
import tempfile
import yaml
from pathlib import Path
from unittest.mock import patch

from harness.adapters.hermes import HermesAdapter


class TestHermesAdapter:
    """Hermes 适配器测试"""

    def test_adapter_name(self):
        """测试适配器名称"""
        adapter = HermesAdapter()
        assert adapter.name == "hermes"

    def test_supports_hooks_false(self):
        """测试 supports_hooks 为 False——Hermes 不支持原生 hooks 自动触发"""
        adapter = HermesAdapter()
        assert adapter.supports_hooks is False

    def test_translate_hooks_produces_mcp_server(self):
        """测试 translate_hooks 输出 MCP Server 注册"""
        adapter = HermesAdapter()
        hooks_config = {
            "session_start": [
                {"type": "script", "command": "python3 scripts/startup.py"},
            ],
        }

        result = adapter.translate_hooks(hooks_config)

        # 核心产出：MCP Server 注册
        assert "mcpServers" in result
        assert "harness-cook" in result["mcpServers"]
        server = result["mcpServers"]["harness-cook"]
        assert server["command"] == "python3"
        assert "-m" in server["args"]
        assert "harness_mcp_server" in server["args"]
        assert "HARNESS_COOK_ROOT" in server["env"]

    def test_translate_hooks_produces_metadata(self):
        """测试 translate_hooks 输出 hooks metadata"""
        adapter = HermesAdapter()
        hooks_config = {
            "session_start": [
                {"type": "script", "command": "python3 scripts/startup.py"},
            ],
        }

        result = adapter.translate_hooks(hooks_config)

        # 附加产出：metadata（原始 hook 配置供参考）
        assert "harness_metadata" in result
        assert "hooks_config" in result["harness_metadata"]
        assert "note" in result["harness_metadata"]
        assert result["harness_metadata"]["note"] == "Hermes governance via MCP tools; no native hook execution"

        # metadata 中保留了 hook 配置
        assert "session_start" in result["harness_metadata"]["hooks_config"]
        entry = result["harness_metadata"]["hooks_config"]["session_start"][0]
        assert entry["type"] == "command"
        assert "trigger" in entry

    def test_translate_skill_hooks_in_metadata(self):
        """测试 skill hook 翻译到 metadata"""
        adapter = HermesAdapter()
        hooks_config = {
            "pre_execute": [
                {"type": "skill", "skill_id": "auto-audit"},
            ],
        }

        result = adapter.translate_hooks(hooks_config)

        assert "harness_metadata" in result
        assert "pre_execute" in result["harness_metadata"]["hooks_config"]
        entry = result["harness_metadata"]["hooks_config"]["pre_execute"][0]
        assert entry["type"] == "skill"
        assert entry["skill_id"] == "auto-audit"
        assert entry["trigger"] == "before_task"

    def test_translate_prompt_hooks_in_metadata(self):
        """测试 prompt hook 翻译到 metadata"""
        adapter = HermesAdapter()
        hooks_config = {
            "session_start": [
                {"type": "prompt", "message": "[harness] 已激活"},
            ],
        }

        result = adapter.translate_hooks(hooks_config)

        assert "harness_metadata" in result
        assert "session_start" in result["harness_metadata"]["hooks_config"]
        entry = result["harness_metadata"]["hooks_config"]["session_start"][0]
        assert entry["type"] == "prompt"
        assert entry["message"] == "[harness] 已激活"

    def test_translate_empty_hooks(self):
        """测试空 hooks 配置——仍产出 MCP Server 注册"""
        adapter = HermesAdapter()
        hooks_config = {}

        result = adapter.translate_hooks(hooks_config)

        # 即使没有 hooks，MCP Server 注册仍然产出
        assert "mcpServers" in result
        assert "harness-cook" in result["mcpServers"]
        # metadata 中的 hooks_config 为空
        assert result["harness_metadata"]["hooks_config"] == {}

    def test_translate_hooks_rejects_unsafe_command(self):
        """测试拒绝不安全的 command"""
        adapter = HermesAdapter()
        hooks_config = {
            "session_start": [
                {"type": "script", "command": "rm -rf / ; echo done"},
            ],
        }

        result = adapter.translate_hooks(hooks_config)

        # 不安全命令被拒绝，metadata 中无对应条目
        hooks_in_meta = result["harness_metadata"]["hooks_config"]
        assert "session_start" not in hooks_in_meta

    def test_get_settings_path_global(self):
        """测试 get_settings_path 返回全局配置路径（非项目级）"""
        adapter = HermesAdapter()
        # 确保没有 HERMES_CONFIG_PATH 环境变量
        with patch.dict(os.environ, {}, clear=True):
            path = adapter.get_settings_path("/tmp/project")

        home = Path.home()
        expected = str(home / ".hermes" / "config.yaml")
        assert path == expected
        # 路径不包含项目目录
        assert "/tmp/project" not in path

    def test_get_settings_path_env_override(self):
        """测试 HERMES_CONFIG_PATH 环境变量覆盖"""
        adapter = HermesAdapter()
        custom_path = "/custom/hermes/config.yaml"
        with patch.dict(os.environ, {"HERMES_CONFIG_PATH": custom_path}):
            path = adapter.get_settings_path("/tmp/project")

        assert path == custom_path

    def test_merge_settings_mcp_server(self):
        """测试合并 MCP Server 定义到全局配置"""
        adapter = HermesAdapter()

        existing = {"mcpServers": {"other-server": {"command": "other"}}}
        new_hooks = {
            "mcpServers": {
                "harness-cook": {"command": "python3", "args": ["-m", "harness_mcp_server"]},
            },
            "harness_metadata": {
                "hooks_config": {"session_start": [{"type": "command"}]},
                "note": "test",
            },
        }

        result = adapter.merge_settings(existing, new_hooks)

        # 保留原有 server
        assert "other-server" in result["mcpServers"]
        # 新增 harness-cook server
        assert "harness-cook" in result["mcpServers"]

    def test_merge_settings_metadata_append(self):
        """测试合并 metadata——追加而非覆盖"""
        adapter = HermesAdapter()

        existing = {
            "harness_metadata": {
                "hooks_config": {"project_a": [{"type": "command"}]},
                "note": "old note",
            },
        }
        new_hooks = {
            "mcpServers": {"harness-cook": {"command": "python3"}},
            "harness_metadata": {
                "hooks_config": {"project_b": [{"type": "skill"}]},
                "note": "new note",
            },
        }

        result = adapter.merge_settings(existing, new_hooks)

        # 合并后保留两个项目的 hooks_config
        assert "project_a" in result["harness_metadata"]["hooks_config"]
        assert "project_b" in result["harness_metadata"]["hooks_config"]

    def test_export_yaml(self):
        """测试导出 YAML 文件"""
        adapter = HermesAdapter()

        config = {
            "mcpServers": {
                "harness-cook": {
                    "command": "python3",
                    "args": ["-m", "harness_mcp_server"],
                    "env": {"HARNESS_COOK_ROOT": "/path/to/harness"},
                },
            },
            "harness_metadata": {
                "hooks_config": {},
                "note": "Hermes governance via MCP tools",
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "hermes", "config.yaml")
            adapter.export_yaml(config, output_path)

            # 验证文件存在且是合法 YAML
            assert os.path.exists(output_path)

            with open(output_path, 'r') as f:
                loaded = yaml.safe_load(f)

            assert "mcpServers" in loaded
            assert "harness-cook" in loaded["mcpServers"]
            assert "harness_metadata" in loaded

    def test_hook_point_mapping(self):
        """测试 hook 点到 trigger 的映射"""
        adapter = HermesAdapter()

        assert adapter._map_hook_to_trigger("session_start") == "on_session_start"
        assert adapter._map_hook_to_trigger("pre_execute") == "before_task"
        assert adapter._map_hook_to_trigger("post_execute") == "after_task"
        assert adapter._map_hook_to_trigger("unknown") == "custom_unknown"

    def test_validate_command_rejects_dangerous(self):
        """测试拒绝危险命令"""
        adapter = HermesAdapter()

        assert adapter._validate_command("") is False
        assert adapter._validate_command("rm -rf / ; echo") is False  # 含 ;
        assert adapter._validate_command("cat file | grep") is False   # 含 |
        assert adapter._validate_command("echo $(whoami)") is False    # 含 $()
        assert adapter._validate_command("python3 ../script.py") is False  # 含 ..

    def test_validate_command_accepts_safe(self):
        """测试接受安全命令"""
        adapter = HermesAdapter()

        assert adapter._validate_command("python3 script.py") is True
        assert adapter._validate_command("/usr/bin/python3 init.py") is True

    def test_validate_skill_id(self):
        """测试 skill_id 验证"""
        adapter = HermesAdapter()

        assert adapter._validate_skill_id("") is False
        assert adapter._validate_skill_id("auto-audit") is True
        assert adapter._validate_skill_id("my_skill_v2") is True
        assert adapter._validate_skill_id("bad!skill") is False

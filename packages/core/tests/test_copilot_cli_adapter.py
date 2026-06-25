"""
Phase 4.1 & 4.2 适配器测试

验证：
- CopilotCLIAdapter.name = "copilot-cli"
- CopilotCLIAdapter.get_settings_path → .copilot/config.json
- CopilotCLIAdapter.translate_hooks → Copilot CLI MCP 格式
- CopilotCLIAdapter.merge_settings → 合并 MCP server + hooks
- CursorAdapter.name = "cursor"
- CursorAdapter.get_settings_path → .cursor/mcp.json
- CursorAdapter.translate_hooks → Cursor MCP 格式
- CursorAdapter.merge_settings → 合并 MCP server + metadata
- 通过 AdapterRegistry 注册和获取
"""

import pytest
from unittest.mock import patch
from pathlib import Path

from harness.adapters.copilot_cli import CopilotCLIAdapter, HOOK_POINT_MAP as COPILOT_HOOK_MAP
from harness.adapters.cursor import CursorAdapter
from harness.adapters.base import IAgentAdapter
from harness.bridge import get_adapter_registry


# ── 测试辅助 ──────────────────────────────────────────────────

HARNESS_ROOT = "/opt/harness-cook"

SAMPLE_HOOKS = {
    "session_start": [
        {"type": "script", "command": "scripts/run-skill.py compliance-check"},
        {"type": "skill", "skill_id": "compliance-check"},
    ],
    "pre_execute": [
        {"type": "script", "command": "packages/hooks/pre_execute.py"},
    ],
    "post_execute": [
        {"type": "prompt", "message": "Review your changes"},
    ],
}


# ═══════════════════════════════════════════════════════════════
#  CopilotCLIAdapter 测试
# ═══════════════════════════════════════════════════════════════

class TestCopilotCLIAdapterName:

    def test_name(self):
        """name = copilot-cli"""
        adapter = CopilotCLIAdapter()
        assert adapter.name == "copilot-cli"

    def test_has_required_methods(self):
        """拥有 IAgentAdapter 要求的方法"""
        adapter = CopilotCLIAdapter()
        assert hasattr(adapter, 'name')
        assert hasattr(adapter, 'translate_hooks')
        assert hasattr(adapter, 'get_settings_path')
        assert hasattr(adapter, 'merge_settings')


class TestCopilotCLIAdapterSettingsPath:

    def test_settings_path(self):
        """get_settings_path → .copilot/config.json"""
        adapter = CopilotCLIAdapter()
        path = adapter.get_settings_path("/my/project")
        assert path == "/my/project/.copilot/config.json"


class TestCopilotCLIAdapterTranslateHooks:

    def test_basic_translate(self):
        """基本 hook 翻译 → Copilot CLI 格式"""
        adapter = CopilotCLIAdapter()
        result = adapter.translate_hooks(SAMPLE_HOOKS, harness_root=HARNESS_ROOT)

        # 有 hooks 部分
        assert "hooks" in result
        # 有 MCP server 定义
        assert "mcpServers" in result
        assert "harness-cook" in result["mcpServers"]

    def test_mcp_server_entry(self):
        """MCP server 定义格式"""
        adapter = CopilotCLIAdapter()
        result = adapter.translate_hooks(SAMPLE_HOOKS, harness_root=HARNESS_ROOT)

        mcp = result["mcpServers"]["harness-cook"]
        assert mcp["command"] == "python3"
        assert "-m" in mcp["args"]
        assert "harness_mcp_server" in mcp["args"]
        assert "HARNESS_COOK_ROOT" in mcp["env"]

    def test_hook_point_mapping(self):
        """hook 点映射正确"""
        assert "session_start" in COPILOT_HOOK_MAP
        assert COPILOT_HOOK_MAP["session_start"] == "on_session_start"
        assert "pre_tool_use" in COPILOT_HOOK_MAP
        assert COPILOT_HOOK_MAP["pre_tool_use"] == "on_pre_tool_use"

    def test_unsafe_command_rejected(self):
        """不安全的 command 被拒绝"""
        adapter = CopilotCLIAdapter()
        unsafe_hooks = {
            "session_start": [
                {"type": "script", "command": "rm -rf /; echo hacked"},
            ],
        }
        result = adapter.translate_hooks(unsafe_hooks, harness_root=HARNESS_ROOT)

        # 不安全命令 → hooks 为空（或不存在）
        session_hooks = result.get("hooks", {}).get("on_session_start", [])
        assert len(session_hooks) == 0

    def test_empty_hooks(self):
        """空 hooks → 仍有 MCP server 定义"""
        adapter = CopilotCLIAdapter()
        result = adapter.translate_hooks({}, harness_root=HARNESS_ROOT)

        assert "mcpServers" in result
        assert result.get("hooks", {}) == {}


class TestCopilotCLIAdapterMergeSettings:

    def test_merge_mcp_servers(self):
        """合并 MCP server 定义"""
        adapter = CopilotCLIAdapter()
        existing = {
            "mcpServers": {
                "other-server": {"command": "other"},
            },
        }
        new_hooks = {
            "hooks": {"on_session_start": [{"type": "command", "command": "echo hi"}]},
            "mcpServers": {
                "harness-cook": {"command": "python3", "args": ["-m", "harness_mcp_server"]},
            },
        }

        result = adapter.merge_settings(existing, new_hooks)
        assert "harness-cook" in result["mcpServers"]
        assert "other-server" in result["mcpServers"]

    def test_merge_hooks(self):
        """合并 hooks"""
        adapter = CopilotCLIAdapter()
        existing = {
            "hooks": {"on_session_start": [{"type": "command", "command": "echo existing"}]},
        }
        new_hooks = {
            "hooks": {"on_session_start": [{"type": "command", "command": "echo new"}]},
        }

        result = adapter.merge_settings(existing, new_hooks)
        session_hooks = result["hooks"]["on_session_start"]
        assert len(session_hooks) == 2

    def test_merge_into_empty(self):
        """合并到空配置"""
        adapter = CopilotCLIAdapter()
        existing = {}
        new_hooks = {
            "hooks": {},
            "mcpServers": {
                "harness-cook": {"command": "python3"},
            },
        }

        result = adapter.merge_settings(existing, new_hooks)
        assert "harness-cook" in result["mcpServers"]


# ═══════════════════════════════════════════════════════════════
#  CursorAdapter 测试
# ═══════════════════════════════════════════════════════════════

class TestCursorAdapterName:

    def test_name(self):
        """name = cursor"""
        adapter = CursorAdapter()
        assert adapter.name == "cursor"

    def test_has_required_methods(self):
        """拥有 IAgentAdapter 要求的方法"""
        adapter = CursorAdapter()
        assert hasattr(adapter, 'name')
        assert hasattr(adapter, 'translate_hooks')
        assert hasattr(adapter, 'get_settings_path')
        assert hasattr(adapter, 'merge_settings')


class TestCursorAdapterSettingsPath:

    def test_settings_path(self):
        """get_settings_path → .cursor/mcp.json"""
        adapter = CursorAdapter()
        path = adapter.get_settings_path("/my/project")
        assert path == "/my/project/.cursor/mcp.json"


class TestCursorAdapterTranslateHooks:

    def test_basic_translate(self):
        """基本翻译 → Cursor MCP 格式"""
        adapter = CursorAdapter()
        result = adapter.translate_hooks(SAMPLE_HOOKS, harness_root=HARNESS_ROOT)

        # 有 MCP server 定义
        assert "mcpServers" in result
        assert "harness-cook" in result["mcpServers"]

        # 有 metadata（hook 配置供参考）
        assert "harness_metadata" in result
        assert "hooks_config" in result["harness_metadata"]

    def test_metadata_note(self):
        """metadata 包含说明"""
        adapter = CursorAdapter()
        result = adapter.translate_hooks(SAMPLE_HOOKS, harness_root=HARNESS_ROOT)

        assert "note" in result["harness_metadata"]
        assert "Cursor" in result["harness_metadata"]["note"]

    def test_mcp_server_entry(self):
        """MCP server 定义格式"""
        adapter = CursorAdapter()
        result = adapter.translate_hooks(SAMPLE_HOOKS, harness_root=HARNESS_ROOT)

        mcp = result["mcpServers"]["harness-cook"]
        assert mcp["command"] == "python3"
        assert "HARNESS_COOK_ROOT" in mcp["env"]

    def test_empty_hooks(self):
        """空 hooks → 仍有 MCP server"""
        adapter = CursorAdapter()
        result = adapter.translate_hooks({}, harness_root=HARNESS_ROOT)

        assert "mcpServers" in result

    def test_unsafe_command_rejected(self):
        """不安全 command 在 metadata 中被过滤"""
        adapter = CursorAdapter()
        unsafe_hooks = {
            "session_start": [
                {"type": "script", "command": "rm -rf / | bad"},
            ],
        }
        result = adapter.translate_hooks(unsafe_hooks, harness_root=HARNESS_ROOT)

        hooks_config = result["harness_metadata"]["hooks_config"]
        assert "session_start" not in hooks_config or len(hooks_config.get("session_start", [])) == 0


class TestCursorAdapterMergeSettings:

    def test_merge_mcp_servers(self):
        """合并 MCP server 定义"""
        adapter = CursorAdapter()
        existing = {
            "mcpServers": {
                "existing-server": {"command": "existing"},
            },
        }
        new_hooks = {
            "mcpServers": {
                "harness-cook": {"command": "python3"},
            },
        }

        result = adapter.merge_settings(existing, new_hooks)
        assert "harness-cook" in result["mcpServers"]
        assert "existing-server" in result["mcpServers"]

    def test_merge_metadata(self):
        """合并 metadata"""
        adapter = CursorAdapter()
        existing = {
            "harness_metadata": {
                "hooks_config": {"pre_execute": [{"type": "command", "command": "old"}]},
            },
        }
        new_hooks = {
            "harness_metadata": {
                "hooks_config": {"post_execute": [{"type": "command", "command": "new"}]},
                "note": "Cursor note",
            },
        }

        result = adapter.merge_settings(existing, new_hooks)
        assert "pre_execute" in result["harness_metadata"]["hooks_config"]
        assert "post_execute" in result["harness_metadata"]["hooks_config"]

    def test_merge_into_empty(self):
        """合并到空配置"""
        adapter = CursorAdapter()
        existing = {}
        new_hooks = {
            "mcpServers": {
                "harness-cook": {"command": "python3"},
            },
        }

        result = adapter.merge_settings(existing, new_hooks)
        assert "harness-cook" in result["mcpServers"]


# ═══════════════════════════════════════════════════════════════
#  适配器注册测试
# ═══════════════════════════════════════════════════════════════

class TestAdapterRegistration:

    def test_copilot_cli_registered(self):
        """copilot-cli 通过 AdapterRegistry 可获取"""
        registry = get_adapter_registry()
        adapter = registry.get_instance("copilot-cli")
        assert isinstance(adapter, CopilotCLIAdapter)

    def test_cursor_registered(self):
        """cursor 通过 AdapterRegistry 可获取"""
        registry = get_adapter_registry()
        adapter = registry.get_instance("cursor")
        assert isinstance(adapter, CursorAdapter)

    def test_all_adapters_registered(self):
        """所有内置适配器都已注册"""
        registry = get_adapter_registry()
        adapters = registry.list_adapters()
        assert "claude-code" in adapters
        assert "copilot-cli" in adapters
        assert "cursor" in adapters

    def test_unknown_adapter_fallback(self):
        """未知适配器 → 回退到 claude-code"""
        registry = get_adapter_registry()
        adapter = registry.get_instance("unknown-adapter")
        assert adapter.name == "claude-code"

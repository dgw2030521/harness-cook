"""
S-1 验收测试——适配器插件机制

验证项：
  1. AdapterRegistry 注册/获取/列出/发现机制
  2. IAgentAdapter S-1 增强（hook_point_map, get_capabilities）
  3. PlatformCapability 数据类
  4. 自定义适配器通过 .harness/adapters/ 自动发现（AgentX 示例）
  5. 退让检测预留（ExecutionStrategy 枚举）

依赖：harness.bridge.AdapterRegistry, harness.types.PlatformCapability/ExecutionStrategy
"""

import pytest
import tempfile
import os
import sys
from pathlib import Path
from unittest.mock import patch

from harness.bridge import AdapterRegistry, get_adapter_registry
from harness.types import PlatformCapability, ExecutionStrategy
from harness.adapters.base import IAgentAdapter


# ═══════════════════════════════════════════════════════════════
#  1. AdapterRegistry 基础功能
# ═══════════════════════════════════════════════════════════════

class TestAdapterRegistryBasic:

    def test_registry_singleton(self):
        """全局 registry 单例可获取"""
        registry = get_adapter_registry()
        assert isinstance(registry, AdapterRegistry)
        # 再次获取应该是同一实例
        registry2 = get_adapter_registry()
        assert registry is registry2

    def test_builtin_adapters_registered(self):
        """5 个内置适配器都已注册"""
        registry = get_adapter_registry()
        adapters = registry.list_adapters()
        expected = ["claude-code", "copilot-cli", "hermes", "cursor", "openai"]
        for name in expected:
            assert name in adapters, f"{name} not found in registry"

    def test_get_instance_returns_correct_type(self):
        """get_instance 返回正确的适配器实例"""
        registry = get_adapter_registry()

        from harness.adapters.claude_code import ClaudeCodeAdapter
        from harness.adapters.copilot_cli import CopilotCLIAdapter
        from harness.adapters.hermes import HermesAdapter
        from harness.adapters.cursor import CursorAdapter
        from harness.adapters.openai import OpenAIAdapter

        assert isinstance(registry.get_instance("claude-code"), ClaudeCodeAdapter)
        assert isinstance(registry.get_instance("copilot-cli"), CopilotCLIAdapter)
        assert isinstance(registry.get_instance("hermes"), HermesAdapter)
        assert isinstance(registry.get_instance("cursor"), CursorAdapter)
        assert isinstance(registry.get_instance("openai"), OpenAIAdapter)

    def test_get_instance_fallback(self):
        """未知适配器回退到 claude-code"""
        registry = get_adapter_registry()
        adapter = registry.get_instance("unknown-adapter")
        assert adapter.name == "claude-code"

    def test_has_adapter(self):
        """has() 检查适配器是否存在"""
        registry = get_adapter_registry()
        assert registry.has("claude-code") is True
        assert registry.has("unknown-adapter") is False

    def test_unregister_adapter(self):
        """unregister() 移除适配器后 get_instance 回退"""
        registry = get_adapter_registry()
        # unregister openai（最后一个，不影响回退逻辑）
        assert registry.has("openai") is True
        registry.unregister("openai")
        assert registry.has("openai") is False
        # 清理：重新注册
        registry._register_builtin()


class TestAdapterRegistryCustomRegister:

    def test_register_custom_adapter_class(self):
        """register() 可注册自定义适配器类"""
        registry = AdapterRegistry()  # 用新实例避免影响全局

        class MockAdapter:
            @property
            def name(self): return "mock"
            @property
            def supports_hooks(self): return False
            @property
            def hook_point_map(self): return {}
            def get_capabilities(self):
                return PlatformCapability()
            def translate_hooks(self, hooks_config, harness_root=None): return {}
            def get_settings_path(self, project_dir): return ""
            def merge_settings(self, existing, new_hooks, harness_root=""): return existing

        registry.register("mock", MockAdapter)
        assert registry.has("mock") is True
        instance = registry.get_instance("mock")
        assert instance.name == "mock"

    def test_register_duplicate_overwrites(self):
        """重复注册同名适配器覆盖旧版本"""
        registry = AdapterRegistry()

        class AdapterV1:
            @property
            def name(self): return "v1"
            @property
            def supports_hooks(self): return False
            @property
            def hook_point_map(self): return {}
            def get_capabilities(self): return PlatformCapability()
            def translate_hooks(self, hooks_config, harness_root=None): return {"version": 1}
            def get_settings_path(self, project_dir): return ""
            def merge_settings(self, existing, new_hooks, harness_root=""): return existing

        class AdapterV2:
            @property
            def name(self): return "v2"
            @property
            def supports_hooks(self): return False
            @property
            def hook_point_map(self): return {}
            def get_capabilities(self): return PlatformCapability()
            def translate_hooks(self, hooks_config, harness_root=None): return {"version": 2}
            def get_settings_path(self, project_dir): return ""
            def merge_settings(self, existing, new_hooks, harness_root=""): return existing

        registry.register("test-adapter", AdapterV1)
        registry.register("test-adapter", AdapterV2)
        instance = registry.get_instance("test-adapter")
        assert instance.translate_hooks({}) == {"version": 2}


class TestAdapterRegistryStats:

    def test_stats_returns_dict(self):
        """stats() 返回包含关键信息的字典"""
        registry = get_adapter_registry()
        stats = registry.stats()
        assert "total_adapters" in stats
        assert "adapter_names" in stats
        assert "discovered" in stats
        assert stats["total_adapters"] >= 5


# ═══════════════════════════════════════════════════════════════
#  2. IAgentAdapter S-1 增强（hook_point_map + get_capabilities）
# ═══════════════════════════════════════════════════════════════

class TestIAgentAdapterEnhancement:

    def test_all_adapters_have_hook_point_map(self):
        """所有内置适配器都有 hook_point_map 属性"""
        registry = get_adapter_registry()
        for name in registry.list_adapters():
            adapter = registry.get_instance(name)
            assert hasattr(adapter, "hook_point_map"), f"{name} missing hook_point_map"
            assert isinstance(adapter.hook_point_map, dict), f"{name} hook_point_map not dict"

    def test_all_adapters_have_get_capabilities(self):
        """所有内置适配器都有 get_capabilities() 方法"""
        registry = get_adapter_registry()
        for name in registry.list_adapters():
            adapter = registry.get_instance(name)
            assert hasattr(adapter, "get_capabilities"), f"{name} missing get_capabilities"
            caps = adapter.get_capabilities()
            assert isinstance(caps, PlatformCapability), f"{name} get_capabilities not PlatformCapability"

    def test_claude_code_hook_point_map(self):
        """Claude Code hook_point_map 包含关键映射"""
        adapter = get_adapter_registry().get_instance("claude-code")
        map_ = adapter.hook_point_map
        assert "session_start" in map_
        assert map_["session_start"] == "SessionStart"
        assert "pre_tool_use" in map_
        assert map_["pre_tool_use"] == "PreToolUse"

    def test_claude_code_capabilities(self):
        """Claude Code 支持 realtime_block 但不支持 realtime_redact"""
        adapter = get_adapter_registry().get_instance("claude-code")
        caps = adapter.get_capabilities()
        assert caps.supports_realtime_block is True
        assert caps.supports_realtime_redact is False

    def test_hermes_capabilities_all_false(self):
        """Hermes 不支持任何原生治理能力（MCP 工具实现）"""
        adapter = get_adapter_registry().get_instance("hermes")
        caps = adapter.get_capabilities()
        assert caps.supports_realtime_block is False
        assert caps.supports_realtime_redact is False
        assert caps.supports_pii_detection is False


# ═══════════════════════════════════════════════════════════════
#  3. PlatformCapability 数据类
# ═══════════════════════════════════════════════════════════════

class TestPlatformCapability:

    def test_default_all_false(self):
        """默认值全部 False/空列表"""
        caps = PlatformCapability()
        assert caps.supports_realtime_redact is False
        assert caps.supports_realtime_block is False
        assert caps.supports_pii_detection is False
        assert caps.pii_types_supported == []
        assert caps.supports_compliance_scan is False
        assert caps.compliance_engines == []

    def test_has_full_guardrail_property(self):
        """has_full_guardrail = realtime_redact AND realtime_block"""
        caps = PlatformCapability(supports_realtime_redact=True, supports_realtime_block=True)
        assert caps.has_full_guardrail is True

        caps2 = PlatformCapability(supports_realtime_redact=True, supports_realtime_block=False)
        assert caps2.has_full_guardrail is False

    def test_has_partial_pii_property(self):
        """has_partial_pii = pii_detection OR non-empty pii_types_supported"""
        caps = PlatformCapability(supports_pii_detection=True)
        assert caps.has_partial_pii is True

        caps2 = PlatformCapability(pii_types_supported=["email", "phone"])
        assert caps2.has_partial_pii is True

        caps3 = PlatformCapability()
        assert caps3.has_partial_pii is False

    def test_summary(self):
        """summary() 返回人类可读描述"""
        caps = PlatformCapability(
            supports_realtime_block=True,
            pii_types_supported=["email"],
            compliance_engines=["builtin"],
        )
        s = caps.summary()
        assert "realtime-block" in s
        assert "email" in s
        assert "builtin" in s


# ═══════════════════════════════════════════════════════════════
#  4. ExecutionStrategy 枚举（S-5 预留）
# ═══════════════════════════════════════════════════════════════

class TestExecutionStrategy:

    def test_enum_values(self):
        """ExecutionStrategy 有三个值"""
        assert ExecutionStrategy.ENHANCEMENT is not None
        assert ExecutionStrategy.COOPERATIVE is not None
        assert ExecutionStrategy.FALLBACK is not None

    def test_enum_members(self):
        """枚举成员数量正确"""
        members = list(ExecutionStrategy)
        assert len(members) == 3


# ═══════════════════════════════════════════════════════════════
#  5. 自定义适配器自动发现（AgentX 示例）
# ═══════════════════════════════════════════════════════════════

AGENT_X_ADAPTER_CODE = '''
"""AgentX 示例适配器——验证 S-1 自动发现机制"""

from pathlib import Path
from harness.adapters.base import IAgentAdapter
from harness.types import PlatformCapability


class AgentXAdapter:
    """AgentX 平台适配器——1 个 .py 文件实现完整接入"""

    @property
    def name(self) -> str:
        return "agentx"

    @property
    def supports_hooks(self) -> bool:
        return True

    @property
    def hook_point_map(self) -> dict:
        return {
            "session_start": "onSessionBegin",
            "session_end": "onSessionEnd",
            "pre_execute": "onTaskBefore",
            "post_execute": "onTaskAfter",
            "pre_tool_use": "onToolBefore",
            "post_tool_use": "onToolAfter",
        }

    def get_capabilities(self) -> PlatformCapability:
        return PlatformCapability(
            supports_realtime_block=True,
            supports_compliance_scan=True,
            compliance_engines=["builtin"],
        )

    def translate_hooks(self, hooks_config, harness_root=None):
        """将 harness hooks 翻译为 AgentX 配置格式"""
        result = {}
        for hook_point, hook_list in hooks_config.items():
            agentx_event = self.hook_point_map.get(hook_point, hook_point)
            result[agentx_event] = [
                {"action": hc.get("command", hc.get("skill_id", "")), "type": hc.get("type", "")}
                for hc in hook_list
            ]
        return result

    def get_settings_path(self, project_dir: str) -> str:
        return str(Path(project_dir) / ".agentx" / "config.json")

    def merge_settings(self, existing, new_hooks, harness_root=""):
        result = dict(existing)
        for key, value in new_hooks.items():
            result[key] = value
        return result
'''


class TestAdapterDiscovery:

    def test_discover_from_directory(self):
        """从 .harness/adapters/ 目录自动发现自定义适配器"""
        registry = AdapterRegistry()

        # 创建临时目录模拟 .harness/adapters/
        with tempfile.TemporaryDirectory() as tmpdir:
            adapters_dir = Path(tmpdir) / "adapters"
            adapters_dir.mkdir()

            # 写入 AgentXAdapter
            agentx_path = adapters_dir / "agentx_adapter.py"
            agentx_path.write_text(AGENT_X_ADAPTER_CODE)

            discovered = registry._discover_from_directory(adapters_dir)

            # AgentXAdapter 应被发现并注册
            assert "agentx" in discovered
            assert registry.has("agentx")

    def test_discover_skips_non_adapter_files(self):
        """发现过程跳过非适配器文件（没有 IAgentAdapter 实现的 .py）"""
        registry = AdapterRegistry()

        with tempfile.TemporaryDirectory() as tmpdir:
            adapters_dir = Path(tmpdir) / "adapters"
            adapters_dir.mkdir()

            # 写入非适配器文件
            helper_path = adapters_dir / "helper.py"
            helper_path.write_text("def some_helper(): return 42\n")

            discovered = registry._discover_from_directory(adapters_dir)
            # helper.py 不含适配器类，应被跳过
            assert "helper" not in discovered
            assert not registry.has("helper")

    def test_agentx_adapter_functional(self):
        """AgentX 适配器实现完整功能——translate_hooks, get_capabilities"""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapters_dir = Path(tmpdir) / "adapters"
            adapters_dir.mkdir()

            agentx_path = adapters_dir / "agentx_adapter.py"
            agentx_path.write_text(AGENT_X_ADAPTER_CODE)

            registry = AdapterRegistry()
            registry._discover_from_directory(adapters_dir)

            adapter = registry.get_instance("agentx")

            # 验证核心功能
            assert adapter.name == "agentx"
            assert adapter.supports_hooks is True
            assert isinstance(adapter.hook_point_map, dict)
            assert adapter.hook_point_map["session_start"] == "onSessionBegin"

            caps = adapter.get_capabilities()
            assert isinstance(caps, PlatformCapability)
            assert caps.supports_realtime_block is True
            assert caps.supports_compliance_scan is True

            # translate_hooks 验证
            hooks = {"session_start": [{"type": "script", "command": "check.sh"}]}
            result = adapter.translate_hooks(hooks)
            assert "onSessionBegin" in result

    def test_full_discover_includes_builtin_and_custom(self):
        """discover() 同时包含内置和自定义适配器"""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapters_dir = Path(tmpdir) / "adapters"
            adapters_dir.mkdir()

            agentx_path = adapters_dir / "agentx_adapter.py"
            agentx_path.write_text(AGENT_X_ADAPTER_CODE)

            registry = AdapterRegistry()
            registry._register_builtin()  # 内置适配器
            # 自定义适配器发现
            registry._discover_from_directory(adapters_dir)

            all_adapters = registry.list_adapters()
            # 5 内置 + 1 自定义
            assert len(all_adapters) >= 6
            assert "agentx" in all_adapters
            assert "claude-code" in all_adapters

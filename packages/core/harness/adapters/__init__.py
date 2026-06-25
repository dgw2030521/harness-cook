"""
harness-cook Agent 适配器

S-1 重构：Bridge 通过 AdapterRegistry（替代硬编码 _ADAPTERS）管理适配器。
注册/发现三层机制：builtin → .harness/adapters/ → harness/adapters/ 目录扫描。

内置适配器：
  - ClaudeCodeAdapter: 默认，翻译成 Claude Code settings.json 格式
  - OpenAIAdapter: 验证适配器模式可行性，翻译成 OpenAI function calling 格式
  - HermesAdapter: 翻译成 Hermes YAML 配置格式
  - CopilotCLIAdapter: 翻译成 Copilot CLI MCP 配置格式
  - CursorAdapter: 翻译成 Cursor IDE MCP 配置格式

每个适配器实现 IAgentAdapter 协议：
  - name: 适配器名称标识
  - supports_hooks: 是否支持原生 hook 自动触发
  - hook_point_map: harness slot → 平台原生事件的映射表（S-1 新增）
  - get_capabilities(): 平台治理能力声明（S-1/S-5 新增）
  - translate_hooks(): Profile hooks → 平台配置格式
  - get_settings_path(): 配置文件路径
  - merge_settings(): 配置合并策略
"""

from harness.adapters.base import IAgentAdapter
from harness.adapters.claude_code import ClaudeCodeAdapter, HOOK_POINT_MAP as CLAUDE_HOOK_MAP
from harness.adapters.openai import OpenAIAdapter
from harness.adapters.hermes import HermesAdapter, HERMES_HOOK_POINT_MAP
from harness.adapters.copilot_cli import CopilotCLIAdapter, HOOK_POINT_MAP as COPILOT_HOOK_MAP
from harness.adapters.cursor import CursorAdapter

# S-1：AdapterRegistry 在 bridge.py 中定义，通过 bridge 导入
from harness.bridge import AdapterRegistry, get_adapter_registry

__all__ = [
    "IAgentAdapter",
    "ClaudeCodeAdapter",
    "OpenAIAdapter",
    "HermesAdapter",
    "CopilotCLIAdapter",
    "CursorAdapter",
    "AdapterRegistry",
    "get_adapter_registry",
]

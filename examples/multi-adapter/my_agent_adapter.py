#!/usr/bin/env python3
"""
极简自定义 Agent 适配器——演示"未来新 agent 接入"路径。

harness-cook 的 adapter 机制：新 agent 平台只需实现 IAgentAdapter 的几个方法
（name / supports_hooks / get_capabilities / translate_hooks / get_settings_path
 / merge_settings），手动 register 到 AdapterRegistry（或放进 .harness/adapters/
 被 discover 自动扫描），即可被 bridge.deploy(adapter_name=...) 端到端翻译。

本 adapter 模拟一个"无原生 hook、走 MCP 降级"的新平台（形态仿 cursor）：
  - supports_hooks=False → gate/hooks 不自动强制执行，靠 MCP 工具 + prompt + git 降级
  - 故意【不实现】translate_gates_to_hooks → 展示无-hooks 平台 gate 走降级路径
  - 自定义 hook_point_map（事件名与 Claude Code / Hermes 都不同）→ 展示"新 agent 新事件名"
"""

import sys
from pathlib import Path

# 把 harness core 加入 sys.path（demo 自包含，不依赖外部 PYTHONPATH）
_HARNESS_ROOT = Path(__file__).resolve().parent.parent.parent
_CORE = _HARNESS_ROOT / "packages" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))


# 新 agent 自定义的 hook 点映射——事件名是平台原生的，与 Claude Code（SessionStart）
# / Hermes（on_session_start）都不同，展示"每个 adapter 有自己的映射表"。
MY_AGENT_HOOK_POINT_MAP = {
    "session_start": "my_agent_on_start",
    "session_end":   "my_agent_on_end",
    "pre_execute":   "my_agent_before_task",
    "post_execute":  "my_agent_after_task",
    "on_error":      "my_agent_on_error",
    "pre_tool_use":  "my_agent_before_tool",
    "post_tool_use": "my_agent_after_tool",
}


class MyAgentAdapter:
    """极简自定义 adapter——演示新 agent 接入只需实现这几个方法。

    不继承 IAgentAdapter（Protocol 是结构子类型，bridge 用 hasattr/getattr 检测，
    不依赖 isinstance）。实现 IAgentAdapter 的全部必须方法 + hook_point_map，
    故意不实现可选的 translate_gates_to_hooks。
    """

    @property
    def name(self) -> str:
        return "my-agent"

    @property
    def supports_hooks(self) -> bool:
        # 假设新 agent 无原生 hook 自动触发 → 走 MCP 降级（S-5 FALLBACK）
        return False

    @property
    def hook_point_map(self) -> dict:
        return MY_AGENT_HOOK_POINT_MAP

    def get_capabilities(self):
        """新 agent 能力声明——无实时阻断/脱敏/合规扫描，全部走 MCP 工具降级。"""
        from harness.types import PlatformCapability
        return PlatformCapability(
            supports_realtime_redact=False,
            supports_realtime_block=False,
            supports_pii_detection=False,
            pii_types_supported=[],
            supports_compliance_scan=False,
            compliance_engines=[],
        )

    def translate_hooks(self, hooks_config: dict, harness_root=None) -> dict:
        """无原生 hook：hook 配置降级为 metadata（不执行，仅保留供参考）。

        治理靠 MCP 工具调用——与 cursor adapter 一致的降级形态。
        """
        return {
            "mcpServers": {
                "harness-cook": {
                    "command": "harness-mcp",
                    "note": "新 agent 通过 MCP 接入治理工具",
                },
            },
            "harness_metadata": {
                "hooks_config": {
                    hp: [
                        {"trigger": MY_AGENT_HOOK_POINT_MAP.get(hp, f"custom_{hp}"), **h}
                        for h in hl
                    ]
                    for hp, hl in hooks_config.items()
                },
                "note": "my-agent 无原生 hook；hook 配置仅作 metadata 保留，治理经 MCP 工具",
            },
        }

    def get_settings_path(self, project_dir: str) -> str:
        return str(Path(project_dir) / ".myagent" / "config.json")

    def merge_settings(self, existing: dict, new_hooks: dict, harness_root: str = "") -> dict:
        """简单合并：新 key 覆盖旧 key（demo 用，不追求去重语义）。"""
        result = dict(existing) if isinstance(existing, dict) else {}
        for k, v in new_hooks.items():
            result[k] = v
        return result

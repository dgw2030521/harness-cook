"""
harness-cook Copilot CLI 适配器

将 harness Profile 翻译为 GitHub Copilot CLI 的 MCP 配置格式。

Copilot CLI 使用 .copilot/config.json 配置 MCP 工具连接：
  - 配置路径: .copilot/config.json
  - MCP server 定义格式与 Claude Code 类似，但结构略有不同
  - Copilot CLI 的 hook 机制通过 MCP 工具调用实现

Copilot CLI 配置格式:
{
    "mcpServers": {
        "harness-cook": {
            "command": "python3",
            "args": ["-m", "harness_mcp_server"],
            "env": {...}
        }
    }
}
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

from harness.adapters.base import IAgentAdapter
from harness.config import resolve_harness_root, resolve_hook_command

logger = logging.getLogger("harness.adapters.copilot_cli")


# ─── Copilot CLI hook 点映射 ──────────────────────────────────

HOOK_POINT_MAP = {
    # 会话级 → Copilot CLI 没有 session hook，映射为 MCP 工具
    "session_start": "on_session_start",
    "session_end": "on_session_end",

    # 工具级 → Copilot CLI 的 tool hooks
    "pre_tool_use": "on_pre_tool_use",
    "post_tool_use": "on_post_tool_use",

    # 交互级
    "user_prompt_submit": "on_user_prompt",

    # 任务级
    "pre_execute": "on_pre_execute",
    "post_execute": "on_post_execute",

    # 文件级
    "on_file_change": "on_file_change",
}


class CopilotCLIAdapter(IAgentAdapter):
    """
    Copilot CLI 适配器——将 harness 配置翻译为 Copilot CLI MCP 配置格式

    Copilot CLI 的配置侧重 MCP server 定义，hook 通过 MCP 工具调用实现。
    与 Claude Code 不同，Copilot CLI 不在配置文件中声明 hook 脚本，
    而是通过 MCP server 的工具来执行治理检查。
    """

    @property
    def name(self) -> str:
        return "copilot-cli"

    @property
    def supports_hooks(self) -> bool:
        return True

    @property
    def hook_point_map(self) -> dict:
        """S-1：Copilot CLI hook 点映射表"""
        return HOOK_POINT_MAP

    def get_capabilities(self) -> "PlatformCapability":
        """S-1/S-5：Copilot CLI 平台能力声明"""
        from harness.types import PlatformCapability
        return PlatformCapability(
            supports_realtime_redact=False,
            supports_realtime_block=True,
            supports_pii_detection=False,
            pii_types_supported=[],
            supports_compliance_scan=False,
            compliance_engines=[],
        )

    def translate_hooks(
        self,
        hooks_config: dict,
        harness_root: Optional[str] = None,
    ) -> dict:
        """
        将声明式 hook 配置翻译成 Copilot CLI 配置格式

        Copilot CLI 的 hook 实现为 MCP 工具调用：
        输入: {"session_start": [{"type": "script", "command": "..."}], ...}
        输出: {
            "hooks": {
                "on_session_start": [
                    {"type": "command", "command": "..."}
                ]
            },
            "mcpServers": {
                "harness-cook": {
                    "command": "python3",
                    "args": ["-m", "harness_mcp_server"],
                    "env": {}
                }
            }
        }
        """
        if harness_root is None:
            harness_root = resolve_harness_root()

        # ── hooks 部分 ────────────────────────────────────────
        hooks_result: dict = {}

        for hook_point, hook_list in hooks_config.items():
            copilot_hook_type = HOOK_POINT_MAP.get(hook_point)
            if not copilot_hook_type:
                logger.warning(f"Unknown hook point: {hook_point} — skipping")
                continue

            hooks_array = []
            for hc in hook_list:
                hook_type = hc.get("type", "")

                if hook_type == "script":
                    command = hc.get("command", "")
                    if command:
                        if not self._validate_command(command):
                            logger.warning(f"Rejected unsafe command: {command}")
                            continue
                        absolute_command = resolve_hook_command(command, harness_root)
                        hooks_array.append({
                            "type": "command",
                            "command": absolute_command,
                        })

                elif hook_type == "skill":
                    skill_id = hc.get("skill_id", "")
                    if skill_id:
                        if not self._validate_skill_id(skill_id):
                            logger.warning(f"Rejected unsafe skill_id: {skill_id}")
                            continue
                        run_skill_path = Path(harness_root) / "scripts" / "run-skill.py"
                        hooks_array.append({
                            "type": "command",
                            "command": f"python3 {run_skill_path} {skill_id}",
                        })

                elif hook_type == "prompt":
                    # Copilot CLI 不支持 prompt 类型 hook
                    # 映射为 MCP 工具调用（通过 harness_guardrails_check）
                    message = hc.get("message", "")
                    if message:
                        logger.debug(f"Copilot CLI: prompt hook → MCP tool call (ignored in config)")

            if hooks_array:
                hooks_result[copilot_hook_type] = hooks_array

        # ── MCP server 定义 ────────────────────────────────────
        mcp_server_entry = self._build_mcp_server_entry(harness_root)

        return {
            "hooks": hooks_result,
            "mcpServers": {
                "harness-cook": mcp_server_entry,
            },
        }

    def _build_mcp_server_entry(self, harness_root: str) -> dict:
        """构建 harness-cook MCP server 定义"""
        mcp_server_path = Path(harness_root) / "packages" / "mcp"

        return {
            "command": "python3",
            "args": ["-m", "harness_mcp_server"],
            "env": {
                "HARNESS_COOK_ROOT": harness_root,
                "PYTHONPATH": str(mcp_server_path),
            },
        }

    def get_settings_path(self, project_dir: str) -> str:
        """返回 Copilot CLI 配置文件路径"""
        return str(Path(project_dir) / ".copilot" / "config.json")

    def merge_settings(self, existing: dict, new_hooks: dict, harness_root: str = "") -> dict:
        """合并 hooks + MCP server 定义到现有配置"""
        result = dict(existing)

        # ── 合并 hooks ────────────────────────────────────────
        if "hooks" not in result:
            result["hooks"] = {}

        new_hooks_section = new_hooks.get("hooks", {})
        for hook_type, new_entries in new_hooks_section.items():
            existing_entries = result["hooks"].get(hook_type, [])
            # 合并：harness 的 hook 附加到末尾（不去重，因为 Copilot CLI 不用 matcher）
            merged = existing_entries + [
                e for e in new_entries if e not in existing_entries
            ]
            result["hooks"][hook_type] = merged

        # ── 合并 MCP server 定义 ────────────────────────────────
        if "mcpServers" not in result:
            result["mcpServers"] = {}

        new_mcp_servers = new_hooks.get("mcpServers", {})
        for server_name, server_config in new_mcp_servers.items():
            # harness-cook MCP server 覆盖已有定义
            result["mcpServers"][server_name] = server_config

        return result

    # ─── S-2: 治理语义翻译 ────────────────────────────────────

    def translate_governance(
        self,
        semantics: list,
        harness_root: Optional[str] = None,
    ) -> dict:
        """S-2：将 GovernanceSemantic 列表翻译为 Copilot CLI 检测配置

        Copilot CLI 通过 MCP 工具调用实现治理检测：
          - 所有语义 → MCP server 的 harness_guardrails_check / harness_check 工具
          - 不在 config.json 中声明具体检测规则
          - 依赖 MCP server 的 PatternRegistry 动态检测
        """
        if harness_root is None:
            harness_root = resolve_harness_root()

        # Copilot CLI 的治理通过 MCP 工具调用（不做配置文件翻译）
        # 只记录语义条目信息，由 MCP server 在工具调用时动态检测
        governance_info = []
        for semantic in semantics:
            governance_info.append({
                "semantic_id": semantic.id,
                "pattern_id": semantic.pattern_id,
                "action": semantic.action.value,
                "severity": semantic.severity,
                "scope": semantic.scope,
            })

        # MCP server 配置（提供 harness_guardrails_check 工具）
        mcp_server_entry = self._build_mcp_server_entry(harness_root)

        return {
            "governance_via_mcp": governance_info,
            "mcpServers": {
                "harness-cook": mcp_server_entry,
            },
            "hint": "Copilot CLI governance is enforced via MCP tool calls (harness_guardrails_check)",
        }

    # ─── 内部辅助 ──────────────────────────────────────────

    def _validate_command(self, command: str) -> bool:
        """验证 command 安全性（与 ClaudeCodeAdapter 一致）"""
        if not command:
            return False
        dangerous_patterns = ["|", ";", "&", "`", "$(", "${"]
        for pattern in dangerous_patterns:
            if pattern in command:
                return False
        if ".." in command:
            return False
        return True

    def _validate_skill_id(self, skill_id: str) -> bool:
        """验证 skill_id 安全性（与 ClaudeCodeAdapter 一致）"""
        if not skill_id:
            return False
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', skill_id):
            return False
        return True

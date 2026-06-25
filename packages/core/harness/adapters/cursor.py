"""
harness-cook Cursor 适配器

将 harness Profile 译为 Cursor IDE 的 MCP 配置格式。

Cursor 使用 .cursor/mcp.json 配置 MCP 工具连接：
  - 配置路径: .cursor/mcp.json
  - MCP server 定义格式与 Claude Code 类似
  - Cursor 通过 MCP 协议调用外部工具实现治理

Cursor MCP 配置格式:
{
    "mcpServers": {
        "harness-cook": {
            "command": "python3",
            "args": ["-m", "harness_mcp_server"],
            "env": {...}
        }
    }
}

注意：Cursor 目前不支持 hook 配置（如 PreToolUse/PostToolUse），
只支持 MCP server 注册。因此 translate_hooks 主要产出 MCP server 定义，
hook 脚本部分作为 metadata 附加，供 Cursor 未来扩展使用。
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

from harness.adapters.base import IAgentAdapter
from harness.config import resolve_harness_root, resolve_hook_command

logger = logging.getLogger("harness.adapters.cursor")


class CursorAdapter(IAgentAdapter):
    """
    Cursor 适配器——将 harness 配置翻译为 Cursor IDE MCP 配置格式

    S-1 增强：新增 hook_point_map 属性和 get_capabilities() 方法

    Cursor 的配置侧重 MCP server 定义，不支持 hook 脚本配置。
    治理检查通过 MCP 工具调用实现（harness_check, harness_guardrails_check 等）。
    """

    @property
    def name(self) -> str:
        return "cursor"

    @property
    def supports_hooks(self) -> bool:
        return False

    @property
    def hook_point_map(self) -> dict:
        """S-1：Cursor hook 点映射表

        Cursor 不支持原生 hook，映射仅供治理语义标准化（S-2）参考。
        """
        return {
            "session_start": "on_session_start",
            "session_end": "on_session_end",
            "pre_execute": "before_task",
            "post_execute": "after_task",
            "on_error": "on_error",
            "pre_tool_use": "before_tool",
            "post_tool_use": "after_tool",
        }

    def get_capabilities(self) -> "PlatformCapability":
        """S-1/S-5：Cursor 平台能力声明"""
        from harness.types import PlatformCapability
        return PlatformCapability(
            supports_realtime_redact=False,
            supports_realtime_block=False,
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
        将声明式 hook 配置翻译成 Cursor MCP 配置格式

        Cursor 不支持 hook 脚本配置，translate_hooks 主要产出 MCP server 定义。
        hook 配置作为 metadata 附加（供 Cursor 未来扩展或手动参考）。

        输入: {"session_start": [{"type": "script", "command": "..."}], ...}
        输出: {
            "mcpServers": {
                "harness-cook": {
                    "command": "python3",
                    "args": ["-m", "harness_mcp_server"],
                    "env": {...}
                }
            },
            "harness_metadata": {
                "hooks_config": {...},
                "note": "Cursor does not support hook scripts; governance via MCP tools"
            }
        }
        """
        if harness_root is None:
            harness_root = resolve_harness_root()

        # ── MCP server 定义（核心产出）──────────────────────────
        mcp_server_entry = self._build_mcp_server_entry(harness_root)

        # ── hook 配置作为 metadata ──────────────────────────────
        # Cursor 不执行 hook 脚本，但保留原始配置供参考
        sanitized_hooks = {}
        for hook_point, hook_list in hooks_config.items():
            sanitized_entries = []
            for hc in hook_list:
                hook_type = hc.get("type", "")
                if hook_type == "script":
                    command = hc.get("command", "")
                    if command and self._validate_command(command):
                        absolute_command = resolve_hook_command(command, harness_root)
                        sanitized_entries.append({
                            "type": "command",
                            "command": absolute_command,
                        })
                elif hook_type == "skill":
                    skill_id = hc.get("skill_id", "")
                    if skill_id and self._validate_skill_id(skill_id):
                        run_skill_path = Path(harness_root) / "scripts" / "run-skill.py"
                        sanitized_entries.append({
                            "type": "command",
                            "command": f"python3 {run_skill_path} {skill_id}",
                        })
            if sanitized_entries:
                sanitized_hooks[hook_point] = sanitized_entries

        return {
            "mcpServers": {
                "harness-cook": mcp_server_entry,
            },
            "harness_metadata": {
                "hooks_config": sanitized_hooks,
                "note": "Cursor does not support hook scripts; governance via MCP tools",
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
        """返回 Cursor MCP 配置文件路径"""
        return str(Path(project_dir) / ".cursor" / "mcp.json")

    def merge_settings(self, existing: dict, new_hooks: dict, harness_root: str = "") -> dict:
        """合并 MCP server 定义到现有配置"""
        result = dict(existing)

        # ── 合并 MCP server 定义 ────────────────────────────────
        if "mcpServers" not in result:
            result["mcpServers"] = {}

        new_mcp_servers = new_hooks.get("mcpServers", {})
        for server_name, server_config in new_mcp_servers.items():
            # harness-cook MCP server 覆盖已有定义
            result["mcpServers"][server_name] = server_config

        # ── 合并 metadata（附加，不覆盖）──────────────────────────
        if "harness_metadata" not in result:
            result["harness_metadata"] = {}

        new_metadata = new_hooks.get("harness_metadata", {})
        if new_metadata:
            # 合并 hooks_config（保留已有的 + 附加新的）
            existing_hooks = result["harness_metadata"].get("hooks_config", {})
            new_hooks_config = new_metadata.get("hooks_config", {})
            for key, entries in new_hooks_config.items():
                existing_hooks[key] = entries
            result["harness_metadata"]["hooks_config"] = existing_hooks
            result["harness_metadata"]["note"] = new_metadata.get("note", "")

        return result

    # ─── S-2: 治理语义翻译 ────────────────────────────────────

    def translate_governance(
        self,
        semantics: list,
        harness_root: Optional[str] = None,
    ) -> dict:
        """S-2：将 GovernanceSemantic 列表翻译为 Cursor 检测配置

        Cursor 通过 .cursorrules 文件实现治理提示：
          - 所有语义 → .cursorrules 中的检测规则描述
          - 无原生 hook 支持，依赖提示词 + MCP 工具
        """
        rules_lines = []
        rules_lines.append("# ═══ harness 治理规则（自动生成，勿手动编辑）═══")
        rules_lines.append("")

        for semantic in semantics:
            action_label = {
                "detect": "⚠️ 检测",
                "redact": "🔒 脱敏",
                "block": "🚫 阻断",
                "warn": "⚠️ 警告",
            }.get(semantic.action.value, "⚠️ 检测")

            rule_line = (
                f"{action_label} {semantic.description} "
                f"(severity={semantic.severity}, scope={semantic.scope})"
            )
            rules_lines.append(rule_line)

            # 添加具体的检测模式描述
            if semantic.pattern_id:
                from harness.pattern_registry import get_pattern_registry
                pattern = get_pattern_registry().get(semantic.pattern_id)
                if pattern:
                    rules_lines.append(f"  Pattern: {pattern.description}")
                    rules_lines.append(f"  Remediation: {pattern.remediation}")

        rules_lines.append("")
        rules_lines.append("检测由 harness MCP 工具 (harness_guardrails_check) 执行")

        return {
            "cursorrules_content": "\n".join(rules_lines),
            "hint": "Cursor governance is enforced via .cursorrules prompts + MCP tool calls",
        }

    # ─── 内部辅助 ──────────────────────────────────────────

    def _validate_command(self, command: str) -> bool:
        """验证 command 安全性"""
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
        """验证 skill_id 安全性"""
        if not skill_id:
            return False
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', skill_id):
            return False
        return True

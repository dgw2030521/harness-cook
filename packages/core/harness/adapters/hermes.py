"""
harness-cook Hermes 适配器

将 harness Profile 翻译为 Hermes 全局 MCP 配置格式。

治理路径：Hermes 不支持项目级配置，也没有原生 hooks 自动触发机制。
因此 Hermes 的治理通过 MCP Server 实现：
  - Hermes 连接 harness-cook MCP Server（全局配置一次）
  - MCP Server 在运行时读取项目的 .harness/ 目录获取项目级治理规则
  - Hermes 调用 harness_check / harness_guardrails_check 等 MCP 工具执行治理

这与 Cursor 适配器的策略一致：无-hooks 平台 → MCP + Gate Prompt 双通道治理。

Hermes 配置格式（YAML，全局）：
  mcpServers:
    harness-cook:
      command: python3
      args: ["-m", "harness_mcp_server"]
      env:
        HARNESS_COOK_ROOT: <安装路径>
  harness_metadata:
    hooks_config: {...}     # 原始 hook 配置，供参考/调试
    note: "..."

注意：MCP Server 注册是全局的（不依赖项目路径），但治理内容是项目级的。
MCP Server 启动时通过 HARNESS_COOK_ROOT + 当前工作目录定位项目配置。
"""

import logging
import os
from pathlib import Path
from typing import Optional

import yaml

from harness.adapters.base import IAgentAdapter
from harness.config import resolve_harness_root, resolve_hook_command
from harness.hook_registry import HookPointRegistry

logger = logging.getLogger("harness.adapters.hermes")


# ─── Hermes hook 点映射 ──────────────────────────

HERMES_HOOK_POINT_MAP = {
    # 会话级
    "session_start": "on_session_start",
    "session_end":   "on_session_end",

    # 任务级（Hermes 有原生任务级概念）
    "pre_execute":   "before_task",
    "post_execute":  "after_task",
    "on_error":      "on_error",

    # 工具级
    "pre_tool_use":  "before_tool",
    "post_tool_use": "after_tool",
}

# 模块加载时注册到全局注册表
HookPointRegistry.register("hermes", HERMES_HOOK_POINT_MAP)


class HermesAdapter(IAgentAdapter):
    """
    Hermes 适配器——将 harness 配置翻译为 Hermes 全局 MCP 配置格式

    S-1 增强：新增 hook_point_map 属性和 get_capabilities() 方法

    Hermes 没有项目级配置，也没有原生 hooks 自动触发机制。
    治理通过 MCP Server 实现：Hermes 调用 MCP 工具 → MCP Server 读项目 .harness/ → 执行治理。

    用法:
        adapter = HermesAdapter()
        hermes_config = adapter.translate_hooks(profile.hooks, harness_root)
    """

    @property
    def name(self) -> str:
        return "hermes"

    @property
    def supports_hooks(self) -> bool:
        """Hermes 不支持原生 hooks 自动触发，治理通过 MCP Server 实现"""
        return False

    @property
    def hook_point_map(self) -> dict:
        """S-1：Hermes hook 点映射表"""
        return HERMES_HOOK_POINT_MAP

    def get_capabilities(self) -> "PlatformCapability":
        """S-1/S-5：Hermes 平台能力声明"""
        from harness.types import PlatformCapability
        return PlatformCapability(
            supports_realtime_redact=False,
            supports_realtime_block=False,   # Hermes 不支持原生阻止
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
        将 Profile hooks 配置翻译为 Hermes 全局 MCP 配置格式

        Hermes 治理路径：MCP Server + Gate Prompt，不依赖 hooks 自动触发。
        translate_hooks 主要产出：
          1. MCP Server 定义（核心——让 Hermes 能调用 harness 工具）
          2. hook 配置作为 metadata（原始配置保留供参考/调试）

        输入: {"session_start": [{"type": "script", "command": "..."}], ...}
        输出: {
            "mcpServers": {
                "harness-cook": { command, args, env }
            },
            "harness_metadata": {
                hooks_config: {...},
                note: "Hermes governance via MCP tools"
            }
        }

        Args:
            hooks_config: Profile 中声明的 hooks 配置
            harness_root: harness-cook 安装目录

        Returns:
            Hermes 全局 MCP 配置字典
        """
        if harness_root is None:
            harness_root = resolve_harness_root()

        # ── MCP Server 定义（核心产出）──────────────────────────
        mcp_server_entry = self._build_mcp_server_entry(harness_root)

        # ── hook 配置作为 metadata ──────────────────────────────
        # Hermes 不自动执行 hook 脚本，但保留原始配置供参考/调试
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
                            "trigger": self._map_hook_to_trigger(hook_point),
                        })
                elif hook_type == "skill":
                    skill_id = hc.get("skill_id", "")
                    if skill_id and self._validate_skill_id(skill_id):
                        sanitized_entries.append({
                            "type": "skill",
                            "skill_id": skill_id,
                            "trigger": self._map_hook_to_trigger(hook_point),
                        })
                elif hook_type == "prompt":
                    message = hc.get("message", "")
                    if message:
                        sanitized_entries.append({
                            "type": "prompt",
                            "message": message,
                            "trigger": self._map_hook_to_trigger(hook_point),
                        })
            if sanitized_entries:
                sanitized_hooks[hook_point] = sanitized_entries

        return {
            "mcpServers": {
                "harness-cook": mcp_server_entry,
            },
            "harness_metadata": {
                "hooks_config": sanitized_hooks,
                "note": "Hermes governance via MCP tools; no native hook execution",
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
        """
        返回 Hermes 全局配置文件路径

        Hermes 只有全局配置，不支持项目级配置。
        MCP Server 注册写入全局配置，MCP Server 运行时通过工作目录定位项目。

        全局配置路径优先级：
          1. ~/.hermes/config.yaml（用户主目录）
          2. 环境变量 HERMES_CONFIG_PATH（自定义路径）

        Args:
            project_dir: 项目目录（仅用于日志，不影响路径）
        """
        env_path = os.environ.get("HERMES_CONFIG_PATH")
        if env_path:
            logger.info(f"Using HERMES_CONFIG_PATH: {env_path}")
            return env_path

        home = Path.home()
        return str(home / ".hermes" / "config.yaml")

    def merge_settings(self, existing: dict, new_hooks: dict, harness_root: str = "") -> dict:
        """
        将翻译后的配置合并到 Hermes 全局现有配置中

        合并策略：
          - MCP server 定义：harness-cook 覆盖已有定义（确保最新版本）
          - metadata：追加合并（不覆盖已有项目配置）

        Args:
            existing: 现有全局配置
            new_hooks: 翻译后的配置
            harness_root: harness-cook 安装目录

        Returns:
            合并后的全局配置
        """
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

    def export_yaml(self, config: dict, output_path: str) -> None:
        """
        将配置导出为 YAML 文件（Hermes 全局配置格式）

        Args:
            config: 配置字典
            output_path: 输出文件路径
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        logger.info(f"Exported Hermes config to {output_path}")

    # ─── S-2: 治理语义翻译 ────────────────────────────────────

    def translate_governance(
        self,
        semantics: list,
        harness_root: Optional[str] = None,
    ) -> dict:
        """S-2：将 GovernanceSemantic 列表翻译为 Hermes 检测配置

        Hermes 通过 MCP Server 工具调用实现治理检测：
          - 所有语义 → harness_guardrails_check MCP 工具调用
          - 无原生 hook 支持，治理依赖 MCP 工具
        """
        governance_info = []
        for semantic in semantics:
            governance_info.append({
                "semantic_id": semantic.id,
                "pattern_id": semantic.pattern_id,
                "action": semantic.action.value,
                "severity": semantic.severity,
                "scope": semantic.scope,
            })

        return {
            "governance_via_mcp": governance_info,
            "hint": "Hermes governance is enforced via MCP tool calls (harness_guardrails_check)",
        }

    # ─── 内部辅助 ──────────────────────────────────────────

    def _map_hook_to_trigger(self, hook_point: str) -> str:
        """将 harness hook 点映射为 Hermes trigger

        使用类级常量 HERMES_HOOK_POINT_MAP 作为映射源，
        未映射的槽位降级为 custom_<hook_point>。
        """
        return HERMES_HOOK_POINT_MAP.get(hook_point, f"custom_{hook_point}")

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

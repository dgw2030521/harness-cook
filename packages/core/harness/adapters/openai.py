"""
harness-cook OpenAI 适配器

将 harness Profile 翻译为 OpenAI function calling 格式。

OpenAI function calling 格式:
{
  "name": "function_name",
  "description": "function description",
  "parameters": {
    "type": "object",
    "properties": {...},
    "required": [...]
  }
}

注意：这是一个验证适配器模式可行性的示例实现，
不是完整的 OpenAI 集成（需要 API key、HTTP 请求等）。
"""

import logging
from typing import Optional

from harness.adapters.base import IAgentAdapter

logger = logging.getLogger("harness.adapters.openai")


class OpenAIAdapter(IAgentAdapter):
    """
    OpenAI 适配器——将 harness 配置翻译为 OpenAI function calling 格式

    S-1 增强：新增 hook_point_map 属性和 get_capabilities() 方法

    用法:
        adapter = OpenAIAdapter()
        functions_config = adapter.translate_hooks(profile.hooks, harness_root)
    """

    @property
    def name(self) -> str:
        return "openai"

    @property
    def supports_hooks(self) -> bool:
        return False

    @property
    def hook_point_map(self) -> dict:
        """S-1：OpenAI hook 点映射表

        OpenAI function calling 不支持 hook 概念，
        映射仅供治理语义标准化（S-2）参考。
        """
        return {
            "pre_execute": "function_call_before",
            "post_execute": "function_call_after",
            "on_error": "function_call_error",
        }

    def get_capabilities(self) -> "PlatformCapability":
        """S-1/S-5：OpenAI 平台能力声明"""
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
        将 Profile hooks 配置翻译为 OpenAI function calling 格式

        OpenAI function calling 不支持 hooks 概念，
        所以将 hooks 转换为 function definitions。

        Args:
            hooks_config: Profile 中声明的 hooks 配置
            harness_root: harness-cook 安装目录（OpenAI 不需要）

        Returns:
            OpenAI functions 配置
        """
        functions = []

        for hook_point, hook_list in hooks_config.items():
            for hc in hook_list:
                hook_type = hc.get("type", "")

                if hook_type == "script":
                    command = hc.get("command", "")
                    # 将 script hook 转换为 function definition
                    functions.append({
                        "name": f"hook_{hook_point}",
                        "description": f"Hook function for {hook_point}",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {
                                    "type": "string",
                                    "description": "Command to execute",
                                },
                                "context": {
                                    "type": "object",
                                    "description": "Execution context",
                                },
                            },
                            "required": ["command"],
                        },
                        "metadata": {
                            "hook_point": hook_point,
                            "command": command,
                            "type": "script",
                        },
                    })

                elif hook_type == "skill":
                    skill_id = hc.get("skill_id", "")
                    # 将 skill hook 转换为 function definition
                    functions.append({
                        "name": f"skill_{skill_id}",
                        "description": f"Skill function: {skill_id}",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "skill_id": {
                                    "type": "string",
                                    "description": "Skill identifier",
                                },
                                "context": {
                                    "type": "object",
                                    "description": "Execution context",
                                },
                            },
                            "required": ["skill_id"],
                        },
                        "metadata": {
                            "hook_point": hook_point,
                            "skill_id": skill_id,
                            "type": "skill",
                        },
                    })

        return {"functions": functions}

    def get_settings_path(self, project_dir: str) -> str:
        """
        返回 OpenAI 配置文件路径

        OpenAI 没有本地配置文件，返回空字符串。
        """
        return ""

    def merge_settings(self, existing: dict, new_hooks: dict, harness_root: str = "") -> dict:
        """
        将翻译后的 functions 合并到现有配置中

        Args:
            existing: 现有配置
            new_hooks: 翻译后的 functions

        Returns:
            合并后的配置
        """
        # OpenAI 配置通常包含在 API 请求中，不是本地文件
        # 这里简单合并 functions 列表
        result = dict(existing)

        existing_functions = result.get("functions", [])
        new_functions = new_hooks.get("functions", [])

        # 去重（基于 function name）
        function_names = {f["name"] for f in existing_functions}
        for func in new_functions:
            if func["name"] not in function_names:
                existing_functions.append(func)
                function_names.add(func["name"])

        result["functions"] = existing_functions
        return result

    # ─── S-2: 治理语义翻译 ────────────────────────────────────

    def translate_governance(
        self,
        semantics: list,
        harness_root: Optional[str] = None,
    ) -> dict:
        """S-2：将 GovernanceSemantic 列表翻译为 OpenAI function calling 检测配置

        OpenAI 通过 function calling 实现治理检测：
          - 每个语义 → 一个 function definition（让模型调用检测函数）
          - 无原生 hook 支持，依赖 function calling
        """
        functions = []
        for semantic in semantics:
            functions.append({
                "name": f"governance_{semantic.id}",
                "description": semantic.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Content to check for governance violations",
                        },
                    },
                    "required": ["content"],
                },
                "metadata": {
                    "semantic_id": semantic.id,
                    "pattern_id": semantic.pattern_id,
                    "action": semantic.action.value,
                    "severity": semantic.severity,
                    "scope": semantic.scope,
                },
            })

        return {
            "functions": functions,
            "hint": "OpenAI governance is enforced via function calling",
        }

"""
harness-cook Claude Code 适配器

将 harness Profile 翻译为 Claude Code 的 settings.json 格式。
这是从 bridge.py 中提取的现有逻辑，重构为适配器模式。
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

from harness.adapters.base import IAgentAdapter
from harness.config import resolve_harness_root, resolve_hook_command
from harness.hook_registry import HookPointRegistry

logger = logging.getLogger("harness.adapters.claude_code")


# ─── Claude Code hook 点映射 ──────────────────────────

HOOK_POINT_MAP = {
    # 会话级
    "session_start": "SessionStart",
    "session_end":   "SessionEnd",  # 修正：原映射到 Stop（每轮结束），现映射到 SessionEnd（会话结束）

    # 工具级
    "pre_tool_use":  "PreToolUse",
    "post_tool_use": "PostToolUse",

    # 异常级
    "on_error":      "PostToolUseFailure",  # 工具执行失败时的原生事件

    # 交互级
    "user_prompt_submit": "UserPromptSubmit",

    # 任务级（映射到工具级，因为 Claude Code 没有直接的任务级 hook）
    "pre_execute":   "PreToolUse",
    "post_execute":  "PostToolUse",

    # 文件级（通过 PostToolUse 的 matcher 实现）
    "on_file_change": "PostToolUse",
}

# ─── matcher 精细化——按 hook_point 类型决定触发范围 ──────

# Claude Code matcher 格式："ToolName" 或 "ToolName1|ToolName2"
# 空 matcher = 全局触发（所有工具调用都触发）
# 精细化 matcher = 只对指定工具触发

# 设计原则：
# 1. 只读操作（Read/Grep/Glob）不应触发合规扫描——它们只读取不修改
# 2. 写入操作（Write/Edit）应触发合规扫描——它们修改代码/文件
# 3. Bash 命令应触发输入护栏——可能执行危险命令
# 4. 会话级/交互级保持全局触发——没有工具上下文

HOOK_MATCHER_MAP = {
    # 写入操作触发合规扫描
    "post_tool_use":  "Write|Edit|NotebookEdit",
    "post_execute":   "Write|Edit|NotebookEdit",
    "on_file_change": "Write|Edit|NotebookEdit",

    # Bash 命令触发输入护栏
    "pre_tool_use":  "Bash",
    "pre_execute":   "Bash",

    # 会话级/交互级/异常级保持全局触发
    "session_start":      "",
    "session_end":        "",
    "on_error":           "",
    "user_prompt_submit": "",
}

# 模块加载时注册到全局注册表
HookPointRegistry.register("claude-code", HOOK_POINT_MAP)


class ClaudeCodeAdapter(IAgentAdapter):
    """
    Claude Code 适配器——将 harness 配置翻译为 Claude Code settings.json 格式

    S-1 增强：新增 hook_point_map 属性和 get_capabilities() 方法

    用法:
        adapter = ClaudeCodeAdapter()
        hooks_config = adapter.translate_hooks(profile.hooks, harness_root)
    """

    @property
    def name(self) -> str:
        return "claude-code"

    @property
    def supports_hooks(self) -> bool:
        return True

    @property
    def hook_point_map(self) -> dict:
        """S-1：Claude Code hook 点映射表"""
        return HOOK_POINT_MAP

    def get_capabilities(self) -> "PlatformCapability":
        """S-1/S-5：Claude Code 平台能力声明

        Claude Code 支持 hooks 自动触发但不支持实时脱敏——
        护栏在 hook 触发时检测但无法实时替换内容。
        """
        from harness.types import PlatformCapability
        return PlatformCapability(
            supports_realtime_redact=False,  # CC 不支持内容级实时脱敏替换
            supports_realtime_block=True,    # CC 支持 PreToolUse hook 阻止
            supports_pii_detection=False,    # CC 没有内置 PII 检测
            pii_types_supported=[],          # 无内置 PII 类型支持
            supports_compliance_scan=False,  # CC 没有内置合规扫描
            compliance_engines=[],           # 无内置合规引擎
        )

    def translate_hooks(
        self,
        hooks_config: dict,
        harness_root: Optional[str] = None,
    ) -> dict:
        """
        将声明式 hook 配置翻译成 Claude Code settings.json 格式

        matcher 精细化（E-3 重构）：
        - post_tool_use/post_execute/on_file_change → matcher="Write|Edit|NotebookEdit"
          只读操作（Read/Grep/Glob）不触发合规扫描
        - pre_tool_use/pre_execute → matcher="Bash"
          只有 Bash 命令触发输入护栏
        - 其他槽位保持 matcher="" 全局触发

        输入: {"session_start": [{"type": "script", "command": "..."}], ...}
        输出: {
            "PostToolUse": [
                {"matcher": "Write|Edit|NotebookEdit", "hooks": [...]},
            ],
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [...]},
            ]
        }
        """
        result: dict = {}

        if harness_root is None:
            harness_root = resolve_harness_root()

        # 按 (claude_hook_type, matcher) 组合收集 hooks
        # 同一 Claude Code 原生事件可能有多个 matcher 的 entry
        # 例如 PreToolUse 可能同时有 matcher="Bash" 和 matcher="" 的 entry
        collected: dict[tuple[str, str], list] = {}

        for hook_point, hook_list in hooks_config.items():
            claude_hook_type = HOOK_POINT_MAP.get(hook_point)
            if not claude_hook_type:
                logger.warning(f"Unknown hook point: {hook_point} — skipping")
                continue

            # 从 HOOK_MATCHER_MAP 获取精细化 matcher
            matcher = HOOK_MATCHER_MAP.get(hook_point, "")

            hooks_array = []
            for hc in hook_list:
                hook_type = hc.get("type", "")

                if hook_type == "script":
                    command = hc.get("command", "")
                    if command:
                        # ── 安全加固：验证 command 合法性 ──
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
                        # ── 安全加固：验证 skill_id 合法性 ──
                        if not self._validate_skill_id(skill_id):
                            logger.warning(f"Rejected unsafe skill_id: {skill_id}")
                            continue

                        run_skill_path = Path(harness_root) / "scripts" / "run-skill.py"
                        hooks_array.append({
                            "type": "command",
                            "command": f"python3 {run_skill_path} {skill_id}",
                        })

                elif hook_type == "prompt":
                    message = hc.get("message", "")
                    if message and claude_hook_type == "SessionStart":
                        hooks_array.append({
                            "type": "command",
                            "command": f"echo '{message}'",
                        })

            if hooks_array:
                key = (claude_hook_type, matcher)
                if key not in collected:
                    collected[key] = []
                collected[key].extend(hooks_array)

        # 按 claude_hook_type 分组输出
        for (claude_hook_type, matcher), hooks in collected.items():
            if claude_hook_type not in result:
                result[claude_hook_type] = []
            result[claude_hook_type].append({
                "matcher": matcher,
                "hooks": hooks,
            })

        return result

    def _validate_command(self, command: str) -> bool:
        """
        验证 command 安全性

        检查项：
          1. 禁止危险的 shell 操作符（|、;、&、`、$()）
          2. 禁止路径穿越（../）

        Returns:
            True = 安全，False = 不安全
        """
        if not command:
            return False

        # 禁止危险的 shell 操作符
        dangerous_patterns = ["|", ";", "&", "`", "$(", "${"]
        for pattern in dangerous_patterns:
            if pattern in command:
                return False

        # 禁止路径穿越
        if ".." in command:
            return False

        return True

    def _validate_skill_id(self, skill_id: str) -> bool:
        """
        验证 skill_id 安全性

        检查项：
          1. 禁止路径分隔符（/、\\）
          2. 禁止特殊字符
          3. 只能包含字母、数字、-、_

        Returns:
            True = 安全，False = 不安全
        """
        if not skill_id:
            return False

        # 只允许字母、数字、-、_
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', skill_id):
            return False

        return True

    def get_settings_path(self, project_dir: str) -> str:
        """返回 Claude Code settings.json 路径"""
        return str(Path(project_dir) / ".claude" / "settings.json")

    def merge_settings(self, existing: dict, new_hooks: dict, harness_root: str = "") -> dict:
        """合并 hooks 到现有 settings — 按 matcher 去重，保留用户已有 hook"""
        result = dict(existing)

        if "hooks" not in result:
            result["hooks"] = {}

        for hook_type, new_entries in new_hooks.items():
            existing_entries = result["hooks"].get(hook_type, [])
            merged_entries = self._merge_hook_entries(existing_entries, new_entries)
            result["hooks"][hook_type] = merged_entries

        return result

    def _merge_hook_entries(self, existing: list, new: list) -> list:
        """合并 hook entries — 按 matcher 去重，harness 的 hook 覆盖同 matcher 的旧版本"""
        by_matcher = {}
        for entry in existing:
            matcher = entry.get("matcher", "")
            by_matcher[matcher] = entry

        for entry in new:
            matcher = entry.get("matcher", "")
            # harness 的 hook 覆盖相同 matcher 的旧版本
            by_matcher[matcher] = entry

        return list(by_matcher.values())

    # ─── S-2: 治理语义翻译 ────────────────────────────

    def translate_governance(
        self,
        semantics: list,
        harness_root: Optional[str] = None,
    ) -> dict:
        """S-2：将 GovernanceSemantic 列表翻译为 Claude Code 检测配置

        Claude Code 的治理检测通过 hooks 实现：
          - REDACT/BLOCK/WARN → PreToolUse hook 调用 harness_guardrails_check
          - DETECT → post_execute hook 调用 harness_check

        翻译策略：
          - 每个 semantic → 一个 PreToolUse hook entry（matcher=Write|Edit）
          - hook command = python3 调用 guardrails 检测脚本
          - 同时在 CLAUDE.md 注入提示词（辅助性的，不依赖）
        """
        if harness_root is None:
            harness_root = resolve_harness_root()

        hooks_result = {}
        claude_md_rules = []

        for semantic in semantics:
            # ── 构建 hook entry ──
            # Claude Code 用 PreToolUse hook 调用护栏检测
            action = semantic.action.value  # detect/redact/block/warn
            pattern_id = semantic.pattern_id
            severity = semantic.severity
            scope = semantic.scope

            # 构建 guardrails 检测命令
            # scope="input" → PreToolUse hook (matcher=Bash)
            # scope="output"/"both" → PostToolUse hook (matcher=Write|Edit|NotebookEdit)
            hook_command = (
                f"python3 -m harness_guardrails_bridge "
                f"--action {action} "
                f"--pattern {pattern_id} "
                f"--severity {severity} "
                f"--scope {scope}"
            )

            if scope == "input":
                # 输入护栏 → PreToolUse (matcher=Bash)
                if "PreToolUse" not in hooks_result:
                    hooks_result["PreToolUse"] = []
                hooks_result["PreToolUse"].append({
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": hook_command}],
                })
            else:
                # 输出/双向护栏 → PostToolUse (matcher=Write|Edit|NotebookEdit)
                if "PostToolUse" not in hooks_result:
                    hooks_result["PostToolUse"] = []
                hooks_result["PostToolUse"].append({
                    "matcher": "Write|Edit|NotebookEdit",
                    "hooks": [{"type": "command", "command": hook_command}],
                })

            # ── 构建 CLAUDE.md 提示词规则 ──
            claude_md_rules.append(
                f"- **{semantic.description}** (severity={severity}, action={action})"
            )

        # 组装结果
        return {
            "hooks": hooks_result,
            "claude_md_rules": claude_md_rules,
        }

    # ─── S-5: gates → PreToolUse 拦截 hook ─────────────
    def translate_gates_to_hooks(
        self,
        gate_checks: list,
        default_gate_mode,
        harness_root: Optional[str] = None,
    ) -> dict:
        """将 Profile gates.checks 翻译为 Claude Code PreToolUse 拦截 hook

        兑现原架构意图（bridge.deploy 注释"有-hooks Agent 用轻提示——hooks 已自动强制执行"）：
        gate_checks 非空 → 产出 PreToolUse[matcher=Write|Edit]→hook-gate-pre-write.py，
        写文件前自动 deny 违规。与 PreToolUse[Bash]（输入护栏）按 matcher 并存，
        互不覆盖（merge_settings 按 matcher 去重）。

        gate 脚本运行时从 profile.gates.checks 读检查项、复用 gates.py 的 check_fn，
        故此处只产出"指向 gate 脚本"的固定 entry（单一规则源——不在此处重复声明检查规则）。

        返回格式与 translate_hooks 一致：{"PreToolUse": [{matcher, hooks}]}（无 "hooks" 包裹）。
        """
        if harness_root is None:
            harness_root = resolve_harness_root()

        # 无 enabled 检查 → 不产出（gates 走 prompt 通道即可，避免空 hook 噪音）
        enabled = [c for c in (gate_checks or []) if c.get("enabled", True)]
        if not enabled:
            return {}

        command = "python3 packages/hooks/hook-gate-pre-write.py"
        if not self._validate_command(command):
            logger.error(f"Rejected unsafe gate command: {command}")
            return {}

        gate_command = resolve_hook_command(command, harness_root)
        return {
            "PreToolUse": [
                {
                    "matcher": "Write|Edit",
                    "hooks": [{"type": "command", "command": gate_command}],
                }
            ]
        }

    # ─── 内部辅助 ──────────────────────────────────────


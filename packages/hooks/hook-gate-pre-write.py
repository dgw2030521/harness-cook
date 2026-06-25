#!/usr/bin/env python3
"""
harness PreToolUse 钩子——写文件前的门禁拦截（gate deny）。

职责：在 Claude Code 调用 Write/Edit 工具前，对即将写入的文件内容做门禁检查。
  - 规则源单一：从当前项目的 Profile（.harness/profiles/<active>.yaml）读 gates.checks
    决定要跑哪些检查、以何种模式决策；检查实现复用 gates.py 的 check_fn
    （default_coding_gate().checks 提供 id→check_fn 映射）。
  - 决策遵循 profile 的 default_gate_mode：
      strict → 任何未通过 → deny
      hybrid → critical/high 未通过 → deny，medium/low → allow（仅提示）
      loose  → 全部 allow（仅记录，不 deny）

与 gates→prompt→CLAUDE.md 并行（双通道）：本钩子是自动拦截通道，prompt 是提示通道。
二者均由 bridge.deploy 从同一 profile 翻译而来——单一声明源。

输入（stdin，Claude Code PreToolUse JSON）：
  {"tool_name": "Write|Edit", "tool_input": {"file_path": "...", "content": "..."}}
输出（stdout，Claude Code hookSpecificOutput）：
  {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                          "permissionDecision": "deny"|"allow",
                          "permissionDecisionReason": "...",
                          "additionalContext": "..."}}

环境：CLAUDE_PROJECT_DIR（Claude Code 注入）指向被编辑项目根，据此定位 .harness/profiles。
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("harness.hook.gate-pre-write")


# ─── 接入 harness core（gates.py / config.py / types.py）────────────

def _setup_pythonpath() -> str:
    """把 harness-cook/packages/core 加入 sys.path，返回 harness 根目录。

    优先级：HARNESS_COOK_ROOT 环境变量（bridge 注入）> 从脚本自身路径推导。
    脚本位于 <root>/packages/hooks/，故 root = parents[2]。
    """
    harness_root = (
        os.environ.get("HARNESS_COOK_ROOT")
        or os.environ.get("HARNESS_ROOT")
        or str(Path(__file__).resolve().parents[2])
    )
    core_path = str(Path(harness_root) / "packages" / "core")
    if core_path not in sys.path:
        sys.path.insert(0, core_path)
    return harness_root


# ─── Profile 加载（复用框架的 ProfileLoader，单一选择逻辑）──────────

def _load_profile(project_dir: str):
    """加载当前项目的活跃 Profile。

    用 ProfileLoader(profiles_dir) 定位 <project_dir>/.harness/profiles，
    复用框架的 resolve_active（env > marker > default）选择逻辑与分层查找。
    """
    from harness.config import ProfileLoader

    profiles_dir = Path(project_dir) / ".harness" / "profiles"
    loader = ProfileLoader(str(profiles_dir) if profiles_dir.exists() else None)
    return loader.load()


# ─── 门禁检查执行（复用 gates.py 的 check_fn，不重复定义规则）────────

# severity → 数值，用于比较严重程度
_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}

# hybrid 模式下达到此严重度即 deny（critical/high）
_HYBRID_DENY_THRESHOLD = _SEVERITY_RANK["high"]


def _run_gate_checks(content: str, file_path: str, enabled_ids: set) -> list:
    """对文件内容跑已启用的 check_fn，返回 CheckResult 列表（仅未通过的）。

    check_fn 映射来自 default_coding_gate().checks——框架唯一定义源，
    本钩子不自带任何检测规则（避免与 gates.py 漂移）。
    """
    from harness.gates import default_coding_gate
    from harness.types import Artifact

    artifact = Artifact(type="code", path=file_path, content=content)
    gate = default_coding_gate()

    failed = []
    for check in gate.checks:
        # profile 未声明该 check id 或显式 enabled=false → 跳过
        if check.id not in enabled_ids:
            continue
        try:
            result = check.check_fn(artifact)
        except Exception as e:  # 单条检查异常不拖垮整个门禁
            logger.warning(f"check_fn '{check.id}' raised: {e}")
            continue
        if not result.passed:
            failed.append((check, result))
    return failed


def _should_deny(failed: list, gate_mode) -> bool:
    """按 gate_mode 决策是否 deny。

    strict → 任何未通过即 deny
    hybrid → critical/high 未通过 → deny
    loose  → 从不 deny（仅提示）
    """
    from harness.gates import GateMode

    if not failed:
        return False
    if gate_mode == GateMode.STRICT:
        return True
    if gate_mode == GateMode.HYBRID:
        return any(
            _SEVERITY_RANK.get(getattr(r, "severity", "medium"), 0) >= _HYBRID_DENY_THRESHOLD
            for _, r in failed
        )
    # loose 或未知 → 不 deny
    return False


# ─── 消息格式化 ────────────────────────────────────────────────────

def _format_message(failed: list, file_path: str, denied: bool) -> str:
    """构造反馈给 Claude 的门禁消息（additionalContext）。"""
    if not failed:
        return f"[harness 门禁 ✅] {file_path} — 合规检查通过，无违规发现"

    lines = []
    if denied:
        lines.append("🚫 阻断级违规（已阻止写入，请修复后再试）:")
    else:
        lines.append("⚠️ 门禁警告（已放行，建议修复）:")
    for check, result in failed:
        sev = getattr(result, "severity", "medium")
        msg = getattr(result, "message", "未通过")
        lines.append(f"  • [{sev}] {check.id} — {msg}")
        suggestion = getattr(result, "fix_suggestion", None)
        if suggestion:
            lines.append(f"    └ 修复建议: {suggestion}")
    return "\n".join(lines)


# ─── 审计日志（失败不影响门禁决策）─────────────────────────────────

def _audit(failed: list, denied: bool, gate_mode, file_path: str,
           session_id: str, project_dir: str) -> None:
    try:
        from harness.audit_logger import log_gate_check

        log_gate_check(
            gate_id="pre-write-gate",
            passed=not failed,
            gate_mode=str(gate_mode).split(".")[-1].lower(),
            check_results=[
                {
                    "check_id": check.id,
                    "passed": False,
                    "severity": getattr(result, "severity", "medium"),
                    "message": getattr(result, "message", "未通过"),
                }
                for check, result in failed
            ],
            project_dir=project_dir,
            session_id=session_id,
            file_path=file_path,
            findings_count=len(failed),
            blocked=len(failed) if denied else 0,
        )
    except Exception as e:
        logger.warning(f"audit log failed (不影响门禁决策): {e}")


# ─── 主流程 ────────────────────────────────────────────────────────

def main() -> None:
    _setup_pythonpath()

    # ── 读取 stdin JSON ──
    try:
        input_data = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        # 无法解析输入 → fail-open（不阻断用户正常工作流）
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }))
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {}) or {}

    # ── 只拦截 Write/Edit ──
    if tool_name not in ("Write", "Edit"):
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }))
        return

    file_path = tool_input.get("file_path", "未知文件")
    # Edit 用 new_string，Write 用 content
    content = tool_input.get("new_string") or tool_input.get("content") or ""

    # 无实质内容 → 不扫描
    if len(content) < 10:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }))
        return

    # ── 定位项目目录（Claude Code 注入，回退 cwd）──
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    # ── 加载 profile，取已启用的 check id 集合 + 门禁模式 ──
    try:
        profile = _load_profile(project_dir)
    except Exception as e:
        logger.warning(f"load profile failed (fail-open): {e}")
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "additionalContext": f"[harness 门禁] profile 加载失败，已放行：{e}",
            }
        }))
        return

    gate_checks = getattr(profile, "gate_checks", None) or []
    enabled_ids = {
        c.get("id") for c in gate_checks
        if c.get("id") and c.get("enabled", True)
    }
    gate_mode = getattr(profile, "default_gate_mode", None)

    # 无已启用检查 → 无需拦截（profile 未声明门禁）
    if not enabled_ids:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }))
        return

    # ── 执行门禁检查 ──
    failed = _run_gate_checks(content, file_path, enabled_ids)
    denied = _should_deny(failed, gate_mode)
    message = _format_message(failed, file_path, denied)

    # ── 审计 ──
    _audit(
        failed, denied, gate_mode, file_path,
        input_data.get("session_id", "unknown"), project_dir,
    )

    # ── 输出决策 ──
    if denied:
        deny_reasons = "; ".join(
            f"[{getattr(r, 'severity', 'medium')}] {c.id} — {getattr(r, 'message', '未通过')}"
            for c, r in failed
        )
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "harness 门禁阻断: " + deny_reasons,
                "additionalContext": message,
            },
        }
    else:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "additionalContext": message,
            },
        }

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
harness Stop hook — 任务完成审计

每次 Claude Code session 结束时自动记录审计条目（变更摘要、session 信息），
通过 systemMessage 注入审计摘要。

审计统一走 audit_logger → AuditStore → 自动获得 chain_hash 保护。

stdin JSON 格式:
  { "session_id": "...", "reason": "...", ... }

stdout JSON 格式:
  { "continue": true, "systemMessage": "[harness 审计] ..." }  — 有审计记录
  { "continue": true, "decision": "approve" }                   — 默认允许停止
"""

import sys
import os
import json
import subprocess
from pathlib import Path


def _setup_pythonpath():
    """设置 PYTHONPATH 以导入 harness core 包"""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    core_path = str(Path(project_dir) / "packages" / "core")
    sys.path.insert(0, core_path)


def _get_session_id(input_data: dict) -> str:
    """
    获取 session_id

    优先级：
      1. stdin JSON 的 session_id 字段
      2. .harness/session_id 文件
      3. 降级为 "unknown"
    """
    session_id = input_data.get("session_id")
    if session_id:
        return session_id

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    session_file = Path(project_dir) / ".harness" / "session_id"
    try:
        if session_file.exists():
            sid = session_file.read_text(encoding="utf-8").strip()
            if sid:
                return sid
    except Exception:
        pass

    return "unknown"


def main():
    _setup_pythonpath()

    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        # 无输入 → 允许停止
        print(json.dumps({"continue": True, "decision": "approve"}))
        return

    session_id = _get_session_id(input_data)
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")

    # ── 1. 获取 git 变更摘要 ─────────────────────────────────────
    diff_summary = ""
    files_changed = []
    try:
        diff = subprocess.check_output(
            ["git", "diff", "--stat", "HEAD"],
            cwd=project_dir,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode("utf-8").strip()
        if diff:
            diff_summary = diff[:500]

        # 获取变更文件列表
        diff_names = subprocess.check_output(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=project_dir,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode("utf-8").strip()
        if diff_names:
            files_changed = [f.strip() for f in diff_names.split("\n") if f.strip()]
    except Exception:
        diff_summary = "无变更记录"

    # ── 2. 写入审计记录（统一走 audit_logger → AuditStore）─────
    try:
        from harness.audit_logger import write_audit_log

        filepath = write_audit_log(
            "session_stop",
            project_dir=project_dir,
            session_id=session_id,
            diff_summary=diff_summary,
            files_changed=files_changed,
        )

        # 统计审计记录数
        harness_dir = Path(project_dir) / ".harness" / "audit"
        audit_count = 0
        if harness_dir.exists():
            # 统计层级化目录下所有 .json 文件
            audit_count = len(list(harness_dir.rglob("*.json")))

        msg = "[harness 审计] Session {} 结束。已记录 {} 条审计日志（含链式哈希保护）。变更摘要: {}".format(
            session_id[:20], audit_count, diff_summary[:200] if diff_summary else "无"
        )
        print(json.dumps({"continue": True, "decision": "approve", "systemMessage": msg}, ensure_ascii=False))

    except ImportError:
        # harness 不可用 → 允许停止，不写审计
        print(json.dumps({"continue": True, "decision": "approve"}))
    except Exception:
        # 审计写入失败 → 允许停止，审计不应阻断流程
        print(json.dumps({"continue": True, "decision": "approve"}))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
harness SessionStart hook — 初始化 harness 环境

每次 Claude Code session 启动时自动检查 harness 可用性、初始化 .harness/ 目录，
通过 systemMessage 注入激活确认消息，让用户"感受到" harness 的存在。

同时生成 session_id 并写入 .harness/session_id 文件，供其他 hook 读取。

stdin JSON 格式:
  { "session_id": "...", "cwd": "...", ... }

stdout JSON 格式:
  { "continue": true, "systemMessage": "[harness] v0.1.0 已激活..." }  — harness 可用
  { "continue": true, "systemMessage": "[harness] 未安装..." }          — harness 不可用
"""

import sys
import os
import json
import uuid
from pathlib import Path
from datetime import datetime


def _setup_pythonpath():
    """设置 PYTHONPATH 以导入 harness core 包"""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    core_path = str(Path(project_dir) / "packages" / "core")
    sys.path.insert(0, core_path)


def _generate_session_id() -> str:
    """生成 session_id: session-YYYYMMDD-HHMMSS-XXXX"""
    now = datetime.now()
    short_uuid = uuid.uuid4().hex[:4]
    return "session-{}-{}-{}".format(
        now.strftime("%Y%m%d"),
        now.strftime("%H%M%S"),
        short_uuid,
    )


def main():
    _setup_pythonpath()

    # ── 0. 读取 stdin JSON ────────────────────────────────────
    session_id = None
    try:
        input_data = json.loads(sys.stdin.read())
        session_id = input_data.get("session_id")
    except (json.JSONDecodeError, ValueError):
        pass

    # 如果 stdin 无 session_id，生成一个
    if not session_id:
        session_id = _generate_session_id()

    # ── 1. 检查 harness 可用性 ──────────────────────────────────
    try:
        import harness
        version = harness.__version__
        available = True
    except ImportError:
        version = "N/A"
        available = False

    # ── 2. 初始化 .harness 目录结构 ──────────────────────────────
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    harness_dir = Path(project_dir) / ".harness"
    try:
        harness_dir.mkdir(exist_ok=True)
        (harness_dir / "audit").mkdir(exist_ok=True)
    except Exception:
        pass  # 目录创建失败不影响 session

    # ── 3. 写入 session_id 文件 ─────────────────────────────────
    try:
        session_file = harness_dir / "session_id"
        session_file.write_text(session_id, encoding="utf-8")
    except Exception:
        pass  # session_id 写入失败不影响 session

    # ── 4. 输出激活确认消息 ──────────────────────────────────────
    if available:
        msg = (
            "[harness] v{} 已激活 (session: {})。"
            "合规扫描（Write/Edit 后自动触发）、"
            "PII 护栏（Bash 输出自动检测）、"
            "审计追踪（session 结束时自动记录）"
            "将在操作时自动运行。"
        ).format(version, session_id[:20])
    else:
        msg = "[harness] 未安装。如需激活，请运行: python3 packages/cli/harness_cli.py activate"

    print(json.dumps({"continue": True, "systemMessage": msg}, ensure_ascii=False))


if __name__ == "__main__":
    main()

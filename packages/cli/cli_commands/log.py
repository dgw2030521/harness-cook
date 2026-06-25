#!/usr/bin/env python3
"""
harness log — 查看执行日志

查看 harness-cook 的执行记录：hooks 触发、skills 执行、gates 检查。
数据来源：.harness/audit/ 目录下的 JSON 文件。

用法:
  harness log                     — 查看最近 20 条日志
  harness log --type skill        — 只看 skill 执行日志
  harness log --follow            — 实时跟踪（类似 tail -f）
  harness log --output json       — JSON 格式输出
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime


def _get_user_project_dir() -> str:
    """获取用户项目目录（审计日志所在位置）

    规则：用户在哪个目录启动 Claude Code，.harness/ 就在那个目录。

    解析优先级：
      1. 环境变量 CLAUDE_PROJECT_DIR（Claude Code 启动时自动设置）
      2. 当前工作目录 cwd
    """
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if env_dir:
        return env_dir
    return os.getcwd()


def _load_audit_files(audit_dir: Path) -> list:
    """加载所有审计文件"""
    if not audit_dir.exists():
        return []

    logs = []
    for f in sorted(audit_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            data["_file"] = f.name
            logs.append(data)
        except Exception:
            continue

    return logs


def _filter_logs(logs: list, log_type: str = None, query: str = None, limit: int = 20) -> list:
    """过滤日志"""
    filtered = logs

    if log_type:
        filtered = [l for l in filtered if l.get("event") == log_type or log_type in str(l)]

    if query:
        query_lower = query.lower()
        filtered = [l for l in filtered if query_lower in json.dumps(l).lower()]

    # 按时间倒序
    filtered.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    return filtered[:limit]


def _format_log_table(logs: list) -> str:
    """表格格式输出"""
    if not logs:
        return "  📭 暂无日志记录"

    lines = []
    lines.append("  📋 执行日志（最近 {} 条）".format(len(logs)))
    lines.append("  " + "─" * 70)
    lines.append("  {:20s} {:15s} {:12s} {}".format("时间", "事件", "Agent", "详情"))
    lines.append("  " + "─" * 70)

    for log in logs:
        timestamp = log.get("timestamp", "")[:19]
        event = log.get("event", "unknown")[:15]
        agent = log.get("agent_id", log.get("session_id", ""))[:12]

        # 提取详情
        detail = ""
        if "diff_summary" in log:
            detail = log["diff_summary"][:30]
        elif "hook_type" in log:
            detail = log.get("hook_name", log.get("hook_type", ""))[:30]
        elif "skill_id" in log:
            detail = "skill: {} [{}]".format(log["skill_id"], log.get("status", ""))
        elif "gate_id" in log:
            detail = "gate: {} [{}]".format(log["gate_id"], "pass" if log.get("passed") else "fail")
        elif "error" in log:
            detail = log["error"][:30]

        lines.append("  {:20s} {:15s} {:12s} {}".format(timestamp, event, agent, detail))

    lines.append("  " + "─" * 70)
    return "\n".join(lines)


def _format_log_json(logs: list) -> str:
    """JSON 格式输出"""
    return json.dumps({"total": len(logs), "logs": logs}, ensure_ascii=False, indent=2)


def _follow_logs(audit_dir: Path, interval: float = 2.0):
    """实时跟踪日志（类似 tail -f）"""
    print("  📡 实时跟踪日志（Ctrl+C 退出）...")
    print()

    seen_files = set()
    try:
        while True:
            if audit_dir.exists():
                for f in sorted(audit_dir.glob("*.json")):
                    if f.name not in seen_files:
                        seen_files.add(f.name)
                        try:
                            data = json.loads(f.read_text(encoding="utf-8"))
                            timestamp = data.get("timestamp", "")[:19]
                            event = data.get("event", "unknown")
                            print("  [{}] {}".format(timestamp, event))
                            if "diff_summary" in data:
                                print("    └─ {}".format(data["diff_summary"][:60]))
                        except Exception:
                            pass

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n  👋 停止跟踪")


def cmd_log(args) -> int:
    """harness log 命令执行"""
    user_project_dir = _get_user_project_dir()
    audit_dir = Path(user_project_dir) / ".harness" / "audit"

    if args.follow:
        _follow_logs(audit_dir, interval=args.interval)
        return 0

    # 加载日志
    logs = _load_audit_files(audit_dir)

    if not logs:
        print("  📭 暂无日志记录")
        print("  💡 日志目录: {}".format(audit_dir))
        print("  💡 提示: 执行 harness 操作后会自动生成日志")
        return 0

    # 过滤
    filtered = _filter_logs(
        logs,
        log_type=args.type,
        query=args.query,
        limit=args.limit,
    )

    # 输出
    if args.output == "json":
        print(_format_log_json(filtered))
    else:
        print(_format_log_table(filtered))

    return 0


def add_log_args(subparsers):
    """注册 log 子命令"""
    log_parser = subparsers.add_parser(
        "log",
        help="查看执行日志",
        description="查看 harness-cook 的执行记录：hooks、skills、gates",
    )
    log_parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="搜索关键词",
    )
    log_parser.add_argument(
        "--type",
        choices=["hook", "skill", "gate", "session", "audit"],
        default=None,
        help="按事件类型过滤",
    )
    log_parser.add_argument(
        "--limit", "-n",
        type=int,
        default=20,
        help="显示条数（默认 20）",
    )
    log_parser.add_argument(
        "--follow", "-f",
        action="store_true",
        help="实时跟踪（类似 tail -f）",
    )
    log_parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="跟踪间隔秒数（默认 2）",
    )
    log_parser.add_argument(
        "--output", "-o",
        choices=["table", "json"],
        default="table",
        help="输出格式",
    )

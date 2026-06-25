#!/usr/bin/env python3
"""
auto-audit Skill 可执行脚本 — 调用 harness 审计引擎查询记录

用法:
  python3 audit_report.py [--query ""] [--limit 50] [--output table|detail|json]

功能:
  1. 查询 harness AuditStore 中的审计记录
  2. 统计各维度数据（按 agent_id、按日期、按状态）
  3. 输出格式化审计摘要

退出码: 0
"""

import argparse
import json
import os
import sys
from pathlib import Path


def _setup_pythonpath():
    """设置 PYTHONPATH 以导入 harness core 包"""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", str(Path(__file__).resolve().parent.parent.parent))
    core_path = str(Path(project_dir) / "packages" / "core")
    sys.path.insert(0, core_path)


def _format_timestamp(ts_str: str) -> str:
    """格式化时间戳为可读格式"""
    try:
        # ISO 格式 → 简短格式
        return ts_str[:19].replace("T", " ")
    except Exception:
        return ts_str[:30] if ts_str else "unknown"


def main():
    _setup_pythonpath()

    parser = argparse.ArgumentParser(description="harness auto-audit — 审计记录查询")
    parser.add_argument("--query", default="", help="搜索关键词")
    parser.add_argument("--limit", type=int, default=50, help="最大返回条数（默认 50）")
    parser.add_argument("--output", choices=["table", "detail", "json"], default="table", help="输出格式")
    args = parser.parse_args()

    # ── 1. 从 harness AuditStore 查询 ──────────────────────────
    try:
        from harness.audit import AuditStore, AuditEngine

        store = AuditStore()
        engine = AuditEngine(store=store)

        entries = engine.search(args.query, limit=args.limit)

    except ImportError:
        print("⚠️ [harness auto-audit] harness 包不可用，尝试从 .harness/audit/ 目录读取")
        entries = []

        # 回退：从 .harness/audit/ 目录直接读取 JSON 文件
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
        audit_dir = Path(project_dir) / ".harness" / "audit"
        if audit_dir.exists():
            for f in sorted(audit_dir.glob("*.json"), reverse=True)[:args.limit]:
                try:
                    data = json.loads(f.read_text())
                    if args.query and args.query not in json.dumps(data):
                        continue
                    entries.append(data)
                except Exception:
                    pass

    # ── 2. 输出格式化 ──────────────────────────────────────────
    if not entries:
        if args.output == "json":
            print(json.dumps({"count": 0, "entries": []}))
        else:
            print("📋 [harness auto-audit] 无审计记录")
        return 0

    if args.output == "json":
        # 处理两种类型的 entries：AuditEntry 对象和 dict
        result_entries = []
        for e in entries:
            if hasattr(e, "task"):
                result_entries.append({
                    "task": e.task,
                    "agent_id": e.agent_id,
                    "session_id": e.session_id,
                    "timestamp": e.timestamp.isoformat() if hasattr(e.timestamp, "isoformat") else str(e.timestamp),
                    "decisions": e.decisions if hasattr(e, "decisions") else [],
                    "actions": e.actions if hasattr(e, "actions") else [],
                    "outcomes": e.outcomes if hasattr(e, "outcomes") else [],
                })
            elif isinstance(e, dict):
                result_entries.append(e)

        print(json.dumps({"count": len(result_entries), "entries": result_entries}, ensure_ascii=False, indent=2))

    elif args.output == "detail":
        print("=" * 70)
        print("  [harness auto-audit] 审计记录详情")
        print("=" * 70)
        print("共 {} 条记录（搜索: '{}')".format(len(entries), args.query or "全部"))
        print()

        for e in entries:
            if hasattr(e, "task"):
                ts = _format_timestamp(e.timestamp.isoformat() if hasattr(e.timestamp, "isoformat") else str(e.timestamp))
                print("📋 {} | Agent: {} | Task: {}".format(ts, e.agent_id, e.task))
                if hasattr(e, "decisions") and e.decisions:
                    for d in e.decisions[:3]:
                        print("  决策: {}".format(d))
                if hasattr(e, "actions") and e.actions:
                    for a in e.actions[:3]:
                        print("  动作: {}".format(a))
            elif isinstance(e, dict):
                ts = _format_timestamp(e.get("timestamp", ""))
                print("📋 {} | {}".format(ts, e.get("event", "session_stop")))
                if e.get("diff_summary"):
                    print("  变更: {}".format(e.get("diff_summary", "")[:200]))
            print()

    else:  # table
        print("=" * 70)
        print("  [harness auto-audit] 审计记录摘要")
        print("=" * 70)
        print("共 {} 条记录（搜索: '{}')".format(len(entries), args.query or "全部"))
        print()

        for e in entries[:20]:
            if hasattr(e, "task"):
                ts = _format_timestamp(e.timestamp.isoformat() if hasattr(e.timestamp, "isoformat") else str(e.timestamp))
                print("  {} | {} | {}".format(ts, e.agent_id, e.task[:60]))
            elif isinstance(e, dict):
                ts = _format_timestamp(e.get("timestamp", ""))
                print("  {} | {}".format(ts, e.get("event", "unknown")[:30]))

        if len(entries) > 20:
            print("  ... 还有 {} 条记录未展示".format(len(entries) - 20))

        print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
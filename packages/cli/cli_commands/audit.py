"""
harness audit 命令——查看审计记录

搜索和展示 Harness 审计日志，支持按关键词/session/agent/日期过滤。
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime

from harness.types import AuditEntry, AuditStats
from harness.audit import AuditStore, AuditEngine


# ─── 输出格式 ───────────────────────────────────────

def _format_table(entries: list[AuditEntry]) -> str:
    """表格格式输出"""
    if not entries:
        return "无审计记录"

    lines = []
    lines.append(f"审计记录 (最近 {len(entries)} 条)")
    lines.append("-" * 70)

    for entry in entries:
        ts = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"  时间: {ts}")
        lines.append(f"  Agent: {entry.agent_id}")
        lines.append(f"  任务: {entry.task}")
        lines.append(f"  Session: {entry.session_id}")

        if entry.decisions:
            lines.append(f"  决策: {len(entry.decisions)} 条")
            for d in entry.decisions[:3]:  # 只显示前3条
                lines.append(f"    - {d}")

        if entry.risk_assessment:
            lines.append(f"  风险评估: {entry.risk_assessment}")

        if entry.escalation_history:
            lines.append(f"  升级记录: {len(entry.escalation_history)} 次")

        lines.append("")

    return "\n".join(lines)


def _format_detail(entries: list[AuditEntry]) -> str:
    """详细格式输出"""
    if not entries:
        return "无审计记录"

    lines = []
    for entry in entries:
        ts = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        lines.append("=" * 50)
        lines.append(f"审计记录详情")
        lines.append("=" * 50)
        lines.append(f"时间: {ts}")
        lines.append(f"Agent: {entry.agent_id}")
        lines.append(f"Session: {entry.session_id}")
        lines.append(f"任务: {entry.task}")
        lines.append("")

        if entry.decisions:
            lines.append("决策链:")
            for i, d in enumerate(entry.decisions):
                lines.append(f"  {i + 1}. {d}")
            lines.append("")

        if entry.actions:
            lines.append("操作记录:")
            for i, a in enumerate(entry.actions):
                lines.append(f"  {i + 1}. {a}")
            lines.append("")

        if entry.outcomes:
            lines.append("结果:")
            for i, o in enumerate(entry.outcomes):
                lines.append(f"  {i + 1}. {o}")
            lines.append("")

        if entry.risk_assessment:
            lines.append(f"风险评估: {entry.risk_assessment}")
            lines.append("")

        if entry.escalation_history:
            lines.append("升级记录:")
            for e in entry.escalation_history:
                lines.append(f"  - {e}")
            lines.append("")

        lines.append("")

    return "\n".join(lines)


def _format_json(entries: list[AuditEntry]) -> str:
    """JSON 格式输出"""
    data = []
    for entry in entries:
        data.append({
            "timestamp": entry.timestamp.isoformat(),
            "agent_id": entry.agent_id,
            "session_id": entry.session_id,
            "task": entry.task,
            "decisions": entry.decisions,
            "actions": entry.actions,
            "outcomes": entry.outcomes,
            "risk_assessment": entry.risk_assessment,
            "escalation_history": entry.escalation_history,
        })
    return json.dumps(data, indent=2, ensure_ascii=False)


def cmd_audit(args):
    """执行 audit 命令"""
    store = AuditStore()

    # 搜索模式
    if args.session:
        # 按 session 加载
        entries = store.load(args.session, date_str=args.date_from)
    else:
        # 搜索
        entries = store.search(
            query=args.query,
            date_from=args.date_from,
            date_to=args.date_to,
            agent_id=args.agent,
            limit=args.limit,
        )

    # 输出
    if args.output == "table":
        output = _format_table(entries)
    elif args.output == "detail":
        output = _format_detail(entries)
    elif args.output == "json":
        output = _format_json(entries)
    else:
        output = _format_table(entries)

    print(output)
    return 0
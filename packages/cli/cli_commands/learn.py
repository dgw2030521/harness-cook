#!/usr/bin/env python3
"""
harness learn — 学习引擎命令

在终端直接体验学习引擎：统计、推荐、校准预估、轨迹、模式。

用法:
  harness learn stats                       — 查看学习统计概览
  harness learn recommendations             — 触发学习，输出推荐列表
  harness learn estimates                   — 查看校准后的预估参数
  harness learn patterns                    — 查看已挖掘的模式
  harness learn traces                      — 查看历史轨迹列表

设计原则:
  - 纯 argparse，外部模块式（add_learn_args + cmd_learn）
  - 输出格式：table（人类可读）/ json（结构化）
  - 错误信息人类可读，非 traceback
"""

import argparse
import json
import sys
from pathlib import Path


# ── 路径自定位 ──────────────────────────────────────────────
_CLI_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _CLI_DIR.parent.parent
_CORE_PATH = str(_PROJECT_ROOT / "packages" / "core")
if _CORE_PATH not in sys.path:
    sys.path.insert(0, _CORE_PATH)


# ═══════════════════════════════════════════════════════════
#  格式化输出
# ═══════════════════════════════════════════════════════════

def _format_stats_table(stats: dict) -> str:
    """学习统计概览表格"""
    lines = []
    lines.append("  🧠 学习引擎统计概览")
    lines.append("  " + "─" * 50)

    es_stats = stats.get("experience_store", {})
    lines.append("  轨迹总数: {}".format(es_stats.get("total_traces", 0)))
    lines.append("  已挖掘模式数: {}".format(es_stats.get("total_patterns", 0)))
    lines.append("  成功率: {:.1%}".format(es_stats.get("success_rate", 0)))

    calibrated = stats.get("calibrated_agents", 0)
    lines.append("  已校准 Agent 数: {}".format(calibrated))

    return "\n".join(lines)


def _format_recommendations_table(recommendations: list) -> str:
    """推荐列表表格"""
    if not recommendations:
        return "  📭 当前无推荐\n  💡 需要先积累执行轨迹，再触发学习引擎挖掘模式"

    lines = []
    lines.append("  🔔 学习推荐列表（{} 条）".format(len(recommendations)))
    lines.append("  " + "─" * 80)
    lines.append("  {:10s} {:8s} {:40s} {}".format("类型", "置信度", "描述", "建议"))
    lines.append("  " + "─" * 80)

    for rec in recommendations:
        desc_display = (rec.description[:40] if len(rec.description) > 40 else rec.description)
        action_display = (rec.suggested_action[:30] if len(rec.suggested_action) > 30 else rec.suggested_action)
        lines.append("  {:10s} {:8.2f} {:40s} {}".format(
            rec.type, rec.confidence, desc_display, action_display))

    lines.append("  " + "─" * 80)
    return "\n".join(lines)


def _format_estimates_table(estimates: dict) -> str:
    """校准预估参数表格"""
    if not estimates:
        return "  📭 暂无校准数据\n  💡 需要积累执行轨迹后才能校准预估"

    lines = []
    lines.append("  🎯 校准预估参数")
    lines.append("  " + "─" * 70)
    lines.append("  {:15s} {:12s} {:15s} {:12s} {}".format(
        "Agent类型", "平均Token", "平均耗时(ms)", "标准差Token", "样本数"))
    lines.append("  " + "─" * 70)

    for agent_type, params in estimates.items():
        lines.append("  {:15s} {:12d} {:15d} {:12d} {}".format(
            agent_type,
            int(params.get("avg_tokens", 0)),
            int(params.get("avg_duration_ms", 0)),
            int(params.get("std_tokens", 0)),
            params.get("sample_count", 0),
        ))

    lines.append("  " + "─" * 70)
    return "\n".join(lines)


def _format_traces_table(traces: list) -> str:
    """轨迹列表表格"""
    if not traces:
        return "  📭 暂无执行轨迹\n  💡 执行 workflow 后轨迹会自动记录到 ExperienceStore"

    lines = []
    lines.append("  📝 执行轨迹列表（{} 条）".format(len(traces)))
    lines.append("  " + "─" * 70)
    lines.append("  {:15s} {:12s} {:15s} {:8s} {}".format(
        "工作流ID", "耗时(ms)", "最终状态", "节点数", "时间戳"))
    lines.append("  " + "─" * 70)

    for trace in traces:
        wf_id = (trace.workflow_id[:15] if len(trace.workflow_id) > 15 else trace.workflow_id)
        status = trace.final_status
        node_count = len(trace.nodes)
        duration = trace.duration_ms
        timestamp = trace.timestamp[:19] if trace.timestamp else "—"
        lines.append("  {:15s} {:12d} {:15s} {:8d} {}".format(
            wf_id, duration, status, node_count, timestamp))

    lines.append("  " + "─" * 70)
    return "\n".join(lines)


def _format_patterns_table(patterns: dict) -> str:
    """已挖掘模式表格"""
    if not patterns:
        return "  📭 暂无已挖掘模式\n  💡 使用 harness learn recommendations 触发学习"

    lines = []
    lines.append("  🔍 已挖掘模式（{} 个）".format(len(patterns)))
    lines.append("  " + "─" * 60)

    for pattern_id, pattern_data in patterns.items():
        lines.append("  模式ID: {}".format(pattern_id))
        desc = pattern_data.get("description", "")
        lines.append("    描述: {}".format(desc))
        confidence = pattern_data.get("confidence", 0)
        lines.append("    置信度: {:.2f}".format(confidence))
        lines.append("")

    return "\n".join(lines)


def _format_json(data) -> str:
    """JSON 格式输出"""
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


# ═══════════════════════════════════════════════════════════
#  命令执行
# ═══════════════════════════════════════════════════════════

def cmd_learn(args) -> int:
    """harness learn 命令执行入口"""
    action = args.action

    try:
        from harness.learning import LearningEngine, ExperienceStore
        from harness.knowledge import get_knowledge_provider

        # ── 初始化引擎 ──
        store = ExperienceStore()
        knowledge_provider = get_knowledge_provider(args.project)
        engine = LearningEngine(
            store=store,
            knowledge_provider=knowledge_provider,
        )

        if action == "stats":
            stats = engine.stats()
            if args.output == "json":
                print(_format_json(stats))
            else:
                print(_format_stats_table(stats))
            return 0

        elif action == "recommendations":
            recommendations = engine.learn()
            if args.output == "json":
                data = [{
                    "type": r.type,
                    "confidence": r.confidence,
                    "description": r.description,
                    "suggested_action": r.suggested_action,
                } for r in recommendations]
                print(_format_json(data))
            else:
                print(_format_recommendations_table(recommendations))
            return 0

        elif action == "estimates":
            estimates = engine.get_calibrated_estimates()
            if args.output == "json":
                print(_format_json(estimates))
            else:
                print(_format_estimates_table(estimates))
            return 0

        elif action == "patterns":
            patterns = store.get_patterns()
            if args.output == "json":
                print(_format_json(patterns))
            else:
                print(_format_patterns_table(patterns))
            return 0

        elif action == "traces":
            traces = store.get_traces(limit=args.limit)
            if args.output == "json":
                data = [{
                    "workflow_id": t.workflow_id,
                    "duration_ms": t.duration_ms,
                    "final_status": t.final_status,
                    "node_count": len(t.nodes),
                    "timestamp": t.timestamp,
                } for t in traces]
                print(_format_json(data))
            else:
                print(_format_traces_table(traces))
            return 0

        else:
            print("  ❌ 未知操作 — {}".format(action), file=sys.stderr)
            return 1

    except Exception as e:
        print("  ❌ 错误: {}".format(e), file=sys.stderr)
        return 1


# ═══════════════════════════════════════════════════════════
#  参数注册
# ═══════════════════════════════════════════════════════════

def add_learn_args(subparsers):
    """注册 learn 子命令"""
    learn_parser = subparsers.add_parser(
        "learn",
        help="学习引擎 — 统计/推荐/校准预估/轨迹/模式",
        description="在终端直接体验学习引擎：统计、推荐、校准预估、轨迹、模式挖掘",
    )

    # action 子操作
    learn_parser.add_argument(
        "action",
        choices=["stats", "recommendations", "estimates", "patterns", "traces"],
        default="stats",
        nargs="?",
        help="操作类型: stats/recommendations/estimates/patterns/traces",
    )

    # 全局参数
    learn_parser.add_argument(
        "--project",
        default="default",
        help="项目名（默认 default）",
    )

    # 分页
    learn_parser.add_argument(
        "--limit", "-n",
        type=int,
        default=20,
        help="显示条数（默认 20）",
    )

    # 输出格式
    learn_parser.add_argument(
        "--output", "-o",
        choices=["table", "json"],
        default="table",
        help="输出格式: table/json",
    )

    learn_parser.set_defaults(func=cmd_learn)

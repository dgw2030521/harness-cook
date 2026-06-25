#!/usr/bin/env python3
"""
harness knowledge — 知识管理命令

在终端直接体验知识库的 CRUD + 搜索 + 语义搜索 + 统计。

用法:
  harness knowledge types                   — 展示 10 种知识类型 + 4 级作用域
  harness knowledge stats                   — 统计概览
  harness knowledge list                    — 列出所有知识条目
  harness knowledge search <关键词>          — 关键词搜索
  harness knowledge semantic <关键词>        — TF-IDF 语义搜索
  harness knowledge add --title --content   — 添加知识条目
  harness knowledge get <id>                — 查看单个条目详情
  harness knowledge delete <id>             — 删除条目

设计原则:
  - 纯 argparse，外部模块式（add_knowledge_args + cmd_knowledge）
  - 输出格式：table（人类可读表格）/ json（结构化）/ detail（单条目全字段）
  - 错误信息人类可读，非 traceback
"""

import argparse
import json
import sys
import os
from pathlib import Path


# ── 路径自定位 ──────────────────────────────────────────────
_CLI_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _CLI_DIR.parent.parent
_CORE_PATH = str(_PROJECT_ROOT / "packages" / "core")
if _CORE_PATH not in sys.path:
    sys.path.insert(0, _CORE_PATH)


def _get_provider(project_name: str = "default"):
    """获取 LocalKnowledgeProvider 实例"""
    from harness.knowledge import get_knowledge_provider
    provider = get_knowledge_provider(project_name)
    return provider


# ═══════════════════════════════════════════════════════════
#  格式化输出
# ═══════════════════════════════════════════════════════════

def _format_types_table() -> str:
    """展示 10 种知识类型 + 4 级作用域"""
    from harness.knowledge import KnowledgeType, KnowledgeScope

    lines = []
    lines.append("  📚 10 种知识类型（KnowledgeType）")
    lines.append("  " + "─" * 60)
    lines.append("  {:15s} {:10s} {}".format("类型", "值", "适用场景"))
    lines.append("  " + "─" * 60)

    descriptions = {
        "ARCHITECTURE": "项目架构 — 系统概览、模块关系、技术栈",
        "CONVENTION":   "编码约定 — 命名规则、代码风格、提交规范",
        "DEPENDENCY":   "依赖关系 — 包依赖、版本约束、服务依赖",
        "API":          "API 定义 — 接口契约、参数签名、返回值",
        "PATTERN":      "设计模式 — 常见解法、最佳实践、反模式",
        "RISK":         "风险记录 — 已知风险、安全漏洞、性能瓶颈",
        "DECISION":     "架构决策 — ADR、技术选型理由、权衡记录",
        "TASK":         "任务上下文 — 当前任务、典型工作流、分工模式",
        "TEST":         "测试策略 — 测试方案、覆盖率要求、典型模式",
        "GLOSSARY":     "术语表 — 项目专有名词、缩写、概念映射",
    }

    for kt in KnowledgeType:
        desc = descriptions.get(kt.name, "")
        lines.append("  {:15s} {:10s} {}".format(kt.name, kt.value, desc))

    lines.append("  " + "─" * 60)
    lines.append("")
    lines.append("  📐 4 级作用域（KnowledgeScope）")
    lines.append("  " + "─" * 40)

    scope_desc = {
        "PROJECT":  "项目级 — 跨模块通用知识",
        "MODULE":   "模块级 — 特定模块的知识",
        "FILE":     "文件级 — 特定文件的知识",
        "FUNCTION": "函数级 — 特定函数的知识",
    }

    for ks in KnowledgeScope:
        desc = scope_desc.get(ks.name, "")
        lines.append("  {:10s} {:10s} {}".format(ks.name, ks.value, desc))

    return "\n".join(lines)


def _format_stats_table(stats: dict) -> str:
    """统计概览表格"""
    lines = []
    lines.append("  📊 知识库统计概览")
    lines.append("  " + "─" * 40)
    lines.append("  项目: {}".format(stats.get("project", "default")))
    lines.append("  活跃条目数: {}".format(stats.get("total_entries", 0)))
    lines.append("  归档条目数: {}".format(stats.get("archived_total", 0)))
    lines.append("  已初始化: {}".format(stats.get("initialized", False)))

    types_dict = stats.get("types", {})
    if types_dict:
        lines.append("")
        lines.append("  活跃层类型分布:")
        for ktype, count in types_dict.items():
            lines.append("    {}: {} 条".format(ktype, count))

    archived_types = stats.get("archived_types", {})
    if archived_types:
        lines.append("  归档层类型分布:")
        for ktype, count in archived_types.items():
            lines.append("    {}: {} 条".format(ktype, count))

    sources_dict = stats.get("sources", {})
    if sources_dict:
        lines.append("  来源分布:")
        for src, count in sources_dict.items():
            lines.append("    {}: {} 条".format(src, count))

    high_freq = stats.get("high_freq_entries", 0)
    if high_freq:
        lines.append("  高频条目(hit_count≥3): {} 条".format(high_freq))

    lines.append("  标签总数: {}".format(stats.get("tags", 0)))

    return "\n".join(lines)


def _format_entries_table(entries: list) -> str:
    """条目列表表格"""
    if not entries:
        return "  📭 知识库为空（暂无条目）\n  💡 使用 harness knowledge add 添加条目"

    lines = []
    lines.append("  📋 知识条目列表（{} 条）".format(len(entries)))
    lines.append("  " + "─" * 80)
    lines.append("  {:12s} {:10s} {:10s} {:30s} {:6s} {:10s}".format(
        "ID", "类型", "作用域", "标题", "置信度", "来源"))
    lines.append("  " + "─" * 80)

    for e in entries:
        title_display = (e.title[:30] if len(e.title) > 30 else e.title)
        lines.append("  {:12s} {:10s} {:10s} {:30s} {:6.2f} {:10s}".format(
            e.id, e.type.value, e.scope.value, title_display, e.confidence, e.source or "—"))

    lines.append("  " + "─" * 80)
    return "\n".join(lines)


def _format_entry_detail(entry) -> str:
    """单条目详情"""
    lines = []
    lines.append("  📄 知识条目详情")
    lines.append("  " + "─" * 60)
    lines.append("  ID: {}".format(entry.id))
    lines.append("  类型: {} ({})".format(entry.type.name, entry.type.value))
    lines.append("  作用域: {} ({})".format(entry.scope.name, entry.scope.value))
    lines.append("  标题: {}".format(entry.title))
    lines.append("  内容: {}".format(entry.content))
    lines.append("  标签: {}".format(", ".join(entry.tags) if entry.tags else "无"))
    lines.append("  置信度: {}".format(entry.confidence))
    lines.append("  来源: {}".format(entry.source or "未标注"))
    lines.append("  创建时间: {}".format(entry.created_at or "未知"))
    lines.append("  更新时间: {}".format(entry.updated_at or "未知"))
    if entry.metadata:
        lines.append("  元数据: {}".format(json.dumps(entry.metadata, ensure_ascii=False)))
    lines.append("  " + "─" * 60)
    return "\n".join(lines)


def _format_search_results(result) -> str:
    """搜索结果表格"""
    entries = result.entries
    if not entries:
        return "  📭 搜索无结果\n  💡 尝试换关键词或使用 harness knowledge semantic 语义搜索"

    lines = []
    lines.append("  🔍 搜索结果（{} 条，搜索方式: {}）".format(len(entries), result.search_method))
    lines.append("  " + "─" * 80)
    lines.append("  {:12s} {:10s} {:30s} {:6s} {}".format(
        "ID", "类型", "标题", "置信度", "内容摘要"))
    lines.append("  " + "─" * 80)

    for e in entries:
        title_display = (e.title[:30] if len(e.title) > 30 else e.title)
        content_preview = e.content[:40] + "..." if len(e.content) > 40 else e.content
        lines.append("  {:12s} {:10s} {:30s} {:6.2f} {}".format(
            e.id, e.type.value, title_display, e.confidence, content_preview))

    lines.append("  " + "─" * 80)
    return "\n".join(lines)


def _format_json(data) -> str:
    """JSON 格式输出"""
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


# ═══════════════════════════════════════════════════════════
#  命令执行
# ═══════════════════════════════════════════════════════════

def cmd_knowledge(args) -> int:
    """harness knowledge 命令执行入口"""
    action = args.action

    try:
        # ── types: 展示 10 种知识类型（不需要 provider）──
        if action == "types":
            if args.output == "json":
                from harness.knowledge import KnowledgeType, KnowledgeScope
                data = {
                    "knowledge_types": [{"name": kt.name, "value": kt.value} for kt in KnowledgeType],
                    "knowledge_scopes": [{"name": ks.name, "value": ks.value} for ks in KnowledgeScope],
                }
                print(_format_json(data))
            else:
                print(_format_types_table())
            return 0

        # ── 其他操作都需要 provider ──
        provider = _get_provider(args.project)

        if action == "stats":
            stats = provider.stats()
            if args.output == "json":
                print(_format_json(stats))
            else:
                print(_format_stats_table(stats))
            return 0

        elif action == "list":
            from harness.knowledge import KnowledgeQuery, KnowledgeType, KnowledgeScope

            # 构建过滤条件
            type_filter = None
            if args.type:
                type_map = {kt.value: kt for kt in KnowledgeType}
                type_filter = type_map.get(args.type)

            scope_filter = None
            if args.scope:
                scope_map = {ks.value: ks for ks in KnowledgeScope}
                scope_filter = scope_map.get(args.scope)

            tags_filter = None
            if args.tags:
                tags_filter = args.tags.split(",")

            query_obj = KnowledgeQuery(
                query="",
                type_filter=type_filter,
                scope_filter=scope_filter,
                tags_filter=tags_filter,
                limit=args.limit,
            )

            result = provider.query(query_obj)

            if args.output == "json":
                data = {
                    "entries": [
                        {
                            "id": e.id, "type": e.type.value, "scope": e.scope.value,
                            "title": e.title, "content": e.content,
                            "tags": e.tags, "confidence": e.confidence,
                            "source": e.source, "created_at": e.created_at,
                        }
                        for e in result.entries
                    ],
                    "total_matches": result.total_matches,
                }
                print(_format_json(data))
            else:
                print(_format_entries_table(result.entries))

            return 0

        elif action == "search":
            from harness.knowledge import KnowledgeQuery, KnowledgeType, KnowledgeScope

            type_filter = None
            if args.type:
                type_map = {kt.value: kt for kt in KnowledgeType}
                type_filter = type_map.get(args.type)

            query_obj = KnowledgeQuery(
                query=args.query_text,
                type_filter=type_filter,
                limit=args.limit,
            )

            result = provider.query(query_obj)

            if args.output == "json":
                data = {
                    "entries": [
                        {"id": e.id, "type": e.type.value, "title": e.title,
                         "content": e.content, "confidence": e.confidence}
                        for e in result.entries
                    ],
                    "total_matches": result.total_matches,
                    "search_method": result.search_method,
                }
                print(_format_json(data))
            else:
                print(_format_search_results(result))

            return 0

        elif action == "semantic":
            result = provider.semantic_search(args.query_text, limit=args.limit)

            if args.output == "json":
                data = {
                    "entries": [
                        {"id": e.id, "type": e.type.value, "title": e.title,
                         "content": e.content, "confidence": e.confidence}
                        for e in result.entries
                    ],
                    "total_matches": result.total_matches,
                    "search_method": result.search_method,
                }
                print(_format_json(data))
            else:
                print(_format_search_results(result))

            return 0

        elif action == "add":
            from harness.knowledge import KnowledgeEntry, KnowledgeType, KnowledgeScope

            # 解析类型
            type_map = {kt.value: kt for kt in KnowledgeType}
            entry_type = type_map.get(args.type, KnowledgeType.ARCHITECTURE)

            # 解析作用域
            scope_map = {ks.value: ks for ks in KnowledgeScope}
            entry_scope = scope_map.get(args.scope, KnowledgeScope.PROJECT)

            # 解析标签
            tags = []
            if args.tags:
                tags = args.tags.split(",")

            entry = KnowledgeEntry(
                type=entry_type,
                scope=entry_scope,
                title=args.title,
                content=args.content,
                tags=tags,
                confidence=args.confidence if args.confidence else 1.0,
                source=args.source if args.source else "human",
            )

            entry_id = provider.put(entry)
            # put() 已内置 auto_save，无需手动 _save_to_disk

            print("  ✅ 知识条目已添加!")
            print("  ID: {}".format(entry_id))
            print("  类型: {} / 作用域: {}".format(entry_type.value, entry_scope.value))
            print("  标题: {}".format(args.title))

            return 0

        elif action == "get":
            entry_id = args.query_text
            if not entry_id:
                print("  ❌ 缺少条目ID — 用法: harness knowledge get <id>", file=sys.stderr)
                return 1
            entry = provider.get(entry_id)

            if not entry:
                print("  ❌ 条目不存在 — ID: {}".format(args.entry_id), file=sys.stderr)
                return 1

            if args.output == "json":
                data = {
                    "id": entry.id, "type": entry.type.value, "scope": entry.scope.value,
                    "title": entry.title, "content": entry.content,
                    "tags": entry.tags, "confidence": entry.confidence,
                    "source": entry.source, "metadata": entry.metadata,
                    "created_at": entry.created_at, "updated_at": entry.updated_at,
                }
                print(_format_json(data))
            else:
                print(_format_entry_detail(entry))

            return 0

        elif action == "delete":
            entry_id = args.query_text
            if not entry_id:
                print("  ❌ 缺少条目ID — 用法: harness knowledge delete <id>", file=sys.stderr)
                return 1
            success = provider.delete(entry_id)
            if success:
                # delete() 已内置 auto_save，无需手动 _save_to_disk
                print("  ✅ 条目已删除 — ID: {}".format(entry_id))
                return 0
            else:
                print("  ❌ 条目不存在 — ID: {}".format(entry_id), file=sys.stderr)
                return 1

        elif action == "evict":
            # ── 知识淘汰（第三层治理）──
            result = provider.evict_stale_entries()

            if args.output == "json":
                print(_format_json(result))
            else:
                lines = []
                lines.append("  🗑️ 知识淘汰结果")
                lines.append("  " + "─" * 40)
                lines.append("  归档到归档层: {} 条".format(result.get("archived", 0)))
                lines.append("  从归档层删除: {} 条".format(result.get("deleted", 0)))
                lines.append("  当前活跃层: {} 条".format(result.get("active", 0)))
                lines.append("  当前归档层: {} 条".format(result.get("archived_total", 0)))
                lines.append("  " + "─" * 40)
                print("\n".join(lines))

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

def add_knowledge_args(subparsers):
    """注册 knowledge 子命令"""
    from harness.knowledge import KnowledgeType, KnowledgeScope

    knowledge_parser = subparsers.add_parser(
        "knowledge",
        help="知识管理 — 10类知识 CRUD + 搜索 + 语义搜索",
        description="在终端直接体验知识库的 CRUD + 搜索 + 语义搜索 + 统计",
    )

    # action 子操作
    knowledge_parser.add_argument(
        "action",
        choices=["list", "search", "semantic", "add", "get", "delete", "stats", "types", "evict"],
        default="stats",
        nargs="?",
        help="操作类型: list/search/semantic/add/get/delete/stats/types/evict",
    )

    # search/semantic 的关键词参数
    knowledge_parser.add_argument(
        "query_text",
        nargs="?",
        default="",
        help="搜索关键词（search/semantic 操作需要）",
    )

    # 全局参数
    knowledge_parser.add_argument(
        "--project",
        default="default",
        help="项目名（默认 default）",
    )

    # 过滤参数
    knowledge_parser.add_argument(
        "--type",
        choices=[kt.value for kt in KnowledgeType],
        default=None,
        help="按知识类型过滤",
    )
    knowledge_parser.add_argument(
        "--scope",
        choices=[ks.value for ks in KnowledgeScope],
        default=None,
        help="按作用域过滤",
    )
    knowledge_parser.add_argument(
        "--tags",
        default=None,
        help="按标签过滤（逗号分隔）",
    )

    # add 专用参数
    knowledge_parser.add_argument(
        "--title",
        default=None,
        help="条目标题（add 操作需要）",
    )
    knowledge_parser.add_argument(
        "--content",
        default=None,
        help="条目内容（add 操作需要）",
    )
    knowledge_parser.add_argument(
        "--confidence",
        type=float,
        default=None,
        help="置信度 0.0-1.0（add 操作可选，默认 1.0）",
    )
    knowledge_parser.add_argument(
        "--source",
        default=None,
        help="知识来源: human/ast/llm/learning（add 操作可选，默认 human）",
    )

    # 分页
    knowledge_parser.add_argument(
        "--limit", "-n",
        type=int,
        default=20,
        help="显示条数（默认 20）",
    )

    # 输出格式
    knowledge_parser.add_argument(
        "--output", "-o",
        choices=["table", "json", "detail"],
        default="table",
        help="输出格式: table/json/detail",
    )

    knowledge_parser.set_defaults(func=cmd_knowledge)

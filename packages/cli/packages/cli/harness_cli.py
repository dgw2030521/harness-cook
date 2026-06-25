"""
harness-cook CLI 入口

命令行直接操作 Harness——让开发者不写代码也能使用核心能力。

用法:
  harness plan <workflow.yaml>   — 可视化 DAG + 门禁配置
  harness run <workflow.yaml>    — 执行编排流程
  harness check [path]           — 合规/质量检查
  harness audit [query]          — 查看审计记录
  harness version                — 显示版本号

设计原则:
  - 纯 argparse 实现，不引入 click（Python 3.9 兼容）
  - 每个子命令独立模块，保持 CLI 入口简洁
  - 输出格式友好：表格/树状/彩色（终端可用）
  - 错误信息人类可读，非 traceback
"""

import argparse
import sys

from harness import __version__
from harness.logging_config import configure_logging
from cli_commands.plan import cmd_plan
from cli_commands.run import cmd_run
from cli_commands.check import cmd_check
from cli_commands.audit import cmd_audit


def main(argv=None):
    """CLI 主入口"""
    parser = argparse.ArgumentParser(
        prog="harness",
        description="harness-cook — Agent Harness SDK CLI\nAgent 决策执行，Harness 稳定约束。",
        epilog="更多帮助: harness <command> --help",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="显示详细日志(DEBUG级别)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="只显示错误日志",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="日志级别 (默认: INFO)",
    )
    parser.add_argument(
        "--log-format",
        choices=["text", "json"],
        default="text",
        help="日志输出格式: text(可读)/json(结构化)",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title="commands",
        description="可用命令",
    )

    # ─── plan ──────────────────────────────────────
    plan_parser = subparsers.add_parser(
        "plan",
        help="可视化 DAG 工作流 + 门禁配置",
        description="解析工作流定义文件，输出 DAG 拓扑图和门禁配置摘要。",
    )
    plan_parser.add_argument(
        "workflow",
        type=str,
        help="工作流定义文件 (YAML/JSON)",
    )
    plan_parser.add_argument(
        "--format",
        choices=["tree", "dot", "json"],
        default="tree",
        help="输出格式: tree(树状)/dot(Graphviz)/json(原始)",
    )
    plan_parser.add_argument(
        "--show-gates",
        action="store_true",
        help="显示每个节点的门禁配置",
    )

    # ─── run ──────────────────────────────────────
    run_parser = subparsers.add_parser(
        "run",
        help="执行编排流程",
        description="加载工作流定义，注册 Agent，执行 DAG 编排。",
    )
    run_parser.add_argument(
        "workflow",
        type=str,
        help="工作流定义文件 (YAML/JSON)",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只验证不执行——检查 DAG 是否合法、Agent 是否注册",
    )
    run_parser.add_argument(
        "--gate-mode",
        choices=["strict", "hybrid", "loose"],
        default="hybrid",
        help="门禁模式: strict/hybrid/loose",
    )
    run_parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="每个节点最大重试次数",
    )
    run_parser.add_argument(
        "--context",
        type=str,
        default=None,
        help="初始上下文 JSON 文件",
    )

    # ─── check ──────────────────────────────────────
    check_parser = subparsers.add_parser(
        "check",
        help="合规/质量检查",
        description="扫描指定路径的产出物，执行合规规则检查。",
    )
    check_parser.add_argument(
        "path",
        type=str,
        nargs="?",
        default=".",
        help="要检查的路径 (默认: 当前目录)",
    )
    check_parser.add_argument(
        "--category",
        choices=["security", "coding", "data", "devops"],
        default=None,
        help="只检查指定类别",
    )
    check_parser.add_argument(
        "--severity",
        choices=["critical", "high", "medium", "low"],
        default=None,
        help="只显示指定严重级别的违规",
    )
    check_parser.add_argument(
        "--fix",
        action="store_true",
        help="尝试自动修复（仅 auto_fixable 违规）",
    )
    check_parser.add_argument(
        "--output",
        choices=["table", "json", "summary"],
        default="table",
        help="输出格式",
    )

    # ─── audit ──────────────────────────────────────
    audit_parser = subparsers.add_parser(
        "audit",
        help="查看审计记录",
        description="搜索和展示 Harness 审计日志。",
    )
    audit_parser.add_argument(
        "query",
        type=str,
        nargs="?",
        default="",
        help="搜索关键词 (空=列出最近记录)",
    )
    audit_parser.add_argument(
        "--session",
        type=str,
        default=None,
        help="按 session_id 过滤",
    )
    audit_parser.add_argument(
        "--agent",
        type=str,
        default=None,
        help="按 agent_id 过滤",
    )
    audit_parser.add_argument(
        "--date-from",
        type=str,
        default=None,
        help="起始日期 (YYYYMMDD)",
    )
    audit_parser.add_argument(
        "--date-to",
        type=str,
        default=None,
        help="截止日期 (YYYYMMDD)",
    )
    audit_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="最大记录数",
    )
    audit_parser.add_argument(
        "--output",
        choices=["table", "json", "detail"],
        default="table",
        help="输出格式",
    )

    # ─── version ──────────────────────────────────────
    version_parser = subparsers.add_parser(
        "version",
        help="显示版本号",
    )

    # 解析参数
    args = parser.parse_args(argv)

    # 配置日志
    configure_logging(
        level=args.verbose and "DEBUG" or args.log_level,
        json_mode=args.log_format == "json",
        quiet=args.quiet,
    )

    if not args.command:
        parser.print_help()
        return 0

    # ─── 执行命令 ──────────────────────────────────────
    try:
        if args.command == "plan":
            return cmd_plan(args)
        elif args.command == "run":
            return cmd_run(args)
        elif args.command == "check":
            return cmd_check(args)
        elif args.command == "audit":
            return cmd_audit(args)
        elif args.command == "version":
            print(f"harness-cook v{__version__}")
            return 0
        else:
            parser.print_help()
            return 1
    except FileNotFoundError as e:
        print(f"错误: 文件不存在 — {e}")
        return 2
    except Exception as e:
        if args.verbose:
            raise
        print(f"错误: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
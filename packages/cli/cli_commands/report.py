"""harness report 命令 — 生成合规/架构报告并打开浏览器查看

用法:
    harness report <path>              # 扫描路径并生成报告
    harness report <path> --open        # 生成后自动打开浏览器
    harness report <path> --format html  # 指定格式(html/dot/dsm)
    harness report <path> --output ./reports/  # 指定输出目录
"""

import argparse
import os
import sys
import webbrowser
from pathlib import Path
from typing import Optional


def add_report_args(subparsers):
    """添加 report 子命令到 argparse"""
    report_parser = subparsers.add_parser(
        "report",
        help="生成合规/架构可视化报告",
        description="扫描指定路径，生成 HTML/DOT/DSM 格式的合规报告",
    )
    report_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="要扫描的项目路径（默认当前目录）",
    )
    report_parser.add_argument(
        "--format",
        choices=["html", "dot", "dsm"],
        default="html",
        help="报告格式（默认html）",
    )
    report_parser.add_argument(
        "--open",
        action="store_true",
        help="生成后自动打开浏览器",
    )
    report_parser.add_argument(
        "--output",
        default=".harness/reports",
        help="报告输出目录（默认.harness/reports）",
    )
    report_parser.add_argument(
        "--packs",
        nargs="*",
        default=["security", "privacy", "architecture"],
        help="指定合规规则包（默认security+privacy+architecture）",
    )
    report_parser.set_defaults(func=run_report)


def run_report(args):
    """执行 report 命令"""
    from harness.compliance import ComplianceEngine, RulePack
    from harness.compliance import security_rule_pack, privacy_rule_pack, architecture_rule_pack
    from harness.report import HTMLReportGenerator, DOTReportGenerator, DSMReport
    from harness.types import Artifact

    project_path = Path(args.path).resolve()
    if not project_path.exists():
        print(f"错误: 路径不存在 — {project_path}", file=sys.stderr)
        return 1

    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # 初始化合规引擎 + 加载规则包
    engine = ComplianceEngine()
    pack_map = {
        "security": security_rule_pack(),
        "privacy": privacy_rule_pack(),
        "architecture": architecture_rule_pack(),
    }
    for pack_name in args.packs:
        pack = pack_map.get(pack_name)
        if pack:
            engine.load_pack(pack)
            print(f"  已加载规则包: {pack_name} ({len(pack.rules)} 条规则)")
        else:
            print(f"  警告: 规则包 '{pack_name}' 不存在，跳过", file=sys.stderr)

    # 发现项目文件
    artifacts = []
    supported_extensions = {
        ".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".java", ".go",
        ".rs", ".rb", ".c", ".cpp", ".h", ".kt", ".swift", ".dart", ".php",
    }
    for ext in supported_extensions:
        for filepath in project_path.rglob(f"*{ext}"):
            # 跳过常见非项目目录
            parts = filepath.parts
            if any(p in parts for p in (
                ".git", "__pycache__", "node_modules", ".harness", "venv", ".venv",
                "dist", "build", ".next", ".nuxt", "target", "out",
            )):
                continue
            try:
                content = filepath.read_text(encoding="utf-8", errors="replace")
                rel_path = str(filepath.relative_to(project_path))
                artifacts.append(Artifact(
                    type="code",
                    path=rel_path,
                    content=content,
                ))
            except Exception as e:
                import logging
                logging.getLogger("harness.report").warning(f"读取文件失败 {filepath}: {e}")

    if not artifacts:
        print("未找到可扫描的源代码文件", file=sys.stderr)
        return 1

    print(f"扫描 {len(artifacts)} 个文件...")

    # 执行扫描
    results = engine.scan(artifacts, project_root=str(project_path))

    violations = [r for r in results if not r.passed]
    print(f"发现 {len(violations)} 个违规 / {len(results)} 总检查项")

    # 生成报告
    report_file = None
    if args.format == "html":
        generator = HTMLReportGenerator()
        report_file = output_dir / "compliance_report.html"
        html_content = generator.generate_compliance_report(
            scan_results=results,
            title=f"Compliance Report — {project_path.name}",
        )
        report_file.write_text(html_content, encoding="utf-8")
    elif args.format == "dot":
        generator = DOTReportGenerator()
        report_file = output_dir / "dependency_graph.dot"
        # DOT 格式需要依赖图数据——尝试从合规引擎的扫描上下文获取
        dep_graph = None
        try:
            from harness.impact_types import FileImpactAnalyzer
            analyzer = FileImpactAnalyzer(project_root=str(project_path))
            analyzer.build_graph_from_project()
            dep_graph = analyzer.get_graph() if hasattr(analyzer, 'get_graph') else analyzer._graph
        except Exception as e:
            print(f"无法构建依赖图: {e}", file=sys.stderr)

        if dep_graph:
            dot_content = generator.generate_dependency_dot(dep_graph)
            report_file.write_text(dot_content, encoding="utf-8")
        else:
            print("DOT 报告需要依赖图数据，当前无法构建依赖图", file=sys.stderr)
            return 1
    elif args.format == "dsm":
        dsm = DSMReport()
        report_file = output_dir / "dsm_report.html"
        # DSM 格式同样需要依赖图数据
        dep_graph = None
        try:
            from harness.impact_types import FileImpactAnalyzer
            analyzer = FileImpactAnalyzer(project_root=str(project_path))
            analyzer.build_graph_from_project()
            dep_graph = analyzer.get_graph() if hasattr(analyzer, 'get_graph') else analyzer._graph
        except Exception as e:
            print(f"无法构建依赖图: {e}", file=sys.stderr)

        if dep_graph:
            dsm_content = dsm.generate_dsm(dep_graph, output_format="html")
            report_file.write_text(dsm_content, encoding="utf-8")
        else:
            print("DSM 报告需要依赖图数据，当前无法构建依赖图", file=sys.stderr)
            return 1

    print(f"报告已生成: {report_file}")

    # 自动打开浏览器
    if args.open and report_file:
        webbrowser.open(str(report_file))
        print("已在浏览器中打开报告")

    return 0
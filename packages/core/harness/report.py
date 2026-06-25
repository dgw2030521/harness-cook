"""
harness-cook 可视化增强——HTML/DOT/DSM 报告生成器

09号竞品报告指出"可视化不如 SonarQube/dependency-cruiser"(ASCII only vs Web Dashboard)。
本模块提供三种报告格式:
  1. HTMLReportGenerator — 自包含HTML(内嵌CSS/JS), 交互式依赖图、合规扫描报告、审计仪表盘
  2. DOTReportGenerator — Graphviz DOT格式, 供 dot 命令渲染
  3. DSMReport — 依赖结构方阵(Dependency Structure Matrix)

所有报告不依赖外部资源(内嵌CSS/JS), 输出到指定目录或返回字符串。
"""

import html
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger("harness.report")


# ═══════════════════════════════════════════════════════════
#  HTML 报告生成器
# ═══════════════════════════════════════════════════════════

class HTMLReportGenerator:
    """
    自包含 HTML 报告生成器——内嵌 CSS/JS，不依赖外部资源

    用法:
        gen = HTMLReportGenerator()
        gen.generate_compliance_report(results, output_dir="/tmp/reports")
        gen.generate_dependency_graph(artifacts, dep_graph, output_dir="/tmp/reports")
        gen.generate_audit_dashboard(stats, output_dir="/tmp/reports")
    """

    def generate_compliance_report(
        self,
        scan_results: list,
        output_dir: Optional[str] = None,
        title: str = "Compliance Scan Report",
    ) -> str:
        """生成合规扫描 HTML 报告"""
        passed = sum(1 for r in scan_results if r.passed)
        failed = len(scan_results) - passed

        rows_html = ""
        for r in scan_results:
            status = "PASS" if r.passed else "FAIL"
            status_class = "pass" if r.passed else "fail"
            findings_text = html.escape("; ".join(r.findings)) if r.findings else "—"
            rows_html += f"""
            <tr class="{status_class}">
                <td>{html.escape(r.rule_id)}</td>
                <td class="status-{status_class}">{status}</td>
                <td>{html.escape(r.severity)}</td>
                <td>{findings_text}</td>
            </tr>"""

        report_html = self._wrap_html(title, f"""
        <div class="summary-bar">
            <div class="stat pass-stat"><span class="stat-num">{passed}</span><span class="stat-label">Passed</span></div>
            <div class="stat fail-stat"><span class="stat-num">{failed}</span><span class="stat-label">Failed</span></div>
            <div class="stat total-stat"><span class="stat-num">{len(scan_results)}</span><span class="stat-label">Total</span></div>
        </div>
        <table>
            <thead><tr><th>Rule</th><th>Status</th><th>Severity</th><th>Findings</th></tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
        """)

        if output_dir:
            return self._write_report(output_dir, "compliance-report.html", report_html)
        return report_html

    def generate_dependency_graph(
        self,
        dep_graph: Any,
        output_dir: Optional[str] = None,
        title: str = "Dependency Graph",
    ) -> str:
        """生成交互式依赖图 HTML(SVG 内嵌)"""
        nodes_html = ""
        edges_html = ""
        if hasattr(dep_graph, 'nodes'):
            for nid, node in dep_graph.nodes.items():
                label = html.escape(str(node))
                x = (hash(nid) % 800) + 50
                y = (hash(nid[::-1]) % 400) + 50
                nodes_html += f'<circle cx="{x}" cy="{y}" r="20" class="dep-node" data-id="{html.escape(nid)}"/>\n'
                nodes_html += f'<text x="{x}" y="{y+30}" class="dep-label">{label}</text>\n'
            for src, targets in dep_graph.edges.items():
                for tgt in targets:
                    sx = (hash(src) % 800) + 50
                    sy = (hash(src[::-1]) % 400) + 50
                    tx = (hash(tgt) % 800) + 50
                    ty = (hash(tgt[::-1]) % 400) + 50
                    edges_html += f'<line x1="{sx}" y1="{sy}" x2="{tx}" y2="{ty}" class="dep-edge"/>\n'

        report_html = self._wrap_html(title, f"""
        <svg width="900" height="500" class="dep-svg">
            <g class="edges">{edges_html}</g>
            <g class="nodes">{nodes_html}</g>
        </svg>
        <script>
        // 鼠标悬停高亮关联边
        document.querySelectorAll('.dep-node').forEach(node => {{
            node.addEventListener('mouseover', () => {{
                node.setAttribute('r', '25');
                node.style.fill = '#ff6b6b';
            }});
            node.addEventListener('mouseout', () => {{
                node.setAttribute('r', '20');
                node.style.fill = '#4ecdc4';
            }});
        }});
        </script>
        """)

        if output_dir:
            return self._write_report(output_dir, "dependency-graph.html", report_html)
        return report_html

    def generate_audit_dashboard(
        self,
        audit_stats: Any,
        output_dir: Optional[str] = None,
        title: str = "Audit Dashboard",
    ) -> str:
        """生成审计统计仪表盘 HTML"""
        total = getattr(audit_stats, 'total_tasks', 0)
        delivered = getattr(audit_stats, 'delivered', 0)
        escalated = getattr(audit_stats, 'escalated', 0)
        auto_fixed = getattr(audit_stats, 'auto_fixed', 0)
        pass_rate = getattr(audit_stats, 'verification_pass_rate', 0)

        bars_html = ""
        metrics = [("Delivered", delivered, "#4ecdc4"), ("Escalated", escalated, "#ff6b6b"),
                   ("Auto-fixed", auto_fixed, "#ffe66d")]
        max_val = max(total, 1)
        for label, value, color in metrics:
            pct = int(value / max_val * 100)
            bars_html += f"""
            <div class="bar-row">
                <span class="bar-label">{label}</span>
                <div class="bar-track"><div class="bar-fill" style="width:{pct}%;background:{color}">{value}</div></div>
            </div>"""

        report_html = self._wrap_html(title, f"""
        <div class="summary-bar">
            <div class="stat"><span class="stat-num">{total}</span><span class="stat-label">Total Tasks</span></div>
            <div class="stat"><span class="stat-num">{pass_rate:.0%}</span><span class="stat-label">Pass Rate</span></div>
        </div>
        <div class="bars">{bars_html}</div>
        """)

        if output_dir:
            return self._write_report(output_dir, "audit-dashboard.html", report_html)
        return report_html

    # ─── 内部方法 ────────────────────────────────────

    def _wrap_html(self, title: str, body: str) -> str:
        """包装成自包含 HTML"""
        return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
body{{font-family:-apple-system,system-ui,sans-serif;background:#1a1a2e;color:#eee;padding:20px}}
.summary-bar{{display:flex;gap:16px;margin-bottom:20px}}
.stat{{background:#16213e;padding:12px 20px;border-radius:8px;text-align:center}}
.stat-num{{font-size:2em;font-weight:bold;display:block}}
.stat-label{{font-size:.85em;color:#aaa}}
table{{width:100%;border-collapse:collapse;margin-top:16px}}
th{{background:#16213e;padding:10px;text-align:left;border-bottom:2px solid #0f3460}}
td{{padding:8px;border-bottom:1px solid #0f3460}}
tr.pass{{background:#1a3a2e}}tr.fail{{background:#3a1a1e}}
.status-pass{{color:#4ecdc4;font-weight:bold}}.status-fail{{color:#ff6b6b;font-weight:bold}}
.dep-svg{{border:1px solid #333;border-radius:8px;margin-top:16px}}
.dep-node{{fill:#4ecdc4;stroke:#16213e;stroke-width:2}}
.dep-edge{{stroke:#555;stroke-width:1}}
.dep-label{{font-size:10px;fill:#eee;text-anchor:middle}}
.bars{{margin-top:16px}}
.bar-row{{display:flex;align-items:center;margin-bottom:8px}}
.bar-label{{width:100px;color:#aaa}}
.bar-track{{width:100%;background:#16213e;height:24px;border-radius:4px}}
.bar-fill{{height:24px;border-radius:4px;padding-left:8px;color:#1a1a2e;font-size:.85em;display:flex;align-items:center}}
</style></head>
<body><h1>{html.escape(title)}</h1><p class="timestamp">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
{body}
</body></html>"""

    def _write_report(self, output_dir: str, filename: str, content: str) -> str:
        """写入报告文件"""
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Report written to {filepath}")
        return filepath


# ═══════════════════════════════════════════════════════════
#  DOT 报告生成器 (Graphviz)
# ═══════════════════════════════════════════════════════════

class DOTReportGenerator:
    """
    DOT 格式报告生成器——输出 Graphviz DOT, 供 `dot -Tpng` 渲染

    用法:
        gen = DOTReportGenerator()
        dot_str = gen.generate_dependency_dot(dep_graph)
        # dot -Tpng -o dep.png <<< dot_str
    """

    def generate_dependency_dot(self, dep_graph: Any) -> str:
        """生成依赖图 DOT"""
        lines = ["digraph dependencies {", "  node [shape=box, style=filled, fillcolor=\"#4ecdc4\", fontcolor=\"#1a1a2e\"];",
                  "  edge [color=\"#555\"];"]

        if hasattr(dep_graph, 'nodes'):
            for nid in dep_graph.nodes:
                label = str(dep_graph.nodes[nid])
                lines.append(f"  \"{nid}\" [label=\"{label}\"];")
            for src, targets in dep_graph.edges.items():
                for tgt in targets:
                    lines.append(f"  \"{src}\" -> \"{tgt}\";")

        lines.append("}")
        return "\n".join(lines)

    def generate_call_graph_dot(self, call_graph: Any) -> str:
        """生成调用图 DOT"""
        lines = ["digraph callgraph {", "  node [shape=ellipse, style=filled, fillcolor=\"#ffe66d\"];",
                  "  edge [color=\"#ff6b6b\"];"]

        if hasattr(call_graph, 'calls'):
            for caller, callees in call_graph.calls.items():
                lines.append(f"  \"{caller}\";")
                for callee in callees:
                    lines.append(f"  \"{caller}\" -> \"{callee}\";")

        lines.append("}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
#  DSM 方阵报告 (Dependency Structure Matrix)
# ═══════════════════════════════════════════════════════════

class DSMReport:
    """
    依赖结构方阵——行=源模块, 列=目标模块, 1=有依赖

    像 SonarQube 商业版的 DSM 视图
    """

    def generate_dsm(
        self,
        dep_graph: Any,
        output_format: str = "text",
    ) -> str:
        """生成 DSM 方阵"""
        # 收集模块列表
        modules = []
        if hasattr(dep_graph, 'nodes'):
            modules = sorted(dep_graph.nodes.keys())
        else:
            modules = sorted(set(str(k) for k in getattr(dep_graph, 'edges', {}).keys()))

        n = len(modules)
        if n == 0:
            return "(empty dependency graph)"

        # 构建 DSM matrix
        matrix = [[0] * n for _ in range(n)]
        if hasattr(dep_graph, 'edges'):
            for src, targets in dep_graph.edges.items():
                if src in modules:
                    si = modules.index(src)
                    for tgt in targets:
                        if tgt in modules:
                            ti = modules.index(tgt)
                            matrix[si][ti] = 1

        if output_format == "html":
            return self._dsm_html(modules, matrix)
        elif output_format == "json":
            return json.dumps({"modules": modules, "matrix": matrix})
        else:
            return self._dsm_text(modules, matrix)

    def _dsm_text(self, modules: list, matrix: list) -> str:
        """纯文本 DSM"""
        # 计算列宽
        max_len = max(len(m) for m in modules) if modules else 8
        col_width = max(max_len, 3) + 1

        # 头部
        header = " " * col_width + "".join(m[:3].ljust(col_width) for m in modules)
        lines = [header]

        # 矩阵行
        for i, mod in enumerate(modules):
            row_label = mod[:max_len].ljust(col_width)
            cells = "".join((" 1 " if matrix[i][j] else " . ").ljust(col_width) for j in range(len(modules)))
            lines.append(row_label + cells)

        return "\n".join(lines)

    def _dsm_html(self, modules: list, matrix: list) -> str:
        """HTML DSM"""
        cells_html = ""
        for i, mod in enumerate(modules):
            cells_html += f"<tr><td class='label'>{html.escape(mod)}</td>"
            for j in range(len(modules)):
                cell_class = "dep" if matrix[i][j] else "empty"
                cells_html += f"<td class='{cell_class}'></td>"
            cells_html += "</tr>\n"

        header_cells = "".join(f"<th>{html.escape(m[:8])}</th>" for m in modules)

        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>DSM Report</title>
<style>
body{{font-family:sans-serif;background:#1a1a2e;color:#eee;padding:20px}}
table{{border-collapse:collapse}}
th,td{{width:28px;height:28px;border:1px solid #333;text-align:center;font-size:.75em}}
th{{background:#16213e;color:#aaa}}
td.label{{background:#16213e;color:#eee;width:auto;text-align:left;padding:4px 8px;white-space:nowrap}}
td.dep{{background:#4ecdc4}}td.empty{{background:#16213e}}
</style></head>
<body><h1>Dependency Structure Matrix</h1>
<table><thead><tr><th></th>{header_cells}</tr></thead>
<tbody>{cells_html}</tbody></table></body></html>"""
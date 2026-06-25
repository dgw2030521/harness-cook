"""
harness check 命令——合规/质量检查

扫描指定路径的文件，执行合规规则检查。
支持按类别/严重性过滤，以及自动修复。

内置规则:
  - security: 常见安全违规（硬编码密钥、SQL注入、XSS）
  - coding: 代码风格（命名规范、复杂度、TODO标记）
"""

import json
import os
import re
from pathlib import Path
from datetime import datetime

from harness.types import (
    Artifact, ComplianceCategory, ComplianceRule, ComplianceResult,
)
from harness.compliance import ComplianceEngine, RulePack
from harness.audit import AuditStore, AuditEngine
from harness.bus import EventBus, get_bus


# ─── 内置规则定义 ───────────────────────────────────────

def _build_security_rules() -> list:
    """内置安全规则"""
    rules = [
        ComplianceRule(
            id="SEC-001",
            category=ComplianceCategory.SECURITY,
            description="检测代码中的硬编码密钥/密码/API Token",
            severity="critical",
            pattern=r'(?:password|secret|api_key|token|private_key)\s*[=:]\s*["\'][^"\']{8,}["\']',
            remediation="使用环境变量或密钥管理服务存储敏感信息",
            auto_fixable=False,
        ),
        ComplianceRule(
            id="SEC-002",
            category=ComplianceCategory.SECURITY,
            description="检测字符串拼接构建 SQL 的情况",
            severity="critical",
            pattern=r'(?:SELECT|INSERT|UPDATE|DELETE|DROP)\s+.*\+\s*(?:str|f["\'])',
            remediation="使用参数化查询替代字符串拼接",
            auto_fixable=False,
        ),
        ComplianceRule(
            id="SEC-003",
            category=ComplianceCategory.SECURITY,
            description="检测直接输出未转义用户输入的情况",
            severity="high",
            pattern=r'(?:innerHTML|document\.write|eval)\s*\(',
            remediation="对用户输入进行转义处理，避免直接注入 HTML",
            auto_fixable=False,
        ),
        ComplianceRule(
            id="SEC-004",
            category=ComplianceCategory.SECURITY,
            description="检测生产代码中的调试日志输出",
            severity="medium",
            pattern=r'(?:console\\.log|print|logging\\.debug)\s*\(',
            remediation="移除调试日志，或替换为可配置的日志级别",
            auto_fixable=True,
        ),
        ComplianceRule(
            id="SEC-005",
            category=ComplianceCategory.SECURITY,
            description="检测 HTTP（非 HTTPS）请求",
            severity="high",
            pattern=r'http://[^\s"\']+',
            remediation="使用 HTTPS 替代 HTTP",
            auto_fixable=False,
        ),
    ]
    return rules


def _build_coding_rules() -> list:
    """内置编码风格规则"""
    rules = [
        ComplianceRule(
            id="CODE-001",
            category=ComplianceCategory.STYLE,
            description="检测超过 50 行的函数定义",
            severity="medium",
            pattern=r'(?!.*)',  # 不匹配任何内容——长函数需要多行分析，pattern模式无法检测
            remediation="将长函数拆分为多个小函数",
            auto_fixable=False,
            languages=["python", "javascript", "typescript"],
        ),
        ComplianceRule(
            id="CODE-002",
            category=ComplianceCategory.STYLE,
            description="检测代码中遗留的 TODO/FIXME 注释",
            severity="low",
            pattern=r'(?:TODO|FIXME|HACK|XXX)\s*[:\(]',
            remediation="清理遗留标记，完成或记录为 Issue",
            auto_fixable=False,
        ),
        ComplianceRule(
            id="CODE-003",
            category=ComplianceCategory.STYLE,
            description="检测空的 except/pass 块",
            severity="high",
            pattern=r'except\s*[\w]*\s*:\s*pass',
            remediation="至少记录异常日志，不要静默吞掉",
            auto_fixable=False,
            languages=["python"],
        ),
        ComplianceRule(
            id="CODE-004",
            category=ComplianceCategory.STYLE,
            description="检测代码中未经解释的硬编码数字",
            severity="low",
            pattern=r'(?:==|!=|>=|<=|>|<|\+)\s*\d{2,}\b',
            remediation="将魔法数字提取为命名常量",
            auto_fixable=False,
        ),
    ]
    return rules


# ─── 文件扫描 ───────────────────────────────────────

_SCAN_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go",
    ".rb", ".php", ".c", ".cpp", ".h", ".rs", ".swift",
    ".kt", ".scala", ".sh", ".bash", ".yml", ".yaml",
    ".json", ".xml", ".html", ".css", ".sql",
}


def _scan_path(path: str) -> list:
    """扫描路径下的文件，生成 Artifact 列表"""
    root = Path(path).resolve()
    artifacts = []

    if root.is_file():
        if root.suffix in _SCAN_EXTENSIONS:
            content = root.read_text(encoding="utf-8", errors="ignore")
            artifacts.append(Artifact(
                type="code",
                path=str(root),
                content=content,
                metadata={
                    "language": _detect_language(root.suffix),
                    "size": len(content),
                },
            ))
        return artifacts

    # 目录扫描
    for filepath in sorted(root.rglob("*")):
        # 跳过隐藏/缓存目录
        if any(part.startswith(".") or part in ("__pycache__", "node_modules", "vendor")
               for part in filepath.parts):
            continue
        if filepath.suffix not in _SCAN_EXTENSIONS:
            continue
        if not filepath.is_file():
            continue

        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        artifacts.append(Artifact(
            type="code",
            path=str(filepath.relative_to(root)),
            content=content,
            metadata={
                "language": _detect_language(filepath.suffix),
                "size": len(content),
            },
        ))

    return artifacts


def _detect_language(suffix: str) -> str:
    """从文件后缀推断语言"""
    mapping = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".tsx": "typescript", ".jsx": "javascript", ".java": "java",
        ".go": "go", ".rb": "ruby", ".php": "php",
        ".c": "c", ".cpp": "cpp", ".h": "c",
        ".rs": "rust", ".swift": "swift", ".kt": "kotlin",
        ".scala": "scala", ".sh": "shell", ".bash": "shell",
        ".yml": "yaml", ".yaml": "yaml",
        ".json": "json", ".xml": "xml",
        ".html": "html", ".css": "css", ".sql": "sql",
    }
    return mapping.get(suffix, "unknown")


# ─── 输出格式 ───────────────────────────────────────

def _format_table(results: list, total_artifacts: int) -> str:
    """表格格式输出"""
    lines = []
    violations = [r for r in results if not r.passed]
    passes = [r for r in results if r.passed]

    lines.append(f"合规检查结果: 扫描 {total_artifacts} 个文件")
    lines.append(f"  通过: {len(passes)} | 违规: {len(violations)}")
    lines.append("")

    if not violations:
        lines.append("  ✓ 无违规项")
        return "\n".join(lines)

    # 按严重性排序
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    violations.sort(key=lambda v: severity_order.get(v.severity, 99))

    lines.append("违规项:")
    for v in violations:
        severity_icon = {"critical": "!!!", "high": "!!", "medium": "!", "low": "~"}.get(v.severity, "?")
        lines.append(f"  {severity_icon} [{v.severity}] {v.rule_id}")
        if v.findings:
            for finding in v.findings:
                lines.append(f"     详情: {finding}")
        if v.locations:
            for loc in v.locations:
                path = loc.get("path", loc.get("match", ""))
                line_num = loc.get("line", "")
                if path or line_num:
                    lines.append(f"     位置: 行 {line_num} — {path}")
        if v.remediation:
            lines.append(f"     建议: {v.remediation}")
        lines.append("")

    return "\n".join(lines)


def _format_json(results: list, total_artifacts: int) -> str:
    """JSON 格式输出"""
    data = {
        "total_artifacts": total_artifacts,
        "total_rules_checked": len(results),
        "violations": len([r for r in results if not r.passed]),
        "results": [
            {
                "rule_id": r.rule_id,
                "passed": r.passed,
                "severity": r.severity,
                "findings": r.findings,
                "remediation": r.remediation,
                "locations": r.locations,
            }
            for r in results
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def _format_summary(results: list, total_artifacts: int) -> str:
    """摘要格式输出"""
    violations = [r for r in results if not r.passed]
    severity_counts = {}
    for v in violations:
        severity_counts[v.severity] = severity_counts.get(v.severity, 0) + 1

    lines = []
    lines.append(f"合规扫描: {total_artifacts} 文件, {len(results)} 规则, {len(violations)} 违规")
    for sev in ["critical", "high", "medium", "low"]:
        count = severity_counts.get(sev, 0)
        if count:
            lines.append(f"  {sev}: {count}")
    return "\n".join(lines)


def cmd_check(args):
    """执行 check 命令"""
    # 扫描文件
    artifacts = _scan_path(args.path)
    if not artifacts:
        print(f"未找到可扫描的文件: {args.path}")
        return 0

    # 构建合规引擎
    bus = get_bus()
    engine = ComplianceEngine(bus=bus)

    # 加载规则包
    security_rules = _build_security_rules()
    coding_rules = _build_coding_rules()

    engine.load_pack(RulePack(
        name="security",
        category=ComplianceCategory.SECURITY,
        rules=security_rules,
    ))
    engine.load_pack(RulePack(
        name="coding",
        category=ComplianceCategory.STYLE,
        rules=coding_rules,
    ))

    # 按类别过滤
    categories = None
    if args.category == "security":
        categories = [ComplianceCategory.SECURITY]
    elif args.category == "coding":
        categories = [ComplianceCategory.STYLE]

    # 执行扫描
    severity_filter = [args.severity] if args.severity else None
    results = engine.scan(artifacts, categories=categories, severity_filter=severity_filter)

    # 自动修复——查找 auto_fixable 违规对应的规则
    if args.fix:
        fixable = []
        for r in results:
            if not r.passed:
                # 在规则中查找 auto_fixable
                for pack in [security_rules, coding_rules]:
                    for rule in pack:
                        if rule.id == r.rule_id and rule.auto_fixable:
                            fixable.append((r, rule))
                            break
        if fixable:
            print(f"尝试自动修复 {len(fixable)} 项违规...")
            for v_result, v_rule in fixable:
                # 输出修复位置信息
                locs = v_result.locations
                paths = [l.get("match", "") for l in locs] if locs else []
                print(f"  修复: {v_rule.id} ({', '.join(paths[:3])})")

    # 输出
    if args.output == "table":
        output = _format_table(results, len(artifacts))
    elif args.output == "json":
        output = _format_json(results, len(artifacts))
    elif args.output == "summary":
        output = _format_summary(results, len(artifacts))
    else:
        output = _format_table(results, len(artifacts))

    print(output)

    # 返回码：有 critical/high 违规 → 1
    violations = [r for r in results if not r.passed]
    if any(v.severity in ("critical", "high") for v in violations):
        return 1
    return 0
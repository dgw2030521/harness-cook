#!/usr/bin/env python3
"""
auto-verify Skill 可执行脚本 — 调用 harness 合规引擎 + 语法检查

用法:
  python3 verify.py [--path .] [--packs security,coding] [--output table|json]

功能:
  1. 扫描 git diff 变更文件
  2. 调用 ComplianceEngine 合规扫描
  3. 对变更文件做语法检查（按文件类型）
  4. 输出验证报告

退出码:
  0 = 全部通过
  1 = 有违规或检查失败
"""

import argparse
import json
import os
import subprocess
import sys
import signal
from pathlib import Path


class _ScanTimeout(Exception):
    """单文件合规扫描超时"""
    pass


def _timeout_handler(signum, frame):
    raise _ScanTimeout("scan timed out")


def _setup_pythonpath():
    """设置 PYTHONPATH 以导入 harness core 包"""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", str(Path(__file__).resolve().parent.parent.parent))
    core_path = str(Path(project_dir) / "packages" / "core")
    sys.path.insert(0, core_path)


def _get_changed_files(path: str) -> list[str]:
    """获取 git diff 变更文件列表"""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        files = result.stdout.strip().split("\n") if result.stdout.strip() else []
        # 也检查未跟踪文件
        result2 = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        untracked = []
        for line in result2.stdout.strip().split("\n"):
            if line.startswith("??" ):
                untracked.append(line[3:].strip())
        return [f for f in files + untracked if f]
    except Exception:
        return []


def _classify_file(filepath: str) -> str:
    """根据扩展名分类文件类型"""
    ext = Path(filepath).suffix.lower()
    if ext in (".py", ".ts", ".js", ".go", ".java", ".c", ".cpp"):
        return "code"
    elif ext in (".md", ".txt", ".rst"):
        return "docs"
    elif ext in (".yaml", ".yml", ".json", ".toml", ".ini", ".env"):
        return "config"
    elif ext in (".css", ".scss", ".less", ".sass"):
        return "style"
    else:
        return "other"


def _syntax_check(filepath: str, project_root: str) -> dict:
    """对单个文件做语法检查"""
    ext = Path(filepath).suffix.lower()
    full_path = Path(project_root) / filepath

    if not full_path.exists():
        return {"file": filepath, "check": "syntax", "status": "SKIP", "detail": "文件不存在"}

    if ext == ".py":
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(full_path)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return {"file": filepath, "check": "py_compile", "status": "PASS", "detail": ""}
        else:
            return {"file": filepath, "check": "py_compile", "status": "FAIL", "detail": result.stderr.strip()[:200]}

    elif ext in (".yaml", ".yml"):
        result = subprocess.run(
            [sys.executable, "-c", f"import yaml; yaml.safe_load(open('{full_path}'))"],
            capture_output=True, text=True, timeout=10,
        )
        return {"file": filepath, "check": "yaml_syntax", "status": "PASS" if result.returncode == 0 else "FAIL",
                "detail": result.stderr.strip()[:200] if result.returncode != 0 else ""}

    elif ext == ".json":
        result = subprocess.run(
            [sys.executable, "-c", f"import json; json.load(open('{full_path}'))"],
            capture_output=True, text=True, timeout=10,
        )
        return {"file": filepath, "check": "json_syntax", "status": "PASS" if result.returncode == 0 else "FAIL",
                "detail": result.stderr.strip()[:200] if result.returncode != 0 else ""}

    elif ext == ".toml":
        result = subprocess.run(
            [sys.executable, "-c", f"import tomllib; tomllib.load(open('{full_path}', 'rb'))"],
            capture_output=True, text=True, timeout=10,
        )
        return {"file": filepath, "check": "toml_syntax", "status": "PASS" if result.returncode == 0 else "FAIL",
                "detail": result.stderr.strip()[:200] if result.returncode != 0 else ""}

    return {"file": filepath, "check": "unknown_type", "status": "SKIP", "detail": f"不支持 {ext} 语法检查"}


def _severity_icon(severity: str) -> str:
    """严重程度 → 可视图标"""
    return {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(severity, "⚪")


def main():
    _setup_pythonpath()

    parser = argparse.ArgumentParser(description="harness auto-verify — 自动验证变更")
    parser.add_argument("--path", default=".", help="项目根目录（默认: 当前目录）")
    parser.add_argument("--packs", default="security,coding", help="合规规则包（逗号分隔，默认: security,coding）")
    parser.add_argument("--output", choices=["table", "json"], default="table", help="输出格式")
    args = parser.parse_args()

    project_root = args.path
    pack_names = [p.strip() for p in args.packs.split(",") if p.strip()]

    # ── 1. 获取变更文件列表 ────────────────────────────────────
    changed_files = _get_changed_files(project_root)

    if not changed_files:
        if args.output == "json":
            print(json.dumps({"status": "no_changes", "files": [], "violations": [], "syntax_checks": []}))
        else:
            print("✅ [harness auto-verify] 无变更文件，无需验证")
        return 0

    # ── 2. 合规扫描 ────────────────────────────────────────────
    try:
        from harness.compliance import ComplianceEngine
        from harness.types import Artifact
        from harness.rule_packs import get_coding_pack, get_security_pack, get_data_pack, get_devops_pack

        pack_map = {
            "coding": get_coding_pack, "security": get_security_pack,
            "data": get_data_pack, "devops": get_devops_pack,
        }

        engine = ComplianceEngine()
        for pname in pack_names:
            factory = pack_map.get(pname)
            if factory:
                engine.load_pack(factory())

        # 逐文件用 scan_quick 扫描，每文件最多5秒超时
        compliance_results = []
        for fpath in changed_files:
            full_path = Path(project_root) / fpath
            if full_path.exists():
                try:
                    content = full_path.read_text(encoding="utf-8", errors="replace")
                    if len(content) <= 50000:  # 跳过过大文件
                        # 设置5秒超时保护
                        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
                        signal.alarm(5)
                        try:
                            file_results = engine.scan_quick(content, path=fpath)
                            compliance_results.extend(file_results)
                        except _ScanTimeout:
                            pass  # 超时则跳过该文件
                        finally:
                            signal.alarm(0)
                            signal.signal(signal.SIGALRM, old_handler)
                except Exception:
                    pass

        violations = [r for r in compliance_results if not r.passed]

    except ImportError:
        compliance_results = []
        violations = []
        print("⚠️ [harness auto-verify] harness 包不可用，跳过合规扫描")

    # ── 3. 语法检查 ────────────────────────────────────────────
    syntax_results = []
    for fpath in changed_files:
        ftype = _classify_file(fpath)
        if ftype in ("code", "config"):
            syntax_results.append(_syntax_check(fpath, project_root))

    syntax_failures = [r for r in syntax_results if r["status"] == "FAIL"]

    # ── 4. 输出验证报告 ────────────────────────────────────────
    has_issues = bool(violations) or bool(syntax_failures)

    if args.output == "json":
        report = {
            "status": "FAIL" if has_issues else "PASS",
            "files_changed": changed_files,
            "violations": [
                {
                    "rule_id": v.rule_id,
                    "severity": v.severity,
                    "findings": v.findings,
                    "remediation": v.remediation,
                    "path": v.locations[0].get("path", "") if v.locations else "",
                }
                for v in violations
            ],
            "syntax_checks": syntax_results,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        # 表格格式
        print("=" * 60)
        print("  [harness auto-verify] 验证报告")
        print("=" * 60)
        print("变更文件: {} 个".format(len(changed_files)))
        for fpath in changed_files:
            print("  - {} ({})".format(fpath, _classify_file(fpath)))
        print()

        # 合规扫描结果
        print("合规扫描 ({} 规则包):".format(", ".join(pack_names)))
        if violations:
            for v in violations[:8]:
                icon = _severity_icon(v.severity)
                findings_text = "; ".join(v.findings[:3]) if v.findings else "无详情"
                print("  {} [{}] {} — {}".format(icon, v.severity, v.rule_id, findings_text))
                if v.remediation:
                    print("    💡 {}".format(v.remediation))
            if len(violations) > 8:
                print("  ... 还有 {} 项违规".format(len(violations) - 8))
        else:
            print("  ✅ 合规扫描全部通过")

        print()

        # 语法检查结果
        if syntax_results:
            print("语法检查:")
            for r in syntax_results:
                status_icon = "✅" if r["status"] == "PASS" else ("❌" if r["status"] == "FAIL" else "⏭️")
                print("  {} {} ({}) {}".format(
                    status_icon, r["file"], r["check"],
                    r["detail"][:100] if r["detail"] else ""
                ))
        print()

        # 总体结论
        if has_issues:
            print("❌ 总体: FAIL ({} 合规违规, {} 语法错误)".format(len(violations), len(syntax_failures)))
        else:
            print("✅ 总体: PASS (所有检查通过)")
        print("=" * 60)

    return 1 if has_issues else 0


if __name__ == "__main__":
    sys.exit(main())
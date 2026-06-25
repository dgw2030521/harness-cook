#!/usr/bin/env python3
"""
auto-review Skill 可执行脚本 — 调用 harness GateEngine 门禁检查

用法:
  python3 review_gate.py [--path .] [--mode strict|hybrid|loose] [--output table|json]

功能:
  1. 获取变更文件内容
  2. 调用 GateEngine.check 执行门禁检查
  3. 输出门禁结果（通过/升级/需修复）
  4. 如果有 violations，输出详细审查反馈

退出码:
  0 = 门禁通过
  1 = 门禁不通过
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


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
            cwd=path, capture_output=True, text=True, timeout=10,
        )
        files = result.stdout.strip().split("\n") if result.stdout.strip() else []
        return [f for f in files if f]
    except Exception:
        return []


def _classify_file(filepath: str) -> str:
    """根据扩展名分类文件类型"""
    ext = Path(filepath).suffix.lower()
    if ext in (".py", ".ts", ".js", ".go", ".java", ".c", ".cpp"):
        return "code"
    elif ext in (".yaml", ".yml", ".json", ".toml", ".ini", ".env"):
        return "config"
    else:
        return "other"


def main():
    _setup_pythonpath()

    parser = argparse.ArgumentParser(description="harness auto-review — 门禁审查")
    parser.add_argument("--path", default=".", help="项目根目录")
    parser.add_argument("--mode", choices=["strict", "hybrid", "loose"], default="hybrid",
                        help="门禁模式（默认: hybrid）")
    parser.add_argument("--output", choices=["table", "json"], default="table", help="输出格式")
    args = parser.parse_args()

    # ── 1. 获取变更文件 ────────────────────────────────────────
    changed_files = _get_changed_files(args.path)

    if not changed_files:
        if args.output == "json":
            print(json.dumps({"gate_passed": True, "message": "无变更文件，门禁默认通过"}))
        else:
            print("✅ [harness auto-review] 无变更文件，门禁默认通过")
        return 0

    # ── 2. 构建 Artifact 列表 ──────────────────────────────────
    try:
        from harness.types import Artifact, GateMode
        from harness.gates import GateEngine, default_coding_gate

        mode_map = {"strict": GateMode.STRICT, "hybrid": GateMode.HYBRID, "loose": GateMode.LOOSE}
        gate_mode = mode_map[args.mode]

        artifacts = []
        for fpath in changed_files:
            full_path = Path(args.path) / fpath
            if full_path.exists():
                try:
                    content = full_path.read_text(encoding="utf-8", errors="replace")
                    if len(content) <= 50000:
                        artifacts.append(Artifact(type=_classify_file(fpath), path=fpath, content=content))
                except Exception:
                    pass

        if not artifacts:
            if args.output == "json":
                print(json.dumps({"gate_passed": True, "message": "无可扫描文件"}))
            else:
                print("✅ [harness auto-review] 无可扫描文件，门禁默认通过")
            return 0

        # ── 3. 执行门禁检查 ──────────────────────────────────────
        gate_def = default_coding_gate()
        gate_def.mode = gate_mode  # 覆盖为用户指定的模式

        gate_engine = GateEngine()
        gate_result = gate_engine.check(artifacts, gate_def)

    except ImportError:
        if args.output == "json":
            print(json.dumps({"gate_passed": None, "message": "harness 包不可用，无法执行门禁检查"}))
        else:
            print("⚠️ [harness auto-review] harness 包不可用，无法执行门禁检查")
        return 0

    # ── 4. 输出结果 ────────────────────────────────────────────
    if args.output == "json":
        report = {
            "gate_id": gate_result.gate_id,
            "gate_passed": gate_result.passed,
            "gate_mode": args.mode,
            "total_checks": gate_result.total_checks,
            "passed_checks": gate_result.passed_checks,
            "failed_checks": gate_result.failed_checks,
            "auto_fixed": gate_result.auto_fixed,
            "escalated": gate_result.escalated,
            "escalation_reason": gate_result.escalation_reason,
            "check_results": [
                {
                    "passed": cr.passed,
                    "severity": cr.severity,
                    "message": cr.message,
                }
                for cr in gate_result.check_results
            ],
            "files_checked": changed_files,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=" * 60)
        print("  [harness auto-review] 门禁审查报告")
        print("=" * 60)
        print("门禁模式: {}".format(args.mode))
        print("检查文件: {} 个".format(len(changed_files)))
        print()

        if gate_result.passed:
            print("✅ 门禁通过 ({}/{})".format(gate_result.passed_checks, gate_result.total_checks))
        else:
            print("❌ 门禁不通过 ({}/{})".format(gate_result.failed_checks, gate_result.total_checks))

            for cr in gate_result.check_results:
                if not cr.passed:
                    icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(cr.severity, "⚪")
                    print("  {} [{}] {}".format(icon, cr.severity, cr.message))

            if gate_result.escalated:
                print("⚠️ 已升级人工 — 原因: {}".format(gate_result.escalation_reason or "critical 级别违规"))

        if gate_result.auto_fixed:
            print("🔧 自动修复了 {} 项".format(gate_result.auto_fixed))

        print("=" * 60)

    return 0 if gate_result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
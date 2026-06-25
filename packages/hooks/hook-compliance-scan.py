#!/usr/bin/env python3
"""
harness PostToolUse(Write|Edit) hook — 合规扫描

每次写文件后自动扫描安全/编码合规，有违规时通过 systemMessage 注入提醒。
不阻断操作（continue=True），只是提醒 Claude 注意。

性能保障:
  - 全局 8 秒超时（含引擎初始化），超时静默跳过
  - scan_quick 单次调用 5 秒超时
  - 超过 50KB 的文件跳过

stdin JSON 格式:
  { "tool_name": "Write|Edit", "tool_input": {"file_path": "...", ...}, "tool_result": "...", ... }

stdout JSON 格式:
  { "continue": true, "systemMessage": "[harness 合规扫描] ..." }  — 有违规
  { "continue": true }                                              — 无违规或异常
"""

import signal
import sys
import os
import json
from pathlib import Path


class _GlobalTimeout(Exception):
    """全局超时"""
    pass


class _ScanTimeout(Exception):
    """单次扫描超时"""
    pass


def _global_timeout_handler(signum, frame):
    raise _GlobalTimeout("hook global timeout")


def _scan_timeout_handler(signum, frame):
    raise _ScanTimeout("scan timed out")


def _setup_pythonpath():
    """设置 PYTHONPATH 以导入 harness core 包"""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    core_path = str(Path(project_dir) / "packages" / "core")
    sys.path.insert(0, core_path)


def _get_session_id(input_data: dict) -> str:
    """
    获取 session_id

    优先级：
      1. stdin JSON 的 session_id 字段
      2. .harness/session_id 文件
      3. 降级为 "unknown"
    """
    session_id = input_data.get("session_id")
    if session_id:
        return session_id

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    session_file = Path(project_dir) / ".harness" / "session_id"
    try:
        if session_file.exists():
            sid = session_file.read_text(encoding="utf-8").strip()
            if sid:
                return sid
    except Exception:
        pass

    return "unknown"


def _severity_icon(severity: str) -> str:
    """严重程度 → 可视图标"""
    return {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(severity, "⚪")


def main():
    # ── 全局 8 秒超时保护 ──────────────────────────────────────
    old_global = signal.signal(signal.SIGALRM, _global_timeout_handler)
    signal.alarm(8)

    try:
        _setup_pythonpath()

        # ── 1. 从 stdin 读取 JSON ──────────────────────────────
        try:
            input_data = json.loads(sys.stdin.read())
        except (json.JSONDecodeError, ValueError):
            print(json.dumps({"continue": True}))
            return

        tool_input = input_data.get("tool_input", {})
        tool_name = input_data.get("tool_name", "")
        file_path = tool_input.get("file_path", "")
        session_id = _get_session_id(input_data)

        if not file_path:
            print(json.dumps({"continue": True}))
            return

        # ── 2. 检查文件存在并读取内容 ──────────────────────────
        target = Path(file_path)
        if not target.exists():
            print(json.dumps({"continue": True}))
            return

        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except Exception:
            print(json.dumps({"continue": True}))
            return

        # 超过 50KB 的文件跳过
        if len(content) > 50000:
            print(json.dumps({"continue": True}))
            return

        # ── 3. 导入 harness 并运行合规扫描 ──────────────────────
        try:
            from harness.compliance import ComplianceEngine
            from harness.rule_packs import get_coding_pack, get_security_pack
        except ImportError:
            print(json.dumps({"continue": True}))
            return

        try:
            engine = ComplianceEngine()
            engine.load_pack(get_coding_pack())
            engine.load_pack(get_security_pack())

            # scan_quick + 5秒超时
            signal.signal(signal.SIGALRM, _scan_timeout_handler)
            signal.alarm(5)
            try:
                results = engine.scan_quick(content, path=file_path)
            except _ScanTimeout:
                print(json.dumps({"continue": True}))
                return
            finally:
                signal.alarm(0)

            violations = [r for r in results if not r.passed]

            if violations:
                # ── 记录合规审计 ─────────────────────────────
                try:
                    from harness.audit_logger import log_compliance_scan
                    violations_detail = [
                        {
                            "rule_id": v.rule_id,
                            "severity": v.severity,
                            "finding": "; ".join(v.findings[:3]) if v.findings else "无详情",
                            "remediation": v.remediation or "",
                        }
                        for v in violations[:8]
                    ]
                    log_compliance_scan(
                        file_path=file_path,
                        tool_name=tool_name,
                        violations=violations_detail,
                        session_id=session_id,
                    )
                except Exception:
                    pass  # 审计失败不影响主流程

                msg_lines = [
                    "[harness 合规扫描] {} 发现 {} 项违规:".format(
                        Path(file_path).name, len(violations)
                    )
                ]
                for v in violations[:8]:
                    icon = _severity_icon(v.severity)
                    findings_text = "; ".join(v.findings[:3]) if v.findings else "无详情"
                    msg_lines.append(
                        "  {} [{}] {} — {}".format(
                            icon, v.severity, v.rule_id, findings_text
                        )
                    )
                    if v.remediation:
                        msg_lines.append("    💡 修复建议: {}".format(v.remediation))

                if len(violations) > 8:
                    msg_lines.append("  ... 还有 {} 项违规未展示".format(len(violations) - 8))

                output = {
                    "continue": True,
                    "systemMessage": "\n".join(msg_lines),
                }
                print(json.dumps(output, ensure_ascii=False))
            else:
                print(json.dumps({"continue": True}))

        except Exception:
            print(json.dumps({"continue": True}))

    except _GlobalTimeout:
        # 全局超时 → 静默跳过，绝不阻断用户操作
        print(json.dumps({"continue": True}))
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_global)


if __name__ == "__main__":
    main()

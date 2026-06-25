#!/usr/bin/env python3
"""
harness PostToolUse(Bash) hook — PII 护栏检查

每次 Bash 命令执行后自动检测输出中的 PII（邮箱/手机号/身份证等），
发现时通过 systemMessage 提醒注意脱敏，同时记录审计日志。

stdin JSON 格式:
  { "tool_name": "Bash", "tool_input": {"command": "..."}, "tool_result": "...", ... }

stdout JSON 格式:
  { "continue": true, "systemMessage": "[harness PII 护栏] ..." }  — 发现 PII
  { "continue": true }                                              — 无 PII 或异常
"""

import sys
import os
import json
from pathlib import Path


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


def main():
    _setup_pythonpath()

    # ── 1. 从 stdin 读取 JSON ──────────────────────────────────
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        print(json.dumps({"continue": True}))
        return

    session_id = _get_session_id(input_data)

    tool_result = input_data.get("tool_result", "")
    # tool_result 可能是 str 或 dict（某些工具返回结构化结果）
    if isinstance(tool_result, dict):
        tool_result = json.dumps(tool_result, ensure_ascii=False)
    elif not isinstance(tool_result, str):
        tool_result = str(tool_result)

    # 太短的输出不值得扫描
    if not tool_result or len(tool_result) < 20:
        print(json.dumps({"continue": True}))
        return

    # ── 2. 导入 harness PII 检测器 ──────────────────────────────
    try:
        from harness.guardrails import PIIDetector
    except ImportError:
        print(json.dumps({"continue": True}))
        return

    # ── 3. 运行 PII 检测 ─────────────────────────────────────────
    try:
        detector = PIIDetector()
        findings = detector.detect(tool_result)

        if findings:
            # 收集 PII 类型统计
            pii_types = sorted(set(f.get("type", "unknown") for f in findings))
            msg = "[harness PII 护栏] Bash 输出中发现 {} 个 PII 实例（类型: {}）。请注意脱敏处理，避免泄露敏感信息。".format(
                len(findings), ", ".join(pii_types)
            )

            # ── 记录 PII 审计 ───────────────────────────────
            try:
                from harness.audit_logger import log_pii_detected
                # 构建 PII 发现详情（脱敏：不含原始匹配值）
                pii_findings = [
                    {
                        "type": f.get("type", "unknown"),
                        "position": "行{},列{}-{}".format(
                            tool_result[:f.get("start", 0)].count("\n") + 1,
                            f.get("start", 0),
                            f.get("end", 0),
                        ),
                    }
                    for f in findings[:10]
                ]
                command = input_data.get("tool_input", {}).get("command", "")
                log_pii_detected(
                    pii_count=len(findings),
                    pii_types=pii_types,
                    direction="output",
                    command=command,
                    pii_findings=pii_findings,
                    session_id=session_id,
                )
            except Exception:
                pass  # 审计失败不影响主流程

            print(json.dumps({"continue": True, "systemMessage": msg}, ensure_ascii=False))
        else:
            print(json.dumps({"continue": True}))

    except Exception:
        print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
harness UserPromptSubmit hook — 输入护栏

每次用户提交 prompt 时自动检查是否包含 PII（邮箱/手机号/身份证等），
发现时通过 systemMessage 提醒脱敏，但不阻断输入，同时记录审计日志。

stdin JSON 格式:
  { "user_prompt": "...", "session_id": "...", ... }

stdout JSON 格式:
  { "continue": true, "systemMessage": "[harness] 输入中检测到 PII..." }  — 发现 PII
  { "continue": true }                                                      — 无 PII
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

    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        print(json.dumps({"continue": True}))
        return

    session_id = _get_session_id(input_data)

    user_prompt = input_data.get("user_prompt", "")
    if not user_prompt:
        print(json.dumps({"continue": True}))
        return

    # ── 1. 导入 harness 输入护栏 ────────────────────────────────
    try:
        from harness.guardrails import PIIDetector
    except ImportError:
        print(json.dumps({"continue": True}))
        return

    # ── 2. PII 检测 ──────────────────────────────────────────────
    try:
        detector = PIIDetector()
        findings = detector.detect(user_prompt)

        if findings:
            pii_types = sorted(set(f.get("type", "unknown") for f in findings))
            # 展示前 3 个匹配的原文片段（用于提醒但不泄露完整 PII）
            samples = []
            for f in findings[:3]:
                match_text = f.get("match", "")
                # 部分遮掩：只显示前 2 和后 2 字符
                if len(match_text) > 6:
                    masked = match_text[:2] + "..." + match_text[-2:]
                else:
                    masked = "***"
                samples.append("{}({})".format(f.get("type", "?"), masked))

            msg = (
                "[harness 输入护栏] 您的输入中检测到 {} 个 PII 实例（类型: {}）。"
                "示例: {}。"
                "建议脱敏后再提交，避免敏感信息泄露。"
            ).format(
                len(findings),
                ", ".join(pii_types),
                ", ".join(samples),
            )

            # ── 记录 PII 审计 ───────────────────────────────
            try:
                from harness.audit_logger import log_pii_detected
                log_pii_detected(
                    pii_count=len(findings),
                    pii_types=pii_types,
                    direction="input",
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

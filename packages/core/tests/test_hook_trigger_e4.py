"""
E-4 验收测试：MCP hook_trigger 工具

验收标准：
1. harness_hook_trigger MCP 工具可调用并返回治理决策
2. 输入类槽位（pre_tool_use）→ InputGuardrails.check() → 返回 BLOCK/WARN/CONTINUE
3. 输出类槽位（post_tool_use）→ OutputGuardrails.check() → 返回 BLOCK/WARN/REDACT/CONTINUE
4. 无护栏类槽位（session_start）→ 返回 CONTINUE
5. 无效槽位 → 返回 CONTINUE + 原因说明
6. 缺少 content → 输入/输出类槽位返回 CONTINUE + 原因说明
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../mcp"))

from harness_mcp_server import HarnessMCPServer


def test_hook_trigger_input_slot():
    """验收标准2：输入类槽位 → InputGuardrails.check()"""
    server = HarnessMCPServer()

    # 正常输入内容
    result = server._tool_hook_trigger({
        "slot": "pre_tool_use",
        "content": "hello world",
        "tool_name": "Bash",
        "direction": "input",
    })

    assert "decision" in result, f"应返回 decision 字段: {result}"
    assert result["slot"] == "pre_tool_use", f"slot 应为 pre_tool_use: {result}"
    assert result["direction"] == "input", f"direction 应为 input: {result}"
    assert result["tool_name"] == "Bash", f"tool_name 应为 Bash: {result}"

    # 正常内容应返回 allow/warn/continue（不 BLOCK）
    decision = result["decision"]
    assert decision in ["allow", "warn", "continue", "WARN"], \
        f"正常输入应不被 BLOCK: decision={decision}"


def test_hook_trigger_output_slot_with_pii():
    """验收标准3：输出类槽位检测到 PII → 返回 REDACT/BLOCK"""
    server = HarnessMCPServer()

    # 包含 PII（邮箱）的内容
    result = server._tool_hook_trigger({
        "slot": "post_tool_use",
        "content": "User email is john.doe@example.com and password is mysecret12345678",
        "tool_name": "Write",
    })

    assert "decision" in result, f"应返回 decision 字段: {result}"
    assert result["slot"] == "post_tool_use", f"slot 应为 post_tool_use"
    # PII 检测应触发 REDACT 或 BLOCK
    decision = result["decision"]
    assert decision in ["redact", "block", "REDACT", "BLOCK"], \
        f"包含 PII 的输出应被 REDACT 或 BLOCK: decision={decision}"


def test_hook_trigger_no_guardrails_slot():
    """验收标准4：无护栏类槽位 → 返回 CONTINUE"""
    server = HarnessMCPServer()

    # session_start 不应有护栏检查
    result = server._tool_hook_trigger({
        "slot": "session_start",
    })

    assert result["decision"] == "CONTINUE", \
        f"session_start 应返回 CONTINUE: {result['decision']}"
    assert result["blocked"] is False, f"session_start 不应 blocked"
    assert "observational" in result["reason"].lower() or "no guardrails" in result["reason"].lower(), \
        f"reason 应说明无护栏检查: {result['reason']}"


def test_hook_trigger_invalid_slot():
    """验收标准5：无效槽位 → 返回 CONTINUE + 原因说明"""
    server = HarnessMCPServer()

    result = server._tool_hook_trigger({
        "slot": "invalid_slot_name",
    })

    assert result["decision"] == "CONTINUE", \
        f"无效槽位应返回 CONTINUE: {result['decision']}"
    assert "Unknown" in result["reason"], \
        f"reason 应包含 'Unknown': {result['reason']}"


def test_hook_trigger_missing_content_for_input_slot():
    """验收标准6：输入类槽位缺少 content → CONTINUE + 原因"""
    server = HarnessMCPServer()

    result = server._tool_hook_trigger({
        "slot": "pre_tool_use",
    })

    assert result["decision"] == "CONTINUE", \
        f"缺少 content 应返回 CONTINUE: {result['decision']}"
    assert "content" in result["reason"].lower(), \
        f"reason 应提及 content: {result['reason']}"


def test_hook_trigger_output_slot_no_pii():
    """输出类槽位检测到无 PII → 返回 CONTINUE/WARN"""
    server = HarnessMCPServer()

    result = server._tool_hook_trigger({
        "slot": "post_tool_use",
        "content": "This is a safe output with no sensitive data",
        "tool_name": "Write",
    })

    assert "decision" in result, f"应返回 decision: {result}"
    assert result["blocked"] is False, \
        f"无 PII 的输出不应 blocked: {result}"
    assert result["direction"] == "output", f"direction 应为 output"


def test_hook_trigger_all_output_slots():
    """所有输出类槽位应路由到 OutputGuardrails"""
    server = HarnessMCPServer()

    for slot in ["post_tool_use", "post_execute", "on_file_change"]:
        result = server._tool_hook_trigger({
            "slot": slot,
            "content": "safe content",
        })
        assert result["direction"] == "output", \
            f"{slot} 应路由到 output: {result}"


def test_hook_trigger_all_no_guardrails_slots():
    """所有无护栏类槽位应返回 CONTINUE"""
    server = HarnessMCPServer()

    no_guardrails_slots = [
        "session_start", "session_end",
        "on_error",
        "on_gate_pass", "on_gate_fail",
        "pre_commit", "post_commit",
        "on_delegate", "on_conflict",
        "on_decision", "on_escalation",
        "user_prompt_submit",
    ]

    for slot in no_guardrails_slots:
        result = server._tool_hook_trigger({
            "slot": slot,
        })
        assert result["decision"] == "CONTINUE", \
            f"{slot} 应返回 CONTINUE: decision={result['decision']}"


def test_tool_dispatch_has_hook_trigger():
    """MCP Server dispatch table 包含 harness_hook_trigger"""
    # harness_hook_trigger 方法存在于 HarnessMCPServer 上
    assert hasattr(HarnessMCPServer, "_tool_hook_trigger"), \
        "HarnessMCPServer 应有 _tool_hook_trigger 方法"


# ─── 运行所有测试 ────────────────────────────────────────

def run_all_tests():
    tests = [
        test_hook_trigger_input_slot,
        test_hook_trigger_output_slot_with_pii,
        test_hook_trigger_no_guardrails_slot,
        test_hook_trigger_invalid_slot,
        test_hook_trigger_missing_content_for_input_slot,
        test_hook_trigger_output_slot_no_pii,
        test_hook_trigger_all_output_slots,
        test_hook_trigger_all_no_guardrails_slots,
        test_tool_dispatch_has_hook_trigger,
    ]

    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
            print(f"✅ {test_fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"❌ {test_fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"❌ {test_fn.__name__}: 异常 {type(e).__name__}: {e}")

    print(f"\n结果：{passed} 通过，{failed} 失败")
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

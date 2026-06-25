"""
E-3 验收测试：Claude Code 适配器 matcher 精细化

验收标准：
1. Read/Grep 不触发合规扫描——post_tool_use matcher 不包含 Read/Grep/Glob
2. Write/Edit 触发合规扫描——post_tool_use matcher 包含 Write|Edit|NotebookEdit
3. Bash 触发输入护栏——pre_tool_use matcher 包含 Bash
4. 会话级保持全局触发——matcher 为空
5. 同一原生事件的不同 matcher 能正确合并（不互相覆盖）
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.adapters.claude_code import (
    ClaudeCodeAdapter,
    HOOK_POINT_MAP,
    HOOK_MATCHER_MAP,
)


def test_matcher_map_post_tool_use_write_only():
    """验收标准1+2：post_tool_use matcher 只包含写入操作，不含只读操作"""
    adapter = ClaudeCodeAdapter()

    # post_tool_use 的 matcher 应包含 Write/Edit/NotebookEdit
    matcher = HOOK_MATCHER_MAP.get("post_tool_use", "")
    assert "Write" in matcher, f"post_tool_use matcher 应包含 Write: {matcher}"
    assert "Edit" in matcher, f"post_tool_use matcher 应包含 Edit: {matcher}"

    # 不应包含只读操作
    assert "Read" not in matcher, f"post_tool_use matcher 不应包含 Read: {matcher}"
    assert "Grep" not in matcher, f"post_tool_use matcher 不应包含 Grep: {matcher}"
    assert "Glob" not in matcher, f"post_tool_use matcher 不应包含 Glob: {matcher}"
    assert "Agent" not in matcher, f"post_tool_use matcher 不应包含 Agent: {matcher}"

    # post_execute 和 on_file_change 同理
    for hp in ["post_execute", "on_file_change"]:
        m = HOOK_MATCHER_MAP.get(hp, "")
        assert "Write" in m, f"{hp} matcher 应包含 Write: {m}"
        assert "Read" not in m, f"{hp} matcher 不应包含 Read: {m}"


def test_matcher_map_pre_tool_use_bash():
    """验收标准3：pre_tool_use matcher 只包含 Bash"""
    adapter = ClaudeCodeAdapter()

    matcher = HOOK_MATCHER_MAP.get("pre_tool_use", "")
    assert "Bash" in matcher, f"pre_tool_use matcher 应包含 Bash: {matcher}"
    # 不应包含只读操作或其他写操作
    assert "Read" not in matcher, f"pre_tool_use matcher 不应包含 Read: {matcher}"
    assert "Write" not in matcher, f"pre_tool_use matcher 不应包含 Write: {matcher}"


def test_matcher_map_session_global():
    """验收标准4：会话级保持全局触发——matcher 为空"""
    for hp in ["session_start", "session_end", "on_error", "user_prompt_submit"]:
        matcher = HOOK_MATCHER_MAP.get(hp, "")
        assert matcher == "", f"{hp} matcher 应为空（全局触发）: {matcher}"


def test_translate_hooks_generates_correct_matcher():
    """translate_hooks 输出带有精细化 matcher"""
    adapter = ClaudeCodeAdapter()

    hooks_config = {
        "post_tool_use": [{"type": "script", "command": "guardrails-check.sh"}],
        "pre_tool_use": [{"type": "script", "command": "input-guard.sh"}],
        "session_start": [{"type": "script", "command": "init.sh"}],
    }

    result = adapter.translate_hooks(hooks_config, harness_root="/tmp")

    # PostToolUse 应有 Write|Edit|NotebookEdit matcher
    post_entries = result.get("PostToolUse", [])
    assert len(post_entries) >= 1, f"PostToolUse 应有 entry"
    post_matcher = post_entries[0].get("matcher", "")
    assert "Write" in post_matcher, f"PostToolUse matcher 应包含 Write: {post_matcher}"
    assert "Read" not in post_matcher, f"PostToolUse matcher 不应包含 Read: {post_matcher}"

    # PreToolUse 应有 Bash matcher
    pre_entries = result.get("PreToolUse", [])
    assert len(pre_entries) >= 1, f"PreToolUse 应有 entry"
    pre_matcher = pre_entries[0].get("matcher", "")
    assert "Bash" in pre_matcher, f"PreToolUse matcher 应包含 Bash: {pre_matcher}"

    # SessionStart 应有空 matcher
    session_entries = result.get("SessionStart", [])
    assert len(session_entries) >= 1, f"SessionStart 应有 entry"
    session_matcher = session_entries[0].get("matcher", "")
    assert session_matcher == "", f"SessionStart matcher 应为空: {session_matcher}"


def test_same_native_event_different_matchers_not_overwritten():
    """验收标准5：同一原生事件的不同 matcher 不互相覆盖

    pre_execute 和 pre_tool_use 都映射到 PreToolUse，
    但 pre_execute matcher="Bash", pre_tool_use matcher="Bash"
    所以它们应该合并为同一个 matcher entry。
    """
    adapter = ClaudeCodeAdapter()

    hooks_config = {
        "pre_tool_use": [{"type": "script", "command": "input-guard.sh"}],
        "pre_execute": [{"type": "script", "command": "pre-exec-check.sh"}],
    }

    result = adapter.translate_hooks(hooks_config, harness_root="/tmp")

    # PreToolUse 应有一个 matcher="Bash" 的 entry（合并）
    pre_entries = result.get("PreToolUse", [])
    assert len(pre_entries) >= 1, f"PreToolUse 应有 entry"

    # 所有 PreToolUse entry 的 matcher 应为 Bash
    bash_matcher_entries = [e for e in pre_entries if "Bash" in e.get("matcher", "")]
    assert len(bash_matcher_entries) >= 1, f"PreToolUse 应有 Bash matcher entry"

    # hooks 数量应为 2（两个 hook 合并到同一个 matcher 下）
    bash_hooks = bash_matcher_entries[0].get("hooks", [])
    assert len(bash_hooks) >= 2, \
        f"Bash matcher 下应有 2 个 hook（合并），实际 {len(bash_hooks)}"


def test_post_tool_use_read_grep_not_in_output():
    """验收：完整 translate_hooks 输出中，PostToolUse matcher 不含只读操作"""
    adapter = ClaudeCodeAdapter()

    hooks_config = {
        "post_tool_use": [{"type": "script", "command": "compliance-scan.sh"}],
    }

    result = adapter.translate_hooks(hooks_config, harness_root="/tmp")

    # 检查所有 PostToolUse entry 的 matcher
    for entry in result.get("PostToolUse", []):
        matcher = entry.get("matcher", "")
        for readonly_tool in ["Read", "Grep", "Glob", "Agent", "WebSearch"]:
            assert readonly_tool not in matcher, \
                f"PostToolUse matcher 不应包含只读工具 {readonly_tool}: {matcher}"


# ─── 运行所有测试 ────────────────────────────────────────

def run_all_tests():
    tests = [
        test_matcher_map_post_tool_use_write_only,
        test_matcher_map_pre_tool_use_bash,
        test_matcher_map_session_global,
        test_translate_hooks_generates_correct_matcher,
        test_same_native_event_different_matchers_not_overwritten,
        test_post_tool_use_read_grep_not_in_output,
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

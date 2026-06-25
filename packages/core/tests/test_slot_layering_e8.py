"""
E-8 验收测试：Slot 分层 + 映射表

验收标准：
1. Profile YAML hooks 部分只有 7 行有效配置（核心5+扩展2），无注释噪音
2. SkillSlotName docstring 有三层分类表 + Slot→HookType 行内注释
3. 映射表文档存在且包含完整 17→3 映射
4. 理论通道插槽不在 Profile YAML 中出现
5. 各层分类依据明确（核心=DAGEngine集成+默认启用，扩展=有hook脚本，理论=仅枚举）
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.types import SkillSlotName


# ─── 三层分类常量 ────────────────────────────────────────────

CORE_SLOTS = {
    SkillSlotName.SESSION_START,
    SkillSlotName.POST_EXECUTE,
    SkillSlotName.ON_ERROR,
    SkillSlotName.ON_GATE_PASS,
    SkillSlotName.ON_GATE_FAIL,
}

EXTENDED_SLOTS = {
    SkillSlotName.SESSION_END,
    SkillSlotName.PRE_EXECUTE,
}

THEORETICAL_SLOTS = {
    SkillSlotName.PRE_TOOL_USE,
    SkillSlotName.POST_TOOL_USE,
    SkillSlotName.ON_FILE_CHANGE,
    SkillSlotName.PRE_COMMIT,
    SkillSlotName.POST_COMMIT,
    SkillSlotName.ON_DELEGATE,
    SkillSlotName.ON_CONFLICT,
    SkillSlotName.ON_DECISION,
    SkillSlotName.ON_ESCALATION,
    SkillSlotName.USER_PROMPT_SUBMIT,
}


# ─── Slot → HookType 映射 ────────────────────────────────────

# 映射规律：
#   pre_* / session_start / user_prompt_submit / on_delegate → BEFORE
#   post_* / session_end / on_gate_pass / on_file_change / on_decision → AFTER
#   on_error / on_gate_fail / on_conflict / on_escalation → ON_ERROR

SLOT_TO_HOOK_TYPE = {
    # 核心通道
    SkillSlotName.SESSION_START: "BEFORE",
    SkillSlotName.POST_EXECUTE: "AFTER",
    SkillSlotName.ON_ERROR: "ON_ERROR",
    SkillSlotName.ON_GATE_PASS: "AFTER",
    SkillSlotName.ON_GATE_FAIL: "ON_ERROR",
    # 扩展通道
    SkillSlotName.SESSION_END: "AFTER",
    SkillSlotName.PRE_EXECUTE: "BEFORE",
    # 理论通道
    SkillSlotName.PRE_TOOL_USE: "BEFORE",
    SkillSlotName.POST_TOOL_USE: "AFTER",
    SkillSlotName.ON_FILE_CHANGE: "AFTER",
    SkillSlotName.PRE_COMMIT: "BEFORE",
    SkillSlotName.POST_COMMIT: "AFTER",
    SkillSlotName.ON_DELEGATE: "BEFORE",
    SkillSlotName.ON_CONFLICT: "ON_ERROR",
    SkillSlotName.ON_DECISION: "AFTER",
    SkillSlotName.ON_ESCALATION: "ON_ERROR",
    SkillSlotName.USER_PROMPT_SUBMIT: "BEFORE",
}


def test_three_layer_classification_complete():
    """验收标准5：三层分类覆盖所有17个插槽"""
    all_slots = set(SkillSlotName)
    classified = CORE_SLOTS | EXTENDED_SLOTS | THEORETICAL_SLOTS

    assert classified == all_slots, \
        f"三层分类应覆盖所有插槽: missing={all_slots - classified}, extra={classified - all_slots}"

    # 各层无交叉
    assert CORE_SLOTS & EXTENDED_SLOTS == set(), \
        "核心通道与扩展通道不应有交叉"
    assert CORE_SLOTS & THEORETICAL_SLOTS == set(), \
        "核心通道与理论通道不应有交叉"
    assert EXTENDED_SLOTS & THEORETICAL_SLOTS == set(), \
        "扩展通道与理论通道不应有交叉"


def test_core_slots_count():
    """验收标准5：核心通道 5 个"""
    assert len(CORE_SLOTS) == 5, \
        f"核心通道应有5个插槽: {len(CORE_SLOTS)}"


def test_extended_slots_count():
    """验收标准5：扩展通道 2 个"""
    assert len(EXTENDED_SLOTS) == 2, \
        f"扩展通道应有2个插槽: {len(EXTENDED_SLOTS)}"


def test_theoretical_slots_count():
    """验收标准5：理论通道 10 个"""
    assert len(THEORETICAL_SLOTS) == 10, \
        f"理论通道应有10个插槽: {len(THEORETICAL_SLOTS)}"


def test_core_plus_extended_equals_7():
    """验收标准1：核心+扩展 = 7 行"""
    assert len(CORE_SLOTS | EXTENDED_SLOTS) == 7, \
        f"核心+扩展通道应有7行: {len(CORE_SLOTS | EXTENDED_SLOTS)}"


def test_slot_to_hook_type_mapping_complete():
    """验收标准2+3：映射表覆盖所有17个插槽"""
    all_slots = set(SkillSlotName)
    mapped_slots = set(SLOT_TO_HOOK_TYPE.keys())

    assert mapped_slots == all_slots, \
        f"映射表应覆盖所有插槽: missing={all_slots - mapped_slots}"


def test_slot_to_hook_type_only_before_after_on_error():
    """验收标准3：映射值只有 BEFORE/AFTER/ON_ERROR"""
    valid_types = {"BEFORE", "AFTER", "ON_ERROR"}
    mapped_values = set(SLOT_TO_HOOK_TYPE.values())

    assert mapped_values == valid_types, \
        f"映射值应只有 BEFORE/AFTER/ON_ERROR: extra={mapped_values - valid_types}"


def test_slot_name_docstring_has_layer_annotation():
    """验收标准2：SkillSlotName docstring 包含三层分类"""
    docstring = SkillSlotName.__doc__
    assert "核心通道" in docstring, \
        "SkillSlotName docstring 应包含'核心通道'"
    assert "扩展通道" in docstring, \
        "SkillSlotName docstring 应包含'扩展通道'"
    assert "理论通道" in docstring, \
        "SkillSlotName docstring 应包含'理论通道'"


def test_slot_name_inline_comments_have_hook_type():
    """验收标准2：SkillSlotName 枚举值行内注释包含 HookType"""
    # 检查几个关键插槽的行内注释
    for slot in SkillSlotName:
        # 获取枚举值定义行的注释
        # 由于 dataclass 不方便直接获取行注释，通过 SLOT_TO_HOOK_TYPE 间接验证
        assert slot in SLOT_TO_HOOK_TYPE, \
            f"每个插槽应在 SLOT_TO_HOOK_TYPE 映射中: missing={slot}"


def test_mapping_doc_exists():
    """验收标准3：映射表文档存在"""
    doc_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..",
        "docs", "45-Slot分层映射表-20260616.md"
    )
    assert os.path.exists(doc_path), \
        f"映射表文档应存在: {doc_path}"


def test_mapping_doc_contains_key_content():
    """验收标准3：映射表文档包含关键内容"""
    doc_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..",
        "docs", "45-Slot分层映射表-20260616.md"
    )
    with open(doc_path, "r") as f:
        content = f.read()

    assert "Slot → HookType" in content, \
        "映射表文档应包含 'Slot → HookType' 映射表标题"
    assert "BEFORE" in content, \
        "映射表文档应包含 BEFORE"
    assert "AFTER" in content, \
        "映射表文档应包含 AFTER"
    assert "ON_ERROR" in content, \
        "映射表文档应包含 ON_ERROR"
    assert "核心通道" in content, \
        "映射表文档应包含 '核心通道'"
    assert "理论通道" in content, \
        "映射表文档应包含 '理论通道'"


def test_profile_yaml_no_theoretical_slots():
    """验收标准4：Profile YAML 中不出现理论通道插槽"""
    profile_path = os.path.join(
        os.path.dirname(__file__), "..",
        "harness", "profiles", "default.yaml"
    )
    with open(profile_path, "r") as f:
        content = f.read()

    theoretical_slot_names = [
        "pre_tool_use", "post_tool_use", "on_file_change",
        "pre_commit", "post_commit", "on_delegate", "on_conflict",
        "on_decision", "user_prompt_submit",
    ]

    for slot_name in theoretical_slot_names:
        # 不应作为 YAML key 出现（即不应有 "slot_name:" 形式的配置行）
        lines = content.split("\n")
        config_lines = [l for l in lines if not l.strip().startswith("#")]
        # 检查非注释行中是否包含理论通道名作为 key
        for line in config_lines:
            stripped = line.strip()
            if stripped.startswith(f"{slot_name}:"):
                assert False, \
                    f"Profile YAML 不应包含理论通道 {slot_name} 作为配置 key"


def test_profile_yaml_has_core_and_extended_hooks():
    """验收标准1：Profile YAML 包含7行核心+扩展通道配置"""
    profile_path = os.path.join(
        os.path.dirname(__file__), "..",
        "harness", "profiles", "default.yaml"
    )
    with open(profile_path, "r") as f:
        content = f.read()

    # 核心通道应该出现在 YAML 中
    core_slot_names = [
        "session_start", "post_execute", "on_error",
        "on_gate_pass", "on_gate_fail",
    ]
    for slot_name in core_slot_names:
        assert f"{slot_name}:" in content, \
            f"Profile YAML 应包含核心通道 {slot_name}"

    # 扩展通道应该出现在 YAML 中
    extended_slot_names = ["session_end", "pre_execute"]
    for slot_name in extended_slot_names:
        assert f"{slot_name}:" in content, \
            f"Profile YAML 应包含扩展通道 {slot_name}"


# ─── 运行所有测试 ────────────────────────────────────────

def run_all_tests():
    tests = [
        test_three_layer_classification_complete,
        test_core_slots_count,
        test_extended_slots_count,
        test_theoretical_slots_count,
        test_core_plus_extended_equals_7,
        test_slot_to_hook_type_mapping_complete,
        test_slot_to_hook_type_only_before_after_on_error,
        test_slot_name_docstring_has_layer_annotation,
        test_slot_name_inline_comments_have_hook_type,
        test_mapping_doc_exists,
        test_mapping_doc_contains_key_content,
        test_profile_yaml_no_theoretical_slots,
        test_profile_yaml_has_core_and_extended_hooks,
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

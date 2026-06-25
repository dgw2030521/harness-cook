"""Superpowers → SkillRegistry 桥接示例

展示如何将 Claude Code superpowers 插件的 skills
自动发现并注册到 harness-cook 的 SkillRegistry。

核心流程：
1. find_superpowers_dir() → 自动定位 superpowers 插件目录
2. scan_superpowers_dir() → 扫描 skill.md 文件
3. parse_skill_frontmatter() → 解析 YAML frontmatter
4. map_superpowers_to_skill_definition() → 映射到 SkillDefinition
5. register_superpowers_skills() → 注册到 SkillRegistry

运行方式：
    cd harness-cook/packages/core
    PYTHONPATH=. python3 ../../examples/superpowers-bridge/demo_superpowers_bridge.py
"""

import sys
import os

# 添加 core 包到 PYTHONPATH
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
core_path = os.path.join(project_root, "packages", "core")
if core_path not in sys.path:
    sys.path.insert(0, core_path)

from harness.superpowers_bridge import (
    find_superpowers_dir,
    scan_superpowers_dir,
    parse_skill_frontmatter,
    map_superpowers_to_skill_definition,
    register_superpowers_skills,
)
from harness.skill_registry import SkillRegistry, SkillSlotName


# ═══════════════════════════════════════════════════════════
#  Step 1: 自动定位 superpowers 插件目录
# ═══════════════════════════════════════════════════════════

def demo_find_dir():
    """演示自动定位 superpowers 目录"""
    print("=" * 60)
    print("  Step 1: 自动定位 Superpowers 插件目录")
    print("=" * 60)

    superpowers_dir = find_superpowers_dir()

    if superpowers_dir:
        print(f"\n✅ 找到 superpowers 目录:")
        print(f"   {superpowers_dir}")
        return superpowers_dir
    else:
        print("\n⚠️  未找到 superpowers 插件目录")
        print("   可能原因:")
        print("   - 未安装 superpowers 插件")
        print("   - 插件目录不在 ~/.claude/plugins/cache/")
        print("\n   继续使用模拟数据演示后续步骤...")
        return None


# ═══════════════════════════════════════════════════════════
#  Step 2: 扫描 skill.md 文件
# ═══════════════════════════════════════════════════════════

def demo_scan_dir(superpowers_dir):
    """演示扫描 skill.md 文件"""
    print("\n" + "=" * 60)
    print("  Step 2: 扫描 skill.md 文件")
    print("=" * 60)

    if superpowers_dir:
        skills = scan_superpowers_dir(superpowers_dir)
        print(f"\n✅ 发现 {len(skills)} 个 superpowers skills:")
        for skill_name, skill_md_path, frontmatter in skills:
            desc = frontmatter.get("description", "")
            print(f"   - {skill_name}: {desc}")
        return skills
    else:
        # 模拟数据
        mock_skills = [
            ("brainstorming", "", {"name": "brainstorming", "description": "Use before EnterPlanMode — brainstorms then plans"}),
            ("debugging", "", {"name": "debugging", "description": "Use when debugging — systematic root cause analysis"}),
            ("verification", "", {"name": "verification", "description": "Use after code changes — verify correctness"}),
            ("using-superpowers", "", {"name": "using-superpowers", "description": "Use when starting any conversation"}),
        ]
        print(f"\n📝 模拟 {len(mock_skills)} 个 superpowers skills:")
        for skill_name, _, frontmatter in mock_skills:
            desc = frontmatter.get("description", "")
            print(f"   - {skill_name}: {desc}")
        return mock_skills


# ═══════════════════════════════════════════════════════════
#  Step 3: 解析 YAML frontmatter
# ═══════════════════════════════════════════════════════════

def demo_parse_frontmatter(superpowers_dir):
    """演示解析 skill.md frontmatter"""
    print("\n" + "=" * 60)
    print("  Step 3: 解析 YAML frontmatter")
    print("=" * 60)

    if superpowers_dir:
        import glob
        skill_files = glob.glob(os.path.join(superpowers_dir, "**/skill.md"), recursive=True)
        if skill_files:
            # 解析第一个 skill.md 作为示例
            for path in skill_files[:3]:
                fm = parse_skill_frontmatter(path)
                if fm:
                    print(f"\n   📄 {os.path.basename(os.path.dirname(path))}/skill.md")
                    print(f"      name: {fm.get('name')}")
                    print(f"      description: {fm.get('description')}")
        return

    # 模拟演示
    print("\n📝 frontmatter 格式示例:")
    print("""
    ---
    name: brainstorming
    description: Use before EnterPlanMode — brainstorms then plans
    ---
    # Brainstorming Skill
    ...
    """)


# ═══════════════════════════════════════════════════════════
#  Step 4: 映射到 SkillDefinition + 插槽语义映射
# ═══════════════════════════════════════════════════════════

def demo_slot_mapping():
    """演示插槽语义映射"""
    print("\n" + "=" * 60)
    print("  Step 4: 插槽语义映射")
    print("=" * 60)

    # 展示已知的语义映射
    slot_map = {
        "brainstorming": SkillSlotName.PRE_EXECUTE,
        "debugging": SkillSlotName.ON_ERROR,
        "verification": SkillSlotName.POST_EXECUTE,
        "using-superpowers": SkillSlotName.SESSION_START,
        "tdd": SkillSlotName.PRE_EXECUTE,
        "frontend-design": SkillSlotName.PRE_EXECUTE,
        "architecture": SkillSlotName.PRE_EXECUTE,
        "patterns": SkillSlotName.PRE_EXECUTE,
        "code-reviewer": SkillSlotName.POST_EXECUTE,
        "mcp-builder": SkillSlotName.PRE_EXECUTE,
    }

    print("\n📊 Superpowers skill → Skill 插槽映射:")
    print(f"   {'Skill 名称':<25} {'→ 插槽':<20} {'语义依据'}")
    print(f"   {'─' * 25} {'─' * 20} {'─' * 15}")

    mappings = [
        ("brainstorming", SkillSlotName.PRE_EXECUTE, "执行前规划"),
        ("debugging", SkillSlotName.ON_ERROR, "异常时调试"),
        ("verification", SkillSlotName.POST_EXECUTE, "执行后验证"),
        ("using-superpowers", SkillSlotName.SESSION_START, "会话开始初始化"),
    ]

    for name, slot, reason in mappings:
        print(f"   {name:<25} → {slot.value:<20} {reason}")

    print(f"\n   未映射的 skills → 默认插槽: {SkillSlotName.PRE_EXECUTE.value}")


# ═══════════════════════════════════════════════════════════
#  Step 5: 注册到 SkillRegistry（完整流程）
# ═══════════════════════════════════════════════════════════

def demo_registration(superpowers_dir):
    """演示完整注册流程"""
    print("\n" + "=" * 60)
    print("  Step 5: 注册到 SkillRegistry")
    print("=" * 60)

    registry = SkillRegistry()

    # 先注册内置 skills（展示共存）
    from harness.skill_registry import SkillDefinition

    builtin_skill = SkillDefinition(
        id="auto-audit",
        name="Auto Audit",
        description="自动审计",
        slot=SkillSlotName.POST_EXECUTE,
        entry_point="packages/hooks/hook-task-audit.py",
        tags=["audit", "builtin"],
    )
    registry.register(builtin_skill)
    print(f"\n✅ 内置 skill 已注册: {builtin_skill.id}")

    # 注册 superpowers skills
    registered = register_superpowers_skills(registry, superpowers_dir)

    if registered:
        print(f"\n✅ 已注册 {len(registered)} 个 superpowers skills")
    else:
        print("\n⚠️  无 superpowers skills 可注册（插件目录不存在或为空）")

    # 展示注册结果
    all_skills = registry.list_all()
    print(f"\n📋 SkillRegistry 当前注册的所有 skills:")
    for record in all_skills:
        skill = record.definition
        source_icon = "🅂" if skill.id.startswith("superpowers:") else "🅑"
        print(f"   {source_icon} {skill.id}")
        print(f"      名称: {skill.name}")
        print(f"      插槽: {skill.slot.value}")
        print(f"      标签: {skill.tags}")

    # 展示 namespace 防碰撞
    superpowers_skills = [r for r in all_skills if r.definition.id.startswith("superpowers:")]
    builtin_skills = [r for r in all_skills if not r.definition.id.startswith("superpowers:")]

    print(f"\n🛡️  Namespace 防碰撞:")
    print(f"   内置 skills: {len(builtin_skills)} 个（无前缀）")
    print(f"   Superpowers skills: {len(superpowers_skills)} 个（superpowers: 前缀）")
    print(f"   即使 skill 名冲突也不会覆盖——namespace 隔离")

    return registry


# ═══════════════════════════════════════════════════════════
#  MCP 工具集成
# ═══════════════════════════════════════════════════════════

def demo_mcp_integration():
    """展示 MCP skill_list 工具中的 source 字段"""
    print("\n" + "=" * 60)
    print("  MCP 工具集成")
    print("=" * 60)

    print("""
MCP Server 的 harness_skill_list 工具输出示例:

{
  "skills": [
    {
      "id": "auto-audit",
      "name": "Auto Audit",
      "slot": "post_execute",
      "source": "builtin"         ← 内置 skill
    },
    {
      "id": "superpowers:brainstorming",
      "name": "brainstorming",
      "slot": "pre_execute",
      "source": "superpowers"     ← 从 superpowers 桥接
    },
    {
      "id": "superpowers:debugging",
      "name": "debugging",
      "slot": "on_error",
      "source": "superpowers"     ← 从 superpowers 桥接
    }
  ]
}

调用方式:
    harness_skill_list(slot="pre_execute")    ← 只看执行前插槽
    harness_skill_list(tag="superpowers")      ← 只看 superpowers skills
""")


if __name__ == "__main__":
    # 完整流程演示
    superpowers_dir = demo_find_dir()
    demo_scan_dir(superpowers_dir)
    demo_parse_frontmatter(superpowers_dir)
    demo_slot_mapping()
    demo_registration(superpowers_dir)
    demo_mcp_integration()

    print(f"\n{'=' * 60}")
    print("  总结")
    print("=" * 60)
    print("""
Superpowers Bridge 将 Claude Code 的 skills 生态自动桥接到
harness-cook 的 SkillRegistry，实现：

1. 🔍 自动发现 — 无需手动配置，扫描插件目录即可
2. 🔄 语义映射 — 按功能语义分配到合适的插槽点
3. 🛡️ Namespace 隲离 — superpowers: 前缀防止 ID 冲突
4. 🤝 共存兼容 — 与内置 skills 和平共处，不覆盖不冲突
5. 📡 MCP 集成 — source 字段区分 skill 来源

适用场景：
- 团队同时使用 Claude Code superpowers + harness-cook
- 想将 superpowers 的 TDD/debugging/brainstorming 等能力
  系统性地接入 harness 的 Skill 插槽生命周期
""")
    print("=" * 60)

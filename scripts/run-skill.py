#!/usr/bin/env python3
"""
harness skill CLI — 命令行执行 Skill

用法:
  python3 scripts/run-skill.py <skill_id> [context_json]

示例:
  python3 scripts/run-skill.py auto-audit
  python3 scripts/run-skill.py auto-audit '{"session_id": "abc123", "node_id": "node-1"}'
"""

import json
import sys
import os

# 添加 core 包到 PYTHONPATH
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
core_path = os.path.join(project_root, "packages", "core")
if core_path not in sys.path:
    sys.path.insert(0, core_path)


def main():
    if len(sys.argv) < 2:
        print("用法: python3 scripts/run-skill.py <skill_id> [context_json]")
        sys.exit(1)

    skill_id = sys.argv[1]
    context = {}

    if len(sys.argv) > 2:
        try:
            context = json.loads(sys.argv[2])
        except json.JSONDecodeError as e:
            print(f"错误: 无效的 JSON 上下文: {e}")
            sys.exit(1)

    try:
        from harness.skill_registry import get_skill_registry, register_builtin_skills

        # 获取注册表并注册内置 skills
        registry = get_skill_registry()
        register_builtin_skills(registry)

        # 执行 skill
        result = registry.execute_skill(skill_id, context)

        if result is None:
            print(f"错误: Skill '{skill_id}' 未找到或未激活")
            sys.exit(1)

        # 输出结果
        if result.status.value == "completed":
            print(f"✅ Skill '{skill_id}' 执行成功")
        else:
            print(f"❌ Skill '{skill_id}' 执行失败: {result.error}")
            sys.exit(1)

    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

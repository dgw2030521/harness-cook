# Superpowers 桥接 Demo

> 跑起来看看如何将 Claude Code superpowers 插件的 skills 自动发现并注册到 harness-cook SkillRegistry。

**完整可运行脚本**见项目 `examples/superpowers-bridge/` 目录（`demo_superpowers_bridge.py`）。本页是文档介绍——代码片段 + 预期输出 + 配置说明。

## 运行方式

```bash
cd harness-cook/packages/core
PYTHONPATH=. python3 ../../examples/superpowers-bridge/demo_superpowers_bridge.py
```

---

## Demo 概述

Superpowers Bridge 将 Claude Code 的 skills 生态自动桥接到 harness-cook 的 SkillRegistry：

1. 🔍 **自动发现** — 无需手动配置，扫描插件目录即可
2. 🔄 **语义映射** — 按功能语义分配到合适的插槽点
3. 🛡️ **Namespace 防碰撞** — `superpowers:` 前缀防止 ID 冲突
4. 🤝 **共存兼容** — 与内置 skills 和平共处，不覆盖不冲突
5. 📡 **MCP 集成** — source 字段区分 skill 来源

---

## 核心流程

```python
from harness.superpowers_bridge import (
    find_superpowers_dir,
    scan_superpowers_dir,
    parse_skill_frontmatter,
    map_superpowers_to_skill_definition,
    register_superpowers_skills,
)
from harness.skill_registry import SkillRegistry, SkillSlotName

# 1. 自动定位 superpowers 目录
superpowers_dir = find_superpowers_dir()

# 2. 扫描 skill.md 文件
skills = scan_superpowers_dir(superpowers_dir)

# 3. 注册到 SkillRegistry
registry = SkillRegistry()
registered = register_superpowers_skills(registry, superpowers_dir)

# 4. 查看注册结果
for record in registry.list_all():
    skill = record.definition
    source = "🅂" if skill.id.startswith("superpowers:") else "🅑"
    print(f"   {source} {skill.id} — {skill.name} [{skill.slot.value}]")
```

---

完整映射见 [Superpowers Bridge](/guide/superpowers-bridge#slot-映射)

---

## Namespace 防碰撞

```
内置 skills: auto-audit        （无前缀）
Superpowers:  superpowers:brainstorming （superpowers: 前缀）
→ 即使 skill 名冲突也不会覆盖——namespace 隔离
```

---

## MCP 工具集成

```json
{
  "skills": [
    {
      "id": "auto-audit",
      "name": "Auto Audit",
      "slot": "post_execute",
      "source": "builtin"
    },
    {
      "id": "superpowers:brainstorming",
      "name": "brainstorming",
      "slot": "pre_execute",
      "source": "superpowers"
    }
  ]
}
```

调用方式：
- `harness_skill_list(slot="pre_execute")` ← 只看执行前插槽
- `harness_skill_list(tag="superpowers")` ← 只看 superpowers skills

---

## 完整 Demo 代码

完整 Demo 代码见项目 `examples/superpowers-bridge/demo_superpowers_bridge.py`。

---

## 相关导航

- 📖 架构原理 → [Skill 插槽点](/guide/skill-slots)
- 🎓 使用方法 → [Superpowers 桥接](/tutorial/superpowers-skill-bridge)

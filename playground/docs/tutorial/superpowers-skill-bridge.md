# Superpowers Skill Bridge

本教程展示如何将 Claude Code superpowers 插件的 skills 自动桥接到 harness-cook 的 SkillRegistry，实现双体系融合。

## Step 1: 了解 Superpowers Bridge

Superpowers Bridge 解决的核心问题：

- **问题**：Claude Code superpowers 插件有 TDD、brainstorming、debugging 等优秀 skills，但它们独立于 harness-cook 的 Skill 插槽生命周期运行
- **解决**：自动发现 superpowers skills → 语义映射到 harness 插槽 → namespace 防碰撞注册

## Step 2: 自动发现 Superpowers 插件

```python
from harness.superpowers_bridge import find_superpowers_dir

dir = find_superpowers_dir()
if dir:
    print(f"找到 superpowers 目录: {dir}")
else:
    print("未找到 superpowers 插件 — 优雅降级，不影响内置功能")
```

自动发现逻辑：
1. 搜索 `~/.claude/plugins/cache/claude-plugins-official/superpowers/<version>/skills/`
2. 按版本号排序，取最新版
3. 未找到时返回 None，后续步骤跳过

## Step 3: 扫描 skill.md 文件

```python
from harness.superpowers_bridge import scan_superpowers_dir

skills = scan_superpowers_dir(dir)
for name, desc in skills:
    print(f"  - {name}: {desc}")
```

Superpowers 的每个 skill 是一个目录，包含 `skill.md` 文件：

```
superpowers/v1.2.3/skills/
├── brainstorming/skill.md
├── debugging/skill.md
├── tdd/skill.md
├── verification/skill.md
├── using-superpowers/skill.md
└── ...
```

## Step 4: 解析 YAML frontmatter

```python
from harness.superpowers_bridge import parse_skill_frontmatter

fm = parse_skill_frontmatter("path/to/brainstorming/skill.md")
print(fm["name"])        # → "brainstorming"
print(fm["description"]) # → "Use before EnterPlanMode — brainstorms then plans"
```

skill.md 的 YAML frontmatter 格式：

```yaml
---
name: brainstorming
description: Use before EnterPlanMode — brainstorms then plans
---
# Brainstorming Skill
...
```

## Step 5: 语义映射到 Skill 插槽

Bridge 根据 skill 的功能语义自动映射到 harness 的 17 个插槽。完整映射见 [Superpowers Bridge 原理](/guide/superpowers-bridge#slot-映射)。

## Step 6: Namespace 防碰撞注册

```python
from harness.superpowers_bridge import register_superpowers_skills
from harness.skill_registry import SkillRegistry

registry = SkillRegistry()
count = register_superpowers_skills(registry)

# 所有 superpowers skills 使用 "superpowers:" 前缀
for skill in registry.list_skills():
    if skill.id.startswith("superpowers:"):
        print(f"🅂 {skill.id} → {skill.slot.value}")
    else:
        print(f"🅑 {skill.id} → {skill.slot.value}")
```

namespace 防碰撞机制：
- 内置 skill: `auto-audit`（无前缀）
- Superpowers skill: `superpowers:brainstorming`（有前缀）
- 即使 superpowers 中也有名为 "auto-audit" 的 skill → 注册为 `superpowers:auto-audit`，不覆盖内置

## Step 7: MCP 工具集成

`harness_skill_list` 工具的输出包含 `source` 字段：

```json
{
  "skills": [
    {"id": "auto-audit", "source": "builtin", "slot": "post_execute"},
    {"id": "superpowers:brainstorming", "source": "superpowers", "slot": "pre_execute"},
    {"id": "superpowers:debugging", "source": "superpowers", "slot": "on_error"}
  ]
}
```

过滤查询：

```json
// 只看 superpowers skills
{"method": "harness_skill_list", "params": {"tag": "superpowers"}}

// 只看特定插槽
{"method": "harness_skill_list", "params": {"slot": "pre_execute"}}
```

## Step 8: Profile 配置集成

在 Profile hooks 中引用 superpowers skills：

```yaml
# .harness/profiles/default.yaml
hooks:
  session_start:
    - type: skill
      skill_id: superpowers:using-superpowers
  pre_execute:
    - type: skill
      skill_id: superpowers:brainstorming
  on_error:
    - type: skill
      skill_id: superpowers:debugging
  post_execute:
    - type: skill
      skill_id: superpowers:verification
```

## Step 9: 优雅降级

如果 superpowers 插件未安装：

- `find_superpowers_dir()` 返回 None
- `register_superpowers_skills()` 注册 0 个 skill
- 不影响任何内置 skill 功能
- 不产生任何错误或异常

```python
# 安全调用——无插件也不会崩溃
registry = SkillRegistry()
count = register_superpowers_skills(registry)
# count 可能是 0（无插件）或 N（有插件）
# 内置 skills 始终可用
```

## 运行完整示例

```bash
cd harness-cook/packages/core
PYTHONPATH=. python3 ../../examples/superpowers-bridge/demo_superpowers_bridge.py
```

下一步 → [门禁审批](./gate-approval)

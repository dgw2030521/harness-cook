# Superpowers Bridge 示例

> 将 Claude Code superpowers 插件的 skills 自动桥接到 harness-cook SkillRegistry

**文档介绍**见 VitePress Demo 页面 [Superpowers 桥接](../../playground/docs/demo/superpowers-bridge.md)——代码片段 + 预期输出 + 配置说明。本目录是可运行的脚本。

## 功能

Superpowers Bridge 实现 **双体系融合**——将 Claude Code superpowers 插件中的 skills（TDD、brainstorming、debugging 等）自动发现并注册到 harness-cook 的 SkillRegistry：

| 能力 | 说明 |
|------|------|
| 自动发现 | 扫描 `~/.claude/plugins/cache/` 定位 superpowers 目录 |
| YAML 解析 | 从 skill.md frontmatter 提取 name/description |
| 语义映射 | 按功能语义分配插槽（brainstorming→PRE_EXECUTE 等） |
| Namespace 雲隔离 | `superpowers:` 前缀防止 ID 冲突 |
| MCP 集成 | `source` 字段区分 skill 来源 |

## 使用方法

### 1. 直接运行示例

```bash
cd harness-cook/packages/core
PYTHONPATH=. python3 ../../examples/superpowers-bridge/demo_superpowers_bridge.py
```

### 2. 在代码中使用

```python
from harness.superpowers_bridge import register_superpowers_skills
from harness.skill_registry import SkillRegistry

# 初始化 Registry
registry = SkillRegistry()

# 自动发现 + 注册（无需手动配置）
count = register_superpowers_skills(registry)

# 查看注册结果
for skill in registry.list_skills():
    print(f"{skill.id} → {skill.slot.value}")
```

### 3. MCP 工具调用

```json
{
  "method": "harness_skill_list",
  "params": {
    "slot": "pre_execute"
  }
}
```

返回结果包含 `source` 字段区分来源：

```json
{
  "skills": [
    {"id": "auto-audit", "source": "builtin", "slot": "post_execute"},
    {"id": "superpowers:brainstorming", "source": "superpowers", "slot": "pre_execute"},
    {"id": "superpowers:debugging", "source": "superpowers", "slot": "on_error"}
  ]
}
```

### 4. 分步调用（调试用）

```python
from harness.superpowers_bridge import (
    find_superpowers_dir,
    scan_superpowers_dir,
    parse_skill_frontmatter,
    map_superpowers_to_skill_definition,
)

# Step 1: 定位目录
dir = find_superpowers_dir()

# Step 2: 扫描 skill.md 文件
skills = scan_superpowers_dir(dir)

# Step 3: 解析 frontmatter
for name, desc in skills:
    # 找到对应的 skill.md 路径，解析 YAML
    fm = parse_skill_frontmatter(skill_md_path)

# Step 4: 映射到 SkillDefinition
skill_def = map_superpowers_to_skill_definition(name, desc)
print(f"映射结果: {skill_def.id}")
print(f"  插槽: {skill_def.slot.value}")
print(f"  标签: {skill_def.tags}")
```

## 插槽语义映射

Bridge 根据 superpowers skill 的功能语义自动映射到 harness 插槽：

| Superpowers Skill | Harness 插槽 | 语义依据 |
|-------------------|-------------|----------|
| brainstorming | PRE_EXECUTE | 执行前规划 |
| debugging | ON_ERROR | 异常时调试 |
| verification | POST_EXECUTE | 执行后验证 |
| using-superpowers | SESSION_START | 会话初始化 |
| tdd | PRE_EXECUTE | 执行前测试驱动 |
| architecture | PRE_EXECUTE | 执行前架构设计 |
| code-reviewer | POST_EXECUTE | 执行后代码审查 |
| 其他未映射 | PRE_EXECUTE（默认） | 执行前辅助 |

## Namespace 雲隔离

所有 superpowers skills 使用 `superpowers:` 前缀：

- 内置 skill: `auto-audit`
- Superpowers skill: `superpowers:brainstorming`

即使名称冲突也不会覆盖——两个体系和平共存。

## 前置要求

- Claude Code 已安装 superpowers 插件（自动发现依赖此条件）
- 如未安装 superpowers，bridge 优雅降级——不注册任何 skill，不影响内置功能

## 组合使用

可与 Profile 配置组合，在 hooks 中引用 superpowers skills：

```yaml
# .harness/profiles/default.yaml
hooks:
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

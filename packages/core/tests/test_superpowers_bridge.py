"""
Superpowers Bridge 测试

覆盖:
  - YAML frontmatter 解析
  - superpowers 目录扫描
  - skill → SkillDefinition 映射（命名空间、slot、tags）
  - SkillRegistry 注册集成
  - MCP skill_list 暴露融合后的 skills
"""

import pytest
import os
import tempfile
from pathlib import Path

from harness.types import SkillDefinition, SkillSlotName
from harness.skill_registry import SkillRegistry, reset_skill_registry
from harness.superpowers_bridge import (
    parse_skill_frontmatter,
    scan_superpowers_dir,
    map_superpowers_to_skill_definition,
    register_superpowers_skills,
    find_superpowers_dir,
    _SLOT_MAP,
    _TAG_MAP,
)


# ═══════════════════════════════════════════════════════════
#  YAML Frontmatter 解析
# ═══════════════════════════════════════════════════════════

class TestFrontmatterParsing:
    def test_parse_simple_frontmatter(self, tmp_path):
        """解析简单的 YAML frontmatter"""
        skill_md = tmp_path / "brainstorming" / "skill.md"
        skill_md.parent.mkdir()
        skill_md.write_text(
            "---\n"
            "name: brainstorming\n"
            "description: Use this before any creative work\n"
            "---\n\n"
            "# Brainstorming Ideas\n"
        )
        result = parse_skill_frontmatter(str(skill_md))
        assert result is not None
        assert result["name"] == "brainstorming"
        assert "creative work" in result["description"]

    def test_parse_quoted_description(self, tmp_path):
        """解析引号包裹的 description"""
        skill_md = tmp_path / "tdd" / "skill.md"
        skill_md.parent.mkdir()
        skill_md.write_text(
            "---\n"
            "name: tdd\n"
            "description: \"Test-driven development with red-green-refactor\"\n"
            "---\n\n# TDD\n"
        )
        result = parse_skill_frontmatter(str(skill_md))
        assert result["name"] == "tdd"
        assert "red-green-refactor" in result["description"]

    def test_parse_no_frontmatter(self, tmp_path):
        """无 frontmatter 的文件应返回 None"""
        skill_md = tmp_path / "plain.md"
        skill_md.write_text("# Just a markdown file\nNo frontmatter here.\n")
        result = parse_skill_frontmatter(str(skill_md))
        assert result is None

    def test_parse_missing_name(self, tmp_path):
        """缺少 name 字段的 frontmatter 应返回 None"""
        skill_md = tmp_path / "bad" / "skill.md"
        skill_md.parent.mkdir()
        skill_md.write_text(
            "---\n"
            "description: Some description without a name\n"
            "---\n\n# No Name\n"
        )
        result = parse_skill_frontmatter(str(skill_md))
        assert result is None

    def test_parse_file_not_found(self):
        """不存在的文件应返回 None"""
        result = parse_skill_frontmatter("/nonexistent/path/skill.md")
        assert result is None


# ═══════════════════════════════════════════════════════════
#  目录扫描
# ═══════════════════════════════════════════════════════════

class TestDirectoryScanning:
    def _make_mock_superpowers_dir(self, tmp_path):
        """创建模拟的 superpowers skills 目录"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        for name, desc in [
            ("brainstorming", "Use this before any creative work"),
            ("systematic-debugging", "Use when encountering bugs"),
            ("verification-before-completion", "Verify before finishing"),
        ]:
            skill_dir = skills_dir / name
            skill_dir.mkdir()
            skill_md = skill_dir / "skill.md"
            skill_md.write_text(
                f"---\nname: {name}\ndescription: '{desc}'\n---\n\n# {name}\n"
            )

        return str(skills_dir)

    def test_scan_discover_skills(self, tmp_path):
        """扫描应发现所有 skill.md 文件"""
        dir_path = self._make_mock_superpowers_dir(tmp_path)
        discovered = scan_superpowers_dir(dir_path)
        assert len(discovered) == 3

        names = [d[0] for d in discovered]
        assert "brainstorming" in names
        assert "systematic-debugging" in names
        assert "verification-before-completion" in names

    def test_scan_nonexistent_dir(self):
        """扫描不存在目录应返回空列表"""
        discovered = scan_superpowers_dir("/nonexistent/path")
        assert discovered == []

    def test_scan_dir_with_no_skills(self, tmp_path):
        """空目录应返回空列表"""
        empty_dir = tmp_path / "empty_skills"
        empty_dir.mkdir()
        discovered = scan_superpowers_dir(str(empty_dir))
        assert discovered == []


# ═══════════════════════════════════════════════════════════
#  Skill → SkillDefinition 映射
# ═══════════════════════════════════════════════════════════

class TestSkillMapping:
    def test_mapping_with_known_skill(self):
        """已知 skill 应正确映射 slot 和 tags"""
        fm = {"name": "brainstorming", "description": "Use before creative work"}
        skill_def = map_superpowers_to_skill_definition(
            "brainstorming", "/path/to/brainstorming/skill.md", fm, "5.1.0"
        )
        assert skill_def.id == "superpowers:brainstorming"
        assert skill_def.name == "brainstorming"
        assert skill_def.slot == SkillSlotName.PRE_EXECUTE
        assert "planning" in skill_def.tags
        assert "superpowers" in skill_def.tags
        assert skill_def.version == "5.1.0"
        assert skill_def.metadata["source"] == "superpowers"

    def test_mapping_with_debugging_skill(self):
        """debugging skill 应映射到 ON_ERROR slot"""
        fm = {"name": "systematic-debugging", "description": "Debug bugs"}
        skill_def = map_superpowers_to_skill_definition(
            "systematic-debugging", "/path/debugging/skill.md", fm
        )
        assert skill_def.id == "superpowers:systematic-debugging"
        assert skill_def.slot == SkillSlotName.ON_ERROR
        assert "debugging" in skill_def.tags

    def test_mapping_with_unknown_skill(self):
        """未知 skill 应映射到默认 slot (PRE_EXECUTE)"""
        fm = {"name": "future-skill", "description": "Some future skill"}
        skill_def = map_superpowers_to_skill_definition(
            "future-skill", "/path/future/skill.md", fm
        )
        assert skill_def.id == "superpowers:future-skill"
        assert skill_def.slot == SkillSlotName.PRE_EXECUTE  # 默认
        assert "superpowers" in skill_def.tags

    def test_namespace_prefix_prevents_collision(self):
        """superpowers: 前缀避免与 harness 内置 ID 冲突"""
        fm = {"name": "auto-audit", "description": "Audit skill from superpowers"}
        skill_def = map_superpowers_to_skill_definition(
            "auto-audit", "/path/skill.md", fm
        )
        # harness 内置的是 "auto-audit"，superpowers 版是 "superpowers:auto-audit"
        assert skill_def.id == "superpowers:auto-audit"
        assert skill_def.id != "auto-audit"


# ═══════════════════════════════════════════════════════════
#  注册集成
# ═══════════════════════════════════════════════════════════

class TestRegistrationIntegration:
    def test_register_mock_superpowers(self, tmp_path):
        """注册模拟的 superpowers skills 到 SkillRegistry"""
        # 创建模拟目录
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_dir = skills_dir / "brainstorming"
        skill_dir.mkdir()
        skill_md = skill_dir / "skill.md"
        skill_md.write_text(
            "---\nname: brainstorming\ndescription: \"Plan before coding\"\n---\n\n# Plan\n"
        )

        registry = SkillRegistry()
        registered = register_superpowers_skills(registry, str(skills_dir))

        assert len(registered) == 1
        assert registered[0].id == "superpowers:brainstorming"

        # 验证可以通过 registry 查找
        record = registry.get("superpowers:brainstorming")
        assert record is not None
        assert record.definition.name == "brainstorming"
        assert record.active

    def test_register_coexists_with_builtin(self, tmp_path):
        """superpowers skills 与 harness 内置 skills 应共存"""
        from harness.skill_registry import register_builtin_skills

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_dir = skills_dir / "brainstorming"
        skill_dir.mkdir()
        skill_md = skill_dir / "skill.md"
        skill_md.write_text(
            "---\nname: brainstorming\ndescription: \"Plan before coding\"\n---\n\n# Plan\n"
        )

        registry = SkillRegistry()
        register_builtin_skills(registry)
        register_superpowers_skills(registry, str(skills_dir))

        # 内置 + superpowers 应共存
        builtin = registry.get("auto-audit")
        assert builtin is not None
        superpowers = registry.get("superpowers:brainstorming")
        assert superpowers is not None

        # 总数 = 内置数 + superpowers 数
        all_skills = registry.list_active()
        assert len(all_skills) >= 4  # 3 builtin + 1 superpowers

    def test_register_no_superpowers_dir(self):
        """无 superpowers 目录时应静默跳过"""
        registry = SkillRegistry()
        # 不设置 HARNESS_SUPERPOWERS_DIR 环境变量
        # 并且确保找不到默认路径
        os.environ.pop("HARNESS_SUPERPOWERS_DIR", None)
        registered = register_superpowers_skills(registry, "/nonexistent/path")
        assert registered == []


# ═══════════════════════════════════════════════════════════
#  Slot 映射完整性
# ═══════════════════════════════════════════════════════════

class TestSlotMappingCompleteness:
    def test_all_superpowers_skills_have_slot(self):
        """每个已知的 superpowers skill 都在 _SLOT_MAP 中"""
        # 这些是从 superpowers 插件 v5.1.0 中实际存在的 skills
        known_skills = [
            "brainstorming",
            "dispatching-parallel-agents",
            "executing-plans",
            "finishing-a-development-branch",
            "receiving-code-review",
            "requesting-code-review",
            "subagent-driven-development",
            "systematic-debugging",
            "test-driven-development",
            "using-git-worktrees",
            "using-superpowers",
            "verification-before-completion",
            "writing-plans",
            "writing-skills",
        ]
        for skill in known_skills:
            assert skill in _SLOT_MAP, f"Missing slot mapping for: {skill}"

    def test_all_superpowers_skills_have_tags(self):
        """每个已知的 superpowers skill 都在 _TAG_MAP 中"""
        known_skills = list(_SLOT_MAP.keys())
        for skill in known_skills:
            assert skill in _TAG_MAP, f"Missing tag mapping for: {skill}"


# ═══════════════════════════════════════════════════════════
#  真实 superpowers 目录（如果存在）
# ═══════════════════════════════════════════════════════════

class TestRealSuperpowersIntegration:
    def test_find_and_register_real_superpowers(self):
        """如果能找到真实的 superpowers 目录，应成功注册"""
        reset_skill_registry()
        registry = SkillRegistry()

        os.environ.pop("HARNESS_SUPERPOWERS_DIR", None)
        dir_path = find_superpowers_dir()

        if dir_path is None:
            pytest.skip("No real superpowers directory found on this machine")

        registered = register_superpowers_skills(registry, dir_path)
        assert len(registered) > 0, "Should register at least 1 superpowers skill"

        # 验证关键 skills 都注册了
        for name in ["brainstorming", "systematic-debugging", "verification-before-completion"]:
            skill_id = f"superpowers:{name}"
            record = registry.get(skill_id)
            assert record is not None, f"Should find {skill_id} in registry"

    def test_skill_list_includes_source_field(self):
        """注册后的 skills 应有 source metadata"""
        reset_skill_registry()
        registry = SkillRegistry()

        os.environ.pop("HARNESS_SUPERPOWERS_DIR", None)
        dir_path = find_superpowers_dir()

        if dir_path is None:
            pytest.skip("No real superpowers directory found on this machine")

        register_superpowers_skills(registry, dir_path)
        all_skills = registry.list_active()

        superpowers_skills = [r for r in all_skills if r.definition.id.startswith("superpowers:")]
        for r in superpowers_skills:
            assert r.definition.metadata.get("source") == "superpowers"

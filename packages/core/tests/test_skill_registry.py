"""Skill Registry 单元测试"""

import sys
import os
import pytest
import tempfile
from pathlib import Path

# 确保 harness 包可导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.types import SkillDefinition, SkillSlotName, TaskResult, TaskStatus
from harness.skill_registry import (
    SkillRegistry, SkillRecord, reset_skill_registry,
    register_builtin_skills, register_project_skills,
    _parse_skill_md_frontmatter, _find_skill_entry_point,
)


class TestSkillRecord:
    """SkillRecord 测试"""

    def test_create_basic(self):
        sd = SkillDefinition(id="test", name="Test Skill")
        record = SkillRecord(sd)
        assert record.id == "test"
        assert record.active is True
        assert record.is_ready is False  # 无 implementation 也无 entry_point

    def test_is_ready_with_entry_point(self):
        sd = SkillDefinition(id="test", name="Test", entry_point="skills/test/run.py")
        record = SkillRecord(sd)
        assert record.is_ready is True

    def test_is_ready_with_implementation(self):
        sd = SkillDefinition(id="test", name="Test")
        record = SkillRecord(sd, implementation=lambda ctx: None)
        assert record.is_ready is True

    def test_is_ready_inactive(self):
        sd = SkillDefinition(id="test", name="Test", entry_point="run.py")
        record = SkillRecord(sd)
        record.active = False
        assert record.is_ready is False


class TestSkillRegistry:
    """SkillRegistry 测试"""

    def setup_method(self):
        """每个测试前重置注册表"""
        self.registry = SkillRegistry()
        self.registry._bus._handlers.clear()  # 清理事件订阅

    def test_register(self):
        sd = SkillDefinition(id="skill-a", name="Skill A", slot=SkillSlotName.POST_EXECUTE)
        record = self.registry.register(sd)
        assert record.id == "skill-a"
        assert record.definition.name == "Skill A"

    def test_register_duplicate_updates(self):
        self.registry.register(SkillDefinition(id="x", name="V1"))
        self.registry.register(SkillDefinition(id="x", name="V2"))
        assert self.registry.get("x").definition.name == "V2"
        assert self.registry.stats()["total_skills"] == 1

    def test_unregister(self):
        self.registry.register(SkillDefinition(id="y", name="Y"))
        assert self.registry.unregister("y") is True
        assert self.registry.get("y") is None
        assert self.registry.unregister("y") is False  # 已不存在

    def test_find_by_slot(self):
        self.registry.register(SkillDefinition(id="a", name="A", slot=SkillSlotName.PRE_EXECUTE))
        self.registry.register(SkillDefinition(id="b", name="B", slot=SkillSlotName.POST_EXECUTE))
        self.registry.register(SkillDefinition(id="c", name="C", slot=SkillSlotName.POST_EXECUTE))

        pre = self.registry.find_by_slot(SkillSlotName.PRE_EXECUTE)
        post = self.registry.find_by_slot(SkillSlotName.POST_EXECUTE)
        assert len(pre) == 1
        assert len(post) == 2

    def test_find_by_slot_excludes_inactive(self):
        self.registry.register(SkillDefinition(id="a", name="A", slot=SkillSlotName.POST_EXECUTE))
        self.registry.deactivate("a")
        assert len(self.registry.find_by_slot(SkillSlotName.POST_EXECUTE)) == 0

    def test_find_by_tag(self):
        self.registry.register(SkillDefinition(id="a", name="A", tags=["audit"]))
        self.registry.register(SkillDefinition(id="b", name="B", tags=["audit", "security"]))
        self.registry.register(SkillDefinition(id="c", name="C", tags=["testing"]))

        audit = self.registry.find_by_tag("audit")
        assert len(audit) == 2

    def test_execute_with_implementation(self):
        def my_impl(context):
            return TaskResult(
                task_id=context.get("task_id", "t"),
                agent_id="test-skill",
                status=TaskStatus.COMPLETED,
            )

        self.registry.register(
            SkillDefinition(id="test-skill", name="Test"),
            implementation=my_impl,
        )
        result = self.registry.execute_skill("test-skill", {"task_id": "t-1"})
        assert result is not None
        assert result.status == TaskStatus.COMPLETED
        assert result.agent_id == "test-skill"

    def test_execute_not_registered(self):
        result = self.registry.execute_skill("nonexistent", {})
        assert result is None

    def test_execute_inactive(self):
        self.registry.register(SkillDefinition(id="x", name="X", entry_point="run.py"))
        self.registry.deactivate("x")
        result = self.registry.execute_skill("x", {})
        assert result is None

    def test_activate_deactivate(self):
        self.registry.register(SkillDefinition(id="x", name="X"))
        assert self.registry.deactivate("x") is True
        assert self.registry.get("x").active is False
        assert self.registry.activate("x") is True
        assert self.registry.get("x").active is True

    def test_list_slots(self):
        self.registry.register(SkillDefinition(id="a", name="A", slot=SkillSlotName.PRE_EXECUTE))
        self.registry.register(SkillDefinition(id="b", name="B", slot=SkillSlotName.POST_EXECUTE))
        slots = self.registry.list_slots()
        assert "pre_execute" in slots
        assert "post_execute" in slots

    def test_stats(self):
        self.registry.register(SkillDefinition(id="a", name="A", tags=["t1"]))
        stats = self.registry.stats()
        assert stats["total_skills"] == 1
        assert stats["active_skills"] == 1

    def test_bind_implementation(self):
        self.registry.register(SkillDefinition(id="x", name="X"))
        assert self.registry.get("x").is_ready is False
        self.registry.bind_implementation("x", lambda ctx: TaskResult(
            task_id="t", agent_id="x", status=TaskStatus.COMPLETED,
        ))
        assert self.registry.get("x").is_ready is True


class TestRegisterBuiltinSkills:
    """register_builtin_skills 测试"""

    def test_registers_builtin_skills(self):
        reset_skill_registry()
        from harness.skill_registry import get_skill_registry
        reg = get_skill_registry()
        register_builtin_skills(reg)
        assert "auto-audit" in reg._skills
        assert "auto-review" in reg._skills
        assert "auto-verify" in reg._skills
        reset_skill_registry()


class TestRegisterProjectSkills:
    """register_project_skills 测试"""

    def test_no_skills_dir_returns_zero(self):
        """项目没有 .harness/skills/ → 返回 0"""
        registry = SkillRegistry()
        with tempfile.TemporaryDirectory() as tmpdir:
            count = register_project_skills(registry, project_dir=tmpdir)
            assert count == 0

    def test_registers_from_skills_dir(self):
        """有 SKILL.md + .py 文件 → 注册成功"""
        registry = SkillRegistry()
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建 .harness/skills/my-skill/
            skill_dir = Path(tmpdir) / ".harness" / "skills" / "my-skill"
            skill_dir.mkdir(parents=True)

            # 写 SKILL.md
            skill_md = skill_dir / "SKILL.md"
            skill_md.write_text(
                "---\n"
                "name: my-skill\n"
                "description: \"My custom skill\"\n"
                "slot: post_execute\n"
                "tags: [\"custom\"]\n"
                "---\n\n"
                "# My Skill\n"
            )

            # 写 .py 文件
            py_file = skill_dir / "my-skill.py"
            py_file.write_text("def main(): pass\n")

            count = register_project_skills(registry, project_dir=tmpdir)
            assert count == 1
            assert "my-skill" in registry._skills
            record = registry._skills["my-skill"]
            assert record.definition.entry_point == ".harness/skills/my-skill/my-skill.py"
            assert record.definition.tags == ["custom"]
            assert record.definition.metadata.get("source") == "project"

    def test_skips_dir_without_skill_md(self):
        """目录没有 SKILL.md → 跳过"""
        registry = SkillRegistry()
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / ".harness" / "skills" / "no-md"
            skill_dir.mkdir(parents=True)
            py_file = skill_dir / "run.py"
            py_file.write_text("def main(): pass\n")

            count = register_project_skills(registry, project_dir=tmpdir)
            assert count == 0

    def test_skips_dir_without_py_file(self):
        """目录没有 .py 文件 → 跳过"""
        registry = SkillRegistry()
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / ".harness" / "skills" / "no-py"
            skill_dir.mkdir(parents=True)
            skill_md = skill_dir / "SKILL.md"
            skill_md.write_text(
                "---\nname: no-py\n---\n\n# No Python\n"
            )

            count = register_project_skills(registry, project_dir=tmpdir)
            assert count == 0

    def test_builtin_overrides_project(self):
        """同名内置 skill 已注册 → 项目级跳过"""
        registry = SkillRegistry()
        # 先注册内置 auto-audit
        register_builtin_skills(registry)

        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / ".harness" / "skills" / "auto-audit"
            skill_dir.mkdir(parents=True)
            skill_md = skill_dir / "SKILL.md"
            skill_md.write_text(
                "---\nname: auto-audit\n---\n\n# Project Override\n"
            )
            py_file = skill_dir / "audit.py"
            py_file.write_text("def main(): pass\n")

            count = register_project_skills(registry, project_dir=tmpdir)
            assert count == 0  # 内置优先，项目级跳过

    def test_custom_slot_name(self):
        """自定义 slot → 正确映射"""
        registry = SkillRegistry()
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / ".harness" / "skills" / "pre-check"
            skill_dir.mkdir(parents=True)
            skill_md = skill_dir / "SKILL.md"
            skill_md.write_text(
                "---\nname: pre-check\nslot: pre_execute\n---\n\n# Pre Check\n"
            )
            py_file = skill_dir / "check.py"
            py_file.write_text("def main(): pass\n")

            count = register_project_skills(registry, project_dir=tmpdir)
            assert count == 1
            assert registry._skills["pre-check"].definition.slot == SkillSlotName.PRE_EXECUTE


class TestSkillMdParsing:
    """SKILL.md front matter 解析测试"""

    def test_parse_valid_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            md_file = Path(tmpdir) / "SKILL.md"
            md_file.write_text(
                "---\nname: my-skill\ndescription: \"Test\"\n---\n\nContent\n"
            )
            result = _parse_skill_md_frontmatter(md_file)
            assert result is not None
            assert result["name"] == "my-skill"

    def test_parse_no_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            md_file = Path(tmpdir) / "SKILL.md"
            md_file.write_text("# No front matter\n")
            result = _parse_skill_md_frontmatter(md_file)
            assert result is None

    def test_parse_empty_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            md_file = Path(tmpdir) / "SKILL.md"
            md_file.write_text("---\n---\n\nContent\n")
            result = _parse_skill_md_frontmatter(md_file)
            # YAML 解析空内容返回 None，不是 dict
            assert result is None


class TestFindSkillEntryPoint:
    """skill entry point 查找测试"""

    def test_single_py_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "my-skill"
            skill_dir.mkdir()
            py_file = skill_dir / "my-skill.py"
            py_file.write_text("def main(): pass\n")

            result = _find_skill_entry_point(skill_dir, {"name": "my-skill"})
            assert result == ".harness/skills/my-skill/my-skill.py"

    def test_multiple_py_files_prefers_matching_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "review"
            skill_dir.mkdir()
            (skill_dir / "review.py").write_text("def main(): pass\n")
            (skill_dir / "utils.py").write_text("def helper(): pass\n")

            result = _find_skill_entry_point(skill_dir, {"name": "review"})
            assert result == ".harness/skills/review/review.py"

    def test_explicit_entry_point_in_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "custom"
            skill_dir.mkdir()

            result = _find_skill_entry_point(skill_dir, {"entry_point": ".harness/skills/custom/main.py"})
            assert result == ".harness/skills/custom/main.py"

    def test_no_py_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "empty"
            skill_dir.mkdir()

            result = _find_skill_entry_point(skill_dir, {"name": "empty"})
            assert result == ""

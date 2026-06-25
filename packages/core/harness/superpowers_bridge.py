"""Superpowers Skills Bridge — 将 Claude Code superpowers 插件的 Skills 发现并注册到 harness SkillRegistry

两套体系的融合桥接：
  - superpowers skills: YAML frontmatter (name, description) + skill.md 内容
  - harness SkillDefinition: id, name, description, slot, tags, entry_point, metadata

核心功能：
  1. 发现: scan_superpowers_dir() — 扫描 superpowers 插件目录下的 skill.md
  2. 解析: parse_skill_frontmatter() — 解析 YAML frontmatter 获取 name/description
  3. 映射: map_superpowers_to_skill_definition() — 将 superpowers skill 映射为 SkillDefinition
  4. 注册: register_superpowers_skills() — 批量注册到 SkillRegistry

命名空间策略:
  - superpowers skills 使用 "superpowers:" 前缀，避免与 harness 内置 skills ID 冲突
  - 例: brainstorming → superpowers:brainstorming

Slot 映射策略（基于 superpowers skill 的语义分类）:
  - brainstorming, writing-plans → PRE_EXECUTE（执行前的规划阶段）
  - test-driven-development → PRE_EXECUTE（执行前的 TDD 循环）
  - systematic-debugging → ON_ERROR（调试异常）
  - verification-before-completion → POST_EXECUTE（完成后验证）
  - receiving-code-review, requesting-code-review → POST_EXECUTE（完成后审查）
  - subagent-driven-development, dispatching-parallel-agents → PRE_EXECUTE（执行前的任务分解）
  - executing-plans → PRE_EXECUTE（执行计划）
  - finishing-a-development-branch → POST_EXECUTE（分支完成）
  - using-git-worktrees → PRE_EXECUTE（工作树准备）
  - writing-skills → PRE_EXECUTE（创建 skill）
  - using-superpowers → SESSION_START（会话初始化）
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from harness.skill_registry import SkillRegistry
from harness.types import SkillDefinition, SkillSlotName

logger = logging.getLogger("harness.superpowers_bridge")


# ═══════════════════════════════════════════════════════════
#  Slot 映射表 — superpowers skill name → SkillSlotName
# ═══════════════════════════════════════════════════════════

_SLOT_MAP: Dict[str, SkillSlotName] = {
    # ── 执行前: 规划/分解/准备 ──
    "brainstorming": SkillSlotName.PRE_EXECUTE,
    "writing-plans": SkillSlotName.PRE_EXECUTE,
    "test-driven-development": SkillSlotName.PRE_EXECUTE,
    "subagent-driven-development": SkillSlotName.PRE_EXECUTE,
    "dispatching-parallel-agents": SkillSlotName.PRE_EXECUTE,
    "executing-plans": SkillSlotName.PRE_EXECUTE,
    "using-git-worktrees": SkillSlotName.PRE_EXECUTE,
    "writing-skills": SkillSlotName.PRE_EXECUTE,

    # ── 执行后: 验证/审查/完成 ──
    "verification-before-completion": SkillSlotName.POST_EXECUTE,
    "receiving-code-review": SkillSlotName.POST_EXECUTE,
    "requesting-code-review": SkillSlotName.POST_EXECUTE,
    "finishing-a-development-branch": SkillSlotName.POST_EXECUTE,

    # ── 异常处理 ──
    "systematic-debugging": SkillSlotName.ON_ERROR,

    # ── 会话初始化 ──
    "using-superpowers": SkillSlotName.SESSION_START,
}

# 默认 slot — 未在映射表中的 superpowers skill
_DEFAULT_SLOT = SkillSlotName.PRE_EXECUTE


# ═══════════════════════════════════════════════════════════
#  Tags 推导 — 基于 superpowers skill name 和 description
# ═══════════════════════════════════════════════════════════

_TAG_MAP: Dict[str, List[str]] = {
    "brainstorming": ["planning", "design", "pre-implementation"],
    "writing-plans": ["planning", "architecture"],
    "test-driven-development": ["testing", "tdd", "quality"],
    "systematic-debugging": ["debugging", "troubleshooting", "error-handling"],
    "verification-before-completion": ["verification", "quality", "testing"],
    "receiving-code-review": ["code-review", "feedback", "quality"],
    "requesting-code-review": ["code-review", "collaboration"],
    "subagent-driven-development": ["agents", "parallel", "scaling"],
    "dispatching-parallel-agents": ["agents", "parallel", "scaling"],
    "executing-plans": ["execution", "implementation"],
    "finishing-a-development-branch": ["git", "branching", "completion"],
    "using-git-worktrees": ["git", "isolation", "worktrees"],
    "writing-skills": ["skills", "creation", "meta"],
    "using-superpowers": ["superpowers", "meta", "session-init"],
}


# ═══════════════════════════════════════════════════════════
#  YAML Frontmatter 解析
# ═══════════════════════════════════════════════════════════

def parse_skill_frontmatter(skill_md_path: str) -> Optional[Dict[str, str]]:
    """
    解析 skill.md 文件的 YAML frontmatter

    格式:
        ---
        name: brainstorming
        description: "You MUST use this before..."
        ---
        # Brainstorming Ideas...
    """
    try:
        with open(skill_md_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (FileNotFoundError, OSError) as exc:
        logger.warning(f"Cannot read skill.md: {skill_md_path} — {exc}")
        return None

    # 提取 YAML frontmatter (--- 之间的内容)
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not fm_match:
        logger.warning(f"No YAML frontmatter in {skill_md_path}")
        return None

    fm_text = fm_match.group(1)
    result = {}

    # 简单 YAML 解析（不需要 pyyaml 依赖，frontmatter 只有 name 和 description）
    for line in fm_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # key: value 或 key: "quoted value"
        kv_match = re.match(r"^(\w+)\s*:\s*(.+)$", line)
        if kv_match:
            key = kv_match.group(1)
            value = kv_match.group(2).strip()
            # 去掉引号
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1]
            result[key] = value

    if "name" not in result:
        logger.warning(f"Missing 'name' in frontmatter: {skill_md_path}")
        return None

    return result


# ═══════════════════════════════════════════════════════════
#  Superpowers 目录扫描
# ═══════════════════════════════════════════════════════════

def scan_superpowers_dir(superpowers_dir: str) -> List[Tuple[str, str, Dict[str, str]]]:
    """
    扫描 superpowers 插件目录，发现所有 skill.md 文件

    Args:
        superpowers_dir: superpowers 插件目录路径
            例: ~/.claude/plugins/cache/claude-plugins-official/superpowers/5.1.0/skills/

    Returns:
        List of (skill_name, skill_md_path, frontmatter_dict) tuples
    """
    skills_path = Path(superpowers_dir)
    if not skills_path.is_dir():
        logger.warning(f"Superpowers directory not found: {superpowers_dir}")
        return []

    discovered = []

    for skill_dir in skills_path.iterdir():
        if not skill_dir.is_dir():
            continue
        skill_name = skill_dir.name
        # 查找 skill.md 或 SKILL.md
        skill_md = skill_dir / "skill.md"
        if not skill_md.exists():
            skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            logger.debug(f"No skill.md found in {skill_dir}")
            continue

        fm = parse_skill_frontmatter(str(skill_md))
        if fm is None:
            continue

        # frontmatter 中的 name 可能与目录名不同，优先用 frontmatter name
        effective_name = fm.get("name", skill_name)
        discovered.append((effective_name, str(skill_md), fm))

    logger.info(f"Discovered {len(discovered)} superpowers skills from {superpowers_dir}")
    return discovered


def find_superpowers_dir() -> Optional[str]:
    """
    自动定位 superpowers 插件目录

    搜索路径:
      1. ~/.claude/plugins/cache/claude-plugins-official/superpowers/<version>/skills/
      2. 环境变量 HARNESS_SUPERPOWERS_DIR
      3. 项目内 .claude/skills/ (全局 skills 目录)
    """
    # 环境变量优先
    env_dir = os.environ.get("HARNESS_SUPERPOWERS_DIR")
    if env_dir and Path(env_dir).is_dir():
        return env_dir

    # 扫描 ~/.claude/plugins/cache/
    home = Path.home()
    cache_dir = home / ".claude" / "plugins" / "cache" / "claude-plugins-official" / "superpowers"

    if cache_dir.is_dir():
        # 找到最新版本目录
        version_dirs = sorted(
            [d for d in cache_dir.iterdir() if d.is_dir()],
            key=lambda d: d.name,
            reverse=True,
        )
        for vdir in version_dirs:
            skills_dir = vdir / "skills"
            if skills_dir.is_dir():
                logger.info(f"Found superpowers at {skills_dir}")
                return str(skills_dir)

    logger.info("Superpowers plugin directory not found — bridge will be empty")
    return None


# ═══════════════════════════════════════════════════════════
#  映射 + 注册
# ═══════════════════════════════════════════════════════════

def map_superpowers_to_skill_definition(
    skill_name: str,
    skill_md_path: str,
    frontmatter: Dict[str, str],
    plugin_version: str = "unknown",
) -> SkillDefinition:
    """
    将 superpowers skill 映射为 harness SkillDefinition

    命名空间: superpowers:<name>
    Slot: 根据 _SLOT_MAP 映射
    Tags: 根据 _TAG_MAP 映射，自动加 "superpowers" 标签
    """
    # ID 使用 superpowers: 前缀，避免与 harness 内置 ID 冲突
    skill_id = f"superpowers:{skill_name}"

    # Slot 映射
    slot = _SLOT_MAP.get(skill_name, _DEFAULT_SLOT)

    # Tags 映射
    tags = _TAG_MAP.get(skill_name, ["superpowers"])
    if "superpowers" not in tags:
        tags.append("superpowers")

    description = frontmatter.get("description", "")

    return SkillDefinition(
        id=skill_id,
        name=skill_name,
        description=description,
        version=plugin_version,
        entry_point=skill_md_path,
        slot=slot,
        tags=tags,
        metadata={
            "source": "superpowers",
            "original_name": skill_name,
            "skill_md_path": skill_md_path,
            "plugin_version": plugin_version,
        },
    )


def register_superpowers_skills(
    registry: Optional[SkillRegistry] = None,
    superpowers_dir: Optional[str] = None,
) -> List[SkillDefinition]:
    """
    发现并注册所有 superpowers skills 到 SkillRegistry

    Args:
        registry: 目标 SkillRegistry（默认用全局单例）
        superpowers_dir: superpowers 目录（默认自动发现）

    Returns:
        注册成功的 SkillDefinition 列表
    """
    reg = registry or _get_global_registry()
    dir_path = superpowers_dir or find_superpowers_dir()

    if dir_path is None:
        logger.info("No superpowers directory found — skipping bridge registration")
        return []

    # 解析插件版本号（从目录路径推断）
    plugin_version = "unknown"
    version_match = re.search(r"/superpowers/([\d.]+)/skills", dir_path)
    if version_match:
        plugin_version = version_match.group(1)

    discovered = scan_superpowers_dir(dir_path)
    registered = []

    for skill_name, skill_md_path, fm in discovered:
        skill_def = map_superpowers_to_skill_definition(
            skill_name, skill_md_path, fm, plugin_version
        )
        record = reg.register(skill_def)
        registered.append(skill_def)
        logger.debug(
            f"Registered superpowers skill: {skill_def.id} "
            f"(slot={skill_def.slot.value}, tags={skill_def.tags})"
        )

    logger.info(f"Registered {len(registered)} superpowers skills into SkillRegistry")
    return registered


def _get_global_registry() -> SkillRegistry:
    """获取全局 SkillRegistry — 惰性导入避免循环依赖"""
    from harness.skill_registry import get_skill_registry
    return get_skill_registry()

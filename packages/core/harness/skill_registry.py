"""
harness-cook Skill 注册与发现

Skill Registry 管理所有可插拔的 Skill——注册、发现、按插槽查找、执行。
与 AgentRegistry 平行设计，保持 API 风格一致。

设计原则：
  - 注册是声明式的：SkillDefinition 声明能力，implementation 可后绑定
  - 插槽驱动发现：通过 SkillSlotName 查找"谁在这个阶段执行"
  - 执行双模式：有 implementation 直接调用，否则 CLI 方式执行 entry_point

核心概念：Skills 定步骤。
每个 Skill 挂载到一个插槽（SkillSlotName），在对应生命周期阶段自动执行。
"""

import logging
import subprocess
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Optional, Dict, List, Callable, Any

from harness.types import (
    SkillDefinition, SkillSlotName, TaskResult, TaskStatus, Artifact,
)
from harness.bus import EventBus, BusEventType, BusEvent, get_bus
from harness.config import find_project_root


logger = logging.getLogger("harness.skill_registry")


# ─── Skill 记录 ──────────────────────────────────────

class SkillRecord:
    """Skill 注册记录——定义 + 实现 + 状态"""

    def __init__(
        self,
        definition: SkillDefinition,
        implementation: Optional[Callable] = None,
    ):
        self.definition = definition
        self.implementation = implementation
        self.active: bool = True
        self.exec_count: int = 0
        self.error_count: int = 0
        self.last_used: Optional[float] = None

    @property
    def id(self) -> str:
        return self.definition.id

    @property
    def is_ready(self) -> bool:
        """是否就绪——激活 + 有入口（implementation 或 entry_point）"""
        return self.active and bool(
            self.implementation is not None or self.definition.entry_point
        )

    def mark_exec_start(self) -> None:
        self.last_used = time.time()
        self.exec_count += 1

    def mark_exec_complete(self) -> None:
        pass  # 成功不额外标记

    def mark_exec_error(self) -> None:
        self.error_count += 1


# ─── Skill 注册表 ────────────────────────────────────

class SkillRegistry:
    """
    Skill 注册表——管理所有可用的 Skill

    用法:
        registry = SkillRegistry()
        registry.register(SkillDefinition(
            id="auto-audit", name="自动审计",
            slot=SkillSlotName.POST_EXECUTE,
            entry_point="skills/auto-audit/audit_report.py",
        ))
        skills = registry.find_by_slot(SkillSlotName.POST_EXECUTE)
        result = registry.execute_skill("auto-audit", {"task_id": "t-1"})
    """

    def __init__(self, bus: Optional[EventBus] = None):
        self._skills: Dict[str, SkillRecord] = {}
        self._bus = bus or get_bus()
        # 插槽映射: slot_name → [skill_id, ...]
        self._slot_map: Dict[SkillSlotName, List[str]] = defaultdict(list)

    # ─── 注册 ────────────────────────────────────────

    def register(
        self,
        skill_def: SkillDefinition,
        implementation: Optional[Callable] = None,
    ) -> SkillRecord:
        """
        注册 Skill

        Args:
            skill_def: Skill 定义（ID、插槽、入口等）
            implementation: 可执行函数（可选，可后绑定）

        Returns:
            SkillRecord 注册记录
        """
        if skill_def.id in self._skills:
            logger.warning(f"Skill {skill_def.id} already registered — updating")
            record = self._skills[skill_def.id]
            record.definition = skill_def
            if implementation:
                record.implementation = implementation
        else:
            record = SkillRecord(definition=skill_def, implementation=implementation)
            self._skills[skill_def.id] = record
            self._slot_map[skill_def.slot].append(skill_def.id)

        logger.info(
            f"Registered skill {skill_def.id} ({skill_def.name}) "
            f"slot={skill_def.slot.value}"
        )

        self._bus.emit(BusEvent(
            type=BusEventType.NODE_START,  # 复用事件类型表示注册
            execution_id="skill-registry",
            data={"skill_id": skill_def.id, "skill_name": skill_def.name, "slot": skill_def.slot.value},
        ))

        return record

    def bind_implementation(self, skill_id: str, implementation: Callable) -> bool:
        """后绑定实现"""
        record = self._skills.get(skill_id)
        if not record:
            logger.error(f"Skill {skill_id} not registered — cannot bind implementation")
            return False
        record.implementation = implementation
        logger.info(f"Bound implementation to skill {skill_id}")
        return True

    def unregister(self, skill_id: str) -> bool:
        """注销 Skill"""
        record = self._skills.pop(skill_id, None)
        if not record:
            return False
        slot = record.definition.slot
        if skill_id in self._slot_map.get(slot, []):
            self._slot_map[slot].remove(skill_id)
        logger.info(f"Unregistered skill {skill_id} (execs={record.exec_count}, errors={record.error_count})")
        return True

    # ─── 查询 ────────────────────────────────────────

    def get(self, skill_id: str) -> Optional[SkillRecord]:
        """按 ID 获取 Skill 记录"""
        return self._skills.get(skill_id)

    def has(self, skill_id: str) -> bool:
        """E-10：检查 skill_id 是否已注册"""
        return skill_id in self._skills

    def find_by_slot(self, slot: SkillSlotName) -> List[SkillRecord]:
        """按插槽查找——返回该插槽上所有激活的 Skill"""
        skill_ids = self._slot_map.get(slot, [])
        return [
            self._skills[sid]
            for sid in skill_ids
            if sid in self._skills and self._skills[sid].active
        ]

    def find_by_tag(self, tag: str) -> List[SkillRecord]:
        """按标签查找"""
        return [
            r for r in self._skills.values()
            if tag in r.definition.tags and r.active
        ]

    def list_all(self) -> List[SkillRecord]:
        """列出所有已注册的 Skill（包括未激活）"""
        return list(self._skills.values())

    def list_active(self) -> List[SkillRecord]:
        """列出所有激活的 Skill"""
        return [r for r in self._skills.values() if r.active]

    def list_slots(self) -> Dict[str, List[str]]:
        """列出每个插槽上的 Skill ID"""
        return {
            slot.value: list(skill_ids)
            for slot, skill_ids in self._slot_map.items()
            if skill_ids
        }

    # ─── 状态管理 ──────────────────────────────────────

    def activate(self, skill_id: str) -> bool:
        """激活 Skill"""
        record = self._skills.get(skill_id)
        if not record:
            return False
        record.active = True
        return True

    def deactivate(self, skill_id: str) -> bool:
        """停用 Skill"""
        record = self._skills.get(skill_id)
        if not record:
            return False
        record.active = False
        return True

    # ─── 执行 ────────────────────────────────────────

    def execute_skill(self, skill_id: str, context: dict) -> Optional[TaskResult]:
        """
        执行 Skill

        优先使用 implementation（Python 函数），
        否则用 CLI 方式执行 entry_point。

        Args:
            skill_id: Skill ID
            context: 执行上下文

        Returns:
            TaskResult 或 None（Skill 未注册/未就绪）
        """
        record = self._skills.get(skill_id)
        if not record or not record.active:
            logger.warning(f"Skill {skill_id} not registered or inactive")
            return None

        if not record.is_ready:
            logger.warning(f"Skill {skill_id} not ready (no implementation or entry_point)")
            return None

        record.mark_exec_start()
        start_time = time.time()

        try:
            if record.implementation:
                result = self._execute_implementation(record, context)
                if not isinstance(result, TaskResult):
                    # 实现返回的不是 TaskResult → 包装
                    result = TaskResult(
                        task_id=context.get("task_id", str(uuid.uuid4())),
                        agent_id=skill_id,
                        status=TaskStatus.COMPLETED,
                        artifacts=[Artifact(type="log", path=skill_id, content=str(result))],
                    )
                record.mark_exec_complete()
                duration_ms = int((time.time() - start_time) * 1000)
                self._log_execution(skill_id, result.status.value, duration_ms, context)
                return result
            else:
                result = self._execute_cli_skill(record, context)
                duration_ms = int((time.time() - start_time) * 1000)
                if result.status == TaskStatus.COMPLETED:
                    record.mark_exec_complete()
                    self._log_execution(skill_id, "completed", duration_ms, context)
                else:
                    record.mark_exec_error()
                    self._log_execution(skill_id, "failed", duration_ms, context, error=result.error)
                return result
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            record.mark_exec_error()
            logger.error(f"Skill {skill_id} execution failed: {e}", exc_info=True)
            self._log_execution(skill_id, "error", duration_ms, context, error=str(e))
            return TaskResult(
                task_id=context.get("task_id", str(uuid.uuid4())),
                agent_id=skill_id,
                status=TaskStatus.FAILED,
                error=str(e),
            )

    def _log_execution(
        self,
        skill_id: str,
        status: str,
        duration_ms: int,
        context: dict,
        error: Optional[str] = None,
    ) -> None:
        """记录 Skill 执行到审计日志"""
        try:
            from harness.audit_logger import log_skill_execute
            # 通过 skill_id 从注册表获取 record 以读取 slot 信息
            record = self._skills.get(skill_id)
            slot_value = record.definition.slot.value if record else "unknown"
            log_skill_execute(
                skill_id=skill_id,
                status=status,
                duration_ms=duration_ms,
                session_id=context.get("session_id", "unknown"),
                node_id=context.get("node_id", ""),
                slot=slot_value,
                trigger_node=context.get("node_id", ""),
                error=error,
            )
        except Exception as e:
            logger.warning(f"Failed to write audit log for skill {skill_id}: {e}")

    def _execute_implementation(
        self,
        record: SkillRecord,
        context: dict,
    ) -> Any:
        """
        执行 Skill 的 Python implementation，带超时保护

        超时策略（跨平台）：
          - Unix: signal.SIGALRM（精确，不占线程）
          - Windows / SIGALRM 不可用: threading.Timer（占一个线程但通用）

        超时后返回 TaskStatus.FAILED，不强制杀死线程。
        """
        timeout = record.definition.timeout_seconds
        if not timeout or timeout <= 0:
            # 无超时限制，直接执行
            return record.implementation(context)

        # 尝试 SIGALRM 方式（Unix）
        try:
            import signal

            class _SkillTimeout(Exception):
                pass

            def _timeout_handler(signum, frame):
                raise _SkillTimeout(
                    f"Skill {record.definition.id} timed out after {timeout}s"
                )

            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(timeout)
            try:
                result = record.implementation(context)
                signal.alarm(0)  # 取消闹钟
                return result
            except _SkillTimeout:
                signal.alarm(0)
                logger.warning(
                    f"Skill {record.definition.id} timed out after {timeout}s (SIGALRM)"
                )
                raise
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

        except (AttributeError, ValueError, OSError):
            # SIGALRM 不可用（Windows / 非主线程）→ 用 threading.Timer
            import threading

            timed_out = threading.Event()
            result_holder: list = [None]
            error_holder: list = [None]

            def _run():
                try:
                    result_holder[0] = record.implementation(context)
                except Exception as e:
                    error_holder[0] = e
                finally:
                    timed_out.set()

            thread = threading.Thread(target=_run, daemon=True)
            thread.start()
            finished = timed_out.wait(timeout=timeout)

            if not finished:
                logger.warning(
                    f"Skill {record.definition.id} timed out after {timeout}s (Timer)"
                )
                raise TimeoutError(
                    f"Skill {record.definition.id} timed out after {timeout}s"
                )

            if error_holder[0]:
                raise error_holder[0]
            return result_holder[0]

    def _execute_cli_skill(self, record: SkillRecord, context: dict) -> TaskResult:
        """CLI 方式执行 Skill"""
        entry = record.definition.entry_point
        task_id = context.get("task_id", str(uuid.uuid4()))

        # ── 安全加固：验证 entry_point 路径 ──
        if not self._validate_entry_point(entry):
            return TaskResult(
                task_id=task_id,
                agent_id=record.definition.id,
                status=TaskStatus.FAILED,
                error=f"Invalid entry_point path (contains forbidden patterns): {entry}",
            )

        try:
            result = subprocess.run(
                ["python3", entry],
                capture_output=True, text=True, timeout=120,
            )
            status = TaskStatus.COMPLETED if result.returncode == 0 else TaskStatus.FAILED
            return TaskResult(
                task_id=task_id,
                agent_id=record.definition.id,
                status=status,
                artifacts=[Artifact(type="log", path=entry, content=result.stdout[:10000])],
                error=result.stderr[:2000] if result.returncode != 0 else None,
            )
        except subprocess.TimeoutExpired:
            return TaskResult(
                task_id=task_id,
                agent_id=record.definition.id,
                status=TaskStatus.FAILED,
                error=f"Skill execution timed out (120s): {entry}",
            )
        except Exception as e:
            return TaskResult(
                task_id=task_id,
                agent_id=record.definition.id,
                status=TaskStatus.FAILED,
                error=f"Skill execution error: {e}",
            )

    def _validate_entry_point(self, entry_point: str) -> bool:
        """
        验证 entry_point 路径安全性

        检查项：
          1. 禁止路径穿越（../、..\\）
          2. 禁止绝对路径（/开头）
          3. 必须以 .py 结尾

        Returns:
            True = 安全，False = 不安全
        """
        if not entry_point:
            return False

        # 禁止路径穿越
        if ".." in entry_point or "~" in entry_point:
            logger.warning(f"Rejected entry_point with path traversal: {entry_point}")
            return False

        # 禁止绝对路径
        if entry_point.startswith("/") or entry_point.startswith("\\"):
            logger.warning(f"Rejected absolute entry_point: {entry_point}")
            return False

        # 必须以 .py 结尾
        if not entry_point.endswith(".py"):
            logger.warning(f"Rejected non-Python entry_point: {entry_point}")
            return False

        return True

    # ─── 统计 ────────────────────────────────────────

    def stats(self) -> dict:
        """注册表统计"""
        records = list(self._skills.values())
        return {
            "total_skills": len(records),
            "active_skills": sum(1 for r in records if r.active),
            "ready_skills": sum(1 for r in records if r.is_ready),
            "total_executions": sum(r.exec_count for r in records),
            "total_errors": sum(r.error_count for r in records),
            "slots": self.list_slots(),
            "by_tag": self._tag_stats(),
        }

    def _tag_stats(self) -> dict:
        """标签统计"""
        tag_count: Dict[str, int] = defaultdict(int)
        for r in self._skills.values():
            for tag in r.definition.tags:
                tag_count[tag] += 1
        return dict(tag_count)


# ─── 全局单例 ────────────────────────────────────────

_global_skill_registry: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    """获取全局 Skill 注册表单例"""
    global _global_skill_registry
    if _global_skill_registry is None:
        _global_skill_registry = SkillRegistry()
    return _global_skill_registry


def reset_skill_registry() -> None:
    """重置全局 Skill 注册表（主要用于测试）"""
    global _global_skill_registry
    _global_skill_registry = SkillRegistry()


def register_builtin_skills(registry: Optional[SkillRegistry] = None) -> None:
    """注册内置 Skills——从 skills/ 目录自动发现并注册"""
    reg = registry or get_skill_registry()

    builtin_skills = [
        SkillDefinition(
            id="auto-audit",
            name="自动审计",
            description="任务完成后自动记录审计日志",
            entry_point="skills/auto-audit/audit_report.py",
            slot=SkillSlotName.POST_EXECUTE,
            tags=["audit", "compliance"],
        ),
        SkillDefinition(
            id="auto-review",
            name="自动审查",
            description="代码变更后自动运行门禁审查",
            entry_point="skills/auto-review/review_gate.py",
            slot=SkillSlotName.POST_EXECUTE,
            tags=["review", "gate"],
        ),
        SkillDefinition(
            id="auto-verify",
            name="自动验证",
            description="验证代码变更是否达到预期效果",
            entry_point="skills/auto-verify/verify.py",
            slot=SkillSlotName.ON_GATE_PASS,
            tags=["verify", "testing"],
        ),
        SkillDefinition(
            id="auto-fix",
            name="自动修复（规划中）",
            description="门禁失败时自动尝试修复——当前为占位定义。entry_point 留空使 is_ready=False，"
                        "execute 时自动跳过（warning），不执行任何修复。待实现后填入 entry_point 即激活。",
            entry_point="",  # 规划中：留空 → 未就绪 → execute 跳过，避免运行时 FAILED
            slot=SkillSlotName.ON_GATE_FAIL,
            tags=["fix", "gate"],
        ),
    ]

    for skill_def in builtin_skills:
        if skill_def.id not in reg._skills:
            reg.register(skill_def)

    logger.info(f"Registered {len(builtin_skills)} builtin skills")


def register_project_skills(
    registry: Optional[SkillRegistry] = None,
    project_dir: Optional[str] = None,
) -> int:
    """
    注册项目级 Skills——从项目 .harness/skills/ 目录自动发现并注册

    项目级 skill 是用户在项目中自建的，与内置 skill（harness-cook 仓库里的）并列。
    每个 skill 目录包含 SKILL.md（声明元数据）和可执行脚本。

    发现逻辑：
      1. 定位 .harness/skills/ 目录（project_dir 参数 > find_project_root()）
      2. 扫描所有子目录，检查是否包含 SKILL.md
      3. 解析 SKILL.md 的 YAML front matter 提取元数据
      4. 自动查找 .py 脚本作为 entry_point
      5. 用解析出的元数据 + entry_point 注册到 SkillRegistry

    Args:
        registry: 目标注册表（默认使用全局注册表）
        project_dir: 项目根目录（默认自动检测）

    Returns:
        注册的项目级 skill 数量
    """
    reg = registry or get_skill_registry()

    # 定位项目根目录
    if project_dir:
        root = Path(project_dir)
    else:
        root = find_project_root()

    skills_dir = root / ".harness" / "skills"
    if not skills_dir.exists() or not skills_dir.is_dir():
        logger.debug(f"No project skills directory found at {skills_dir}")
        return 0

    registered_count = 0

    for skill_subdir in skills_dir.iterdir():
        if not skill_subdir.is_dir():
            continue

        skill_md = skill_subdir / "SKILL.md"
        if not skill_md.exists():
            logger.debug(f"Skipping {skill_subdir.name}: no SKILL.md found")
            continue

        # 解析 SKILL.md 的 YAML front matter
        metadata = _parse_skill_md_frontmatter(skill_md)
        if not metadata:
            logger.warning(f"Skipping {skill_subdir.name}: failed to parse SKILL.md front matter")
            continue

        # 自动查找 entry_point（.py 脚本）
        entry_point = _find_skill_entry_point(skill_subdir, metadata)
        if not entry_point:
            logger.warning(f"Skipping {skill_subdir.name}: no Python entry point found")
            continue

        # 确定插槽
        slot_name = metadata.get("slot", "post_execute")
        try:
            slot = SkillSlotName(slot_name)
        except ValueError:
            logger.warning(f"Unknown slot '{slot_name}' for {skill_subdir.name}, using POST_EXECUTE")
            slot = SkillSlotName.POST_EXECUTE

        skill_def = SkillDefinition(
            id=metadata.get("name", skill_subdir.name),
            name=metadata.get("title", metadata.get("name", skill_subdir.name)),
            description=metadata.get("description", ""),
            version=metadata.get("version", "1.0.0"),
            entry_point=entry_point,
            slot=slot,
            tags=metadata.get("tags", []),
            metadata={"source": "project", "project_dir": str(root)},
        )

        # 内置 skill 优先级更高：如果同名已注册，项目级跳过
        if skill_def.id in reg._skills:
            existing = reg._skills[skill_def.id]
            if existing.definition.metadata.get("source") != "project":
                logger.info(f"Skipping project skill {skill_def.id}: builtin already registered")
                continue

        reg.register(skill_def)
        registered_count += 1

    logger.info(f"Registered {registered_count} project skills from {skills_dir}")
    return registered_count


def _parse_skill_md_frontmatter(skill_md: Path) -> Optional[Dict[str, Any]]:
    """
    解析 SKILL.md 的 YAML front matter

    格式：
    ---
    name: auto-audit
    description: "..."
    slot: post_execute
    tags: ["audit", "compliance"]
    ---
    """
    try:
        content = skill_md.read_text()
        if not content.startswith("---"):
            return None

        # 提取 front matter
        end_idx = content.find("---", 3)
        if end_idx < 0:
            return None

        yaml_content = content[3:end_idx].strip()

        # 尝试解析 YAML（轻量级，不依赖 PyYAML 的复杂功能）
        import yaml
        metadata = yaml.safe_load(yaml_content)
        if not isinstance(metadata, dict):
            return None

        return metadata

    except Exception as e:
        logger.debug(f"Failed to parse {skill_md}: {e}")
        return None


def _find_skill_entry_point(skill_dir: Path, metadata: Dict[str, Any]) -> str:
    """
    自动查找 skill 的 Python entry point

    查找策略：
      1. metadata 中明确指定 entry_point → 直接使用
      2. 目录中唯一 .py 文件 → 使用它
      3. 目录中多个 .py 文件 → 优先选与目录名匹配的
      4. 都没有 → 返回空（跳过注册）

    返回的路径是相对于 .harness/skills/ 的，形如 ".harness/skills/custom-review/review.py"
    """
    # 1. 明确指定
    explicit_entry = metadata.get("entry_point", "")
    if explicit_entry:
        return explicit_entry

    # 查找 .py 文件
    py_files = [f for f in skill_dir.iterdir() if f.is_file() and f.suffix == ".py" and not f.name.startswith("_")]
    if not py_files:
        return ""

    # 2. 唯一 .py 文件
    if len(py_files) == 1:
        return str(Path(".harness") / "skills" / skill_dir.name / py_files[0].name)

    # 3. 多个 .py 文件 → 优先选与目录名匹配的
    for py_file in py_files:
        if py_file.stem == skill_dir.name:
            return str(Path(".harness") / "skills" / skill_dir.name / py_file.name)

    # 4. 回退：选第一个非 __init__.py 的
    return str(Path(".harness") / "skills" / skill_dir.name / py_files[0].name)

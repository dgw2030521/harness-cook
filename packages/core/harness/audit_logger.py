"""
harness-cook 审计日志写入器

定位：操作溯源——记录 Agent "具体做了什么、改了什么文件、触发了什么规则"，
而非流水账式的"做了什么事件"。

每条审计记录必须回答：
  1. 做了什么操作？（事件类型 + 具体动作）
  2. 操作对象是什么？（文件路径、工具名、命令）
  3. 结果如何？（违规详情、PII 详情、门禁检查结果）
  4. 可追溯吗？（session_id 关联同一会话的所有操作）

存储统一走 AuditStore.save() → 自动获得 SHA-256 哈希链保护。
降级机制：如果 AuditStore 导入失败，回退到原有的扁平 JSON 写入。
"""

import json
import logging
import os
from pathlib import Path
from datetime import datetime
from typing import Optional

from harness.config import find_project_root

logger = logging.getLogger("harness.audit_logger")


# ─── session_id 获取 ────────────────────────────────────

def _resolve_session_id(session_id: Optional[str] = None) -> str:
    """
    解析 session_id

    优先级：
      1. 显式传入的 session_id（非 "unknown"）
      2. 从 .harness/session_id 文件读取
      3. 降级为 "unknown"
    """
    if session_id and session_id != "unknown":
        return session_id

    # 从 .harness/session_id 文件读取（由 session_start hook 写入）
    project_dir = find_project_root()
    session_file = project_dir / ".harness" / "session_id"
    try:
        if session_file.exists():
            sid = session_file.read_text(encoding="utf-8").strip()
            if sid:
                return sid
    except Exception:
        pass

    return "unknown"


# ─── event → AuditEntry 映射 ─────────────────────────────

def _build_audit_entry(event: str, **kwargs) -> dict:
    """
    将扁平的 event + kwargs 映射为 AuditEntry 所需的结构化数据

    核心原则：每个 event 记录操作上下文，不只是状态。
    - compliance_scan: 记录具体违规规则和发现
    - pii_detected: 记录 PII 类型和位置（脱敏）
    - skill_execute: 记录触发的插槽和上下文
    - gate_check: 记录每项检查结果
    - deploy: 记录部署的 hooks 和 gates 详情
    - session_stop: 记录变更文件列表
    - hook_execute: 记录触发来源
    """
    session_id = _resolve_session_id(kwargs.get("session_id"))
    timestamp = datetime.now()

    # 通用字段
    entry_data = {
        "timestamp": timestamp,
        "task": kwargs.get("task", ""),
        "session_id": session_id,
        "agent_id": kwargs.get("agent_id", event),
        "decisions": [],
        "actions": [],
        "outcomes": {},
        "risk_assessment": None,
        "escalation_history": [],
    }

    # ─── compliance_scan: 文件级合规扫描 ──────────────────────
    if event == "compliance_scan":
        file_path = kwargs.get("file_path", "")
        tool_name = kwargs.get("tool_name", "")
        violations = kwargs.get("violations") or []

        entry_data["task"] = "合规扫描: {}".format(file_path)
        entry_data["agent_id"] = "compliance-scan"
        entry_data["decisions"] = [{
            "reasoning": "PostToolUse 合规扫描触发" + ("，由 {} 操作触发".format(tool_name) if tool_name else ""),
            "action": "compliance_scan",
            "confidence": 1.0 if not violations else 0.8,
            "timestamp": timestamp.isoformat(),
        }]
        entry_data["actions"] = [{
            "tool": tool_name or "unknown",
            "input": file_path,
            "output": "{} 项违规".format(len(violations)) if violations else "通过",
            "duration_ms": kwargs.get("duration_ms", 0),
        }]
        entry_data["outcomes"] = {
            "file_path": file_path,
            "tool_name": tool_name,
            "violations_count": len(violations),
            "severity": kwargs.get("severity", ""),
            "violations": violations,  # [{rule_id, severity, finding, remediation}]
        }

    # ─── pii_detected: PII 检测 ──────────────────────────────
    elif event == "pii_detected":
        direction = kwargs.get("direction", "output")
        pii_types = kwargs.get("pii_types") or []
        pii_findings = kwargs.get("pii_findings") or []
        command = kwargs.get("command", "")

        entry_data["task"] = "PII 检测: {} 方向".format(direction)
        entry_data["agent_id"] = "guardrails-pii"
        entry_data["decisions"] = [{
            "reasoning": "Bash 输出 PII 检测" if direction == "output" else "输入 PII 检测",
            "action": "pii_detected",
            "confidence": 0.9,
            "timestamp": timestamp.isoformat(),
        }]
        entry_data["actions"] = [{
            "tool": "Bash",
            "input": command[:200] if command else "",
            "output": "发现 {} 个 PII".format(len(pii_findings)) if pii_findings else "无 PII",
            "duration_ms": kwargs.get("duration_ms", 0),
        }]
        entry_data["outcomes"] = {
            "direction": direction,
            "pii_count": kwargs.get("pii_count", 0),
            "pii_types": pii_types,
            "pii_findings": pii_findings,  # [{type, position}]（脱敏，不含原始匹配值）
        }

    # ─── skill_execute: Skill 执行 ──────────────────────────
    elif event == "skill_execute":
        skill_id = kwargs.get("skill_id", "")
        slot = kwargs.get("slot", "")
        trigger_node = kwargs.get("trigger_node", "")
        status = kwargs.get("status", "success")

        entry_data["task"] = "执行 Skill: {}".format(skill_id)
        entry_data["agent_id"] = skill_id
        entry_data["decisions"] = [{
            "reasoning": "Skill 在 {} 插槽触发执行".format(slot) if slot else "Skill 执行",
            "action": skill_id,
            "confidence": 1.0 if status == "completed" or status == "success" else 0.5,
            "timestamp": timestamp.isoformat(),
        }]
        entry_data["actions"] = [{
            "tool": "skill",
            "input": skill_id,
            "output": status,
            "duration_ms": kwargs.get("duration_ms", 0),
        }]
        entry_data["outcomes"] = {
            "skill_id": skill_id,
            "status": status,
            "duration_ms": kwargs.get("duration_ms", 0),
            "slot": slot,
            "trigger_node": trigger_node,
            "error": kwargs.get("error"),
        }

    # ─── gate_check: 门禁检查 ──────────────────────────────
    elif event == "gate_check":
        gate_id = kwargs.get("gate_id", "")
        passed = kwargs.get("passed", False)
        gate_mode = kwargs.get("gate_mode", "")
        check_results = kwargs.get("check_results") or []

        entry_data["task"] = "门禁检查: {}".format(gate_id)
        entry_data["agent_id"] = gate_id
        entry_data["decisions"] = [{
            "reasoning": "门禁模式={}, {}项检查, 结果={}".format(
                gate_mode, len(check_results), "通过" if passed else "未通过"
            ),
            "action": "gate_check",
            "confidence": 1.0 if passed else 0.5,
            "timestamp": timestamp.isoformat(),
        }]
        entry_data["outcomes"] = {
            "gate_id": gate_id,
            "passed": passed,
            "gate_mode": gate_mode,
            "check_results": check_results,  # [{check_id, passed, severity, message}]
        }

    # ─── deploy: Profile 部署 ──────────────────────────────
    elif event == "deploy":
        profile_name = kwargs.get("profile_name", "")
        adapter = kwargs.get("adapter", "")
        hooks_deployed = kwargs.get("hooks_deployed") or []
        gate_checks_detail = kwargs.get("gate_checks_detail") or []

        entry_data["task"] = "部署 Profile: {}".format(profile_name)
        entry_data["agent_id"] = "harness-bridge"
        entry_data["decisions"] = [{
            "reasoning": "Profile 部署到 {} 平台".format(adapter) if adapter else "Profile 部署",
            "action": "deploy",
            "confidence": 1.0,
            "timestamp": timestamp.isoformat(),
        }]
        entry_data["actions"] = [{
            "tool": "bridge",
            "input": profile_name,
            "output": "部署 {} 个 hooks, {} 个 gate checks".format(
                kwargs.get("hooks_count", 0), kwargs.get("gate_checks", 0)
            ),
            "duration_ms": kwargs.get("duration_ms", 0),
        }]
        entry_data["outcomes"] = {
            "profile_name": profile_name,
            "adapter": adapter,
            "hooks_count": kwargs.get("hooks_count", 0),
            "gate_checks": kwargs.get("gate_checks", 0),
            "hooks_deployed": hooks_deployed,  # [{hook_point, command}]
            "gate_checks_detail": gate_checks_detail,  # [{id, enabled}]
        }

    # ─── session_stop: 会话结束 ──────────────────────────────
    elif event == "session_stop":
        diff_summary = kwargs.get("diff_summary", "")
        files_changed = kwargs.get("files_changed") or []

        entry_data["task"] = "Session 结束"
        entry_data["agent_id"] = "session-stop"
        entry_data["decisions"] = [{
            "reasoning": "Claude Code session 结束，记录变更摘要",
            "action": "session_stop",
            "confidence": 1.0,
            "timestamp": timestamp.isoformat(),
        }]
        entry_data["outcomes"] = {
            "diff_summary": diff_summary[:500] if diff_summary else "",
            "files_changed": files_changed,  # ["file1.py", "file2.ts"]
        }

    # ─── hook_execute: Hook 执行 ──────────────────────────────
    elif event == "hook_execute":
        hook_name = kwargs.get("hook_name", "hook")
        hook_type = kwargs.get("hook_type", "")
        trigger = kwargs.get("trigger", {})

        entry_data["task"] = "Hook 执行: {}".format(hook_name)
        entry_data["agent_id"] = hook_name
        entry_data["decisions"] = [{
            "reasoning": "Hook 由 {} 事件触发".format(hook_type) if hook_type else "Hook 触发",
            "action": hook_name,
            "confidence": 1.0,
            "timestamp": timestamp.isoformat(),
        }]
        entry_data["actions"] = [{
            "tool": hook_type or "hook",
            "input": json.dumps(trigger, ensure_ascii=False)[:200] if trigger else "",
            "output": kwargs.get("status", ""),
            "duration_ms": kwargs.get("duration_ms", 0),
        }]
        entry_data["outcomes"] = {
            "hook_name": hook_name,
            "hook_type": hook_type,
            "status": kwargs.get("status", "success"),
            "duration_ms": kwargs.get("duration_ms", 0),
            "trigger": trigger,  # {tool_name, tool_input_summary}
        }

    # ─── 未知 event 类型 ──────────────────────────────────────
    else:
        entry_data["task"] = event
        entry_data["decisions"] = [{
            "reasoning": event,
            "action": event,
            "confidence": 1.0,
            "timestamp": timestamp.isoformat(),
        }]
        internal_keys = {"session_id", "task", "agent_id"}
        entry_data["outcomes"] = {
            k: v for k, v in kwargs.items()
            if k not in internal_keys
        }

    return entry_data


# ─── 主写入函数 ─────────────────────────────────────────

def write_audit_log(
    event: str,
    project_dir: Optional[str] = None,
    **kwargs
) -> Optional[str]:
    """
    写入审计日志

    统一走 AuditStore.save() → 自动获得 SHA-256 哈希链保护。
    如果 AuditStore 不可用，降级到扁平 JSON 写入。

    Args:
        event: 事件类型
        project_dir: 项目目录（默认从环境变量）
        **kwargs: 事件相关数据（各 event 类型有不同的推荐字段）

    Returns:
        写入的文件路径，失败返回 None
    """
    try:
        from harness.audit import AuditStore
        from harness.types import AuditEntry

        entry_data = _build_audit_entry(event, **kwargs)

        entry = AuditEntry(
            timestamp=entry_data["timestamp"],
            task=entry_data["task"],
            session_id=entry_data["session_id"],
            agent_id=entry_data["agent_id"],
            decisions=entry_data["decisions"],
            actions=entry_data["actions"],
            outcomes=entry_data["outcomes"],
            risk_assessment=entry_data["risk_assessment"],
            escalation_history=entry_data["escalation_history"],
        )

        store = AuditStore(project_dir=project_dir)
        filepath = store.save(entry)
        logger.debug(f"Audit log written via AuditStore: {filepath}")
        return filepath

    except ImportError:
        logger.debug("AuditStore not available, falling back to flat JSON write")
        return _write_flat_json(event, project_dir=project_dir, **kwargs)
    except Exception as e:
        logger.warning(f"AuditStore write failed: {e}, falling back to flat JSON write")
        return _write_flat_json(event, project_dir=project_dir, **kwargs)


def _write_flat_json(
    event: str,
    project_dir: Optional[str] = None,
    **kwargs
) -> Optional[str]:
    """
    降级写入：直接写扁平 JSON 文件（无 chain_hash）

    当 AuditStore 不可用时使用此方法。
    """
    root = Path(project_dir) if project_dir else find_project_root()
    audit_dir = root / ".harness" / "audit"

    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None

    timestamp = datetime.now().isoformat()
    safe_ts = timestamp.replace(":", "-").replace(".", "-")

    entry = {
        "timestamp": timestamp,
        "event": event,
        "session_id": _resolve_session_id(kwargs.get("session_id")),
        **kwargs,
    }

    filename = "session-{}-{}.json".format(safe_ts, event)
    filepath = audit_dir / filename

    try:
        filepath.write_text(
            json.dumps(entry, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(filepath)
    except Exception:
        return None


# ─── 便捷函数 ───────────────────────────────────────────

def log_hook_execute(
    hook_name: str,
    hook_type: str,
    status: str = "success",
    duration_ms: int = 0,
    trigger: dict = None,
    **kwargs,
) -> Optional[str]:
    """记录 hook 执行

    Args:
        hook_name: Hook 名称
        hook_type: Hook 类型（script/skill/prompt）
        status: 执行状态
        duration_ms: 执行耗时
        trigger: 触发来源上下文 {tool_name, tool_input_summary}
    """
    return write_audit_log(
        "hook_execute",
        hook_name=hook_name,
        hook_type=hook_type,
        status=status,
        duration_ms=duration_ms,
        trigger=trigger or {},
        **kwargs,
    )


def log_skill_execute(
    skill_id: str,
    status: str = "success",
    duration_ms: int = 0,
    slot: str = "",
    trigger_node: str = "",
    **kwargs,
) -> Optional[str]:
    """记录 skill 执行

    Args:
        skill_id: Skill ID
        status: 执行状态
        duration_ms: 执行耗时
        slot: 触发的插槽名称
        trigger_node: 触发的 DAG 节点 ID
    """
    return write_audit_log(
        "skill_execute",
        skill_id=skill_id,
        status=status,
        duration_ms=duration_ms,
        slot=slot,
        trigger_node=trigger_node,
        **kwargs,
    )


def log_gate_check(
    gate_id: str,
    passed: bool,
    gate_mode: str = "",
    check_results: list = None,
    **kwargs,
) -> Optional[str]:
    """记录 gate 检查

    Args:
        gate_id: Gate ID
        passed: 是否通过
        gate_mode: 门禁模式（strict/hybrid/loose）
        check_results: 各项检查结果 [{check_id, passed, severity, message}]
    """
    return write_audit_log(
        "gate_check",
        gate_id=gate_id,
        passed=passed,
        gate_mode=gate_mode,
        check_results=check_results or [],
        **kwargs,
    )


def log_deploy(
    profile_name: str,
    hooks_count: int,
    gate_checks: int,
    adapter: str = "",
    hooks_deployed: list = None,
    gate_checks_detail: list = None,
    **kwargs,
) -> Optional[str]:
    """记录 deploy 操作

    Args:
        profile_name: Profile 名称
        hooks_count: 部署的 hooks 数量
        gate_checks: gate checks 数量
        adapter: 目标适配器名称（如 claude-code）
        hooks_deployed: 部署的 hooks 详情 [{hook_point, command}]
        gate_checks_detail: gate checks 详情 [{id, enabled}]
    """
    return write_audit_log(
        "deploy",
        profile_name=profile_name,
        hooks_count=hooks_count,
        gate_checks=gate_checks,
        adapter=adapter,
        hooks_deployed=hooks_deployed or [],
        gate_checks_detail=gate_checks_detail or [],
        **kwargs,
    )


def log_compliance_scan(
    file_path: str,
    tool_name: str = "",
    violations: list = None,
    **kwargs,
) -> Optional[str]:
    """记录合规扫描结果

    Args:
        file_path: 被扫描的文件路径
        tool_name: 触发扫描的工具名（Write/Edit）
        violations: 违规详情 [{rule_id, severity, finding, remediation}]
    """
    violations = violations or []
    max_severity = ""
    if violations:
        severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        max_severity = max(
            (v.get("severity", "low") for v in violations),
            key=lambda s: severity_order.get(s, 0),
            default="low",
        )
    return write_audit_log(
        "compliance_scan",
        file_path=file_path,
        tool_name=tool_name,
        violations_count=len(violations),
        severity=max_severity,
        violations=violations,
        **kwargs,
    )


def log_pii_detected(
    pii_count: int,
    pii_types: list = None,
    direction: str = "output",
    command: str = "",
    pii_findings: list = None,
    **kwargs,
) -> Optional[str]:
    """记录 PII 检测结果

    Args:
        pii_count: PII 实例数量
        pii_types: PII 类型列表
        direction: 检测方向（input/output）
        command: 触发的 Bash 命令（截断到200字符）
        pii_findings: PII 发现详情 [{type, position}]（脱敏，不含原始值）
    """
    return write_audit_log(
        "pii_detected",
        pii_count=pii_count,
        pii_types=pii_types or [],
        direction=direction,
        command=command[:200] if command else "",
        pii_findings=pii_findings or [],
        **kwargs,
    )


# ─── 旧数据迁移 ─────────────────────────────────────────

def migrate_legacy_logs(
    project_dir: Optional[str] = None,
    delete_originals: bool = False,
) -> dict:
    """
    将旧的扁平 session-*.json 迁移到 AuditStore 层级化存储

    Args:
        project_dir: 项目目录
        delete_originals: 是否删除原始扁平文件（默认保留）

    Returns:
        迁移结果摘要
    """
    from harness.audit import AuditStore
    from harness.types import AuditEntry

    root = Path(project_dir) if project_dir else find_project_root()
    audit_dir = root / ".harness" / "audit"

    result = {
        "migrated": 0,
        "skipped": 0,
        "errors": 0,
        "details": [],
    }

    if not audit_dir.exists():
        return result

    for filepath in sorted(audit_dir.glob("session-*.json")):
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            event = data.get("event", "unknown")
            timestamp_str = data.get("timestamp", "")
            session_id = data.get("session_id", "unknown")

            try:
                timestamp = datetime.fromisoformat(timestamp_str)
            except (ValueError, TypeError):
                timestamp = datetime.now()

            entry = AuditEntry(
                timestamp=timestamp,
                task=data.get("task", event),
                session_id=session_id,
                agent_id=data.get("agent_id", data.get("skill_id", data.get("hook_name", event))),
                decisions=[{
                    "reasoning": "Migrated from legacy flat log",
                    "action": event,
                    "confidence": 1.0,
                    "timestamp": timestamp_str,
                }],
                actions=[],
                outcomes={k: v for k, v in data.items()
                          if k not in {"timestamp", "session_id", "event", "task", "agent_id",
                                       "decisions", "actions", "outcomes", "risk_assessment",
                                       "escalation_history", "chain_hash"}},
                risk_assessment=None,
                escalation_history=[],
            )

            store = AuditStore(project_dir=str(root))
            new_path = store.save(entry)

            result["migrated"] += 1
            result["details"].append({
                "original": str(filepath),
                "new": new_path,
                "event": event,
            })

            if delete_originals:
                filepath.unlink()

        except Exception as e:
            result["errors"] += 1
            result["details"].append({
                "original": str(filepath),
                "error": str(e),
            })

    logger.info(
        f"Migration complete: {result['migrated']} migrated, "
        f"{result['skipped']} skipped, {result['errors']} errors"
    )
    return result

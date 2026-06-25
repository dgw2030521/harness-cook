"""
harness-cook Dashboard API Server

提供 REST API 供前端获取:
  - Hook 执行统计 (次数/成功率/分布)
  - 审计记录搜索 (操作溯源)
  - 合规扫描结果
  - 注册表状态 (已注册 Agent 列表)
  - 门禁检查历史 (通过率/详情)
  - 事件总线最近事件流
  - Profile 状态 (hooks/gates 配置)
  - Deploy 历史 (部署记录)

启动: python -m packages.dashboard.app
或:   python packages/dashboard/app.py
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── PYTHONPATH 设置 ──
_HARNESS_ROOT = Path(__file__).resolve().parent.parent.parent
_CORE_DIR = _HARNESS_ROOT / "packages" / "core"
if str(_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(_CORE_DIR))

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from harness.audit import AuditEngine, AuditStore, AuditStats
from harness.bus import EventBus
from harness.compliance import ComplianceEngine, ComplianceCategory
from harness.config import HarnessConfig
from harness.gates import GateEngine, GateMode
from harness.registry import AgentRegistry, AgentRecord
from harness.types import (
    AuditEntry,
    BusEvent,
    BusEventType,
    CheckResult,
    ComplianceResult,
    ComplianceRule,
)


# ── 全局实例 (延迟初始化) ─
_config: Optional[HarnessConfig] = None
_registry: Optional[AgentRegistry] = None
_audit_engine: Optional[AuditEngine] = None
_audit_store: Optional[AuditStore] = None
_compliance_engine: Optional[ComplianceEngine] = None
_gate_engine: Optional[GateEngine] = None
_bus: Optional[EventBus] = None


def _init_instances() -> None:
    """初始化所有 harness 核心组件——必须有项目级 .harness 才初始化

    Dashboard 所有数据来自 .harness/ 目录。没有项目级 .harness 时，
    核心组件不会被初始化，API 端点将返回空数据或提示未激活。
    """
    global _config, _registry, _audit_engine, _audit_store
    global _compliance_engine, _gate_engine, _bus

    if _config is not None:
        return

    project_dir = _get_project_dir()
    if project_dir is None:
        # 没有 .harness → 不初始化核心组件，API 返回"项目未激活"
        return

    _config = HarnessConfig(project_path=project_dir)
    _bus = EventBus()
    _registry = AgentRegistry(bus=_bus)
    _audit_store = AuditStore(project_dir=project_dir)
    _audit_engine = AuditEngine(store=_audit_store, bus=_bus)
    _compliance_engine = ComplianceEngine(bus=_bus)
    _gate_engine = GateEngine(bus=_bus)


def _get_project_dir() -> str | None:
    """获取项目根目录——必须有项目级 .harness 才返回路径

    优先级：
      1. HARNESS_PROJECT_DIR 环境变量（CLI harness dashboard 传入）
      2. CLAUDE_PROJECT_DIR 环境变量（Claude Code 场景）
      3. 从 cwd 向上查找含 .harness/ 的目录（排除 home 目录）

    关键设计：
      - 所有 Dashboard 数据（审计、Profile、知识库）来自 .harness/
      - 没有 .harness → 没有数据 → 返回 None，API 端点应返回空数据而非假数据
      - 排除 home 目录的 .harness（~/.harness 是全局配置）

    Returns:
        项目根目录路径，或 None（无项目级 .harness）
    """
    home_dir = Path.home().resolve()

    # 1. CLI 显式传入的项目目录（最高优先级）
    cli_dir = os.environ.get("HARNESS_PROJECT_DIR")
    if cli_dir and Path(cli_dir).exists():
        if (Path(cli_dir) / ".harness").is_dir() and Path(cli_dir).resolve() != home_dir:
            return cli_dir
        return None

    # 2. Claude Code 项目目录
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_dir and Path(env_dir).exists():
        if (Path(env_dir) / ".harness").is_dir() and Path(env_dir).resolve() != home_dir:
            return env_dir
        return None

    # 3. 从 cwd 向上查找含 .harness/ 的目录（排除 home 目录）
    current = Path.cwd().resolve()
    for parent in [current] + list(current.parents):
        if parent == home_dir:
            break  # 到达 home 目录就停止，不匹配 ~/.harness
        if (parent / ".harness").is_dir():
            return str(parent)

    # 没有找到项目级 .harness
    return None


def _read_deployed_hooks(project_dir: str) -> dict:
    """读取实际部署的 hooks 配置

    优先级：settings.local.json > settings.json
    """
    claude_dir = Path(project_dir) / ".claude"

    for filename in ["settings.local.json", "settings.json"]:
        settings_path = claude_dir / filename
        if settings_path.exists():
            try:
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
                hooks = settings.get("hooks", {})
                if hooks:
                    return hooks
            except (json.JSONDecodeError, Exception):
                continue

    return {}


def _merge_hooks(profile_hooks: dict, deployed_hooks: dict) -> dict:
    """合并 Profile 声明的 hooks 和实际部署的 hooks

    策略：
    - 实际部署的 hooks 优先（代表当前生效状态）
    - Profile 声明但未部署的 hooks 补充进来（标注 _source: "profile" 标记）
    - 使用适配器的 HOOK_POINT_MAP 做 snake_case → PascalCase 映射
    """
    try:
        from harness.adapters.claude_code import HOOK_POINT_MAP
    except ImportError:
        HOOK_POINT_MAP = {
            "session_start": "SessionStart",
            "session_end": "Stop",
            "pre_tool_use": "PreToolUse",
            "post_tool_use": "PostToolUse",
            "user_prompt_submit": "UserPromptSubmit",
            "pre_execute": "PreToolUse",
            "post_execute": "PostToolUse",
            "on_file_change": "PostToolUse",
        }

    # 反向映射：PascalCase → snake_case（用于检测部署的 hook 是否来自 Profile 声明）
    reverse_map: dict[str, list[str]] = {}
    for snake, pascal in HOOK_POINT_MAP.items():
        reverse_map.setdefault(pascal, []).append(snake)

    # 1. 收集已部署的 hooks 中，哪些 Profile hook 点已被覆盖
    covered_profile_points: set[str] = set()
    for pascal_point in deployed_hooks:
        for snake_point in reverse_map.get(pascal_point, []):
            covered_profile_points.add(snake_point)

    # 2. 先放部署的 hooks（实际生效）
    merged = {}
    for point, hook_groups in deployed_hooks.items():
        merged[point] = hook_groups

    # 3. 补充 Profile 声明但未部署的
    for snake_point, hook_list in profile_hooks.items():
        if snake_point in covered_profile_points:
            continue  # 已有部署版本，跳过

        pascal_point = HOOK_POINT_MAP.get(snake_point)
        if not pascal_point:
            continue

        # 如果 PascalCase 点也未部署，补充 Profile 声明
        if pascal_point not in merged and isinstance(hook_list, list) and hook_list:
            wrapped_hooks = []
            for h in hook_list:
                if isinstance(h, dict):
                    hook_type = h.get("type", "script")
                    if hook_type == "script":
                        wrapped_hooks.append({
                            "type": "command",
                            "command": h.get("command", ""),
                        })
                    elif hook_type == "skill":
                        wrapped_hooks.append({
                            "type": "skill",
                            "skill_id": h.get("skill_id", ""),
                        })
                    elif hook_type == "prompt":
                        wrapped_hooks.append({
                            "type": "prompt",
                            "message": h.get("message", ""),
                        })
            if wrapped_hooks:
                merged[pascal_point] = [{"matcher": "", "hooks": wrapped_hooks, "_source": "profile"}]

    return merged


# ── HTML 前端 ──
_DASHBOARD_HTML = Path(__file__).resolve().parent / "frontend.html"


# ── FastAPI App ──
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app_instance):
    _init_instances()
    yield

app = FastAPI(
    title="harness-cook Dashboard",
    version="0.1.0",
    description="Agent Harness 可视化观测界面",
    lifespan=lifespan,
)


@app.get("/", response_class=HTMLResponse)
async def dashboard_page():
    """返回 Dashboard HTML 前端"""
    if not _DASHBOARD_HTML.exists():
        return HTMLResponse(
            "<h1>Dashboard HTML not found</h1>"
            "<p>Please ensure frontend.html exists in packages/dashboard/</p>"
        )
    return HTMLResponse(_DASHBOARD_HTML.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════
# REST API 端点
# ═══════════════════════════════════════════════════

@app.get("/api/stats", summary="Hook 执行统计概览")
async def get_stats() -> Dict[str, Any]:
    """返回 Hook 执行统计: 总执行数/成功率/按类型分布/Gate 通过率"""
    all_entries = _audit_store.search(query="", limit=1000)

    # ── Hook 执行统计 ──
    hook_entries = [
        e for e in all_entries
        if e.agent_id in ("hook-session-init", "hook-task-audit", "run-skill",
                          "session-start", "session-stop", "post-tool-use",
                          "session_stop")
        or "hook" in e.agent_id.lower()
        or "Hook" in e.task
        or "hook" in e.task.lower()
    ]

    total_hook_executions = len(hook_entries)
    successful_hooks = sum(
        1 for e in hook_entries
        if e.outcomes.get("status") in ("success", "completed") or not e.outcomes.get("error")
    )
    hook_success_rate = (successful_hooks / total_hook_executions) if total_hook_executions else 0.0

    # 按 hook 类型分布
    hook_by_type: dict[str, int] = {}
    for e in hook_entries:
        hook_type = e.outcomes.get("hook_type", e.outcomes.get("trigger", {}).get("tool_name", "unknown"))
        if not hook_type:
            hook_type = e.agent_id
        hook_by_type[hook_type] = hook_by_type.get(hook_type, 0) + 1

    # ── Gate 通过率统计 ──
    gate_entries = [e for e in all_entries if "gate" in e.agent_id.lower() or "gate" in e.task.lower() or e.outcomes.get("gate_id")]
    total_gate_checks = len(gate_entries)
    passed_gate_checks = sum(1 for e in gate_entries if e.outcomes.get("passed", False))
    gate_pass_rate = (passed_gate_checks / total_gate_checks) if total_gate_checks else 0.0

    # ── 部署的 Hooks 数量 ──
    project_dir = _get_project_dir()
    deployed_hooks = _read_deployed_hooks(project_dir)
    deployed_hook_count = sum(len(v) for v in deployed_hooks.values()) if deployed_hooks else 0

    # ── 审计记录总数 ─
    audit_count = len(all_entries)

    # ── 合规扫描统计 ──
    compliance_entries = [e for e in all_entries if "compliance" in e.agent_id.lower() or "合规" in e.task]
    compliance_scans = len(compliance_entries)
    compliance_violations = sum(
        e.outcomes.get("violations_count", 0)
        for e in compliance_entries
    )

    return {
        "total_hook_executions": total_hook_executions,
        "hook_success_rate": hook_success_rate,
        "hook_by_type": hook_by_type,
        "deployed_hook_count": deployed_hook_count,
        "gate_pass_rate": gate_pass_rate,
        "total_gate_checks": total_gate_checks,
        "audit_count": audit_count,
        "compliance_scans": compliance_scans,
        "compliance_violations": compliance_violations,
    }


@app.get("/api/audit/search", summary="审计记录搜索")
async def search_audit(
    query: str = Query("", description="搜索关键词"),
    agent_id: Optional[str] = Query(None, description="Agent ID 过滤"),
    limit: int = Query(20, description="最大返回数"),
) -> List[Dict[str, Any]]:
    """搜索审计记录: 决策链、行动链、风险评估、升级历史"""
    entries = _audit_store.search(query=query, agent_id=agent_id, limit=limit)
    results = []
    for entry in entries:
        results.append({
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
            "session_id": entry.session_id,
            "agent_id": entry.agent_id,
            "task": entry.task,
            "decisions": entry.decisions,
            "actions": entry.actions,
            "outcomes": entry.outcomes,
            "risk_assessment": entry.risk_assessment,
            "escalation_history": entry.escalation_history,
        })
    return results


@app.get("/api/audit/session/{session_id}", summary="按 session 查看审计")
async def get_audit_session(session_id: str) -> List[Dict[str, Any]]:
    """按 session_id 加载完整审计记录"""
    entries = _audit_store.load(session_id=session_id)
    results = []
    for entry in entries:
        results.append({
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
            "session_id": entry.session_id,
            "agent_id": entry.agent_id,
            "task": entry.task,
            "decisions": entry.decisions,
            "actions": entry.actions,
            "outcomes": entry.outcomes,
            "risk_assessment": entry.risk_assessment,
        })
    return results


@app.get("/api/agents", summary="注册表 Agent 列表")
async def list_agents() -> List[Dict[str, Any]]:
    """返回所有已注册 Agent 的定义与状态"""
    records = _registry.list_all()
    results = []
    for record in records:
        defn = record.definition
        results.append({
            "id": record.id,
            "name": defn.name if defn else "unknown",
            "capabilities": [c.value for c in (defn.capabilities or [])] if defn else [],
            "agent_type": defn.agent_type.value if defn and defn.agent_type else None,
            "is_ready": record.is_ready,
            "task_count": record.task_count,
            "error_count": record.error_count,
            "last_used": record.last_used,
        })
    return results


@app.get("/api/compliance/scan", summary="合规扫描")
async def compliance_scan(
    content: str = Query("", description="待扫描内容文本"),
    categories: str = Query("security,privacy", description="合规类别(逗号分隔)"),
) -> List[Dict[str, Any]]:
    """对指定内容执行合规扫描"""
    from harness.types import Artifact

    artifact = Artifact(type="code", path="scan_input", content=content)
    cat_list = []
    for c in categories.split(","):
        c_strip = c.strip()
        try:
            cat_list.append(ComplianceCategory(c_strip))
        except ValueError:
            pass

    if not cat_list:
        cat_list = [ComplianceCategory.SECURITY, ComplianceCategory.PRIVACY]

    results = _compliance_engine.scan(
        artifacts=[artifact], categories=cat_list
    )
    output = []
    for r in results:
        output.append({
            "rule_id": r.rule_id,
            "passed": r.passed,
            "severity": r.severity,
            "findings": r.findings,
            "remediation": r.remediation,
            "locations": r.locations,
        })
    return output


@app.get("/api/compliance/rules", summary="合规规则列表")
async def list_compliance_rules() -> Dict[str, Any]:
    """列出所有合规规则包及其规则"""
    pack_names = _compliance_engine.list_packs()
    result = {}
    for pack_name in pack_names:
        pack = _compliance_engine.get_pack(pack_name)
        if pack is None:
            continue
        rules_info = []
        for rule in pack.rules:
            rules_info.append({
                "id": rule.id,
                "category": rule.category.value,
                "pattern": rule.pattern,
                "severity": rule.severity,
                "description": rule.description,
                "remediation": rule.remediation,
                "auto_fixable": rule.auto_fixable,
                "languages": rule.languages,
            })
        result[pack_name] = {
            "category": pack.category.value,
            "rules_count": len(rules_info),
            "rules": rules_info,
        }
    return result


@app.get("/api/events", summary="最近事件流")
async def recent_events(
    limit: int = Query(50, description="最大返回数"),
    event_type: Optional[str] = Query(None, description="事件类型过滤"),
) -> List[Dict[str, Any]]:
    """返回事件总线最近事件"""
    events = _bus.get_history(limit=limit)
    if event_type:
        try:
            et = BusEventType(event_type)
            events = [e for e in events if e.type == et]
        except ValueError:
            pass

    results = []
    for event in events:
        results.append({
            "type": event.type.value,
            "execution_id": event.execution_id,
            "node_id": event.node_id,
            "agent_id": event.agent_id,
            "data": event.data,
            "timestamp": event.timestamp.isoformat() if event.timestamp else None,
        })
    return results


@app.get("/api/gates/history", summary="门禁检查历史")
async def gate_history(
    limit: int = Query(30, description="最大返回数"),
) -> List[Dict[str, Any]]:
    """返回门禁检查历史记录"""
    entries = _audit_store.search(query="gate", limit=limit)
    results = []
    for entry in entries:
        gate_info = []
        for action in entry.actions:
            if "gate" in str(action.get("tool", "")).lower():
                gate_info.append(action)
        if gate_info or entry.outcomes.get("gate_id"):
            results.append({
                "session_id": entry.session_id,
                "agent_id": entry.agent_id,
                "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                "gate_id": entry.outcomes.get("gate_id", ""),
                "passed": entry.outcomes.get("passed", False),
                "gate_mode": entry.outcomes.get("gate_mode", ""),
                "check_results": entry.outcomes.get("check_results", []),
                "gate_actions": gate_info,
            })
    return results


@app.get("/api/hooks/executions", summary="Hook 执行历史")
async def hook_executions(
    limit: int = Query(30, description="最大返回数"),
    hook_type: Optional[str] = Query(None, description="Hook 类型过滤"),
) -> List[Dict[str, Any]]:
    """返回 Hook 执行历史记录"""
    all_entries = _audit_store.search(query="", limit=2000)

    # 与 /api/stats 使用相同的过滤逻辑
    hook_entries = [
        e for e in all_entries
        if e.agent_id in ("hook-session-init", "hook-task-audit", "run-skill",
                          "session-start", "session-stop", "post-tool-use",
                          "session_stop")
        or "hook" in e.agent_id.lower()
        or "Hook" in e.task
        or "hook" in e.task.lower()
    ]

    if hook_type:
        hook_entries = [
            e for e in hook_entries
            if hook_type.lower() in e.agent_id.lower()
            or hook_type.lower() in e.task.lower()
            or hook_type.lower() in e.outcomes.get("hook_type", "").lower()
        ]

    results = []
    for entry in hook_entries[:limit]:
        results.append({
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
            "session_id": entry.session_id,
            "hook_name": entry.agent_id,
            "hook_type": entry.outcomes.get("hook_type", entry.actions[0].get("tool", "") if entry.actions else ""),
            "status": entry.outcomes.get("status", "unknown"),
            "duration_ms": entry.outcomes.get("duration_ms", entry.actions[0].get("duration_ms", 0) if entry.actions else 0),
            "trigger": entry.outcomes.get("trigger", {}),
            "task": entry.task,
        })

    return results


# ═══════════════════════════════════════════════════
# 知识库 API (Knowledge)
# ═══════════════════════════════════════════════════

@app.get("/api/knowledge/stats", summary="知识库统计概览")
async def knowledge_stats(project: str = Query("default", description="项目名")) -> Dict[str, Any]:
    """知识库统计概览——活跃层+归档层+类型分布+来源分布"""
    try:
        from harness.knowledge import get_knowledge_provider
        provider = get_knowledge_provider(project)
        return provider.stats()
    except Exception as e:
        return {"error": str(e), "total_entries": 0}


@app.get("/api/knowledge/list", summary="知识条目列表")
async def knowledge_list(
    project: str = Query("default", description="项目名"),
    type: Optional[str] = Query(None, description="按类型过滤"),
    scope: Optional[str] = Query(None, description="按作用域过滤"),
    tags: Optional[str] = Query(None, description="按标签过滤(逗号分隔)"),
    source: Optional[str] = Query(None, description="按来源过滤"),
    limit: int = Query(20, description="返回条数"),
) -> Dict[str, Any]:
    """列出知识条目——支持类型/作用域/标签/来源过滤"""
    try:
        from harness.knowledge import get_knowledge_provider, KnowledgeQuery, KnowledgeType, KnowledgeScope

        provider = get_knowledge_provider(project)

        # 构建过滤条件
        type_filter = None
        if type:
            type_map = {kt.value: kt for kt in KnowledgeType}
            type_filter = type_map.get(type)

        scope_filter = None
        if scope:
            scope_map = {ks.value: ks for ks in KnowledgeScope}
            scope_filter = scope_map.get(scope)

        tags_filter = None
        if tags:
            tags_filter = tags.split(",")

        query_obj = KnowledgeQuery(
            query="",
            type_filter=type_filter,
            scope_filter=scope_filter,
            tags_filter=tags_filter,
            source_filter=source,
            limit=limit,
        )

        result = provider.query(query_obj)
        return {
            "entries": [
                {
                    "id": e.id, "type": e.type.value, "scope": e.scope.value,
                    "title": e.title, "content": e.content[:200],
                    "tags": e.tags, "confidence": e.confidence,
                    "source": e.source, "created_at": e.created_at,
                    "hit_count": e.metadata.get("hit_count", 1),
                }
                for e in result.entries
            ],
            "total_matches": result.total_matches,
            "search_method": result.search_method,
        }
    except Exception as e:
        return {"error": str(e), "entries": [], "total_matches": 0}


@app.get("/api/knowledge/search", summary="关键词搜索")
async def knowledge_search(
    q: str = Query(..., description="搜索关键词"),
    project: str = Query("default", description="项目名"),
    type: Optional[str] = Query(None, description="按类型过滤"),
    limit: int = Query(20, description="返回条数"),
) -> Dict[str, Any]:
    """关键词搜索知识条目"""
    try:
        from harness.knowledge import get_knowledge_provider, KnowledgeQuery, KnowledgeType

        provider = get_knowledge_provider(project)

        type_filter = None
        if type:
            type_map = {kt.value: kt for kt in KnowledgeType}
            type_filter = type_map.get(type)

        query_obj = KnowledgeQuery(query=q, type_filter=type_filter, limit=limit)
        result = provider.query(query_obj)

        return {
            "entries": [
                {
                    "id": e.id, "type": e.type.value, "title": e.title,
                    "content": e.content[:200], "confidence": e.confidence,
                    "source": e.source, "tags": e.tags,
                }
                for e in result.entries
            ],
            "total_matches": result.total_matches,
            "search_method": result.search_method,
        }
    except Exception as e:
        return {"error": str(e), "entries": [], "total_matches": 0}


@app.get("/api/knowledge/semantic", summary="TF-IDF 语义搜索")
async def knowledge_semantic(
    q: str = Query(..., description="语义搜索关键词"),
    project: str = Query("default", description="项目名"),
    limit: int = Query(20, description="返回条数"),
) -> Dict[str, Any]:
    """TF-IDF 语义搜索知识条目"""
    try:
        from harness.knowledge import get_knowledge_provider

        provider = get_knowledge_provider(project)
        result = provider.semantic_search(q, limit=limit)

        return {
            "entries": [
                {
                    "id": e.id, "type": e.type.value, "title": e.title,
                    "content": e.content[:200], "confidence": e.confidence,
                    "source": e.source, "tags": e.tags,
                }
                for e in result.entries
            ],
            "total_matches": result.total_matches,
            "search_method": result.search_method,
        }
    except Exception as e:
        return {"error": str(e), "entries": [], "total_matches": 0}


@app.post("/api/knowledge/evict", summary="触发知识淘汰")
async def knowledge_evict(project: str = Query("default", description="项目名")) -> Dict[str, Any]:
    """触发知识淘汰——30天未查询→归档，90天+低频→删除"""
    try:
        from harness.knowledge import get_knowledge_provider

        provider = get_knowledge_provider(project)
        result = provider.evict_stale_entries()
        return result
    except Exception as e:
        return {"error": str(e), "archived": 0, "deleted": 0}


@app.get("/api/knowledge/types", summary="知识类型+作用域枚举")
async def knowledge_types() -> Dict[str, Any]:
    """展示 10 种知识类型 + 4 级作用域"""
    try:
        from harness.knowledge import KnowledgeType, KnowledgeScope
        return {
            "knowledge_types": [
                {"name": kt.name, "value": kt.value} for kt in KnowledgeType
            ],
            "knowledge_scopes": [
                {"name": ks.name, "value": ks.value} for ks in KnowledgeScope
            ],
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/health", summary="Dashboard 健康检查")
async def dashboard_health() -> Dict[str, Any]:
    """Dashboard 主健康检查端点——前端右上角状态指示器调用"""
    project_dir = _get_project_dir()
    if project_dir is None:
        return {
            "status": "not_initialized",
            "project_name": None,
            "project_dir": None,
            "message": "当前项目未激活 harness，请先执行 harness activate",
        }

    deployed_hooks = _read_deployed_hooks(project_dir)
    hook_count = sum(len(v) for v in deployed_hooks.values()) if deployed_hooks else 0
    project_name = Path(project_dir).name

    return {
        "status": "healthy",
        "project_name": project_name,
        "project_dir": project_dir,
        "harness_initialized": _config is not None,
        "hooks_deployed": hook_count,
        "agents_registered": len(_registry.list_all()),
        "audit_entries": len(_audit_store.search(query="", limit=1)),
        "timestamp": datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════
# VSCode 扩展契约端点
# 对齐 packages/vscode-extension/src/extension.js 的调用契约。
# /api/scan、/api/audit/verify、/api/rollback/* 真实可用（引擎已存在）；
# /api/report/dependency-graph、/api/call-graph、/api/taint 依赖 codegraph
# MCP（独立 MCP server，Dashboard 不重复实现），返回 501 明确引导。
# ═══════════════════════════════════════════════════

@app.post("/api/scan", summary="合规扫描（VSCode 扩展契约：按文件路径）")
async def vscode_scan(request: Request) -> Dict[str, Any]:
    """VSCode harness-cook.scan 命令端点。

    请求体: {"file_path": str, "language": str}
    响应: {"results": [{rule_id, passed, severity, findings, locations, remediation}]}
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    file_path = body.get("file_path") if isinstance(body, dict) else None
    if not file_path or not Path(file_path).exists():
        raise HTTPException(status_code=404, detail="File not found: {}".format(file_path))
    try:
        content = Path(file_path).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise HTTPException(status_code=500, detail="Read file failed: {}".format(e))

    if _compliance_engine is None:
        raise HTTPException(
            status_code=503,
            detail="Project not activated: no .harness directory found",
        )
    from harness.types import Artifact
    artifact = Artifact(type="code", path=file_path, content=content)
    results = _compliance_engine.scan(
        artifacts=[artifact],
        categories=[ComplianceCategory.SECURITY, ComplianceCategory.PRIVACY],
    )
    return {"results": [
        {
            "rule_id": r.rule_id,
            "passed": r.passed,
            "severity": r.severity,
            "findings": r.findings,
            "locations": r.locations,
            "remediation": r.remediation,
        }
        for r in results
    ]}


@app.get("/api/audit/verify", summary="审计链完整性验证（VSCode 扩展契约）")
async def vscode_audit_verify() -> Dict[str, Any]:
    """VSCode harness-cook.showAuditChain 命令端点。

    响应: {"valid": bool, "entries": int, "last_hash": str, "broken_at": Optional[int]}
    """
    if _audit_store is None:
        raise HTTPException(
            status_code=503,
            detail="Project not activated: no .harness directory found",
        )
    report = _audit_store.verify_chain()
    tampered = report.get("tampered", [])
    broken = report.get("broken_links", [])
    broken_at = None
    if broken:
        broken_at = broken[0].get("index")
    elif tampered:
        broken_at = tampered[0].get("index")
    last_hash = tampered[0].get("actual_hash", "") if tampered else ""
    return {
        "valid": report.get("valid", False),
        "entries": report.get("verified_records", 0),
        "last_hash": last_hash,
        "broken_at": broken_at,
    }


@app.post("/api/rollback/snapshot", summary="创建回滚快照（VSCode 扩展契约）")
async def vscode_rollback_snapshot(request: Request) -> Dict[str, Any]:
    """VSCode harness-cook.rollbackSnapshot 命令端点。

    请求体: {"file_paths": [str]}
    响应: {"snapshot_id": str}
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    file_paths = body.get("file_paths", []) if isinstance(body, dict) else []
    if not file_paths:
        raise HTTPException(status_code=400, detail="file_paths required")

    try:
        from harness.rollback import RollbackEngine
        engine = RollbackEngine()
        snap = engine.create_snapshot(
            execution_id="vscode-manual",
            node_id="vscode",
            file_paths=file_paths,
        )
        return {"snapshot_id": snap.snapshot_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Snapshot failed: {}".format(e))


@app.get("/api/rollback/list", summary="列出回滚快照（VSCode 扩展契约）")
async def vscode_rollback_list() -> Dict[str, Any]:
    """VSCode harness-cook.rollbackRestore 命令端点（第一步：列出快照）。

    响应: {"snapshots": [{snapshot_id, created_at, file_count}]}
    """
    try:
        from harness.rollback import RollbackEngine
        engine = RollbackEngine()
        snaps = engine.list_snapshots()
        return {"snapshots": [
            {
                "snapshot_id": s.snapshot_id,
                "created_at": datetime.fromtimestamp(s.created_at).strftime("%Y-%m-%d %H:%M:%S"),
                "file_count": len(s.snapshots),
            }
            for s in snaps
        ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail="List snapshots failed: {}".format(e))


@app.post("/api/rollback/restore", summary="恢复回滚快照（VSCode 扩展契约）")
async def vscode_rollback_restore(request: Request) -> Dict[str, Any]:
    """VSCode harness-cook.rollbackRestore 命令端点（第二步：恢复快照）。

    请求体: {"snapshot_id": str}
    响应: {"restored_files": int}
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    snapshot_id = body.get("snapshot_id") if isinstance(body, dict) else None
    if not snapshot_id:
        raise HTTPException(status_code=400, detail="snapshot_id required")

    try:
        from harness.rollback import RollbackEngine
        engine = RollbackEngine()
        result = engine.restore_snapshot(snapshot_id)
        if not result.success:
            raise HTTPException(
                status_code=500,
                detail="; ".join(result.errors) if result.errors else "Restore failed",
            )
        return {"restored_files": result.files_restored}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Restore failed: {}".format(e))


@app.get("/api/report/dependency-graph", summary="依赖图（需 codegraph MCP）")
async def vscode_dependency_graph(root: str = Query("", description="项目根目录")) -> Dict[str, Any]:
    """VSCode harness-cook.showDependencyGraph 命令端点。

    依赖图能力由 codegraph MCP（独立 MCP server）提供，Dashboard 不重复实现。
    """
    raise HTTPException(
        status_code=501,
        detail="Dependency graph is provided by the codegraph MCP server. "
               "Enable codegraph MCP in your Agent client to use this feature.",
    )


@app.post("/api/call-graph", summary="调用图（需 codegraph MCP）")
async def vscode_call_graph(request: Request) -> Dict[str, Any]:
    """VSCode harness-cook.showCallGraph 命令端点。

    调用图能力由 codegraph MCP 提供，Dashboard 不重复实现。
    """
    raise HTTPException(
        status_code=501,
        detail="Call graph is provided by the codegraph MCP server. "
               "Enable codegraph MCP to use this feature.",
    )


@app.post("/api/taint", summary="污点分析（需 codegraph MCP）")
async def vscode_taint(request: Request) -> Dict[str, Any]:
    """VSCode harness-cook.taintAnalysis 命令端点。

    污点分析能力由 codegraph MCP 提供，Dashboard 不重复实现。
    """
    raise HTTPException(
        status_code=501,
        detail="Taint analysis is provided by the codegraph MCP server. "
               "Enable codegraph MCP to use this feature.",
    )


@app.get("/api/knowledge/health", summary="知识库健康检查")
async def knowledge_health_check() -> Dict[str, Any]:
    """知识库子系统的健康检查——与 Dashboard 主健康检查复用逻辑"""
    project_dir = _get_project_dir()
    deployed_hooks = _read_deployed_hooks(project_dir)
    hook_count = sum(len(v) for v in deployed_hooks.values()) if deployed_hooks else 0
    project_name = Path(project_dir).name

    return {
        "status": "healthy",
        "project_name": project_name,
        "project_dir": project_dir,
        "harness_initialized": _config is not None,
        "hooks_deployed": hook_count,
        "agents_registered": len(_registry.list_all()),
        "audit_entries": len(_audit_store.search(query="", limit=1)),
        "timestamp": datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════
# Skills / Profiles / Deploys API (第一期新增)
# ═══════════════════════════════════════════════════

@app.get("/api/skills", summary="已注册 Skills 列表")
async def list_skills(
    slot: Optional[str] = Query(None, description="按插槽过滤"),
    tag: Optional[str] = Query(None, description="按标签过滤"),
) -> Dict[str, Any]:
    """返回所有已注册 Skill 及其插槽分配"""
    try:
        from harness.skill_registry import get_skill_registry, register_builtin_skills
        from harness.types import SkillSlotName

        registry = get_skill_registry()
        register_builtin_skills(registry)

        # 过滤
        if slot:
            try:
                slot_enum = SkillSlotName(slot)
                records = registry.find_by_slot(slot_enum)
            except ValueError:
                records = registry.list_active()
        elif tag:
            records = registry.find_by_tag(tag)
        else:
            records = registry.list_active()

        skills_list = []
        for r in records:
            skills_list.append({
                "id": r.definition.id,
                "name": r.definition.name,
                "description": r.definition.description,
                "slot": r.definition.slot.value,
                "tags": r.definition.tags,
                "active": r.active,
                "is_ready": r.is_ready,
                "exec_count": r.exec_count,
                "error_count": r.error_count,
                "last_used": r.last_used,
            })

        return {
            "total": len(skills_list),
            "skills": skills_list,
            "slots": registry.list_slots(),
        }
    except Exception as e:
        return {"total": 0, "skills": [], "error": str(e)}


@app.get("/api/profiles", summary="Profile 列表")
async def list_profiles(
    current: bool = Query(False, description="是否返回当前活跃 Profile 详情"),
) -> Dict[str, Any]:
    """返回所有可用 Profile 或当前活跃 Profile 详情"""
    try:
        from harness.config import list_profiles as _list_profiles
        from harness.config import load_profile, ProfileLoader

        if current:
            # 确定项目根目录
            project_dir = _get_project_dir()

            # 加载 Profile
            profiles_dir = str(Path(project_dir) / ".harness" / "profiles")
            profile = load_profile("default", profiles_dir=profiles_dir)

            # 读取实际部署的 settings（settings.local.json 优先，settings.json 兜底）
            deployed_hooks = _read_deployed_hooks(project_dir)

            # 合并 hooks（部署优先，Profile 声明补充）
            profile_hooks = profile.hooks or {}
            merged_hooks = _merge_hooks(profile_hooks, deployed_hooks)

            return {
                "active": profile.name,
                "description": profile.description,
                "default_agent": profile.default_agent,
                "pipeline_agents": profile.pipeline_agents,
                "hooks": merged_hooks,
                "hook_sources": {
                    "profile_declared": list(profile_hooks.keys()),
                    "deployed_active": list(deployed_hooks.keys()),
                },
                "skill_slots": profile.skill_slots,
                "default_gate_mode": profile.default_gate_mode.value,
                "gate_checks": profile.gate_checks,
            }
        else:
            # 返回所有 Profile 列表
            profiles = _list_profiles()
            return {
                "profiles": profiles,
                "total": len(profiles),
            }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"profiles": ["default"], "error": str(e)}


@app.get("/api/deploys", summary="Deploy 历史")
async def deploy_history(
    limit: int = Query(20, description="最大返回数"),
) -> List[Dict[str, Any]]:
    """返回 Bridge deploy 历史记录（从审计日志读取）"""
    try:
        from harness.audit import AuditStore

        store = AuditStore()
        entries = store.search(query="deploy", limit=limit)

        results = []
        for entry in entries:
            results.append({
                "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                "session_id": entry.session_id,
                "profile_name": entry.outcomes.get("profile_name", "unknown"),
                "hooks_count": entry.outcomes.get("hooks_count", 0),
                "gate_checks": entry.outcomes.get("gate_checks", 0),
            })

        return results
    except Exception as e:
        return []


# ── 新增监控指标 API ──

@app.get("/api/metrics/skill-execution", summary="Skill 执行统计")
async def skill_execution_metrics() -> Dict[str, Any]:
    """返回 Skill 执行统计信息"""
    try:
        from harness.skill_registry import get_skill_registry

        registry = get_skill_registry()
        stats = registry.stats()

        return {
            "total_skills": stats.get("total_skills", 0),
            "active_skills": stats.get("active_skills", 0),
            "ready_skills": stats.get("ready_skills", 0),
            "total_executions": stats.get("total_executions", 0),
            "total_errors": stats.get("total_errors", 0),
            "success_rate": (
                (stats.get("total_executions", 0) - stats.get("total_errors", 0))
                / stats.get("total_executions", 1)
                if stats.get("total_executions", 0) > 0 else 0
            ),
            "slots": stats.get("slots", {}),
            "by_tag": stats.get("by_tag", {}),
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/metrics/system-performance", summary="系统性能指标")
async def system_performance_metrics() -> Dict[str, Any]:
    """返回系统性能指标"""
    try:
        import psutil
        import os

        process = psutil.Process(os.getpid())

        return {
            "cpu_percent": process.cpu_percent(interval=0.1),
            "memory_mb": process.memory_info().rss / 1024 / 1024,
            "memory_percent": process.memory_percent(),
            "threads": process.num_threads(),
            "open_files": len(process.open_files()),
            "uptime_seconds": (datetime.now() - datetime.fromtimestamp(process.create_time())).total_seconds(),
        }
    except ImportError:
        return {"error": "psutil not installed"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/metrics/error-rate", summary="错误率统计")
async def error_rate_metrics() -> Dict[str, Any]:
    """返回错误率统计"""
    try:
        from harness.audit import AuditStore

        store = AuditStore()

        # 获取最近的审计记录
        recent_entries = store.search(query="", limit=100)

        total = len(recent_entries)
        errors = sum(1 for e in recent_entries if e.outcomes.get("status") == "failed")

        return {
            "total_events": total,
            "error_count": errors,
            "error_rate": errors / total if total > 0 else 0,
            "success_rate": (total - errors) / total if total > 0 else 0,
            "recent_errors": [
                {
                    "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                    "task": e.task,
                    "error": e.outcomes.get("error", "unknown"),
                }
                for e in recent_entries[-5:]
                if e.outcomes.get("status") == "failed"
            ],
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/metrics/adapter-usage", summary="适配器使用情况")
async def adapter_usage_metrics() -> Dict[str, Any]:
    """返回适配器使用情况统计"""
    try:
        from harness.audit import AuditStore

        store = AuditStore()

        # 搜索 deploy 相关的审计记录
        deploy_entries = store.search(query="deploy", limit=100)

        adapter_counts = {}
        for entry in deploy_entries:
            adapter = entry.outcomes.get("adapter", "unknown")
            adapter_counts[adapter] = adapter_counts.get(adapter, 0) + 1

        return {
            "total_deploys": len(deploy_entries),
            "by_adapter": adapter_counts,
            "most_used_adapter": max(adapter_counts.items(), key=lambda x: x[1])[0] if adapter_counts else "none",
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/metrics/rule-pack-usage", summary="规则包使用情况")
async def rule_pack_usage_metrics() -> Dict[str, Any]:
    """返回规则包使用情况统计"""
    try:
        from harness.compliance import ComplianceEngine

        engine = ComplianceEngine()
        packs = engine.list_packs()

        pack_stats = []
        for pack_name in packs:
            pack = engine.get_pack(pack_name)
            if pack:
                pack_stats.append({
                    "name": pack_name,
                    "category": pack.category.value,
                    "rule_count": len(pack.rules),
                })

        return {
            "total_packs": len(packs),
            "packs": pack_stats,
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/metrics/overview", summary="监控概览")
async def metrics_overview() -> Dict[str, Any]:
    """返回监控概览（聚合所有指标）"""
    try:
        skill_metrics = await skill_execution_metrics()
        error_metrics = await error_rate_metrics()
        adapter_metrics = await adapter_usage_metrics()

        return {
            "timestamp": datetime.now().isoformat(),
            "skills": skill_metrics,
            "errors": error_metrics,
            "adapters": adapter_metrics,
            "health": "healthy" if error_metrics.get("error_rate", 0) < 0.1 else "degraded",
        }
    except Exception as e:
        return {"error": str(e)}


# ── main 入口 ──
if __name__ == "__main__":
    import uvicorn

    print("harness-cook Dashboard 启动...")
    print("访问 http://localhost:8765 查看可视化界面")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8765,
        log_level="info",
    )
"""
harness-cook MCP Server — MCP Python SDK 实现。

使用官方 MCP Python SDK 处理协议层，所有工具业务逻辑保留原实现。

Exposed tools (25):
  - harness_check            Run compliance check (supports engine + language routing)
  - harness_audit            Query audit log (supports backend selection)
  - harness_plan             DAG topological visualization
  - harness_run              Execute a DAG workflow
  - harness_status           Aggregated system status
  - harness_register         Register an Agent
  - harness_gate_create      Create a Gate definition
  - harness_gate_approve     Approve or reject a pending gate (E-9: EventBus callback mode)
  - harness_guardrails_check Input / output guardrail check
  - harness_hook_trigger     Trigger governance logic for a lifecycle slot (BLOCK/WARN/REDACT/CONTINUE)
  - harness_pipeline_run     Start coding pipeline
  - harness_pipeline_status  Query pipeline execution status
  - harness_agent_list       List available agent roles
  - harness_profile_list     List all available harness Profiles
  - harness_profile_load     Load a specific harness Profile
  - harness_skill_list       List registered Skills
  - harness_skill_register   Register a new Skill
  - harness_bridge_deploy    Deploy Profile to Agent platform (claude-code/copilot-cli/cursor)
  - harness_trace_export     Export audit entries as OTel/Traceloop traces
  - harness_rule_import      Import compliance rules from external engines (sonarqube/archunit/dep_cruiser)
  - harness_knowledge_query  Query knowledge entries with filters (type/scope/tags/source)
  - harness_knowledge_search Search knowledge by keyword or TF-IDF semantic search
  - harness_knowledge_stats  Knowledge base statistics overview
  - harness_knowledge_activate  Activate an Insight as a ComplianceRule (S-4: one-click activation)
  - harness_knowledge_deactivate  Deactivate an Insight's ComplianceRule (S-4: undo activation)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
try:
    import yaml  # stdlib has no yaml; we accept the dependency for workflow parsing
    HAS_YAML = True
except ImportError:
    HAS_YAML = False
from typing import Any, Dict, List, Optional

# ── MCP SDK imports ───────────────────────────────────────────

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource

logger = logging.getLogger("harness.mcp")

# ── harness-cook core imports ─────────────────────────────────

from harness.compliance import ComplianceEngine, RulePack
from harness.rule_packs import get_coding_pack, get_security_pack, get_data_pack, get_devops_pack, get_architecture_pack, get_legal_pack
from harness.audit import AuditStore, AuditEngine
from harness.engine import DAGEngine, ExecutionContext
from harness.registry import AgentRegistry, get_registry
from harness.bridge import HarnessBridge
from harness.gates import GateEngine, GateResult
from harness.guardrails import (
    InputGuardrails, OutputGuardrails, GuardrailResult, PIIDetector,
    GuardrailsPair, default_guardrails,
)
from harness.integrations.audit_store_protocol import IAuditStore
from harness.integrations.multi_store import MultiAuditStore
from harness.integrations.engine_config import AuditEngineConfig
from harness.types import (
    DAGNode, DAGEdge, DAGWorkflow,
    GateDefinition, GateCheck, GateMode, RetryStrategy,
    AgentDefinition, AgentCapability, Artifact, TaskResult,
    InputGuardrailConfig, OutputGuardrailConfig,
    GuardrailAction, ComplianceCategory,
)
from harness.knowledge import (
    KnowledgeType, KnowledgeScope, KnowledgeEntry, KnowledgeQuery,
    LocalKnowledgeProvider, get_knowledge_provider,
    InsightActivationStore, insight_to_rule_pack,
)


# ── StubAgent: MCP 注册的 Agent 无 Python implementation ──────
# 通过 MCP 只能传 definition（ID、能力等），不能传 IExecutableAgent 对象。
# StubAgent 让 MCP 注册的 Agent 变成 is_ready=true，DAG 引擎可以执行。
# 执行时返回一个 "completed" TaskResult，内容为任务描述的确认。

class StubAgent:
    """MCP 注册 Agent 的默认 implementation — 让 Agent is_ready=True"""

    def __init__(self, definition: AgentDefinition):
        self._definition = definition

    def execute(self, task: str, context: dict) -> TaskResult:
        import time, uuid
        start = time.monotonic()
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return TaskResult(
            task_id=context.get("task_id", str(uuid.uuid4())),
            agent_id=self._definition.id,
            status="completed",
            artifacts=[Artifact(
                type="log",
                path=f"stub-{self._definition.id}",
                content=f"StubAgent executed task: {task}",
                metadata={"agent_type": self._definition.id, "stub": True},
            )],
            duration_ms=elapsed_ms,
            tokens_used=0,
            metadata={"stub_execution": True, "task": task},
        )

    def estimate_tokens(self, task: str) -> int:
        return len(task) * 4 + 500

from harness.bus import EventBus, get_bus

# ── Rule-pack registry (name → factory) ───────────────────────

_PACK_FACTORIES: Dict[str, Any] = {
    "coding": get_coding_pack,
    "security": get_security_pack,
    "data": get_data_pack,
    "devops": get_devops_pack,
    "architecture": get_architecture_pack,
    "legal": get_legal_pack,
}

SERVER_VERSION = "0.1.0"


# ════════════════════════════════════════════════════════════════
#  Tool definitions — MCP SDK Tool objects
# ════════════════════════════════════════════════════════════════

TOOL_DEFINITIONS: List[Tool] = [
    Tool(
        name="harness_check",
        description="Run a compliance scan on content at a given path using specified rule packs. "
                    "Engine routing: 'builtin' (default, always available); 'sonarqube'/'opa'/'archunit'/'dep_cruiser' "
                    "are planned — fall back to builtin with engine_warning when their SDK is not installed. "
                    "Language routing is planned (builtin engine does not consume it yet; see language_routing).",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "待扫描文件路径或标识符。用于读取内容（未传 content 时）及语言检测——"
                                  "matches_scope 按扩展名激活语言特定规则（如 CODE-001 仅 python）。"
                                  "传 content 时也应提供含扩展名的路径以激活语言规则；"
                                  "无扩展名的标识符会降级为只跑全语言规则。",
                },
                "content": {
                    "type": "string",
                    "description": "待扫描内容。未提供时从 path 指向的文件读取（仅文本文件，"
                                  "上限 2MB；目录/二进制/不存在文件会返回 read_warning 而非扫描）。",
                },
                "pack_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Names of rule packs to load (coding, security, data, devops). Defaults to all.",
                },
                "engine": {
                    "type": "string",
                    "description": "Compliance engine to use: 'builtin' (default), 'sonarqube', 'opa', 'archunit', 'dep_cruiser'. "
                                  "If engine is not available, falls back to builtin with a warning.",
                    "default": "builtin",
                },
                "language_routing": {
                    "type": "object",
                    "description": "Language-aware routing config (language → engine). "
                                  "Example: {'java': 'archunit', 'javascript': 'dep_cruiser'}. "
                                  "注：当前版本 builtin 引擎不消费此参数，外部引擎路由为规划中。",
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="harness_audit",
        description="Search the audit log for entries matching a query. "
                    "Supports backend selection: 'local' (default), 'langfuse', 'arize', 'datadog'. "
                    "If configured for multi-backend, searches primary store.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keyword.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 50).",
                    "default": 50,
                },
                "backend": {
                    "type": "string",
                    "description": "Audit backend to search: 'local' (default), 'langfuse', 'arize', 'datadog'. "
                                  "Only searches primary store in multi-backend mode.",
                    "default": "local",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="harness_plan",
        description="Visualize a DAG workflow by returning its topological execution order.",
        inputSchema={
            "type": "object",
            "properties": {
                "workflow_yaml": {
                    "type": "string",
                    "description": "YAML string defining the DAG workflow (nodes + edges).",
                },
            },
            "required": ["workflow_yaml"],
        },
    ),
    Tool(
        name="harness_run",
        description="Execute a DAG workflow and return the execution context results.",
        inputSchema={
            "type": "object",
            "properties": {
                "workflow_yaml": {
                    "type": "string",
                    "description": "YAML string defining the DAG workflow.",
                },
            },
            "required": ["workflow_yaml"],
        },
    ),
    Tool(
        name="harness_status",
        description="Return aggregated system status (registry, compliance, engine stats).",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="harness_register",
        description="Register a new Agent in the harness registry.",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Unique agent identifier.",
                },
                "name": {
                    "type": "string",
                    "description": "Human-readable agent name.",
                },
                "capabilities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Agent capabilities (perceive, reason, execute, remember, collaborate, self_drive).",
                },
                "toolsets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Toolset names the agent requires.",
                },
            },
            "required": ["agent_id"],
        },
    ),
    Tool(
        name="harness_gate_create",
        description="Create a Gate definition with specified checks.",
        inputSchema={
            "type": "object",
            "properties": {
                "gate_type": {
                    "type": "string",
                    "description": "Gate mode: strict, hybrid, or loose.",
                },
                "checks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "category": {"type": "string"},
                            "severity": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["id", "category", "severity", "description"],
                    },
                    "description": "List of gate checks.",
                },
                "auto_fix": {
                    "type": "boolean",
                    "description": "Whether auto-fix should be enabled (default false).",
                    "default": False,
                },
            },
            "required": ["gate_type", "checks"],
        },
    ),
    Tool(
        name="harness_guardrails_check",
        description="Check content through input or output guardrails for PII and safety. "
                    "Engine options: 'builtin' (default, local guardrails), 'guardrails-ai' (Guardrails AI SDK, "
                    "auto-fallback to builtin if SDK not installed).",
        inputSchema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Content to check.",
                },
                "direction": {
                    "type": "string",
                    "description": "'input' or 'output' (default 'input').",
                    "default": "input",
                },
                "engine": {
                    "type": "string",
                    "description": "Guardrails engine: 'builtin' (default) or 'guardrails-ai'. "
                                  "SDK not installed → auto-fallback to builtin.",
                    "default": "builtin",
                },
            },
            "required": ["content"],
        },
    ),
    Tool(
        name="harness_hook_trigger",
        description="Trigger governance logic for a lifecycle slot and return a governance decision. "
                    "Routes to the appropriate governance layer based on slot type: "
                    "pre_tool_use/pre_execute → InputGuardrails; "
                    "post_tool_use/post_execute/on_file_change → OutputGuardrails; "
                    "other slots → CONTINUE (no governance check). "
                    "Returns BLOCK/WARN/REDACT/CONTINUE decision.",
        inputSchema={
            "type": "object",
            "properties": {
                "slot": {
                    "type": "string",
                    "description": "Lifecycle slot name. Valid slots: "
                                  "session_start, session_end, "
                                  "pre_execute, post_execute, on_error, "
                                  "pre_tool_use, post_tool_use, "
                                  "on_gate_pass, on_gate_fail, "
                                  "on_file_change, "
                                  "pre_commit, post_commit, "
                                  "on_delegate, on_conflict, "
                                  "on_decision, on_escalation, "
                                  "user_prompt_submit.",
                },
                "content": {
                    "type": "string",
                    "description": "Content to check (text, code, command output). "
                                  "Required for guardrails-checking slots.",
                },
                "tool_name": {
                    "type": "string",
                    "description": "Tool name context (e.g., 'Write', 'Edit', 'Bash'). "
                                  "Used for matcher-based routing.",
                },
                "direction": {
                    "type": "string",
                    "description": "'input' or 'output' (default 'input'). "
                                  "Determines which guardrails pair to use.",
                    "default": "input",
                },
            },
            "required": ["slot"],
        },
    ),
    Tool(
        name="harness_gate_approve",
        description="Approve or reject a pending gate approval request (E-9: EventBus callback mode). "
                    "When GateManager.wait_for_approval() emits a GATE_APPROVAL_REQUEST event and blocks "
                    "on a threading.Event, this tool emits the corresponding GATE_APPROVAL_DECISION event "
                    "via the project's EventBus, which wakes the waiting thread. "
                    "Valid decisions: approved, rejected, cancelled.",
        inputSchema={
            "type": "object",
            "properties": {
                "gate_id": {
                    "type": "string",
                    "description": "The gate ID to approve or reject. "
                                  "Must match a pending GATE_APPROVAL_REQUEST.",
                },
                "decision": {
                    "type": "string",
                    "description": "Approval decision. Valid values: "
                                  "approved, rejected, cancelled.",
                    "enum": ["approved", "rejected", "cancelled"],
                },
                "decided_by": {
                    "type": "string",
                    "description": "Who made the decision (e.g., username, role). "
                                  "Defaults to 'human'.",
                    "default": "human",
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for the decision. Optional.",
                    "default": "",
                },
            },
            "required": ["gate_id", "decision"],
        },
    ),
    Tool(
        name="harness_pipeline_run",
        description="Start a coding pipeline (Analyst→Coder→Validator→Committer) with gate enforcement.",
        inputSchema={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Task description for the pipeline to execute.",
                },
                "working_directory": {
                    "type": "string",
                    "description": "Project working directory (default current).",
                    "default": ".",
                },
                "gate_mode": {
                    "type": "string",
                    "description": "Gate strictness: strict, hybrid, or loose (default hybrid).",
                    "default": "hybrid",
                },
                "agents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Pipeline agent sequence (default: analyst, coder, validator, committer).",
                },
                "max_retries": {
                    "type": "integer",
                    "description": "Max retries on gate failure (default 2).",
                    "default": 2,
                },
            },
            "required": ["task"],
        },
    ),
    Tool(
        name="harness_pipeline_status",
        description="Query the status of the current or most recent pipeline execution.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="harness_agent_list",
        description="List available agent roles with their tool configurations.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="harness_profile_list",
        description="List all available harness Profiles.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="harness_profile_load",
        description="Load a harness Profile. "
                    "If no name specified, auto-resolves via HARNESS_PROFILE env var > .harness/active_profile marker > 'default'. "
                    "Governance intensity (gates, constraints, severity) is defined directly in the Profile YAML — "
                    "edit .harness/profiles/*.yaml to adjust.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Profile name. Leave empty to auto-resolve active profile.",
                },
            },
        },
    ),
    Tool(
        name="harness_skill_list",
        description="List registered Skills, optionally filtered by slot or tag.",
        inputSchema={
            "type": "object",
            "properties": {
                "slot": {
                    "type": "string",
                    "description": "Filter by slot name (pre_execute, post_execute, on_gate_pass, on_gate_fail, on_error, session_start, session_end).",
                },
                "tag": {
                    "type": "string",
                    "description": "Filter by tag.",
                },
            },
        },
    ),
    Tool(
        name="harness_skill_register",
        description="Register a new Skill in the harness skill registry.",
        inputSchema={
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "description": "Unique skill identifier."},
                "name": {"type": "string", "description": "Human-readable skill name."},
                "description": {"type": "string", "description": "What this skill does."},
                "entry_point": {"type": "string", "description": "Path to skill script."},
                "slot": {"type": "string", "description": "Slot name (default: post_execute)."},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for filtering."},
            },
            "required": ["skill_id", "name"],
        },
    ),
    Tool(
        name="harness_bridge_deploy",
        description="Deploy current Profile configuration to an Agent platform. "
                    "Supported adapters: claude-code (default), copilot-cli, cursor. "
                    "If no profile_name specified, auto-resolves via HARNESS_PROFILE env var > .harness/active_profile marker > 'default'.",
        inputSchema={
            "type": "object",
            "properties": {
                "profile_name": {
                    "type": "string",
                    "description": "Profile to deploy. Leave empty to auto-resolve active profile.",
                },
                "adapter": {
                    "type": "string",
                    "description": "Target adapter: 'claude-code' (default), 'copilot-cli', or 'cursor'.",
                    "default": "claude-code",
                },
            },
        },
    ),
    Tool(
        name="harness_trace_export",
        description="Export audit entries as OTel/Traceloop-compatible trace format. "
                    "Returns span dicts with harness.* and traceloop.* attributes for observability integration.",
        inputSchema={
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "description": "Export format: 'otel-json' (default) or 'traceloop'. "
                                  "'otel-json' uses standard OTel Span attributes; "
                                  "'traceloop' adds Traceloop-specific attribute mapping.",
                    "default": "otel-json",
                },
                "date_from": {
                    "type": "string",
                    "description": "Start date filter (ISO format, e.g. '2026-01-01'). Optional.",
                },
                "date_to": {
                    "type": "string",
                    "description": "End date filter (ISO format, e.g. '2026-12-31'). Optional.",
                },
                "query": {
                    "type": "string",
                    "description": "Search keyword to filter entries. Optional.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max entries to export (default 50).",
                    "default": 50,
                },
            },
        },
    ),
    Tool(
        name="harness_rule_import",
        description="Import compliance rules from external engines (SonarQube, ArchUnit, DepCruiser). "
                    "Returns a RulePack that can be loaded into the compliance engine.",
        inputSchema={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Rule source: 'sonarqube', 'archunit', or 'dep_cruiser'.",
                },
                "project_key": {
                    "type": "string",
                    "description": "Project key for SonarQube (optional). For ArchUnit/DepCruiser, used as project_root.",
                },
                "config": {
                    "type": "object",
                    "description": "Source-specific configuration (sonarqube_url, sonarqube_token, config_file, etc.).",
                    "additionalProperties": {"type": "string"},
                },
                "languages": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Language filter for SonarQube (e.g. ['python', 'java']). Optional.",
                },
            },
            "required": ["source"],
        },
    ),
    # ── Knowledge tools: Agent 主动查询项目知识 ────────────────
    Tool(
        name="harness_knowledge_query",
        description="Query knowledge entries with filters. "
                    "Returns structured project knowledge (architecture decisions, known risks, coding conventions, etc.). "
                    "Use this when you need project context before making decisions — "
                    "e.g., before choosing a tech stack, check existing DECISION entries; "
                    "before writing code, check known RISK and PATTERN entries. "
                    "Knowledge types: architecture, convention, dependency, api, pattern, risk, decision, task, test, glossary. "
                    "Scopes: project, module, file, function.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword to search in title, content, and tags.",
                },
                "type_filter": {
                    "type": "string",
                    "description": "Filter by knowledge type: architecture, convention, dependency, api, pattern, risk, decision, task, test, glossary.",
                },
                "scope_filter": {
                    "type": "string",
                    "description": "Filter by scope: project, module, file, function.",
                },
                "tags_filter": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by tags.",
                },
                "source_filter": {
                    "type": "string",
                    "description": "Filter by source: human, ast, llm, learning, compliance, guardrail, gate.",
                },
                "project": {
                    "type": "string",
                    "description": "Project name (default: auto-resolve from current directory).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max entries to return (default 20).",
                    "default": 20,
                },
            },
        },
    ),
    Tool(
        name="harness_knowledge_search",
        description="Search knowledge by keyword or TF-IDF semantic search. "
                    "Keyword search matches title, content, and tags. "
                    "Semantic search uses TF-IDF for broader relevance matching. "
                    "Use 'method=semantic' when keyword search returns no results or you need conceptually related entries.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query — keyword or concept description.",
                },
                "method": {
                    "type": "string",
                    "description": "Search method: 'keyword' (default) for exact matching, 'semantic' for TF-IDF relevance.",
                    "default": "keyword",
                },
                "project": {
                    "type": "string",
                    "description": "Project name (default: auto-resolve from current directory).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max entries to return (default 10).",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="harness_knowledge_stats",
        description="Knowledge base statistics overview — entry counts, type distribution, source distribution, "
                    "high-frequency entries, archived entries. "
                    "Use this to understand what knowledge is available before querying specifics.",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project name (default: auto-resolve from current directory).",
                },
            },
        },
    ),
    # ── S-4 Knowledge activation tools ────────────────────
    Tool(
        name="harness_knowledge_activate",
        description="Activate an Insight as a ComplianceRule (S-4: one-click activation). "
                    "Converts a knowledge Insight entry into a ComplianceRule wrapped in a RulePack, "
                    "then loads it into the ComplianceEngine for real-time checking. "
                    "The activation is tracked and can be undone via harness_knowledge_deactivate. "
                    "This is the core S-4 mechanism: user adopts an insight → one-click → becomes a rule.",
        inputSchema={
            "type": "object",
            "properties": {
                "insight_id": {
                    "type": "string",
                    "description": "The KnowledgeEntry ID of the Insight to activate. "
                                    "Use harness_knowledge_query or harness_knowledge_search to find Insight entries first.",
                },
                "severity": {
                    "type": "string",
                    "description": "Severity level for the activated rule: critical, high, medium, low.",
                    "default": "medium",
                },
                "project": {
                    "type": "string",
                    "description": "Project name (default: auto-resolve from current directory).",
                },
            },
            "required": ["insight_id"],
        },
    ),
    Tool(
        name="harness_knowledge_deactivate",
        description="Deactivate (undo) an Insight's ComplianceRule activation (S-4). "
                    "Removes the RulePack from the ComplianceEngine and deletes the activation record. "
                    "Use this when an Insight-derived rule is no longer needed or was activated by mistake.",
        inputSchema={
            "type": "object",
            "properties": {
                "insight_id": {
                    "type": "string",
                    "description": "The KnowledgeEntry ID of the Insight to deactivate. "
                                    "Must match an previously activated Insight.",
                },
                "project": {
                    "type": "string",
                    "description": "Project name (default: auto-resolve from current directory).",
                },
            },
            "required": ["insight_id"],
        },
    ),
]


# ════════════════════════════════════════════════════════════════
#  HarnessMCPServer — 业务逻辑容器
# ════════════════════════════════════════════════════════════════

class HarnessMCPServer:
    """
    harness-cook MCP Server 业务逻辑层。

    持有所有引擎实例（合规、审计、DAG、门禁、护栏），
    提供 21 个 _tool_* 方法作为工具实现。

    MCP 协议层由 MCP SDK Server 处理，不在此类中。
    """

    def __init__(
        self,
        bus: Optional[EventBus] = None,
        registry: Optional[AgentRegistry] = None,
        project_dir: Optional[str] = None,
    ) -> None:
        # ── 确定项目根目录 ────────────────────────────────────
        # 优先级：显式参数 > CLAUDE_PROJECT_DIR 环境变量 > 无
        # 传入 project_dir 让 AuditStore 等核心模块定位到
        # 项目的 .harness/ 目录，而非回退到 ~/.harness/
        self._project_dir = project_dir or os.environ.get("CLAUDE_PROJECT_DIR")

        # 在任何 Profile 加载之前注册内置 Skills，确保 ProfileLoader.load 内部
        # E-10 校验（_validate_hooks_skill_ids）时 skill 已就绪。
        # 关键：_build_audit_store / _resolve_audit_engine_config 等也会触发 Profile 加载，
        # 故此注册必须先于一切引擎初始化执行。register_builtin_skills 幂等，可重复调用。
        try:
            from harness.skill_registry import get_skill_registry, register_builtin_skills
            register_builtin_skills(get_skill_registry())
        except Exception:
            pass  # Skill 注册失败不应阻断引擎初始化

        self._bus = bus or get_bus()
        self._registry = registry or get_registry()

        # ── 合规引擎：预加载所有内置规则包 ──────────────────
        self._compliance_engine = ComplianceEngine(bus=self._bus)
        for factory in _PACK_FACTORIES.values():
            self._compliance_engine.load_pack(factory())

        # ── 审计引擎：从 Profile 配置构建存储链 ──────────────
        # 默认：AuditStore（本地 JSON）
        # Profile 配置了 audit_engine.backends → MultiAuditStore（双写）
        self._audit_store = self._build_audit_store()
        self._audit_engine = AuditEngine(store=self._audit_store, bus=self._bus)
        self._audit_engine_config = self._resolve_audit_engine_config()

        self._gate_engine = GateEngine(bus=self._bus)
        self._dag_engine = DAGEngine(registry=self._registry, gate_engine=self._gate_engine, bus=self._bus)
        self._guardrails_pair = default_guardrails()

        # ── 治理引擎初始化 ──────────────────────────────────
        # 从配置读取护栏引擎选择（default=builtin）
        self._guardrails_engine = os.environ.get(
            "HARNESS_GUARDRAILS_ENGINE", "builtin"
        )
        # 尝试加载 Profile 配置覆盖环境变量
        try:
            from harness.config import ProfileLoader
            profile_loader = ProfileLoader()
            active_profile_name = profile_loader.resolve_active()
            profile = profile_loader.load(active_profile_name)
            if profile and profile.guardrails_engine:
                self._guardrails_engine = profile.guardrails_engine.engine
        except Exception:
            pass  # Profile 加载失败 → 使用默认 builtin

    # ══════════════════════════════════════════════════════════════
    #  Private helpers — 审计存储构建
    # ══════════════════════════════════════════════════════════════

    def _resolve_audit_engine_config(self) -> AuditEngineConfig:
        """从 Profile 配置读取 AuditEngineConfig；无配置 → 默认 local"""
        try:
            from harness.config import ProfileLoader
            profile_loader = ProfileLoader()
            active_profile_name = profile_loader.resolve_active()
            profile = profile_loader.load(active_profile_name)
            if profile and profile.audit_engine:
                return profile.audit_engine
        except Exception:
            pass
        return AuditEngineConfig()  # backends=["local"]

    def _build_audit_store(self) -> IAuditStore:
        """根据 AuditEngineConfig 构建 IAuditStore

        - backends=["local"] → AuditStore（默认）
        - backends=["local", "langfuse"] → MultiAuditStore 双写
        - backends=["langfuse"] → 直接 LangfuseAuditStore（primary）
        """
        config = self._resolve_audit_engine_config()
        backends = config.backends

        if not backends or backends == ["local"]:
            # 单 local → AuditStore
            return AuditStore(project_dir=self._project_dir)

        # 构建存储链：local 永远是 primary（搜索/验证来源）
        stores: List[IAuditStore] = [AuditStore(project_dir=self._project_dir)]

        for backend in backends:
            if backend == "local":
                continue  # 已作为 primary
            store = self._create_external_store(backend, config)
            if store is not None:
                stores.append(store)
            else:
                logger.warning(f"Audit backend '{backend}' SDK not installed — skipping")

        if len(stores) == 1:
            return stores[0]  # 只有 local（外部后端全部不可用）

        return MultiAuditStore(stores=stores, bus=self._bus)

    def _create_external_store(self, backend: str, config: AuditEngineConfig) -> Optional[IAuditStore]:
        """创建外部审计存储实例；SDK 未安装 → 返回 None"""
        backend_config = config.config.get(backend, {})

        if backend == "langfuse":
            try:
                from harness.integrations.langfuse_store import LangfuseAuditStore
                return LangfuseAuditStore(config=backend_config)
            except ImportError:
                logger.debug("langfuse SDK not installed — LangfuseAuditStore unavailable")
                return None

        if backend == "arize":
            try:
                from harness.integrations.arize_store import ArizeAuditStore
                return ArizeAuditStore(config=backend_config)
            except ImportError:
                logger.debug("arize SDK not installed — ArizeAuditStore unavailable")
                return None

        if backend == "datadog":
            try:
                from harness.integrations.datadog_store import DatadogAuditStore
                return DatadogAuditStore(config=backend_config)
            except ImportError:
                logger.debug("ddtrace SDK not installed — DatadogAuditStore unavailable")
                return None

        logger.warning(f"Unknown audit backend: '{backend}' — skipping")
        return None

    # ══════════════════════════════════════════════════════════════
    #  Tool implementations — 原样保留，不依赖 JSON-RPC 协议层
    # ══════════════════════════════════════════════════════════════

    def _tool_check(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_check: run compliance scan with engine routing."""
        path = args.get("path", "unknown")
        pack_names = args.get("pack_names", list(_PACK_FACTORIES.keys()))
        engine = args.get("engine", "builtin")
        language_routing = args.get("language_routing")

        # Reuse the pre-loaded compliance engine (loaded in __init__)
        skipped_packs = []
        for pname in pack_names:
            if not self._compliance_engine.get_pack(pname):
                skipped_packs.append(pname)

        # ── 引擎路由 ──────────────────────────────────
        routed_engine = "builtin"
        engine_warning = None

        if engine != "builtin":
            # 尝试使用指定引擎
            from harness.rule_checker import MatcherRegistry
            checker = MatcherRegistry.get(engine)
            if checker is not None:
                routed_engine = engine
            else:
                engine_warning = f"Engine '{engine}' not available (SDK not installed), falling back to builtin"
                routed_engine = "builtin"

        # ── 语言路由 ──────────────────────────────────
        # 如果没有显式 language_routing，使用默认语言路由表
        effective_routing = language_routing
        if not effective_routing and engine == "builtin":
            # 默认语言路由表
            effective_routing = {
                "java": "archunit",
                "javascript": "dep_cruiser",
                "typescript": "dep_cruiser",
            }

        # 内容来源：优先用调用方显式提供的 content；未提供则从 path 指向的文件读取
        content, read_warning = self._resolve_scan_content(args, path)
        if read_warning is not None:
            # 读不到有效内容（二进制/不存在/目录/过大）→ 跳过扫描，
            # 避免对空内容产生 LEGAL-001 类（^.{0,50}$）的空匹配误报
            results = []
        else:
            results = self._compliance_engine.scan_quick(
                content, path, pack_names=pack_names
            )

        summary = {
            "path": path,
            "pack_names": pack_names,
            "pack_filter_applied": pack_names is not None
            and len(pack_names) < len(_PACK_FACTORIES),
            "skipped_packs": skipped_packs,
            "engine": routed_engine,
            "engine_warning": engine_warning,
            "language_routing": effective_routing,
            "read_warning": read_warning,
            "total_rules": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
            "details": [
                {
                    "rule_id": r.rule_id,
                    "passed": r.passed,
                    "severity": r.severity,
                    "findings": r.findings,
                    "remediation": r.remediation,
                }
                for r in results
            ],
        }
        return summary

    def _resolve_scan_content(
        self, args: Dict[str, Any], path: str
    ) -> tuple[str, str | None]:
        """解析待扫描内容：优先用显式 content，否则从 path 读取文件。

        返回 (content, warning)。warning 非 None 表示未能从 path 读取到内容
        （路径非文件、不存在、读取失败、二进制或过大），此时 content 为空串。
        所有异常都被捕获并转为 warning，避免扫描入口因 IO 异常而崩溃。
        """
        content = args.get("content")
        if content:
            return content, None

        if not path or path == "unknown":
            return "", "未提供 content 且 path 为空，无可扫描内容"

        p = Path(path)
        if not p.is_file():
            return "", f"path 不是可读文件：{path}（可能是目录/标识符/不存在）"

        # 大文件上限，防止意外读入超大文件拖慢扫描
        try:
            size = p.stat().st_size
        except OSError as e:
            return "", f"读取文件状态失败：{e}"
        if size > 2 * 1024 * 1024:
            return "", f"文件过大（{size} 字节），跳过扫描（上限 2MB）"

        try:
            raw = p.read_bytes()
        except OSError as e:
            return "", f"读取文件失败：{e}"

        # 二进制文件检测：含 NUL 字节视为二进制，解码无意义
        if b"\x00" in raw:
            return "", f"文件为二进制，跳过扫描：{path}"

        return raw.decode("utf-8", errors="replace"), None

    def _tool_audit(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_audit: search audit log with backend selection.

        backend 参数仅用于信息标记——搜索始终从主存储（primary store）执行，
        因为外部存储（langfuse/arize/datadog）不支持搜索 API。
        """
        query = args.get("query", "")
        limit = args.get("limit", 50)
        backend = args.get("backend", "local")

        # 搜索始终从 primary store（local AuditStore）执行
        entries = self._audit_engine.search(query, limit=limit)

        # 标记当前配置的后端列表
        configured_backends = self._audit_engine_config.backends

        return {
            "query": query,
            "backend": backend,
            "configured_backends": configured_backends,
            "count": len(entries),
            "entries": [
                {
                    "task": e.task,
                    "agent_id": e.agent_id,
                    "session_id": e.session_id,
                    "timestamp": e.timestamp.isoformat(),
                    "decisions": e.decisions,
                    "actions": e.actions,
                    "outcomes": e.outcomes,
                }
                for e in entries
            ],
        }

    def _tool_plan(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_plan: visualize DAG topological order."""
        workflow_yaml = args.get("workflow_yaml", "")
        workflow = self._parse_workflow_yaml(workflow_yaml)

        order = self._dag_engine.plan(workflow)
        nodes_info = [
            {"id": n.id, "agent_type": n.agent_type, "task": n.task}
            for n in workflow.nodes
        ]
        edges_info = [
            {"from": e.from_node, "to": e.to_node, "condition": e.condition}
            for e in workflow.edges
        ]

        return {
            "execution_order": order,
            "nodes": nodes_info,
            "edges": edges_info,
            "node_count": len(workflow.nodes),
            "edge_count": len(workflow.edges),
        }

    def _tool_run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_run: execute a DAG workflow."""
        workflow_yaml = args.get("workflow_yaml", "")
        workflow = self._parse_workflow_yaml(workflow_yaml)
        ctx = self._dag_engine.execute(workflow)

        return {
            "execution_id": ctx.execution_id,
            "workflow_id": ctx.workflow_id,
            "duration_ms": ctx.duration_ms,
            "completed_nodes": list(ctx.completed_nodes),
            "failed_nodes": list(ctx.failed_nodes),
            "escalated": ctx.escalated,
            "escalation_reason": ctx.escalation_reason,
            "node_status": ctx.node_status,
        }

    def _tool_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_status: aggregated system status."""
        # 审计记录数
        audit_files = list(self._audit_store._store_dir.rglob("*.json"))

        # 最后活动时间
        last_activity = None
        if audit_files:
            try:
                latest = max(audit_files, key=lambda f: f.stat().st_mtime)
                last_activity = datetime.fromtimestamp(latest.stat().st_mtime).isoformat()
            except Exception:
                pass

        # 当前 session
        session_id = None
        session_file = Path(self._project_dir or os.getcwd()) / ".harness" / "session_id"
        try:
            if session_file.exists():
                session_id = session_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass

        # 规则包详情
        pack_names = self._compliance_engine.list_packs()
        packs_detail = []
        for pname in pack_names:
            pack = self._compliance_engine.get_pack(pname)
            if pack:
                packs_detail.append({
                    "name": pname,
                    "rules": len(pack.rules),
                    "category": pack.category.value,
                })

        # 部署状态（持久化，系统级）
        try:
            bridge = HarnessBridge()
            deployment = bridge.status(project_dir=self._project_dir)
        except Exception:
            deployment = {"deployed": False}

        # 运行时组件状态
        registry_stats = self._registry.stats()
        bus_stats = self._bus.stats()

        return {
            "version": SERVER_VERSION,
            "session_id": session_id,
            "deployment": deployment,
            "compliance": {
                **self._compliance_engine.stats(),
                "packs": packs_detail,
            },
            "engine": self._dag_engine.stats(),
            "gate": self._gate_engine.stats(),
            "audit": {
                "record_count": len(audit_files),
                "store_dir": str(self._audit_store._store_dir),
                "last_activity": last_activity,
            },
            "registry": {
                **registry_stats,
                "note": "通过 harness_register 或 @define_agent 注册" if registry_stats["total_agents"] == 0 else None,
            },
            "bus": {
                **bus_stats,
                "note": "check/run 时自动激活订阅" if bus_stats["total_subscriptions"] == 0 else None,
            },
            "server": {
                "name": "harness-cook",
                "version": SERVER_VERSION,
                "project_dir": self._project_dir,
            },
        }

    def _tool_register(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_register: register an Agent."""
        agent_id = args.get("agent_id", "")
        name = args.get("name", agent_id)
        cap_strings = args.get("capabilities", ["execute"])
        toolsets = args.get("toolsets", [])

        # Map string capabilities to AgentCapability enum
        cap_map = {c.value: c for c in AgentCapability}
        capabilities = [cap_map.get(c, AgentCapability.EXECUTE) for c in cap_strings]

        definition = AgentDefinition(
            id=agent_id,
            name=name,
            capabilities=capabilities,
            toolsets=toolsets,
        )
        # MCP 注册的 Agent 没有 Python implementation 对象，
        # 自动绑定 StubAgent 使 is_ready=True，DAG 引擎可执行。
        stub = StubAgent(definition)
        record = self._registry.register(definition, implementation=stub)

        return {
            "agent_id": record.id,
            "name": record.definition.name,
            "capabilities": [c.value for c in record.definition.capabilities],
            "toolsets": record.definition.toolsets,
            "active": record.active,
            "is_ready": record.is_ready,
        }

    def _tool_gate_create(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_gate_create: create a Gate definition."""
        gate_type = args.get("gate_type", "hybrid")
        checks_data = args.get("checks", [])
        auto_fix = args.get("auto_fix", False)

        mode_map = {
            "strict": GateMode.STRICT,
            "hybrid": GateMode.HYBRID,
            "loose": GateMode.LOOSE,
        }
        mode = mode_map.get(gate_type, GateMode.HYBRID)

        # Build GateCheck list with a simple default check_fn
        gate_checks: List[GateCheck] = []
        for chk in checks_data:
            chk_id = chk.get("id", "chk-0")
            chk_category = chk.get("category", "logic")
            chk_severity = chk.get("severity", "medium")
            chk_description = chk.get("description", "Default check")

            # Simple check_fn that always passes (placeholder)
            def _make_check_fn(sev: str, desc: str):
                def _fn(artifact: Artifact) -> Any:
                    from harness.types import CheckResult
                    return CheckResult(passed=True, severity=sev, message=desc)
                return _fn

            auto_fix_fn = None
            if auto_fix:
                def _make_auto_fix_fn():
                    def _fn(artifact: Artifact, result: Any) -> Artifact:
                        return artifact
                    return _fn
                auto_fix_fn = _make_auto_fix_fn()

            gate_checks.append(GateCheck(
                id=chk_id,
                category=chk_category,
                severity=chk_severity,
                description=chk_description,
                check_fn=_make_check_fn(chk_severity, chk_description),
                auto_fix_fn=auto_fix_fn,
            ))

        gate_def = GateDefinition(
            id=f"gate-{gate_type}-{len(gate_checks)}",
            checks=gate_checks,
            mode=mode,
        )

        return {
            "gate_id": gate_def.id,
            "mode": gate_def.mode.value,
            "check_count": len(gate_def.checks),
            "checks": [
                {"id": c.id, "category": c.category, "severity": c.severity, "description": c.description}
                for c in gate_def.checks
            ],
            "auto_fix": auto_fix,
        }

    def _tool_guardrails_check(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_guardrails_check: check content through guardrails.

        Engine routing:
        - builtin → GuardrailsPair（现有行为不变）
        - guardrails-ai → GuardrailsAIChecker（不可用时静默回退 + warning）
        """
        content = args.get("content", "")
        direction = args.get("direction", "input")
        engine = args.get("engine", self._guardrails_engine)

        # builtin engine → 现有 GuardrailsPair
        if engine == "builtin":
            if direction == "input":
                result = self._guardrails_pair.check_input(content)
            else:
                result = self._guardrails_pair.check_output(content)

            return {
                "action": result.action.value,
                "blocked": result.blocked,
                "warnings": result.warnings,
                "violations": result.violations,
                "redactions": result.redactions,
                "original_content": result.original_content,
                "processed_content": result.processed_content,
                "engine": "builtin",
            }

        # guardrails-ai engine → GuardrailsAIChecker
        if engine == "guardrails-ai":
            try:
                from harness.integrations.guardrails_ai_checker import GuardrailsAIChecker
                from harness.types import (
                    Artifact, ComplianceRule, ComplianceResult, ScanContext,
                    ComplianceCategory,
                )

                checker = GuardrailsAIChecker()

                # 构建 ComplianceRule（PII 检测规则）
                rule = ComplianceRule(
                    id="GR-001",
                    category=ComplianceCategory.PRIVACY,
                    pattern="no_pii",
                    severity="critical",
                    description="PII detection via Guardrails AI",
                    remediation="Remove PII from content",
                    matcher_type="guardrails_ai",
                    matcher_config={},
                    languages=[],
                )

                # 构建 Artifact
                artifact = Artifact(type="text", path="content.txt", content=content)

                # 构建 ScanContext
                scan_context = ScanContext(
                    artifacts=[artifact],
                    project_root="/tmp/guardrails-ai",
                )

                compliance_result = checker.check(rule, artifact, scan_context)

                # 将 ComplianceResult 转为 GuardrailsResult 格式
                if compliance_result.passed:
                    return {
                        "action": "allow",
                        "blocked": False,
                        "warnings": [],
                        "violations": [],
                        "redactions": [],
                        "original_content": content,
                        "processed_content": content,
                        "engine": "guardrails-ai",
                    }
                else:
                    return {
                        "action": "block",
                        "blocked": True,
                        "warnings": compliance_result.findings,
                        "violations": compliance_result.findings,
                        "redactions": [],
                        "original_content": content,
                        "processed_content": content,
                        "engine": "guardrails-ai",
                        "severity": compliance_result.severity,
                        "remediation": compliance_result.remediation,
                    }

            except ImportError:
                # SDK 未安装 → 回退到 builtin + warning
                logger.warning("guardrails-ai SDK not installed — falling back to builtin engine")
                if direction == "input":
                    result = self._guardrails_pair.check_input(content)
                else:
                    result = self._guardrails_pair.check_output(content)

                return {
                    "action": result.action.value,
                    "blocked": result.blocked,
                    "warnings": result.warnings + ["[fallback] guardrails-ai SDK not installed, used builtin engine"],
                    "violations": result.violations,
                    "redactions": result.redactions,
                    "original_content": result.original_content,
                    "processed_content": result.processed_content,
                    "engine": "builtin",
                    "fallback_reason": "guardrails-ai SDK not installed",
                }

        # 未知 engine → 回退到 builtin + warning
        logger.warning(f"Unknown guardrails engine '{engine}' — falling back to builtin")
        if direction == "input":
            result = self._guardrails_pair.check_input(content)
        else:
            result = self._guardrails_pair.check_output(content)

        return {
            "action": result.action.value,
            "blocked": result.blocked,
            "warnings": result.warnings + [f"[fallback] Unknown engine '{engine}', used builtin"],
            "violations": result.violations,
            "redactions": result.redactions,
            "original_content": result.original_content,
            "processed_content": result.processed_content,
            "engine": "builtin",
            "fallback_reason": f"Unknown engine '{engine}'",
        }

    def _tool_hook_trigger(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_hook_trigger: trigger governance logic for a lifecycle slot.

        触发路径声明（E-5）——路径1: MCP hook_trigger → 实时护栏拦截：
          这是护栏（InputGuardrails / OutputGuardrails）的唯一触发入口。
          Agent 平台在 hook 事件中调用此工具，路由到对应治理层：
          - 输入类槽位（pre_tool_use, pre_execute）→ InputGuardrails.check()
          - 输出类槽位（post_tool_use, post_execute, on_file_change）→ OutputGuardrails.check()
          - 其他槽位 → CONTINUE（无护栏检查，仅记录审计）

        护栏不被 DAGEngine 或 ComplianceEngine 触发（它们是事后检查/扫描）。

        返回治理决策：BLOCK / WARN / REDACT / CONTINUE
        """
        from harness.types import SkillSlotName

        slot = args.get("slot", "")
        content = args.get("content", "")
        tool_name = args.get("tool_name", "")
        direction = args.get("direction", "input")

        # ── 验证 slot 合法性 ──
        valid_slots = set(SkillSlotName._value2member_map_.keys())
        if slot not in valid_slots:
            return {
                "decision": "CONTINUE",
                "reason": f"Unknown slot '{slot}'. Valid slots: {sorted(valid_slots)}",
                "blocked": False,
                "warnings": [],
                "violations": [],
                "redactions": [],
            }

        # ── 路由到对应治理层 ──
        # 输入类：pre_tool_use / pre_execute → InputGuardrails
        INPUT_SLOTS = {"pre_tool_use", "pre_execute"}
        # 输出类：post_tool_use / post_execute / on_file_change → OutputGuardrails
        OUTPUT_SLOTS = {"post_tool_use", "post_execute", "on_file_change"}

        if slot in INPUT_SLOTS:
            if not content:
                return {
                    "decision": "CONTINUE",
                    "reason": f"Slot '{slot}' requires content parameter",
                    "blocked": False,
                    "warnings": [f"No content provided for input slot '{slot}'"],
                    "violations": [],
                    "redactions": [],
                }
            result = self._guardrails_pair.check_input(content)
            return {
                "decision": result.action.value,
                "blocked": result.blocked,
                "warnings": result.warnings,
                "violations": result.violations,
                "redactions": result.redactions,
                "original_content": result.original_content,
                "processed_content": result.processed_content,
                "slot": slot,
                "tool_name": tool_name,
                "direction": "input",
            }

        elif slot in OUTPUT_SLOTS:
            if not content:
                return {
                    "decision": "CONTINUE",
                    "reason": f"Slot '{slot}' requires content parameter",
                    "blocked": False,
                    "warnings": [f"No content provided for output slot '{slot}'"],
                    "violations": [],
                    "redactions": [],
                }
            result = self._guardrails_pair.check_output(content)
            return {
                "decision": result.action.value,
                "blocked": result.blocked,
                "warnings": result.warnings,
                "violations": result.violations,
                "redactions": result.redactions,
                "original_content": result.original_content,
                "processed_content": result.processed_content,
                "slot": slot,
                "tool_name": tool_name,
                "direction": "output",
            }

        else:
            # 其他槽位（session_start/end, gate, commit 等）→ 无护栏检查
            return {
                "decision": "CONTINUE",
                "reason": f"Slot '{slot}' has no guardrails check — governance is observational only",
                "blocked": False,
                "warnings": [],
                "violations": [],
                "redactions": [],
                "slot": slot,
                "tool_name": tool_name,
            }

    def _tool_gate_approve(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_gate_approve: approve or reject a pending gate request (E-9).

        触发路径声明（E-9）——路径2: MCP harness_gate_approve → GATE_APPROVAL_DECISION → EventBus:
          当 GateManager.wait_for_approval() 发出 GATE_APPROVAL_REQUEST 并阻塞在
          threading.Event 上时，此工具通过项目 EventBus 发出 GATE_APPROVAL_DECISION 事件，
          唤醒等待线程，使其返回审批决策而非超时降级。

        有效决策值：approved / rejected / cancelled
        """
        gate_id = args.get("gate_id", "")
        decision_str = args.get("decision", "")
        decided_by = args.get("decided_by", "human")
        reason = args.get("reason", "")

        if not gate_id:
            return {"success": False, "error": "gate_id is required"}

        valid_decisions = {"approved", "rejected", "cancelled"}
        if decision_str not in valid_decisions:
            return {
                "success": False,
                "error": f"Invalid decision '{decision_str}'. Valid: {sorted(valid_decisions)}",
            }

        # ── 通过 EventBus 发出 GATE_APPROVAL_DECISION 事件 ──
        try:
            from harness.types import BusEventType, BusEvent

            # 使用已有的 bus（初始化时绑定）而非重新获取
            bus = self._bus

            decision_event = BusEvent(
                type=BusEventType.GATE_APPROVAL_DECISION,
                execution_id=gate_id,
                data={
                    "gate_id": gate_id,
                    "decision": decision_str,
                    "decided_by": decided_by,
                    "reason": reason,
                },
            )
            bus.emit(decision_event)

            logger.info(
                f"GATE_APPROVAL_DECISION emitted via MCP: "
                f"gate={gate_id}, decision={decision_str}, by={decided_by}"
            )

            return {
                "success": True,
                "gate_id": gate_id,
                "decision": decision_str,
                "decided_by": decided_by,
                "reason": reason,
                "message": f"Gate '{gate_id}' approval decision '{decision_str}' has been emitted via EventBus",
            }

        except Exception as e:
            logger.error(f"harness_gate_approve failed: {e}")
            return {"success": False, "error": str(e)}

    # ── Agents pipeline tools ──────────────────────────────────

    def _tool_pipeline_run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_pipeline_run: return a PipelineDefinition for Claude Code to orchestrate.

        Returns a structured plan (not direct execution) because MCP server process
        cannot spawn Claude Code subagents. Claude Code receives this definition and
        orchestrates execution using its own Workflow/Agent tools.
        """
        task = args.get("task", "")
        if not task:
            return {"success": False, "error": "No task specified"}

        # 默认配置以 CodingAgentPipeline 为单一源——消费其 max_retries/gate_mode/agents 字段，
        # 使 dataclass 定义不悬空（harness_agents 不可用时降级硬编码默认值，保持向后兼容）
        try:
            from harness_agents.coding_agents import CodingAgentPipeline
            _defaults = CodingAgentPipeline()
            default_agents = _defaults.agents
            default_gate_mode = _defaults.gate_mode
            default_max_retries = _defaults.max_retries
        except ImportError:
            default_agents = ["analyst", "coder", "validator", "committer"]
            default_gate_mode = "hybrid"
            default_max_retries = 2

        agents = args.get("agents", default_agents)
        gate_mode = args.get("gate_mode", default_gate_mode)
        max_retries = args.get("max_retries", default_max_retries)

        # 构建步骤定义：每个 agent 对应一个编排步骤
        step_templates = {
            "analyst": {
                "description": "分析任务需求，拆解为子任务，识别约束和风险",
                "gate_checks": ["requirements_completeness", "risk_identified"],
            },
            "coder": {
                "description": "根据分析结果编写代码/配置变更",
                "gate_checks": ["code_syntax", "no_hardcoded_secrets", "follows_project_style"],
            },
            "validator": {
                "description": "验证代码变更：语法检查、合规扫描、门禁审查",
                "gate_checks": ["all_syntax_pass", "no_compliance_violations", "tests_pass"],
            },
            "committer": {
                "description": "生成 commit 信息，整理变更摘要",
                "gate_checks": ["commit_message_format", "no_sensitive_data_in_diff"],
            },
        }

        steps = []
        for agent_role in agents:
            template = step_templates.get(agent_role, {
                "description": f"执行 {agent_role} 角色",
                "gate_checks": [],
            })
            steps.append({
                "agent": agent_role,
                "task": template["description"],
                "gate_checks": template["gate_checks"],
            })

        pipeline_id = f"pipeline-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        return {
            "success": True,
            "pipeline_id": pipeline_id,
            "task": task,
            "agents": agents,
            "gate_mode": gate_mode,
            "max_retries": max_retries,
            "working_directory": args.get("working_directory", "."),
            "steps": steps,
            "instruction": (
                "Claude Code 收到此 PipelineDefinition 后，应使用 Workflow/Agent 工具编排执行："
                "1) 每个步骤对应一个 subagent；"
                "2) 步骤间有顺序依赖（analyst→coder→validator→committer）；"
                "3) gate_mode 决定门禁严格度（strict=零容忍, hybrid=允许低级别, loose=仅拦截critical）；"
                "4) 每步完成后用 harness_check/harness_gate_create 检查门禁"
            ),
        }

    def _tool_pipeline_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_pipeline_status: query pipeline execution status."""
        # Return a static info response (no persistent state in MCP server)
        return {
            "available": True,
            "default_agents": ["analyst", "coder", "validator", "committer"],
            "gate_modes": ["strict", "hybrid", "loose"],
            "default_gate_mode": "hybrid",
            "default_max_retries": 2,
            "note": "Use harness_pipeline_run to start a pipeline. "
                    "Status is returned in the run result — "
                    "no persistent pipeline state is tracked by the MCP server.",
        }

    def _tool_agent_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_agent_list: list available agent roles and tool configs."""
        try:
            from harness_agents.coding_agents import AGENT_CLASSES
            from harness_agents.tool_executor import ToolExecutor
        except ImportError:
            return {"available": False, "error": "harness_agents package not available"}

        agents_info = {}
        for role, cls in AGENT_CLASSES.items():
            try:
                executor = ToolExecutor() if "ToolExecutor" in dir() else None
                tools = cls.TOOL_WHITELIST if hasattr(cls, "TOOL_WHITELIST") else []
                prompt = cls.DEFAULT_SYSTEM_PROMPT if hasattr(cls, "DEFAULT_SYSTEM_PROMPT") else ""
                agents_info[role] = {
                    "class": cls.__name__,
                    "tools": tools,
                    "system_prompt_preview": prompt[:200] if prompt else "(default)",
                }
            except Exception as exc:
                agents_info[role] = {"class": cls.__name__, "error": str(exc)}

        return {
            "available": True,
            "agents": agents_info,
            "total": len(agents_info),
        }

    # ── Profile / Skill / Bridge 工具 ──────────────────────────

    def _tool_profile_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_profile_list: list available Profiles."""
        try:
            from harness.config import list_profiles
            profiles = list_profiles()
            return {"profiles": profiles, "total": len(profiles)}
        except Exception as exc:
            return {"profiles": ["default"], "error": str(exc)}

    def _tool_profile_load(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_profile_load: load a harness Profile."""
        try:
            from harness.config import load_profile, resolve_active_profile
            name = args.get("name")
            if name is None:
                name = resolve_active_profile()
            profile = load_profile(name)
            result: Dict[str, Any] = {
                "name": profile.name,
                "description": profile.description,
                "default_agent": profile.default_agent,
                "pipeline_agents": profile.pipeline_agents,
                "hooks": profile.hooks,
                "default_gate_mode": profile.default_gate_mode.value,
                "gate_checks": profile.gate_checks,
                "skill_slots": profile.skill_slots,
                "resolved_via": "auto-resolve" if args.get("name") is None else "explicit",
            }
            if profile.constraints:
                result["constraints"] = profile.constraints
            if profile.default_spec:
                result["spec_defaults"] = {
                    "objective_template": profile.default_spec.objective,
                    "acceptance_criteria": profile.default_spec.acceptance_criteria,
                }
            if profile.workflow:
                result["workflow_steps"] = [
                    {"name": s.name, "skill": s.skill, "condition": s.condition}
                    for s in profile.workflow.steps
                ]
            return result
        except Exception as exc:
            return {"error": str(exc)}

    def _tool_skill_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_skill_list: list registered Skills (builtin + superpowers bridge)."""
        try:
            from harness.skill_registry import get_skill_registry, register_builtin_skills
            from harness.superpowers_bridge import register_superpowers_skills
            registry = get_skill_registry()
            register_builtin_skills(registry)
            # ── Superpowers 桥接: 发现并注册 superpowers skills ──
            register_superpowers_skills(registry)

            slot_filter = args.get("slot")
            tag_filter = args.get("tag")

            if slot_filter:
                from harness.types import SkillSlotName
                try:
                    slot_enum = SkillSlotName(slot_filter)
                    records = registry.find_by_slot(slot_enum)
                except ValueError:
                    records = registry.list_active()
            elif tag_filter:
                records = registry.find_by_tag(tag_filter)
            else:
                records = registry.list_active()

            return {
                "skills": [
                    {
                        "id": r.definition.id,
                        "name": r.definition.name,
                        "description": r.definition.description,
                        "slot": r.definition.slot.value,
                        "tags": r.definition.tags,
                        "active": r.active,
                        "is_ready": r.is_ready,
                        "source": r.definition.metadata.get("source", "builtin"),
                    }
                    for r in records
                ],
                "total": len(records),
                "slots": registry.list_slots(),
            }
        except Exception as exc:
            return {"skills": [], "error": str(exc)}

    def _tool_skill_register(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_skill_register: register a new Skill."""
        try:
            from harness.skill_registry import get_skill_registry
            from harness.types import SkillDefinition, SkillSlotName

            skill_id = args.get("skill_id", "")
            name = args.get("name", skill_id)
            if not skill_id:
                return {"success": False, "error": "skill_id is required"}

            slot_str = args.get("slot", "post_execute")
            try:
                slot = SkillSlotName(slot_str)
            except ValueError:
                slot = SkillSlotName.POST_EXECUTE

            skill_def = SkillDefinition(
                id=skill_id,
                name=name,
                description=args.get("description", ""),
                entry_point=args.get("entry_point", ""),
                slot=slot,
                tags=args.get("tags", []),
            )

            registry = get_skill_registry()
            record = registry.register(skill_def)

            return {
                "success": True,
                "skill_id": record.definition.id,
                "name": record.definition.name,
                "slot": record.definition.slot.value,
                "active": record.active,
                "is_ready": record.is_ready,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _tool_bridge_deploy(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_bridge_deploy: deploy Profile to Agent platform. Supports multiple adapters."""
        try:
            from harness.bridge import get_bridge, get_adapter_registry
            from harness.config import load_profile, resolve_active_profile

            # ── 列出可用适配器 ────────────────────────────────────
            registry = get_adapter_registry()
            registry.discover()  # 确保发现完毕
            available_adapters = registry.list_adapters()

            profile_name = args.get("profile_name")
            adapter_name = args.get("adapter", "claude-code")

            if profile_name is None:
                profile_name = resolve_active_profile()
            profile = load_profile(profile_name)

            # 将 adapter 参数注入 Profile（覆盖默认）
            profile.adapter = adapter_name

            bridge = get_bridge()
            result = bridge.deploy(profile)

            return {
                "success": True,
                "resolved_via": "auto-resolve" if args.get("profile_name") is None else "explicit",
                "adapter": adapter_name,
                "available_adapters": available_adapters,
                **result,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _tool_trace_export(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_trace_export: export audit entries as OTel/Traceloop trace format.

        format='otel-json' → 使用 OTelBridge.export_audit_entry() 生成 span dict
        format='traceloop' → 使用 TraceloopExporter.export_audit_entry() 添加 traceloop.* 属性

        搜索从 primary store（local）执行，然后按格式转换每个 entry。
        """
        format_type = args.get("format", "otel-json")
        query = args.get("query", "")
        date_from = args.get("date_from")
        date_to = args.get("date_to")
        limit = args.get("limit", 50)

        # 搜索审计记录（始终从 primary store）
        entries = self._audit_engine.search(
            query,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

        # 按格式导出
        if format_type == "traceloop":
            try:
                from harness.integrations.traceloop_exporter import TraceloopExporter
                from harness.otel_integration import OTelBridge
                exporter = TraceloopExporter(OTelBridge())
                spans = [exporter.export_audit_entry(entry) for entry in entries]
            except ImportError:
                # TraceloopExporter 不可用 → 降级到 otel-json
                from harness.otel_integration import OTelBridge, _audit_entry_to_span_dict
                bridge = OTelBridge()
                spans = [bridge.export_audit_entry(entry) for entry in entries]
                format_type = "otel-json (fallback: traceloop SDK unavailable)"
        elif format_type == "otel-json":
            from harness.otel_integration import OTelBridge
            bridge = OTelBridge()
            spans = [bridge.export_audit_entry(entry) for entry in entries]
        else:
            return {
                "success": False,
                "error": f"Unknown format: '{format_type}'. Supported: 'otel-json', 'traceloop'",
            }

        return {
            "success": True,
            "format": format_type,
            "count": len(spans),
            "spans": spans,
            "configured_backends": self._audit_engine_config.backends,
        }

    # ── Knowledge tools: Agent 主动查询项目知识 ───────────────────────

    def _tool_knowledge_query(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_knowledge_query: 查询知识条目，支持类型/范围/标签/来源过滤。

        Agent 主动调用此工具获取项目知识——这是 harness-cook 不替 Agent 做事的体现：
        harness 提供知识查询能力，Agent 决定何时查询、查询什么。
        """
        try:
            project = args.get("project")
            provider = get_knowledge_provider(project)

            query_str = args.get("query", "")
            type_filter = args.get("type_filter")
            scope_filter = args.get("scope_filter")
            tags_filter = args.get("tags_filter")
            source_filter = args.get("source_filter")
            limit = args.get("limit", 20)

            # 构造 KnowledgeQuery
            type_enum = None
            if type_filter:
                try:
                    type_enum = KnowledgeType(type_filter)
                except ValueError:
                    pass  # 无效类型 → 不过滤

            scope_enum = None
            if scope_filter:
                try:
                    scope_enum = KnowledgeScope(scope_filter)
                except ValueError:
                    pass

            kq = KnowledgeQuery(
                query=query_str,
                type_filter=type_enum,
                scope_filter=scope_enum,
                tags_filter=tags_filter,
                source_filter=source_filter,
                limit=limit,
            )

            result = provider.query(kq)

            return {
                "entries": [
                    {
                        "id": e.id,
                        "type": e.type.value,
                        "scope": e.scope.value,
                        "title": e.title,
                        "content": e.content[:500] if len(e.content) > 500 else e.content,
                        "tags": e.tags,
                        "confidence": e.confidence,
                        "source": e.source,
                        "hit_count": e.metadata.get("hit_count", 0),
                        "created_at": e.created_at,
                    }
                    for e in result.entries
                ],
                "total_matches": result.total_matches,
                "query": result.query,
                "search_method": result.search_method,
            }
        except Exception as exc:
            return {"entries": [], "total_matches": 0, "error": str(exc)}

    def _tool_knowledge_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_knowledge_search: 关键词搜索或 TF-IDF 语义搜索。

        method='keyword' → 精确关键词匹配（标题+内容+标签）
        method='semantic' → TF-IDF 向量相似度搜索（概念相关，更广覆盖）
        """
        try:
            project = args.get("project")
            provider = get_knowledge_provider(project)

            query_str = args.get("query", "")
            method = args.get("method", "keyword")
            limit = args.get("limit", 10)

            if not query_str:
                return {"entries": [], "total_matches": 0, "error": "query is required"}

            if method == "semantic":
                result = provider.semantic_search(query_str, limit=limit)
            else:
                # keyword search via query()
                kq = KnowledgeQuery(query=query_str, limit=limit)
                result = provider.query(kq)

            return {
                "entries": [
                    {
                        "id": e.id,
                        "type": e.type.value,
                        "scope": e.scope.value,
                        "title": e.title,
                        "content": e.content[:500] if len(e.content) > 500 else e.content,
                        "tags": e.tags,
                        "confidence": e.confidence,
                        "source": e.source,
                        "hit_count": e.metadata.get("hit_count", 0),
                        "created_at": e.created_at,
                    }
                    for e in result.entries
                ],
                "total_matches": result.total_matches,
                "query": result.query,
                "search_method": result.search_method,
            }
        except Exception as exc:
            return {"entries": [], "total_matches": 0, "error": str(exc)}

    def _tool_knowledge_stats(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_knowledge_stats: 知识库统计概览。

        展示条目数、类型分布、来源分布、高频条目、归档条目。
        Agent 可先调此工具了解知识库规模，再决定查询什么。
        """
        try:
            project = args.get("project")
            provider = get_knowledge_provider(project)

            stats = provider.stats()

            # 构造人类友好的摘要
            knowledge_types = [
                "architecture", "convention", "dependency", "api",
                "pattern", "risk", "decision", "task", "test", "glossary",
            ]
            knowledge_scopes = ["project", "module", "file", "function"]

            return {
                "total_entries": stats.get("total_entries", 0),
                "type_distribution": stats.get("type_distribution", {}),
                "scope_distribution": stats.get("scope_distribution", {}),
                "sources_distribution": stats.get("sources_distribution", {}),
                "high_freq_entries": stats.get("high_freq_entries", []),
                "archived_total": stats.get("archived_total", 0),
                "archived_types": stats.get("archived_types", {}),
                "total_tags": stats.get("total_tags", 0),
                "available_types": knowledge_types,
                "available_scopes": knowledge_scopes,
                "hint": (
                    "Use harness_knowledge_query to filter by type/scope/tags/source, "
                    "or harness_knowledge_search for keyword/semantic search."
                ),
            }
        except Exception as exc:
            return {"error": str(exc)}

    # ── S-4: Insight → Rule activation ────────────────────────

    def _tool_knowledge_activate(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_knowledge_activate: S-4 一键激活 Insight 为 ComplianceRule。

        流程：
        1. 从知识库获取 Insight 条目
        2. 创建 InsightActivation 记录
        3. 转换为 RulePack（insight_to_rule_pack）
        4. 加载到 ComplianceEngine
        5. 返回激活结果
        """
        insight_id = args.get("insight_id", "")
        severity = args.get("severity", "medium")
        project = args.get("project")

        if not insight_id:
            return {"success": False, "error": "insight_id is required"}

        try:
            # 1. 获取 Insight 条目
            provider = get_knowledge_provider(project)
            entry = provider.get(insight_id)

            if not entry:
                return {
                    "success": False,
                    "error": f"Insight '{insight_id}' not found in knowledge base",
                    "hint": "Use harness_knowledge_query or harness_knowledge_search to find Insight entries first.",
                }

            # 2. 检查是否已激活
            store = InsightActivationStore(project_name=project or provider._project)
            store.initialize()
            if store.is_activated(insight_id):
                existing = store.get_activation(insight_id)
                return {
                    "success": False,
                    "error": f"Insight '{insight_id}' is already activated as RulePack '{existing.rule_pack_name}'",
                    "existing_activation": {
                        "rule_pack_name": existing.rule_pack_name,
                        "severity": existing.severity,
                        "activated_at": existing.activated_at,
                    },
                    "hint": "Use harness_knowledge_deactivate to undo the existing activation first.",
                }

            # 3. 创建激活记录
            activation = store.activate(entry, severity=severity)

            # 4. 转换为 RulePack
            pack = insight_to_rule_pack(entry, activation)

            # 5. 加载到 ComplianceEngine
            engine = ComplianceEngine()
            engine.load_pack(pack)

            return {
                "success": True,
                "insight_id": insight_id,
                "insight_title": entry.title,
                "rule_pack_name": activation.rule_pack_name,
                "rule_id": activation.rule_id,
                "severity": severity,
                "activated_at": activation.activated_at,
                "rule_category": pack.category.value if hasattr(pack.category, 'value') else str(pack.category),
                "rule_description": entry.title,
                "rule_remediation": entry.metadata.get("remediation", ""),
                "hint": "Use harness_knowledge_deactivate to undo this activation.",
            }

        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _tool_knowledge_deactivate(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_knowledge_deactivate: S-4 撤销 Insight 的 RulePack 激活。

        流程：
        1. 从 InsightActivationStore 获取激活记录
        2. 从 ComplianceEngine 卸载 RulePack
        3. 删除激活记录
        4. 返回撤销结果
        """
        insight_id = args.get("insight_id", "")
        project = args.get("project")

        if not insight_id:
            return {"success": False, "error": "insight_id is required"}

        try:
            # 1. 获取并检查激活记录
            provider = get_knowledge_provider(project)
            store = InsightActivationStore(project_name=project or provider._project)
            store.initialize()

            activation = store.get_activation(insight_id)
            if not activation:
                return {
                    "success": False,
                    "error": f"Insight '{insight_id}' is not activated (no activation record found)",
                    "hint": "Use harness_knowledge_activate to activate an Insight first.",
                }

            # 2. 从 ComplianceEngine 卸载 RulePack
            engine = ComplianceEngine()
            try:
                engine.unload_pack(activation.rule_pack_name)
            except Exception as unload_exc:
                logger.warning(f"S-4: unload_pack failed (may not be loaded): {unload_exc}")

            # 3. 删除激活记录
            removed = store.deactivate(insight_id)

            return {
                "success": True,
                "insight_id": insight_id,
                "deactivated_rule_pack": removed.rule_pack_name if removed else "",
                "deactivated_rule_id": removed.rule_id if removed else "",
                "deactivated_at": datetime.now().isoformat(),
                "original_severity": removed.severity if removed else "",
                "hint": "The Insight is now available for re-activation via harness_knowledge_activate.",
            }

        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ── YAML workflow parser ────────────────────────────────────

    def _tool_rule_import(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """harness_rule_import: import compliance rules from external engines.

        Sources: sonarqube, archunit, dep_cruiser.
        Returns a RulePack with translated ComplianceRule objects.
        """
        source = args.get("source", "")
        project_key = args.get("project_key", "")
        config = args.get("config", {})
        languages = args.get("languages")

        try:
            if source == "sonarqube":
                from harness.integrations.rule_importer import SonarQubeRuleImporter
                importer = SonarQubeRuleImporter(config=config)
                pack = importer.import_rules(
                    project_key=project_key,
                    languages=languages,
                )
            elif source == "archunit":
                from harness.integrations.rule_importer import ArchUnitRuleImporter
                importer = ArchUnitRuleImporter()
                # project_key 作为 project_root 或 test_file
                test_file = config.get("test_file", "")
                pack = importer.import_rules(
                    test_file=test_file,
                    project_root=project_key,
                )
            elif source == "dep_cruiser":
                from harness.integrations.rule_importer import DepCruiserRuleImporter
                importer = DepCruiserRuleImporter()
                config_file = config.get("config_file", "")
                pack = importer.import_rules(
                    config_file=config_file,
                    project_root=project_key,
                )
            else:
                return {
                    "success": False,
                    "error": f"Unknown source: '{source}'. Supported: 'sonarqube', 'archunit', 'dep_cruiser'",
                }

            # 将导入的规则翻译为 JSON 格式返回
            rules_json = []
            for rule in pack.rules:
                rules_json.append({
                    "id": rule.id,
                    "name": rule.name,
                    "pattern": rule.pattern,
                    "severity": rule.severity,
                    "description": rule.description,
                    "matcher_type": rule.matcher_type,
                    "matcher_config": rule.matcher_config,
                })

            return {
                "success": True,
                "source": source,
                "pack_name": pack.name,
                "rules_count": len(pack.rules),
                "rules": rules_json,
                "metadata": pack.metadata,
            }

        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _parse_workflow_yaml(self, yaml_str: str) -> DAGWorkflow:
        """Parse a YAML string into a DAGWorkflow object."""
        if not yaml_str:
            # Return an empty workflow for testing
            return DAGWorkflow(id="empty", name="empty", nodes=[], edges=[])

        if not HAS_YAML:
            raise ValueError("PyYAML not installed — cannot parse workflow YAML")

        data = yaml.safe_load(yaml_str)
        if not isinstance(data, dict):
            return DAGWorkflow(id="empty", name="empty", nodes=[], edges=[])

        wf_id = data.get("id", "wf-from-mcp")
        wf_name = data.get("name", wf_id)

        # Parse nodes
        nodes_data = data.get("nodes", [])
        nodes: List[DAGNode] = []
        for nd in nodes_data:
            gate = None
            if "gate" in nd:
                gate = self._parse_gate_yaml(nd["gate"])
            nodes.append(DAGNode(
                id=nd.get("id", "node-0"),
                agent_type=nd.get("agent_type", "coder"),
                task=nd.get("task", ""),
                inputs=nd.get("inputs", []),
                outputs=nd.get("outputs", []),
                gate=gate,
            ))

        # Parse edges
        edges_data = data.get("edges", [])
        edges: List[DAGEdge] = []
        for ed in edges_data:
            edges.append(DAGEdge(
                from_node=ed.get("from", "node-0"),
                to_node=ed.get("to", "node-1"),
                condition=ed.get("condition"),
            ))

        global_gate = None
        if "global_gate" in data:
            global_gate = self._parse_gate_yaml(data["global_gate"])

        return DAGWorkflow(
            id=wf_id,
            name=wf_name,
            nodes=nodes,
            edges=edges,
            global_gate=global_gate,
        )

    def _parse_gate_yaml(self, gate_data: Any) -> GateDefinition:
        """Parse gate data from YAML into a GateDefinition."""
        if not isinstance(gate_data, dict):
            return GateDefinition(id="gate-default", checks=[])

        mode_str = gate_data.get("mode", "hybrid")
        mode_map = {"strict": GateMode.STRICT, "hybrid": GateMode.HYBRID, "loose": GateMode.LOOSE}
        mode = mode_map.get(mode_str, GateMode.HYBRID)

        checks_data = gate_data.get("checks", [])
        gate_checks: List[GateCheck] = []
        for chk in checks_data:
            if isinstance(chk, str):
                chk = {"id": chk, "category": "logic", "severity": "medium", "description": chk}
            chk_id = chk.get("id", "chk-0")
            chk_severity = chk.get("severity", "medium")
            chk_desc = chk.get("description", chk_id)
            chk_category = chk.get("category", "logic")

            def _make_fn(cid: str, desc: str, sev: str):
                def _fn(artifact: Artifact) -> Any:
                    from harness.types import CheckResult
                    return CheckResult(passed=True, severity=sev, message=desc)
                return _fn

            gate_checks.append(GateCheck(
                id=chk_id,
                category=chk_category,
                severity=chk_severity,
                description=chk_desc,
                check_fn=_make_fn(chk_id, chk_desc, chk_severity),
            ))

        return GateDefinition(
            id=gate_data.get("id", "gate-from-yaml"),
            checks=gate_checks,
            mode=mode,
            max_retries=gate_data.get("max_retries", 3),
        )


# ════════════════════════════════════════════════════════════════
#  MCP SDK Server — 协议层 + stdio transport
# ════════════════════════════════════════════════════════════════

def create_mcp_server(logic: HarnessMCPServer) -> Server:
    """创建 MCP SDK Server 实例，注册工具列表和调用处理器"""

    server = Server("harness-cook", version=SERVER_VERSION)

    # ── 工具 dispatch table ────────────────────────────────────
    _TOOL_DISPATCH = {
        "harness_check":            logic._tool_check,
        "harness_audit":            logic._tool_audit,
        "harness_plan":             logic._tool_plan,
        "harness_run":              logic._tool_run,
        "harness_status":           logic._tool_status,
        "harness_register":         logic._tool_register,
        "harness_gate_create":      logic._tool_gate_create,
        "harness_gate_approve":     logic._tool_gate_approve,
        "harness_guardrails_check": logic._tool_guardrails_check,
        "harness_hook_trigger":    logic._tool_hook_trigger,
        "harness_pipeline_run":     logic._tool_pipeline_run,
        "harness_pipeline_status":  logic._tool_pipeline_status,
        "harness_agent_list":       logic._tool_agent_list,
        "harness_profile_list":     logic._tool_profile_list,
        "harness_profile_load":     logic._tool_profile_load,
        "harness_skill_list":       logic._tool_skill_list,
        "harness_skill_register":   logic._tool_skill_register,
        "harness_bridge_deploy":    logic._tool_bridge_deploy,
        "harness_trace_export":     logic._tool_trace_export,
        "harness_rule_import":      logic._tool_rule_import,
        "harness_knowledge_query":  logic._tool_knowledge_query,
        "harness_knowledge_search": logic._tool_knowledge_search,
        "harness_knowledge_stats":  logic._tool_knowledge_stats,
        "harness_knowledge_activate":   logic._tool_knowledge_activate,
        "harness_knowledge_deactivate": logic._tool_knowledge_deactivate,
    }

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """返回所有已注册的工具定义"""
        return TOOL_DEFINITIONS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent | ImageContent | EmbeddedResource]:
        """执行工具调用，返回结果"""
        handler = _TOOL_DISPATCH.get(name)
        if handler is None:
            raise ValueError(f"Unknown tool: {name}")

        result = handler(arguments)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    return server


async def serve(logic: Optional[HarnessMCPServer] = None) -> None:
    """启动 MCP Server — stdio transport 模式"""
    if logic is None:
        logic = HarnessMCPServer()

    server = create_mcp_server(logic)

    async with stdio_server() as (read_stream, write_stream):
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options)


# ── CLI entry point ─────────────────────────────────────────────

def main() -> None:
    """Run harness-cook MCP server from the command line."""
    asyncio.run(serve())


if __name__ == "__main__":
    main()

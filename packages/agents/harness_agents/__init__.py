"""
harness-agents: Agent execution layer for harness-cook.

Provides the "engine and steering wheel" that runs on top of the
harness-cook SDK "brake system".  Three-layer architecture:

  1. ToolExecutor  — file I/O, shell commands, search
  2. AgentRuntime  — ReAct loop (think → tool_call → observe → think)
  3. Orchestrator  — multi-agent pipeline (Analyst → Coder → Validator → Committer)

Each layer uses harness-cook SDK types (DAGWorkflow, GateCheck, etc.)
and respects constraints / gates / compliance / guardrails automatically.
"""

from .tool_executor import ToolExecutor, ToolCall, ToolResult
from .react_runtime import AgentRuntime, ReActState, AgentConfig
from .coding_agents import (
    AnalystAgent,
    CoderAgent,
    ValidatorAgent,
    CommitterAgent,
)
from .orchestrator import Orchestrator, PipelineConfig, PipelineResult

__all__ = [
    "ToolExecutor",
    "ToolCall",
    "ToolResult",
    "AgentRuntime",
    "ReActState",
    "AgentConfig",
    "AnalystAgent",
    "CoderAgent",
    "ValidatorAgent",
    "CommitterAgent",
    "Orchestrator",
    "PipelineConfig",
    "PipelineResult",
]
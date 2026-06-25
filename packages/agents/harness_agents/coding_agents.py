"""
Coding Agents — Four specialized agents that work together in a pipeline.

Analyst → Coder → Validator → Committer

Each agent uses AgentRuntime (ReAct loop) which delegates LLM calls to an
ILLMProvider.  The agent's system_prompt defines its role; the runtime handles
the think→tool_call→observe→think cycle.

These agents do NOT call LLM directly — they configure a runtime with the
appropriate tool whitelist and system prompt, then execute via the runtime.
"""

from __future__ import annotations

import uuid
import time
from dataclasses import dataclass, field
from typing import Optional, List

# ── Conditional TaskResult import ──
# Try to use the SDK's TaskResult first; fall back to a local definition
# so the module works even when the harness-cook core package is not installed.
try:
    from harness import TaskResult, Artifact
except ImportError:
    from dataclasses import dataclass as _dc, field as _f

    @_dc
    class Artifact:          # noqa: F811 — minimal local fallback
        type: str
        path: str
        content: str
        metadata: dict = _f(default_factory=dict)

    @_dc
    class TaskResult:        # noqa: F811 — minimal local fallback
        task_id: str
        agent_id: str
        status: str          # "completed" | "failed" | "escalated"
        artifacts: List[Artifact]  # type: ignore[assignment]
        duration_ms: int
        tokens_used: int = 0
        error: Optional[str] = None
        metadata: dict = _f(default_factory=dict)

# ── Internal imports ──
from .react_runtime import AgentRuntime, AgentConfig
from .tool_executor import ToolExecutor


# ═══════════════════════════════════════════════════════════════════════
#  Base helper
# ═══════════════════════════════════════════════════════════════════════

def _generate_id(prefix: str) -> str:
    """Short deterministic-ish ID for task/agent tracking."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ═══════════════════════════════════════════════════════════════════════
#  AnalystAgent
# ═══════════════════════════════════════════════════════════════════════

class AnalystAgent:
    """Analyzes requirements and produces a task plan.

    Reads existing code, searches for relevant files, and produces an
    analysis report listing affected files, changes needed, and risks.
    """

    SYSTEM_PROMPT = (
        "You are an expert code analyst. Given a task description, analyze "
        "the requirements, identify affected files, and produce a detailed "
        "implementation plan."
    )

    TOOL_WHITELIST = ["read_file", "search_code", "list_files"]

    def __init__(
        self,
        tool_executor: ToolExecutor,
        config: Optional[AgentConfig] = None,
    ) -> None:
        self._tool_executor = tool_executor
        self._config = config or AgentConfig(
            max_rounds=10,
            allowed_tools=self.TOOL_WHITELIST,
        )
        self._agent_id = _generate_id("analyst")

    def get_tools(self) -> List[str]:
        """Available tool names for this agent."""
        return list(self.TOOL_WHITELIST)

    def get_system_prompt(self) -> str:
        """System prompt that defines the agent's role."""
        return self.SYSTEM_PROMPT

    def execute(
        self,
        task: str,
        context: Optional[str] = None,
    ) -> TaskResult:
        """Run the analyst on a task description.

        Returns a TaskResult with an analysis report as the primary artifact.
        """
        task_id = _generate_id("task")
        start_ms = int(time.monotonic() * 1000)

        # Build the full prompt (task + optional context from prior agents)
        full_task = task
        if context:
            full_task = f"{task}\n\n--- Prior context ---\n{context}"

        runtime = AgentRuntime(
            tool_executor=self._tool_executor,
            config=self._config,
            system_prompt=self.SYSTEM_PROMPT,
        )

        try:
            output = runtime.run(full_task)
            duration_ms = int(time.monotonic() * 1000) - start_ms

            return TaskResult(
                task_id=task_id,
                agent_id=self._agent_id,
                status="completed",
                artifacts=[
                    Artifact(
                        type="doc",
                        path="analysis_report.md",
                        content=output,
                        metadata={"agent": "analyst"},
                    )
                ],
                duration_ms=duration_ms,
                tokens_used=runtime.tokens_used if hasattr(runtime, "tokens_used") else 0,
                metadata={"agent_role": "analyst"},
            )
        except Exception as exc:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            return TaskResult(
                task_id=task_id,
                agent_id=self._agent_id,
                status="failed",
                artifacts=[],
                duration_ms=duration_ms,
                error=str(exc),
                metadata={"agent_role": "analyst"},
            )


# ═══════════════════════════════════════════════════════════════════════
#  CoderAgent
# ═══════════════════════════════════════════════════════════════════════

class CoderAgent:
    """Writes code based on the analyst's plan.

    Has access to all tools (read, write, edit, search, run, list) so it
    can make precise, targeted edits following the implementation plan.
    """

    SYSTEM_PROMPT = (
        "You are an expert programmer. Given an implementation plan, write "
        "the code changes. Use edit_file to make precise, targeted edits."
    )

    TOOL_WHITELIST = [
        "read_file",
        "write_file",
        "edit_file",
        "search_code",
        "run_command",
        "list_files",
    ]

    def __init__(
        self,
        tool_executor: ToolExecutor,
        config: Optional[AgentConfig] = None,
    ) -> None:
        self._tool_executor = tool_executor
        self._config = config or AgentConfig(
            max_rounds=20,
            allowed_tools=self.TOOL_WHITELIST,
        )
        self._agent_id = _generate_id("coder")

    def get_tools(self) -> List[str]:
        """Available tool names for this agent."""
        return list(self.TOOL_WHITELIST)

    def get_system_prompt(self) -> str:
        """System prompt that defines the agent's role."""
        return self.SYSTEM_PROMPT

    def execute(
        self,
        task: str,
        context: Optional[str] = None,
    ) -> TaskResult:
        """Run the coder on an implementation plan.

        The `task` should be the analyst's plan; `context` can carry
        additional details from prior stages.
        """
        task_id = _generate_id("task")
        start_ms = int(time.monotonic() * 1000)

        full_task = task
        if context:
            full_task = f"{task}\n\n--- Prior context ---\n{context}"

        runtime = AgentRuntime(
            tool_executor=self._tool_executor,
            config=self._config,
            system_prompt=self.SYSTEM_PROMPT,
        )

        try:
            output = runtime.run(full_task)
            duration_ms = int(time.monotonic() * 1000) - start_ms

            return TaskResult(
                task_id=task_id,
                agent_id=self._agent_id,
                status="completed",
                artifacts=[
                    Artifact(
                        type="code",
                        path="code_changes.diff",
                        content=output,
                        metadata={"agent": "coder"},
                    )
                ],
                duration_ms=duration_ms,
                tokens_used=runtime.tokens_used if hasattr(runtime, "tokens_used") else 0,
                metadata={"agent_role": "coder"},
            )
        except Exception as exc:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            return TaskResult(
                task_id=task_id,
                agent_id=self._agent_id,
                status="failed",
                artifacts=[],
                duration_ms=duration_ms,
                error=str(exc),
                metadata={"agent_role": "coder"},
            )


# ═══════════════════════════════════════════════════════════════════════
#  ValidatorAgent
# ═══════════════════════════════════════════════════════════════════════

class ValidatorAgent:
    """Verifies the coder's work.

    Runs tests, checks for lint errors, verifies type safety.  Produces
    a validation report (passed/failed, issues found).
    """

    SYSTEM_PROMPT = (
        "You are a strict code reviewer and test runner. Verify that code "
        "changes work correctly. Run tests, check for lint errors, verify "
        "type safety."
    )

    TOOL_WHITELIST = ["read_file", "run_command", "search_code"]

    def __init__(
        self,
        tool_executor: ToolExecutor,
        config: Optional[AgentConfig] = None,
    ) -> None:
        self._tool_executor = tool_executor
        self._config = config or AgentConfig(
            max_rounds=12,
            allowed_tools=self.TOOL_WHITELIST,
        )
        self._agent_id = _generate_id("validator")

    def get_tools(self) -> List[str]:
        """Available tool names for this agent."""
        return list(self.TOOL_WHITELIST)

    def get_system_prompt(self) -> str:
        """System prompt that defines the agent's role."""
        return self.SYSTEM_PROMPT

    def execute(
        self,
        task: str,
        context: Optional[str] = None,
    ) -> TaskResult:
        """Run validation on the coder's changes.

        The `task` describes what to validate; `context` carries the
        coder's output (diffs / change summary).
        """
        task_id = _generate_id("task")
        start_ms = int(time.monotonic() * 1000)

        full_task = task
        if context:
            full_task = f"{task}\n\n--- Changes to validate ---\n{context}"

        runtime = AgentRuntime(
            tool_executor=self._tool_executor,
            config=self._config,
            system_prompt=self.SYSTEM_PROMPT,
        )

        try:
            output = runtime.run(full_task)
            duration_ms = int(time.monotonic() * 1000) - start_ms

            # Determine pass/fail from the validation output
            status = "completed"
            if "FAIL" in output.upper() or "ERROR" in output.upper():
                # Not a hard failure of the *agent*, but signal issues
                status = "completed"  # agent completed its job; issues in metadata
                pass  # metadata carries the detail

            return TaskResult(
                task_id=task_id,
                agent_id=self._agent_id,
                status=status,
                artifacts=[
                    Artifact(
                        type="doc",
                        path="validation_report.md",
                        content=output,
                        metadata={"agent": "validator"},
                    )
                ],
                duration_ms=duration_ms,
                tokens_used=runtime.tokens_used if hasattr(runtime, "tokens_used") else 0,
                metadata={
                    "agent_role": "validator",
                    "validation_result": "passed" if "PASS" in output.upper() else "issues_found",
                },
            )
        except Exception as exc:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            return TaskResult(
                task_id=task_id,
                agent_id=self._agent_id,
                status="failed",
                artifacts=[],
                duration_ms=duration_ms,
                error=str(exc),
                metadata={"agent_role": "validator"},
            )


# ═══════════════════════════════════════════════════════════════════════
#  CommitterAgent
# ═══════════════════════════════════════════════════════════════════════

class CommitterAgent:
    """Creates a git commit with verified changes.

    Reviews all changes, writes a concise commit message, and prepares
    the commit.  Only has access to git commands and file reading.
    """

    SYSTEM_PROMPT = (
        "You are a commit specialist. Review all changes, write a concise "
        "commit message, and prepare the commit."
    )

    TOOL_WHITELIST = ["run_command", "read_file"]

    def __init__(
        self,
        tool_executor: ToolExecutor,
        config: Optional[AgentConfig] = None,
    ) -> None:
        self._tool_executor = tool_executor
        self._config = config or AgentConfig(
            max_rounds=8,
            allowed_tools=self.TOOL_WHITELIST,
        )
        self._agent_id = _generate_id("committer")

    def get_tools(self) -> List[str]:
        """Available tool names for this agent."""
        return list(self.TOOL_WHITELIST)

    def get_system_prompt(self) -> str:
        """System prompt that defines the agent's role."""
        return self.SYSTEM_PROMPT

    def execute(
        self,
        task: str,
        context: Optional[str] = None,
    ) -> TaskResult:
        """Run the committer to finalize and commit changes.

        The `task` describes what was done; `context` carries the
        validation report confirming the changes are safe.
        """
        task_id = _generate_id("task")
        start_ms = int(time.monotonic() * 1000)

        full_task = task
        if context:
            full_task = f"{task}\n\n--- Validation context ---\n{context}"

        runtime = AgentRuntime(
            tool_executor=self._tool_executor,
            config=self._config,
            system_prompt=self.SYSTEM_PROMPT,
        )

        try:
            output = runtime.run(full_task)
            duration_ms = int(time.monotonic() * 1000) - start_ms

            return TaskResult(
                task_id=task_id,
                agent_id=self._agent_id,
                status="completed",
                artifacts=[
                    Artifact(
                        type="doc",
                        path="commit_summary.md",
                        content=output,
                        metadata={"agent": "committer"},
                    )
                ],
                duration_ms=duration_ms,
                tokens_used=runtime.tokens_used if hasattr(runtime, "tokens_used") else 0,
                metadata={"agent_role": "committer"},
            )
        except Exception as exc:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            return TaskResult(
                task_id=task_id,
                agent_id=self._agent_id,
                status="failed",
                artifacts=[],
                duration_ms=duration_ms,
                error=str(exc),
                metadata={"agent_role": "committer"},
            )


# ═══════════════════════════════════════════════════════════════════════
#  CodingAgentPipeline — dataclass that defines the pipeline configuration
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class CodingAgentPipeline:
    """Configuration for the Analyst → Coder → Validator → Committer pipeline.

    Attributes:
        agents: Ordered list of agent role names that participate.
                Default is the full four-agent pipeline.
        gate_mode: How strictly gates are enforced between stages.
                   Matches harness SDK GateMode values:
                   'strict' — all checks must pass, otherwise block
                   'hybrid'  — lint/style auto-fix, logic errors escalate
                   'loose'   — basic checks only, don't block delivery
        max_retries: How many times to retry a failed stage before escalating.
        require_validation: If True, the validator stage must pass before
                            the committer runs.
    """

    agents: List[str] = field(
        default_factory=lambda: ["analyst", "coder", "validator", "committer"]
    )
    gate_mode: str = "hybrid"         # strict | hybrid | loose
    max_retries: int = 2
    require_validation: bool = True


# ═══════════════════════════════════════════════════════════════════════
#  Agent registry — convenience mapping
# ═══════════════════════════════════════════════════════════════════════

AGENT_CLASSES = {
    "analyst":    AnalystAgent,
    "coder":      CoderAgent,
    "validator":  ValidatorAgent,
    "committer":  CommitterAgent,
}


def get_agent_class(role: str):
    """Return the agent class for a given role name.

    Returns None if the role is not recognized.
    """
    return AGENT_CLASSES.get(role)
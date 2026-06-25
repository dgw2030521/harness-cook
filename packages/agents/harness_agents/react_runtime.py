"""
AgentRuntime: ReAct (Reasoning + Acting) loop for harness-cook agents.

Implements the classic think -> tool_call -> observe -> think cycle
that powers every agent in the harness-agents stack.

Layer 2 of the three-layer architecture:
  1. ToolExecutor  — file I/O, shell commands, search
  2. AgentRuntime  — ReAct loop (think -> tool_call -> observe -> think)
  3. Orchestrator  — multi-agent pipeline

The runtime does NOT call an actual LLM directly.  It uses a
configurable ILLMProvider protocol so users can inject any LLM
backend (OpenAI, Anthropic, 百炼, local models, etc.).

ReAct prompt format (classic, not OpenAI function_calling):
  - Tool call:  "Action: <tool_name>(<json_args>)"
  - Final answer: "Final Answer: <text>"
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from .tool_executor import ToolExecutor, ToolCall, ToolResult

# ── TaskResult ──────────────────────────────────────────────────────────
# Import from harness SDK core when available; otherwise use local fallback.

try:
    from harness import TaskResult as _CoreTaskResult
    TaskResult = _CoreTaskResult
except ImportError:
    @dataclass
    class TaskResult:
        """Local fallback TaskResult when harness SDK is not installed."""
        status: str = "completed"
        output: str = ""
        artifacts: list = field(default_factory=list)
        metadata: dict = field(default_factory=dict)


# ── ReActState ──────────────────────────────────────────────────────────

class ReActState(Enum):
    """State machine for the ReAct loop.

    THINKING  → composing prompt, waiting for LLM response
    ACTING    → parsed tool_calls, about to execute
    OBSERVING → executing tool_calls, collecting results
    COMPLETED → agent produced a Final Answer
    FAILED    → agent exceeded max_rounds or hit an unrecoverable error
    """
    THINKING = "thinking"
    ACTING = "acting"
    OBSERVING = "observing"
    COMPLETED = "completed"
    FAILED = "failed"


# ── AgentConfig ─────────────────────────────────────────────────────────

@dataclass
class AgentConfig:
    """Configuration for an AgentRuntime instance.

    max_rounds caps the ReAct loop to prevent infinite cycling.
    temperature, max_tokens, model are forwarded to the LLM provider.
    system_prompt overrides the default ReAct prompt template.
    """
    max_rounds: int = 15
    temperature: float = 0.2
    max_tokens: int = 65536
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    allowed_tools: Optional[List[str]] = None


# ── StepRecord ──────────────────────────────────────────────────────────

@dataclass
class StepRecord:
    """One round of the ReAct loop — thought, action, observation.

    Stored in the step_history so callers can inspect the full
    reasoning trace after the task completes.
    """
    round: int
    thought: str
    action: Optional[ToolCall] = None
    observation: Optional[ToolResult] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── ILLMProvider ────────────────────────────────────────────────────────

@runtime_checkable
class ILLMProvider(Protocol):
    """Protocol for LLM backends — inject any provider you like.

    The AgentRuntime calls `complete()` with the assembled message
    list and config; the provider returns a dict with the LLM's
    content and any tool_calls it detected.

    Returns:
        {
            "content": str,
            "tool_calls": Optional[list[dict]]
        }
    where tool_calls format is:
        [{"name": str, "arguments": dict, "id": str}]

    This protocol is runtime-checkable so you can verify compliance
    with isinstance(obj, ILLMProvider).
    """

    def complete(self, messages: List[Dict[str, Any]], config: AgentConfig) -> Dict[str, Any]:
        """Call the LLM with assembled messages and return response dict.

        Args:
            messages: OpenAI-style message list [{"role": ..., "content": ...}]
            config: AgentConfig forwarded for temperature, max_tokens, model.

        Returns:
            {"content": str, "tool_calls": Optional[list[dict]]}
        """
        ...


# ── MockLLMProvider ────────────────────────────────────────────────────

class MockLLMProvider:
    """Canned LLM provider for testing and demonstrations.

    Returns deterministic responses so tests can verify the ReAct
    loop mechanics without hitting a real API.

    Behaviour per round:
      round 1 → Action: read_file({"path": "README.md"})
      round 2 → Final Answer: <summary of the "read" result>

    Users can override by subclassing or providing their own
    ILLMProvider implementation.
    """

    def complete(self, messages: List[Dict[str, Any]], config: AgentConfig) -> Dict[str, Any]:
        # Determine the current round from step-history embedded in messages
        round_num = 0
        for m in messages:
            if m.get("role") == "assistant" and "Action:" in m.get("content", ""):
                round_num += 1

        if round_num == 0:
            # First round: request a tool call
            tool_id = str(uuid.uuid4())
            return {
                "content": "Thought: I need to read the README to understand the project.\n"
                           "Action: read_file({\"path\": \"README.md\"})",
                "tool_calls": [
                    {
                        "name": "read_file",
                        "arguments": {"path": "README.md"},
                        "id": tool_id,
                    }
                ],
            }

        # Second+ round: produce a final answer based on observations
        last_observation = ""
        for m in reversed(messages):
            if m.get("role") == "user" and "Observation:" in m.get("content", ""):
                last_observation = m["content"]
                break

        summary = last_observation[:200] if last_observation else "No observation available."
        return {
            "content": f"Thought: I have the information I need.\n"
                       f"Final Answer: Based on my research, here is what I found: {summary}",
            "tool_calls": None,
        }


# ── Default ReAct system prompt ─────────────────────────────────────────

DEFAULT_REACT_SYSTEM_PROMPT = """You are a ReAct agent that solves tasks step-by-step.

For each step, you MUST output your reasoning in exactly this format:

Thought: <your reasoning about what to do next>
Action: <tool_name>(<json_arguments>)
  OR
Thought: <your reasoning>
Final Answer: <your final answer to the task>

Available tools:
{tool_descriptions}

Rules:
1. Always start with "Thought:" before every action or final answer.
2. Use "Action: tool_name(json_args)" to call a tool. The json_args must be valid JSON.
3. After receiving an Observation, continue with another Thought.
4. When you have enough information, output "Final Answer: <text>".
5. Do NOT output anything after Final Answer.
6. Do NOT make up observations — only use what the tools return.
"""


# ── ReAct response parsers ─────────────────────────────────────────────

_ACTION_PATTERN = re.compile(
    r"Action:\s*(\w+)\s*\((\{.*?\})\)",
    re.DOTALL,
)
_FINAL_ANSWER_PATTERN = re.compile(
    r"Final Answer:\s*(.+)",
    re.DOTALL,
)
_THOUGHT_PATTERN = re.compile(
    r"Thought:\s*(.+?)(?:\n(?:Action|Final Answer):)",
    re.DOTALL,
)


def _parse_action(text: str) -> Optional[ToolCall]:
    """Extract a tool call from LLM response text.

    Matches: "Action: <tool_name>(<json_args>)"
    Returns a ToolCall or None if no action found.
    """
    match = _ACTION_PATTERN.search(text)
    if not match:
        return None
    tool_name = match.group(1)
    raw_args = match.group(2)
    try:
        arguments = json.loads(raw_args)
    except json.JSONDecodeError:
        arguments = {"_raw": raw_args}
    return ToolCall(tool_name=tool_name, args=arguments, id=str(uuid.uuid4()))


def _parse_final_answer(text: str) -> Optional[str]:
    """Extract a final answer from LLM response text.

    Matches: "Final Answer: <text>"
    Returns the answer text or None if no final answer found.
    """
    match = _FINAL_ANSWER_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    return None


def _parse_thought(text: str) -> str:
    """Extract the Thought portion from LLM response text.

    If no explicit Thought: marker, returns the full text.
    """
    match = _THOUGHT_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    # Fallback: everything before Action/Final Answer, or full text
    lines = text.split("\n")
    thought_lines = []
    for line in lines:
        if line.startswith("Action:") or line.startswith("Final Answer:"):
            break
        thought_lines.append(line)
    thought = "\n".join(thought_lines).strip()
    if thought.startswith("Thought:"):
        thought = thought[len("Thought:"):].strip()
    return thought or text.strip()


# ── AgentRuntime ────────────────────────────────────────────────────────

class AgentRuntime:
    """ReAct (Reasoning + Acting) agent runtime.

    Implements the think -> tool_call -> observe -> think loop:
      1. THINK: compose prompt (system + task + history) → call LLM
      2. ACT:   parse LLM response → extract tool_calls
      3. OBSERVE: execute tool_calls via ToolExecutor → collect results
      4. Repeat until COMPLETED or max_rounds reached

    Usage:
        executor = ToolExecutor(sandbox_dir="/project")
        config = AgentConfig(max_rounds=10)
        provider = MyOpenAIProvider(api_key="...")
        runtime = AgentRuntime(executor, config, provider)
        result = runtime.run("Fix the bug in main.py")
    """

    def __init__(
        self,
        tool_executor: ToolExecutor,
        config: AgentConfig,
        llm_provider: Optional[ILLMProvider] = None,
    ) -> None:
        self._executor = tool_executor
        self._config = config
        self._provider: ILLMProvider = llm_provider or MockLLMProvider()
        self._state = ReActState.THINKING
        self._step_history: List[StepRecord] = []

    # ── Public API ──────────────────────────────────────────────────

    def run(self, task: str, context: Optional[str] = None) -> TaskResult:
        """Execute the ReAct loop for a given task.

        Args:
            task: The task description / question for the agent.
            context: Optional additional context (e.g. file contents,
                     error logs, prior conversation).

        Returns:
            TaskResult with final answer in output field and the
            full step_history in metadata.
        """
        self._state = ReActState.THINKING
        self._step_history = []
        start_time = datetime.now(timezone.utc)

        # Build initial system prompt
        system_prompt = self._build_system_prompt()

        # Build initial user message
        user_content = f"Task: {task}"
        if context:
            user_content += f"\n\nContext:\n{context}"

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        final_answer: Optional[str] = None
        error_msg: Optional[str] = None

        for round_num in range(1, self._config.max_rounds + 1):
            # ── THINK ────────────────────────────────────────────
            self._state = ReActState.THINKING
            try:
                response = self._provider.complete(messages, self._config)
            except Exception as exc:
                self._state = ReActState.FAILED
                error_msg = f"LLM provider error on round {round_num}: {exc}"
                break

            content = response.get("content", "")
            provider_tool_calls = response.get("tool_calls")

            # Parse thought from content
            thought = _parse_thought(content)

            # ── Check for Final Answer ────────────────────────────
            parsed_answer = _parse_final_answer(content)
            if parsed_answer is not None:
                final_answer = parsed_answer
                self._step_history.append(
                    StepRecord(
                        round=round_num,
                        thought=thought,
                        action=None,
                        observation=None,
                    )
                )
                self._state = ReActState.COMPLETED
                break

            # ── ACT: parse tool call ──────────────────────────────
            self._state = ReActState.ACTING

            # Prefer explicit tool_calls from provider; fall back to
            # text-based Action: parsing
            tool_call: Optional[ToolCall] = None
            if provider_tool_calls and len(provider_tool_calls) > 0:
                tc = provider_tool_calls[0]
                tool_call = ToolCall(
                    tool_name=tc.get("name", ""),
                    args=tc.get("arguments", {}),
                    id=tc.get("id", str(uuid.uuid4())),
                )
            else:
                tool_call = _parse_action(content)

            if tool_call is None:
                # No action and no final answer — treat as final answer
                # using the full content (the LLM may have just responded
                # directly without following the format)
                final_answer = content.strip()
                self._step_history.append(
                    StepRecord(
                        round=round_num,
                        thought=thought or content.strip(),
                        action=None,
                        observation=None,
                    )
                )
                self._state = ReActState.COMPLETED
                break

            # ── OBSERVE: execute the tool call ────────────────────
            self._state = ReActState.OBSERVING
            observation = self._executor.execute(tool_call)

            # Record this step
            self._step_history.append(
                StepRecord(
                    round=round_num,
                    thought=thought,
                    action=tool_call,
                    observation=observation,
                )
            )

            # Append to conversation history
            messages.append({"role": "assistant", "content": content})
            messages.append({
                "role": "user",
                "content": f"Observation: {observation.output}"
                           + (f"\nError: {observation.error}" if observation.error else ""),
            })

            # Loop continues → next THINK phase

        # ── Post-loop: determine outcome ─────────────────────────
        if final_answer is None:
            # Did not reach COMPLETED within max_rounds
            self._state = ReActState.FAILED
            if error_msg is None:
                error_msg = f"Agent did not produce a Final Answer within {self._config.max_rounds} rounds"
            final_answer = error_msg or "Agent failed to complete the task"

        elapsed_ms = int(
            (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        )

        # Build result — adapt to whichever TaskResult is active
        try:
            # Core TaskResult expects task_id, agent_id, etc.
            result = TaskResult(
                task_id=str(uuid.uuid4()),
                agent_id="react-agent",
                status=self._state.value,
                artifacts=[],
                duration_ms=elapsed_ms,
                metadata={
                    "final_answer": final_answer,
                    "step_history": [
                        {
                            "round": s.round,
                            "thought": s.thought,
                            "action": s.action.tool_name if s.action else None,
                            "action_args": s.action.args if s.action else None,
                            "observation": s.observation.output[:500] if s.observation else None,
                            "observation_success": s.observation.success if s.observation else None,
                            "timestamp": s.timestamp.isoformat(),
                        }
                        for s in self._step_history
                    ],
                },
            )
            # Core TaskResult may not have an output field; store in metadata
            if hasattr(result, "output"):
                result.output = final_answer
            else:
                result.metadata["output"] = final_answer
        except TypeError:
            # Local fallback TaskResult has simpler signature
            result = TaskResult(
                status=self._state.value,
                output=final_answer,
                artifacts=[],
                metadata={
                    "step_history": [
                        {
                            "round": s.round,
                            "thought": s.thought,
                            "action": s.action.tool_name if s.action else None,
                            "observation": s.observation.output[:500] if s.observation else None,
                            "timestamp": s.timestamp.isoformat(),
                        }
                        for s in self._step_history
                    ],
                },
            )

        return result

    def get_history(self) -> List[StepRecord]:
        """Return the step history from the current or last run."""
        return list(self._step_history)

    def get_state(self) -> ReActState:
        """Return the current ReAct loop state."""
        return self._state

    # ── Internal helpers ───────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        """Assemble the system prompt with tool descriptions."""
        if self._config.system_prompt:
            return self._config.system_prompt

        tools = self._executor.get_tool_definitions()
        tool_lines = []
        for t in tools:
            params = t.get("parameters", {})
            param_str = ", ".join(
                f"{k}: {v.get('type', 'any') if isinstance(v, dict) else v}"
                for k, v in params.items()
            )
            tool_lines.append(f"- {t['name']}({param_str}): {t['description']}")

        tool_descriptions = "\n".join(tool_lines)
        return DEFAULT_REACT_SYSTEM_PROMPT.format(tool_descriptions=tool_descriptions)
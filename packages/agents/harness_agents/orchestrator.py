"""
harness-agents Orchestrator: multi-agent pipeline coordination.

Coordinates the coding pipeline:
  Analyst -> Coder -> Validator -> Committer
with gate checks between each step, using harness-cook SDK's
DAG engine when available or falling back to sequential execution.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol

# Conditional harness SDK import
try:
    from harness import (
        DAGWorkflow, DAGNode, DAGEdge, DAGEngine,
        GateCheck, GateMode, ComplianceEngine, ComplianceResult,
        TaskResult as SDKTaskResult, Artifact as SDKArtifact,
        AuditEntry, AuditStore,
    )
    HAS_HARNESS_SDK = True
except ImportError:
    HAS_HARNESS_SDK = False

    @dataclass
    class TaskResult:  # type: ignore[no-redef]
        status: str = "completed"
        output: str = ""
        artifacts: List[Any] = field(default_factory=list)
        metadata: Dict[str, Any] = field(default_factory=dict)

    @dataclass
    class Artifact:  # type: ignore[no-redef]
        type: str = ""
        path: str = ""
        content: str = ""


from .tool_executor import ToolExecutor, ToolCall, ToolResult as ToolResultData
from .react_runtime import AgentRuntime, AgentConfig, ILLMProvider, ReActState
from .coding_agents import (
    AnalystAgent, CoderAgent, ValidatorAgent, CommitterAgent,
    AGENT_CLASSES, get_agent_class,
)


class PipelineStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    GATE_BLOCKED = "gate_blocked"
    ABORTED = "aborted"


@dataclass
class PipelineConfig:
    """Configuration for a coding pipeline run."""
    task: str = ""
    project_path: str = "."
    agents: List[str] = field(default_factory=lambda: [
        "analyst", "coder", "validator", "committer"
    ])
    gate_mode: str = "hybrid"
    max_retries: int = 2
    llm_provider: Optional[Any] = None
    working_directory: str = "."


@dataclass
class StepResult:
    """Result of a single pipeline step."""
    agent: str = ""
    status: str = ""
    output: str = ""
    duration_ms: int = 0
    gate_passed: bool = False
    gate_reason: str = ""
    retries: int = 0
    timestamp: str = ""


@dataclass
class PipelineResult:
    """Final result of the entire pipeline."""
    success: bool = False
    task: str = ""
    steps: List[StepResult] = field(default_factory=list)
    final_output: str = ""
    commit_hash: Optional[str] = None
    total_duration_ms: int = 0
    gate_results: List[Dict[str, Any]] = field(default_factory=list)
    compliance_violations: List[Dict[str, Any]] = field(default_factory=list)
    status: PipelineStatus = PipelineStatus.PENDING


# ── Gate check functions ──────────────────────────────────────

def _analyst_gate(output: str) -> Dict[str, Any]:
    """Analyst output must contain a plan or affected files."""
    keywords = ["affected_files", "plan", "changes", "analysis", "implement"]
    found = [k for k in keywords if k.lower() in output.lower()]
    passed = len(found) >= 1
    return {
        "passed": passed,
        "reason": ("Plan keywords found: " + ", ".join(found)) if passed else "No plan/analysis keywords found in analyst output",
        "step": "analyst",
    }


def _coder_gate(output: str, working_directory: str) -> Dict[str, Any]:
    """Coder must have changed at least one file."""
    has_changes = False
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            cwd=working_directory,
            capture_output=True, text=True, timeout=10,
        )
        changed = result.stdout.strip()
        has_changes = bool(changed) and ("file changed" in changed.lower() or changed.count("\n") > 0)
    except Exception as e:
        # git diff 不可用时降级到关键词检查，但必须记录 warning
        logging.getLogger("harness.orchestrator").warning(
            f"coder_gate: git diff failed ({e}), falling back to keyword check"
        )
        has_changes = any(
            kw in output.lower()
            for kw in ["edited", "modified", "created", "wrote", "changed", "updated"]
        )
    return {
        "passed": has_changes,
        "reason": "File changes detected" if has_changes else "No file changes detected from coder",
        "step": "coder",
    }


def _validator_gate(output: str) -> Dict[str, Any]:
    """Validator must report all checks passed."""
    passed_keywords = ["passed", "ok", "success", "all tests pass", "no issues found", "no violations", "clean"]
    failed_keywords = ["failed", "error", "failing", "test failure", "issues found:", "1 failing"]
    has_passed = any(k in output.lower() for k in passed_keywords)
    has_failed = any(k in output.lower() for k in failed_keywords)
    gate_passed = has_passed and not has_failed
    return {
        "passed": gate_passed,
        "reason": "Validation checks passed" if gate_passed else "Validation found issues",
        "step": "validator",
    }


def _committer_gate(working_directory: str) -> Dict[str, Any]:
    """Working tree must be clean after commit."""
    is_clean = False  # 默认假设不合规——git status 不可用时保守判定
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=working_directory,
            capture_output=True, text=True, timeout=10,
        )
        is_clean = result.stdout.strip() == ""
    except Exception as e:
        # git status 不可用时保守判定为不干净，而非默认放行
        logging.getLogger("harness.orchestrator").warning(
            f"committer_gate: git status failed ({e}), conservatively assuming dirty tree"
        )
    return {
        "passed": is_clean,
        "reason": "Working tree clean after commit" if is_clean else "Uncommitted changes remain after commit",
        "step": "committer",
    }


GATE_FUNCTIONS = {
    "analyst": lambda output, wd: _analyst_gate(output),
    "coder": lambda output, wd: _coder_gate(output, wd),
    "validator": lambda output, wd: _validator_gate(output),
    "committer": lambda output, wd: _committer_gate(wd),
}


class Orchestrator:
    """Coordinates multi-agent coding pipelines with gate enforcement.

    Architecture:
      1. Build pipeline from PipelineConfig.agents sequence
      2. Run each agent sequentially with upstream context
      3. Gate check after each step (harness SDK or built-in)
      4. Retry on gate failure (up to max_retries)
      5. Abort pipeline on unrecoverable gate failure
      6. Collect compliance violations and audit trail
    """

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self._tool_executor = ToolExecutor()
        self._status = PipelineStatus.PENDING
        self._steps: List[StepResult] = []
        self._start_time: float = 0.0
        self._current_agent: Optional[str] = None

    def run(self, task: Optional[str] = None) -> PipelineResult:
        """Execute the full coding pipeline."""
        task = task or self.config.task
        if not task:
            return PipelineResult(
                success=False, task="", status=PipelineStatus.FAILED,
                final_output="No task specified",
            )

        self._status = PipelineStatus.RUNNING
        self._start_time = time.time()
        self._steps = []

        upstream_context = ""
        pipeline_result = PipelineResult(
            success=False, task=task, status=PipelineStatus.RUNNING,
        )

        # Run compliance scan before pipeline starts (if SDK available)
        if HAS_HARNESS_SDK:
            try:
                engine = ComplianceEngine()
                engine.load_pack("security")
                engine.load_pack("coding")
                scan_result = engine.scan(self.config.working_directory)
                pipeline_result.compliance_violations = [
                    {"rule_id": v.rule_id, "severity": v.severity.value,
                     "description": v.description, "file": v.file_path}
                    for v in scan_result.violations
                ]
            except Exception as e:
                # 合规扫描失败不能静默跳过——治理框架必须在扫描失败时记录并标记
                logging.getLogger("harness.orchestrator").warning(
                    f"Compliance scan failed ({e}), compliance_violations left empty"
                )
                # 标记扫描失败，让下游知道合规检查未执行
                pipeline_result.compliance_violations = [
                    {"rule_id": "SCAN_FAILURE", "severity": "high",
                     "description": f"Compliance scan failed: {e}", "file": ""}
                ]

        for agent_name in self.config.agents:
            self._current_agent = agent_name
            agent_cls = get_agent_class(agent_name)
            if agent_cls is None:
                pipeline_result.status = PipelineStatus.FAILED
                pipeline_result.final_output = "Unknown agent: " + agent_name
                break

            step = self._run_step(
                agent_cls, agent_name, task, upstream_context,
            )

            # Gate check
            gate_result = self._check_gate(
                agent_name, step.output, self.config.working_directory,
            )
            step.gate_passed = gate_result["passed"]
            step.gate_reason = gate_result["reason"]
            pipeline_result.gate_results.append(gate_result)

            # Handle gate failure
            if not gate_result["passed"]:
                if step.retries < self.config.max_retries:
                    retry_step = self._run_step(
                        agent_cls, agent_name, task, upstream_context,
                    )
                    retry_step.retries = step.retries + 1
                    retry_gate = self._check_gate(
                        agent_name, retry_step.output,
                        self.config.working_directory,
                    )
                    retry_step.gate_passed = retry_gate["passed"]
                    retry_step.gate_reason = retry_gate["reason"]
                    pipeline_result.gate_results.append(retry_gate)

                    if retry_gate["passed"]:
                        step = retry_step
                    else:
                        pipeline_result.status = PipelineStatus.GATE_BLOCKED
                        pipeline_result.final_output = (
                            "Gate blocked at " + agent_name + " after "
                            + str(step.retries + 1) + " retries: " + retry_gate["reason"]
                        )
                        self._steps.append(step)
                        self._steps.append(retry_step)
                        break
                else:
                    pipeline_result.status = PipelineStatus.GATE_BLOCKED
                    pipeline_result.final_output = (
                        "Gate blocked at " + agent_name + ": " + gate_result["reason"]
                    )
                    self._steps.append(step)
                    break

            self._steps.append(step)
            upstream_context = step.output

        # Finalize result
        pipeline_result.steps = self._steps
        pipeline_result.total_duration_ms = int(
            (time.time() - self._start_time) * 1000
        )

        if pipeline_result.status != PipelineStatus.GATE_BLOCKED:
            all_passed = all(s.gate_passed for s in self._steps)
            if all_passed and len(self._steps) == len(self.config.agents):
                pipeline_result.success = True
                pipeline_result.status = PipelineStatus.COMPLETED
                pipeline_result.final_output = self._steps[-1].output
                pipeline_result.commit_hash = self._get_commit_hash()
            else:
                pipeline_result.success = False
                pipeline_result.status = PipelineStatus.FAILED

        self._status = pipeline_result.status
        return pipeline_result

    def _run_step(
        self,
        agent_cls: type,
        agent_name: str,
        task: str,
        upstream_context: str,
    ) -> StepResult:
        """Run a single agent step."""
        start = time.time()
        try:
            agent = agent_cls(
                tool_executor=self._tool_executor,
            )
            result = agent.execute(
                task=task,
                context=upstream_context if upstream_context else None,
            )
            output = result.output if hasattr(result, "output") else str(result)
            status = result.status if hasattr(result, "status") else "completed"
        except Exception as e:
            output = "Agent execution error: " + str(e)
            status = "failed"

        duration_ms = int((time.time() - start) * 1000)
        return StepResult(
            agent=agent_name,
            status=status,
            output=output,
            duration_ms=duration_ms,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def _check_gate(
        self,
        agent_name: str,
        output: str,
        working_directory: str,
    ) -> Dict[str, Any]:
        """Run gate check for a pipeline step."""
        gate_fn = GATE_FUNCTIONS.get(agent_name)
        if gate_fn:
            result = gate_fn(output, working_directory)
            if self.config.gate_mode == "loose":
                result["passed"] = True
                result["reason"] = "Loose gate: auto-approved"
            elif self.config.gate_mode == "strict" and not result["passed"]:
                pass  # keep original result
            return result
        return {"passed": True, "reason": "No gate defined for " + agent_name, "step": agent_name}

    def _get_commit_hash(self) -> Optional[str]:
        """Try to get the latest commit hash."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=self.config.working_directory,
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logging.getLogger("harness.orchestrator").warning(
                f"get_commit_hash: git rev-parse failed ({e}), returning None"
            )
        return None

    def get_pipeline_status(self) -> Dict[str, Any]:
        """Get current pipeline execution status."""
        return {
            "status": self._status.value,
            "current_agent": self._current_agent,
            "steps_completed": len(self._steps),
            "steps_total": len(self.config.agents),
            "progress": str(len(self._steps)) + "/" + str(len(self.config.agents)),
        }
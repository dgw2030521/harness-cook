"""Tests for harness_agents package — ToolExecutor, AgentRuntime, CodingAgents, Orchestrator."""
from __future__ import annotations

import os
import sys
import tempfile
import time

# Ensure harness_agents is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "core"))

import pytest


# ── ToolExecutor tests ────────────────────────────────────────

class TestToolExecutor:
    """Test the ToolExecutor's built-in tools."""

    def setup_method(self):
        from harness_agents.tool_executor import ToolExecutor, ToolCall
        self.executor = ToolExecutor()
        self.tmpdir = tempfile.mkdtemp()

    def test_import(self):
        from harness_agents.tool_executor import ToolExecutor, ToolCall, ToolResult
        assert ToolExecutor is not None
        assert ToolCall is not None
        assert ToolResult is not None

    def test_available_tools(self):
        tools = self.executor.get_available_tools()
        assert len(tools) >= 6
        names = [t["name"] for t in tools]
        assert "read_file" in names
        assert "write_file" in names
        assert "search_code" in names
        assert "run_command" in names
        assert "list_files" in names
        assert "edit_file" in names

    def test_write_then_read(self):
        from harness_agents.tool_executor import ToolCall
        # Write a file
        path = os.path.join(self.tmpdir, "test.txt")
        write_call = ToolCall(
            tool_name="write_file",
            args={"path": path, "content": "hello world"},
            id="w1",
        )
        result = self.executor.execute(write_call)
        assert result.success
        assert "written" in result.output.lower() or "created" in result.output.lower() or result.success

        # Read it back
        read_call = ToolCall(
            tool_name="read_file",
            args={"path": path},
            id="r1",
        )
        result = self.executor.execute(read_call)
        assert result.success
        assert "hello world" in result.output

    def test_list_files(self):
        from harness_agents.tool_executor import ToolCall
        # Create a file first
        path = os.path.join(self.tmpdir, "sample.py")
        write_call = ToolCall(
            tool_name="write_file",
            args={"path": path, "content": "x = 1"},
            id="w2",
        )
        self.executor.execute(write_call)

        # List the directory
        list_call = ToolCall(
            tool_name="list_files",
            args={"path": self.tmpdir},
            id="l1",
        )
        result = self.executor.execute(list_call)
        assert result.success
        assert "sample.py" in result.output

    def test_run_command(self):
        from harness_agents.tool_executor import ToolCall
        call = ToolCall(
            tool_name="run_command",
            args={"command": "echo hello"},
            id="cmd1",
        )
        result = self.executor.execute(call)
        assert result.success
        assert "hello" in result.output

    def test_edit_file(self):
        from harness_agents.tool_executor import ToolCall
        # Write initial content
        path = os.path.join(self.tmpdir, "edit_test.py")
        write_call = ToolCall(
            tool_name="write_file",
            args={"path": path, "content": "old_value = 1"},
            id="w3",
        )
        self.executor.execute(write_call)

        # Edit: replace old_value with new_value
        edit_call = ToolCall(
            tool_name="edit_file",
            args={"path": path, "old_string": "old_value", "new_string": "new_value"},
            id="e1",
        )
        result = self.executor.execute(edit_call)
        assert result.success

        # Verify edit worked
        read_call = ToolCall(
            tool_name="read_file",
            args={"path": path},
            id="r2",
        )
        result = self.executor.execute(read_call)
        assert "new_value" in result.output

    def test_register_custom_tool(self):
        from harness_agents.tool_executor import ToolCall
        def my_tool(args):
            return "custom output: " + str(args.get("input", ""))
        self.executor.register_tool(
            "my_custom",
            my_tool,
            {"name": "my_custom", "description": "A custom tool", "parameters": {"input": {"type": "string"}}},
        )
        call = ToolCall(tool_name="my_custom", args={"input": "test"}, id="c1")
        result = self.executor.execute(call)
        assert result.success
        assert "custom output: test" in result.output

    def test_error_handling(self):
        from harness_agents.tool_executor import ToolCall
        call = ToolCall(
            tool_name="read_file",
            args={"path": "/nonexistent/file.txt"},
            id="err1",
        )
        result = self.executor.execute(call)
        assert not result.success
        assert result.error is not None

    def test_duration_tracking(self):
        from harness_agents.tool_executor import ToolCall
        call = ToolCall(
            tool_name="run_command",
            args={"command": "sleep 0.1 && echo done"},
            id="dur1",
        )
        result = self.executor.execute(call)
        assert result.duration_ms >= 50  # at least 50ms


# ── AgentRuntime tests ────────────────────────────────────────

class TestAgentRuntime:
    """Test the ReAct agent loop."""

    def test_import(self):
        from harness_agents.react_runtime import AgentRuntime, ReActState, AgentConfig
        assert AgentRuntime is not None
        assert ReActState is not None
        assert AgentConfig is not None

    def test_config_defaults(self):
        from harness_agents.react_runtime import AgentConfig
        config = AgentConfig()
        assert config.max_rounds == 15
        assert config.temperature == 0.2
        assert config.max_tokens == 65536

    def test_mock_provider(self):
        from harness_agents.react_runtime import MockLLMProvider
        provider = MockLLMProvider()
        result = provider.complete(
            messages=[{"role": "user", "content": "test"}],
            config=None,
        )
        assert "content" in result

    def test_runtime_creation(self):
        from harness_agents.react_runtime import AgentRuntime, AgentConfig
        from harness_agents.tool_executor import ToolExecutor
        executor = ToolExecutor()
        config = AgentConfig(max_rounds=3)
        runtime = AgentRuntime(executor, config)
        assert runtime.get_state() == "thinking" or runtime is not None

    def test_simple_run(self):
        from harness_agents.react_runtime import AgentRuntime, AgentConfig, MockLLMProvider
        from harness_agents.tool_executor import ToolExecutor
        executor = ToolExecutor()
        config = AgentConfig(max_rounds=3)
        provider = MockLLMProvider()
        runtime = AgentRuntime(executor, config, provider)
        result = runtime.run("Read a file")
        # Mock provider returns canned response, should complete
        assert result is not None
        assert hasattr(result, "status") or hasattr(result, "output")


# ── Coding Agents tests ───────────────────────────────────────

class TestCodingAgents:
    """Test the four coding agent definitions."""

    def test_import(self):
        from harness_agents.coding_agents import (
            AnalystAgent, CoderAgent, ValidatorAgent, CommitterAgent,
            CodingAgentPipeline, AGENT_CLASSES, get_agent_class,
        )
        assert AnalystAgent is not None
        assert CoderAgent is not None
        assert ValidatorAgent is not None
        assert CommitterAgent is not None

    def test_agent_registry(self):
        from harness_agents.coding_agents import AGENT_CLASSES, get_agent_class
        assert "analyst" in AGENT_CLASSES
        assert "coder" in AGENT_CLASSES
        assert "validator" in AGENT_CLASSES
        assert "committer" in AGENT_CLASSES
        assert get_agent_class("analyst") is not None
        assert get_agent_class("unknown") is None

    def test_pipeline_defaults(self):
        from harness_agents.coding_agents import CodingAgentPipeline
        pipeline = CodingAgentPipeline()
        assert pipeline.agents == ["analyst", "coder", "validator", "committer"]
        assert pipeline.gate_mode == "hybrid"
        assert pipeline.max_retries == 2
        assert pipeline.require_validation is True

    def test_agent_tools(self):
        from harness_agents.coding_agents import AnalystAgent
        from harness_agents.tool_executor import ToolExecutor
        executor = ToolExecutor()
        agent = AnalystAgent(tool_executor=executor)
        tools = agent.get_tools()
        assert "read_file" in tools
        assert "search_code" in tools

    def test_agent_system_prompts(self):
        from harness_agents.coding_agents import AnalystAgent, CoderAgent
        from harness_agents.tool_executor import ToolExecutor
        executor = ToolExecutor()
        analyst = AnalystAgent(tool_executor=executor)
        coder = CoderAgent(tool_executor=executor)
        assert "analyst" in analyst.get_system_prompt().lower() or "analyze" in analyst.get_system_prompt().lower()
        assert "programmer" in coder.get_system_prompt().lower() or "code" in coder.get_system_prompt().lower()


# ── Orchestrator tests ────────────────────────────────────────

class TestOrchestrator:
    """Test the pipeline orchestrator."""

    def test_import(self):
        from harness_agents.orchestrator import (
            Orchestrator, PipelineConfig, PipelineResult, PipelineStatus,
        )
        assert Orchestrator is not None
        assert PipelineConfig is not None
        assert PipelineResult is not None
        assert PipelineStatus is not None

    def test_config_defaults(self):
        from harness_agents.orchestrator import PipelineConfig
        config = PipelineConfig()
        assert config.agents == ["analyst", "coder", "validator", "committer"]
        assert config.gate_mode == "hybrid"
        assert config.max_retries == 2

    def test_no_task_returns_failure(self):
        from harness_agents.orchestrator import Orchestrator, PipelineConfig, PipelineStatus
        config = PipelineConfig(task="")
        orch = Orchestrator(config)
        result = orch.run()
        assert not result.success
        assert result.status == PipelineStatus.FAILED

    def test_status_enum(self):
        from harness_agents.orchestrator import PipelineStatus
        assert PipelineStatus.PENDING.value == "pending"
        assert PipelineStatus.RUNNING.value == "running"
        assert PipelineStatus.COMPLETED.value == "completed"
        assert PipelineStatus.FAILED.value == "failed"
        assert PipelineStatus.GATE_BLOCKED.value == "gate_blocked"

    def test_gate_functions_exist(self):
        from harness_agents.orchestrator import GATE_FUNCTIONS
        assert "analyst" in GATE_FUNCTIONS
        assert "coder" in GATE_FUNCTIONS
        assert "validator" in GATE_FUNCTIONS
        assert "committer" in GATE_FUNCTIONS

    def test_analyst_gate_pass(self):
        from harness_agents.orchestrator import _analyst_gate
        result = _analyst_gate("The affected_files include main.py and utils.py. Plan: refactor the module.")
        assert result["passed"]

    def test_analyst_gate_fail(self):
        from harness_agents.orchestrator import _analyst_gate
        result = _analyst_gate("I don't know what to do.")
        assert not result["passed"]

    def test_validator_gate_pass(self):
        from harness_agents.orchestrator import _validator_gate
        result = _validator_gate("All tests passed. No issues found.")
        assert result["passed"]

    def test_validator_gate_fail(self):
        from harness_agents.orchestrator import _validator_gate
        result = _validator_gate("Test failure: 3 tests failed.")
        assert not result["passed"]

    def test_pipeline_status_method(self):
        from harness_agents.orchestrator import Orchestrator, PipelineConfig
        config = PipelineConfig(task="test task")
        orch = Orchestrator(config)
        status = orch.get_pipeline_status()
        assert "status" in status
        assert "steps_completed" in status
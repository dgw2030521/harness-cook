"""
Phase 9 tests — harness-cook MCP Server

Tests the MCP protocol implementation including:
  - Initialize handshake
  - tools/list schema
  - tools/call for each of 8 tools
  - JSON-RPC error handling
  - stdio transport simulation
  - Concurrent request handling
  - harness exception → MCP error conversion

NOTE: These tests require PYTHONPATH to include the ../mcp directory.
When running the full suite (PYTHONPATH=.), the MCP module may not be
available and these tests will be skipped automatically.
"""

from __future__ import annotations

import io
import json
import threading
from unittest.mock import patch

import pytest

try:
    from harness_mcp_server import (
        HarnessMCPServer,
        TOOL_DEFINITIONS,
        PARSE_ERROR,
        INVALID_REQUEST,
        METHOD_NOT_FOUND,
        INVALID_PARAMS,
        INTERNAL_ERROR,
    )
    HAS_MCP = True
except ImportError:
    HAS_MCP = False

pytestmark = pytest.mark.skipif(not HAS_MCP, reason="harness_mcp_server not available (need PYTHONPATH=../mcp)")

from harness.compliance import ComplianceEngine
from harness.audit import AuditStore, AuditEngine
from harness.engine import DAGEngine
from harness.registry import AgentRegistry, get_registry, reset_registry
from harness.gates import GateEngine
from harness.guardrails import GuardrailsPair, default_guardrails
from harness.types import (
    AgentCapability, AgentDefinition, Artifact, ComplianceResult,
    DAGWorkflow, DAGNode, DAGEdge, GateDefinition, GateCheck, GateMode,
    InputGuardrailConfig, OutputGuardrailConfig, GuardrailAction,
)


# ── Helpers ──────────────────────────────────────────────────────

def _make_request(method: str, id: int = 1, params: dict = None) -> dict:
    """Build a JSON-RPC 2.0 request dict."""
    req = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        req["params"] = params
    return req


def _make_server() -> HarnessMCPServer:
    """Create a fresh HarnessMCPServer with reset global state."""
    reset_registry()
    return HarnessMCPServer()


# ═════════════════════════════════════════════════════════════════
#  1. Initialize handshake (3 tests)
# ═════════════════════════════════════════════════════════════════

class TestInitialize:
    def test_initialize_returns_protocol_info(self):
        server = _make_server()
        req = _make_request("initialize", id=1, params={
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "nextx", "version": "0.1.0"},
        })
        resp = server.handle_request(req)
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        result = resp["result"]
        assert result["protocolVersion"] == "2024-11-05"
        assert result["capabilities"]["tools"] == {}
        assert result["serverInfo"]["name"] == "harness-cook"
        assert result["serverInfo"]["version"] == "0.1.0"

    def test_initialize_sets_initialized_flag(self):
        server = _make_server()
        assert not server._initialized
        req = _make_request("initialize", id=1)
        server.handle_request(req)
        assert server._initialized

    def test_initialize_without_params(self):
        """initialize should work even with empty params."""
        server = _make_server()
        req = _make_request("initialize", id=2, params={})
        resp = server.handle_request(req)
        assert "result" in resp
        assert resp["result"]["protocolVersion"] == "2024-11-05"


# ═════════════════════════════════════════════════════════════════
#  2. tools/list (3 tests)
# ═════════════════════════════════════════════════════════════════

class TestToolsList:
    def test_tools_list_returns_all_tools(self):
        server = _make_server()
        req = _make_request("tools/list", id=10)
        resp = server.handle_request(req)
        assert "result" in resp
        tools = resp["result"]["tools"]
        assert len(tools) >= 8  # grew from 8 to 11 with agents pipeline tools

    def test_tools_list_contains_expected_tool_names(self):
        server = _make_server()
        req = _make_request("tools/list", id=11)
        resp = server.handle_request(req)
        names = [t["name"] for t in resp["result"]["tools"]]
        expected = [
            "harness_check", "harness_audit", "harness_plan",
            "harness_run", "harness_status", "harness_register",
            "harness_gate_create", "harness_guardrails_check",
            "harness_pipeline_run", "harness_pipeline_status", "harness_agent_list",
        ]
        assert names == expected

    def test_each_tool_has_required_schema_fields(self):
        server = _make_server()
        req = _make_request("tools/list", id=12)
        resp = server.handle_request(req)
        for tool in resp["result"]["tools"]:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool
            assert tool["inputSchema"]["type"] == "object"


# ═════════════════════════════════════════════════════════════════
#  3. tools/call — harness_check (2 tests)
# ═════════════════════════════════════════════════════════════════

class TestHarnessCheck:
    def test_harness_check_basic(self):
        server = _make_server()
        req = _make_request("tools/call", id=20, params={
            "name": "harness_check",
            "arguments": {"path": "/src/main.py", "pack_names": ["coding"]},
        })
        resp = server.handle_request(req)
        assert "result" in resp
        content_text = resp["result"]["content"][0]["text"]
        data = json.loads(content_text)
        assert data["path"] == "/src/main.py"
        assert "coding" in data["pack_names"]

    def test_harness_check_with_content(self):
        """Test harness_check with content that triggers a security violation."""
        server = _make_server()
        # SEC-001 detects hardcoded secrets: password='supersecret123'
        req = _make_request("tools/call", id=21, params={
            "name": "harness_check",
            "arguments": {
                "path": "/app.py",
                "pack_names": ["security"],
                "content": "password='supersecret123'",
            },
        })
        resp = server.handle_request(req)
        assert "result" in resp
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["failed"] > 0


# ═════════════════════════════════════════════════════════════════
#  4. tools/call — harness_audit (2 tests)
# ═════════════════════════════════════════════════════════════════

class TestHarnessAudit:
    def test_harness_audit_basic(self):
        server = _make_server()
        req = _make_request("tools/call", id=30, params={
            "name": "harness_audit",
            "arguments": {"query": "test", "limit": 10},
        })
        resp = server.handle_request(req)
        assert "result" in resp
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["query"] == "test"
        assert isinstance(data["entries"], list)

    def test_harness_audit_default_limit(self):
        server = _make_server()
        req = _make_request("tools/call", id=31, params={
            "name": "harness_audit",
            "arguments": {"query": ""},
        })
        resp = server.handle_request(req)
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["query"] == ""


# ═════════════════════════════════════════════════════════════════
#  5. tools/call — harness_plan (2 tests)
# ═════════════════════════════════════════════════════════════════

class TestHarnessPlan:
    def test_harness_plan_basic(self):
        server = _make_server()
        wf_yaml = """
id: test-wf
nodes:
  - id: n1
    agent_type: coder
    task: "write code"
  - id: n2
    agent_type: reviewer
    task: "review code"
    inputs: [n1]
edges:
  - from: n1
    to: n2
"""
        req = _make_request("tools/call", id=40, params={
            "name": "harness_plan",
            "arguments": {"workflow_yaml": wf_yaml},
        })
        resp = server.handle_request(req)
        assert "result" in resp
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["execution_order"] == ["n1", "n2"]
        assert data["node_count"] == 2
        assert data["edge_count"] == 1

    def test_harness_plan_empty_workflow(self):
        server = _make_server()
        req = _make_request("tools/call", id=41, params={
            "name": "harness_plan",
            "arguments": {"workflow_yaml": ""},
        })
        resp = server.handle_request(req)
        assert "result" in resp
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["node_count"] == 0


# ═════════════════════════════════════════════════════════════════
#  6. tools/call — harness_run (2 tests)
# ═════════════════════════════════════════════════════════════════

class TestHarnessRun:
    def test_harness_run_basic(self):
        """harness_run executes a DAG workflow (nodes will fail because no agents registered)."""
        server = _make_server()
        wf_yaml = """
id: run-wf
nodes:
  - id: step1
    agent_type: coder
    task: "do something"
edges: []
"""
        req = _make_request("tools/call", id=50, params={
            "name": "harness_run",
            "arguments": {"workflow_yaml": wf_yaml},
        })
        resp = server.handle_request(req)
        assert "result" in resp
        data = json.loads(resp["result"]["content"][0]["text"])
        assert "execution_id" in data
        assert "workflow_id" in data
        assert "node_status" in data

    def test_harness_run_empty_workflow(self):
        server = _make_server()
        req = _make_request("tools/call", id=51, params={
            "name": "harness_run",
            "arguments": {"workflow_yaml": ""},
        })
        resp = server.handle_request(req)
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["workflow_id"] == "empty"


# ═════════════════════════════════════════════════════════════════
#  7. tools/call — harness_status (2 tests)
# ═════════════════════════════════════════════════════════════════

class TestHarnessStatus:
    def test_harness_status_basic(self):
        server = _make_server()
        req = _make_request("tools/call", id=60, params={
            "name": "harness_status",
            "arguments": {},
        })
        resp = server.handle_request(req)
        assert "result" in resp
        data = json.loads(resp["result"]["content"][0]["text"])
        assert "registry" in data
        assert "compliance" in data
        assert "engine" in data
        assert "gate" in data
        assert "server" in data

    def test_harness_status_server_info(self):
        server = _make_server()
        req = _make_request("tools/call", id=61, params={
            "name": "harness_status",
            "arguments": {},
        })
        resp = server.handle_request(req)
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["server"]["name"] == "harness-cook"
        assert data["server"]["version"] == "0.1.0"


# ═════════════════════════════════════════════════════════════════
#  8. tools/call — harness_register (2 tests)
# ═════════════════════════════════════════════════════════════════

class TestHarnessRegister:
    def test_harness_register_basic(self):
        server = _make_server()
        req = _make_request("tools/call", id=70, params={
            "name": "harness_register",
            "arguments": {
                "agent_id": "my-coder",
                "name": "Coder Agent",
                "capabilities": ["execute", "reason"],
                "toolsets": ["terminal"],
            },
        })
        resp = server.handle_request(req)
        assert "result" in resp
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["agent_id"] == "my-coder"
        assert data["name"] == "Coder Agent"
        assert "execute" in data["capabilities"]
        assert data["active"] == True

    def test_harness_register_minimal(self):
        server = _make_server()
        req = _make_request("tools/call", id=71, params={
            "name": "harness_register",
            "arguments": {"agent_id": "minimal-agent"},
        })
        resp = server.handle_request(req)
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["agent_id"] == "minimal-agent"


# ═════════════════════════════════════════════════════════════════
#  9. tools/call — harness_gate_create (2 tests)
# ═════════════════════════════════════════════════════════════════

class TestHarnessGateCreate:
    def test_harness_gate_create_basic(self):
        server = _make_server()
        req = _make_request("tools/call", id=80, params={
            "name": "harness_gate_create",
            "arguments": {
                "gate_type": "hybrid",
                "checks": [
                    {"id": "chk-1", "category": "security", "severity": "high", "description": "No eval"},
                ],
            },
        })
        resp = server.handle_request(req)
        assert "result" in resp
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["mode"] == "hybrid"
        assert data["check_count"] == 1

    def test_harness_gate_create_strict_with_auto_fix(self):
        server = _make_server()
        req = _make_request("tools/call", id=81, params={
            "name": "harness_gate_create",
            "arguments": {
                "gate_type": "strict",
                "checks": [
                    {"id": "chk-s1", "category": "logic", "severity": "critical", "description": "Logic check"},
                    {"id": "chk-s2", "category": "style", "severity": "medium", "description": "Style check"},
                ],
                "auto_fix": True,
            },
        })
        resp = server.handle_request(req)
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["mode"] == "strict"
        assert data["check_count"] == 2
        assert data["auto_fix"] == True


# ═════════════════════════════════════════════════════════════════
#  10. tools/call — harness_guardrails_check (2 tests)
# ═════════════════════════════════════════════════════════════════

class TestHarnessGuardrailsCheck:
    def test_guardrails_check_input(self):
        server = _make_server()
        req = _make_request("tools/call", id=90, params={
            "name": "harness_guardrails_check",
            "arguments": {"content": "Hello, this is safe content.", "direction": "input"},
        })
        resp = server.handle_request(req)
        assert "result" in resp
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["action"] in ["warn", "block", "redact", "replace"]
        assert not data["blocked"]

    def test_guardrails_check_output_with_pii(self):
        server = _make_server()
        req = _make_request("tools/call", id=91, params={
            "name": "harness_guardrails_check",
            "arguments": {"content": "user@example.com is the email", "direction": "output"},
        })
        resp = server.handle_request(req)
        assert "result" in resp
        data = json.loads(resp["result"]["content"][0]["text"])
        # Default output guardrails redact PII
        assert data["action"] in ["warn", "block", "redact", "replace"]


# ═════════════════════════════════════════════════════════════════
#  11. JSON-RPC error format (5 tests)
# ═════════════════════════════════════════════════════════════════

class TestJsonRpcErrors:
    def test_unknown_method_returns_method_not_found(self):
        server = _make_server()
        req = _make_request("nonexistent/method", id=100)
        resp = server.handle_request(req)
        assert "error" in resp
        assert resp["error"]["code"] == METHOD_NOT_FOUND
        assert "not found" in resp["error"]["message"].lower()

    def test_unknown_tool_returns_error(self):
        server = _make_server()
        req = _make_request("tools/call", id=101, params={
            "name": "nonexistent_tool",
            "arguments": {},
        })
        resp = server.handle_request(req)
        assert "error" in resp
        assert resp["error"]["code"] == METHOD_NOT_FOUND

    def test_missing_tool_name_returns_invalid_params(self):
        server = _make_server()
        req = _make_request("tools/call", id=102, params={
            "arguments": {"path": "/src"},
        })
        resp = server.handle_request(req)
        assert "error" in resp
        assert resp["error"]["code"] == INVALID_PARAMS

    def test_non_dict_params_returns_invalid_params(self):
        server = _make_server()
        req = {"jsonrpc": "2.0", "id": 103, "method": "tools/call", "params": "bad_string"}
        resp = server.handle_request(req)
        assert "error" in resp
        assert resp["error"]["code"] == INVALID_PARAMS

    def test_invalid_jsonrpc_version(self):
        server = _make_server()
        req = {"jsonrpc": "1.0", "id": 104, "method": "initialize"}
        resp = server.handle_request(req)
        assert "error" in resp
        assert resp["error"]["code"] == INVALID_REQUEST


# ═════════════════════════════════════════════════════════════════
#  12. JSON-RPC parse error (2 tests)
# ═════════════════════════════════════════════════════════════════

class TestParseErrors:
    def test_non_dict_request_returns_invalid_request(self):
        server = _make_server()
        resp = server.handle_request("not a dict")
        assert "error" in resp
        assert resp["error"]["code"] == INVALID_REQUEST

    def test_missing_method_returns_invalid_request(self):
        server = _make_server()
        req = {"jsonrpc": "2.0", "id": 200}
        resp = server.handle_request(req)
        assert "error" in resp
        assert resp["error"]["code"] == INVALID_REQUEST


# ═════════════════════════════════════════════════════════════════
#  13. harness exceptions → MCP error response (3 tests)
# ═════════════════════════════════════════════════════════════════

class TestHarnessExceptionConversion:
    def test_compliance_engine_error_converted(self):
        """Force a ComplianceEngine error → MCP error response."""
        server = _make_server()
        with patch.object(ComplianceEngine, "scan_quick", side_effect=ValueError("scan error")):
            req = _make_request("tools/call", id=300, params={
                "name": "harness_check",
                "arguments": {"path": "/bad"},
            })
            resp = server.handle_request(req)
            assert "error" in resp
            assert resp["error"]["code"] == INTERNAL_ERROR
            assert "scan error" in resp["error"]["message"]

    def test_audit_search_error_converted(self):
        """Force an AuditEngine error → MCP error response."""
        server = _make_server()
        with patch.object(server._audit_engine, "search", side_effect=RuntimeError("audit broken")):
            req = _make_request("tools/call", id=301, params={
                "name": "harness_audit",
                "arguments": {"query": "test"},
            })
            resp = server.handle_request(req)
            assert "error" in resp
            assert resp["error"]["code"] == INTERNAL_ERROR

    def test_tool_execution_generic_exception(self):
        """Any exception in tool execution → INTERNAL_ERROR."""
        server = _make_server()
        with patch.object(server._dag_engine, "_topological_sort", side_effect=Exception("boom")):
            req = _make_request("tools/call", id=302, params={
                "name": "harness_plan",
                "arguments": {"workflow_yaml": "id: x\nnodes:\n- id: n1\n  agent_type: coder\n  task: t"},
            })
            resp = server.handle_request(req)
            assert "error" in resp
            assert resp["error"]["code"] == INTERNAL_ERROR


# ═════════════════════════════════════════════════════════════════
#  14. stdio transport simulation (3 tests)
# ═════════════════════════════════════════════════════════════════

class TestStdioTransport:
    def test_stdio_single_request(self):
        """Simulate a single request over StringIO."""
        server = _make_server()
        input_data = json.dumps(_make_request("initialize", id=1)) + "\n"
        stdin = io.StringIO(input_data)
        stdout = io.StringIO()
        server.run(stdin=stdin, stdout=stdout)

        output = stdout.getvalue()
        lines = [l for l in output.strip().split("\n") if l]
        assert len(lines) == 1
        resp = json.loads(lines[0])
        assert resp["result"]["serverInfo"]["name"] == "harness-cook"

    def test_stdio_multiple_requests(self):
        """Multiple JSON-RPC requests in sequence."""
        server = _make_server()
        lines_in = []
        lines_in.append(json.dumps(_make_request("initialize", id=1)))
        lines_in.append(json.dumps(_make_request("tools/list", id=2)))
        lines_in.append(json.dumps(_make_request("tools/call", id=3, params={
            "name": "harness_status", "arguments": {},
        })))
        input_data = "\n".join(lines_in) + "\n"
        stdin = io.StringIO(input_data)
        stdout = io.StringIO()
        server.run(stdin=stdin, stdout=stdout)

        output_lines = [l for l in stdout.getvalue().strip().split("\n") if l]
        assert len(output_lines) == 3
        r1 = json.loads(output_lines[0])
        assert r1["result"]["serverInfo"]["name"] == "harness-cook"
        r2 = json.loads(output_lines[1])
        assert len(r2["result"]["tools"]) >= 8
        r3 = json.loads(output_lines[2])
        assert "registry" in r3["result"]["content"][0]["text"]

    def test_stdio_malformed_json_returns_parse_error(self):
        """Malformed JSON input → parse error response."""
        server = _make_server()
        input_data = "{bad json}\n"
        stdin = io.StringIO(input_data)
        stdout = io.StringIO()
        server.run(stdin=stdin, stdout=stdout)

        output_lines = [l for l in stdout.getvalue().strip().split("\n") if l]
        assert len(output_lines) == 1
        resp = json.loads(output_lines[0])
        assert resp["error"]["code"] == PARSE_ERROR


# ═════════════════════════════════════════════════════════════════
#  15. Concurrent request handling (2 tests)
# ═════════════════════════════════════════════════════════════════

class TestConcurrentRequests:
    def test_concurrent_initialize_and_status(self):
        """Two threads making requests concurrently should both succeed."""
        server = _make_server()
        results = {}

        def thread_init():
            req = _make_request("initialize", id=400)
            results["init"] = server.handle_request(req)

        def thread_status():
            req = _make_request("tools/call", id=401, params={
                "name": "harness_status", "arguments": {},
            })
            results["status"] = server.handle_request(req)

        t1 = threading.Thread(target=thread_init)
        t2 = threading.Thread(target=thread_status)
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert "init" in results
        assert "status" in results
        assert results["init"]["result"]["serverInfo"]["name"] == "harness-cook"
        # Status result is wrapped in content
        status_text = results["status"]["result"]["content"][0]["text"]
        status_data = json.loads(status_text)
        assert "registry" in status_data

    def test_concurrent_register_agents(self):
        """Register two agents concurrently."""
        server = _make_server()
        results = {}

        def thread_reg1():
            req = _make_request("tools/call", id=410, params={
                "name": "harness_register",
                "arguments": {"agent_id": "agent-a", "name": "Agent A"},
            })
            results["a"] = server.handle_request(req)

        def thread_reg2():
            req = _make_request("tools/call", id=411, params={
                "name": "harness_register",
                "arguments": {"agent_id": "agent-b", "name": "Agent B"},
            })
            results["b"] = server.handle_request(req)

        t1 = threading.Thread(target=thread_reg1)
        t2 = threading.Thread(target=thread_reg2)
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert "a" in results
        assert "b" in results
        data_a = json.loads(results["a"]["result"]["content"][0]["text"])
        data_b = json.loads(results["b"]["result"]["content"][0]["text"])
        assert data_a["agent_id"] == "agent-a"
        assert data_b["agent_id"] == "agent-b"


# ═════════════════════════════════════════════════════════════════
#  16. Edge cases (3 tests)
# ═════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_null_id_in_request(self):
        """JSON-RPC allows null id for notifications (but we still respond)."""
        server = _make_server()
        req = {"jsonrpc": "2.0", "id": None, "method": "initialize"}
        resp = server.handle_request(req)
        assert resp["id"] is None
        assert "result" in resp

    def test_empty_string_request(self):
        """Empty string is not a valid JSON-RPC request."""
        server = _make_server()
        resp = server.handle_request("")
        assert "error" in resp

    def test_tools_call_without_arguments_key(self):
        """tools/call with params but no 'arguments' key — should default to empty."""
        server = _make_server()
        req = _make_request("tools/call", id=500, params={
            "name": "harness_status",
        })
        resp = server.handle_request(req)
        assert "result" in resp
        # status tool works with empty arguments
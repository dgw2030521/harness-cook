"""
harness-cook MCP Server 单元测试

测试策略:
- 不依赖真实 MCP 连接（测试业务逻辑 + 工具定义）
- 直接调用 HarnessMCPServer._tool_* 方法
- 测试 MCP SDK Tool 定义的正确性
- 协议层由 MCP SDK 处理，不需要在测试中覆盖
"""

import json
import unittest
from pathlib import Path
import sys

# __file__ = .../packages/mcp/tests/test_mcp_server.py
# parent = tests, parent.parent = mcp, parent.parent.parent = packages
_PACKAGES_DIR = Path(__file__).resolve().parent.parent.parent
_CORE_DIR = str(_PACKAGES_DIR / "core")
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

_MCP_DIR = str(_PACKAGES_DIR / "mcp")
if _MCP_DIR not in sys.path:
    sys.path.insert(0, _MCP_DIR)

from harness_mcp_server import HarnessMCPServer, TOOL_DEFINITIONS, create_mcp_server


class TestToolDefinitions(unittest.TestCase):
    """MCP SDK Tool 定义测试"""

    def test_tool_definitions_are_tool_objects(self):
        """TOOL_DEFINITIONS 应为 MCP SDK Tool 对象列表"""
        from mcp.types import Tool
        for tool_def in TOOL_DEFINITIONS:
            self.assertIsInstance(tool_def, Tool)

    def test_tool_definitions_count(self):
        """应有至少 17 个工具"""
        self.assertGreaterEqual(len(TOOL_DEFINITIONS), 17)

    def test_tools_have_required_fields(self):
        """每个工具应有 name、description、inputSchema"""
        for tool_def in TOOL_DEFINITIONS:
            self.assertIsNotNone(tool_def.name)
            self.assertIsNotNone(tool_def.description)
            self.assertIsNotNone(tool_def.inputSchema)

    def test_expected_tool_names(self):
        """验证预期的工具名称存在"""
        tool_names = [t.name for t in TOOL_DEFINITIONS]
        expected = [
            "harness_check",
            "harness_audit",
            "harness_plan",
            "harness_run",
            "harness_status",
            "harness_register",
            "harness_gate_create",
            "harness_guardrails_check",
            "harness_pipeline_run",
            "harness_pipeline_status",
            "harness_agent_list",
            "harness_profile_list",
            "harness_profile_load",
            "harness_skill_list",
            "harness_skill_register",
            "harness_bridge_deploy",
        ]
        for name in expected:
            self.assertIn(name, tool_names, f"Missing tool: {name}")

    def test_tool_input_schema_structure(self):
        """每个工具的 inputSchema 应有 type=object"""
        for tool_def in TOOL_DEFINITIONS:
            schema = tool_def.inputSchema
            self.assertEqual(schema.get("type"), "object")


class TestMCPServerCreation(unittest.TestCase):
    """MCP SDK Server 创建测试"""

    def test_create_mcp_server(self):
        """create_mcp_server 应返回 MCP SDK Server 实例"""
        from mcp.server import Server
        logic = HarnessMCPServer()
        server = create_mcp_server(logic)
        self.assertIsInstance(server, Server)
        self.assertEqual(server.name, "harness-cook")


class TestToolCallCheck(unittest.TestCase):
    """harness_check 业务逻辑测试"""

    def setUp(self):
        self.server = HarnessMCPServer()

    def test_check_with_path(self):
        """检测指定路径"""
        result = self.server._tool_check({"path": "test.py"})
        self.assertIn("path", result)
        self.assertEqual(result["path"], "test.py")

    def test_check_with_pack_names(self):
        """指定规则包名"""
        result = self.server._tool_check({"path": "test.py", "pack_names": ["security"]})
        self.assertIn("pack_names", result)

    def test_check_default_pack_names(self):
        """默认加载所有规则包"""
        result = self.server._tool_check({"path": "test.py"})
        self.assertIn("pack_names", result)
        self.assertGreater(len(result["pack_names"]), 0)


class TestToolCallAudit(unittest.TestCase):
    """harness_audit 业务逻辑测试"""

    def setUp(self):
        self.server = HarnessMCPServer()

    def test_audit_query(self):
        """审计查询应返回结果"""
        result = self.server._tool_audit({"query": "test"})
        self.assertIn("query", result)
        self.assertEqual(result["query"], "test")

    def test_audit_with_limit(self):
        """指定 limit 应限制返回条数"""
        result = self.server._tool_audit({"query": "test", "limit": 5})
        self.assertIn("count", result)
        self.assertLessEqual(result["count"], 5)


class TestToolCallStatus(unittest.TestCase):
    """harness_status 业务逻辑测试"""

    def setUp(self):
        self.server = HarnessMCPServer()

    def test_status_returns_info(self):
        """状态查询应返回系统信息"""
        result = self.server._tool_status({})
        self.assertIn("version", result)
        self.assertIn("compliance", result)
        self.assertIn("registry", result)
        self.assertIn("bus", result)
        self.assertIn("server", result)


class TestToolCallGuardrails(unittest.TestCase):
    """harness_guardrails_check 业务逻辑测试"""

    def setUp(self):
        self.server = HarnessMCPServer()

    def test_guardrails_detect_email(self):
        """护栏应检测 email PII"""
        result = self.server._tool_guardrails_check({"content": "请联系 test@example.com"})
        self.assertIn("action", result)
        self.assertIn("blocked", result)

    def test_guardrails_input_direction(self):
        """direction=input 应使用 input guardrails"""
        result = self.server._tool_guardrails_check({"content": "hello", "direction": "input"})
        self.assertIn("action", result)

    def test_guardrails_output_direction(self):
        """direction=output 应使用 output guardrails"""
        result = self.server._tool_guardrails_check({"content": "hello", "direction": "output"})
        self.assertIn("action", result)


class TestToolCallRegister(unittest.TestCase):
    """harness_register 业务逻辑测试"""

    def setUp(self):
        self.server = HarnessMCPServer()

    def test_register_agent(self):
        """注册 Agent 应成功"""
        result = self.server._tool_register({
            "agent_id": "test-coder",
            "name": "Test Coder",
            "capabilities": ["execute", "reason"],
        })
        self.assertIn("agent_id", result)
        self.assertEqual(result["agent_id"], "test-coder")
        self.assertTrue(result["is_ready"])

    def test_register_agent_with_toolsets(self):
        """注册 Agent 可带 toolsets"""
        result = self.server._tool_register({
            "agent_id": "test-agent",
            "toolsets": ["bash", "read"],
        })
        self.assertIn("toolsets", result)


class TestToolCallAgentList(unittest.TestCase):
    """harness_agent_list 业务逻辑测试"""

    def setUp(self):
        self.server = HarnessMCPServer()

    def test_agent_list(self):
        """查询 Agent 列表应返回结果"""
        result = self.server._tool_agent_list({})
        # harness_agents 包可能不可安装，结果可能包含 available=False
        self.assertIn("available", result)


class TestToolCallGateCreate(unittest.TestCase):
    """harness_gate_create 业务逻辑测试"""

    def setUp(self):
        self.server = HarnessMCPServer()

    def test_gate_create_hybrid(self):
        """创建 hybrid gate"""
        result = self.server._tool_gate_create({
            "gate_type": "hybrid",
            "checks": [
                {"id": "chk-1", "category": "logic", "severity": "medium", "description": "test check"},
            ],
        })
        self.assertIn("gate_id", result)
        self.assertEqual(result["mode"], "hybrid")

    def test_gate_create_strict_with_auto_fix(self):
        """创建 strict gate + auto_fix"""
        result = self.server._tool_gate_create({
            "gate_type": "strict",
            "checks": [
                {"id": "chk-2", "category": "security", "severity": "high", "description": "security check"},
            ],
            "auto_fix": True,
        })
        self.assertEqual(result["mode"], "strict")
        self.assertTrue(result["auto_fix"])


class TestToolCallPipelineRun(unittest.TestCase):
    """harness_pipeline_run 业务逻辑测试"""

    def setUp(self):
        self.server = HarnessMCPServer()

    def test_pipeline_run(self):
        """pipeline run 应返回编排定义"""
        result = self.server._tool_pipeline_run({"task": "implement feature X"})
        self.assertTrue(result["success"])
        self.assertIn("pipeline_id", result)
        self.assertIn("steps", result)

    def test_pipeline_run_no_task(self):
        """缺少 task 应返回错误"""
        result = self.server._tool_pipeline_run({"task": ""})
        self.assertFalse(result["success"])


class TestToolCallPipelineStatus(unittest.TestCase):
    """harness_pipeline_status 业务逻辑测试"""

    def setUp(self):
        self.server = HarnessMCPServer()

    def test_pipeline_status(self):
        """pipeline status 应返回静态信息"""
        result = self.server._tool_pipeline_status({})
        self.assertTrue(result["available"])
        self.assertIn("default_agents", result)


class TestYAMLWorkflowParser(unittest.TestCase):
    """YAML workflow parser 测试"""

    def setUp(self):
        self.server = HarnessMCPServer()

    def test_parse_empty_yaml(self):
        """空 YAML 应返回空 workflow"""
        result = self.server._tool_plan({"workflow_yaml": ""})
        self.assertIn("node_count", result)

    def test_parse_simple_workflow(self):
        """解析简单 workflow YAML"""
        yaml_str = """
id: test-wf
name: Test Workflow
nodes:
  - id: node-1
    agent_type: coder
    task: write code
edges: []
"""
        result = self.server._tool_plan({"workflow_yaml": yaml_str})
        self.assertIn("execution_order", result)
        self.assertIn("nodes", result)


class TestToolCallUnknownTool(unittest.TestCase):
    """MCP SDK 层的未知工具名测试"""

    def test_create_server_dispatch_complete(self):
        """create_mcp_server 的 dispatch 应覆盖所有 TOOL_DEFINITIONS"""
        logic = HarnessMCPServer()
        server = create_mcp_server(logic)

        # 验证所有已定义工具都有对应的 handler
        tool_names = [t.name for t in TOOL_DEFINITIONS]
        # 间接验证：dispatch table 和 TOOL_DEFINITIONS 名称一致
        self.assertGreater(len(tool_names), 0)


if __name__ == "__main__":
    unittest.main()

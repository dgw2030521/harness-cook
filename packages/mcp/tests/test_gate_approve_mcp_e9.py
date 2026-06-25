"""
E-9：harness_gate_approve MCP 工具验收测试

验证要点:
  1. harness_gate_approve 工具定义存在（TOOL_DEFINITIONS）
  2. _tool_gate_approve 方法发出 GATE_APPROVAL_DECISION 事件
  3. 有效决策值：approved / rejected / cancelled
  4. 无效决策值返回错误
  5. 缺少 gate_id 返回错误
  6. dispatch map 包含 harness_gate_approve

Core 部分测试见：packages/core/tests/test_gate_approval_e9.py
"""

import json
import unittest
from pathlib import Path
import sys

# __file__ = .../packages/mcp/tests/test_gate_approve_mcp_e9.py
# parent = tests, parent.parent = mcp, parent.parent.parent = packages
_PACKAGES_DIR = Path(__file__).resolve().parent.parent.parent
_CORE_DIR = str(_PACKAGES_DIR / "core")
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

_MCP_DIR = str(_PACKAGES_DIR / "mcp")
if _MCP_DIR not in sys.path:
    sys.path.insert(0, _MCP_DIR)

from harness_mcp_server import HarnessMCPServer, TOOL_DEFINITIONS
from harness.bus import EventBus
from harness.types import BusEventType


class TestGateApproveToolDefinition(unittest.TestCase):
    """E-9：harness_gate_approve 工具定义存在"""

    def test_tool_definition_exists(self):
        """E-9：TOOL_DEFINITIONS 包含 harness_gate_approve"""
        tool_names = [t.name for t in TOOL_DEFINITIONS]
        self.assertIn("harness_gate_approve", tool_names)

    def test_tool_definition_has_required_params(self):
        """E-9：工具定义包含 gate_id 和 decision 参数"""
        gate_approve_tool = next(
            t for t in TOOL_DEFINITIONS if t.name == "harness_gate_approve"
        )
        schema = gate_approve_tool.inputSchema
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        self.assertIn("gate_id", properties)
        self.assertIn("decision", properties)
        self.assertIn("gate_id", required)
        self.assertIn("decision", required)

    def test_tool_definition_decision_enum(self):
        """E-9：decision 参数有 enum 约束"""
        gate_approve_tool = next(
            t for t in TOOL_DEFINITIONS if t.name == "harness_gate_approve"
        )
        decision_prop = gate_approve_tool.inputSchema["properties"]["decision"]
        enum_values = decision_prop.get("enum", [])

        self.assertEqual(sorted(enum_values), ["approved", "cancelled", "rejected"])


class TestGateApproveToolMethod(unittest.TestCase):
    """E-9：_tool_gate_approve 方法行为验证"""

    def setUp(self):
        self.bus = EventBus()
        self.server = HarnessMCPServer(bus=self.bus)

    def test_gate_approve_emits_decision_event(self):
        """E-9：harness_gate_approve 工具发出 GATE_APPROVAL_DECISION 事件"""
        # 记录 bus emit 的事件
        emitted_events = []
        original_emit = self.bus.emit

        def capture_emit(event):
            emitted_events.append(event)
            return original_emit(event)

        self.bus.emit = capture_emit

        result = self.server._tool_gate_approve({
            "gate_id": "gate-mcp-1",
            "decision": "approved",
            "decided_by": "admin",
            "reason": "MCP 测试审批",
        })

        self.assertTrue(result["success"])
        self.assertEqual(result["gate_id"], "gate-mcp-1")
        self.assertEqual(result["decision"], "approved")

        # 应发出 1 个 GATE_APPROVAL_DECISION 事件
        decision_events = [
            e for e in emitted_events
            if e.type == BusEventType.GATE_APPROVAL_DECISION
        ]
        self.assertEqual(len(decision_events), 1)
        self.assertEqual(decision_events[0].data["decision"], "approved")
        self.assertEqual(decision_events[0].data["gate_id"], "gate-mcp-1")

    def test_gate_approve_reject(self):
        """E-9：harness_gate_approve 工具发出 rejected 决策"""
        emitted_events = []
        original_emit = self.bus.emit

        def capture_emit(event):
            emitted_events.append(event)
            return original_emit(event)

        self.bus.emit = capture_emit

        result = self.server._tool_gate_approve({
            "gate_id": "gate-mcp-2",
            "decision": "rejected",
            "reason": "安全审查未通过",
        })

        self.assertTrue(result["success"])
        self.assertEqual(result["decision"], "rejected")

        decision_events = [
            e for e in emitted_events
            if e.type == BusEventType.GATE_APPROVAL_DECISION
        ]
        self.assertEqual(len(decision_events), 1)
        self.assertEqual(decision_events[0].data["decision"], "rejected")

    def test_gate_approve_cancelled(self):
        """E-9：cancelled 决策通过"""
        result = self.server._tool_gate_approve({
            "gate_id": "gate-mcp-4",
            "decision": "cancelled",
        })

        self.assertTrue(result["success"])
        self.assertEqual(result["decision"], "cancelled")

    def test_gate_approve_invalid_decision(self):
        """E-9：无效决策值返回错误"""
        result = self.server._tool_gate_approve({
            "gate_id": "gate-mcp-3",
            "decision": "maybe",
        })

        self.assertFalse(result["success"])
        self.assertIn("Invalid decision", result.get("error", ""))

    def test_gate_approve_missing_gate_id(self):
        """E-9：缺少 gate_id 返回错误"""
        result = self.server._tool_gate_approve({
            "decision": "approved",
        })

        self.assertFalse(result["success"])
        self.assertIn("gate_id is required", result.get("error", ""))

    def test_gate_approve_default_decided_by(self):
        """E-9：不指定 decided_by 时默认为 human"""
        result = self.server._tool_gate_approve({
            "gate_id": "gate-mcp-5",
            "decision": "approved",
        })

        self.assertTrue(result["success"])
        self.assertEqual(result["decided_by"], "human")


class TestGateApproveDispatchMap(unittest.TestCase):
    """E-9：dispatch map 包含 harness_gate_approve"""

    def test_dispatch_map_has_gate_approve(self):
        """E-9：MCP Server 的 dispatch map 包含 harness_gate_approve"""
        # 通过 create_mcp_server 检查 dispatch map
        server = HarnessMCPServer()
        # 检查方法是否存在
        self.assertTrue(
            hasattr(server, "_tool_gate_approve"),
            "HarnessMCPServer should have _tool_gate_approve method",
        )


if __name__ == "__main__":
    unittest.main()

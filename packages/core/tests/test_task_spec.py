"""
TaskSpec（任务验收契约）单元测试

测试策略:
- TaskSpec 是执行前的正面定义，Constraints 是禁止做什么
- 验证 _verify_spec 方法在不同场景下的行为
- 验证 DAGNode.spec 字段的向后兼容性（spec=None 时原有行为不变）
"""

import unittest
from harness.types import (
    TaskSpec, DAGNode, TaskResult, TaskStatus, Artifact,
    GateDefinition, GateMode,
)
from harness.engine import DAGEngine, ExecutionContext


class TestTaskSpecDefinition(unittest.TestCase):
    """TaskSpec 数据结构测试"""

    def test_task_spec_creation(self):
        """TaskSpec 应能正常创建"""
        spec = TaskSpec(
            objective="实现用户认证模块",
            acceptance_criteria=[
                "所有测试通过",
                "无硬编码密钥",
                "API 返回 200/401/403",
            ],
        )
        self.assertEqual(spec.objective, "实现用户认证模块")
        self.assertEqual(len(spec.acceptance_criteria), 3)

    def test_task_spec_with_schema(self):
        """TaskSpec 可带输入/输出 schema"""
        spec = TaskSpec(
            objective="生成配置文件",
            acceptance_criteria=["配置文件格式正确"],
            input_schema={"type": "object", "required": ["template"]},
            output_schema={"type": "object", "required": ["config"]},
        )
        self.assertIsNotNone(spec.input_schema)
        self.assertIsNotNone(spec.output_schema)

    def test_task_spec_defaults(self):
        """TaskSpec 默认值应合理"""
        spec = TaskSpec(objective="做点什么")
        self.assertEqual(len(spec.acceptance_criteria), 0)
        self.assertEqual(spec.max_retries, 2)
        self.assertEqual(spec.timeout_seconds, 300)
        self.assertIsNone(spec.input_schema)
        self.assertIsNone(spec.output_schema)


class TestDAGNodeWithSpec(unittest.TestCase):
    """DAGNode + TaskSpec 向后兼容测试"""

    def test_dag_node_without_spec(self):
        """无 spec 的 DAGNode 应保持原有行为"""
        node = DAGNode(
            id="test-node",
            agent_type="coder",
            task="写代码",
            inputs=["input-1"],
            outputs=["output-1"],
        )
        self.assertIsNone(node.spec)

    def test_dag_node_with_spec(self):
        """有 spec 的 DAGNode 应正确持有 TaskSpec"""
        spec = TaskSpec(
            objective="写认证代码",
            acceptance_criteria=["所有测试通过"],
        )
        node = DAGNode(
            id="test-node",
            agent_type="coder",
            task="写代码",
            inputs=["input-1"],
            outputs=["output-1"],
            spec=spec,
        )
        self.assertIsNotNone(node.spec)
        self.assertEqual(node.spec.objective, "写认证代码")

    def test_dag_node_backward_compat(self):
        """旧代码创建 DAGNode 无 spec 参数 → 不出错"""
        # 不传 spec，沿用旧方式
        node = DAGNode(
            id="n1",
            agent_type="coder",
            task="task",
            inputs=[],
            outputs=[],
        )
        self.assertIsNone(node.spec)
        self.assertIsNone(node.gate)


class TestVerifySpecMethod(unittest.TestCase):
    """DAGEngine._verify_spec 方法测试"""

    def setUp(self):
        self.engine = DAGEngine()

    def test_verify_spec_no_spec_returns_none(self):
        """无 TaskSpec 时 _verify_spec 返回 None（向后兼容）"""
        node = DAGNode(
            id="n1", agent_type="coder", task="task", inputs=[], outputs=[]
        )
        result = TaskResult(
            task_id="t1", agent_id="a1", status=TaskStatus.COMPLETED
        )
        ctx = ExecutionContext(
            execution_id="e1", workflow_id="w1"
        )
        spec_result = self.engine._verify_spec(node, result, ctx)
        self.assertIsNone(spec_result)

    def test_verify_spec_with_empty_criteria(self):
        """空验收标准 + COMPLETED 状态 → passed"""
        node = DAGNode(
            id="n1", agent_type="coder", task="task", inputs=[], outputs=[],
            spec=TaskSpec(objective="做任务", acceptance_criteria=[]),
        )
        result = TaskResult(
            task_id="t1", agent_id="a1", status=TaskStatus.COMPLETED
        )
        ctx = ExecutionContext(execution_id="e1", workflow_id="w1")
        spec_result = self.engine._verify_spec(node, result, ctx)
        self.assertIsNotNone(spec_result)
        self.assertTrue(spec_result["passed"])

    def test_verify_spec_pass_criteria(self):
        """"通过"类验收标准 + COMPLETED → passed"""
        node = DAGNode(
            id="n1", agent_type="coder", task="task", inputs=[], outputs=[],
            spec=TaskSpec(objective="做任务", acceptance_criteria=["所有测试通过"]),
        )
        result = TaskResult(
            task_id="t1", agent_id="a1", status=TaskStatus.COMPLETED
        )
        ctx = ExecutionContext(execution_id="e1", workflow_id="w1")
        spec_result = self.engine._verify_spec(node, result, ctx)
        self.assertTrue(spec_result["passed"])

    def test_verify_spec_failed_status_fails_all(self):
        """TaskResult.FAILED 状态 → 所有标准都不满足"""
        node = DAGNode(
            id="n1", agent_type="coder", task="task", inputs=[], outputs=[],
            spec=TaskSpec(objective="做任务", acceptance_criteria=["所有测试通过"]),
        )
        result = TaskResult(
            task_id="t1", agent_id="a1", status=TaskStatus.FAILED
        )
        ctx = ExecutionContext(execution_id="e1", workflow_id="w1")
        spec_result = self.engine._verify_spec(node, result, ctx)
        self.assertFalse(spec_result["passed"])
        self.assertIn("所有测试通过", spec_result["failed_criteria"])

    def test_verify_spec_no_keyword_pass(self):
        """"无硬编码密钥"类标准 + 无密钥的 artifacts → passed"""
        node = DAGNode(
            id="n1", agent_type="coder", task="task", inputs=[], outputs=[],
            spec=TaskSpec(objective="写代码", acceptance_criteria=["无硬编码密钥"]),
        )
        result = TaskResult(
            task_id="t1", agent_id="a1", status=TaskStatus.COMPLETED,
            artifacts=[Artifact(type="code", path="auth.py", content="def login(): pass")],
        )
        ctx = ExecutionContext(execution_id="e1", workflow_id="w1")
        spec_result = self.engine._verify_spec(node, result, ctx)
        self.assertTrue(spec_result["passed"])

    def test_verify_spec_timeout_check(self):
        """超时标准 → duration_ms 超过阈值时失败"""
        node = DAGNode(
            id="n1", agent_type="coder", task="task", inputs=[], outputs=[],
            spec=TaskSpec(objective="做任务", acceptance_criteria=[], timeout_seconds=5),
        )
        result = TaskResult(
            task_id="t1", agent_id="a1", status=TaskStatus.COMPLETED,
            duration_ms=10000,  # 10秒 > 5秒阈值
        )
        ctx = ExecutionContext(execution_id="e1", workflow_id="w1")
        spec_result = self.engine._verify_spec(node, result, ctx)
        self.assertFalse(spec_result["passed"])
        self.assertTrue(any("Timeout" in c for c in spec_result["failed_criteria"]))

    def test_verify_spec_output_schema_check(self):
        """output_schema 检查 → required 字段缺失时失败"""
        node = DAGNode(
            id="n1", agent_type="coder", task="task", inputs=[], outputs=[],
            spec=TaskSpec(
                objective="生成配置",
                acceptance_criteria=[],
                output_schema={"type": "object", "required": ["module", "version"]},
            ),
        )
        # artifact.content 是 JSON 但缺少 version
        result = TaskResult(
            task_id="t1", agent_id="a1", status=TaskStatus.COMPLETED,
            artifacts=[Artifact(type="config", path="config.json", content='{"module": "auth"}')],
        )
        ctx = ExecutionContext(execution_id="e1", workflow_id="w1")
        spec_result = self.engine._verify_spec(node, result, ctx)
        self.assertFalse(spec_result["passed"])

    def test_verify_spec_output_schema_pass(self):
        """output_schema 检查 → required 字段存在时通过"""
        node = DAGNode(
            id="n1", agent_type="coder", task="task", inputs=[], outputs=[],
            spec=TaskSpec(
                objective="生成配置",
                acceptance_criteria=[],
                output_schema={"type": "object", "required": ["module"]},
            ),
        )
        result = TaskResult(
            task_id="t1", agent_id="a1", status=TaskStatus.COMPLETED,
            artifacts=[Artifact(type="config", path="config.json", content='{"module": "auth"}')],
        )
        ctx = ExecutionContext(execution_id="e1", workflow_id="w1")
        spec_result = self.engine._verify_spec(node, result, ctx)
        self.assertTrue(spec_result["passed"])


if __name__ == "__main__":
    unittest.main()

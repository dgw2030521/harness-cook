"""
TaskStatus Enum 向后兼容性测试

验证:
1. TaskStatus 枚举值与字符串比较
2. TaskResult 接受字符串 status 并自动转换
3. TaskStatus 在 dict/set 中可与字符串混用
4. 未知状态字符串的降级处理
"""

import unittest
from harness.types import TaskStatus, TaskResult


class TestTaskStatusCompatibility(unittest.TestCase):
    """TaskStatus 向后兼容性测试"""

    def test_enum_equals_string(self):
        """TaskStatus.COMPLETED == 'completed' 应返回 True"""
        self.assertTrue(TaskStatus.COMPLETED == "completed")
        self.assertTrue(TaskStatus.FAILED == "failed")
        self.assertTrue(TaskStatus.ESCALATED == "escalated")

    def test_string_equals_enum(self):
        """'completed' == TaskStatus.COMPLETED 应返回 True（反向比较）"""
        # __eq__ 返回 NotImplemented 时 Python 会尝试反向比较
        self.assertTrue("completed" == TaskStatus.COMPLETED)

    def test_enum_not_equals_wrong_string(self):
        """TaskStatus.COMPLETED != 'failed' 应返回 True"""
        self.assertFalse(TaskStatus.COMPLETED == "failed")

    def test_hash_compatibility(self):
        """TaskStatus 与字符串 hash 值一致，可在 dict/set 中混用"""
        d = {TaskStatus.COMPLETED: "ok", "failed": "err"}
        # Enum key 和 string key 应能共存
        self.assertEqual(d[TaskStatus.COMPLETED], "ok")
        self.assertEqual(d["failed"], "err")

        # set 中应能去重
        s = {TaskStatus.COMPLETED, "completed"}
        self.assertEqual(len(s), 1)

    def test_task_result_auto_convert_str(self):
        """TaskResult 接受字符串 status，__post_init__ 自动转为 Enum"""
        result = TaskResult(
            task_id="t1",
            agent_id="a1",
            status="completed",
        )
        self.assertIsInstance(result.status, TaskStatus)
        self.assertEqual(result.status, TaskStatus.COMPLETED)

    def test_task_result_accept_enum(self):
        """TaskResult 直接接受 Enum status"""
        result = TaskResult(
            task_id="t2",
            agent_id="a2",
            status=TaskStatus.FAILED,
        )
        self.assertIsInstance(result.status, TaskStatus)
        self.assertEqual(result.status, TaskStatus.FAILED)

    def test_task_result_unknown_status_degrades(self):
        """未知状态字符串应降级为 FAILED，原始值记录在 metadata"""
        result = TaskResult(
            task_id="t3",
            agent_id="a3",
            status="unknown_status",
        )
        self.assertIsInstance(result.status, TaskStatus)
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(result.metadata.get("_original_status"), "unknown_status")

    def test_default_status_is_completed(self):
        """TaskResult 默认 status 应为 COMPLETED"""
        result = TaskResult(task_id="t4", agent_id="a4")
        self.assertEqual(result.status, TaskStatus.COMPLETED)


if __name__ == "__main__":
    unittest.main()
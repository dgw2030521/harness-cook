"""
harness-sdk 内部工具——普通函数包装为 IExecutableAgent

当用户用 register_agent(definition, plain_function) 时，
需要一个适配器将普通函数包装为 IExecutableAgent 接口。
"""

import uuid
import logging
from typing import Callable, Dict, Any

from harness.types import AgentDefinition, IExecutableAgent, TaskResult, TaskStatus

logger = logging.getLogger("harness_sdk._wrapper")


class FunctionWrapper:
    """将普通函数包装为 IExecutableAgent

    用法（内部使用，开发者无需直接接触）:
        wrapper = FunctionWrapper(my_handler, definition)
        result = wrapper.execute("task", context)

    普通函数签名要求: fn(task: str, context: dict) -> TaskResult
    """

    def __init__(self, fn: Callable, definition: AgentDefinition):
        self._fn = fn
        self._definition = definition
        self.__name__ = fn.__name__
        self.__doc__ = fn.__doc__

    def execute(self, task: str, context: Dict[str, Any]) -> TaskResult:
        """执行任务——调用原函数"""
        try:
            result = self._fn(task, context)
            # 确保返回 TaskResult
            if isinstance(result, TaskResult):
                return result
            # 兜底: 如果函数返回了dict或其他类型，包装为TaskResult
            if isinstance(result, dict):
                return TaskResult(
                    task_id=context.get("task_id", str(uuid.uuid4())),
                    agent_id=self._definition.id,
                    status=result.get("status", TaskStatus.COMPLETED),
                    artifacts=result.get("artifacts", []),
                    duration_ms=result.get("duration_ms", 0),
                    tokens_used=result.get("tokens_used", 0),
                    error=result.get("error"),
                    metadata=result.get("metadata", {}),
                )
            # 无法识别 → 失败
            return TaskResult(
                task_id=context.get("task_id", str(uuid.uuid4())),
                agent_id=self._definition.id,
                status=TaskStatus.FAILED,
                artifacts=[],
                duration_ms=0,
                error=f"Handler returned unexpected type: {type(result).__name__}",
            )
        except Exception as e:
            logger.error(f"Agent {self._definition.id} handler error: {e}")
            return TaskResult(
                task_id=context.get("task_id", str(uuid.uuid4())),
                agent_id=self._definition.id,
                status=TaskStatus.FAILED,
                artifacts=[],
                duration_ms=0,
                error=str(e),
            )

    def estimate_tokens(self, task: str) -> int:
        """启发式估算: 每字符约4token + 基础开销500"""
        return len(task) * 4 + 500
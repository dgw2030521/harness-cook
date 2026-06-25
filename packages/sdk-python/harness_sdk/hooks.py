"""
harness-sdk 生命周期钩子——Agent 执行前后的拦截控制

Hook 系统让开发者在不修改 Agent 逻辑的前提下:
  - before_hook: 执行前拦截（加日志、注入上下文、校验输入）
  - after_hook: 执行后拦截（结果后处理、通知、审计记录）
  - error_hook: 异常拦截（错误上报、降级处理、重试触发）

设计模式: Chain of Responsibility
  - 多个 Hook 组成 HookChain，按注册顺序依次执行
  - 任一 Hook 可决定 SKIP（跳过后续）或 ABORT（中止执行）
  - 鸭子类型: Hook 只需 __call__ 方法，不需要继承基类

用法:
    from harness_sdk import before_hook, after_hook, error_hook

    @before_hook
    def log_input(context):
        print(f"Agent {context.agent_name} starting: {context.task}")

    @after_hook
    def notify_result(context):
        if context.result.status == "escalated":
            send_notification(context.result)

    @error_hook
    def report_error(context):
        log_to_monitoring(context.error)
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Callable, Dict, Any

from harness.types import TaskResult, AgentDefinition

logger = logging.getLogger("harness_sdk.hooks")


# ─── Hook 类型 ────────────────────────────────────────

class HookType(Enum):
    """钩子类型——三种生命周期拦截点"""
    BEFORE = "before"      # 执行前
    AFTER = "after"        # 执行后
    ON_ERROR = "on_error"  # 异常时


# ─── Hook 上下文 ────────────────────────────────────────

@dataclass
class HookContext:
    """Hook 执行上下文——传递给每个 Hook 的信息包

    before_hook 时: task + agent_name + agent_id + context 有值
    after_hook 时: 上述 + result 有值
    on_error 时: 上述 + error 有值
    """
    task: str = ""
    agent_name: str = ""
    agent_id: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    result: Optional[TaskResult] = None
    error: Optional[str] = None
    hook_type: HookType = HookType.BEFORE
    # metadata 供 Hook 写入自定义数据，传递给后续 Hook
    metadata: Dict[str, Any] = field(default_factory=dict)


# ─── Hook 结果 ────────────────────────────────────────

class HookResult(Enum):
    """Hook 执行结果——控制 HookChain 的流转

    CONTINUE: 正常通过，继续执行下一个 Hook
    SKIP: 跳过后续所有 Hook（但 Agent 继续执行）
    ABORT: 中止执行（Agent 不执行，直接返回失败 TaskResult）
    """
    CONTINUE = "continue"
    SKIP = "skip"
    ABORT = "abort"


# ─── Hook 基类 ────────────────────────────────────────

class Hook:
    """生命周期钩子基类

    鸭子类型: 只需 __call__(context) → HookResult 即可，
    不强制继承。本类提供类型提示 + 便捷构造。
    """

    def __init__(
        self,
        fn: Callable[[HookContext], HookResult],
        hook_type: HookType,
        name: Optional[str] = None,
    ):
        self._fn = fn
        self._hook_type = hook_type
        self._name = name or fn.__name__

    def __call__(self, context: HookContext) -> HookResult:
        """执行钩子"""
        try:
            context.hook_type = self._hook_type
            return self._fn(context)
        except Exception as e:
            logger.warning(f"Hook '{self._name}' 执行异常: {e}")
            return HookResult.CONTINUE  # Hook 异常不影响 Agent 执行

    @property
    def name(self) -> str:
        return self._name

    @property
    def hook_type(self) -> HookType:
        return self._hook_type


# ─── 装饰器快捷方式 ────────────────────────────────────

def before_hook(fn: Callable[[HookContext], HookResult]) -> Hook:
    """@before_hook——将函数注册为 before 钩子

    用法:
        @before_hook
        def validate_input(ctx: HookContext) -> HookResult:
            if len(ctx.task) > 10000:
                return HookResult.ABORT
            return HookResult.CONTINUE
    """
    return Hook(fn, HookType.BEFORE)


def after_hook(fn: Callable[[HookContext], HookResult]) -> Hook:
    """@after_hook——将函数注册为 after 钩子

    用法:
        @after_hook
        def log_result(ctx: HookContext) -> HookResult:
            print(f"Result: {ctx.result.status}")
            return HookResult.CONTINUE
    """
    return Hook(fn, HookType.AFTER)


def error_hook(fn: Callable[[HookContext], HookResult]) -> Hook:
    """@error_hook——将函数注册为 on_error 钩子

    用法:
        @error_hook
        def report_failure(ctx: HookContext) -> HookResult:
            alert_team(ctx.error)
            return HookResult.CONTINUE
    """
    return Hook(fn, HookType.ON_ERROR)


# ─── Hook Chain ────────────────────────────────────────

class HookChain:
    """钩子链——按注册顺序依次执行多个 Hook

    用法:
        chain = HookChain()
        chain.add(log_input)
        chain.add(validate_input)
        result = chain.run_before(task="...", agent_name="...", context={})
    """

    def __init__(self):
        self._before_hooks: List[Hook] = []
        self._after_hooks: List[Hook] = []
        self._error_hooks: List[Hook] = []

    def add(self, hook: Hook) -> None:
        """添加钩子到对应链"""
        if hook.hook_type == HookType.BEFORE:
            self._before_hooks.append(hook)
        elif hook.hook_type == HookType.AFTER:
            self._after_hooks.append(hook)
        elif hook.hook_type == HookType.ON_ERROR:
            self._error_hooks.append(hook)

    def run_before(self, task: str, agent_name: str, agent_id: str,
                   context: Dict[str, Any]) -> Optional[str]:
        """运行 before 钩子链

        Returns:
            None: 全部通过
            str: ABORT 原因（如有 Hook 返回 ABORT）
        """
        ctx = HookContext(
            task=task, agent_name=agent_name, agent_id=agent_id, context=context,
        )
        for hook in self._before_hooks:
            result = hook(ctx)
            if result == HookResult.ABORT:
                logger.info(f"Before hook '{hook.name}' aborted execution")
                return f"Aborted by hook '{hook.name}'"
            if result == HookResult.SKIP:
                logger.info(f"Before hook '{hook.name}' skipped remaining hooks")
                break
        return None

    def run_after(self, result: TaskResult, task: str, agent_name: str,
                  agent_id: str, context: Dict[str, Any]) -> None:
        """运行 after 钩子链"""
        ctx = HookContext(
            task=task, agent_name=agent_name, agent_id=agent_id,
            context=context, result=result,
        )
        for hook in self._after_hooks:
            hook_result = hook(ctx)
            if hook_result == HookResult.SKIP:
                break

    def run_on_error(self, error: str, task: str, agent_name: str,
                     agent_id: str, context: Dict[str, Any]) -> None:
        """运行 on_error 钩子链"""
        ctx = HookContext(
            task=task, agent_name=agent_name, agent_id=agent_id,
            context=context, error=error,
        )
        for hook in self._error_hooks:
            hook_result = hook(ctx)
            if hook_result == HookResult.SKIP:
                break

    def stats(self) -> Dict[str, Any]:
        """钩子链统计"""
        return {
            "before_hooks": len(self._before_hooks),
            "after_hooks": len(self._after_hooks),
            "error_hooks": len(self._error_hooks),
            "total_hooks": len(self._before_hooks) + len(self._after_hooks) + len(self._error_hooks),
        }
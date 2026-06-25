"""
harness-cook 事件总线

模块间通信的核心——所有组件通过 Bus 解耦：
  Engine → Bus → Audit (记录)
  Gate  → Bus → Learning (收集trace)
  Compliance → Bus → Negotiation (冲突检测)

项目级隔离（E-7）：
  get_bus(project_name="project-a") 返回项目A专属的 EventBus 实例。
  项目A的事件不会出现在项目B的 bus history 中。
  get_bus()（无参数）返回全局 Bus（向后兼容）。

设计原则：
  - 同步优先（简单可靠），异步可选
  - 事件不可变（发出后不修改）
  - 按事件类型订阅，不是按模块订阅
  - 按项目隔离（不同项目的 Bus 实例互不干扰）
"""

import logging
from collections import defaultdict
from typing import Callable, Optional, List
from concurrent.futures import ThreadPoolExecutor, Future
from harness.types import BusEvent, BusEventType


logger = logging.getLogger("harness.bus")


# ─── 事件处理器 ──────────────────────────────────────

class EventHandler:
    """事件处理器——一个订阅者对一类事件的响应函数"""

    def __init__(
        self,
        event_type: BusEventType,
        handler_fn: Callable[[BusEvent], None],
        name: str = "",
        priority: int = 0,          # 优先级，数字越小越先执行
    ):
        self.event_type = event_type
        self.handler_fn = handler_fn
        self.name = name or handler_fn.__name__
        self.priority = priority

    def __call__(self, event: BusEvent) -> None:
        try:
            self.handler_fn(event)
        except Exception as e:
            logger.error(f"Handler {self.name} failed: {e}", exc_info=True)


# ─── 事件总线 ────────────────────────────────────────

class EventBus:
    """
    事件总线——同步、有序、可观测的事件分发器

    项目级隔离（E-7）：
      每个 project_name 对应独立的 EventBus 实例。
      通过 get_bus(project_name) 获取项目级 Bus。

    用法:
        bus = get_bus()                       # 全局 Bus
        bus = get_bus("my-project")           # 项目级 Bus
        bus.subscribe(BusEventType.NODE_START, on_node_start)
        bus.emit(BusEvent(type=BusEventType.NODE_START, execution_id="ex-1"))
    """

    def __init__(self, project_name: Optional[str] = None):
        self._project_name = project_name
        self._handlers: dict[BusEventType, list[EventHandler]] = defaultdict(list)
        self._history: list[BusEvent] = []
        self._history_limit: int = 1000
        self._paused: bool = False
        self._paused_buffer: list[BusEvent] = []
        # 异步分发线程池（lazy init）
        self._async_executor: Optional[ThreadPoolExecutor] = None

    # ─── 订阅 ────────────────────────────────────────

    def subscribe(
        self,
        event_type: BusEventType,
        handler_fn: Callable[[BusEvent], None],
        name: str = "",
        priority: int = 0,
    ) -> EventHandler:
        """
        订阅事件类型

        Args:
            event_type: 要订阅的事件类型
            handler_fn: 处理函数，接收 BusEvent
            name: 处理器名称（用于日志）
            priority: 优先级，数字越小越先执行

        Returns:
            EventHandler 实例（可用于 unsubscribe）
        """
        handler = EventHandler(event_type, handler_fn, name, priority)
        self._handlers[event_type].append(handler)
        # 按优先级排序
        self._handlers[event_type].sort(key=lambda h: h.priority)
        logger.debug(f"Subscribed {handler.name} to {event_type.value} (priority={priority})")
        return handler

    def unsubscribe(self, handler: EventHandler) -> bool:
        """取消订阅"""
        handlers = self._handlers.get(handler.event_type, [])
        if handler in handlers:
            handlers.remove(handler)
            logger.debug(f"Unsubscribed {handler.name} from {handler.event_type.value}")
            return True
        return False

    # ─── 发射 ────────────────────────────────────────

    def emit(self, event: BusEvent) -> None:
        """
        发射事件——同步调用所有订阅者

        如果总线暂停，事件会被缓冲，恢复后批量发射。
        """
        if self._paused:
            self._paused_buffer.append(event)
            return

        self._record_history(event)

        handlers = self._handlers.get(event.type, [])
        if not handlers:
            logger.debug(f"No handlers for {event.type.value}")
            return

        for handler in handlers:
            handler(event)

    def emit_many(self, events: list[BusEvent]) -> None:
        """批量发射事件"""
        for event in events:
            self.emit(event)

    # ─── 异步分发 ──────────────────────────────────────

    def emit_async(self, event: BusEvent) -> None:
        """
        异步发射事件——在独立线程中调用所有订阅者

        与 emit() 的区别：
          - emit(): 同步，阻塞调用方直到所有 handler 执行完毕
          - emit_async(): 异步，立即返回，handler 在线程池中执行

        适用场景：
          - handler 包含重 IO 操作（审计写文件、合规扫描）
          - 发布者（如 DAGEngine）不希望被慢 handler 阻塞
          - handler 的执行结果不影响后续逻辑

        注意：
          - handler 异常不会传播到调用方，仅在日志中记录
          - 事件历史记录仍然同步写入（保证顺序性）
        """
        if self._paused:
            self._paused_buffer.append(event)
            return

        # 同步记录历史（保证顺序性）
        self._record_history(event)

        handlers = self._handlers.get(event.type, [])
        if not handlers:
            logger.debug(f"No handlers for {event.type.value} (async)")
            return

        # 在线程池中分发
        if self._async_executor is None:
            self._async_executor = ThreadPoolExecutor(
                max_workers=2,
                thread_name_prefix="harness-bus",
            )

        for handler in handlers:
            self._async_executor.submit(self._safe_call_handler, handler, event)

    def _safe_call_handler(self, handler: EventHandler, event: BusEvent) -> None:
        """安全调用 handler（捕获异常，记录日志）"""
        try:
            handler(event)
        except Exception as e:
            logger.error(f"Async handler {handler.name} failed: {e}", exc_info=True)

    def shutdown(self) -> None:
        """关闭线程池（通常在进程退出时调用）"""
        if self._async_executor:
            self._async_executor.shutdown(wait=False)
            self._async_executor = None

    # ─── 历史 ────────────────────────────────────────

    def _record_history(self, event: BusEvent) -> None:
        self._history.append(event)
        if len(self._history) > self._history_limit:
            self._history = self._history[-self._history_limit:]

    def get_history(
        self,
        event_type: Optional[BusEventType] = None,
        execution_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[BusEvent]:
        """
        查询事件历史

        Args:
            event_type: 按事件类型过滤
            execution_id: 按执行上下文过滤
            limit: 最大返回数量
        """
        events = self._history
        if event_type:
            events = [e for e in events if e.type == event_type]
        if execution_id:
            events = [e for e in events if e.execution_id == execution_id]
        return events[-limit:]

    def clear_history(self) -> None:
        self._history.clear()

    # ─── 暂停/恢复 ────────────────────────────────────

    def pause(self) -> None:
        """暂停事件分发——所有后续事件缓冲"""
        self._paused = True
        logger.info("EventBus paused — events will be buffered")

    def resume(self) -> None:
        """恢复事件分发——缓冲的事件批量发射"""
        self._paused = False
        logger.info(f"EventBus resumed — flushing {len(self._paused_buffer)} buffered events")
        for event in self._paused_buffer:
            self.emit(event)
        self._paused_buffer.clear()

    # ─── 诊断 ────────────────────────────────────────

    def stats(self) -> dict:
        """总线统计——订阅者数量、事件数量等"""
        return {
            "project_name": self._project_name or "__global__",
            "total_subscriptions": sum(len(h) for h in self._handlers.values()),
            "subscriptions_by_type": {
                et.value: len(handlers) for et, handlers in self._handlers.items()
            },
            "history_size": len(self._history),
            "paused": self._paused,
            "buffered_events": len(self._paused_buffer),
        }


# ─── 全局/项目级单例 ────────────────────────────────

_global_bus: Optional[EventBus] = None
_project_buses: dict[str, EventBus] = {}


def get_bus(project_name: Optional[str] = None) -> EventBus:
    """
    获取事件总线实例——按项目隔离（E-7）

    Args:
        project_name: 项目名。传入时返回项目级 Bus（独立实例）。
                      None 时返回全局 Bus（向后兼容）。

    Returns:
        项目级或全局 EventBus 实例
    """
    if project_name is None:
        global _global_bus
        if _global_bus is None:
            _global_bus = EventBus()
        return _global_bus

    global _project_buses
    if project_name not in _project_buses:
        _project_buses[project_name] = EventBus(project_name=project_name)
        logger.info(f"Created project-level EventBus for '{project_name}'")
    return _project_buses[project_name]


def reset_bus(project_name: Optional[str] = None) -> None:
    """
    重置事件总线（主要用于测试）

    Args:
        project_name: 重置指定项目的 Bus。None 时重置全局 Bus + 所有项目 Bus。
    """
    global _global_bus, _project_buses

    if project_name is None:
        # 重置全局 + 所有项目级 Bus
        _global_bus = EventBus()
        _project_buses.clear()
    else:
        # 只重置指定项目的 Bus
        _project_buses[project_name] = EventBus(project_name=project_name)


def list_project_buses() -> list[str]:
    """列出所有已创建的项目级 Bus 名称"""
    global _project_buses
    return list(_project_buses.keys())
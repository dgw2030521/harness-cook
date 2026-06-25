"""
harness-cook MultiAuditStore —— 多后端双写审计存储

实现 IAuditStore Protocol，将审计记录同时写入多个存储后端：
  - 主存储（primary）: 写入必须成功，失败则抛异常
  - 次存储（secondary）: 火忘式写入（fire-and-forget），失败不阻塞，但发 AUDIT_SECONDARY_FAIL 事件

设计原则：
  - save → 全部写入；主存储成功是必须的
  - load / search / verify_chain / integrity_report → 仅从主存储
  - 次存储失败 → warning 日志 + AUDIT_SECONDARY_FAIL 事件（可观测但不阻塞）

用法：
    from harness.audit import AuditStore
    from harness.integrations.multi_store import MultiAuditStore
    from harness.integrations.langfuse_store import LangfuseAuditStore

    primary = AuditStore()       # 本地 JSON（必须成功）
    secondary = LangfuseAuditStore()  # Langfuse（火忘式）

    store = MultiAuditStore([primary, secondary])
    engine = AuditEngine(store=store)
"""

import logging
from typing import Optional, Dict, List

from harness.types import AuditEntry, BusEventType, BusEvent
from harness.bus import EventBus, get_bus
from harness.integrations.audit_store_protocol import IAuditStore


logger = logging.getLogger("harness.multi_store")


class MultiAuditStore:
    """
    多后端双写审计存储

    __init__(stores) → primary=stores[0], secondary=stores[1:]
    save(entry) → primary 写入（必须成功） + secondary 写入（火忘式）
    load/search/verify_chain/integrity_report → 仅从 primary
    """

    def __init__(
        self,
        stores: List[IAuditStore],
        bus: Optional[EventBus] = None,
    ):
        """
        Args:
            stores: 存储后端列表，至少1个。stores[0] 是主存储。
            bus: 事件总线，用于发送 AUDIT_SECONDARY_FAIL 事件。
                 默认使用全局 get_bus()。
        """
        if not stores:
            raise ValueError("MultiAuditStore requires at least one store (primary)")

        self._primary = stores[0]
        self._secondary = stores[1:]
        self._bus = bus or get_bus()

    # ─── IAuditStore 接口实现 ───────────────────────────

    def save(self, entry: AuditEntry) -> str:
        """
        保存审计记录 → 主存储写入（必须成功） + 次存储写入（火忘式）

        主存储成功 → 返回主存储的标识
        主存储失败 → 抛异常（不尝试次存储）
        次存储失败 → warning + AUDIT_SECONDARY_FAIL 事件（不阻塞）
        """
        # 主存储写入——必须成功
        result = self._primary.save(entry)

        # 次存储写入——火忘式
        for store in self._secondary:
            try:
                store.save(entry)
            except Exception as e:
                store_name = type(store).__name__
                logger.warning(
                    f"Secondary store {store_name} save failed (non-blocking): {e}"
                )
                # 发 AUDIT_SECONDARY_FAIL 事件
                self._bus.emit(BusEvent(
                    type=BusEventType.AUDIT_SECONDARY_FAIL,
                    execution_id=entry.session_id,
                    agent_id=entry.agent_id,
                    data={
                        "store_name": store_name,
                        "error": str(e),
                        "entry_session_id": entry.session_id,
                    },
                ))

        return result

    def load(
        self,
        session_id: str,
        date_str: Optional[str] = None,
    ) -> List[AuditEntry]:
        """从主存储加载审计记录"""
        return self._primary.load(session_id, date_str)

    def search(
        self,
        query: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[AuditEntry]:
        """从主存储搜索审计记录"""
        return self._primary.search(query, date_from, date_to, agent_id, limit)

    def verify_chain(self) -> Dict:
        """验证主存储的哈希链完整性"""
        return self._primary.verify_chain()

    def integrity_report(self) -> Dict:
        """主存储的链状态报告"""
        return self._primary.integrity_report()

    # ─── 辅助属性 ────────────────────────────────────────

    @property
    def primary(self) -> IAuditStore:
        """主存储后端"""
        return self._primary

    @property
    def secondary_stores(self) -> List[IAuditStore]:
        """次存储后端列表"""
        return self._secondary

    @property
    def chain_head(self) -> Optional[str]:
        """主存储的链头 hash"""
        return getattr(self._primary, "chain_head", None)

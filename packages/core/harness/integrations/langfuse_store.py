"""
harness-cook LangfuseAuditStore —— Langfuse 审计存储后端

实现 IAuditStore Protocol，将 AuditEntry 写入 Langfuse trace/spans：
  - 每个 AuditEntry → 一个 Langfuse trace（session_id 作为 trace ID）
  - 每个 decision/action/outcome → trace 内的 span
  - risk_assessment → trace 的 metadata 标注
  - chain_hash → trace 的 tags（用于关联哈希链）

限制：
  - search() → 返回空列表 + warning（Langfuse SDK 无搜索 API）
  - verify_chain() → 返回 {valid: True}（Langfuse 不维护哈希链）
  - integrity_report() → 简化报告
  - load() → 返回空列表（Langfuse SDK 无按 session 加载 API）

依赖：
  - pip install harness-cook[langfuse] → 安装 langfuse>=2.0
  - SDK import 在方法级别（模块级 import 会破坏默认安装）

用法：
    from harness.integrations.langfuse_store import LangfuseAuditStore

    store = LangfuseAuditStore(
        public_key="pk-xxx",
        secret_key="sk-xxx",
        host="https://cloud.langfuse.com",  # 或自托管地址
    )

    # 通常作为 MultiAuditStore 的次存储
    from harness.integrations.multi_store import MultiAuditStore
    multi = MultiAuditStore([AuditStore(), store])
"""

import logging
from typing import Optional, Dict, List

from harness.types import AuditEntry
from harness.integrations.audit_store_protocol import IAuditStore


logger = logging.getLogger("harness.langfuse_store")


class LangfuseAuditStore:
    """
    Langfuse 审计存储后端

    实现 IAuditStore Protocol：
      save → AuditEntry → Langfuse trace/spans
      load → 空列表（Langfuse 无按 session 加载 API）
      search → 空列表 + warning（Langfuse 无搜索 API）
      verify_chain → {valid: True}（Langfuse 不维护哈希链）
      integrity_report → 简化报告
    """

    def __init__(
        self,
        public_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        host: Optional[str] = None,
        config: Optional[Dict] = None,
    ):
        """
        Args:
            public_key: Langfuse 公钥（可从环境变量 LANGFUSE_PUBLIC_KEY 读取）
            secret_key: Langfuse 密钥（可从环境变量 LANGFUSE_SECRET_KEY 读取）
            host: Langfuse 服务地址（默认 https://cloud.langfuse.com）
            config: 额外配置（透传给 Langfuse SDK）
        """
        self._public_key = public_key
        self._secret_key = secret_key
        self._host = host or "https://cloud.langfuse.com"
        self._config = config or {}
        self._client = None  # 惰性初始化
        self._availability_cache: Optional[bool] = None

    # ─── 惰性探测 ────────────────────────────────────────

    def _is_available(self) -> bool:
        """探测 Langfuse SDK 是否可用（缓存式）"""
        if self._availability_cache is not None:
            return self._availability_cache

        try:
            import langfuse
            self._availability_cache = True
            return True
        except ImportError:
            logger.debug("langfuse SDK not installed — LangfuseAuditStore unavailable")
            self._availability_cache = False
            return False

    def _get_client(self):
        """惰性获取 Langfuse 客户端"""
        if self._client is not None:
            return self._client

        if not self._is_available():
            raise RuntimeError("langfuse SDK not installed")

        from langfuse import Langfuse

        # 优先使用显式传入的 key，其次从环境变量
        self._client = Langfuse(
            public_key=self._public_key,
            secret_key=self._secret_key,
            host=self._host,
            **self._config,
        )
        return self._client

    # ─── IAuditStore 接口实现 ───────────────────────────

    def save(self, entry: AuditEntry) -> str:
        """
        保存审计记录 → Langfuse trace + spans

        每个 AuditEntry 变一个 trace，每个 decision/action/outcome 变一个 span。

        Returns:
            Langfuse trace ID
        """
        if not self._is_available():
            raise RuntimeError("langfuse SDK not installed — cannot save audit entry")

        client = self._get_client()

        # 创建 trace（session_id 作为 trace ID）
        trace = client.trace(
            id=entry.session_id,
            name=f"harness.audit.{entry.agent_id}",
            input={"task": entry.task},
            metadata={
                "agent_id": entry.agent_id,
                "timestamp": entry.timestamp.isoformat(),
                "chain_hash": entry.chain_hash or "",
                "risk_assessment": entry.risk_assessment,
                "escalation_history": entry.escalation_history,
            },
            tags=["harness-audit", entry.agent_id],
        )

        # 创建 spans —— decisions
        for i, decision in enumerate(entry.decisions):
            trace.span(
                name=f"decision-{i}",
                input=decision if isinstance(decision, dict) else {"reasoning": decision},
                output=None,
                metadata={"type": "decision"},
            )

        # 创建 spans —— actions
        for i, action in enumerate(entry.actions):
            trace.span(
                name=f"action-{i}",
                input=action if isinstance(action, dict) else {"action": action},
                output=None,
                metadata={"type": "action"},
            )

        # 创建 spans —— outcomes
        for i, outcome in enumerate(entry.outcomes):
            trace.span(
                name=f"outcome-{i}",
                input=outcome if isinstance(outcome, dict) else {"outcome": outcome},
                output=None,
                metadata={"type": "outcome"},
            )

        # Flush 确保 trace 已发送
        client.flush()

        return entry.session_id

    def load(
        self,
        session_id: str,
        date_str: Optional[str] = None,
    ) -> List[AuditEntry]:
        """
        按 session 加载 → 空列表（Langfuse SDK 无按 session 加载 API）

        Langfuse 的数据检索需要通过其 Web UI 或 API，不在 SDK 范围。
        读取审计数据应使用主存储（AuditStore）。
        """
        logger.debug("LangfuseAuditStore.load() → returns empty list (SDK has no load API)")
        return []

    def search(
        self,
        query: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[AuditEntry]:
        """
        搜索审计记录 → 空列表 + warning

        Langfuse SDK 无搜索 API，搜索应使用主存储。
        """
        logger.warning("LangfuseAuditStore.search() → returns empty list (SDK has no search API)")
        return []

    def verify_chain(self) -> Dict:
        """
        验证哈希链 → {valid: True}

        Langfuse 不维护哈希链，链验证应使用主存储。
        """
        return {
            "valid": True,
            "total_records": 0,
            "verified_records": 0,
            "legacy_records": 0,
            "tampered": [],
            "broken_links": [],
            "note": "Langfuse does not maintain hash chains — use primary store for verification",
        }

    def integrity_report(self) -> Dict:
        """链状态报告 → 简化版"""
        return {
            "status": "valid",
            "chain_head": None,
            "total_records": 0,
            "verified_records": 0,
            "legacy_records": 0,
            "tampered_count": 0,
            "broken_links_count": 0,
            "recommendation": "Langfuse does not maintain hash chains. Use primary AuditStore for integrity verification.",
        }

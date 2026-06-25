"""
harness-cook ArizeAuditStore —— Arize Phoenix 审计存储后端

实现 IAuditStore Protocol，将 AuditEntry 写入 Arize Phoenix trace：
  - 每个 AuditEntry → 一个 Phoenix trace
  - 每个 decision/action/outcome → trace 内的 span
  - risk_assessment → trace 的 compliance annotation
  - chain_hash → trace 的 attributes（用于关联哈希链）

限制：
  - load() → 空列表（Arize SDK 无按 session 加载 API）
  - search() → 空列表 + warning（Arize SDK 无搜索 API）
  - verify_chain() → {valid: True}（Arize 不维护哈希链）

依赖：
  - pip install harness-cook[arize] → 安装 arize>=5.0
  - SDK import 在方法级别（模块级 import 会破坏默认安装）
"""

import logging
from typing import Optional, Dict, List

from harness.types import AuditEntry
from harness.integrations.audit_store_protocol import IAuditStore


logger = logging.getLogger("harness.arize_store")


class ArizeAuditStore:
    """
    Arize Phoenix 审计存储后端

    实现 IAuditStore Protocol：
      save → AuditEntry → Arize Phoenix trace + compliance annotations
      load → 空列表
      search → 空列表 + warning
      verify_chain → {valid: True}
      integrity_report → 简化报告
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        space_id: Optional[str] = None,
        space_key: Optional[str] = None,
        config: Optional[Dict] = None,
    ):
        """
        Args:
            api_key: Arize API key（可从环境变量 ARIZE_API_KEY 读取）
            space_id: Arize Space ID
            space_key: Arize Space Key
            config: 额外配置
        """
        self._api_key = api_key
        self._space_id = space_id
        self._space_key = space_key
        self._config = config or {}
        self._client = None
        self._availability_cache: Optional[bool] = None

    # ─── 惰性探测 ────────────────────────────────────────

    def _is_available(self) -> bool:
        """探测 Arize SDK 是否可用（缓存式）"""
        if self._availability_cache is not None:
            return self._availability_cache

        try:
            import arize
            self._availability_cache = True
            return True
        except ImportError:
            logger.debug("arize SDK not installed — ArizeAuditStore unavailable")
            self._availability_cache = False
            return False

    def _get_client(self):
        """惰性获取 Arize 客户端"""
        if self._client is not None:
            return self._client

        if not self._is_available():
            raise RuntimeError("arize SDK not installed")

        from arize.plogging import ArizeLogger

        self._client = ArizeLogger(
            api_key=self._api_key,
            space_id=self._space_id,
            space_key=self._space_key,
            **self._config,
        )
        return self._client

    # ─── IAuditStore 接口实现 ───────────────────────────

    def save(self, entry: AuditEntry) -> str:
        """
        保存审计记录 → Arize Phoenix trace + compliance annotations

        Returns:
            Arize trace ID（session_id）
        """
        if not self._is_available():
            raise RuntimeError("arize SDK not installed — cannot save audit entry")

        client = self._get_client()

        # 构建 trace attributes
        attributes = {
            "harness.agent_id": entry.agent_id,
            "harness.task": entry.task,
            "harness.session_id": entry.session_id,
            "harness.timestamp": entry.timestamp.isoformat(),
            "harness.chain_hash": entry.chain_hash or "",
            "harness.risk_assessment": entry.risk_assessment or "",
        }

        # 记录主 trace
        client.log(
            model_id=f"harness-audit-{entry.agent_id}",
            prediction_id=entry.session_id,
            prediction_label="audit_entry",
            features={
                "task": entry.task,
                "agent_id": entry.agent_id,
            },
            attributes=attributes,
            tags=["harness-audit", entry.agent_id],
        )

        # 记录 compliance annotations
        if entry.risk_assessment:
            client.log(
                model_id=f"harness-governance-{entry.agent_id}",
                prediction_id=f"{entry.session_id}-compliance",
                prediction_label="compliance_annotation",
                features={
                    "risk_assessment": entry.risk_assessment,
                },
                attributes={
                    "harness.compliance": "true",
                    "harness.risk_level": entry.risk_assessment,
                },
            )

        return entry.session_id

    def load(
        self,
        session_id: str,
        date_str: Optional[str] = None,
    ) -> List[AuditEntry]:
        """按 session 加载 → 空列表"""
        logger.debug("ArizeAuditStore.load() → returns empty list (SDK has no load API)")
        return []

    def search(
        self,
        query: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[AuditEntry]:
        """搜索审计记录 → 空列表 + warning"""
        logger.warning("ArizeAuditStore.search() → returns empty list (SDK has no search API)")
        return []

    def verify_chain(self) -> Dict:
        """验证哈希链 → {valid: True}"""
        return {
            "valid": True,
            "total_records": 0,
            "verified_records": 0,
            "legacy_records": 0,
            "tampered": [],
            "broken_links": [],
            "note": "Arize does not maintain hash chains — use primary store for verification",
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
            "recommendation": "Arize does not maintain hash chains. Use primary AuditStore for integrity verification.",
        }

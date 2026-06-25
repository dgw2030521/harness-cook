"""
HeliconeAuditStore — Helicone 审计存储后端

实现 IAuditStore Protocol，将 AuditEntry 写入 Helicone 日志系统：
  - 每个 AuditEntry → Helicone log 请求（通过 HTTP API）
  - session_id → Helicone request ID
  - decisions/actions/outcomes → Helicone properties/metadata
  - chain_hash → Helicone custom property（用于关联哈希链）

双重定位：
  Helicone 在 harness-cook 中有两个角色：
  1. 护栏引擎（HeliconeMiddlewareChecker）—— matcher_type="helicone"
  2. 审计后端（HeliconeAuditStore）—— audit.backends=["local", "helicone"]

限制：
  - search() → 返回空列表 + warning（Helicone API 搜索能力有限）
  - verify_chain() → 返回 {valid: True}（Helicone 不维护哈希链）
  - integrity_report() → 简化报告

依赖：
  - pip install harness-cook[helicone] → 安装 helicone SDK
  - SDK import 在方法级别（模块级 import 会破坏默认安装）

用法：
    from harness.integrations.helicone_store import HeliconeAuditStore

    store = HeliconeAuditStore(
        api_key="hk-xxx",
        base_url="https://api.helicone.ai",  # 或自定义部署
    )

    # 通常作为 MultiAuditStore 的次存储
    from harness.integrations.multi_store import MultiAuditStore
    multi = MultiAuditStore([AuditStore(), store])
"""

import json
import logging
from typing import Optional, Dict, List

from harness.types import AuditEntry
from harness.integrations.audit_store_protocol import IAuditStore

logger = logging.getLogger("harness.helicone_store")


class HeliconeAuditStore:
    """Helicone 审计存储后端

    实现 IAuditStore Protocol：
      save → AuditEntry → Helicone log request (HTTP API)
      load → 空列表（Helicone 无按 session 加载 API）
      search → 空列表 + warning（Helicone API 搜索能力有限）
      verify_chain → {valid: True}（Helicone 不维护哈希链）
      integrity_report → 简化报告
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        config: Optional[Dict] = None,
    ):
        """
        Args:
            api_key: Helicone API key（可从环境变量 HELICONE_API_KEY 读取）
            base_url: Helicone API 基础 URL（默认 https://api.helicone.ai）
            config: 额外配置（自定义 headers、超时等）
        """
        self._api_key = api_key
        self._base_url = base_url or "https://api.helicone.ai"
        self._config = config or {}
        self._client = None  # 惰性初始化
        self._availability_cache: Optional[bool] = None

    # ─── 惰性探测 ────────────────────────────────────────

    def _is_available(self) -> bool:
        """探测 Helicone SDK 是否可用（缓存式）"""
        if self._availability_cache is not None:
            return self._availability_cache

        try:
            import helicone
            self._availability_cache = True
            return True
        except ImportError:
            logger.debug("helicone SDK not installed — HeliconeAuditStore unavailable")
            self._availability_cache = False
            return False

    def _get_client(self):
        """惰性获取 Helicone 客户端

        优先使用 helicone SDK，回退到 HTTP API 直接调用。
        """
        if self._client is not None:
            return self._client

        if self._is_available():
            import helicone
            self._client = helicone.Helicone(api_key=self._api_key)
            return self._client

        # SDK 不可用时使用 HTTP 直连
        import urllib.request
        self._client = {"type": "http", "base_url": self._base_url}
        return self._client

    def _get_api_key(self) -> Optional[str]:
        """获取 API key——优先显式传入，其次环境变量"""
        if self._api_key:
            return self._api_key
        import os
        return os.environ.get("HELICONE_API_KEY")

    # ─── IAuditStore 接口实现 ───────────────────────────

    def save(self, entry: AuditEntry) -> str:
        """
        保存审计记录 → Helicone log request

        每个 AuditEntry 翻译为 Helicone 的 log 写入请求：
          - session_id → request ID
          - task → prompt
          - decisions/actions/outcomes → custom properties
          - chain_hash/risk_assessment → metadata tags

        Returns:
            Helicone log ID（用 session_id 作为标识）
        """
        client = self._get_client()
        api_key = self._get_api_key()

        # 构建审计日志数据
        log_data = {
            "request": {
                "prompt": entry.task,
                "model": "harness-governance",
            },
            "response": {
                "output": json.dumps({
                    "decisions": entry.decisions,
                    "actions": entry.actions,
                    "outcomes": entry.outcomes,
                }),
                "status": "success",
            },
            "custom_properties": {
                "harness_agent_id": entry.agent_id,
                "harness_session_id": entry.session_id,
                "harness_chain_hash": entry.chain_hash or "",
                "harness_risk_assessment": entry.risk_assessment or "",
                "harness_timestamp": entry.timestamp.isoformat(),
                "harness_escalation_count": str(len(entry.escalation_history or [])),
            },
            "tags": ["harness-audit", entry.agent_id],
        }

        # 通过 SDK 或 HTTP API 写入
        if isinstance(client, dict) and client["type"] == "http":
            # HTTP 直连写入
            import urllib.request

            url = f"{self._base_url}/v1/log"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "Helicone-Auth": api_key or "",
            }

            req = urllib.request.Request(
                url,
                data=json.dumps(log_data).encode("utf-8"),
                headers=headers,
                method="POST",
            )

            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    resp.read()  # 确认响应已接收
            except Exception as e:
                logger.warning(f"Helicone HTTP log write failed: {e}")
                # 不阻塞主流程——审计后端写入失败可容忍
                pass

        else:
            # SDK 写入
            try:
                client.log(
                    prompt=entry.task,
                    output=json.dumps({
                        "decisions": entry.decisions,
                        "actions": entry.actions,
                        "outcomes": entry.outcomes,
                    }),
                    model="harness-governance",
                    custom_properties=log_data["custom_properties"],
                    tags=log_data["tags"],
                )
            except Exception as e:
                logger.warning(f"Helicone SDK log write failed: {e}")
                pass

        return entry.session_id

    def load(
        self,
        session_id: str,
        date_str: Optional[str] = None,
    ) -> List[AuditEntry]:
        """
        按 session 加载 → 空列表

        Helicone 的数据检索需要通过其 Dashboard UI 或 API，
        不在 SDK 范围。读取审计数据应使用主存储。
        """
        logger.debug("HeliconeAuditStore.load() → returns empty list (SDK has no load API)")
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

        Helicone API 搜索能力有限，搜索应使用主存储。
        """
        logger.warning("HeliconeAuditStore.search() → returns empty list (limited search API)")
        return []

    def verify_chain(self) -> Dict:
        """
        验证哈希链 → {valid: True}

        Helicone 不维护哈希链，链验证应使用主存储。
        """
        return {
            "valid": True,
            "total_records": 0,
            "verified_records": 0,
            "legacy_records": 0,
            "tampered": [],
            "broken_links": [],
            "note": "Helicone does not maintain hash chains — use primary store for verification",
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
            "recommendation": "Helicone does not maintain hash chains. Use primary AuditStore for integrity verification.",
        }

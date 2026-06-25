"""
harness-cook DatadogAuditStore —— Datadog APM 审计存储后端

实现 IAuditStore Protocol，将 AuditEntry 写入 Datadog APM span：
  - 每个 AuditEntry → 一个 Datadog span（harness.audit 类型）
  - 每个 decision/action/outcome → span 的 attributes
  - chain_hash → span tag
  - risk_assessment → span metric

独特价值：基础设施 + Agent 动作的全栈 trace（Datadog APM 的核心优势）

限制：
  - load() → 空列表（Datadog SDK 无按 session 加载 API）
  - search() → 空列表 + warning
  - verify_chain() → {valid: True}

依赖：
  - pip install harness-cook[datadog] → 安装 ddtrace>=2.0
  - SDK import 在方法级别
"""

import logging
from typing import Optional, Dict, List

from harness.types import AuditEntry
from harness.integrations.audit_store_protocol import IAuditStore


logger = logging.getLogger("harness.datadog_store")


class DatadogAuditStore:
    """
    Datadog APM 审计存储后端

    独特价值：基础设施 + Agent 动作的全栈 trace

    实现 IAuditStore Protocol：
      save → AuditEntry → Datadog APM span
      load → 空列表
      search → 空列表 + warning
      verify_chain → {valid: True}
      integrity_report → 简化报告
    """

    def __init__(
        self,
        service_name: str = "harness-cook",
        env: Optional[str] = None,
        config: Optional[Dict] = None,
    ):
        """
        Args:
            service_name: Datadog 服务名称
            env: Datadog 环境（可从 DD_ENV 环境变量读取）
            config: 额外配置
        """
        self._service_name = service_name
        self._env = env
        self._config = config or {}
        self._tracer = None
        self._availability_cache: Optional[bool] = None

    # ─── 惰性探测 ────────────────────────────────────────

    def _is_available(self) -> bool:
        """探测 ddtrace SDK 是否可用（缓存式）"""
        if self._availability_cache is not None:
            return self._availability_cache

        try:
            import ddtrace
            self._availability_cache = True
            return True
        except ImportError:
            logger.debug("ddtrace SDK not installed — DatadogAuditStore unavailable")
            self._availability_cache = False
            return False

    def _get_tracer(self):
        """惰性获取 Datadog tracer"""
        if self._tracer is not None:
            return self._tracer

        if not self._is_available():
            raise RuntimeError("ddtrace SDK not installed")

        from ddtrace import tracer

        # 配置 tracer
        if self._service_name:
            tracer.set_service_info(
                service=self._service_name,
                env=self._env or "",
                version="harness-cook-v2",
            )

        self._tracer = tracer
        return self._tracer

    # ─── IAuditStore 接口实现 ───────────────────────────

    def save(self, entry: AuditEntry) -> str:
        """
        保存审计记录 → Datadog APM span

        Returns:
            span_id（字符串形式）
        """
        if not self._is_available():
            raise RuntimeError("ddtrace SDK not installed — cannot save audit entry")

        tracer = self._get_tracer()

        # 创建 span
        span = tracer.trace(
            name=f"harness.audit.{entry.agent_id}",
            service=self._service_name,
            resource=entry.task,
        )

        # 设置 span tags
        span.set_tag("harness.session_id", entry.session_id)
        span.set_tag("harness.agent_id", entry.agent_id)
        span.set_tag("harness.chain_hash", entry.chain_hash or "")
        span.set_tag("harness.risk_assessment", entry.risk_assessment or "")
        span.set_tag("harness.audit_type", "governance_trace")

        # 设置 span metrics
        span.set_metric("harness.decisions_count", len(entry.decisions))
        span.set_metric("harness.actions_count", len(entry.actions))
        span.set_metric("harness.outcomes_count", len(entry.outcomes))

        # 为每个 decision 创建子 span
        for i, decision in enumerate(entry.decisions):
            child = tracer.trace(
                name=f"harness.decision.{i}",
                service=self._service_name,
            )
            if isinstance(decision, dict):
                for key, value in decision.items():
                    child.set_tag(f"harness.decision.{key}", str(value))
            else:
                child.set_tag("harness.decision.content", str(decision))
            child.finish()

        # 为每个 action 创建子 span
        for i, action in enumerate(entry.actions):
            child = tracer.trace(
                name=f"harness.action.{i}",
                service=self._service_name,
            )
            if isinstance(action, dict):
                for key, value in action.items():
                    child.set_tag(f"harness.action.{key}", str(value))
            else:
                child.set_tag("harness.action.content", str(action))
            child.finish()

        # 为每个 outcome 创建子 span
        for i, outcome in enumerate(entry.outcomes):
            child = tracer.trace(
                name=f"harness.outcome.{i}",
                service=self._service_name,
            )
            if isinstance(outcome, dict):
                for key, value in outcome.items():
                    child.set_tag(f"harness.outcome.{key}", str(value))
            else:
                child.set_tag("harness.outcome.content", str(outcome))
            child.finish()

        # 完成主 span
        span.finish()

        return str(span.span_id)

    def load(
        self,
        session_id: str,
        date_str: Optional[str] = None,
    ) -> List[AuditEntry]:
        """按 session 加载 → 空列表"""
        logger.debug("DatadogAuditStore.load() → returns empty list (SDK has no load API)")
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
        logger.warning("DatadogAuditStore.search() → returns empty list (SDK has no search API)")
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
            "note": "Datadog does not maintain hash chains — use primary store for verification",
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
            "recommendation": "Datadog does not maintain hash chains. Use primary AuditStore for integrity verification.",
        }

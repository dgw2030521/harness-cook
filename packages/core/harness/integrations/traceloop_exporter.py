"""
harness-cook TraceloopExporter —— OTel 审计导出的 Traceloop 包装

OTelBridge.export_audit_entry() 的薄包装，添加 Traceloop 特定属性命名。

Traceloop 使用 OpenTelemetry 作为底层 trace 协议，但有自己的属性命名约定：
  - traceloop.workflow.name → harness task
  - traceloop.agent.name → harness agent_id

TraceloopExporter 将 harness 标准属性映射到 Traceloop 属性命名，
使得审计 trace 可以在 Traceloop Dashboard 中正确展示。

依赖：
  - pip install harness-cook[integrations] → 安装 traceloop SDK（可选）
  - SDK import 在方法级别

用法：
    from harness.integrations.traceloop_exporter import TraceloopExporter
    from harness.otel_integration import OTelBridge

    exporter = TraceloopExporter(OTelBridge())
    span_dict = exporter.export_audit_entry(entry)
"""

import logging
from typing import Optional, Dict, Any

from harness.integrations.audit_store_protocol import IAuditStore


logger = logging.getLogger("harness.traceloop_exporter")


# ─── Traceloop 属性命名映射 ────────────────────────────────

TRACELOOP_ATTR_MAP = {
    "harness.task": "traceloop.workflow.name",
    "harness.agent_id": "traceloop.agent.name",
    "harness.session_id": "traceloop.session.id",
    "harness.chain_hash": "traceloop.chain.hash",
    "harness.risk_assessment": "traceloop.risk.level",
    "harness.timestamp": "traceloop.event.timestamp",
}


class TraceloopExporter:
    """
    Traceloop 属性命名导出器

    OTelBridge.export_audit_entry() 的薄包装，添加 Traceloop 特定属性。
    不创建新的 Span，只映射属性命名。

    可选：如果 Traceloop SDK 可用，会同时通过 SDK 发送 trace。
    """

    def __init__(self, otel_bridge: Any = None):
        """
        Args:
            otel_bridge: OTelBridge 实例（用于调用 export_audit_entry）
        """
        self._otel_bridge = otel_bridge
        self._traceloop_available: Optional[bool] = None

    def _is_traceloop_available(self) -> bool:
        """探测 Traceloop SDK 是否可用"""
        if self._traceloop_available is not None:
            return self._traceloop_available

        try:
            import traceloop
            self._traceloop_available = True
            return True
        except ImportError:
            logger.debug("traceloop SDK not installed — using OTel export only")
            self._traceloop_available = False
            return False

    def export_audit_entry(self, entry: Any) -> Dict:
        """
        导出 AuditEntry → Traceloop 属性格式的 OTel Span

        步骤：
          1. 调用 OTelBridge.export_audit_entry() → 获取 harness 格式 Span
          2. 将 harness 属性映射到 Traceloop 属性命名
          3. 合并两种属性命名（兼容 OTel Collector + Traceloop Dashboard）

        Returns:
            合并属性后的 Span 字典
        """
        # Step 1: 获取 harness 格式 Span
        if self._otel_bridge:
            span_dict = self._otel_bridge.export_audit_entry(entry)
        else:
            # 无 OTelBridge → 使用 _audit_entry_to_span_dict
            from harness.otel_integration import _audit_entry_to_span_dict
            span_dict = _audit_entry_to_span_dict(entry)

        # Step 2: 映射 Traceloop 属性命名
        attributes = span_dict.get("attributes", {})
        traceloop_attrs = {}
        for harness_attr, traceloop_attr in TRACELOOP_ATTR_MAP.items():
            if harness_attr in attributes:
                traceloop_attrs[traceloop_attr] = attributes[harness_attr]

        # Step 3: 合并属性
        span_dict["attributes"] = {**attributes, **traceloop_attrs}
        span_dict["traceloop_compatible"] = True

        return span_dict

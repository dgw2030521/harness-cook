"""
OpenTelemetry 集成模块

为 harness-cook 提供可观测性支持：
- Trace：工作流执行的分布式追踪
- Metrics：执行时间、成功率、token 消耗等指标

使用方式：

1. 安装 OpenTelemetry：
   ```bash
   pip install opentelemetry-api opentelemetry-sdk
   ```

2. 配置 TracerProvider：
   ```python
   from opentelemetry import trace
   from opentelemetry.sdk.trace import TracerProvider
   from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

   trace.set_tracer_provider(TracerProvider())
   trace.get_tracer_provider().add_span_processor(
       SimpleSpanProcessor(ConsoleSpanExporter())
   )
   ```

3. 在 DAGEngine 中启用：
   ```python
   from harness.engine import DAGEngine
   from harness.otel_integration import OTelBridge

   otel = OTelBridge()
   engine = DAGEngine()
   otel.attach_to_engine(engine)
   ```

4. 执行工作流时自动创建 Span：
   ```python
   result = engine.execute(workflow)
   # Span 自动创建和结束
   ```

## 指标说明

| 指标名称 | 类型 | 说明 |
|---------|------|------|
| harness.workflow.duration | Histogram | 工作流执行时间（毫秒） |
| harness.workflow.node.duration | Histogram | 节点执行时间（毫秒） |
| harness.workflow.node.count | Counter | 节点执行次数 |
| harness.workflow.node.error | Counter | 节点错误次数 |
| harness.gate.check.count | Counter | 门禁检查次数 |
| harness.gate.check.passed | Counter | 门禁通过次数 |
| harness.gate.check.failed | Counter | 门禁失败次数 |
| harness.agent.tokens.used | Counter | Agent 消耗的 token 数 |
"""

import logging
import time
from typing import Optional, Any

logger = logging.getLogger("harness.otel")

# ─── 可选依赖检查 ────────────────────────────────────────

try:
    from opentelemetry import trace
    from opentelemetry import metrics
    from opentelemetry.trace import Status, StatusCode
    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False
    logger.debug("OpenTelemetry not installed — tracing disabled")


class OTelBridge:
    """
    OpenTelemetry 桥接器——将 harness 执行信息桥接到 OTel

    用法：
        otel = OTelBridge()
        otel.attach_to_engine(engine)
    """

    def __init__(
        self,
        service_name: str = "harness-cook",
        tracer_name: str = "harness.engine",
    ):
        self._service_name = service_name
        self._tracer_name = tracer_name
        self._tracer = None
        self._meter = None

        if HAS_OTEL:
            self._tracer = trace.get_tracer(tracer_name)
            self._meter = metrics.get_meter(tracer_name)
            self._setup_metrics()

    def _setup_metrics(self) -> None:
        """初始化 OTel 指标"""
        if not self._meter:
            return

        self._workflow_duration = self._meter.create_histogram(
            name="harness.workflow.duration",
            description="Workflow execution duration in milliseconds",
            unit="ms",
        )
        self._node_duration = self._meter.create_histogram(
            name="harness.workflow.node.duration",
            description="Node execution duration in milliseconds",
            unit="ms",
        )
        self._node_count = self._meter.create_counter(
            name="harness.workflow.node.count",
            description="Number of node executions",
            unit="1",
        )
        self._node_error = self._meter.create_counter(
            name="harness.workflow.node.error",
            description="Number of node errors",
            unit="1",
        )
        self._tokens_used = self._meter.create_counter(
            name="harness.agent.tokens.used",
            description="Tokens consumed by agents",
            unit="1",
        )

    def attach_to_engine(self, engine: Any) -> None:
        """
        将 OTel 桥接到 DAGEngine

        通过 EventBus 监听事件，自动创建 Span 和记录指标。

        Args:
            engine: DAGEngine 实例
        """
        if not HAS_OTEL:
            logger.warning("OpenTelemetry not available — skipping attachment")
            return

        from harness.bus import BusEventType

        # 监听工作流事件
        engine._bus.subscribe(
            BusEventType.WORKFLOW_START,
            self._on_workflow_start,
            name="otel-workflow-start",
        )
        engine._bus.subscribe(
            BusEventType.WORKFLOW_COMPLETE,
            self._on_workflow_complete,
            name="otel-workflow-complete",
        )

        # 监听节点事件
        engine._bus.subscribe(
            BusEventType.NODE_START,
            self._on_node_start,
            name="otel-node-start",
        )
        engine._bus.subscribe(
            BusEventType.NODE_COMPLETE,
            self._on_node_complete,
            name="otel-node-complete",
        )
        engine._bus.subscribe(
            BusEventType.NODE_FAIL,
            self._on_node_fail,
            name="otel-node-fail",
        )

        logger.info(f"OpenTelemetry bridge attached to engine (service={self._service_name})")

    def _on_workflow_start(self, event: Any) -> None:
        """工作流开始事件处理"""
        if not self._tracer:
            return

        data = event.data or {}
        workflow_id = data.get("workflow_id", "unknown")
        execution_id = event.execution_id

        # 创建 Span
        span = self._tracer.start_span(
            name=f"workflow.{workflow_id}",
            attributes={
                "harness.execution_id": execution_id,
                "harness.workflow_id": workflow_id,
                "harness.node_count": data.get("node_count", 0),
            },
        )
        # 将 Span 存储到 event 中，以便后续使用
        event.data["_otel_span"] = span

    def _on_workflow_complete(self, event: Any) -> None:
        """工作流完成事件处理"""
        if not self._tracer:
            return

        data = event.data or {}
        span = data.pop("_otel_span", None)
        if not span:
            return

        duration_ms = data.get("duration_ms", 0)
        completed = data.get("completed_nodes", 0)
        failed = data.get("failed_nodes", 0)
        escalated = data.get("escalated", False)

        # 记录属性
        span.set_attribute("harness.duration_ms", duration_ms)
        span.set_attribute("harness.completed_nodes", completed)
        span.set_attribute("harness.failed_nodes", failed)

        # 设置状态
        if escalated or failed > 0:
            span.set_status(Status(StatusCode.ERROR, f"Failed: {failed} nodes failed"))
        else:
            span.set_status(Status(StatusCode.OK))

        span.end()

        # 记录指标
        if self._workflow_duration:
            self._workflow_duration.record(duration_ms)

    def _on_node_start(self, event: Any) -> None:
        """节点开始事件处理"""
        if not self._tracer:
            return

        data = event.data or {}
        node_id = event.node_id or "unknown"
        agent_type = data.get("agent_type", "unknown")

        span = self._tracer.start_span(
            name=f"node.{node_id}",
            attributes={
                "harness.execution_id": event.execution_id,
                "harness.node_id": node_id,
                "harness.agent_type": agent_type,
            },
        )
        event.data["_otel_span"] = span

    def _on_node_complete(self, event: Any) -> None:
        """节点完成事件处理"""
        if not self._tracer:
            return

        data = event.data or {}
        span = data.pop("_otel_span", None)
        if not span:
            return

        agent_id = data.get("agent_id", "unknown")
        artifacts = data.get("artifacts", 0)

        span.set_attribute("harness.agent_id", agent_id)
        span.set_attribute("harness.artifacts", artifacts)
        span.set_status(Status(StatusCode.OK))
        span.end()

        # 记录指标
        if self._node_count:
            self._node_count.add(1, {"harness.node_id": event.node_id or "unknown"})

    def _on_node_fail(self, event: Any) -> None:
        """节点失败事件处理"""
        if not self._tracer:
            return

        data = event.data or {}
        span = data.pop("_otel_span", None)
        if not span:
            return

        reason = data.get("reason", "unknown")
        span.set_attribute("harness.error", reason)
        span.set_status(Status(StatusCode.ERROR, reason))
        span.end()

        # 记录指标
        if self._node_error:
            self._node_error.add(1, {"harness.node_id": event.node_id or "unknown"})

    # ─── 审计扩展方法 ─────────────────────────────────────

    def export_audit_entry(self, entry: Any) -> dict:
        """
        导出 AuditEntry → OTel Span 格式字典

        将审计记录转换为 OTel Span 格式，用于导出到
        OTel Collector 或 Traceloop。

        不重写现有 workflow/node/gate Span，只新增 audit/compliance Span。

        Args:
            entry: AuditEntry 实例

        Returns:
            OTel Span 格式字典（name, attributes, status, kind）
        """
        span_dict = _audit_entry_to_span_dict(entry)

        # 如果 tracer 可用，同时创建真实的 Span
        if self._tracer:
            span = self._tracer.start_span(
                name=span_dict["name"],
                attributes=span_dict["attributes"],
            )
            if HAS_OTEL:
                if span_dict["status"] == "OK":
                    span.set_status(Status(StatusCode.OK))
                else:
                    span.set_status(Status(StatusCode.ERROR, "audit risk detected"))
            span.end()

        return span_dict

    def attach_to_audit_engine(self, engine: Any) -> None:
        """
        将 OTel 桥接到 AuditEngine

        通过 EventBus 监听 COMPLIANCE_FAIL/COMPLIANCE_CHECK 事件，
        自动创建 OTel Span。

        不重写现有 attach_to_engine()，只新增审计事件的监听。

        Args:
            engine: AuditEngine 实例
        """
        if not self._tracer:
            logger.warning("OpenTelemetry tracer not available — skipping audit attachment")
            return

        from harness.bus import BusEventType

        # 监听合规事件 → 创建 OTel Span
        engine._bus.subscribe(
            BusEventType.COMPLIANCE_CHECK,
            self._on_compliance_check,
            name="otel-compliance-check",
        )
        engine._bus.subscribe(
            BusEventType.COMPLIANCE_FAIL,
            self._on_compliance_fail,
            name="otel-compliance-fail",
        )

        logger.info(f"OpenTelemetry bridge attached to audit engine (service={self._service_name})")

    def _on_compliance_check(self, event: Any) -> None:
        """合规检查事件 → 创建 OTel Span"""
        if not self._tracer:
            return

        data = event.data or {}
        rule_id = data.get("rule_id", "unknown")

        span = self._tracer.start_span(
            name=f"harness.compliance.{rule_id}",
            attributes={
                "harness.execution_id": event.execution_id,
                "harness.rule_id": rule_id,
                "harness.agent_id": event.agent_id or "",
            },
        )
        span.set_status(Status(StatusCode.OK))
        span.end()

    def _on_compliance_fail(self, event: Any) -> None:
        """合规失败事件 → 创建 OTel Span（ERROR 状态）"""
        if not self._tracer:
            return

        data = event.data or {}
        rule_id = data.get("rule_id", "unknown")
        severity = data.get("severity", "unknown")

        span = self._tracer.start_span(
            name=f"harness.compliance.{rule_id}",
            attributes={
                "harness.execution_id": event.execution_id,
                "harness.rule_id": rule_id,
                "harness.agent_id": event.agent_id or "",
                "harness.severity": severity,
                "harness.violation": True,
            },
        )
        span.set_status(Status(StatusCode.ERROR, f"Compliance violation: {rule_id}"))
        span.end()


# ─── 便捷函数 ────────────────────────────────────────────

_bridge_instance: Optional[OTelBridge] = None


def get_otel_bridge(service_name: str = "harness-cook") -> OTelBridge:
    """获取全局 OTel 桥接器实例"""
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = OTelBridge(service_name=service_name)
    return _bridge_instance


def attach_otel_to_engine(engine: Any, service_name: str = "harness-cook") -> None:
    """
    便捷函数：将 OTel 桥接到 DAGEngine

    用法：
        from harness.engine import DAGEngine
        from harness.otel_integration import attach_otel_to_engine

        engine = DAGEngine()
        attach_otel_to_engine(engine)
    """
    bridge = get_otel_bridge(service_name)
    bridge.attach_to_engine(engine)


# ─── 审计扩展 ────────────────────────────────────────────


def _audit_entry_to_span_dict(entry) -> dict:
    """
    AuditEntry → OTel Span 格式字典

    将审计记录转换为 OTel Span 的标准属性格式，
    用于导出到 OTel Collector 或 Traceloop。

    Span 命名：
      - 门禁审计: harness.gate.{gate_id}
      - 合规审计: harness.compliance.{rule_id}
      - 通用审计: harness.audit.{agent_id}

    Attributes 使用 harness.* 前缀。
    """
    return {
        "name": f"harness.audit.{entry.agent_id}",
        "attributes": {
            "harness.session_id": entry.session_id,
            "harness.agent_id": entry.agent_id,
            "harness.task": entry.task,
            "harness.timestamp": entry.timestamp.isoformat() if hasattr(entry.timestamp, "isoformat") else str(entry.timestamp),
            "harness.chain_hash": entry.chain_hash or "",
            "harness.risk_assessment": entry.risk_assessment or "",
            "harness.decisions_count": len(entry.decisions),
            "harness.actions_count": len(entry.actions),
            "harness.outcomes_count": len(entry.outcomes),
        },
        "status": "OK" if not entry.risk_assessment else "ERROR",
        "kind": "INTERNAL",
    }

"""
知识自动沉淀桥梁——EventBus → Knowledge 的三层治理机制

从 EventBus 事件中自动沉淀知识条目，经过三层治理：
1. 写入门控：同一规则累计 ≥ 3次才沉淀（过滤噪音）
2. 去重合并：按规则名做 title, hit_count 累计（防止膨胀）
3. 自动淘汰：由 LocalKnowledgeProvider.evict_stale_entries() 处理

订阅的 EventBus 事件：
- compliance:fail → RISK 知识（合规违规，同一规则 ≥ 3次才沉淀）
- guardrail:block → RISK 知识（护栏拦截，只存确认拦截）
- gate:fail → DECISION 知识（门禁拒绝，架构级决策）
- gate:pass → DECISION 知识（门禁通过，架构级决策）
- recommendation → PATTERN/RISK 知识（学习推荐，confidence ≥ 0.7）

用法：
    from harness.knowledge import LocalKnowledgeProvider
    from harness.knowledge_subscriber import KnowledgeSubscriber
    from harness.bus import EventBus

    bus = EventBus()
    provider = LocalKnowledgeProvider(project_name="my-project")
    provider.initialize()

    subscriber = KnowledgeSubscriber(provider, bus)
    # subscriber 自动订阅事件，合规违规/护栏拦截等会自动沉淀到知识库
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from harness.bus import EventBus, BusEvent, BusEventType
from harness.knowledge import (
    KnowledgeEntry,
    KnowledgeType,
    KnowledgeScope,
    LocalKnowledgeProvider,
)
from harness.types import Recommendation

logger = logging.getLogger("harness.knowledge_subscriber")


# ═══════════════════════════════════════════════════════════
#  写入门控——事件累计计数器
# ═══════════════════════════════════════════════════════════

class _EventAccumulator:
    """事件累计计数器——第一层写入门控的核心

    同一规则/模式的违规事件累计到 ≥ THRESHOLD 次才触发沉淀。
    低于阈值的事件视为噪音（单次异常），不写入知识库。

    累计策略：
    - 每个 rule_name 维护一个计数器
    - 每次事件触发 → count += 1
    - count ≥ THRESHOLD → 触发沉淀，并重置计数（避免无限累积）
    """

    # 门控阈值：同一规则累计触发 ≥ 3 次才沉淀
    THRESHOLD = 3

    def __init__(self):
        self._counts: Dict[str, int] = defaultdict(int)
        self._pending_events: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    def accumulate(self, rule_key: str, event_data: Dict[str, Any]) -> bool:
        """累计事件，返回是否达到沉淀阈值

        Args:
            rule_key: 规则标识（如 "no-hardcoded-secrets", "excessive-retries"）
            event_data: 事件数据摘要

        Returns:
            True → 达到阈值，可以沉淀；False → 继续累计
        """
        self._counts[rule_key] += 1
        self._pending_events[rule_key].append(event_data)

        # 只保留最近 THRESHOLD+2 条事件（避免内存膨胀）
        if len(self._pending_events[rule_key]) > self.THRESHOLD + 2:
            self._pending_events[rule_key] = self._pending_events[rule_key][-self.THRESHOLD:]

        if self._counts[rule_key] >= self.THRESHOLD:
            # 达到阈值 → 重置计数，返回 True
            self._counts[rule_key] = 0
            return True

        return False

    def get_pending_events(self, rule_key: str) -> List[Dict[str, Any]]:
        """获取累计的事件数据"""
        events = self._pending_events.get(rule_key, [])
        self._pending_events[rule_key] = []
        return events

    def stats(self) -> Dict[str, int]:
        """返回累计统计"""
        return {k: v for k, v in self._counts.items() if v > 0}


# ═══════════════════════════════════════════════════════════
#  KnowledgeSubscriber——EventBus → Knowledge 桥梁
# ═══════════════════════════════════════════════════════════

class KnowledgeSubscriber:
    """知识自动沉淀桥梁——三层治理机制

    从 EventBus 事件中自动沉淀知识条目，经过三层治理：
    1. 写入门控（_EventAccumulator）：同一规则累计 ≥ 3次才沉淀
    2. 去重合并（LocalKnowledgeProvider.put(merge=True)）：按规则名做 title
    3. 自动淘汰（LocalKnowledgeProvider.evict_stale_entries()）：30天→归档, 90天→删除

    订阅的事件 → 对应知识类型：
    - compliance:fail → RISK（合规违规）
    - guardrail:block → RISK（护栏拦截）
    - gate:fail → DECISION（门禁拒绝）
    - gate:pass → DECISION（门禁通过）
    - recommendation → PATTERN/RISK（学习推荐）

    用法：
        subscriber = KnowledgeSubscriber(provider, bus)
        # 自动订阅事件，无需额外调用

        # 触发淘汰（通常在 session_end 或定时任务中调用）
        subscriber.evict()
    """

    # ── 知识来源标记 ──
    SOURCE_COMPLIANCE = "compliance"
    SOURCE_GUARDRAIL = "guardrail"
    SOURCE_GATE = "gate"
    SOURCE_LEARNING = "learning"

    def __init__(
        self,
        provider: LocalKnowledgeProvider,
        bus: EventBus,
        auto_evict: bool = True,
        evict_interval_events: int = 50,
    ):
        """初始化 KnowledgeSubscriber

        Args:
            provider: 知识 Provider（LocalKnowledgeProvider）
            bus: EventBus（事件总线）
            auto_evict: 是否在累计一定事件后自动触发淘汰
            evict_interval_events: 每累计多少次事件后触发淘汰（默认50）
        """
        self._provider = provider
        self._bus = bus
        self._accumulator = _EventAccumulator()
        self._auto_evict = auto_evict
        self._evict_interval = evict_interval_events
        self._event_count = 0  # 累计事件数（用于定时淘汰）

        # ── 订阅 EventBus 事件 ──
        bus.subscribe(BusEventType.COMPLIANCE_FAIL, self._on_compliance_fail)
        bus.subscribe(BusEventType.GUARDRAIL_BLOCK, self._on_guardrail_block)
        bus.subscribe(BusEventType.GATE_FAIL, self._on_gate_fail)
        bus.subscribe(BusEventType.GATE_PASS, self._on_gate_pass)
        bus.subscribe(BusEventType.RECOMMENDATION, self._on_recommendation)

        logger.info("KnowledgeSubscriber 已订阅 EventBus 事件（compliance/guardrail/gate/recommendation）")

    # ── 事件处理器 ──

    def _on_compliance_fail(self, event: BusEvent) -> None:
        """合规违规事件 → RISK 知识（写入门控：同一规则 ≥ 3次）"""
        data = event.data or {}
        rule_name = data.get("rule_name") or data.get("rule_id") or "unknown-rule"
        category = data.get("category", "security")
        description = data.get("description") or data.get("findings", "")
        severity = data.get("severity", "medium")

        # ── 第一层：写入门控 ──
        event_summary = {
            "rule_name": rule_name,
            "description": description[:200],  # 截断避免过长
            "severity": severity,
            "timestamp": event.timestamp.isoformat() if event.timestamp else "",
        }

        should_persist = self._accumulator.accumulate(rule_name, event_summary)
        self._event_count += 1

        if should_persist:
            # ── 第二层：去重合并 ──
            # 用规则名做 title（同类问题归到同一条目）
            pending_events = self._accumulator.get_pending_events(rule_name)

            entry = KnowledgeEntry(
                type=KnowledgeType.RISK,
                scope=KnowledgeScope.PROJECT,
                title=f"合规风险: {rule_name}",
                content=f"规则 {rule_name} 多次触发违规（{category}类）\n\n"
                        f"最近案例:\n" + "\n".join(
                            f"  - {e.get('description', '')[:100]}" for e in pending_events[-3:]
                        ),
                source=self.SOURCE_COMPLIANCE,
                tags=["合规", category, severity],
                confidence=0.5,  # 首次沉淀，需要累积验证
                metadata={
                    "hit_count": self._EventAccumulator.THRESHOLD,  # 初始 = 阈值
                    "event_summary": description[:200],
                    "source_events": [
                        {"rule_name": e.get("rule_name"), "severity": e.get("severity")}
                        for e in pending_events[-5:]
                    ],
                },
            )

            self._provider.put(entry, merge=True)
            logger.info(f"合规知识沉淀: {rule_name} (≥{self._EventAccumulator.THRESHOLD}次触发)")

        # ── 第三层：定时淘汰 ──
        if self._auto_evict and self._event_count >= self._evict_interval:
            self.evict()
            self._event_count = 0

    def _on_guardrail_block(self, event: BusEvent) -> None:
        """护栏拦截事件 → RISK 知识（写入门控：确认拦截）"""
        data = event.data or {}
        direction = data.get("direction", "input")  # input/output
        violation_type = data.get("violation_type") or data.get("type") or "unknown"
        original_content = data.get("original_content", "")
        redacted_content = data.get("redacted_content", "")
        reason = data.get("reason", "")

        # ── 第一层：写入门控 ──
        # 护栏拦截不做累计阈值（每次确认拦截都值得记录）
        # 但只记录确认拦截（有 reason 的），忽略无 reason 的（疑似误拦）
        if not reason:
            logger.debug("护栏拦截事件无 reason，跳过沉淀（疑似误拦）")
            return

        # ── 第二层：去重合并 ──
        entry = KnowledgeEntry(
            type=KnowledgeType.RISK,
            scope=KnowledgeScope.PROJECT,
            title=f"护栏拦截: {violation_type}",
            content=f"护栏拦截了{direction}方向的{violation_type}类型内容\n\n"
                    f"拦截原因: {reason}\n"
                    f"原始内容(摘要): {original_content[:100]}...",
            source=self.SOURCE_GUARDRAIL,
            tags=["护栏", violation_type, direction],
            confidence=0.6,  # 护栏拦截较可靠
            metadata={
                "hit_count": 1,
                "event_summary": f"护栏拦截: {violation_type} ({direction})",
                "source_events": [{
                    "violation_type": violation_type,
                    "direction": direction,
                    "timestamp": event.timestamp.isoformat() if event.timestamp else "",
                }],
            },
        )

        self._provider.put(entry, merge=True)
        logger.info(f"护栏知识沉淀: {violation_type} ({direction})")
        self._event_count += 1

    def _on_gate_fail(self, event: BusEvent) -> None:
        """门禁拒绝事件 → DECISION 知识（只存架构级决策）"""
        self._persist_gate_decision(event, passed=False)

    def _on_gate_pass(self, event: BusEvent) -> None:
        """门禁通过事件 → DECISION 知识（只存架构级决策）"""
        self._persist_gate_decision(event, passed=True)

    def _persist_gate_decision(self, event: BusEvent, passed: bool) -> None:
        """门禁决策 → DECISION 知识（只存架构级决策）"""
        data = event.data or {}
        gate_id = data.get("gate_id") or data.get("id") or "unknown-gate"
        gate_mode = data.get("gate_mode", "hybrid")
        check_results = data.get("check_results", [])
        agent_id = data.get("agent_id", "")

        # ── 第一层：写入门控 ──
        # 只沉淀架构级决策（gate 包含 architecture/security 类检查）
        is_architectural = any(
            cr.get("category") in ("architecture", "security", "data")
            for cr in check_results
            if isinstance(cr, dict)
        )
        if not is_architectural:
            logger.debug(f"门禁决策非架构级，跳过沉淀: {gate_id}")
            return

        # ── 第二层：去重合并 ──
        status = "通过" if passed else "拒绝"
        entry = KnowledgeEntry(
            type=KnowledgeType.DECISION,
            scope=KnowledgeScope.PROJECT,
            title=f"门禁决策: {gate_id}",
            content=f"门禁 {gate_id} ({gate_mode}模式) {status}\n\n"
                    f"检查项:\n" + "\n".join(
                        f"  - {cr.get('id', '?')}: {cr.get('category', '?')} "
                        f"({'通过' if cr.get('passed') else '拒绝'})"
                        for cr in check_results[:5]
                        if isinstance(cr, dict)
                    ),
            source=self.SOURCE_GATE,
            tags=["门禁", gate_mode, status],
            confidence=0.7 if passed else 0.6,  # 拒绝决策置信度稍低（可能需要复查）
            metadata={
                "hit_count": 1,
                "event_summary": f"门禁{status}: {gate_id} ({gate_mode})",
                "source_events": [{
                    "gate_id": gate_id,
                    "passed": passed,
                    "timestamp": event.timestamp.isoformat() if event.timestamp else "",
                }],
            },
        )

        self._provider.put(entry, merge=True)
        logger.info(f"门禁知识沉淀: {gate_id} ({status})")
        self._event_count += 1

    def _on_recommendation(self, event: BusEvent) -> None:
        """学习推荐事件 → PATTERN/RISK 知识（confidence ≥ 0.7）"""
        data = event.data or {}
        rec_type = data.get("type", "agent")
        confidence = data.get("confidence", 0.0)
        description = data.get("description", "")
        suggested_action = data.get("suggested_action", "")

        # ── 第一层：写入门控 ──
        # 只沉淀高置信度推荐（≥ 0.7）
        if confidence < 0.7:
            logger.debug(f"学习推荐置信度过低({confidence:.2f}), 跳过沉淀")
            return

        # 确定知识类型
        if rec_type == "agent":
            knowledge_type = KnowledgeType.PATTERN
        elif rec_type == "architecture":
            knowledge_type = KnowledgeType.RISK
        elif rec_type in ("gate", "schedule"):
            return  # 这些类型不需要沉淀
        else:
            knowledge_type = KnowledgeType.PATTERN

        # ── 第二层：去重合并 ──
        entry = KnowledgeEntry(
            type=knowledge_type,
            scope=KnowledgeScope.PROJECT,
            title=f"学习推荐: {rec_type}",
            content=f"{description}\n\n建议操作: {suggested_action}",
            source=self.SOURCE_LEARNING,
            tags=["learned", rec_type],
            confidence=confidence,
            metadata={
                "hit_count": 1,
                "recommendation_type": rec_type,
                "event_summary": f"学习推荐({rec_type}): {description[:100]}",
                "source_events": [{
                    "type": rec_type,
                    "confidence": confidence,
                    "timestamp": event.timestamp.isoformat() if event.timestamp else "",
                }],
            },
        )

        self._provider.put(entry, merge=True)
        logger.info(f"学习知识沉淀: {rec_type} (confidence={confidence:.2f})")
        self._event_count += 1

    # ── 淘汰触发 ──

    def evict(self) -> Dict[str, Any]:
        """触发知识淘汰——第三层治理

        由 LocalKnowledgeProvider.evict_stale_entries() 执行：
        - 30天未查询 → 归档层
        - 90天未查询 + hit_count < 3 → 删除
        """
        result = self._provider.evict_stale_entries()
        logger.info(f"知识淘汰结果: 归档{result['archived']}条, 删除{result['deleted']}条")
        return result

    # ── 状态查询 ──

    def stats(self) -> Dict[str, Any]:
        """返回 KnowledgeSubscriber 运行统计"""
        return {
            "event_count": self._event_count,
            "accumulator_stats": self._accumulator.stats(),
            "provider_stats": self._provider.stats(),
        }

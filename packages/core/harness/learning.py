"""
harness-cook 自学习模块

Learning 是 Harness 的"经验库"——从历史执行中挖掘模式、校准预估、推荐改进。
核心能力：
  1. 模式挖掘（PatternMiner）——发现反复出现的成功/失败模式
  2. 反模式检测（AntiPatternDetector）——识别常见错误模式
  3. 预估校准（PredictionCalibrator）——让token/时间预估越来越准
  4. 推荐引擎（RecommendationEngine）——基于历史数据给出改进建议

E-6 重构——产出 Insight 而非 ComplianceRule：
  Learning 产出 Insight（洞见），通过 EventBus 发射 INSIGHT_FOUND 事件。
  Insight 进入知识库供查看和决策，不自动注册为 ComplianceRule。
  消除自动注册路径：Learning → Recommendation(type="rule") → ComplianceEngine._on_recommendation → 自动注册规则。

触发路径声明（E-5/E-6）：
  - 路径1：Insight → 知识库写入（Learning._persist_to_knowledge）
  - 路径2：Insight → EventBus 事件（BusEventType.INSIGHT_FOUND）
  - 禁止路径：Insight → 自动注册为 ComplianceRule（已消除）
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple, Any
from datetime import datetime
from harness.types import ExecutionTrace, TraceNode, Recommendation, CheckResult, Insight
from harness.bus import EventBus, BusEventType, BusEvent, get_bus


logger = logging.getLogger("harness.learning")


# ─── 经验存储 ────────────────────────────────────────

class ExperienceStore:
    """
    经验存储——保存历史执行轨迹，供后续学习使用

    简化版：内存存储 + 基本统计。
    生产版：可替换为向量数据库（相似轨迹检索）。
    """

    def __init__(self):
        self._traces: List[ExecutionTrace] = []
        self._patterns: Dict[str, dict] = {}    # 挖掘出的模式

    def store(self, trace: ExecutionTrace) -> None:
        """存储执行轨迹"""
        self._traces.append(trace)

    def get_traces(
        self,
        workflow_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[ExecutionTrace]:
        """检索历史轨迹"""
        traces = self._traces
        if workflow_id:
            traces = [t for t in traces if t.workflow_id == workflow_id]
        return traces[-limit:]

    def store_pattern(self, pattern_id: str, pattern_data: dict) -> None:
        """存储挖掘出的模式"""
        self._patterns[pattern_id] = pattern_data

    def get_patterns(self) -> Dict[str, dict]:
        """获取所有模式"""
        return dict(self._patterns)

    def stats(self) -> dict:
        return {
            "total_traces": len(self._traces),
            "total_patterns": len(self._patterns),
            "success_rate": (
                sum(1 for t in self._traces if t.final_status == "completed")
                / len(self._traces)
                if self._traces else 0
            ),
        }


# ─── 模式挖掘 ────────────────────────────────────────

class PatternMiner:
    """
    模式挖掘——从历史轨迹中发现反复出现的成功/失败模式

    检测的模式类型：
      - 频繁失败组合（某些Agent组合经常失败）
      - 频繁成功路径（某些执行路径成功率特别高）
      - 资源浪费模式（某些节点token消耗远超预估）
    """

    def __init__(self, store: ExperienceStore):
        self._store = store

    def mine(self) -> list[Recommendation]:
        """挖掘模式 → 生成推荐"""
        traces = self._store.get_traces(limit=200)
        if len(traces) < 5:
            logger.info("Not enough traces for pattern mining (need at least 5)")
            return []

        recommendations = []

        # 1. 频繁失败组合
        failure_patterns = self._find_failure_patterns(traces)
        for pattern in failure_patterns:
            recommendations.append(Recommendation(
                type="agent",
                confidence=pattern["confidence"],
                description=pattern["description"],
                suggested_action=pattern["suggested_action"],
                evidence=pattern["evidence"],
            ))
            self._store.store_pattern(pattern["id"], pattern)

        # 2. 资源浪费模式
        waste_patterns = self._find_resource_waste(traces)
        for pattern in waste_patterns:
            recommendations.append(Recommendation(
                type="schedule",
                confidence=pattern["confidence"],
                description=pattern["description"],
                suggested_action=pattern["suggested_action"],
                evidence=pattern["evidence"],
            ))
            self._store.store_pattern(pattern["id"], pattern)

        # 3. 频繁成功路径
        success_patterns = self._find_success_patterns(traces)
        for pattern in success_patterns:
            recommendations.append(Recommendation(
                type="architecture",
                confidence=pattern["confidence"],
                description=pattern["description"],
                suggested_action=pattern["suggested_action"],
                evidence=pattern["evidence"],
            ))
            self._store.store_pattern(pattern["id"], pattern)

        return recommendations

    def _find_failure_patterns(self, traces: list[ExecutionTrace]) -> list[dict]:
        """找出频繁失败的Agent组合"""
        # 统计每个Agent的失败率
        agent_failures: Dict[str, int] = {}
        agent_totals: Dict[str, int] = {}

        for trace in traces:
            for node in trace.nodes:
                agent_totals[node.agent_type] = agent_totals.get(node.agent_type, 0) + 1
                if node.result_status == "failed":
                    agent_failures[node.agent_type] = agent_failures.get(node.agent_type, 0) + 1

        patterns = []
        for agent, failures in agent_failures.items():
            total = agent_totals.get(agent, 0)
            rate = failures / total if total > 0 else 0
            if rate > 0.3:   # 失败率超过30%
                patterns.append({
                    "id": f"failure-{agent}",
                    "confidence": min(rate, 0.95),
                    "description": f"Agent {agent} has high failure rate: {rate:.1%}",
                    "suggested_action": f"Review {agent} implementation or add stronger gates",
                    "evidence": [f"Failure rate: {rate:.1%} ({failures}/{total} tasks)"],
                })

        return patterns

    def _find_resource_waste(self, traces: list[ExecutionTrace]) -> list[dict]:
        """找出token消耗异常的节点"""
        patterns = []

        # 统计每个Agent的平均token消耗
        agent_tokens: Dict[str, list[int]] = {}
        for trace in traces:
            for node in trace.nodes:
                if node.agent_type not in agent_tokens:
                    agent_tokens[node.agent_type] = []
                agent_tokens[node.agent_type].append(node.tokens_used)

        for agent, tokens_list in agent_tokens.items():
            if len(tokens_list) < 3:
                continue
            avg = sum(tokens_list) / len(tokens_list)
            max_tokens = max(tokens_list)
            # 最大消耗超过平均值3倍 → 异常
            if max_tokens > avg * 3:
                patterns.append({
                    "id": f"waste-{agent}",
                    "confidence": 0.7,
                    "description": f"Agent {agent} has occasional token spikes: max {max_tokens} vs avg {int(avg)}",
                    "suggested_action": f"Add token budget limit or split large tasks for {agent}",
                    "evidence": [f"Average: {int(avg)}, Max: {max_tokens}, Ratio: {max_tokens/avg:.1f}x"],
                })

        return patterns

    def _find_success_patterns(self, traces: list[ExecutionTrace]) -> list[dict]:
        """找出成功率特别高的执行路径"""
        patterns = []

        # 统计每个workflow的成功率
        workflow_stats: Dict[str, Dict[str, int]] = {}
        for trace in traces:
            if trace.workflow_id not in workflow_stats:
                workflow_stats[trace.workflow_id] = {"success": 0, "total": 0}
            workflow_stats[trace.workflow_id]["total"] += 1
            if trace.final_status == "completed":
                workflow_stats[trace.workflow_id]["success"] += 1

        for wf_id, stats in workflow_stats.items():
            if stats["total"] < 3:
                continue
            rate = stats["success"] / stats["total"]
            if rate > 0.8:   # 成功率超过80%
                patterns.append({
                    "id": f"success-{wf_id}",
                    "confidence": min(rate, 0.95),
                    "description": f"Workflow {wf_id} has high success rate: {rate:.1%}",
                    "suggested_action": f"Use {wf_id} workflow structure as template for similar tasks",
                    "evidence": [f"Success rate: {rate:.1%} ({stats['success']}/{stats['total']} runs)"],
                })

        return patterns


# ─── 反模式检测 ────────────────────────────────────────

class AntiPatternDetector:
    """
    反模式检测——识别当前执行中的常见错误模式

    已知反模式：
      - "过度重试"：同一节点重试超过3次
      - "门禁松弛"：LOOSE模式下所有检查都pass → 可能是规则太弱
      - "token爆炸"：单个任务消耗超过总预算的50%
    """

    KNOWN_ANTIPATTERNS = {
        "over-retry": {
            "description": "Node retried more than 3 times",
            "threshold": 3,
            "suggested_action": "Review agent implementation or strengthen gate checks",
        },
        "gate-too-loose": {
            "description": "All gate checks pass in LOOSE mode — rules may be too weak",
            "threshold": 0,
            "suggested_action": "Consider switching to HYBRID or STRICT mode",
        },
        "token-explosion": {
            "description": "Single task consumes >50% of total budget",
            "threshold": 0.5,
            "suggested_action": "Split the task or add token budget limit",
        },
    }

    def detect(self, trace: ExecutionTrace, token_budget: int = 200000) -> list[Recommendation]:
        """检测当前执行轨迹中的反模式"""
        recommendations = []

        # 1. 过度重试
        for node in trace.nodes:
            if node.retries > 3:
                recommendations.append(Recommendation(
                    type="gate",
                    confidence=0.8,
                    description=f"Over-retry detected: {node.agent_type} retried {node.retries} times",
                    suggested_action="Strengthen pre-execution checks or review agent implementation",
                    evidence=[f"Node {node.node_id}: {node.retries} retries"],
                ))
                # ── Learning → RulePack 闭环: 反模式同时建议注册规则 ──
                recommendations.append(Recommendation(
                    type="rule",
                    confidence=0.8,
                    description=f"Over-retry pattern for {node.agent_type}",
                    suggested_action=f"Add retry limit rule for {node.agent_type}: max 3 retries",
                    evidence=[f"Node {node.node_id}: {node.retries} retries"],
                ))

        # 2. Token爆炸
        total_tokens = sum(n.tokens_used for n in trace.nodes)
        for node in trace.nodes:
            if node.tokens_used > token_budget * 0.5:
                ratio = node.tokens_used / token_budget
                recommendations.append(Recommendation(
                    type="schedule",
                    confidence=0.9,
                    description=f"Token explosion: {node.agent_type} used {ratio:.1%} of total budget",
                    suggested_action="Split large tasks or add per-node token limits",
                    evidence=[f"Node {node.node_id}: {node.tokens_used} tokens ({ratio:.1%} of budget)"],
                ))
                # ── Learning → RulePack 闭环: Token 爆炸建议注册预算规则 ──
                recommendations.append(Recommendation(
                    type="rule",
                    confidence=0.9,
                    description=f"Token budget exceeded by {node.agent_type}",
                    suggested_action=f"Add token budget rule: {node.agent_type} max {int(token_budget * 0.4)} tokens",
                    evidence=[f"Node {node.node_id}: {node.tokens_used} tokens ({ratio:.1%})"],
                ))

        # 3. 全部通过但太快（门禁可能太松）
        quick_passes = [
            n for n in trace.nodes
            if n.gate_passed and n.duration_ms < 1000 and n.result_status == "completed"
        ]
        if len(quick_passes) > len(trace.nodes) * 0.5 and len(trace.nodes) > 5:
            recommendations.append(Recommendation(
                type="gate",
                confidence=0.5,
                description="Many nodes pass gates very quickly — checks may be too loose",
                suggested_action="Review gate check depth, consider HYBRID or STRICT mode",
                evidence=[f"{len(quick_passes)}/{len(trace.nodes)} nodes passed in <1s"],
            ))

        return recommendations


# ─── 预估校准 ────────────────────────────────────────

class PredictionCalibrator:
    """
    预估校准——让 Scheduler 的 token/时间预估越来越准

    方法：维护每个Agent的平均值和方差，新预估 = 历史均值 × 加权平均
    """

    def __init__(self, store: ExperienceStore):
        self._store = store
        self._agent_estimates: Dict[str, dict] = {}  # agent_type → {avg_tokens, avg_duration, count}

    def calibrate(self) -> Dict[str, dict]:
        """根据历史数据校准预估参数"""
        traces = self._store.get_traces(limit=200)

        # 按Agent类型统计平均值
        agent_data: Dict[str, list] = {}
        for trace in traces:
            for node in trace.nodes:
                if node.agent_type not in agent_data:
                    agent_data[node.agent_type] = {"tokens": [], "durations": []}
                agent_data[node.agent_type]["tokens"].append(node.tokens_used)
                agent_data[node.agent_type]["durations"].append(node.duration_ms)

        # 计算校准值
        for agent_type, data in agent_data.items():
            n = len(data["tokens"])
            if n < 2:
                continue

            avg_tokens = sum(data["tokens"]) / n
            avg_duration = sum(data["durations"]) / n
            std_tokens = math.sqrt(sum((t - avg_tokens) ** 2 for t in data["tokens"]) / n)

            self._agent_estimates[agent_type] = {
                "avg_tokens": int(avg_tokens),
                "avg_duration_ms": int(avg_duration),
                "std_tokens": int(std_tokens),
                "sample_count": n,
                "calibrated_at": datetime.now().isoformat(),
            }

        logger.info(f"Calibrated estimates for {len(self._agent_estimates)} agent types")
        return dict(self._agent_estimates)

    def get_estimate(self, agent_type: str) -> Optional[dict]:
        """获取校准后的预估"""
        return self._agent_estimates.get(agent_type)

    def get_all_estimates(self) -> Dict[str, dict]:
        """获取所有校准预估"""
        return dict(self._agent_estimates)


# ─── 学习引擎 ────────────────────────────────────────

class LearningEngine:
    """
    学习引擎——整合模式挖掘、反模式检测、预估校准

    用法:
        engine = LearningEngine()
        recommendations = engine.learn(trace)
        # recommendations → 调整 Scheduler/Gate/Agent 的参数
    """

    def __init__(
        self,
        store: Optional[ExperienceStore] = None,
        bus: Optional[EventBus] = None,
        token_budget: int = 200000,
        knowledge_provider: Optional[Any] = None,
    ):
        self._store = store or ExperienceStore()
        self._bus = bus or get_bus()
        self._miner = PatternMiner(self._store)
        self._antipattern = AntiPatternDetector()
        self._calibrator = PredictionCalibrator(self._store)
        self._token_budget = token_budget
        self._knowledge_provider = knowledge_provider  # LocalKnowledgeProvider 或 None

    def record_trace(self, trace: ExecutionTrace) -> None:
        """记录执行轨迹"""
        self._store.store(trace)

        # 通知事件（reserved）：trace 已同步存入 self._store；当前无异步订阅者，保留作可观测/未来消费者接入
        self._bus.emit(BusEvent(
            type=BusEventType.TRACE_CAPTURED,
            execution_id=trace.workflow_id,
            data={
                "duration_ms": trace.duration_ms,
                "node_count": len(trace.nodes),
                "status": trace.final_status,
            },
        ))

    def learn(self, trace: Optional[ExecutionTrace] = None) -> list[Recommendation]:
        """
        学习——从轨迹中挖掘推荐 + 产出 Insight（E-6 重构）

        如果提供当前轨迹：反模式检测 + 模式挖掘
        如果不提供：只做模式挖掘（用历史数据）

        E-6 变化：
          1. 反模式检测结果同时产出 Insight（洞见）
          2. Insight 通过 INSIGHT_FOUND 事件发射（替代 Recommendation→rule 自动路径）
          3. Insight 进入知识库供查看，不自动注册为 ComplianceRule
        """
        recommendations = []

        if trace:
            # 反模式检测
            antipatterns = self._antipattern.detect(trace, self._token_budget)
            recommendations.extend(antipatterns)

            # 记录轨迹
            self.record_trace(trace)

        # 模式挖掘（用全部历史数据）
        patterns = self._miner.mine()
        recommendations.extend(patterns)

        # 预估校准
        self._calibrator.calibrate()

        # ── E-6：产出 Insight ──
        # 将高置信度反模式推荐转换为 Insight
        insights = self._convert_to_insights(recommendations)

        # ── 知识沉淀：Insight 写入 Knowledge 模块 ──
        if self._knowledge_provider:
            self._persist_insights_to_knowledge(insights)

        # 发射推荐事件（保留原有 RECOMMENDATION 事件，供 Scheduler/Gate 使用）
        for rec in recommendations:
            self._bus.emit(BusEvent(
                type=BusEventType.RECOMMENDATION,
                execution_id="learning",
                data={
                    "type": rec.type,
                    "confidence": rec.confidence,
                    "description": rec.description,
                    "suggested_action": rec.suggested_action,
                },
            ))

        # 通知事件（reserved）：insight 已通过 _persist_insights_to_knowledge 同步写入知识库（路径1）；
        # 本事件（路径2）当前无异步订阅者，保留作可观测/未来消费者接入
        for insight in insights:
            self._bus.emit(BusEvent(
                type=BusEventType.INSIGHT_FOUND,
                execution_id="learning",
                project_name=insight.source_project,
                data={
                    "pattern_type": insight.pattern_type,
                    "confidence": insight.confidence,
                    "title": insight.title,
                    "description": insight.description,
                    "remediation": insight.remediation,
                    "evidence": insight.evidence,
                },
            ))

        return recommendations

    def _convert_to_insights(self, recommendations: list[Recommendation]) -> list[Insight]:
        """
        将高置信度推荐转换为 Insight（E-6）

        只转换 agent 和 architecture 类型的高置信度推荐（≥ 0.7），
        schedule/gate 类型不做转换（它们是运行时调整建议，不是治理洞见）。
        """
        insights = []

        for rec in recommendations:
            # 只处理高置信度的治理类推荐
            if rec.confidence < 0.7:
                continue

            if rec.type == "agent":
                pattern_type = "antipattern"
            elif rec.type == "architecture":
                pattern_type = "risk"
            elif rec.type in ("gate", "schedule"):
                continue  # 不转换为 Insight
            else:
                pattern_type = "antipattern"

            insight = Insight(
                pattern_type=pattern_type,
                confidence=rec.confidence,
                title=rec.description[:80] if len(rec.description) > 80 else rec.description,
                description=rec.description,
                remediation=rec.suggested_action,
                evidence=rec.evidence,
                source_project=None,  # 项目名由调用方在 BusEvent 中携带
                metadata={
                    "recommendation_type": rec.type,
                },
            )
            insights.append(insight)

        return insights

    def _persist_insights_to_knowledge(self, insights: list[Insight]) -> None:
        """
        将 Insight 沉淀为知识条目（E-6 重构）

        将 Insight 转换为 KnowledgeEntry，通过 merge=True 写入 KnowledgeProvider。
        Insight 不自动注册为 ComplianceRule——只写入知识库供查看和决策。

        三层治理：
        - 第一层写入门控：confidence < 0.7 的 Insight 直接跳过（_convert_to_insights 已过滤）
        - 第二层去重合并：按 Insight pattern_type + title 做去重键
        - 第三层自动淘汰：由 LocalKnowledgeProvider.evict_stale_entries() 处理

        禁止路径（E-6 消除）：
          Insight → 自动注册为 ComplianceRule（此路径已被消除）
        """
        if not self._knowledge_provider:
            return

        try:
            from harness.knowledge import KnowledgeEntry, KnowledgeType, KnowledgeScope

            persisted_count = 0
            for insight in insights:
                # 根据 Insight pattern_type 选择知识类型
                knowledge_type = None
                if insight.pattern_type == "antipattern":
                    knowledge_type = KnowledgeType.PATTERN
                elif insight.pattern_type == "risk":
                    knowledge_type = KnowledgeType.RISK
                elif insight.pattern_type == "architecture":
                    knowledge_type = KnowledgeType.DECISION

                if not knowledge_type:
                    continue

                # 创建知识条目（Insight 标题做去重键 → 同类归同一条目）
                entry = KnowledgeEntry(
                    type=knowledge_type,
                    scope=KnowledgeScope.PROJECT,
                    title=f"洞见: {insight.title}",
                    content=f"{insight.description}\n\n修复建议: {insight.remediation}",
                    tags=["insight", insight.pattern_type],
                    confidence=insight.confidence,
                    source="learning-insight",
                    metadata={
                        "insight_pattern_type": insight.pattern_type,
                        "event_summary": f"洞见({insight.pattern_type}): {insight.description[:100]}",
                        "source_events": [{
                            "pattern_type": insight.pattern_type,
                            "confidence": insight.confidence,
                        }],
                    },
                )

                # 写入 KnowledgeProvider（merge=True → 自动去重合并 + hit_count 累计）
                self._knowledge_provider.put(entry, merge=True)
                persisted_count += 1
                logger.debug(f"Persisted insight to knowledge: {entry.id}")

            if persisted_count > 0:
                logger.info(f"Persisted {persisted_count} insights to knowledge")
        except Exception as e:
            logger.warning(f"Failed to persist insights to knowledge: {e}")

    def get_calibrated_estimates(self) -> Dict[str, dict]:
        """获取校准后的预估参数"""
        return self._calibrator.get_all_estimates()

    def stats(self) -> dict:
        return {
            "experience_store": self._store.stats(),
            "calibrated_agents": len(self._calibrator.get_all_estimates()),
        }
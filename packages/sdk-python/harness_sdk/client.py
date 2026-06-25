"""
harness-sdk Client——编排、合规、审计一站式接口

HarnessClient 封装 Harness 各子系统的操作:
  1. DAG 编排 —— run_workflow / run_single_task
  2. 合规扫描 —— compliance_scan
  3. 审计查询 —— audit_query / audit_stats
  4. 知识注入 —— inject_knowledge
  5. 学习触发 —— trigger_learning

用法:
    from harness_sdk import create_client

    client = create_client(project_name="my-project")

    # DAG编排
    result = client.run_workflow(workflow, inputs={})

    # 合规扫描
    scan_result = client.compliance_scan(artifacts=[...], packs=["security"])

    # 审计查询
    entries = client.audit_query(task="code-review", limit=20)
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from harness.types import (
    DAGWorkflow, TaskResult, TaskStatus, Artifact, ComplianceResult,
    AuditEntry, AuditStats, ExecutionTrace, Recommendation,
)
from harness.engine import DAGEngine, ExecutionContext
from harness.compliance import ComplianceEngine
from harness.audit import AuditEngine, AuditStore
from harness.learning import LearningEngine
from harness.config import HarnessConfig, load_config
from harness.knowledge import (
    LocalKnowledgeProvider, KnowledgeQuery, KnowledgeContext,
    get_knowledge_provider,
)
from harness.registry import get_registry

logger = logging.getLogger("harness_sdk.client")


# ─── Client 配置 ────────────────────────────────────────

@dataclass
class HarnessClientConfig:
    """Client 配置"""
    project_name: str = "default"
    config_path: Optional[str] = None
    learning_enabled: bool = True
    audit_enabled: bool = True


# ─── Harness Client ────────────────────────────────────────

class HarnessClient:
    """Harness 一站式 Client——编排+合规+审计+学习

    用法:
        client = HarnessClient(HarnessClientConfig(project_name="my-app"))
        # 或
        client = create_client(project_name="my-app")

        # DAG编排
        result = client.run_workflow(dag_workflow, inputs={"task": "review code"})

        # 合规扫描
        scan = client.compliance_scan(artifacts=[...], packs=["security", "privacy"])

        # 审计
        stats = client.audit_stats()
        entries = client.audit_query(task="code-review", limit=10)
    """

    def __init__(self, config: HarnessClientConfig):
        self._config = config

        # 加载 Harness 配置
        self._harness_config = load_config(config.config_path)

        # 初始化子系统
        self._engine = DAGEngine()
        self._compliance = ComplianceEngine()
        self._audit_store = AuditStore()
        self._audit_engine = AuditEngine(self._audit_store)
        self._learning = LearningEngine() if config.learning_enabled else None
        self._knowledge = get_knowledge_provider(config.project_name)

    # ─── DAG 编排 ──

    def run_workflow(
        self,
        workflow: DAGWorkflow,
        inputs: Optional[Dict[str, Any]] = None,
        config_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, TaskResult]:
        """运行 DAG 工作流

        Args:
            workflow: DAGWorkflow 定义
            inputs: 节点输入参数
            config_override: 运行时配置覆盖

        Returns:
            node_id → TaskResult 的映射
        """
        registry = get_registry()
        context = ExecutionContext(
            workflow=workflow,
            registry=registry,
            config=self._harness_config,
        )

        results = self._engine.execute(context)

        # 审计记录
        if self._config.audit_enabled:
            self._audit_engine.record_workflow(workflow, results)

        return results

    def run_single_task(
        self,
        agent_id: str,
        task: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> TaskResult:
        """运行单个 Agent 任务（不走 DAG）

        Args:
            agent_id: 已注册的 Agent ID
            task: 任务描述
            context: 执行上下文

        Returns:
            TaskResult
        """
        registry = get_registry()
        agent = registry.get_implementation(agent_id)
        if agent is None:
            return TaskResult(
                task_id="",
                agent_id=agent_id,
                status=TaskStatus.FAILED,
                artifacts=[],
                duration_ms=0,
                error=f"Agent '{agent_id}' not found in registry",
            )

        if context is None:
            context = {}

        return agent.execute(task, context)

    # ─── 合规 ──

    def compliance_scan(
        self,
        artifacts: List[Artifact],
        packs: Optional[List[str]] = None,
    ) -> List[ComplianceResult]:
        """合规扫描

        Args:
            artifacts: 要检查的产出物列表
            packs: 规则包名称列表（默认 ["security", "privacy"]）

        Returns:
            ComplianceResult 列表
        """
        from harness.compliance import ComplianceCategory

        if packs is None:
            categories = [ComplianceCategory.SECURITY, ComplianceCategory.PRIVACY]
        else:
            category_map = {
                "security": ComplianceCategory.SECURITY,
                "privacy": ComplianceCategory.PRIVACY,
                "license": ComplianceCategory.LICENSE,
                "style": ComplianceCategory.STYLE,
                "architecture": ComplianceCategory.ARCHITECTURE,
            }
            categories = [category_map[p] for p in packs if p in category_map]

        return self._compliance.scan(artifacts, categories)

    # ─── 审计 ──

    def audit_query(
        self,
        task: Optional[str] = None,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[AuditEntry]:
        """审计查询

        Args:
            task: 按任务关键词过滤
            agent_id: 按 Agent ID 过滤
            status: 按状态过滤
            limit: 返回条数上限

        Returns:
            AuditEntry 列表
        """
        # AuditStore.search(query, agent_id=..., limit=...) 对应
        query_str = task or ""
        entries = self._audit_store.search(
            query=query_str,
            agent_id=agent_id,
            limit=limit,
        )
        return entries

    def audit_stats(self) -> AuditStats:
        """审计统计"""
        return self._audit_engine.get_stats()

    # ─── 学习 ──

    def trigger_learning(
        self,
        trace: Optional[ExecutionTrace] = None,
    ) -> List[Recommendation]:
        """触发学习——挖掘推荐

        Args:
            trace: 当前执行轨迹（可选）

        Returns:
            Recommendation 列表
        """
        if self._learning is None:
            logger.info("Learning disabled, skipping")
            return []
        return self._learning.learn(trace)

    def get_calibrated_estimates(self) -> Dict[str, Dict[str, Any]]:
        """获取校准后的预估参数"""
        if self._learning is None:
            return {}
        return self._learning.get_calibrated_estimates()

    # ─── 知识 ──

    def inject_knowledge(
        self,
        query: str,
        type_filter: Optional[str] = None,
        scope_filter: Optional[str] = None,
        limit: int = 10,
    ) -> KnowledgeContext:
        """知识注入——查询知识库并构造注入上下文

        Args:
            query: 搜索关键词
            type_filter: 知识类型过滤
            scope_filter: 知识范围过滤
            limit: 返回条数上限

        Returns:
            KnowledgeContext（可注入到 Agent 的 context）
        """
        from harness.knowledge import KnowledgeType, KnowledgeScope

        resolved_type = None
        if type_filter:
            resolved_type = KnowledgeType(type_filter)

        resolved_scope = None
        if scope_filter:
            resolved_scope = KnowledgeScope(scope_filter)

        kw_query = KnowledgeQuery(
            query=query,
            type_filter=resolved_type,
            scope_filter=resolved_scope,
            limit=limit,
        )
        result = self._knowledge.query(kw_query)

        return KnowledgeContext(
            provider=self._knowledge,
            relevant_entries=result.entries,
            query_result=result,
        )

    def add_knowledge(
        self,
        title: str,
        content: str,
        type: str = "architecture",
        scope: str = "project",
        tags: Optional[List[str]] = None,
        source: Optional[str] = None,
    ) -> str:
        """添加知识条目

        Args:
            title: 知识标题
            content: 知识内容
            type: 知识类型
            scope: 知识范围
            tags: 标签列表
            source: 知识来源

        Returns:
            知识条目 ID
        """
        from harness.knowledge import KnowledgeEntry, KnowledgeType, KnowledgeScope

        entry = KnowledgeEntry(
            type=KnowledgeType(type),
            scope=KnowledgeScope(scope),
            title=title,
            content=content,
            tags=tags or [],
            source=source,
        )
        return self._knowledge.put(entry)

    # ─── 统计 ──

    def stats(self) -> Dict[str, Any]:
        """Harness 全局统计"""
        audit_stats = self._audit_engine.get_stats()
        learning_stats = self._learning.stats() if self._learning else {}
        knowledge_stats = self._knowledge.stats()

        return {
            "audit": {
                "total_tasks": audit_stats.total_tasks,
                "delivered": audit_stats.delivered,
                "escalated": audit_stats.escalated,
            },
            "learning": learning_stats,
            "knowledge": knowledge_stats,
        }


# ─── 便捷函数 ────────────────────────────────────────

def create_client(
    project_name: str = "default",
    config_path: Optional[str] = None,
    learning_enabled: bool = True,
    audit_enabled: bool = True,
) -> HarnessClient:
    """创建 Harness Client——便捷函数

    用法:
        client = create_client("my-project")
        result = client.run_workflow(workflow)
    """
    config = HarnessClientConfig(
        project_name=project_name,
        config_path=config_path,
        learning_enabled=learning_enabled,
        audit_enabled=audit_enabled,
    )
    return HarnessClient(config)
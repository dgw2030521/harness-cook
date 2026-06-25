"""
Phase 3 测试: 知识管理适配层

从 nextX IKnowledgeProvider/KnowledgeType/KnowledgeScope 提取的设计模式,
在 harness-cook 中适配为 Python 实现。

测试覆盖:
- KnowledgeType: 10种枚举
- KnowledgeScope: 4级范围
- KnowledgeEntry: 构造/ID生成/关键词匹配/过滤/概要
- KnowledgeQuery/KnowledgeQueryResult: 查询请求和结果
- LocalKnowledgeProvider: CRUD/查询/索引/统计/持久化
- KnowledgeContext: Agent上下文注入
- NoOpEmbeddingService: 降级兜底
"""

import unittest
import os
import tempfile
from harness.knowledge import (
    KnowledgeType, KnowledgeScope, KnowledgeEntry,
    KnowledgeQuery, KnowledgeQueryResult,
    LocalKnowledgeProvider, NoOpEmbeddingService,
    KnowledgeContext, get_knowledge_provider,
)


class TestKnowledgeType(unittest.TestCase):
    """10种知识类型枚举"""

    def test_all_types(self):
        types = list(KnowledgeType)
        assert len(types) == 10
        expected_values = [
            "architecture", "convention", "dependency", "api", "pattern",
            "risk", "decision", "task", "test", "glossary",
        ]
        actual_values = [t.value for t in types]
        assert sorted(actual_values) == sorted(expected_values)

    def test_common_types(self):
        assert KnowledgeType.ARCHITECTURE.value == "architecture"
        assert KnowledgeType.CONVENTION.value == "convention"
        assert KnowledgeType.API.value == "api"
        assert KnowledgeType.RISK.value == "risk"
        assert KnowledgeType.DECISION.value == "decision"
        assert KnowledgeType.GLOSSARY.value == "glossary"


class TestKnowledgeScope(unittest.TestCase):
    """4级知识范围枚举"""

    def test_all_scopes(self):
        scopes = list(KnowledgeScope)
        assert len(scopes) == 4
        assert KnowledgeScope.PROJECT.value == "project"
        assert KnowledgeScope.MODULE.value == "module"
        assert KnowledgeScope.FILE.value == "file"
        assert KnowledgeScope.FUNCTION.value == "function"

    def test_scope_hierarchy(self):
        """范围层级: project > module > file > function"""
        scopes = [KnowledgeScope.PROJECT, KnowledgeScope.MODULE,
                  KnowledgeScope.FILE, KnowledgeScope.FUNCTION]
        assert len(scopes) == 4


class TestKnowledgeEntry(unittest.TestCase):
    """知识条目——核心数据模型"""

    def test_creation_with_defaults(self):
        e = KnowledgeEntry(
            type=KnowledgeType.ARCHITECTURE,
            scope=KnowledgeScope.PROJECT,
            title="项目架构",
            content="采用React+TypeScript前端架构",
        )
        assert e.id is not None
        assert len(e.id) == 12  # SHA-256短hash
        assert e.type == KnowledgeType.ARCHITECTURE
        assert e.scope == KnowledgeScope.PROJECT
        assert e.confidence == 1.0
        assert e.source is None
        assert e.created_at is not None
        assert e.updated_at is not None

    def test_id_stability(self):
        """相同type+scope+title生成相同ID"""
        e1 = KnowledgeEntry(type=KnowledgeType.API, scope=KnowledgeScope.FILE, title="login API")
        e2 = KnowledgeEntry(type=KnowledgeType.API, scope=KnowledgeScope.FILE, title="login API")
        assert e1.id == e2.id

    def test_id_different_title(self):
        """不同title生成不同ID"""
        e1 = KnowledgeEntry(type=KnowledgeType.API, scope=KnowledgeScope.FILE, title="login API")
        e2 = KnowledgeEntry(type=KnowledgeType.API, scope=KnowledgeScope.FILE, title="logout API")
        assert e1.id != e2.id

    def test_matches_query_title(self):
        e = KnowledgeEntry(
            type=KnowledgeType.ARCHITECTURE,
            title="React项目架构",
            content="采用React框架",
        )
        assert e.matches_query("react") is True
        assert e.matches_query("vue") is False

    def test_matches_query_content(self):
        e = KnowledgeEntry(
            type=KnowledgeType.CONVENTION,
            title="编码规范",
            content="变量命名用camelCase",
        )
        assert e.matches_query("camelcase") is True
        assert e.matches_query("snake_case") is False

    def test_matches_query_tags(self):
        e = KnowledgeEntry(
            type=KnowledgeType.RISK,
            title="安全风险",
            tags=["security", "auth"],
        )
        assert e.matches_query("security") is True
        assert e.matches_query("auth") is True

    def test_matches_filters_type(self):
        e = KnowledgeEntry(type=KnowledgeType.API, scope=KnowledgeScope.FILE)
        assert e.matches_filters(type_filter=KnowledgeType.API) is True
        assert e.matches_filters(type_filter=KnowledgeType.RISK) is False

    def test_matches_filters_scope(self):
        e = KnowledgeEntry(type=KnowledgeType.API, scope=KnowledgeScope.FILE)
        assert e.matches_filters(scope_filter=KnowledgeScope.FILE) is True
        assert e.matches_filters(scope_filter=KnowledgeScope.PROJECT) is False

    def test_matches_filters_tags(self):
        e = KnowledgeEntry(tags=["python", "testing"])
        assert e.matches_filters(tags_filter=["python"]) is True
        assert e.matches_filters(tags_filter=["java"]) is False

    def test_matches_filters_source(self):
        e = KnowledgeEntry(source="human")
        assert e.matches_filters(source_filter="human") is True
        assert e.matches_filters(source_filter="ast") is False

    def test_matches_filters_combined(self):
        e = KnowledgeEntry(
            type=KnowledgeType.RISK,
            scope=KnowledgeScope.FILE,
            tags=["security"],
            source="llm",
        )
        assert e.matches_filters(
            type_filter=KnowledgeType.RISK,
            scope_filter=KnowledgeScope.FILE,
        ) is True
        assert e.matches_filters(
            type_filter=KnowledgeType.RISK,
            scope_filter=KnowledgeScope.PROJECT,
        ) is False

    def test_summary(self):
        e = KnowledgeEntry(
            type=KnowledgeType.ARCHITECTURE,
            scope=KnowledgeScope.PROJECT,
            title="项目架构",
            content="采用React+TypeScript",
        )
        s = e.summary()
        assert "architecture" in s
        assert "project" in s
        assert "项目架构" in s

    def test_explicit_id(self):
        e = KnowledgeEntry(id="custom-id-123", title="test")
        assert e.id == "custom-id-123"

    def test_custom_confidence(self):
        e = KnowledgeEntry(title="test", confidence=0.7, source="llm")
        assert e.confidence == 0.7
        assert e.source == "llm"


class TestKnowledgeQuery(unittest.TestCase):
    """知识查询请求"""

    def test_default_query(self):
        q = KnowledgeQuery(query="react")
        assert q.query == "react"
        assert q.type_filter is None
        assert q.limit == 20

    def test_filtered_query(self):
        q = KnowledgeQuery(
            query="security",
            type_filter=KnowledgeType.RISK,
            scope_filter=KnowledgeScope.FILE,
            tags_filter=["auth"],
            source_filter="human",
            limit=5,
        )
        assert q.type_filter == KnowledgeType.RISK
        assert q.scope_filter == KnowledgeScope.FILE
        assert q.limit == 5


class TestKnowledgeQueryResult(unittest.TestCase):
    """知识查询结果"""

    def test_default_result(self):
        r = KnowledgeQueryResult()
        assert r.entries == []
        assert r.total_matches == 0
        assert r.search_method == "keyword"


class TestLocalKnowledgeProvider(unittest.TestCase):
    """本地知识Provider——JSON文件存储"""

    def setUp(self):
        # 用临时目录避免影响真实知识库
        self._tmpdir = tempfile.mkdtemp()
        self.provider = LocalKnowledgeProvider(project_name="_test_project")
        # 覆盖存储路径到临时目录
        self.provider._base_dir = self._tmpdir
        self.provider.initialize()

    def tearDown(self):
        self.provider.dispose()
        # 清理临时目录
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_initialize_creates_directory(self):
        project_dir = self.provider._project_dir()
        assert os.path.exists(project_dir)

    def test_put_and_get(self):
        entry = KnowledgeEntry(
            type=KnowledgeType.ARCHITECTURE,
            scope=KnowledgeScope.PROJECT,
            title="项目架构",
            content="采用React框架",
        )
        entry_id = self.provider.put(entry)
        retrieved = self.provider.get(entry_id)
        assert retrieved is not None
        assert retrieved.title == "项目架构"
        assert retrieved.type == KnowledgeType.ARCHITECTURE

    def test_put_updates_existing(self):
        entry = KnowledgeEntry(
            type=KnowledgeType.API,
            title="登录API",
            content="POST /api/login",
        )
        entry_id = self.provider.put(entry)
        
        # 更新
        entry.content = "POST /api/v2/login"
        self.provider.put(entry)
        
        retrieved = self.provider.get(entry_id)
        assert retrieved.content == "POST /api/v2/login"

    def test_delete(self):
        entry = KnowledgeEntry(title="临时知识", content="会被删除")
        entry_id = self.provider.put(entry)
        assert self.provider.delete(entry_id) is True
        assert self.provider.get(entry_id) is None

    def test_delete_nonexistent(self):
        assert self.provider.delete("nonexistent-id") is False

    def test_query_by_keyword(self):
        self.provider.put(KnowledgeEntry(
            type=KnowledgeType.ARCHITECTURE,
            title="React架构", content="前端用React",
        ))
        self.provider.put(KnowledgeEntry(
            type=KnowledgeType.CONVENTION,
            title="编码规范", content="用TypeScript",
        ))
        result = self.provider.query(KnowledgeQuery(query="react"))
        assert result.total_matches >= 1
        assert any("React" in e.title for e in result.entries)

    def test_query_with_type_filter(self):
        self.provider.put(KnowledgeEntry(
            type=KnowledgeType.RISK, title="安全风险", content="XSS风险",
        ))
        self.provider.put(KnowledgeEntry(
            type=KnowledgeType.API, title="登录API", content="POST /login",
        ))
        result = self.provider.query(KnowledgeQuery(
            query="login",
            type_filter=KnowledgeType.API,
        ))
        assert all(e.type == KnowledgeType.API for e in result.entries)

    def test_query_with_scope_filter(self):
        self.provider.put(KnowledgeEntry(
            scope=KnowledgeScope.PROJECT, title="项目级知识",
        ))
        self.provider.put(KnowledgeEntry(
            scope=KnowledgeScope.FILE, title="文件级知识",
        ))
        result = self.provider.query(KnowledgeQuery(
            query="",
            scope_filter=KnowledgeScope.FILE,
        ))
        assert all(e.scope == KnowledgeScope.FILE for e in result.entries)

    def test_query_with_limit(self):
        for i in range(5):
            self.provider.put(KnowledgeEntry(
                title=f"知识{i}", content=f"内容{i}",
            ))
        result = self.provider.query(KnowledgeQuery(query="知识", limit=2))
        assert len(result.entries) <= 2

    def test_query_empty_results(self):
        result = self.provider.query(KnowledgeQuery(query="不存在的关键词"))
        assert result.total_matches == 0

    def test_semantic_search_fallback(self):
        """语义搜索降级为关键词搜索"""
        self.provider.put(KnowledgeEntry(
            title="架构知识", content="React框架",
        ))
        result = self.provider.semantic_search("react", limit=5)
        assert result.search_method == "keyword_fallback"

    def test_stats(self):
        self.provider.put(KnowledgeEntry(
            type=KnowledgeType.ARCHITECTURE,
            title="架构1",
            tags=["frontend"],
        ))
        stats = self.provider.stats()
        assert stats["total_entries"] >= 1
        assert "architecture" in stats["types"]
        assert stats["initialized"] is True

    def test_persistence(self):
        """持久化到磁盘后重新加载"""
        entry = KnowledgeEntry(
            type=KnowledgeType.DECISION,
            title="ADR-001",
            content="选择React而非Vue",
            source="human",
        )
        self.provider.put(entry)
        self.provider.build_index()  # 持久化
        
        # 创建新provider,从磁盘加载
        provider2 = LocalKnowledgeProvider(project_name="_test_project")
        provider2._base_dir = self._tmpdir
        provider2.initialize()
        
        retrieved = provider2.get(entry.id)
        assert retrieved is not None
        assert retrieved.title == "ADR-001"
        assert retrieved.source == "human"
        provider2.dispose()

    def test_tags_index(self):
        self.provider.put(KnowledgeEntry(
            title="安全知识", tags=["security", "auth"],
        ))
        self.provider.put(KnowledgeEntry(
            title="测试知识", tags=["testing", "unit-test"],
        ))
        result = self.provider.query(KnowledgeQuery(
            query="",
            tags_filter=["security"],
        ))
        assert len(result.entries) >= 1
        assert any("security" in e.tags for e in result.entries)


class TestNoOpEmbeddingService(unittest.TestCase):
    """空Embedding服务——降级兜底"""

    def test_embed_returns_empty(self):
        svc = NoOpEmbeddingService()
        assert svc.embed("test") == []

    def test_embed_batch_returns_empty(self):
        svc = NoOpEmbeddingService()
        result = svc.embed_batch(["a", "b"])
        assert len(result) == 2
        assert all(v == [] for v in result)

    def test_similarity_returns_zero(self):
        svc = NoOpEmbeddingService()
        assert svc.similarity([1, 2], [1, 2]) == 0.0

    def test_search_similar_returns_empty(self):
        svc = NoOpEmbeddingService()
        assert svc.search_similar([1], {"a": [1]}, 5) == []


class TestKnowledgeContext(unittest.TestCase):
    """Agent上下文注入"""

    def test_inject_to_context(self):
        entries = [
            KnowledgeEntry(type=KnowledgeType.API, title="登录API", content="POST /login"),
            KnowledgeEntry(type=KnowledgeType.RISK, title="XSS风险", content="存在XSS"),
        ]
        query_result = KnowledgeQueryResult(
            entries=entries,
            total_matches=2,
            search_method="keyword",
        )
        ctx = KnowledgeContext(
            relevant_entries=entries,
            query_result=query_result,
        )
        agent_context = {}
        ctx.inject_to_context(agent_context)
        
        assert "knowledge" in agent_context
        assert agent_context["knowledge"]["total"] == 2
        assert len(agent_context["knowledge"]["entries"]) == 2
        assert agent_context["knowledge"]["search_method"] == "keyword"

    def test_empty_context(self):
        ctx = KnowledgeContext()
        agent_context = {}
        ctx.inject_to_context(agent_context)
        assert "knowledge" in agent_context
        assert agent_context["knowledge"]["total"] == 0
        assert agent_context["knowledge"]["search_method"] == "none"


class TestGetKnowledgeProvider(unittest.TestCase):
    """全局单例工厂"""

    def test_get_provider(self):
        # 使用临时项目名避免污染全局
        provider = get_knowledge_provider("_unittest_temp")
        assert isinstance(provider, LocalKnowledgeProvider)
        # 清理
        provider.dispose()


if __name__ == "__main__":
    unittest.main()
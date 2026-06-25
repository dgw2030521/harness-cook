"""
知识管理适配层——从 nextX IKnowledgeProvider/KnowledgeType/KnowledgeScope 提取的设计蓝图

.. warning::
    **实验性模块** - 接口和实现可能在未来版本中变更。
    已在 Phase 3 中与 Learning 模块集成（经验沉淀），但持久化和语义搜索仍不完整。

Harness 统一管控 Agent 的知识访问:
- Agent 可以查询什么知识(10种 KnowledgeType)
- 知识的范围层级(4级 KnowledgeScope: project→module→file→function)
- 知识怎么存储和检索(LocalKnowledgeProvider + JSON文件)
- 语义搜索怎么做(EmbeddingService接口,首期不实现)

nextX 的核心设计模式:
1. KnowledgeType 10种类型 — 从静态结构→动态规则→人为决策→辅助信息
2. KnowledgeScope 4级范围 — project/module/file/function精确定位
3. IKnowledgeProvider 6大能力域 — CRUD+语义搜索+索引管理+云同步+生命周期
4. LocalKnowledgeProvider — SQLite+.ai/目录双轨存储,三层搜索(keyword→embedding→TF-IDF)
5. EmbeddingService Strategy模式 — 单条→批量特化,SHA-256缓存,TF-IDF降级兜底

harness-cook 适配定位(领域适配层):
- 首期只做本地JSON存储(P0-P1)
- Embedding接口定义但不实现(成本高)
- 与learning.py桥接 — ExperienceStore → KnowledgeProvider ✅ 已实现
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger("harness.knowledge")


# ═══════════════════════════════════════════════════════════
#  知识类型——10种,从 nextX KnowledgeType 提取
# ═══════════════════════════════════════════════════════════

class KnowledgeType(Enum):
    """知识类型——Agent可查询的10种知识类别
    
    从静态结构→动态规则→人为决策→辅助信息的完整覆盖:
    - architecture/convention/dependency: 静态结构(项目骨架)
    - api/pattern/risk: 动态规则(行为模式)
    - decision/task: 人为决策(历史选择)
    - test/glossary: 辅助信息(验证+术语)
    """
    ARCHITECTURE = "architecture"  # 项目架构: 目录结构/模块关系/技术栈
    CONVENTION = "convention"      # 编码约定: 命名规则/格式规范/提交规范
    DEPENDENCY = "dependency"      # 依赖关系: 包依赖/服务依赖/数据依赖
    API = "api"                    # API定义: 接口签名/参数/返回值
    PATTERN = "pattern"            # 设计模式: 常见解法/反模式/最佳实践
    RISK = "risk"                  # 风险知识: 安全风险/性能瓶颈/已知问题
    DECISION = "decision"          # 决策记录: ADR(Architecture Decision Record)
    TASK = "task"                  # 任务知识: 历史任务/典型工作流/分工模式
    TEST = "test"                  # 测试知识: 测试策略/覆盖要求/典型测试模式
    GLOSSARY = "glossary"          # 术语表: 项目专有名词/缩写/概念映射


# ═══════════════════════════════════════════════════════════
#  知识范围——4级,从 nextX KnowledgeScope 提取
# ═══════════════════════════════════════════════════════════

class KnowledgeScope(Enum):
    """知识范围——4级粒度
    
    project: 整个项目级(如"项目用React+TypeScript")
    module: 模块级(如"auth模块负责用户认证")
    file: 文件级(如"login.tsx处理登录UI")
    function: 函数级(如"validateEmail()检查邮箱格式")
    """
    PROJECT = "project"
    MODULE = "module"
    FILE = "file"
    FUNCTION = "function"


# ═══════════════════════════════════════════════════════════
#  知识条目——核心数据模型
# ═══════════════════════════════════════════════════════════

@dataclass
class KnowledgeEntry:
    """知识条目——一条结构化的项目知识
    
    从 nextX KnowledgeItem 提取+增强:
    - id: 唯一标识(自动生成SHA-256短hash)
    - type+scope: 分类定位
    - content: 知识正文
    - metadata: 附加信息(source/confidence/tags)
    - timestamps: 创建/更新时间
    """
    id: Optional[str] = None
    type: KnowledgeType = KnowledgeType.ARCHITECTURE
    scope: KnowledgeScope = KnowledgeScope.PROJECT
    title: str = ""
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    confidence: float = 1.0          # 0.0-1.0, 知识可信度
    source: Optional[str] = None     # 知识来源: "human" | "ast" | "llm" | "learning"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def __post_init__(self):
        if self.id is None:
            # 用 type+scope+title 生成稳定ID
            raw = f"{self.type.value}:{self.scope.value}:{self.title}"
            self.id = hashlib.sha256(raw.encode()).hexdigest()[:12]
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if self.updated_at is None:
            self.updated_at = self.created_at

    def matches_query(self, query: str) -> bool:
        """简单关键词匹配——标题+内容+标签"""
        q = query.lower()
        if q in self.title.lower():
            return True
        if q in self.content.lower():
            return True
        for tag in self.tags:
            if q in tag.lower():
                return True
        return False

    def matches_filters(
        self,
        type_filter: Optional[KnowledgeType] = None,
        scope_filter: Optional[KnowledgeScope] = None,
        tags_filter: Optional[List[str]] = None,
        source_filter: Optional[str] = None,
    ) -> bool:
        """多条件过滤"""
        if type_filter and self.type != type_filter:
            return False
        if scope_filter and self.scope != scope_filter:
            return False
        if tags_filter:
            if not any(t in self.tags for t in tags_filter):
                return False
        if source_filter and self.source != source_filter:
            return False
        return True

    def summary(self) -> str:
        """条目概要"""
        return f"[{self.type.value}/{self.scope.value}] {self.title} ({len(self.content)}字)"


# ═══════════════════════════════════════════════════════════
#  查询请求+结果
# ═══════════════════════════════════════════════════════════

@dataclass
class KnowledgeQuery:
    """知识查询请求"""
    query: str                               # 搜索关键词
    type_filter: Optional[KnowledgeType] = None    # 按类型过滤
    scope_filter: Optional[KnowledgeScope] = None  # 按范围过滤
    tags_filter: Optional[List[str]] = None        # 按标签过滤
    source_filter: Optional[str] = None            # 按来源过滤
    limit: int = 20                             # 返回条目上限


@dataclass
class KnowledgeQueryResult:
    """知识查询结果"""
    entries: List[KnowledgeEntry] = field(default_factory=list)
    total_matches: int = 0
    query: str = ""
    search_method: str = "keyword"  # "keyword" | "embedding" | "hybrid"


# ═══════════════════════════════════════════════════════════
#  IKnowledgeProvider — Protocol接口
# ═══════════════════════════════════════════════════════════

class IKnowledgeProvider(Protocol):
    """知识Provider接口——从 nextX IKnowledgeProvider 提取
    
    6大能力域:
    1. CRUD: get/put/delete — 基础存取
    2. 查询: query — 关键词搜索+过滤
    3. 语义搜索: semantic_search — embedding向量搜索(首期降级为keyword)
    4. 索引: build_index/update_index — 知识索引管理
    5. 统计: stats — 知识库概况
    6. 生命周期: initialize/dispose — 初始化+清理
    """
    def get(self, entry_id: str) -> Optional[KnowledgeEntry]: ...
    def put(self, entry: KnowledgeEntry) -> str: ...
    def delete(self, entry_id: str) -> bool: ...
    def query(self, query: KnowledgeQuery) -> KnowledgeQueryResult: ...
    def semantic_search(self, query: str, limit: int) -> KnowledgeQueryResult: ...
    def build_index(self) -> None: ...
    def stats(self) -> Dict[str, Any]: ...
    def initialize(self) -> None: ...
    def dispose(self) -> None: ...


# ═══════════════════════════════════════════════════════════
#  LocalKnowledgeProvider — 本地JSON文件存储
# ═══════════════════════════════════════════════════════════

class LocalKnowledgeProvider:
    """本地知识Provider——JSON文件存储实现

    从 nextX LocalKnowledgeProvider 适配:
    - nextX用SQLite+.ai/目录双轨 → harness-cook首期简化为JSON文件
    - 三层搜索策略: keyword → embedding(降级为keyword) → TF-IDF(暂不实现)
    - 知识目录: ~/.harness/knowledge/{project}/

    存储格式:
    ~/.harness/knowledge/{project}/entries.json — 活跃知识条目(参与context注入)
    ~/.harness/knowledge/{project}/archived.json — 归档知识条目(不注入context,可手动搜索)
    ~/.harness/knowledge/{project}/index.json   — 类型/标签索引(加速查询)

    三层治理机制:
    1. 写入门控: KnowledgeSubscriber 层面筛选(≥3次阈值/架构级/≥0.7置信度)
    2. 去重合并: put() 增量合并(hit_count累计, 按规则名做title, 不重复建条目)
    3. 自动淘汰: evict_stale_entries()(30天未查询→归档, 90天+低频→删除)
    """

    # ── 淘汰默认参数 ──
    EVICT_TTL_DAYS = 30       # 活跃层: 30天未查询→归档
    EVICT_ARCHIVE_TTL_DAYS = 90  # 归档层: 90天+低频→删除
    EVICT_LOW_FREQ_THRESHOLD = 3  # 低频阈值: hit_count < 3

    def __init__(self, project_name: Optional[str] = None, auto_save: bool = True):
        self._project = project_name or "default"
        self._entries: Dict[str, KnowledgeEntry] = {}
        self._archived: Dict[str, KnowledgeEntry] = {}  # 归档层
        self._type_index: Dict[KnowledgeType, List[str]] = {}
        self._tag_index: Dict[str, List[str]] = {}
        self._initialized = False
        self._base_dir = os.path.expanduser("~/.harness/knowledge")
        self._auto_save = auto_save  # put/delete 后自动持久化
    
    def _project_dir(self) -> str:
        return os.path.join(self._base_dir, self._project)
    
    def _entries_path(self) -> str:
        return os.path.join(self._project_dir(), "entries.json")

    def _index_path(self) -> str:
        return os.path.join(self._project_dir(), "index.json")

    def _archived_path(self) -> str:
        """归档层路径"""
        return os.path.join(self._project_dir(), "archived.json")

    def initialize(self) -> None:
        """初始化——从JSON文件加载已有知识(活跃层+归档层)"""
        project_dir = self._project_dir()
        os.makedirs(project_dir, exist_ok=True)

        # 加载活跃层
        entries_path = self._entries_path()
        if os.path.exists(entries_path):
            with open(entries_path, "r") as f:
                data = json.load(f)
            for item in data.get("entries", []):
                entry = KnowledgeEntry(
                    id=item.get("id"),
                    type=KnowledgeType(item.get("type", "architecture")),
                    scope=KnowledgeScope(item.get("scope", "project")),
                    title=item.get("title", ""),
                    content=item.get("content", ""),
                    metadata=item.get("metadata", {}),
                    tags=item.get("tags", []),
                    confidence=item.get("confidence", 1.0),
                    source=item.get("source"),
                    created_at=item.get("created_at"),
                    updated_at=item.get("updated_at"),
                )
                self._entries[entry.id] = entry

        # 加载归档层
        archived_path = self._archived_path()
        if os.path.exists(archived_path):
            with open(archived_path, "r") as f:
                data = json.load(f)
            for item in data.get("entries", []):
                entry = KnowledgeEntry(
                    id=item.get("id"),
                    type=KnowledgeType(item.get("type", "architecture")),
                    scope=KnowledgeScope(item.get("scope", "project")),
                    title=item.get("title", ""),
                    content=item.get("content", ""),
                    metadata=item.get("metadata", {}),
                    tags=item.get("tags", []),
                    confidence=item.get("confidence", 1.0),
                    source=item.get("source"),
                    created_at=item.get("created_at"),
                    updated_at=item.get("updated_at"),
                )
                self._archived[entry.id] = entry

        self._build_internal_index()
        self._initialized = True
        logger.info(f"知识Provider初始化: 加载{len(self._entries)}条活跃知识, {len(self._archived)}条归档知识")
    
    def dispose(self) -> None:
        """清理——持久化到JSON文件"""
        self._save_to_disk()
        self._save_archive()
        self._entries.clear()
        self._archived.clear()
        self._type_index.clear()
        self._tag_index.clear()
        self._initialized = False
    
    def _save_to_disk(self) -> None:
        """保存到磁盘——原子写入(写临时文件→rename,防崩溃半截)"""
        entries_data = {
            "project": self._project,
            "updated_at": datetime.now().isoformat(),
            "entries": [
                {
                    "id": e.id,
                    "type": e.type.value,
                    "scope": e.scope.value,
                    "title": e.title,
                    "content": e.content,
                    "metadata": e.metadata,
                    "tags": e.tags,
                    "confidence": e.confidence,
                    "source": e.source,
                    "created_at": e.created_at,
                    "updated_at": e.updated_at,
                }
                for e in self._entries.values()
            ]
        }
        os.makedirs(self._project_dir(), exist_ok=True)
        
        # 原子写入: 先写临时文件,再rename(POSIX原子操作)
        entries_tmp = self._entries_path() + ".tmp"
        with open(entries_tmp, "w") as f:
            json.dump(entries_data, f, indent=2, ensure_ascii=False)
        os.replace(entries_tmp, self._entries_path())
        
        # 保存索引——同样原子写入
        index_data = {
            "type_index": {t.value: ids for t, ids in self._type_index.items()},
            "tag_index": self._tag_index,
        }
        index_tmp = self._index_path() + ".tmp"
        with open(index_tmp, "w") as f:
            json.dump(index_data, f, indent=2)
        os.replace(index_tmp, self._index_path())

    def _save_archive(self) -> None:
        """保存归档层到磁盘——原子写入"""
        archive_data = {
            "project": self._project,
            "updated_at": datetime.now().isoformat(),
            "entries": [
                {
                    "id": e.id,
                    "type": e.type.value,
                    "scope": e.scope.value,
                    "title": e.title,
                    "content": e.content,
                    "metadata": e.metadata,
                    "tags": e.tags,
                    "confidence": e.confidence,
                    "source": e.source,
                    "created_at": e.created_at,
                    "updated_at": e.updated_at,
                }
                for e in self._archived.values()
            ]
        }
        os.makedirs(self._project_dir(), exist_ok=True)

        archive_tmp = self._archived_path() + ".tmp"
        with open(archive_tmp, "w") as f:
            json.dump(archive_data, f, indent=2, ensure_ascii=False)
        os.replace(archive_tmp, self._archived_path())
    
    def _build_internal_index(self) -> None:
        """构建内部索引——类型+标签加速查询"""
        self._type_index.clear()
        self._tag_index.clear()
        
        for entry_id, entry in self._entries.items():
            # 类型索引
            if entry.type not in self._type_index:
                self._type_index[entry.type] = []
            self._type_index[entry.type].append(entry_id)
            
            # 标签索引
            for tag in entry.tags:
                if tag not in self._tag_index:
                    self._tag_index[tag] = []
                self._tag_index[tag].append(entry_id)
    
    # ── CRUD ──
    
    def get(self, entry_id: str) -> Optional[KnowledgeEntry]:
        """按ID获取知识条目"""
        return self._entries.get(entry_id)
    
    def put(self, entry: KnowledgeEntry, merge: bool = False) -> str:
        """存入知识条目——返回条目ID

        Args:
            entry: 知识条目
            merge: 是否启用去重合并模式
                - False: 直接覆盖（手动添加、种子注入等确定性写入）
                - True:  增量合并（KnowledgeSubscriber、LearningEngine 等自动沉淀）
                    已有条目 → hit_count+1, 追加事件摘要, 合并 tags, 更新 confidence
                    新条目   → hit_count=1, 初始 confidence 根据来源设定

        去重合并逻辑（merge=True 时）：
            1. 已有同ID条目 → 不覆盖content，而是增量合并metadata
            2. hit_count 累计：每触发一次 +1
            3. hit_count ≥ 3 → confidence 升级到 0.8（从初始 0.5）
            4. source_events 追加：保留最近5条触发事件摘要
            5. tags 合并：去重追加
        """
        existing = self._entries.get(entry.id)

        if merge and existing:
            # ── 增量合并：不覆盖，只追加 metadata ──
            hit_count = existing.metadata.get("hit_count", 1) + 1
            existing.metadata["hit_count"] = hit_count

            # 追加事件摘要（保留最近5条）
            source_events = existing.metadata.setdefault("source_events", [])
            event_summary = entry.metadata.get("event_summary", "")
            if event_summary:
                source_events.append(event_summary)
                if len(source_events) > 5:
                    source_events = source_events[-5:]
                    existing.metadata["source_events"] = source_events

            # 合并 tags（去重追加）
            existing_tags = set(existing.tags)
            for tag in entry.tags:
                if tag not in existing_tags:
                    existing.tags.append(tag)

            # hit_count ≥ 3 → confidence 升级
            if hit_count >= 3:
                existing.confidence = max(existing.confidence, 0.8)

            existing.updated_at = datetime.now().isoformat()

            # 更新索引
            self._build_internal_index()

            # 自动持久化
            if self._auto_save:
                self._save_to_disk()

            return existing.id

        else:
            # ── 直接写入（手动/种子/首次自动） ──
            # 为自动沉淀的条目初始化 hit_count 和 last_queried_at
            if merge and not existing:
                entry.metadata.setdefault("hit_count", 1)
                entry.metadata.setdefault("last_queried_at", entry.created_at)
                entry.metadata.setdefault("source_events", [])
                # 自动沉淀初始 confidence 根据来源设定
                if entry.confidence == 1.0 and entry.source in (
                    "compliance", "guardrail", "gate", "learning"
                ):
                    entry.confidence = 0.5  # 首次自动沉淀，需要累积验证

            if existing:
                entry.updated_at = datetime.now().isoformat()
            self._entries[entry.id] = entry

            # 更新索引
            self._build_internal_index()

            # 自动持久化
            if self._auto_save:
                self._save_to_disk()

            return entry.id
    
    def delete(self, entry_id: str) -> bool:
        """删除知识条目"""
        if entry_id not in self._entries:
            return False
        del self._entries[entry_id]
        self._build_internal_index()

        # 自动持久化
        if self._auto_save:
            self._save_to_disk()

        return True
    
    # ── 查询 ──
    
    def query(self, query: KnowledgeQuery) -> KnowledgeQueryResult:
        """关键词查询——三层搜索策略的第一层
        
        1. 先用索引过滤(type/tags/scope/source)
        2. 再在过滤结果中关键词匹配
        3. 返回top N
        """
        candidates = list(self._entries.values())
        
        # 索引加速过滤
        if query.type_filter:
            candidate_ids = set(self._type_index.get(query.type_filter, []))
            candidates = [e for e in candidates if e.id in candidate_ids]
        
        if query.tags_filter:
            tag_ids = set()
            for tag in query.tags_filter:
                tag_ids.update(self._tag_index.get(tag, []))
            candidates = [e for e in candidates if e.id in tag_ids]
        
        # 逐条过滤(scope/source)
        filtered = [
            e for e in candidates
            if e.matches_filters(
                type_filter=None,  # type已通过索引过滤
                scope_filter=query.scope_filter,
                source_filter=query.source_filter,
            )
        ]
        
        # 关键词匹配(空query=全量返回)
        if query.query:
            matched = [e for e in filtered if e.matches_query(query.query)]
        else:
            matched = filtered  # 无关键词=返回所有过滤结果
        
        # 截断
        total = len(matched)
        result_entries = matched[:query.limit]

        # ── 第三层治理: 查询时更新 last_queried_at（淘汰机制的时间戳来源） ──
        now_iso = datetime.now().isoformat()
        for entry in result_entries:
            entry.metadata["last_queried_at"] = now_iso
            entry.updated_at = now_iso

        # 批量更新后持久化（避免逐条IO）
        if result_entries and self._auto_save:
            self._save_to_disk()

        return KnowledgeQueryResult(
            entries=result_entries,
            total_matches=total,
            query=query.query,
            search_method="keyword",
        )
    
    def semantic_search(self, query: str, limit: int = 10) -> KnowledgeQueryResult:
        """语义搜索——TF-IDF 向量化 + 余弦相似度

        本地语义搜索，无需外部 API：
        1. 对所有条目的 title+content 构建 TF-IDF 向量
        2. 对查询文本也构建 TF-IDF 向量
        3. 计算余弦相似度，返回 top N

        如果条目数 < 3，降级为关键词搜索（TF-IDF 在小样本上意义不大）。
        """
        if len(self._entries) < 3:
            logger.debug(f"语义搜索降级为关键词搜索（条目数={len(self._entries)}）: '{query}'")
            kw_result = self.query(KnowledgeQuery(query=query, limit=limit))
            kw_result.search_method = "keyword_fallback"
            return kw_result

        try:
            engine = _TfIdfSearchEngine(self._entries)
            results = engine.search(query, limit=limit)

            if not results:
                # TF-IDF 无命中 → 降级到关键词
                kw_result = self.query(KnowledgeQuery(query=query, limit=limit))
                kw_result.search_method = "keyword_fallback"
                return kw_result

            # ── 更新 last_queried_at（淘汰机制） ──
            now_iso = datetime.now().isoformat()
            for entry in results:
                entry.metadata["last_queried_at"] = now_iso
                entry.updated_at = now_iso
            if results and self._auto_save:
                self._save_to_disk()

            return KnowledgeQueryResult(
                entries=results,
                total_matches=len(results),
                query=query,
                search_method="tfidf",
            )
        except Exception as e:
            logger.warning(f"TF-IDF 语义搜索异常，降级为关键词: {e}")
            kw_result = self.query(KnowledgeQuery(query=query, limit=limit))
            kw_result.search_method = "keyword_fallback"
            return kw_result
    
    # ── 索引 ──

    def build_index(self) -> None:
        """构建索引——持久化到磁盘"""
        self._build_internal_index()
        self._save_to_disk()
        logger.info(f"知识索引重建: {len(self._entries)}条活跃, {len(self._archived)}条归档, {len(self._type_index)}种类型, {len(self._tag_index)}个标签")

    def update_index(self, entry_id: str) -> None:
        """更新单条索引"""
        entry = self._entries.get(entry_id)
        if entry:
            self._build_internal_index()

    # ── 归档层 ──

    def get_archived(self, entry_id: str) -> Optional[KnowledgeEntry]:
        """从归档层获取条目"""
        return self._archived.get(entry_id)

    def list_archived(self, limit: int = 20) -> List[KnowledgeEntry]:
        """列出归档层条目（不参与context注入，仅供手动搜索）"""
        return list(self._archived.values())[:limit]

    def restore_from_archive(self, entry_id: str) -> bool:
        """从归档层恢复条目到活跃层"""
        entry = self._archived.get(entry_id)
        if not entry:
            return False
        # 恢复到活跃层
        entry.metadata["last_queried_at"] = datetime.now().isoformat()
        entry.confidence = max(entry.confidence, 0.5)
        self._entries[entry.id] = entry
        del self._archived[entry_id]
        self._build_internal_index()
        if self._auto_save:
            self._save_to_disk()
            self._save_archive()
        logger.info(f"知识条目恢复: {entry_id} 从归档层恢复到活跃层")
        return True

    # ── 第三层治理：自动淘汰 ──

    def evict_stale_entries(
        self,
        ttl_days: Optional[int] = None,
        archive_ttl_days: Optional[int] = None,
        low_freq_threshold: Optional[int] = None,
    ) -> Dict[str, Any]:
        """淘汰不活跃的知识条目——三层治理的核心机制

        活跃层 → 归档层: last_queried_at 超过 ttl_days (默认30天)
        归档层 → 删除: 超过 archive_ttl_days (默认90天) 且 hit_count < low_freq_threshold (默认3)

        Returns:
            {"archived": 归档数, "deleted": 删除数, "active": 剩余活跃数}
        """
        ttl = ttl_days or self.EVICT_TTL_DAYS
        archive_ttl = archive_ttl_days or self.EVICT_ARCHIVE_TTL_DAYS
        low_freq = low_freq_threshold or self.EVICT_LOW_FREQ_THRESHOLD

        now = datetime.now()
        archived_count = 0
        deleted_count = 0

        # ── 活跃层 → 归档层 ──
        to_archive = []
        for entry_id, entry in list(self._entries.items()):
            last_queried = entry.metadata.get("last_queried_at", entry.updated_at)
            if last_queried:
                try:
                    days_inactive = (now - datetime.fromisoformat(last_queried)).days
                except (ValueError, TypeError):
                    continue
                if days_inactive > ttl:
                    to_archive.append(entry_id)

        for entry_id in to_archive:
            entry = self._entries.pop(entry_id)
            self._archived[entry.id] = entry
            archived_count += 1
            logger.debug(f"知识归档: {entry_id} (inactive {ttl}+ days)")

        # ── 归档层 → 删除 ──
        to_delete = []
        for entry_id, entry in list(self._archived.items()):
            last_queried = entry.metadata.get("last_queried_at", entry.updated_at)
            hit_count = entry.metadata.get("hit_count", 1)
            if last_queried:
                try:
                    days_inactive = (now - datetime.fromisoformat(last_queried)).days
                except (ValueError, TypeError):
                    continue
                if days_inactive > archive_ttl and hit_count < low_freq:
                    to_delete.append(entry_id)

        for entry_id in to_delete:
            del self._archived[entry_id]
            deleted_count += 1
            logger.debug(f"知识删除: {entry_id} (archived {archive_ttl}+ days, hit_count={hit_count})")

        # 重建索引 + 持久化
        if to_archive or to_delete:
            self._build_internal_index()
            if self._auto_save:
                self._save_to_disk()
                self._save_archive()

        result = {
            "archived": archived_count,
            "deleted": deleted_count,
            "active": len(self._entries),
            "archived_total": len(self._archived),
        }
        if archived_count or deleted_count:
            logger.info(f"知识淘汰: 归档{archived_count}条, 删除{deleted_count}条, 剩余活跃{len(self._entries)}条")
        return result

    # ── 统计 ──

    def stats(self) -> Dict[str, Any]:
        """知识库统计——活跃层+归档层"""
        type_counts = {}
        for t, ids in self._type_index.items():
            type_counts[t.value] = len(ids)

        # 归档层类型分布
        archived_type_counts = {}
        for entry in self._archived.values():
            t = entry.type.value
            archived_type_counts[t] = archived_type_counts.get(t, 0) + 1

        # 来源分布
        source_counts = {}
        for entry in self._entries.values():
            s = entry.source or "unknown"
            source_counts[s] = source_counts.get(s, 0) + 1

        # 高频条目（hit_count ≥ 3）
        high_freq = sum(
            1 for e in self._entries.values()
            if e.metadata.get("hit_count", 1) >= 3
        )

        return {
            "total_entries": len(self._entries),
            "types": type_counts,
            "tags": len(self._tag_index),
            "project": self._project,
            "initialized": self._initialized,
            "archived_total": len(self._archived),
            "archived_types": archived_type_counts,
            "sources": source_counts,
            "high_freq_entries": high_freq,
        }


# ═══════════════════════════════════════════════════════════
#  EmbeddingService — Protocol接口(首期不实现)
# ═══════════════════════════════════════════════════════════

class IEmbeddingService(Protocol):
    """Embedding服务接口——从 nextX EmbeddingService 提取
    
    首期只定义接口,不实现:
    - 单条embedding → 向量
    - 批量embedding → 多向量
    - 向量相似度搜索 → top N
    
    未来实现选项:
    - OpenAI embedding API (nextX已有实现)
    - 本地sentence-transformers
    - 百炼embedding API
    """
    def embed(self, text: str) -> List[float]: ...
    def embed_batch(self, texts: List[str]) -> List[List[float]]: ...
    def similarity(self, vec_a: List[float], vec_b: List[float]) -> float: ...
    def search_similar(self, query_vec: List[float], candidates: Dict[str, List[float]], limit: int) -> List[str]: ...


class NoOpEmbeddingService:
    """空实现——首期降级兜底
    
    所有embedding请求返回空向量,
    semantic_search自动降级为keyword搜索
    """
    
    def embed(self, text: str) -> List[float]:
        """返回空向量"""
        return []
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """返回空向量列表"""
        return [[] for _ in texts]
    
    def similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        """返回0相似度"""
        return 0.0
    
    def search_similar(self, query_vec: List[float], candidates: Dict[str, List[float]], limit: int) -> List[str]:
        """返回空结果"""
        return []


# ═══════════════════════════════════════════════════════════
#  知识注入——AgentExecutionContext扩展(Phase 1桥接)
# ═══════════════════════════════════════════════════════════

@dataclass
class KnowledgeContext:
    """Agent执行时的知识上下文——注入到Agent的context参数
    
    Phase 1的@harness_agent装饰器给Agent传context: dict,
    KnowledgeContext提供结构化的知识注入方式:
    
    用法:
        context["knowledge"] = KnowledgeContext(
            provider=local_provider,
            relevant_entries=[...],
            query_result=result,
        )
    """
    provider: Optional[LocalKnowledgeProvider] = None
    relevant_entries: List[KnowledgeEntry] = field(default_factory=list)
    query_result: Optional[KnowledgeQueryResult] = None
    
    def inject_to_context(self, context: Dict[str, Any]) -> None:
        """将知识注入到Agent的context dict"""
        context["knowledge"] = {
            "entries": [
                {
                    "type": e.type.value,
                    "scope": e.scope.value,
                    "title": e.title,
                    "content": e.content,
                    "confidence": e.confidence,
                    "tags": e.tags,
                }
                for e in self.relevant_entries
            ],
            "total": len(self.relevant_entries),
            "search_method": self.query_result.search_method if self.query_result else "none",
        }


# ═══════════════════════════════════════════════════════════
#  单例工厂
# ═══════════════════════════════════════════════════════════

_global_providers: Dict[str, LocalKnowledgeProvider] = {}


def get_knowledge_provider(project_name: Optional[str] = None) -> LocalKnowledgeProvider:
    """获取知识Provider(每个project独立实例)"""
    global _global_providers
    key = project_name or "default"
    if key not in _global_providers:
        _global_providers[key] = LocalKnowledgeProvider(project_name)
        _global_providers[key].initialize()
    return _global_providers[key]


# ═══════════════════════════════════════════════════════════
#  TF-IDF 语义搜索引擎
# ═══════════════════════════════════════════════════════════

import math
import re


class _TfIdfSearchEngine:
    """
    本地 TF-IDF 语义搜索引擎

    流程：
      1. 对所有条目的 title + content 分词
      2. 计算 TF-IDF 向量（TF: 词频, IDF: 逆文档频率）
      3. 对查询文本同样分词 + 向量化
      4. 余弦相似度排序，返回 top N

    中文分词：简单的字符级/词语级混合分词（无需 jieba 等外部依赖）
    """

    def __init__(self, entries: Dict[str, KnowledgeEntry]):
        self._entries = entries
        self._docs: Dict[str, list[str]] = {}  # entry_id → tokens
        self._idf: Dict[str, float] = {}       # token → IDF 值
        self._vectors: Dict[str, Dict[str, float]] = {}  # entry_id → TF-IDF 向量

        self._build()

    def _tokenize(self, text: str) -> list[str]:
        """
        混合分词：提取中文词组 + 英文单词

        策略：
          - 英文：按空格/标点分词，转小写
          - 中文：2-4 字的 n-gram（无需词典）
          - 过滤停用词和短 token
        """
        tokens: list[str] = []

        # 英文单词
        en_words = re.findall(r'[a-zA-Z][a-zA-Z0-9_]*', text)
        tokens.extend(w.lower() for w in en_words)

        # 中文 n-gram（2-4 字）
        cn_chars = re.findall(r'[一-鿿]+', text)
        for segment in cn_chars:
            for n in (2, 3, 4):
                for i in range(len(segment) - n + 1):
                    tokens.append(segment[i:i + n])

        # 过滤：去掉单字符 token
        return [t for t in tokens if len(t) >= 2]

    def _build(self) -> None:
        """构建 TF-IDF 索引"""
        # 1. 分词
        for entry_id, entry in self._entries.items():
            text = f"{entry.title} {entry.content}"
            self._docs[entry_id] = self._tokenize(text)

        # 2. 计算 IDF
        total_docs = len(self._docs)
        doc_freq: Dict[str, int] = {}
        for tokens in self._docs.values():
            unique_tokens = set(tokens)
            for token in unique_tokens:
                doc_freq[token] = doc_freq.get(token, 0) + 1

        for token, freq in doc_freq.items():
            self._idf[token] = math.log((total_docs + 1) / (freq + 1)) + 1  # 平滑

        # 3. 计算 TF-IDF 向量
        for entry_id, tokens in self._docs.items():
            tf: Dict[str, float] = {}
            for token in tokens:
                tf[token] = tf.get(token, 0) + 1
            # 归一化 TF
            max_tf = max(tf.values()) if tf else 1
            vector: Dict[str, float] = {}
            for token, count in tf.items():
                vector[token] = (count / max_tf) * self._idf.get(token, 1.0)
            self._vectors[entry_id] = vector

    def _cosine_similarity(self, v1: Dict[str, float], v2: Dict[str, float]) -> float:
        """计算两个稀疏向量的余弦相似度"""
        common_keys = set(v1.keys()) & set(v2.keys())
        if not common_keys:
            return 0.0

        dot = sum(v1[k] * v2[k] for k in common_keys)
        norm1 = math.sqrt(sum(v ** 2 for v in v1.values()))
        norm2 = math.sqrt(sum(v ** 2 for v in v2.values()))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot / (norm1 * norm2)

    def search(self, query: str, limit: int = 10) -> list[KnowledgeEntry]:
        """执行语义搜索，返回相似度最高的条目"""
        # 查询向量化
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        # 计算查询 TF
        tf: Dict[str, float] = {}
        for token in query_tokens:
            tf[token] = tf.get(token, 0) + 1
        max_tf = max(tf.values()) if tf else 1
        query_vector: Dict[str, float] = {}
        for token, count in tf.items():
            query_vector[token] = (count / max_tf) * self._idf.get(token, 1.0)

        # 计算相似度
        scores: list[tuple[str, float]] = []
        for entry_id, doc_vector in self._vectors.items():
            sim = self._cosine_similarity(query_vector, doc_vector)
            if sim > 0:
                scores.append((entry_id, sim))

        # 排序
        scores.sort(key=lambda x: x[1], reverse=True)

        # 返回 top N
        results = []
        for entry_id, score in scores[:limit]:
            entry = self._entries.get(entry_id)
            if entry:
                results.append(entry)

        return results


# ═══════════════════════════════════════════════════════════
#  S-4：Insight → Rule 激活机制
# ═══════════════════════════════════════════════════════════

@dataclass
class InsightActivation:
    """Insight → RulePack 激活映射（S-4）

    记录哪个 Insight 条目被激活为哪条 ComplianceRule，
    以便撤销时能追踪原始 Insight 并卸载对应的 RulePack。
    """
    insight_id: str                # 原始 Insight 的 KnowledgeEntry.id
    rule_pack_name: str            # 激活后的 RulePack 名称（格式：insight_{insight_id}）
    rule_id: str                   # 激活后的 ComplianceRule.id
    activated_at: str              # 激活时间戳
    insight_title: str             # Insight 标题（便于展示）
    insight_pattern_type: str      # 原始 pattern_type（antipattern/risk/architecture）
    severity: str                  # 激活时选择的严重级别

    def summary(self) -> str:
        """激活记录概要"""
        return f"Insight '{self.insight_title}' → RulePack '{self.rule_pack_name}' (severity={self.severity})"


class InsightActivationStore:
    """S-4 激活记录存储——追踪 Insight→RulePack 的映射关系

    激活记录持久化到 ~/.harness/knowledge/{project}/activations.json，
    与知识条目在同一目录（项目级自包含）。

    用法:
        store = InsightActivationStore(project_name="my-project")
        activation = store.activate(insight_entry, severity="high")
        store.deactivate(activation.insight_id)
    """

    DEFAULT_BASE_DIR = os.path.expanduser("~/.harness/knowledge")

    def __init__(self, project_name: Optional[str] = None, base_dir: Optional[str] = None):
        self._project = project_name or "default"
        self._activations: Dict[str, InsightActivation] = {}
        self._base_dir = base_dir or self.DEFAULT_BASE_DIR
        self._initialized = False

    def _project_dir(self) -> str:
        return os.path.join(self._base_dir, self._project)

    def _activations_path(self) -> str:
        return os.path.join(self._project_dir(), "activations.json")

    def initialize(self) -> None:
        """从 JSON 文件加载已有激活记录"""
        path = self._activations_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data.get("activations", []):
                    activation = InsightActivation(
                        insight_id=item["insight_id"],
                        rule_pack_name=item["rule_pack_name"],
                        rule_id=item["rule_id"],
                        activated_at=item["activated_at"],
                        insight_title=item.get("insight_title", ""),
                        insight_pattern_type=item.get("insight_pattern_type", ""),
                        severity=item.get("severity", "medium"),
                    )
                    self._activations[activation.insight_id] = activation
            except Exception as e:
                logger.warning(f"Failed to load activation records: {e}")
        self._initialized = True

    def _save(self) -> None:
        """持久化激活记录到 JSON"""
        os.makedirs(self._project_dir(), exist_ok=True)
        data = {
            "activations": [
                {
                    "insight_id": a.insight_id,
                    "rule_pack_name": a.rule_pack_name,
                    "rule_id": a.rule_id,
                    "activated_at": a.activated_at,
                    "insight_title": a.insight_title,
                    "insight_pattern_type": a.insight_pattern_type,
                    "severity": a.severity,
                }
                for a in self._activations.values()
            ]
        }
        with open(self._activations_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def activate(
        self,
        insight_entry: KnowledgeEntry,
        severity: str = "medium",
    ) -> InsightActivation:
        """将 Insight 激活为 ComplianceRule

        Args:
            insight_entry: 知识库中的 Insight 条目
            severity: 严重级别（critical/high/medium/low）

        Returns:
            激活映射记录
        """
        insight_id = insight_entry.id
        rule_pack_name = f"insight_{insight_id}"
        rule_id = f"insight_rule_{insight_id}"

        activation = InsightActivation(
            insight_id=insight_id,
            rule_pack_name=rule_pack_name,
            rule_id=rule_id,
            activated_at=datetime.now().isoformat(),
            insight_title=insight_entry.title,
            insight_pattern_type=insight_entry.metadata.get("pattern_type", "unknown"),
            severity=severity,
        )

        self._activations[insight_id] = activation
        self._save()
        logger.info(f"S-4: Activated insight '{insight_entry.title}' → RulePack '{rule_pack_name}'")
        return activation

    def deactivate(self, insight_id: str) -> Optional[InsightActivation]:
        """撤销 Insight → RulePack 的激活

        Args:
            insight_id: Insight 的 KnowledgeEntry.id

        Returns:
            被撤销的激活记录（None = 该 Insight 未被激活）
        """
        activation = self._activations.pop(insight_id, None)
        if activation:
            self._save()
            logger.info(f"S-4: Deactivated insight '{activation.insight_title}' → removed RulePack '{activation.rule_pack_name}'")
        return activation

    def get_activation(self, insight_id: str) -> Optional[InsightActivation]:
        """查询 Insight 的激活状态"""
        if not self._initialized:
            self.initialize()
        return self._activations.get(insight_id)

    def list_activations(self) -> List[InsightActivation]:
        """列出所有激活记录"""
        if not self._initialized:
            self.initialize()
        return list(self._activations.values())

    def is_activated(self, insight_id: str) -> bool:
        """检查 Insight 是否已被激活"""
        if not self._initialized:
            self.initialize()
        return insight_id in self._activations


def insight_to_rule_pack(
    insight_entry: KnowledgeEntry,
    activation: InsightActivation,
) -> "RulePack":
    """将 Insight 转换为 ComplianceRule + RulePack

    转换逻辑：
      - Insight.title → ComplianceRule.description
      - Insight.content → ComplianceRule.pattern（作为检查逻辑描述）
      - Insight.metadata.remediation → ComplianceRule.remediation
      - Insight.metadata.pattern_type → category 映射
      - Insight.confidence → severity 映射（如果用户未指定）

    Args:
        insight_entry: 原始 Insight 知识条目
        activation: 激活映射记录

    Returns:
        可加载到 ComplianceEngine 的 RulePack
    """
    from harness.types import ComplianceRule, ComplianceCategory

    # ── pattern_type → category 映射 ──
    pattern_type = activation.insight_pattern_type
    if pattern_type == "risk":
        category = ComplianceCategory.SECURITY
    elif pattern_type == "architecture":
        category = ComplianceCategory.ARCHITECTURE
    else:
        category = ComplianceCategory.STYLE  # antipattern → style

    # ── 构建 ComplianceRule ──
    rule = ComplianceRule(
        id=activation.rule_id,
        category=category,
        pattern=insight_entry.content or insight_entry.title,  # 检查逻辑描述
        severity=activation.severity,
        description=insight_entry.title,
        remediation=insight_entry.metadata.get("remediation", ""),
        auto_fixable=False,  # Insight 激活的规则默认不可自动修复
        languages=insight_entry.metadata.get("languages", []),
        matcher_type="regex",  # 默认用 regex matcher
        matcher_config=insight_entry.metadata.get("matcher_config", {}),
    )

    # ── 构建 RulePack ──
    from harness.compliance_engine import RulePack
    pack = RulePack(
        name=activation.rule_pack_name,
        category=category,
        rules=[rule],
    )

    return pack
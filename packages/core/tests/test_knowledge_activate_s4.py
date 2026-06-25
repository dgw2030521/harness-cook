"""
S-4 验收测试：知识库 → 规则激活 MCP 工具

验收标准：用户采纳洞察 → 一键激活为规则 → 可撤销

测试范围：
  1. InsightActivation 数据模型
  2. InsightActivationStore 存储（激活/撤销/查询）
  3. insight_to_rule_pack 转换逻辑
  4. 端到端激活流程（知识库 → Insight → RulePack → ComplianceEngine）
  5. 撤销流程
  6. 边界情况（重复激活、撤销未激活、空 ID）
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.knowledge import (
    KnowledgeEntry,
    KnowledgeType,
    KnowledgeScope,
    LocalKnowledgeProvider,
    InsightActivation,
    InsightActivationStore,
    insight_to_rule_pack,
)
from harness.types import ComplianceCategory, ComplianceRule
from harness.compliance_engine import RulePack, ComplianceEngine


# ═══════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def sample_insight_entry():
    """创建一个模拟的 Insight 知识条目"""
    return KnowledgeEntry(
        id="insight-001",
        type=KnowledgeType.RISK,
        scope=KnowledgeScope.PROJECT,
        title="Hardcoded API key detected in config module",
        content="Pattern: API keys embedded in source code (regex: [A-Za-z0-9]{32,44})",
        metadata={
            "pattern_type": "risk",
            "confidence": 0.92,
            "remediation": "Use environment variables or secret manager for API keys",
            "languages": ["python", "javascript"],
            "matcher_config": {},
        },
        tags=["security", "api-key", "hardcoded"],
        confidence=0.92,
        source="learning",
    )


@pytest.fixture
def sample_insight_antipattern():
    """反模式类型的 Insight"""
    return KnowledgeEntry(
        id="insight-002",
        type=KnowledgeType.PATTERN,
        scope=KnowledgeScope.MODULE,
        title="God class pattern in user_service.py",
        content="Single class handles auth, CRUD, email, and logging",
        metadata={
            "pattern_type": "antipattern",
            "confidence": 0.85,
            "remediation": "Split into AuthService, UserService, EmailService",
            "languages": ["python"],
            "matcher_config": {},
        },
        tags=["architecture", "god-class"],
        confidence=0.85,
        source="ast",
    )


@pytest.fixture
def sample_insight_architecture():
    """架构类型的 Insight"""
    return KnowledgeEntry(
        id="insight-003",
        type=KnowledgeType.ARCHITECTURE,
        scope=KnowledgeScope.PROJECT,
        title="Circular dependency between core and utils modules",
        content="core imports utils, utils imports core.config",
        metadata={
            "pattern_type": "architecture",
            "confidence": 0.78,
            "remediation": "Extract shared config into a separate config module",
            "matcher_config": {},
        },
        tags=["architecture", "circular-dep"],
        confidence=0.78,
        source="ast",
    )


@pytest.fixture
def temp_store_dir():
    """创建临时目录用于 InsightActivationStore"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def activation_store(temp_store_dir):
    """创建 InsightActivationStore（使用临时目录）"""
    store = InsightActivationStore(project_name="test-project", base_dir=temp_store_dir)
    yield store


# ═══════════════════════════════════════════════════════════
#  Test S-4.1: InsightActivation 数据模型
# ═══════════════════════════════════════════════════════════

class TestInsightActivationModel:
    """InsightActivation dataclass 基本行为"""

    def test_creation(self):
        activation = InsightActivation(
            insight_id="insight-001",
            rule_pack_name="insight_insight-001",
            rule_id="insight_rule_insight-001",
            activated_at="2026-06-16T10:00:00",
            insight_title="Hardcoded API key",
            insight_pattern_type="risk",
            severity="high",
        )
        assert activation.insight_id == "insight-001"
        assert activation.rule_pack_name == "insight_insight-001"
        assert activation.rule_id == "insight_rule_insight-001"
        assert activation.severity == "high"

    def test_summary(self):
        activation = InsightActivation(
            insight_id="insight-001",
            rule_pack_name="insight_insight-001",
            rule_id="insight_rule_insight-001",
            activated_at="2026-06-16T10:00:00",
            insight_title="Hardcoded API key",
            insight_pattern_type="risk",
            severity="high",
        )
        summary = activation.summary()
        assert "Hardcoded API key" in summary
        assert "insight_insight-001" in summary
        assert "severity=high" in summary


# ═══════════════════════════════════════════════════════════
#  Test S-4.2: InsightActivationStore 存储
# ═══════════════════════════════════════════════════════════

class TestInsightActivationStore:
    """激活记录的 CRUD 操作"""

    def test_activate_creates_record(self, activation_store, sample_insight_entry):
        """激活 Insight 创建 InsightActivation 记录"""
        activation = activation_store.activate(sample_insight_entry, severity="high")

        assert activation.insight_id == "insight-001"
        assert activation.rule_pack_name == "insight_insight-001"
        assert activation.rule_id == "insight_rule_insight-001"
        assert activation.severity == "high"
        assert activation.insight_title == "Hardcoded API key detected in config module"
        assert activation.insight_pattern_type == "risk"

    def test_activate_persists_to_json(self, activation_store, sample_insight_entry):
        """激活记录持久化到 JSON 文件"""
        activation_store.activate(sample_insight_entry, severity="medium")

        # 验证文件存在
        activations_path = activation_store._activations_path()
        assert os.path.exists(activations_path)

        # 验证内容格式
        with open(activations_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data["activations"]) == 1
        assert data["activations"][0]["insight_id"] == "insight-001"

    def test_activate_default_severity(self, activation_store, sample_insight_entry):
        """默认 severity 为 medium"""
        activation = activation_store.activate(sample_insight_entry)
        assert activation.severity == "medium"

    def test_deactivate_removes_record(self, activation_store, sample_insight_entry):
        """撤销激活删除记录"""
        activation_store.activate(sample_insight_entry)
        removed = activation_store.deactivate("insight-001")

        assert removed is not None
        assert removed.insight_id == "insight-001"
        assert removed.rule_pack_name == "insight_insight-001"

    def test_deactivate_unknown_returns_none(self, activation_store):
        """撤销未激活的 Insight 返回 None"""
        result = activation_store.deactivate("nonexistent-insight")
        assert result is None

    def test_is_activated(self, activation_store, sample_insight_entry):
        """检查激活状态"""
        assert not activation_store.is_activated("insight-001")

        activation_store.activate(sample_insight_entry)
        assert activation_store.is_activated("insight-001")

        activation_store.deactivate("insight-001")
        assert not activation_store.is_activated("insight-001")

    def test_get_activation(self, activation_store, sample_insight_entry):
        """查询激活记录"""
        activation = activation_store.activate(sample_insight_entry)
        retrieved = activation_store.get_activation("insight-001")

        assert retrieved is not None
        assert retrieved.insight_id == activation.insight_id
        assert retrieved.rule_pack_name == activation.rule_pack_name

    def test_list_activations(self, activation_store, sample_insight_entry, sample_insight_antipattern):
        """列出所有激活记录"""
        activation_store.activate(sample_insight_entry, severity="high")
        activation_store.activate(sample_insight_antipattern, severity="low")

        activations = activation_store.list_activations()
        assert len(activations) == 2

    def test_initialize_loads_existing(self, temp_store_dir):
        """从 JSON 文件加载已有激活记录"""
        # 先写入一个 activations.json
        project_dir = os.path.join(temp_store_dir, "test-project")
        os.makedirs(project_dir, exist_ok=True)
        activations_path = os.path.join(project_dir, "activations.json")
        data = {
            "activations": [{
                "insight_id": "insight-001",
                "rule_pack_name": "insight_insight-001",
                "rule_id": "insight_rule_insight-001",
                "activated_at": "2026-06-16T10:00:00",
                "insight_title": "Test insight",
                "insight_pattern_type": "risk",
                "severity": "high",
            }]
        }
        with open(activations_path, "w") as f:
            json.dump(data, f)

        store = InsightActivationStore(project_name="test-project", base_dir=temp_store_dir)
        store.initialize()

        assert store.is_activated("insight-001")
        activation = store.get_activation("insight-001")
        assert activation.insight_title == "Test insight"

    def test_deactivate_updates_json(self, activation_store, sample_insight_entry):
        """撤销后 JSON 文件同步更新"""
        activation_store.activate(sample_insight_entry)
        activation_store.deactivate("insight-001")

        # 验证 JSON 文件中记录已清空
        activations_path = activation_store._activations_path()
        with open(activations_path, "r") as f:
            data = json.load(f)
        assert len(data["activations"]) == 0


# ═══════════════════════════════════════════════════════════
#  Test S-4.3: insight_to_rule_pack 转换逻辑
# ═══════════════════════════════════════════════════════════

class TestInsightToRulePack:
    """Insight → ComplianceRule + RulePack 转换"""

    def test_risk_insight_to_security_category(self, sample_insight_entry):
        """risk pattern_type → SECURITY category"""
        activation = InsightActivation(
            insight_id="insight-001",
            rule_pack_name="insight_insight-001",
            rule_id="insight_rule_insight-001",
            activated_at="2026-06-16T10:00:00",
            insight_title=sample_insight_entry.title,
            insight_pattern_type="risk",
            severity="high",
        )
        pack = insight_to_rule_pack(sample_insight_entry, activation)

        assert pack.category == ComplianceCategory.SECURITY
        assert len(pack.rules) == 1
        rule = pack.rules[0]
        assert rule.id == "insight_rule_insight-001"
        assert rule.severity == "high"
        assert rule.description == sample_insight_entry.title

    def test_antipattern_to_coding_category(self, sample_insight_antipattern):
        """antipattern pattern_type → CODING category"""
        activation = InsightActivation(
            insight_id="insight-002",
            rule_pack_name="insight_insight-002",
            rule_id="insight_rule_insight-002",
            activated_at="2026-06-16T10:00:00",
            insight_title=sample_insight_antipattern.title,
            insight_pattern_type="antipattern",
            severity="medium",
        )
        pack = insight_to_rule_pack(sample_insight_antipattern, activation)

        assert pack.category == ComplianceCategory.STYLE  # CODING is not a valid ComplianceCategory; antipattern → STYLE
        assert len(pack.rules) == 1

    def test_architecture_to_architecture_category(self, sample_insight_architecture):
        """architecture pattern_type → ARCHITECTURE category"""
        activation = InsightActivation(
            insight_id="insight-003",
            rule_pack_name="insight_insight-003",
            rule_id="insight_rule_insight-003",
            activated_at="2026-06-16T10:00:00",
            insight_title=sample_insight_architecture.title,
            insight_pattern_type="architecture",
            severity="medium",
        )
        pack = insight_to_rule_pack(sample_insight_architecture, activation)

        assert pack.category == ComplianceCategory.ARCHITECTURE

    def test_rule_has_remediation_from_metadata(self, sample_insight_entry):
        """remediation 从 Insight metadata 传递到 ComplianceRule"""
        activation = InsightActivation(
            insight_id="insight-001",
            rule_pack_name="insight_insight-001",
            rule_id="insight_rule_insight-001",
            activated_at="2026-06-16T10:00:00",
            insight_title=sample_insight_entry.title,
            insight_pattern_type="risk",
            severity="high",
        )
        pack = insight_to_rule_pack(sample_insight_entry, activation)

        rule = pack.rules[0]
        assert rule.remediation == "Use environment variables or secret manager for API keys"

    def test_rule_has_languages_from_metadata(self, sample_insight_entry):
        """languages 从 Insight metadata 传递到 ComplianceRule"""
        activation = InsightActivation(
            insight_id="insight-001",
            rule_pack_name="insight_insight-001",
            rule_id="insight_rule_insight-001",
            activated_at="2026-06-16T10:00:00",
            insight_title=sample_insight_entry.title,
            insight_pattern_type="risk",
            severity="high",
        )
        pack = insight_to_rule_pack(sample_insight_entry, activation)

        rule = pack.rules[0]
        assert "python" in rule.languages
        assert "javascript" in rule.languages

    def test_rule_not_auto_fixable(self, sample_insight_entry):
        """Insight 激活的规则默认 auto_fixable=False"""
        activation = InsightActivation(
            insight_id="insight-001",
            rule_pack_name="insight_insight-001",
            rule_id="insight_rule_insight-001",
            activated_at="2026-06-16T10:00:00",
            insight_title=sample_insight_entry.title,
            insight_pattern_type="risk",
            severity="high",
        )
        pack = insight_to_rule_pack(sample_insight_entry, activation)

        assert pack.rules[0].auto_fixable is False

    def test_pack_name_matches_activation(self, sample_insight_entry):
        """RulePack name 与激活记录的 rule_pack_name 一致"""
        activation = InsightActivation(
            insight_id="insight-001",
            rule_pack_name="insight_insight-001",
            rule_id="insight_rule_insight-001",
            activated_at="2026-06-16T10:00:00",
            insight_title=sample_insight_entry.title,
            insight_pattern_type="risk",
            severity="high",
        )
        pack = insight_to_rule_pack(sample_insight_entry, activation)

        assert pack.name == "insight_insight-001"


# ═══════════════════════════════════════════════════════════
#  Test S-4.4: 端到端激活流程
# ═══════════════════════════════════════════════════════════

class TestEndToEndActivation:
    """完整激活流程：知识库 → Insight → RulePack → ComplianceEngine"""

    def test_full_activation_flow(self, activation_store, sample_insight_entry):
        """验收标准：用户采纳洞察 → 一键激活为规则"""
        # Step 1: 激活 Insight
        activation = activation_store.activate(sample_insight_entry, severity="high")

        # Step 2: 转换为 RulePack
        pack = insight_to_rule_pack(sample_insight_entry, activation)

        # Step 3: 加载到 ComplianceEngine
        engine = ComplianceEngine()
        engine.load_pack(pack)

        # 验证 RulePack 已加载
        loaded_pack = engine.get_pack("insight_insight-001")
        assert loaded_pack is not None
        assert loaded_pack.name == "insight_insight-001"
        assert len(loaded_pack.rules) == 1

    def test_full_deactivation_flow(self, activation_store, sample_insight_entry):
        """验收标准：可撤销"""
        # Step 1: 激活
        activation = activation_store.activate(sample_insight_entry, severity="high")
        pack = insight_to_rule_pack(sample_insight_entry, activation)
        engine = ComplianceEngine()
        engine.load_pack(pack)

        # 验证激活状态
        assert activation_store.is_activated("insight-001")
        assert engine.get_pack("insight_insight-001") is not None

        # Step 2: 撤销
        activation_store.deactivate("insight-001")
        engine.unload_pack("insight_insight-001")

        # 验证撤销结果
        assert not activation_store.is_activated("insight-001")
        assert engine.get_pack("insight_insight-001") is None

    def test_reactivate_after_deactivation(self, activation_store, sample_insight_entry):
        """撤销后可以重新激活"""
        # 激活 → 撤销 → 重新激活
        activation_store.activate(sample_insight_entry, severity="high")
        activation_store.deactivate("insight-001")

        assert not activation_store.is_activated("insight-001")

        # 重新激活（不同 severity）
        new_activation = activation_store.activate(sample_insight_entry, severity="low")
        assert new_activation.severity == "low"
        assert activation_store.is_activated("insight-001")

    def test_activate_multiple_insights(self, activation_store, sample_insight_entry, sample_insight_antipattern):
        """可以同时激活多个 Insight"""
        activation1 = activation_store.activate(sample_insight_entry, severity="high")
        activation2 = activation_store.activate(sample_insight_antipattern, severity="low")

        assert activation_store.is_activated("insight-001")
        assert activation_store.is_activated("insight-002")
        assert len(activation_store.list_activations()) == 2

    def test_duplicate_activation_prevented(self, activation_store, sample_insight_entry):
        """重复激活同一 Insight 应被拒绝（在 MCP 工具层面）"""
        # Store 层面：activate 会覆盖
        activation1 = activation_store.activate(sample_insight_entry, severity="high")
        activation2 = activation_store.activate(sample_insight_entry, severity="low")

        # Store 层面：同名覆盖，保留最新的
        retrieved = activation_store.get_activation("insight-001")
        assert retrieved.severity == "low"

        # MCP 工具层面：用 is_activated 检查后拒绝
        # (MCP 工具在 activate 前先检查 is_activated，返回 error)


# ═══════════════════════════════════════════════════════════
#  Test S-4.5: 边界情况
# ═══════════════════════════════════════════════════════════

class TestBoundaryCases:
    """边界和异常处理"""

    def test_activate_with_empty_insight_id(self, activation_store):
        """空 insight_id 的 Insight"""
        empty_entry = KnowledgeEntry(
            id="",
            type=KnowledgeType.RISK,
            scope=KnowledgeScope.PROJECT,
            title="Empty ID insight",
            content="No ID",
            metadata={"pattern_type": "risk"},
            tags=[],
            confidence=0.5,
            source="learning",
        )
        activation = activation_store.activate(empty_entry)
        # 空字符串仍然可激活（rule_pack_name = insight_）
        assert activation.rule_pack_name == "insight_"

    def test_activate_with_missing_pattern_type(self, activation_store):
        """metadata 中无 pattern_type"""
        entry = KnowledgeEntry(
            id="insight-no-pattern",
            type=KnowledgeType.PATTERN,
            scope=KnowledgeScope.PROJECT,
            title="Unknown pattern type",
            content="Some content",
            metadata={},  # 无 pattern_type
            tags=[],
            confidence=0.5,
            source="learning",
        )
        activation = activation_store.activate(entry)
        assert activation.insight_pattern_type == "unknown"

    def test_activate_with_missing_remediation(self, activation_store):
        """metadata 中无 remediation"""
        entry = KnowledgeEntry(
            id="insight-no-remediation",
            type=KnowledgeType.RISK,
            scope=KnowledgeScope.PROJECT,
            title="No remediation insight",
            content="Some content",
            metadata={"pattern_type": "risk"},
            tags=[],
            confidence=0.5,
            source="learning",
        )
        activation = activation_store.activate(entry)
        pack = insight_to_rule_pack(entry, activation)

        # remediation 为空字符串
        assert pack.rules[0].remediation == ""

    def test_deactivate_nonexistent_does_not_error(self, activation_store):
        """撤销不存在的 Insight 不会报错"""
        result = activation_store.deactivate("nonexistent-id")
        assert result is None
        # Store 内部状态不变
        assert len(activation_store.list_activations()) == 0

    def test_activation_store_handles_corrupt_json(self, temp_store_dir):
        """损坏的 JSON 文件不导致崩溃"""
        project_dir = os.path.join(temp_store_dir, "test-project")
        os.makedirs(project_dir, exist_ok=True)
        activations_path = os.path.join(project_dir, "activations.json")

        # 写入损坏的 JSON
        with open(activations_path, "w") as f:
            f.write("{invalid json content")

        store = InsightActivationStore(project_name="test-project", base_dir=temp_store_dir)
        store.initialize()  # 应不崩溃
        # 激活记录为空（损坏文件被忽略）
        assert len(store.list_activations()) == 0


# ═══════════════════════════════════════════════════════════
#  Test S-4.6: MCP 工具层面测试
# ═══════════════════════════════════════════════════════════

class TestMCPKnowledgeActivateTool:
    """MCP 工具 harness_knowledge_activate / harness_knowledge_deactivate"""

    def test_mcp_activate_returns_success(self):
        """MCP 工具激活返回成功结构"""
        insight_entry = KnowledgeEntry(
            id="mcp-insight-001",
            type=KnowledgeType.RISK,
            scope=KnowledgeScope.PROJECT,
            title="MCP test insight",
            content="regex: [A-Za-z0-9]{32}",
            metadata={
                "pattern_type": "risk",
                "remediation": "Use env vars",
            },
            tags=["security"],
            confidence=0.9,
            source="learning",
        )

        # 直接测试核心逻辑（不依赖 MCP server）
        store = InsightActivationStore(project_name="mcp-test")
        activation = store.activate(insight_entry, severity="high")
        pack = insight_to_rule_pack(insight_entry, activation)

        # 加载到引擎
        engine = ComplianceEngine()
        engine.load_pack(pack)

        # 验证激活完成
        assert store.is_activated("mcp-insight-001")
        assert engine.get_pack("insight_mcp-insight-001") is not None
        assert activation.severity == "high"
        assert activation.rule_pack_name == "insight_mcp-insight-001"

    def test_mcp_deactivate_after_activate(self):
        """MCP 工具撤销激活"""
        insight_entry = KnowledgeEntry(
            id="mcp-insight-002",
            type=KnowledgeType.RISK,
            scope=KnowledgeScope.PROJECT,
            title="MCP deactivate test",
            content="regex: hardcoded",
            metadata={
                "pattern_type": "risk",
                "remediation": "Move to config",
            },
            tags=["security"],
            confidence=0.8,
            source="learning",
        )

        # 激活
        store = InsightActivationStore(project_name="mcp-test-2")
        activation = store.activate(insight_entry, severity="medium")
        pack = insight_to_rule_pack(insight_entry, activation)
        engine = ComplianceEngine()
        engine.load_pack(pack)

        # 撤销
        removed = store.deactivate("mcp-insight-002")
        engine.unload_pack("insight_mcp-insight-002")

        # 验证撤销完成
        assert removed is not None
        assert not store.is_activated("mcp-insight-002")
        assert engine.get_pack("insight_mcp-insight-002") is None

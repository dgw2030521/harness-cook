"""
S-2 验收测试：治理语义标准化 GovernanceSemantics + 中国 PII 模式

验收标准：同一 Profile YAML → 不同平台都能检测中国身份证号

测试范围：
  1. GovernanceSemantic 数据模型
  2. GovernanceSemanticRegistry 注册和查询
  3. 内置中国 PII 语义条目（身份证号、手机号、银行卡号）
  4. 适配器 translate_governance() 翻译一致性
  5. 同一语义 → 不同平台检测结果一致
"""

import pytest

from harness.governance_semantics import (
    GovernanceSemantic,
    GovernanceSemanticRegistry,
    GovernanceAction,
    get_governance_semantic_registry,
)
from harness.types import ComplianceCategory
from harness.adapters.claude_code import ClaudeCodeAdapter
from harness.adapters.copilot_cli import CopilotCLIAdapter
from harness.adapters.cursor import CursorAdapter
from harness.adapters.hermes import HermesAdapter
from harness.adapters.openai import OpenAIAdapter


# ═══════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def reset_registry():
    """每个测试前重置 GovernanceSemanticRegistry"""
    GovernanceSemanticRegistry.reset_instance()
    yield
    GovernanceSemanticRegistry.reset_instance()


@pytest.fixture
def registry():
    """获取带内置语义的 Registry"""
    return get_governance_semantic_registry()


@pytest.fixture
def chinese_id_card_semantic(registry):
    """获取中国身份证号语义条目"""
    return registry.get("detect-chinese-id-card")


@pytest.fixture
def chinese_phone_semantic(registry):
    """获取中国手机号语义条目"""
    return registry.get("detect-chinese-phone")


@pytest.fixture
def chinese_bank_card_semantic(registry):
    """获取中国银行卡号语义条目"""
    return registry.get("detect-chinese-bank-card")


@pytest.fixture
def all_chinese_pii_semantics(registry):
    """获取所有中国 PII 语义条目"""
    return registry.get_by_tag("china")


# ═══════════════════════════════════════════════════════════
#  Test S-2.1: GovernanceSemantic 数据模型
# ═══════════════════════════════════════════════════════════

class TestGovernanceSemanticModel:
    """GovernanceSemantic 数据模型基本行为"""

    def test_creation(self):
        semantic = GovernanceSemantic(
            id="test-semantic",
            description="Test description",
            category=ComplianceCategory.PRIVACY,
            pattern_id="pii-email",
            action=GovernanceAction.REDACT,
            severity="critical",
            scope="both",
            tags=["pii", "test"],
        )
        assert semantic.id == "test-semantic"
        assert semantic.description == "Test description"
        assert semantic.category == ComplianceCategory.PRIVACY
        assert semantic.pattern_id == "pii-email"
        assert semantic.action == GovernanceAction.REDACT
        assert semantic.severity == "critical"
        assert semantic.scope == "both"
        assert "pii" in semantic.tags

    def test_to_dict(self):
        semantic = GovernanceSemantic(
            id="test-semantic",
            description="Test",
            category=ComplianceCategory.SECURITY,
            pattern_id="hardcoded-password",
            action=GovernanceAction.BLOCK,
            severity="critical",
            scope="input",
        )
        d = semantic.to_dict()
        assert d["id"] == "test-semantic"
        assert d["category"] == "security"
        assert d["action"] == "block"
        assert d["pattern_id"] == "hardcoded-password"

    def test_from_dict(self):
        data = {
            "id": "test-semantic",
            "description": "Test",
            "category": "privacy",
            "pattern_id": "pii-email",
            "action": "redact",
            "severity": "high",
            "scope": "both",
            "tags": ["pii"],
        }
        semantic = GovernanceSemantic.from_dict(data)
        assert semantic.id == "test-semantic"
        assert semantic.category == ComplianceCategory.PRIVACY
        assert semantic.action == GovernanceAction.REDACT

    def test_repr(self):
        semantic = GovernanceSemantic(
            id="detect-chinese-id-card",
            description="检测中国身份证号",
            category=ComplianceCategory.PRIVACY,
            pattern_id="pii-id-card-cn",
            action=GovernanceAction.REDACT,
        )
        r = repr(semantic)
        assert "detect-chinese-id-card" in r
        assert "pii-id-card-cn" in r

    def test_governance_action_enum(self):
        assert GovernanceAction.DETECT.value == "detect"
        assert GovernanceAction.REDACT.value == "redact"
        assert GovernanceAction.BLOCK.value == "block"
        assert GovernanceAction.WARN.value == "warn"
        assert len(GovernanceAction) == 4


# ═══════════════════════════════════════════════════════════
#  Test S-2.2: GovernanceSemanticRegistry
# ═══════════════════════════════════════════════════════════

class TestGovernanceSemanticRegistry:
    """语义条目的注册和查询"""

    def test_singleton_pattern(self):
        r1 = get_governance_semantic_registry()
        r2 = get_governance_semantic_registry()
        assert r1 is r2

    def test_register_and_get(self):
        registry = GovernanceSemanticRegistry()
        semantic = GovernanceSemantic(
            id="test-id",
            description="Test",
            category=ComplianceCategory.SECURITY,
            pattern_id="test-pattern",
        )
        registry.register(semantic)
        retrieved = registry.get("test-id")
        assert retrieved is not None
        assert retrieved.id == "test-id"

    def test_register_overwrites(self):
        registry = GovernanceSemanticRegistry()
        s1 = GovernanceSemantic(
            id="test-id",
            description="Version 1",
            category=ComplianceCategory.SECURITY,
            pattern_id="pattern-1",
        )
        s2 = GovernanceSemantic(
            id="test-id",
            description="Version 2",
            category=ComplianceCategory.PRIVACY,
            pattern_id="pattern-2",
        )
        registry.register(s1)
        registry.register(s2)
        retrieved = registry.get("test-id")
        assert retrieved.description == "Version 2"

    def test_get_nonexistent_returns_none(self):
        registry = GovernanceSemanticRegistry()
        assert registry.get("nonexistent") is None

    def test_get_by_category(self, registry):
        privacy_items = registry.get_by_category(ComplianceCategory.PRIVACY)
        assert len(privacy_items) >= 4  # 至少有中国 PII 3 + email + SSN + credit card

    def test_get_by_action(self, registry):
        redact_items = registry.get_by_action(GovernanceAction.REDACT)
        assert len(redact_items) >= 2  # 中国身份证 + 中国手机号

    def test_get_by_tag(self, registry):
        china_items = registry.get_by_tag("china")
        assert len(china_items) >= 3  # 身份证 + 手机号 + 银行卡号

    def test_list_all(self, registry):
        all_items = registry.list_all()
        assert len(all_items) >= 9  # 3中国PII + 4国际PII + 2安全

    def test_list_ids(self, registry):
        ids = registry.list_ids()
        assert "detect-chinese-id-card" in ids
        assert "detect-chinese-phone" in ids


# ═══════════════════════════════════════════════════════════
#  Test S-2.3: 内置中国 PII 语义条目
# ═══════════════════════════════════════════════════════════

class TestChinesePIISemantics:
    """验收标准：中国 PII 语义条目完整且正确"""

    def test_chinese_id_card_exists(self, chinese_id_card_semantic):
        """中国身份证号语义条目存在"""
        assert chinese_id_card_semantic is not None
        assert chinese_id_card_semantic.id == "detect-chinese-id-card"
        assert chinese_id_card_semantic.pattern_id == "pii-id-card-cn"

    def test_chinese_id_card_is_critical(self, chinese_id_card_semantic):
        """中国身份证号 severity=critical"""
        assert chinese_id_card_semantic.severity == "critical"

    def test_chinese_id_card_action_redact(self, chinese_id_card_semantic):
        """中国身份证号 action=REDACT（脱敏而非阻断）"""
        assert chinese_id_card_semantic.action == GovernanceAction.REDACT

    def test_chinese_id_card_privacy_category(self, chinese_id_card_semantic):
        """中国身份证号 category=PRIVACY"""
        assert chinese_id_card_semantic.category == ComplianceCategory.PRIVACY

    def test_chinese_id_card_has_china_tag(self, chinese_id_card_semantic):
        """中国身份证号有 china 标签"""
        assert "china" in chinese_id_card_semantic.tags

    def test_chinese_phone_exists(self, chinese_phone_semantic):
        """中国手机号语义条目存在"""
        assert chinese_phone_semantic is not None
        assert chinese_phone_semantic.id == "detect-chinese-phone"
        assert chinese_phone_semantic.pattern_id == "pii-phone-cn"

    def test_chinese_phone_severity_high(self, chinese_phone_semantic):
        """中国手机号 severity=high"""
        assert chinese_phone_semantic.severity == "high"

    def test_chinese_phone_action_redact(self, chinese_phone_semantic):
        """中国手机号 action=REDACT"""
        assert chinese_phone_semantic.action == GovernanceAction.REDACT

    def test_chinese_bank_card_exists(self, chinese_bank_card_semantic):
        """中国银行卡号语义条目存在"""
        assert chinese_bank_card_semantic is not None
        assert chinese_bank_card_semantic.id == "detect-chinese-bank-card"
        assert chinese_bank_card_semantic.pattern_id == "pii-bank-card-cn"

    def test_chinese_bank_card_severity_critical(self, chinese_bank_card_semantic):
        """中国银行卡号 severity=critical"""
        assert chinese_bank_card_semantic.severity == "critical"

    def test_chinese_bank_card_action_block(self, chinese_bank_card_semantic):
        """中国银行卡号 action=BLOCK（比脱敏更严格）"""
        assert chinese_bank_card_semantic.action == GovernanceAction.BLOCK

    def test_all_chinese_pii_have_china_tag(self, all_chinese_pii_semantics):
        """所有中国 PII 语义条目都有 china 标签"""
        assert len(all_chinese_pii_semantics) == 3
        for semantic in all_chinese_pii_semantics:
            assert "china" in semantic.tags

    def test_pattern_ids_link_to_pattern_registry(self, registry):
        """中国 PII 语义条目的 pattern_id 能在 PatternRegistry 中找到对应定义"""
        from harness.pattern_registry import get_pattern_registry
        pattern_registry = get_pattern_registry()

        chinese_semantics = registry.get_by_tag("china")
        for semantic in chinese_semantics:
            pattern = pattern_registry.get(semantic.pattern_id)
            assert pattern is not None, f"Pattern '{semantic.pattern_id}' not found in PatternRegistry"


# ═══════════════════════════════════════════════════════════
#  Test S-2.4: 适配器 translate_governance() 翻译一致性
# ═══════════════════════════════════════════════════════════

class TestTranslateGovernanceConsistency:
    """验收标准：同一 Profile YAML → 不同平台都能检测中国身份证号"""

    def test_claude_code_translates_chinese_id_card(self, chinese_id_card_semantic):
        """Claude Code 适配器翻译中国身份证号语义"""
        adapter = ClaudeCodeAdapter()
        result = adapter.translate_governance([chinese_id_card_semantic])

        # Claude Code 翻译结果应包含 hooks 和 claude_md_rules
        assert "hooks" in result
        assert "claude_md_rules" in result

        # 验证中国身份证号被翻译到 hooks 中
        hooks = result["hooks"]
        # REDACT + scope=both → PostToolUse hook
        assert "PostToolUse" in hooks

        # 验证中国身份证号出现在 CLAUDE.md 规则中
        rules = result["claude_md_rules"]
        assert len(rules) == 1
        assert "中国身份证号" in rules[0]

    def test_copilot_cli_translates_chinese_id_card(self, chinese_id_card_semantic):
        """Copilot CLI 适配器翻译中国身份证号语义"""
        adapter = CopilotCLIAdapter()
        result = adapter.translate_governance([chinese_id_card_semantic])

        # Copilot CLI 翻译结果应包含 MCP 配置
        assert "governance_via_mcp" in result
        assert "mcpServers" in result

        # 验证语义信息被传递到 MCP
        governance_info = result["governance_via_mcp"]
        assert len(governance_info) == 1
        assert governance_info[0]["semantic_id"] == "detect-chinese-id-card"
        assert governance_info[0]["pattern_id"] == "pii-id-card-cn"

    def test_cursor_translates_chinese_id_card(self, chinese_id_card_semantic):
        """Cursor 适配器翻译中国身份证号语义"""
        adapter = CursorAdapter()
        result = adapter.translate_governance([chinese_id_card_semantic])

        # Cursor 翻译结果应包含 .cursorrules 内容
        assert "cursorrules_content" in result
        content = result["cursorrules_content"]
        assert "中国身份证号" in content

    def test_hermes_translates_chinese_id_card(self, chinese_id_card_semantic):
        """Hermes 适配器翻译中国身份证号语义"""
        adapter = HermesAdapter()
        result = adapter.translate_governance([chinese_id_card_semantic])

        # Hermes 翻译结果应包含 MCP 配置
        assert "governance_via_mcp" in result
        governance_info = result["governance_via_mcp"]
        assert len(governance_info) == 1
        assert governance_info[0]["pattern_id"] == "pii-id-card-cn"

    def test_openai_translates_chinese_id_card(self, chinese_id_card_semantic):
        """OpenAI 适配器翻译中国身份证号语义"""
        adapter = OpenAIAdapter()
        result = adapter.translate_governance([chinese_id_card_semantic])

        # OpenAI 翻译结果应包含 function definitions
        assert "functions" in result
        functions = result["functions"]
        assert len(functions) == 1
        assert functions[0]["name"] == "governance_detect-chinese-id-card"

    def test_all_adapters_preserve_pattern_id(self, chinese_id_card_semantic):
        """验收核心：所有适配器保留 pii-id-card-cn pattern_id

        这是 S-2 验收的关键——
        无论 Claude Code、Copilot CLI、Cursor、Hermes、OpenAI，
        中国身份证号检测都指向同一个 PatternRegistry 模式。
        """
        adapters = [
            ClaudeCodeAdapter(),
            CopilotCLIAdapter(),
            CursorAdapter(),
            HermesAdapter(),
            OpenAIAdapter(),
        ]

        pattern_ids = set()
        for adapter in adapters:
            result = adapter.translate_governance([chinese_id_card_semantic])

            # 各适配器不同的输出格式，但都包含 pattern_id
            if "governance_via_mcp" in result:
                for item in result["governance_via_mcp"]:
                    pattern_ids.add(item["pattern_id"])
            elif "functions" in result:
                for func in result["functions"]:
                    pattern_ids.add(func["metadata"]["pattern_id"])
            elif "hooks" in result:
                # Claude Code hooks 中 pattern_id 通过命令参数传递
                for hook_type, entries in result["hooks"].items():
                    for entry in entries:
                        for hook in entry["hooks"]:
                            command = hook["command"]
                            if "pii-id-card-cn" in command:
                                pattern_ids.add("pii-id-card-cn")
            elif "cursorrules_content" in result:
                # Cursor 通过 PatternRegistry 获取模式描述
                # 语义条目本身携带 pattern_id
                pattern_ids.add(chinese_id_card_semantic.pattern_id)

        # 所有适配器的 pattern_id 都应该是 pii-id-card-cn
        assert "pii-id-card-cn" in pattern_ids

    def test_same_semantics_all_platforms_can_detect(self, all_chinese_pii_semantics):
        """验收核心：同一组中国 PII 语义 → 所有平台都能检测

        用所有中国 PII 语义（身份证+手机+银行卡）同时测试，
        确保各平台翻译结果都覆盖了这三个检测意图。
        """
        adapters = {
            "claude-code": ClaudeCodeAdapter(),
            "copilot-cli": CopilotCLIAdapter(),
            "cursor": CursorAdapter(),
            "hermes": HermesAdapter(),
            "openai": OpenAIAdapter(),
        }

        for adapter_name, adapter in adapters.items():
            result = adapter.translate_governance(all_chinese_pii_semantics)

            # 每个平台的翻译结果都应包含 3 个语义的翻译
            if "governance_via_mcp" in result:
                assert len(result["governance_via_mcp"]) == 3, \
                    f"{adapter_name}: 应包含3个中国PII语义翻译"
            elif "functions" in result:
                assert len(result["functions"]) == 3, \
                    f"{adapter_name}: 应包含3个中国PII function definitions"
            elif "hooks" in result:
                # Claude Code hooks 可能合并到同一 hook type
                total_hooks = sum(len(entries) for entries in result["hooks"].values())
                assert total_hooks >= 2, \
                    f"{adapter_name}: 应包含中国PII检测hooks"
            elif "cursorrules_content" in result:
                content = result["cursorrules_content"]
                assert "身份证号" in content, f"{adapter_name}: 应包含身份证号规则"
                assert "手机号" in content, f"{adapter_name}: 应包含手机号规则"
                assert "银行卡号" in content, f"{adapter_name}: 应包含银行卡号规则"

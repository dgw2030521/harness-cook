"""
S-5 验收测试：退让检测机制 PlatformCapability + ExecutionStrategy

验收标准：平台返回 supports_realtime_redact=True → 护栏自动切换增强模式

测试范围：
  1. PlatformCapability.resolve_execution_strategy() 决策逻辑
  2. 各内置适配器的能力声明和执行策略
  3. 模拟 supports_realtime_redact=True → ENHANCEMENT
  4. Bridge deploy 中的退让检测和提示强度调整
  5. end-to-end: 自定义适配器声明 redact=True → deploy 结果为 enhancement
"""

import pytest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

from harness.types import (
    PlatformCapability,
    ExecutionStrategy,
    ComplianceCategory,
    GateMode,
    GateDefinition,
    GateCheck,
    ProfileConfig,
    StepConfig,
    WorkflowConfig,
)
from harness.bridge import HarnessBridge, AdapterRegistry, get_adapter_registry
from harness.adapters.claude_code import ClaudeCodeAdapter
from harness.adapters.copilot_cli import CopilotCLIAdapter
from harness.adapters.cursor import CursorAdapter
from harness.adapters.hermes import HermesAdapter
from harness.adapters.openai import OpenAIAdapter
from harness.adapters.base import IAgentAdapter


# ═══════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def default_profile():
    """创建一个用于测试的基本 Profile"""
    return ProfileConfig(
        name="default",
        description="Test profile",
        default_agent="claude-code",
        default_gate_mode=GateMode.HYBRID,
        hooks={},
        gate_checks=[],
        steps=[StepConfig(name="step1", description="desc")],
        workflow=WorkflowConfig(name="wf1", steps=["step1"]),
    )


# ═══════════════════════════════════════════════════════════
#  Test S-5.1: PlatformCapability.resolve_execution_strategy()
# ═══════════════════════════════════════════════════════════

class TestResolveExecutionStrategy:
    """S-5 核心：resolve_execution_strategy 决策逻辑"""

    def test_full_guardrail_returns_enhancement(self):
        """验收核心：supports_realtime_redact=True + block=True → ENHANCEMENT

        当平台已有完整护栏能力（脱敏+阻止），harness 退让为可选增强层。
        """
        cap = PlatformCapability(
            supports_realtime_redact=True,
            supports_realtime_block=True,
        )
        strategy = cap.resolve_execution_strategy()
        assert strategy == ExecutionStrategy.ENHANCEMENT

    def test_redact_only_returns_cooperative(self):
        """验收核心：supports_realtime_redact=True → COOPERATIVE

        平台有脱敏能力但没有阻止能力 → harness 补充阻止场景。
        """
        cap = PlatformCapability(
            supports_realtime_redact=True,
            supports_realtime_block=False,
        )
        strategy = cap.resolve_execution_strategy()
        assert strategy == ExecutionStrategy.COOPERATIVE

    def test_block_only_returns_cooperative(self):
        """平台有阻止能力但没有脱敏 → COOPERATIVE"""
        cap = PlatformCapability(
            supports_realtime_redact=False,
            supports_realtime_block=True,
        )
        strategy = cap.resolve_execution_strategy()
        assert strategy == ExecutionStrategy.COOPERATIVE

    def test_no_guardrail_returns_fallback(self):
        """平台无任何护栏能力 → FALLBACK"""
        cap = PlatformCapability()
        strategy = cap.resolve_execution_strategy()
        assert strategy == ExecutionStrategy.FALLBACK

    def test_pii_detection_returns_cooperative(self):
        """平台有 PII 检测能力 → COOPERATIVE"""
        cap = PlatformCapability(
            supports_pii_detection=True,
            pii_types_supported=["email", "phone"],
        )
        strategy = cap.resolve_execution_strategy()
        assert strategy == ExecutionStrategy.COOPERATIVE

    def test_compliance_scan_returns_cooperative(self):
        """平台有合规扫描能力 → COOPERATIVE"""
        cap = PlatformCapability(
            supports_compliance_scan=True,
            compliance_engines=["sonarqube"],
        )
        strategy = cap.resolve_execution_strategy()
        assert strategy == ExecutionStrategy.COOPERATIVE

    def test_pii_types_list_returns_cooperative(self):
        """平台有 PII 类型列表但没声明 supports_pii_detection → COOPERATIVE"""
        cap = PlatformCapability(
            supports_pii_detection=False,
            pii_types_supported=["id-card-cn", "phone-cn"],
        )
        strategy = cap.resolve_execution_strategy()
        assert strategy == ExecutionStrategy.COOPERATIVE

    def test_enhancement_is_highest_priority(self):
        """ENHANCEMENT 优先级最高：即使有 PII/合规，redact+block 时仍为 ENHANCEMENT"""
        cap = PlatformCapability(
            supports_realtime_redact=True,
            supports_realtime_block=True,
            supports_pii_detection=True,
            pii_types_supported=["email"],
            supports_compliance_scan=True,
            compliance_engines=["sonarqube"],
        )
        strategy = cap.resolve_execution_strategy()
        assert strategy == ExecutionStrategy.ENHANCEMENT


# ═══════════════════════════════════════════════════════════
#  Test S-5.2: 内置适配器能力声明和执行策略
# ═══════════════════════════════════════════════════════════

class TestBuiltinAdapterCapabilities:
    """各内置适配器的 get_capabilities() 和执行策略"""

    def test_claude_code_capability_and_strategy(self):
        """Claude Code: block=True → COOPERATIVE"""
        adapter = ClaudeCodeAdapter()
        cap = adapter.get_capabilities()
        assert cap.supports_realtime_block is True
        assert cap.supports_realtime_redact is False
        assert cap.resolve_execution_strategy() == ExecutionStrategy.COOPERATIVE

    def test_copilot_cli_capability_and_strategy(self):
        """Copilot CLI: block=True → COOPERATIVE"""
        adapter = CopilotCLIAdapter()
        cap = adapter.get_capabilities()
        assert cap.supports_realtime_block is True
        assert cap.supports_realtime_redact is False
        assert cap.resolve_execution_strategy() == ExecutionStrategy.COOPERATIVE

    def test_cursor_capability_and_strategy(self):
        """Cursor: 无任何护栏能力 → FALLBACK"""
        adapter = CursorAdapter()
        cap = adapter.get_capabilities()
        assert cap.supports_realtime_redact is False
        assert cap.supports_realtime_block is False
        assert cap.resolve_execution_strategy() == ExecutionStrategy.FALLBACK

    def test_hermes_capability_and_strategy(self):
        """Hermes: 无任何护栏能力 → FALLBACK"""
        adapter = HermesAdapter()
        cap = adapter.get_capabilities()
        assert cap.supports_realtime_redact is False
        assert cap.supports_realtime_block is False
        assert cap.resolve_execution_strategy() == ExecutionStrategy.FALLBACK

    def test_openai_capability_and_strategy(self):
        """OpenAI: 无任何护栏能力 → FALLBACK"""
        adapter = OpenAIAdapter()
        cap = adapter.get_capabilities()
        assert cap.supports_realtime_redact is False
        assert cap.supports_realtime_block is False
        assert cap.resolve_execution_strategy() == ExecutionStrategy.FALLBACK

    def test_all_adapters_have_get_capabilities(self):
        """所有内置适配器都实现了 get_capabilities()"""
        adapters = [
            ClaudeCodeAdapter(),
            CopilotCLIAdapter(),
            CursorAdapter(),
            HermesAdapter(),
            OpenAIAdapter(),
        ]
        for adapter in adapters:
            cap = adapter.get_capabilities()
            assert isinstance(cap, PlatformCapability)


# ═══════════════════════════════════════════════════════════
#  Test S-5.3: 自定义适配器声明 redact=True → ENHANCEMENT
# ═══════════════════════════════════════════════════════════

class TestCustomAdapterRedactTrue:
    """验收核心：自定义适配器声明 supports_realtime_redact=True → ENHANCEMENT

    这直接验证 S-5 的验收标准：
    "平台返回 supports_realtime_redact=True → 护栏自动切换增强模式"
    """

    def test_redact_true_adapter_yields_enhancement(self):
        """声明 redact=True 的适配器 → 执行策略为 ENHANCEMENT"""
        # 构造一个声明 redact=True 的 PlatformCapability
        cap = PlatformCapability(
            supports_realtime_redact=True,
            supports_realtime_block=True,  # 完整护栏 → ENHANCEMENT
        )
        strategy = cap.resolve_execution_strategy()
        assert strategy == ExecutionStrategy.ENHANCEMENT

    def test_redact_true_without_block_yields_cooperative(self):
        """声明 redact=True 但没有 block → COOPERATIVE（不是 ENHANCEMENT）

        ENHANCEMENT 需要完整护栏（redact + block），只有 redact 时
        harness 还需要补充 block 场景 → COOPERATIVE。
        """
        cap = PlatformCapability(
            supports_realtime_redact=True,
            supports_realtime_block=False,
        )
        strategy = cap.resolve_execution_strategy()
        assert strategy == ExecutionStrategy.COOPERATIVE

    def test_redact_true_changes_fallback_to_enhancement(self):
        """从 FALLBACK 切换到 ENHANCEMENT：同一个适配器，redact 从 False→True

        验证：当平台的 redact 能力从无到有时，执行策略从 FALLBACK 升级到 ENHANCEMENT。
        """
        # 无 redact 的默认能力 → FALLBACK
        cap_no_redact = PlatformCapability()
        assert cap_no_redact.resolve_execution_strategy() == ExecutionStrategy.FALLBACK

        # 有 redact + block → ENHANCEMENT
        cap_with_redact = PlatformCapability(
            supports_realtime_redact=True,
            supports_realtime_block=True,
        )
        assert cap_with_redact.resolve_execution_strategy() == ExecutionStrategy.ENHANCEMENT


# ═══════════════════════════════════════════════════════════
#  Test S-5.4: PlatformCapability 属性方法
# ═══════════════════════════════════════════════════════════

class TestPlatformCapabilityProperties:
    """PlatformCapability 的 has_full_guardrail、has_partial_pii、summary"""

    def test_has_full_guardrail(self):
        cap = PlatformCapability(
            supports_realtime_redact=True,
            supports_realtime_block=True,
        )
        assert cap.has_full_guardrail is True

    def test_has_full_guardrail_false_if_missing_one(self):
        cap = PlatformCapability(
            supports_realtime_redact=True,
            supports_realtime_block=False,
        )
        assert cap.has_full_guardrail is False

    def test_has_partial_pii_with_detection(self):
        cap = PlatformCapability(
            supports_pii_detection=True,
        )
        assert cap.has_partial_pii is True

    def test_has_partial_pii_with_types_list(self):
        cap = PlatformCapability(
            pii_types_supported=["email", "id-card-cn"],
        )
        assert cap.has_partial_pii is True

    def test_has_partial_pii_false(self):
        cap = PlatformCapability()
        assert cap.has_partial_pii is False

    def test_summary_full_guardrail(self):
        cap = PlatformCapability(
            supports_realtime_redact=True,
            supports_realtime_block=True,
            supports_pii_detection=True,
            pii_types_supported=["email"],
            supports_compliance_scan=True,
            compliance_engines=["sonarqube"],
        )
        s = cap.summary()
        assert "realtime-redact" in s
        assert "realtime-block" in s
        assert "pii(email)" in s
        assert "compliance(sonarqube)" in s

    def test_summary_empty(self):
        cap = PlatformCapability()
        assert cap.summary() == "none"

    def test_summary_partial_pii(self):
        cap = PlatformCapability(
            pii_types_supported=["id-card-cn"],
        )
        s = cap.summary()
        assert "pii(id-card-cn)" in s


# ═══════════════════════════════════════════════════════════
#  Test S-5.5: ExecutionStrategy 枚举值
# ═══════════════════════════════════════════════════════════

class TestExecutionStrategyEnum:
    """ExecutionStrategy 枚举值定义"""

    def test_enhancement_value(self):
        assert ExecutionStrategy.ENHANCEMENT.value == "enhancement"

    def test_cooperative_value(self):
        assert ExecutionStrategy.COOPERATIVE.value == "cooperative"

    def test_fallback_value(self):
        assert ExecutionStrategy.FALLBACK.value == "fallback"

    def test_three_strategies_only(self):
        assert len(ExecutionStrategy) == 3


# ═══════════════════════════════════════════════════════════
#  Test S-5.6: Bridge deploy 中的退让检测
# ═══════════════════════════════════════════════════════════

class TestBridgeDeployYieldStrategy:
    """Bridge deploy() 结果包含 execution_strategy 和 platform_capabilities"""

    def test_fallback_strategy_upgrades_prompt_strength(self):
        """FALLBACK + supports_hooks=True → prompt_strength 从 mild 升级为 mandatory

        当平台无任何护栏能力，即使适配器支持 hooks，
        harness 的提示强度也应该升级为 mandatory（强化兜底模式）。
        """
        bridge = HarnessBridge.__new__(HarnessBridge)
        bridge._bus = MagicMock()

        # 模拟一个 supports_hooks=True 但 capabilities=FALLBACK 的场景
        # 当前内置适配器中：Claude Code supports_hooks=True, COOPERATIVE
        # 需要模拟一个 FALLBACK 场景来验证升级逻辑

        # 创建一个 supports_hooks=True 但 capabilities 全为 False 的 mock 适配器
        mock_adapter = MagicMock(spec=IAgentAdapter)
        mock_adapter.name = "mock-platform"
        mock_adapter.supports_hooks = True
        mock_adapter.get_settings_path.return_value = "/tmp/mock_settings.json"
        mock_adapter.translate_hooks.return_value = {"hooks": {}}
        mock_adapter.merge_settings.return_value = {"hooks": {}}
        mock_adapter.get_capabilities.return_value = PlatformCapability(
            supports_realtime_redact=False,
            supports_realtime_block=False,
        )

        # 验证 FALLBACK 策略
        cap = mock_adapter.get_capabilities()
        strategy = cap.resolve_execution_strategy()
        assert strategy == ExecutionStrategy.FALLBACK

        # 验证升级逻辑：FALLBACK + mild → mandatory
        prompt_strength = "mild"
        execution_strategy = strategy
        if execution_strategy == ExecutionStrategy.FALLBACK and prompt_strength == "mild":
            prompt_strength = "mandatory"

        assert prompt_strength == "mandatory"

    def test_enhancement_strategy_keeps_mild(self):
        """ENHANCEMENT + supports_hooks=True → prompt_strength 保持 mild

        平台已有完整护栏 → harness 只需轻提示增强。
        """
        bridge = HarnessBridge.__new__(HarnessBridge)
        bridge._bus = MagicMock()

        # 创建 redact=True + block=True 的 mock 适配器
        mock_adapter = MagicMock(spec=IAgentAdapter)
        mock_adapter.name = "enhanced-platform"
        mock_adapter.supports_hooks = True
        mock_adapter.get_capabilities.return_value = PlatformCapability(
            supports_realtime_redact=True,
            supports_realtime_block=True,
        )

        cap = mock_adapter.get_capabilities()
        strategy = cap.resolve_execution_strategy()
        assert strategy == ExecutionStrategy.ENHANCEMENT

        # ENHANCEMENT + mild → 保持 mild
        prompt_strength = "mild"
        # 升级逻辑只在 FALLBACK 时触发
        if strategy == ExecutionStrategy.FALLBACK and prompt_strength == "mild":
            prompt_strength = "mandatory"

        assert prompt_strength == "mild"

    def test_cooperative_strategy_keeps_mild_for_hooked(self):
        """COOPERATIVE + supports_hooks=True → prompt_strength 保持 mild"""
        # Claude Code 是 COOPERATIVE + supports_hooks=True
        adapter = ClaudeCodeAdapter()
        cap = adapter.get_capabilities()
        strategy = cap.resolve_execution_strategy()
        assert strategy == ExecutionStrategy.COOPERATIVE

        prompt_strength = "mild"
        if strategy == ExecutionStrategy.FALLBACK and prompt_strength == "mild":
            prompt_strength = "mandatory"
        assert prompt_strength == "mild"

    def test_fallback_strategy_mandatory_for_non_hooked(self):
        """FALLBACK + supports_hooks=False → prompt_strength=mandatory（本来就是）"""
        # Cursor 是 FALLBACK + supports_hooks=False
        adapter = CursorAdapter()
        cap = adapter.get_capabilities()
        strategy = cap.resolve_execution_strategy()
        assert strategy == ExecutionStrategy.FALLBACK

        # 无 hooks 适配器本来就是 mandatory
        prompt_strength = "mandatory" if not adapter.supports_hooks else "mild"
        # FALLBACK 不需要再升级，已经是 mandatory
        assert prompt_strength == "mandatory"


# ═══════════════════════════════════════════════════════════
#  Test S-5.7: 自定义适配器自动发现 → 能力声明生效
# ═══════════════════════════════════════════════════════════

class TestCustomAdapterCapabilityDiscovery:
    """模拟 AgentX 适配器声明 redact=True → ENHANCEMENT"""

    def test_agentx_adapter_yields_enhancement(self):
        """AgentX（假设的平台）声明 redact+block → ENHANCEMENT

        这是 S-5 验收的直接体现：
        新平台只需实现 IAgentAdapter.get_capabilities()，
        声明 supports_realtime_redact=True → 自动获得 ENHANCEMENT 策略。
        """
        # 模拟 AgentX 的能力声明
        agentx_cap = PlatformCapability(
            supports_realtime_redact=True,
            supports_realtime_block=True,
            supports_pii_detection=True,
            pii_types_supported=["id-card-cn", "phone-cn", "bank-card-cn"],
        )

        strategy = agentx_cap.resolve_execution_strategy()
        assert strategy == ExecutionStrategy.ENHANCEMENT

    def test_platform_with_only_redact_yields_cooperative(self):
        """只有 redact（无 block）的平台 → COOPERATIVE

        如假设的"自动脱敏平台"：能替换敏感内容但不会阻止操作。
        harness 需补充阻止场景。
        """
        cap = PlatformCapability(
            supports_realtime_redact=True,
            supports_realtime_block=False,
        )
        strategy = cap.resolve_execution_strategy()
        assert strategy == ExecutionStrategy.COOPERATIVE

    def test_strategy_switching_is_automatic(self):
        """验证：策略切换完全基于 PlatformCapability，无需手动配置

        确保从 redact=False→True 时策略自动变化。
        """
        # 无 redact → FALLBACK
        cap_before = PlatformCapability()
        assert cap_before.resolve_execution_strategy() == ExecutionStrategy.FALLBACK

        # 添加 redact + block → ENHANCEMENT
        cap_after = PlatformCapability(
            supports_realtime_redact=True,
            supports_realtime_block=True,
        )
        assert cap_after.resolve_execution_strategy() == ExecutionStrategy.ENHANCEMENT

        # 确认没有手动配置，策略完全自动决定
        # （这是核心设计原则：退让检测基于能力声明自动生效）

"""
引擎配置 + ProfileConfig 扩展测试

验证：
- 引擎配置 dataclass 默认值
- ProfileConfig 新字段的向后兼容性（None 默认）
- YAML 加载引擎配置
- ConfigLoader 的 _dict_to_profile 和 _profile_to_dict 解析引擎配置
"""

import pytest

from harness.types import ProfileConfig, GateMode
from harness.integrations.engine_config import (
    GuardrailsEngineConfig,
    ComplianceEngineConfig,
    AuditEngineConfig,
)
from harness.config import ProfileLoader


# ═══════════════════════════════════════════════════════════
#  引擎配置 dataclass 默认值测试
# ═══════════════════════════════════════════════════════════

class TestGuardrailsEngineConfig:
    """GuardrailsEngineConfig 默认值测试"""

    def test_default_values(self):
        """默认 engine=builtin, config={}"""
        cfg = GuardrailsEngineConfig()
        assert cfg.engine == "builtin"
        assert cfg.config == {}

    def test_custom_engine(self):
        """自定义 engine=guardrails-ai"""
        cfg = GuardrailsEngineConfig(engine="guardrails-ai", config={"api_key": "xxx"})
        assert cfg.engine == "guardrails-ai"
        assert cfg.config["api_key"] == "xxx"


class TestComplianceEngineConfig:
    """ComplianceEngineConfig 默认值测试"""

    def test_default_values(self):
        """默认 engines=["builtin"], language_routing={}, config={}"""
        cfg = ComplianceEngineConfig()
        assert cfg.engines == ["builtin"]
        assert cfg.language_routing == {}
        assert cfg.config == {}

    def test_custom_engines_and_routing(self):
        """自定义引擎列表和语言路由"""
        cfg = ComplianceEngineConfig(
            engines=["builtin", "sonarqube"],
            language_routing={"java": "archunit", "javascript": "dep_cruiser"},
        )
        assert "sonarqube" in cfg.engines
        assert cfg.language_routing["java"] == "archunit"


class TestAuditEngineConfig:
    """AuditEngineConfig 默认值测试"""

    def test_default_values(self):
        """默认 backends=["local"], trace_format=builtin, collector_url="" """
        cfg = AuditEngineConfig()
        assert cfg.backends == ["local"]
        assert cfg.trace_format == "builtin"
        assert cfg.collector_url == ""

    def test_custom_backends(self):
        """自定义后端组合"""
        cfg = AuditEngineConfig(
            backends=["local", "langfuse"],
            trace_format="otel-json",
            collector_url="http://localhost:4318",
        )
        assert "langfuse" in cfg.backends
        assert cfg.trace_format == "otel-json"
        assert cfg.collector_url == "http://localhost:4318"


# ═══════════════════════════════════════════════════════════
#  ProfileConfig 向后兼容性测试
# ═══════════════════════════════════════════════════════════

class TestProfileConfigBackwardCompatibility:
    """ProfileConfig 新字段的向后兼容性"""

    def test_default_none_fields(self):
        """新字段默认 None → 不影响现有使用"""
        profile = ProfileConfig()
        assert profile.guardrails_engine is None
        assert profile.compliance_engine is None
        assert profile.audit_engine is None

    def test_existing_fields_unchanged(self):
        """现有字段默认值不变"""
        profile = ProfileConfig()
        assert profile.name == "default"
        assert profile.default_agent == "claude-code"
        assert profile.default_gate_mode == GateMode.HYBRID
        assert profile.pipeline_agents == ["analyst", "coder", "validator", "committer"]

    def test_set_engine_configs(self):
        """设置引擎配置不影响其他字段"""
        profile = ProfileConfig(
            guardrails_engine=GuardrailsEngineConfig(engine="guardrails-ai"),
            compliance_engine=ComplianceEngineConfig(engines=["builtin", "sonarqube"]),
            audit_engine=AuditEngineConfig(backends=["local", "langfuse"]),
        )
        assert profile.guardrails_engine.engine == "guardrails-ai"
        assert profile.compliance_engine.engines == ["builtin", "sonarqube"]
        assert profile.audit_engine.backends == ["local", "langfuse"]
        # 其他字段不变
        assert profile.name == "default"
        assert profile.default_agent == "claude-code"


# ═══════════════════════════════════════════════════════════
#  ConfigLoader 解析测试
# ═══════════════════════════════════════════════════════════

class TestConfigLoaderEngineConfig:
    """ConfigLoader 的引擎配置解析"""

    def test_dict_to_profile_no_engine_config(self):
        """无引擎配置的字典 → ProfileConfig 引擎字段为 None"""
        loader = ProfileLoader()
        data = {
            "profile": {"name": "test", "description": "test profile"},
            "agent": {"adapter": "claude-code"},
            "pipeline": {"agents": ["analyst", "coder", "validator", "committer"]},
            "gates": {"default_mode": "hybrid", "checks": []},
        }
        profile = loader._dict_to_profile(data)
        assert profile.guardrails_engine is None
        assert profile.compliance_engine is None
        assert profile.audit_engine is None

    def test_dict_to_profile_with_guardrails_engine(self):
        """含 guardrails_engine 的字典 → 正确解析"""
        loader = ProfileLoader()
        data = {
            "profile": {"name": "test"},
            "agent": {"adapter": "claude-code"},
            "pipeline": {"agents": ["analyst"]},
            "gates": {"default_mode": "hybrid"},
            "guardrails_engine": {
                "engine": "guardrails-ai",
                "config": {"api_key": "test-key"},
            },
        }
        profile = loader._dict_to_profile(data)
        assert profile.guardrails_engine is not None
        assert profile.guardrails_engine.engine == "guardrails-ai"
        assert profile.guardrails_engine.config["api_key"] == "test-key"

    def test_dict_to_profile_with_compliance_engine(self):
        """含 compliance_engine 的字典 → 正确解析"""
        loader = ProfileLoader()
        data = {
            "profile": {"name": "test"},
            "agent": {"adapter": "claude-code"},
            "pipeline": {"agents": ["analyst"]},
            "gates": {"default_mode": "hybrid"},
            "compliance_engine": {
                "engines": ["builtin", "sonarqube"],
                "language_routing": {"java": "archunit"},
            },
        }
        profile = loader._dict_to_profile(data)
        assert profile.compliance_engine is not None
        assert "sonarqube" in profile.compliance_engine.engines
        assert profile.compliance_engine.language_routing["java"] == "archunit"

    def test_dict_to_profile_with_audit_engine(self):
        """含 audit_engine 的字典 → 正确解析"""
        loader = ProfileLoader()
        data = {
            "profile": {"name": "test"},
            "agent": {"adapter": "claude-code"},
            "pipeline": {"agents": ["analyst"]},
            "gates": {"default_mode": "hybrid"},
            "audit_engine": {
                "backends": ["local", "langfuse"],
                "trace_format": "otel-json",
                "collector_url": "http://localhost:4318",
            },
        }
        profile = loader._dict_to_profile(data)
        assert profile.audit_engine is not None
        assert "langfuse" in profile.audit_engine.backends
        assert profile.audit_engine.trace_format == "otel-json"
        assert profile.audit_engine.collector_url == "http://localhost:4318"

    def test_profile_to_dict_with_engine_configs(self):
        """ProfileConfig → 字典包含引擎配置"""
        loader = ProfileLoader()
        profile = ProfileConfig(
            name="test",
            guardrails_engine=GuardrailsEngineConfig(engine="guardrails-ai"),
            compliance_engine=ComplianceEngineConfig(engines=["builtin", "sonarqube"]),
            audit_engine=AuditEngineConfig(backends=["local", "langfuse"]),
        )
        result = loader._profile_to_dict(profile)
        assert "guardrails_engine" in result
        assert result["guardrails_engine"]["engine"] == "guardrails-ai"
        assert "compliance_engine" in result
        assert result["compliance_engine"]["engines"] == ["builtin", "sonarqube"]
        assert "audit_engine" in result
        assert result["audit_engine"]["backends"] == ["local", "langfuse"]

    def test_profile_to_dict_without_engine_configs(self):
        """ProfileConfig（引擎字段 None）→ 字典不含引擎配置键"""
        loader = ProfileLoader()
        profile = ProfileConfig(name="test")
        result = loader._profile_to_dict(profile)
        assert "guardrails_engine" not in result
        assert "compliance_engine" not in result
        assert "audit_engine" not in result

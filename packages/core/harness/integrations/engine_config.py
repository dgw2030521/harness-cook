"""
引擎配置 dataclass — 治理集成总线的配置数据结构

三层治理引擎配置：
- GuardrailsEngineConfig: 护栏层（Guardrails AI）
- ComplianceEngineConfig: 合规层（SonarQube/OPA/ArchUnit/dep-cruiser）
- AuditEngineConfig: 审计层（Langfuse/Arize/Datadog）

所有配置字段默认 None → 向后兼容，现有 Profile YAML 无需改动。
"""

from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════════════
#  护栏层引擎配置
# ═══════════════════════════════════════════════════════════

@dataclass
class GuardrailsEngineConfig:
    """护栏层引擎配置

    用法：
        GuardrailsEngineConfig(
            engine="guardrails-ai",
            config={"api_key": "..."},
        )

    engine 取值：
    - "builtin": 使用内置 GuardrailsPair（行为不变）
    - "guardrails-ai": 使用 GuardrailsAIChecker
    """
    engine: str = "builtin"
    config: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════
#  合规层引擎配置
# ═══════════════════════════════════════════════════════════

@dataclass
class ComplianceEngineConfig:
    """合规层引擎配置

    用法：
        ComplianceEngineConfig(
            engines=["builtin"],
            language_routing={"java": "archunit", "javascript": "dep_cruiser"},
        )

    engines 取值：
    - ["builtin"]: 使用内置 RegexChecker + ASTChecker 等
    - ["guardrails-ai"]: 使用 GuardrailsAIChecker
    - ["sonarqube"]: 使用 SonarQubeChecker（引用模式）
    - ["opa"]: 使用 OPAChecker（实时策略评估）
    - 可组合：["builtin", "sonarqube"]

    language_routing:
    - 语言 → 引擎的建议性路由（用户可通过 matcher_type 覆盖）
    - 引擎不可用时回退到标准路由
    """
    engines: list[str] = field(default_factory=lambda: ["builtin"])
    language_routing: dict[str, str] = field(default_factory=dict)
    config: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════
#  审计层引擎配置
# ═══════════════════════════════════════════════════════════

@dataclass
class AuditEngineConfig:
    """审计层引擎配置

    用法：
        AuditEngineConfig(
            backends=["local"],
            trace_format="otel-json",
            collector_url="http://localhost:4318",
        )

    backends 取值：
    - ["local"]: 使用内置 AuditStore（JSON 文件）
    - ["langfuse"]: LangfuseAuditStore
    - ["arize"]: ArizeAuditStore
    - ["datadog"]: DatadogAuditStore
    - 可组合：["local", "langfuse"] → MultiAuditStore（双写）

    trace_format:
    - "builtin": harness 内部格式
    - "otel-json": OTel JSON 导出格式
    - "otel-protobuf": OTel Protobuf 导出格式

    collector_url:
    - OTel Collector 的 HTTP endpoint
    - 空字符串=不导出到 OTel Collector
    """
    backends: list[str] = field(default_factory=lambda: ["local"])
    trace_format: str = "builtin"
    collector_url: str = ""
    config: dict = field(default_factory=dict)

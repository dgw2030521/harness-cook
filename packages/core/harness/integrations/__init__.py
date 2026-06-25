"""
harness-cook 外部引擎集成子包

治理集成总线核心——将外部专业引擎接入 harness-cook 治理框架，
通过 ExternalEngineChecker 基类实现统一的：
- 惰性探测（_probe_engine → 缓存可用性）
- 请求翻译（_translate_request → harness 规则语言到引擎格式）
- 引擎调用（_call_engine → 执行外部引擎检查）
- 响应翻译（_translate_response → 引擎结果到 ComplianceResult）
- 自动降级（引擎不可用时回退到内置 checker）

合规引擎集成：
- SonarQubeChecker（引用模式——从 CI 缓存检索结果）
- OPAChecker（实时策略评估——HTTP 或嵌入式）
- ArchUnitChecker（Java 架构合规——子进程调用 Java 测试）
- DepCruiserChecker（JS/TS 依赖合规——子进程调用 depcruise）

审计存储集成：
- IAuditStore Protocol（审计存储统一契约）
- MultiAuditStore（多后端双写，主存储必须成功，次存储火忘式）

编排平台中间件：
- LangGraphGovernanceNode（LangGraph 兼容治理节点）
- DeerFlowBridge（DeerFlow 编排平台治理桥接）

规则导入器：
- SonarQubeRuleImporter / ArchUnitRuleImporter / DepCruiserRuleImporter

安装方式：
- pip install harness-cook          → 不装任何外部引擎，纯内置
- pip install harness-cook[guardrails] → 安装 Guardrails AI SDK
- pip install harness-cook[sonarqube]  → 安装 SonarQube 集成
- pip install harness-cook[opa]        → 安装 OPA 集成
- pip install harness-cook[integrations] → 安装所有外部引擎 SDK
"""

from harness.integrations.base import ExternalEngineChecker
from harness.integrations.engine_config import (
    GuardrailsEngineConfig,
    ComplianceEngineConfig,
    AuditEngineConfig,
)
from harness.integrations.audit_store_protocol import IAuditStore
from harness.integrations.multi_store import MultiAuditStore

# ─── 合规引擎（懒加载——不影响默认安装）──────────────────────
# 直接 import 是安全的，因为模块级不触发外部 SDK import
# SDK import 在方法级别（_probe_engine / _call_engine）

from harness.integrations.sonarqube_checker import SonarQubeChecker
from harness.integrations.opa_checker import OPAChecker
from harness.integrations.archunit_checker import ArchUnitChecker
from harness.integrations.dep_cruiser_checker import DepCruiserChecker

# ─── 护栏引擎 ────────────────────────────────────────────
from harness.integrations.guardrails_ai_checker import GuardrailsAIChecker
from harness.integrations.nemo_guardrails_checker import NeMoGuardrailsChecker
from harness.integrations.llama_guard_checker import LlamaGuardChecker

# ─── 编排平台中间件 ────────────────────────────────────────────
from harness.integrations.langgraph_middleware import (
    LangGraphGovernanceNode,
    wrap_node_with_governance,
    build_governance_graph,
)
from harness.integrations.deerflow_bridge import DeerFlowBridge

# ─── 审计后端（Helicone 双重定位——护栏 + 审计日志）───────────
from harness.integrations.helicone_store import HeliconeAuditStore

# ─── 规则导入器 ────────────────────────────────────────────────
from harness.integrations.rule_importer import (
    RulePack,
    SonarQubeRuleImporter,
    ArchUnitRuleImporter,
    DepCruiserRuleImporter,
)

__all__ = [
    "ExternalEngineChecker",
    "GuardrailsEngineConfig",
    "ComplianceEngineConfig",
    "AuditEngineConfig",
    "IAuditStore",
    "MultiAuditStore",
    # 合规引擎
    "SonarQubeChecker",
    "OPAChecker",
    "ArchUnitChecker",
    "DepCruiserChecker",
    # 护栏引擎
    "GuardrailsAIChecker",
    "NeMoGuardrailsChecker",
    "LlamaGuardChecker",
    # 编排中间件
    "LangGraphGovernanceNode",
    "wrap_node_with_governance",
    "build_governance_graph",
    "DeerFlowBridge",
    # 审计后端（Helicone 双重定位）
    "HeliconeAuditStore",
    # 规则导入器
    "RulePack",
    "SonarQubeRuleImporter",
    "ArchUnitRuleImporter",
    "DepCruiserRuleImporter",
]

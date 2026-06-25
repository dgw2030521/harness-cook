"""
harness-cook 合规规则引擎 — 统一入口

所有合规相关的公共类和函数均在此模块 re-export，
保证外部 `from harness.compliance import ...` 不受拆分影响。

Compliance Engine 是 Harness 的"法规执行者"——扫描产出物是否符合预定义的合规规则。
与 Gate 不同：Gate 是"质检门禁"（每次任务完成后检查），Compliance 是"法规扫描"（持续扫描）。

核心流程：
  1. 加载合规规则包（ComplianceRule集合）
  2. 构建 ScanContext（包含依赖图等跨文件上下文）
  3. 扫描 Artifact → 通过 MatcherRegistry 路由到 IRuleChecker
  4. 返回 ComplianceResult（通过/违规 + 严重性 + 修复建议）
  5. 违规事件通过 Bus 广播 → Audit 记录 → Learning 收集

匹配策略（matcher_type）：
  - "regex": 正则表达式匹配（默认，单文件模式，向后兼容）
  - "dependency_graph": 依赖图架构检查（跨文件，检测分层违规/循环依赖/过深链路）
  - "ast": AST 结构检查（检测 God Class/深继承等）
  - "cross_file": 跨文件模式检查（检测分散逻辑/重复抽象）
"""

# ─── 类型（原文件从 harness.types 导入，外部模块通过 harness.compliance 引用） ──
from harness.types import (
    Artifact,
    ComplianceCategory,
    ComplianceRule,
    ComplianceResult,
    ScanContext,
)

# ─── 语言注册表 ──────────────────────────────────────
from harness.language_registry import LanguageRegistry

# ─── 规则检查器 ──────────────────────────────────────
from harness.rule_checker import (
    IRuleChecker,
    RegexChecker,
    DependencyGraphChecker,
    ASTChecker,
    CrossFileChecker,
    MatcherRegistry,
)

# ─── 合规引擎与规则包 ──────────────────────────────────
from harness.compliance_engine import (
    RulePack,
    ComplianceEngine,
    security_rule_pack,
    privacy_rule_pack,
    architecture_rule_pack,
)

from harness.rule_packs.legal import get_legal_pack
legal_rule_pack = get_legal_pack

__all__ = [
    # 类型
    "Artifact",
    "ComplianceCategory",
    "ComplianceRule",
    "ComplianceResult",
    "ScanContext",
    # 语言注册表
    "LanguageRegistry",
    # 规则检查器
    "IRuleChecker",
    "RegexChecker",
    "DependencyGraphChecker",
    "ASTChecker",
    "CrossFileChecker",
    "MatcherRegistry",
    # 合规引擎与规则包
    "RulePack",
    "ComplianceEngine",
    "security_rule_pack",
    "privacy_rule_pack",
    "architecture_rule_pack",
    "legal_rule_pack",
]

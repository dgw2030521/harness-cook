"""
GovernanceSemantics — 治理语义标准化（S-2）

设计目的：
  同一 Profile YAML 中的治理意图（如"检测中国身份证号"）
  → 不同平台都能语义一致地执行检测

核心概念：
  - GovernanceSemantic: 标准化的治理意图条目
    如 "detect-chinese-id-card" → 含 PII 类别、PatternRegistry ID、目标动作
  - GovernanceSemanticRegistry: 语义条目的注册和查询中心
  - 适配器 translate_governance(): 将语义条目翻译为平台特定检测配置

语义条目 → 平台翻译路径：
  1. Profile YAML governance段引用语义ID（如 detect-chinese-id-card）
  2. GovernanceSemanticRegistry.get() 获取完整语义定义
  3. 适配器.translate_governance() 翻译为平台格式：
     - Claude Code → CLAUDE.md 提示词 + hook 脚本
     - Copilot CLI → MCP 工具检测配置
     - Cursor → .cursorrules 规则文件
     - Hermes → MCP 检测工具调用
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional, Dict, List

from harness.types import ComplianceCategory

logger = logging.getLogger("harness.governance_semantics")


# ═══════════════════════════════════════════════════════════
#  治理意图动作枚举
# ═══════════════════════════════════════════════════════════

class GovernanceAction(Enum):
    """治理意图动作——语义条目期望的检测行为"""
    DETECT = "detect"        # 检测并记录（合规层）
    REDACT = "redact"        # 检测并脱敏（护栏层）
    BLOCK = "block"          # 检测并阻断（护栏层）
    WARN = "warn"            # 检测并警告（护栏层）


# ═══════════════════════════════════════════════════════════
#  GovernanceSemantic 数据模型
# ═══════════════════════════════════════════════════════════

class GovernanceSemantic:
    """标准化的治理意图条目（S-2）

    一个 GovernanceSemantic 代表一个平台无关的治理意图，
    如"检测中国身份证号并脱敏"。

    字段说明：
      - id: 语义条目唯一标识（如 "detect-chinese-id-card"）
      - description: 人类可读描述
      - category: 合规类别（SECURITY / PRIVACY / ARCHITECTURE 等）
      - pattern_id: 关联的 PatternDefinition ID（如 "pii-id-card-cn"）
      - action: 期望的治理动作（DETECT / REDACT / BLOCK / WARN）
      - severity: 严重级别（critical / high / medium / low）
      - scope: 作用范围（input / output / both）
      - tags: 标签列表（便于查询和分组）

    用法：
        semantic = GovernanceSemantic(
            id="detect-chinese-id-card",
            description="检测并脱敏中国身份证号",
            category=ComplianceCategory.PRIVACY,
            pattern_id="pii-id-card-cn",
            action=GovernanceAction.REDACT,
            severity="critical",
            scope="both",
        )
        # 适配器翻译：
        adapter.translate_governance([semantic]) → 平台格式
    """

    def __init__(
        self,
        id: str,
        description: str,
        category: ComplianceCategory,
        pattern_id: str,
        action: GovernanceAction = GovernanceAction.DETECT,
        severity: str = "medium",
        scope: str = "both",
        tags: Optional[List[str]] = None,
    ):
        self.id = id
        self.description = description
        self.category = category
        self.pattern_id = pattern_id
        self.action = action
        self.severity = severity
        self.scope = scope
        self.tags = tags or []

    def to_dict(self) -> Dict:
        """序列化为字典"""
        return {
            "id": self.id,
            "description": self.description,
            "category": self.category.value,
            "pattern_id": self.pattern_id,
            "action": self.action.value,
            "severity": self.severity,
            "scope": self.scope,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> GovernanceSemantic:
        """从字典反序列化"""
        return cls(
            id=data["id"],
            description=data["description"],
            category=ComplianceCategory(data["category"]),
            pattern_id=data["pattern_id"],
            action=GovernanceAction(data.get("action", "detect")),
            severity=data.get("severity", "medium"),
            scope=data.get("scope", "both"),
            tags=data.get("tags", []),
        )

    def __repr__(self) -> str:
        return f"GovernanceSemantic(id='{self.id}', action={self.action.value}, pattern_id='{self.pattern_id}')"


# ═══════════════════════════════════════════════════════════
#  GovernanceSemanticRegistry — 语义条目注册和查询
# ═══════════════════════════════════════════════════════════

class GovernanceSemanticRegistry:
    """语义条目注册中心——所有治理意图的唯一定义源

    用法:
        registry = get_governance_semantic_registry()
        semantic = registry.get("detect-chinese-id-card")
        semantics = registry.get_by_category(ComplianceCategory.PRIVACY)
    """

    _instance: Optional[GovernanceSemanticRegistry] = None

    def __init__(self):
        self._semantics: Dict[str, GovernanceSemantic] = {}

    @classmethod
    def get_instance(cls) -> GovernanceSemanticRegistry:
        """获取全局单例——首次调用时自动注册内置语义"""
        if cls._instance is None:
            cls._instance = cls()
            _register_builtin_semantics(cls._instance)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置全局单例（测试用）"""
        cls._instance = None

    def register(self, semantic: GovernanceSemantic) -> None:
        """注册一个语义条目（同名覆盖）"""
        if semantic.id in self._semantics:
            logger.debug(f"Semantic '{semantic.id}' re-registered — overwriting")
        self._semantics[semantic.id] = semantic

    def get(self, id: str) -> Optional[GovernanceSemantic]:
        """按 ID 获取语义条目"""
        return self._semantics.get(id)

    def get_by_category(self, category: ComplianceCategory) -> List[GovernanceSemantic]:
        """按合规类别获取所有语义条目"""
        return [s for s in self._semantics.values() if s.category == category]

    def get_by_action(self, action: GovernanceAction) -> List[GovernanceSemantic]:
        """按治理动作获取所有语义条目"""
        return [s for s in self._semantics.values() if s.action == action]

    def get_by_tag(self, tag: str) -> List[GovernanceSemantic]:
        """按标签获取所有语义条目"""
        return [s for s in self._semantics.values() if tag in s.tags]

    def list_all(self) -> List[GovernanceSemantic]:
        """列出所有语义条目"""
        return list(self._semantics.values())

    def list_ids(self) -> List[str]:
        """列出所有语义条目 ID"""
        return list(self._semantics.keys())


def get_governance_semantic_registry() -> GovernanceSemanticRegistry:
    """获取全局 GovernanceSemanticRegistry 单例"""
    return GovernanceSemanticRegistry.get_instance()


# ═══════════════════════════════════════════════════════════
#  内置语义注册——中国 PII + 国际 PII + 安全
# ═══════════════════════════════════════════════════════════

def _register_builtin_semantics(registry: GovernanceSemanticRegistry) -> None:
    """注册所有内置治理语义条目

    每个语义条目关联一个 PatternDefinition ID，
    确保"同一语义 → 同一正则 → 不同平台一致检测"。
    """

    # ─── 中国 PII 语义（S-2 核心验收）───

    # 中国身份证号 → 检测+脱敏
    registry.register(GovernanceSemantic(
        id="detect-chinese-id-card",
        description="检测并脱敏中国身份证号（18位身份证号码）",
        category=ComplianceCategory.PRIVACY,
        pattern_id="pii-id-card-cn",
        action=GovernanceAction.REDACT,
        severity="critical",
        scope="both",
        tags=["china", "pii", "id-card"],
    ))

    # 中国手机号 → 检测+脱敏
    registry.register(GovernanceSemantic(
        id="detect-chinese-phone",
        description="检测并脱敏中国手机号（11位手机号码）",
        category=ComplianceCategory.PRIVACY,
        pattern_id="pii-phone-cn",
        action=GovernanceAction.REDACT,
        severity="high",
        scope="both",
        tags=["china", "pii", "phone"],
    ))

    # 中国银行卡号 → 检测+阻断（比脱敏更严格）
    registry.register(GovernanceSemantic(
        id="detect-chinese-bank-card",
        description="检测并阻断中国银行卡号暴露（16-19位银行卡号）",
        category=ComplianceCategory.PRIVACY,
        pattern_id="pii-bank-card-cn",
        action=GovernanceAction.BLOCK,
        severity="critical",
        scope="both",
        tags=["china", "pii", "bank-card"],
    ))

    # ─── 国际 PII 语义 ───

    # Email 地址 → 检测+警告
    registry.register(GovernanceSemantic(
        id="detect-email",
        description="检测 Email 地址暴露并警告",
        category=ComplianceCategory.PRIVACY,
        pattern_id="pii-email",
        action=GovernanceAction.WARN,
        severity="medium",
        scope="both",
        tags=["pii", "email"],
    ))

    # 美国 SSN → 检测+阻断
    registry.register(GovernanceSemantic(
        id="detect-us-ssn",
        description="检测并阻断美国社会安全号(SSN)暴露",
        category=ComplianceCategory.PRIVACY,
        pattern_id="pii-ssn",
        action=GovernanceAction.BLOCK,
        severity="critical",
        scope="both",
        tags=["pii", "ssn", "us"],
    ))

    # 信用卡号 → 检测+阻断
    registry.register(GovernanceSemantic(
        id="detect-credit-card",
        description="检测并阻断信用卡号暴露",
        category=ComplianceCategory.PRIVACY,
        pattern_id="pii-credit-card",
        action=GovernanceAction.BLOCK,
        severity="critical",
        scope="both",
        tags=["pii", "credit-card"],
    ))

    # ─── 安全语义 ───

    # 硬编码密码 → 检测+阻断
    registry.register(GovernanceSemantic(
        id="detect-hardcoded-password",
        description="检测并阻断硬编码密码",
        category=ComplianceCategory.SECURITY,
        pattern_id="hardcoded-password",
        action=GovernanceAction.BLOCK,
        severity="critical",
        scope="input",
        tags=["security", "secret", "password"],
    ))

    # 硬编码 API 密钥 → 检测+阻断
    registry.register(GovernanceSemantic(
        id="detect-hardcoded-api-key",
        description="检测并阻断硬编码 API 密钥",
        category=ComplianceCategory.SECURITY,
        pattern_id="hardcoded-api-key",
        action=GovernanceAction.BLOCK,
        severity="critical",
        scope="input",
        tags=["security", "secret", "api-key"],
    ))

    # eval/exec 代码注入 → 检测+阻断
    registry.register(GovernanceSemantic(
        id="detect-eval-injection",
        description="检测并阻断 eval() 代码注入",
        category=ComplianceCategory.SECURITY,
        pattern_id="code-injection-eval",
        action=GovernanceAction.BLOCK,
        severity="critical",
        scope="input",
        tags=["security", "code-injection", "eval"],
    ))

    # SQL 注入 → 检测+阻断
    registry.register(GovernanceSemantic(
        id="detect-sql-injection",
        description="检测并阻断 SQL 注入",
        category=ComplianceCategory.SECURITY,
        pattern_id="sql-injection-basic",
        action=GovernanceAction.BLOCK,
        severity="critical",
        scope="input",
        tags=["security", "sql-injection"],
    ))

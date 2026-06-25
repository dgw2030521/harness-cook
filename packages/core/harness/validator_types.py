"""
Validator适配层——从 nextX IValidator/ValidationContext/ValidationIssue 提取的设计蓝图

.. note::
    ComplianceValidator 和 GuardrailsValidator 已集成到 ValidatorRegistry，
    通过 ``register_defaults()`` 即可获得合规检查 + PII/安全护栏的验证能力。

Harness 统一管控 Agent 的验证逻辑:
- 通用Validator接口(不限于compliance规则)
- 验证上下文(变更+需求+知识+配置)
- 验证结果(问题+严重度+可自动修复标记)
- 验证注册器(多Validator协调执行)

nextX 的核心设计模式:
1. IValidator: validate() + 可选autoFix() — 验证+修复双通道
2. ValidationContext: changes+requirements+knowledge+config — 验证所需全部上下文
3. ValidationIssue: CodeLocation + severity + autoFixable标记 — 精确问题定位
4. Requirement: 验收标准 + must/should/could优先级 — 需求分级
5. ValidatorRegistry: 注册+执行+协调 — 多Validator统一调度

harness-cook 适配定位:
- Validator接口统一 compliance.py 和 guardrails.py 的验证逻辑
- 首期ValidatorRegistry只支持同步执行(不含并行验证)
- compliance.py和guardrails.py逐步重构为Validator实现
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, Set

logger = logging.getLogger("harness.validator")


# ═══════════════════════════════════════════════════════════
#  问题严重度——从 nextX ValidationIssue.severity 提取
# ═══════════════════════════════════════════════════════════

class IssueSeverity(Enum):
    """验证问题严重度——4级"""
    CRITICAL = "critical"    # 必须修复,否则阻断
    HIGH = "high"            # 应该修复,不修复有风险
    MEDIUM = "medium"        # 建议修复,非阻塞
    LOW = "low"              # 信息提示,无影响


# ═══════════════════════════════════════════════════════════
#  需求优先级——从 nextX Requirement.priority 提取
# ═══════════════════════════════════════════════════════════

class RequirementPriority(Enum):
    """需求优先级——RFC 2119 语义(must/should/could)"""
    MUST = "must"      # 必须满足,否则验证失败
    SHOULD = "should"  # 应该满足,不满足降级为警告
    COULD = "could"    # 可选增强,不满足仅提示


# ═══════════════════════════════════════════════════════════
#  代码定位——从 nextX CodeLocation 提取
# ═══════════════════════════════════════════════════════════

@dataclass
class CodeLocation:
    """代码定位——精确到文件+行号"""
    file_path: str = ""
    line_number: Optional[int] = None
    column: Optional[int] = None
    symbol_name: Optional[str] = None  # 函数/类名
    
    def display(self) -> str:
        """人类可读定位"""
        parts = [self.file_path]
        if self.line_number:
            parts.append(f":{self.line_number}")
            if self.column:
                parts.append(f":{self.column}")
        if self.symbol_name:
            parts.append(f" ({self.symbol_name})")
        return "".join(parts)


# ═══════════════════════════════════════════════════════════
#  验证问题——从 nextX ValidationIssue 提取
# ═══════════════════════════════════════════════════════════

@dataclass
class ValidationIssue:
    """验证问题——带严重度+定位+可自动修复标记
    
    从 nextX ValidationIssue 提取+增强:
    - severity: 4级(CRITICAL/HIGH/MEDIUM/LOW)
    - location: 代码定位(file+line+symbol)
    - autoFixable: 是否可自动修复
    - fix_hint: 修复建议(给人工参考或autoFix用)
    """
    rule_id: str = ""                    # 触发规则ID
    severity: IssueSeverity = IssueSeverity.MEDIUM
    message: str = ""                    # 问题描述
    location: Optional[CodeLocation] = None
    autoFixable: bool = False            # 是否可自动修复
    fix_hint: Optional[str] = None       # 修复建议
    context: Dict[str, Any] = field(default_factory=dict)  # 附加上下文
    
    def is_blocking(self) -> bool:
        """是否阻断执行"""
        return self.severity in (IssueSeverity.CRITICAL, IssueSeverity.HIGH)


# ═══════════════════════════════════════════════════════════
#  验证需求——从 nextX Requirement 提取
# ═══════════════════════════════════════════════════════════

@dataclass
class Requirement:
    """验证需求——含验收标准+优先级
    
    从 nextX Requirement 提取:
    - priority: must/should/could(RFC 2119语义)
    - acceptance_criteria: 验收标准列表
    - category: 需求分类(安全/性能/格式/逻辑)
    """
    id: str = ""
    title: str = ""
    description: str = ""
    priority: RequirementPriority = RequirementPriority.MUST
    category: str = ""                   # 安全/性能/格式/逻辑
    acceptance_criteria: List[str] = field(default_factory=list)
    
    def is_mandatory(self) -> bool:
        """是否必须满足"""
        return self.priority == RequirementPriority.MUST


# ═══════════════════════════════════════════════════════════
#  变更描述——验证的输入
# ═══════════════════════════════════════════════════════════

@dataclass
class ChangeDescription:
    """变更描述——Agent执行产生的变更
    
    验证器需要知道:
    - 哪些文件被改了
    - 变更类型(新增/修改/删除)
    - 变更内容摘要
    """
    file_path: str = ""
    change_type: str = "modify"   # "add" | "modify" | "delete"
    diff_summary: str = ""        # 变更摘要
    lines_added: int = 0
    lines_removed: int = 0
    
    def is_destructive(self) -> bool:
        """是否破坏性变更(删除>50行或delete类型)"""
        return self.change_type == "delete" or self.lines_removed > 50


# ═══════════════════════════════════════════════════════════
#  验证上下文——从 nextX ValidationContext 提取
# ═══════════════════════════════════════════════════════════

@dataclass
class ValidationContext:
    """验证上下文——验证所需全部信息
    
    从 nextX ValidationContext 提取:
    - changes: Agent的变更列表
    - requirements: 需验证的需求
    - knowledge: 项目知识(Phase 3的KnowledgeProvider提供)
    - config: 验证配置
    - agent_id: 执行Agent的ID
    - task: Agent的任务描述
    """
    changes: List[ChangeDescription] = field(default_factory=list)
    requirements: List[Requirement] = field(default_factory=list)
    knowledge: Dict[str, Any] = field(default_factory=dict)   # KnowledgeContext注入
    config: Dict[str, Any] = field(default_factory=dict)
    agent_id: Optional[str] = None
    task: Optional[str] = None
    
    def has_destructive_changes(self) -> bool:
        """是否包含破坏性变更"""
        return any(c.is_destructive() for c in self.changes)
    
    def affected_files(self) -> List[str]:
        """受影响文件列表"""
        return [c.file_path for c in self.changes]
    
    def mandatory_requirements(self) -> List[Requirement]:
        """必须满足的需求"""
        return [r for r in self.requirements if r.is_mandatory()]


# ═══════════════════════════════════════════════════════════
#  验证结果——从 nextX ValidationResult 提取
# ═══════════════════════════════════════════════════════════

@dataclass
class ValidationResult:
    """验证结果——汇总问题+状态
    
    从 nextX ValidationResult 提取+增强:
    - issues: 所有发现的问题
    - passed: 是否通过(无阻断性问题)
    - fixed_issues: autoFix已修复的问题数
    - validator_id: 执行的Validator ID
    """
    validator_id: str = ""
    passed: bool = True
    issues: List[ValidationIssue] = field(default_factory=list)
    fixed_issues: int = 0
    execution_time_ms: float = 0.0
    
    def blocking_issues(self) -> List[ValidationIssue]:
        """阻断性问题"""
        return [i for i in self.issues if i.is_blocking()]
    
    def warnings(self) -> List[ValidationIssue]:
        """警告性问题"""
        return [i for i in self.issues if i.severity == IssueSeverity.MEDIUM]
    
    def info(self) -> List[ValidationIssue]:
        """信息性问题"""
        return [i for i in self.issues if i.severity == IssueSeverity.LOW]
    
    def auto_fixable_issues(self) -> List[ValidationIssue]:
        """可自动修复的问题"""
        return [i for i in self.issues if i.autoFixable]
    
    def summary(self) -> str:
        """结果概要"""
        blocking = len(self.blocking_issues())
        total = len(self.issues)
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.validator_id}: {total} issues ({blocking} blocking, {self.fixed_issues} fixed)"


# ═══════════════════════════════════════════════════════════
#  IValidator — Protocol接口
# ═══════════════════════════════════════════════════════════

class IValidator(Protocol):
    """Validator接口——从 nextX IValidator 提取
    
    双通道设计:
    1. validate(ctx) → ValidationResult — 检测问题
    2. autoFix(ctx, issues) → ValidationResult — 自动修复
    
    autoFix可选——不是所有Validator都能自动修复。
    """
    def id(self) -> str: ...
    def name(self) -> str: ...
    def validate(self, ctx: ValidationContext) -> ValidationResult: ...
    def auto_fix(self, ctx: ValidationContext, issues: List[ValidationIssue]) -> ValidationResult: ...


# ═══════════════════════════════════════════════════════════
#  ValidatorRegistry——多Validator统一调度
# ═══════════════════════════════════════════════════════════

class ValidatorRegistry:
    """Validator注册器——注册+执行+协调
    
    设计模式:
    - 注册: register_validator() 加入Validator
    - 执行: run_validation() 按优先级顺序执行所有注册的Validator
    - 协调: 汇总所有Validator结果,判定最终pass/fail
    - 自动修复: run_auto_fix() 对autoFixable问题执行修复
    
    与Phase 1的关系:
    - compliance.py的ComplianceRule → 逐步重构为IValidator实现
    - guardrails.py的检查逻辑 → 逐步重构为IValidator实现
    """
    
    def __init__(self):
        self._validators: Dict[str, IValidator] = {}
        self._execution_order: List[str] = []
    
    def register_validator(self, validator: IValidator) -> None:
        """注册Validator"""
        vid = validator.id()
        self._validators[vid] = validator
        if vid not in self._execution_order:
            self._execution_order.append(vid)
        logger.info(f"注册Validator: {vid} ({validator.name()})")
    
    def unregister_validator(self, validator_id: str) -> bool:
        """取消注册"""
        if validator_id not in self._validators:
            return False
        del self._validators[validator_id]
        self._execution_order.remove(validator_id)
        return True
    
    def get_validator(self, validator_id: str) -> Optional[IValidator]:
        """获取Validator"""
        return self._validators.get(validator_id)
    
    def run_validation(
        self,
        ctx: ValidationContext,
        validator_ids: Optional[List[str]] = None,
    ) -> List[ValidationResult]:
        """执行验证——按注册顺序或指定顺序
        
        Args:
            ctx: 验证上下文
            validator_ids: 指定执行的Validator(None=全部)
        
        Returns:
            所有Validator的结果列表
        """
        results: List[ValidationResult] = []
        
        order = validator_ids or self._execution_order
        for vid in order:
            validator = self._validators.get(vid)
            if validator is None:
                logger.warning(f"Validator {vid} 未注册,跳过")
                continue
            
            result = validator.validate(ctx)
            results.append(result)
            logger.info(result.summary())
        
        return results
    
    def run_auto_fix(
        self,
        ctx: ValidationContext,
        issues: List[ValidationIssue],
    ) -> List[ValidationResult]:
        """执行自动修复——对autoFixable问题尝试修复
        
        只对autoFixable=True的问题调用对应Validator的autoFix()。
        """
        results: List[ValidationResult] = []
        
        # 按rule_id分组,找到对应Validator
        issues_by_validator: Dict[str, List[ValidationIssue]] = {}
        for issue in issues:
            if not issue.autoFixable:
                continue
            vid = issue.rule_id.split(":")[0] if ":" in issue.rule_id else issue.rule_id
            issues_by_validator.setdefault(vid, []).append(issue)
        
        for vid, vid_issues in issues_by_validator.items():
            validator = self._validators.get(vid)
            if validator is None:
                continue
            result = validator.auto_fix(ctx, vid_issues)
            results.append(result)
        
        return results
    
    def judge_results(self, results: List[ValidationResult]) -> bool:
        """判定最终pass/fail——任一Validator有blocking issue → fail"""
        for result in results:
            if result.blocking_issues():
                return False
        return True
    
    def list_validators(self) -> List[str]:
        """列出已注册的Validator"""
        return list(self._execution_order)
    
    def register_defaults(self) -> None:
        """注册默认Validator——ComplianceValidator + GuardrailsValidator

        自动获取全局 ComplianceEngine 和 GuardrailsPair 实例，
        无需手动注册即可拥有合规检查 + PII/安全护栏能力。
        """
        self.register_validator(ComplianceValidator())
        self.register_validator(GuardrailsValidator())
        logger.info("已注册默认Validator: compliance + guardrails")

    def stats(self) -> Dict[str, Any]:
        """注册器统计"""
        return {
            "total_validators": len(self._validators),
            "validator_ids": list(self._execution_order),
        }


# ═══════════════════════════════════════════════════════════
#  内置Validator——基础实现
# ═══════════════════════════════════════════════════════════

class DestructiveChangeValidator:
    """破坏性变更检测Validator
    
    检测:
    - 删除文件(delete类型)
    - 大量行删除(>50行)
    - 约束冲突(no_destructive=True时)
    """
    
    def id(self) -> str:
        return "destructive-change"
    
    def name(self) -> str:
        return "破坏性变更检测"
    
    def validate(self, ctx: ValidationContext) -> ValidationResult:
        issues: List[ValidationIssue] = []
        
        for change in ctx.changes:
            if change.is_destructive():
                issues.append(ValidationIssue(
                    rule_id="destructive-change:large-delete",
                    severity=IssueSeverity.CRITICAL,
                    message=f"破坏性变更: {change.file_path} ({change.change_type}, 删除{change.lines_removed}行)",
                    location=CodeLocation(file_path=change.file_path),
                    autoFixable=False,
                    fix_hint="减少删除范围或改用修改模式",
                ))
        
        passed = not any(i.is_blocking() for i in issues)
        return ValidationResult(
            validator_id=self.id(),
            passed=passed,
            issues=issues,
        )
    
    def auto_fix(self, ctx: ValidationContext, issues: List[ValidationIssue]) -> ValidationResult:
        """破坏性变更不可自动修复"""
        return ValidationResult(
            validator_id=self.id(),
            passed=False,
            issues=issues,
        )


class MaxChangesValidator:
    """变更数量限制Validator
    
    检测:
    - 单次变更超过max_changes限制
    - 过多文件同时修改
    """
    
    def __init__(self, max_changes: int = 50, max_files: int = 10):
        self._max_changes = max_changes
        self._max_files = max_files
    
    def id(self) -> str:
        return "max-changes"
    
    def name(self) -> str:
        return "变更数量限制"
    
    def validate(self, ctx: ValidationContext) -> ValidationResult:
        issues: List[ValidationIssue] = []
        
        total_lines = sum(c.lines_added + c.lines_removed for c in ctx.changes)
        total_files = len(ctx.changes)
        
        if total_lines > self._max_changes:
            issues.append(ValidationIssue(
                rule_id="max-changes:total-lines",
                severity=IssueSeverity.HIGH,
                message=f"变更行数超限: {total_lines}行 > {self._max_changes}行",
                autoFixable=False,
                fix_hint="缩小变更范围,分批提交",
            ))
        
        if total_files > self._max_files:
            issues.append(ValidationIssue(
                rule_id="max-changes:total-files",
                severity=IssueSeverity.MEDIUM,
                message=f"变更文件数超限: {total_files}个 > {self._max_files}个",
                autoFixable=False,
                fix_hint="减少同时修改的文件数",
            ))
        
        passed = not any(i.is_blocking() for i in issues)
        return ValidationResult(
            validator_id=self.id(),
            passed=passed,
            issues=issues,
        )
    
    def auto_fix(self, ctx: ValidationContext, issues: List[ValidationIssue]) -> ValidationResult:
        """变更数量不可自动修复"""
        return ValidationResult(
            validator_id=self.id(),
            passed=False,
            issues=issues,
        )


# ═══════════════════════════════════════════════════════════
#  ComplianceValidator——合规检查 Validator
# ═══════════════════════════════════════════════════════════

_SEVERITY_MAP = {
    "critical": IssueSeverity.CRITICAL,
    "high": IssueSeverity.HIGH,
    "medium": IssueSeverity.MEDIUM,
    "low": IssueSeverity.LOW,
}


class ComplianceValidator:
    """合规检查Validator——桥接 ComplianceEngine.scan_quick()

    将 ComplianceResult(passed=False) 转换为 ValidationIssue，
    使合规检查融入 ValidatorRegistry 的统一调度流程。

    调用链:
        validate(ctx) → 遍历 ctx.changes → scan_quick(content, path)
        → ComplianceResult → ValidationIssue → ValidationResult
    """

    def id(self) -> str:
        return "compliance"

    def name(self) -> str:
        return "合规检查"

    def validate(self, ctx: ValidationContext) -> ValidationResult:
        # 延迟导入避免循环依赖
        from harness.compliance import ComplianceEngine

        engine = ComplianceEngine()
        issues: List[ValidationIssue] = []

        for change in ctx.changes:
            # 只对有内容的变更执行扫描
            content = change.diff_summary
            if not content:
                continue
            results = engine.scan_quick(content, path=change.file_path)
            for cr in results:
                if cr.passed:
                    continue
                severity = _SEVERITY_MAP.get(cr.severity, IssueSeverity.MEDIUM)
                # 从 locations 提取行号
                location = None
                if cr.locations:
                    loc = cr.locations[0]
                    location = CodeLocation(
                        file_path=change.file_path,
                        line_number=loc.get("line"),
                        symbol_name=loc.get("match"),
                    )
                issues.append(ValidationIssue(
                    rule_id=f"compliance:{cr.rule_id}",
                    severity=severity,
                    message="; ".join(cr.findings) if cr.findings else cr.rule_id,
                    location=location,
                    autoFixable=False,
                    fix_hint=cr.remediation,
                ))

        passed = not any(i.is_blocking() for i in issues)
        return ValidationResult(
            validator_id=self.id(),
            passed=passed,
            issues=issues,
        )

    def auto_fix(self, ctx: ValidationContext, issues: List[ValidationIssue]) -> ValidationResult:
        """合规问题暂不支持自动修复"""
        return ValidationResult(
            validator_id=self.id(),
            passed=False,
            issues=issues,
        )


# ═══════════════════════════════════════════════════════════
#  GuardrailsValidator——PII/安全护栏 Validator
# ═══════════════════════════════════════════════════════════

_ACTION_SEVERITY_MAP = {
    "block": IssueSeverity.CRITICAL,
    "warn": IssueSeverity.MEDIUM,
    "redact": IssueSeverity.LOW,
    "replace": IssueSeverity.LOW,
}


class GuardrailsValidator:
    """PII/安全护栏Validator——桥接 GuardrailsPair.check_input/check_output

    将 GuardrailResult(blocked/warn/redact) 转换为 ValidationIssue，
    使护栏检测融入 ValidatorRegistry 的统一调度流程。

    调用链:
        validate(ctx) → 遍历 ctx.changes → check_output(diff_summary)
        → GuardrailResult → ValidationIssue → ValidationResult
    """

    def id(self) -> str:
        return "guardrails"

    def name(self) -> str:
        return "PII/安全护栏"

    def validate(self, ctx: ValidationContext) -> ValidationResult:
        # 延迟导入避免循环依赖
        from harness.guardrails import default_guardrails

        pair = default_guardrails()
        issues: List[ValidationIssue] = []

        for change in ctx.changes:
            content = change.diff_summary
            if not content:
                continue
            gr = pair.check_output(content)
            if not gr.blocked and not gr.warnings and not gr.violations:
                continue

            severity = _ACTION_SEVERITY_MAP.get(gr.action.value, IssueSeverity.MEDIUM)

            # 构造问题描述
            messages = []
            if gr.violations:
                messages.extend(gr.violations)
            if gr.warnings:
                messages.extend(gr.warnings)

            # 从 redactions 提取 PII 类型信息
            pii_types = [r.get("type", "unknown") for r in gr.redactions] if gr.redactions else []

            rule_id = "guardrails:output-check"
            if pii_types:
                rule_id = f"guardrails:pii-{','.join(sorted(pii_types))}"

            issues.append(ValidationIssue(
                rule_id=rule_id,
                severity=severity,
                message="; ".join(messages) if messages else f"护栏拦截: action={gr.action.value}",
                location=CodeLocation(file_path=change.file_path),
                autoFixable=False,
                fix_hint="检查内容中的敏感信息，使用环境变量或配置引用替代",
                context={"redactions": gr.redactions, "action": gr.action.value},
            ))

        passed = not any(i.is_blocking() for i in issues)
        return ValidationResult(
            validator_id=self.id(),
            passed=passed,
            issues=issues,
        )

    def auto_fix(self, ctx: ValidationContext, issues: List[ValidationIssue]) -> ValidationResult:
        """护栏问题暂不支持自动修复（PII脱敏应由 guardrails.redact 处理）"""
        return ValidationResult(
            validator_id=self.id(),
            passed=False,
            issues=issues,
        )


# ═══════════════════════════════════════════════════════════
#  单例工厂
# ═══════════════════════════════════════════════════════════

_registry: Optional[ValidatorRegistry] = None


def get_validator_registry() -> ValidatorRegistry:
    """获取全局Validator注册器(内置默认Validator + compliance/guardrails集成)"""
    global _registry
    if _registry is None:
        _registry = ValidatorRegistry()
        # 注册内置Validator
        _registry.register_validator(DestructiveChangeValidator())
        _registry.register_validator(MaxChangesValidator())
        # 注册 compliance + guardrails Validator
        _registry.register_defaults()
    return _registry
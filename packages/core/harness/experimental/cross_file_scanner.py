"""
harness-cook 跨文件合规扫描器 — @experimental

利用 impact_analyzer 的依赖图做跨文件合规检测：
  1. 先做影响分析——变更文件 → 直接/间接影响
  2. 沿依赖链传播合规检查——受影响文件也要合规扫描
  3. 返回 CrossFileScanResult（影响文件 + 合规违规 + 风险评级）

注意：此模块为 @experimental，API 可能变更。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any

from harness.types import Artifact, ComplianceRule, ComplianceResult, ScanContext
from harness.impact_types import FileImpactAnalyzer, ImpactAnalysis
from harness.bus import EventBus, BusEventType, BusEvent, get_bus

logger = logging.getLogger("harness.experimental.cross_file_scan")


class CrossFileRiskGrade(Enum):
    """跨文件合规风险评级——综合影响范围 + 违规严重性"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    CLEAN = "clean"


@dataclass
class FileCompliancePropagation:
    """单文件合规传播结果"""
    file_path: str
    is_change_file: bool = False
    impact_level: str = ""              # "direct" | "indirect" | "none"
    compliance_results: List[ComplianceResult] = field(default_factory=list)
    violation_count: int = 0
    highest_severity: str = ""


@dataclass
class CrossFileScanResult:
    """跨文件合规扫描结果"""
    impact_analysis: Optional[ImpactAnalysis] = None
    file_propagations: List[FileCompliancePropagation] = field(default_factory=list)
    total_violations: int = 0
    risk_grade: CrossFileRiskGrade = CrossFileRiskGrade.CLEAN
    affected_files: List[str] = field(default_factory=list)
    change_files: List[str] = field(default_factory=list)
    summary: str = ""

    def highest_severity_across_files(self) -> str:
        for sev in ("critical", "high", "medium", "low"):
            if any(fp.highest_severity == sev for fp in self.file_propagations):
                return sev
        return ""


class CrossFileScanEngine:
    """跨文件合规扫描引擎——影响分析 + 合规传播

    Phase 1: 影响分析 — 变更文件 → ImpactAnalyzer → 影响范围
    Phase 2: 合规传播 — 变更文件全规则 / 直接影响 security+architecture / 间接影响仅 critical
    """

    def __init__(self, impact_analyzer: FileImpactAnalyzer,
                 compliance_engine: Any = None, bus: Optional[EventBus] = None):
        self._impact_analyzer = impact_analyzer
        self._compliance_engine = compliance_engine
        self._bus = bus or get_bus()

    def scan(self, change_files: List[str], artifacts: List[Artifact],
             rules: Optional[List[ComplianceRule]] = None) -> CrossFileScanResult:
        result = CrossFileScanResult(change_files=change_files)

        # Phase 1: 影响分析
        if not self._impact_analyzer._built:
            self._impact_analyzer.build_graph_from_project()

        impact = self._impact_analyzer.analyze_impact(change_files)
        result.impact_analysis = impact
        result.affected_files = list(impact.direct_impacts | impact.indirect_impacts)
        self._bus.emit(BusEvent(type=BusEventType.COMPLIANCE_CHECK,
            execution_id="cross-file-scan",
            data={"change_files": change_files, "risk_level": impact.risk.level.value}))

        # Phase 2: 合规传播
        artifact_map: Dict[str, Artifact] = {a.path: a for a in artifacts}
        direct_set, indirect_set = impact.direct_impacts, impact.indirect_impacts

        for file_path in set(change_files) | direct_set | indirect_set:
            artifact = artifact_map.get(file_path)
            if not artifact:
                continue

            # 按影响层级选择扫描规则范围
            if file_path in change_files:
                scan_rules = rules
                impact_level, is_change = "none", True
            elif file_path in direct_set:
                scan_rules = [r for r in rules if r.category.value in ("security", "architecture")] if rules else None
                impact_level, is_change = "direct", False
            else:
                scan_rules = [r for r in rules if r.severity == "critical"] if rules else None
                impact_level, is_change = "indirect", False

            compliance_results = self._scan_artifact(artifact, scan_rules)
            prop = FileCompliancePropagation(
                file_path=file_path, is_change_file=is_change, impact_level=impact_level,
                compliance_results=compliance_results,
                violation_count=sum(1 for cr in compliance_results if not cr.passed))
            for sev in ("critical", "high", "medium", "low"):
                if any(not cr.passed and cr.severity == sev for cr in compliance_results):
                    prop.highest_severity = sev; break
            result.file_propagations.append(prop)

        result.total_violations = sum(fp.violation_count for fp in result.file_propagations)
        result.risk_grade = self._compute_risk_grade(impact, result)
        result.summary = f"[{result.risk_grade.value}] 变更{len(result.change_files)}文件 → 影响{len(result.affected_files)}文件, 违规{result.total_violations}项"
        return result

    def _scan_artifact(self, artifact: Artifact, rules: Optional[List[ComplianceRule]]) -> List[ComplianceResult]:
        if not rules:
            return []
        if self._compliance_engine:
            scan_ctx = ScanContext(artifacts=[artifact],
                dependency_graph=self._impact_analyzer.get_graph() if self._impact_analyzer._built else None)
            results = []
            for rule in rules:
                try:
                    r = self._compliance_engine.scan([artifact], [rule], scan_ctx)
                    results.extend(r if isinstance(r, list) else [r])
                except Exception as e:
                    logger.warning(f"Compliance scan failed for rule {rule.id}: {e}")
            return results
        # Fallback: RegexChecker
        from harness.compliance import RegexChecker
        checker, results = RegexChecker(), []
        scan_ctx = ScanContext(artifacts=[artifact])
        for rule in rules:
            if rule.matcher_type == "regex" and checker.matches_scope(rule, artifact):
                try:
                    results.append(checker.check(rule, artifact, scan_ctx))
                except Exception as e:
                    logger.warning(f"Regex compliance check failed for rule {rule.id}: {e}")
        return results

    def _compute_risk_grade(self, impact: ImpactAnalysis, result: CrossFileScanResult) -> CrossFileRiskGrade:
        if result.total_violations == 0: return CrossFileRiskGrade.CLEAN
        il, hs = impact.risk.level.value, result.highest_severity_across_files()
        if il == "high":   return CrossFileRiskGrade.CRITICAL if hs in ("critical","high") else CrossFileRiskGrade.HIGH
        if il == "medium": return CrossFileRiskGrade.HIGH if hs == "critical" else CrossFileRiskGrade.MEDIUM
        return CrossFileRiskGrade.MEDIUM if hs in ("critical","high") else CrossFileRiskGrade.LOW

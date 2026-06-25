"""
harness-cook 合规规则引擎 — 合规引擎与规则包

ComplianceEngine 是 Harness 的"法规执行者"——扫描产出物是否符合预定义的合规规则。
与 Gate 不同：Gate 是"质检门禁"（每次任务完成后检查），Compliance 是"法规扫描"（持续扫描）。

触发路径声明（E-5）：
  ComplianceEngine 只有一条触发路径：
    路径2: 事后合规扫描
      由 MCP harness_check 工具或 CLI 显式调用 ComplianceEngine.scan()
      → 对代码产物做静态规则扫描
      → 生成 ComplianceResult 报告（违规/通过 + 严重性 + 修复建议）
      → 不做实时拦截（不返回 BLOCK/WARN 决策）

  ComplianceEngine 不被以下路径触发：
    - DAGEngine：编排引擎做门禁检查（Gate），不是合规扫描
    - MCP hook_trigger：护栏路径做实时拦截，不是合规扫描

核心流程：
  1. 加载合规规则包（ComplianceRule集合）
  2. 构建 ScanContext（包含依赖图等跨文件上下文）
  3. 扫描 Artifact → 通过 MatcherRegistry 路由到 IRuleChecker
  4. 返回 ComplianceResult（通过/违规 + 严重性 + 修复建议）
  5. 违规事件通过 Bus 广播 → Audit 记录 → Learning 收集
"""

import logging
from pathlib import Path
from typing import Optional, Dict, List

from harness.types import (
    Artifact, ComplianceCategory, ComplianceRule, ComplianceResult, ScanContext,
)
from harness.bus import EventBus, BusEventType, BusEvent, get_bus
from harness.config import find_project_root
from harness.language_registry import LanguageRegistry
from harness.rule_checker import MatcherRegistry
from harness.pattern_registry import get_pattern_registry


logger = logging.getLogger("harness.compliance")


# ─── 规则包 ──────────────────────────────────────────

class RulePack:
    """
    合规规则包——一组相关规则的集合

    例如：security-rules 包含所有安全相关规则
          coding-rules 包含所有编码规范规则
    """

    def __init__(self, name: str, category: ComplianceCategory, rules: list[ComplianceRule]):
        self.name = name
        self.category = category
        self.rules = rules

    def add_rule(self, rule: ComplianceRule) -> None:
        self.rules.append(rule)

    def remove_rule(self, rule_id: str) -> bool:
        for i, r in enumerate(self.rules):
            if r.id == rule_id:
                self.rules.pop(i)
                return True
        return False

    def get_rule(self, rule_id: str) -> Optional[ComplianceRule]:
        for r in self.rules:
            if r.id == rule_id:
                return r
        return None


# ─── 合规引擎 ────────────────────────────────────────

class ComplianceEngine:
    """
    合规引擎——扫描产出物是否符合规则

    用法:
        engine = ComplianceEngine()
        engine.load_pack(security_pack)
        results = engine.scan(artifacts, project_root="/path/to/project")
        violations = [r for r in results if not r.passed]
    """

    def __init__(self, bus: Optional[EventBus] = None):
        self._packs: Dict[str, RulePack] = {}
        self._bus = bus or get_bus()
        # 确保 MatcherRegistry 已注册默认匹配器
        if not MatcherRegistry._matchers:
            MatcherRegistry.default()
        self._stats = {
            "total_scans": 0,
            "total_rules_applied": 0,
            "total_violations": 0,
            "total_auto_fixable": 0,
        }

        # ── E-6：消除自动注册路径 ──
        # ComplianceEngine 不再订阅 RECOMMENDATION 事件自动注册为规则。
        # Learning 产出 Insight（洞见），而非 ComplianceRule。
        # Insight 进入知识库供查看/决策，不自动生效。
        # 如果需要将 Insight 激活为规则，需用户手动确认（S-4）。
        # 以下订阅已移除：
        #   self._bus.subscribe(BusEventType.RECOMMENDATION, self._on_recommendation)

    # ─── 加载规则包 ──────────────────────────────────

    def load_pack(self, pack: RulePack) -> None:
        """加载规则包"""
        self._packs[pack.name] = pack
        logger.info(f"Loaded rule pack '{pack.name}' with {len(pack.rules)} rules "
                     f"(category: {pack.category.value})")

    def unload_pack(self, pack_name: str) -> bool:
        """卸载规则包"""
        if pack_name in self._packs:
            del self._packs[pack_name]
            logger.info(f"Unloaded rule pack '{pack_name}'")
            return True
        return False

    def get_pack(self, pack_name: str) -> Optional[RulePack]:
        """获取规则包"""
        return self._packs.get(pack_name)

    def list_packs(self) -> list[str]:
        """列出所有已加载的规则包"""
        return list(self._packs.keys())

    # ─── 自定义规则包自动发现 ──────────────────────────

    def discover_custom_packs(self, project_root: Optional[str] = None) -> int:
        """自动发现并加载自定义规则包

        搜索路径（按优先级）:
        1. 项目目录下的 .harness/rules/ （项目级规则）
        2. 用户目录下的 ~/.harness/rules/ （全局规则）

        规则包格式: Python 文件，包含 get_xxx_pack() 函数返回 RulePack 实例

        Args:
            project_root: 项目根目录（默认当前目录）

        Returns:
            发现并加载的规则包数量
        """
        import importlib.util

        loaded = 0
        search_dirs = []

        # 项目级规则（使用项目根目录检测）
        root = project_root or str(find_project_root())
        project_rules = Path(root) / ".harness" / "rules"
        search_dirs.append(project_rules)

        # 全局规则
        global_rules = Path.home() / ".harness" / "rules"
        search_dirs.append(global_rules)

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for py_file in search_dir.glob("*.py"):
                if py_file.name.startswith("_"):
                    continue
                try:
                    spec = importlib.util.spec_from_file_location(
                        f"harness_custom_rule_{py_file.stem}", str(py_file)
                    )
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    # 查找所有 get_xxx_pack 函数
                    for attr_name in dir(module):
                        if attr_name.startswith("get_") and attr_name.endswith("_pack"):
                            pack_fn = getattr(module, attr_name)
                            if callable(pack_fn):
                                pack = pack_fn()
                                if isinstance(pack, RulePack):
                                    self.load_pack(pack)
                                    loaded += 1
                                    logger.info(f"Discovered custom rule pack '{pack.name}' from {py_file}")
                except Exception as e:
                    logger.warning(f"Failed to load custom rule file {py_file}: {e}")

        return loaded

    # ─── 扫描 ────────────────────────────────────────

    def scan(
        self,
        artifacts: list[Artifact],
        categories: Optional[list[ComplianceCategory]] = None,
        severity_filter: Optional[list[str]] = None,
        project_root: Optional[str] = None,
        language_routing: Optional[Dict[str, str]] = None,
    ) -> list[ComplianceResult]:
        """
        扫描产出物

        Args:
            artifacts: 要扫描的产出物列表
            categories: 只扫描指定类别（空=全部）
            severity_filter: 只扫描指定严重性级别（空=全部）
            project_root: 项目根目录（用于构建依赖图，架构级规则需要）
            language_routing: 语言感知路由配置（language → matcher_type）。
                可用时，对未指定 matcher_type 的规则按文件语言自动路由。
                语言路由是建议性的，用户通过 matcher_type 显式指定时优先。

        Returns:
            ComplianceResult 列表（每个规则对每个产出物的结果）
        """
        results = []
        self._stats["total_scans"] += 1

        # 构建 ScanContext
        context = self._build_scan_context(artifacts, project_root)

        # 对架构级规则做全局检查（dependency_graph/cross_file），避免重复报同一违规
        # 先收集需要全局检查的规则
        global_rules: list[tuple[ComplianceRule, str]] = []  # (rule, pack_name)
        for pack_name, pack in self._packs.items():
            if categories and pack.category not in categories:
                continue
            for rule in pack.rules:
                if severity_filter and rule.severity not in severity_filter:
                    continue
                if rule.matcher_type in ("dependency_graph", "cross_file"):
                    global_rules.append((rule, pack_name))

        # 全局规则：只需对任意一个 artifact 执行一次，结果对所有相关 artifact 生效
        global_results: dict[str, ComplianceResult] = {}  # rule_id → result
        for rule, pack_name in global_rules:
            checker = MatcherRegistry.get(rule.matcher_type)
            if checker is None:
                logger.warning(f"No matcher for type '{rule.matcher_type}', falling back to regex")
                checker = MatcherRegistry.get("regex")

            # 找一个适用的 artifact 作为代表
            representative = None
            for artifact in artifacts:
                if checker.matches_scope(rule, artifact):
                    representative = artifact
                    break

            if representative:
                self._stats["total_rules_applied"] += 1
                result = checker.check(rule, representative, context)
                global_results[rule.id] = result
                results.append(result)

                if not result.passed:
                    self._stats["total_violations"] += 1
                    if rule.auto_fixable:
                        self._stats["total_auto_fixable"] += 1
                    self._bus.emit(BusEvent(
                        type=BusEventType.COMPLIANCE_FAIL,
                        execution_id="compliance-scan",
                        data={
                            "rule_id": rule.id,
                            "artifact_path": representative.path,
                            "severity": rule.severity,
                            "findings": result.findings,
                        },
                    ))

        # 单文件规则：逐个 artifact 检查
        for pack_name, pack in self._packs.items():
            if categories and pack.category not in categories:
                continue

            for rule in pack.rules:
                if severity_filter and rule.severity not in severity_filter:
                    continue
                # 跳过已处理的全局规则
                if rule.id in global_results:
                    continue

                matcher_type = rule.matcher_type

                for artifact in artifacts:
                    # ── 语言感知路由 ──────────────────────────────
                    # 当 matcher_type 是默认 regex 且 language_routing 可用时，
                    # 尝试按文件语言自动路由到更合适的引擎
                    effective_matcher_type = matcher_type
                    if language_routing and matcher_type == "regex":
                        # 推断 artifact 的语言
                        lang_result = LanguageRegistry.get_by_extension(artifact.path)
                        if lang_result:
                            language_name = lang_result[0]
                            routed_matcher = language_routing.get(language_name)
                            if routed_matcher:
                                # 路由建议存在 → 检查引擎是否可用
                                routed_checker = MatcherRegistry.get(routed_matcher)
                                if routed_checker is not None:
                                    effective_matcher_type = routed_matcher
                                    logger.debug(
                                        f"Language routing: {artifact.path} ({language_name}) "
                                        f"→ {routed_matcher} (override from regex)"
                                    )

                    checker = MatcherRegistry.get(effective_matcher_type)
                    if checker is None:
                        logger.warning(f"No matcher for type '{effective_matcher_type}', falling back to regex")
                        checker = MatcherRegistry.get("regex")

                    if not checker.matches_scope(rule, artifact):
                        continue

                    self._stats["total_rules_applied"] += 1
                    result = checker.check(rule, artifact, context)
                    results.append(result)

                    if not result.passed:
                        self._stats["total_violations"] += 1
                        if rule.auto_fixable:
                            self._stats["total_auto_fixable"] += 1

                        # 发射合规失败事件
                        self._bus.emit(BusEvent(
                            type=BusEventType.COMPLIANCE_FAIL,
                            execution_id="compliance-scan",
                            data={
                                "rule_id": rule.id,
                                "artifact_path": artifact.path,
                                "severity": rule.severity,
                                "findings": result.findings,
                            },
                        ))

        # 发射合规检查完成事件
        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if not r.passed)
        self._bus.emit(BusEvent(
            type=BusEventType.COMPLIANCE_CHECK,
            execution_id="compliance-scan",
            data={"passed": passed, "failed": failed, "total": len(results)},
        ))

        return results

    def scan_quick(
        self,
        content: str,
        path: str = "unknown",
        pack_names: list[str] | None = None,
    ) -> list[ComplianceResult]:
        """快速扫描——只扫描单个内容字符串，跳过架构级/跨文件规则

        与 scan() 的区别：
        - 跳过 dependency_graph 和 cross_file 类型的规则（这些需要全局上下文）
        - 不构建依赖图（节省初始化时间）
        - 只对单个 artifact 应用单文件规则

        pack_names 用于限定只扫描指定规则包（按包名匹配）；传 None 表示扫描全部
        已加载规则包。向后兼容：现有两参数调用方不传 pack_names，行为不变。
        """
        artifact = Artifact(type="code", path=path, content=content)
        results = []
        self._stats["total_scans"] += 1

        # 快速扫描不需要 ScanContext，用最小化 context
        context = ScanContext(
            artifacts=[artifact],
            project_root=None,
            dependency_graph=None,
        )

        # 只跑单文件规则，跳过全局/架构规则
        skip_matcher_types = {"dependency_graph", "cross_file"}
        # 按调用方指定的 pack_names 过滤规则包；None 表示扫描全部已加载包
        selected_packs = self._packs.items()
        if pack_names is not None:
            requested = set(pack_names)
            selected_packs = [
                (n, p) for n, p in selected_packs if n in requested
            ]
        for pack_name, pack in selected_packs:
            for rule in pack.rules:
                if rule.matcher_type in skip_matcher_types:
                    continue

                checker = MatcherRegistry.get(rule.matcher_type)
                if checker is None:
                    continue

                if not checker.matches_scope(rule, artifact):
                    continue

                self._stats["total_rules_applied"] += 1
                result = checker.check(rule, artifact, context)
                results.append(result)

                if not result.passed:
                    self._stats["total_violations"] += 1
                    if rule.auto_fixable:
                        self._stats["total_auto_fixable"] += 1

        return results

    # ─── 内部方法 ────────────────────────────────────

    def _build_scan_context(
        self,
        artifacts: list[Artifact],
        project_root: Optional[str] = None,
    ) -> ScanContext:
        """构建扫描上下文——包含依赖图"""
        dep_graph = None
        if project_root:
            try:
                from harness.impact_types import FileImpactAnalyzer
                analyzer = FileImpactAnalyzer(project_root=project_root)
                analyzer.build_graph_from_project()
                dep_graph = analyzer.get_graph() if hasattr(analyzer, 'get_graph') else analyzer._graph
                logger.info(f"Built dependency graph from {project_root}: "
                            f"{dep_graph.stats() if hasattr(dep_graph, 'stats') else 'unknown stats'}")
            except Exception as e:
                logger.warning(f"Failed to build dependency graph: {e}")

        return ScanContext(
            artifacts=artifacts,
            dependency_graph=dep_graph,
            project_root=project_root,
        )

    def _apply_rule(self, rule: ComplianceRule, artifact: Artifact) -> ComplianceResult:
        """应用单条规则到单个产出物——委托给 MatcherRegistry（向后兼容）"""
        checker = MatcherRegistry.get(rule.matcher_type)
        if checker is None:
            checker = MatcherRegistry.get("regex")
        context = ScanContext(artifacts=[artifact])
        return checker.check(rule, artifact, context)

    # ─── 统计 ────────────────────────────────────────

    def stats(self) -> dict:
        """合规引擎统计（E-6：learned_rules 已废弃，返回 0）"""
        return {
            **self._stats,
            "loaded_packs": len(self._packs),
            "total_rules": sum(len(p.rules) for p in self._packs.values()),
            "learned_rules": 0,  # E-6：消除自动注册路径后，learned-rules 包不再存在
        }

    # ── Learning 推荐 → 仅记录日志（E-6：消除自动注册路径）──

    def _on_recommendation(self, event: BusEvent) -> None:
        """
        处理学习引擎的推荐事件——仅记录日志，不自动注册为规则（E-6 重构）

        E-6 消除的自动注册路径：
          Learning → Recommendation(type="rule") → 自动注册为 ComplianceRule
          此路径已被消除——Learning 产出 Insight，而非 ComplianceRule。

        当前行为：
          只记录推荐事件到日志，供手动审核和决策。
          如果需要将 Insight 激活为规则，需用户手动确认（S-4）。
        """
        rec_type = event.data.get("type")
        confidence = event.data.get("confidence", 0.0)
        description = event.data.get("description", "")

        logger.info(
            f"Learning recommendation received (not auto-registered): "
            f"type={rec_type}, confidence={confidence:.2f}, "
            f"desc={description[:50]}"
        )


# ─── 内置规则包 ──────────────────────────────────────

def security_rule_pack() -> RulePack:
    """内置安全合规规则包——从 PatternRegistry 生成 SECURITY 类别规则

    模式来源变更（E-2 重构）：
    - 旧：security_rule_pack 内硬编码 ComplianceRule 列表
    - 新：从 PatternRegistry 获取 SECURITY 类别模式，自动转换为 ComplianceRule
    - PatternRegistry 是唯一定义源，合规层只做报告记录

    保留的合规特有规则（PatternRegistry 不覆盖）：
    - architecture_rule_pack、legal_rule_pack 等非 regex 模式的规则包不变
    """
    registry = get_pattern_registry()
    rules = registry.to_compliance_rules(category=ComplianceCategory.SECURITY)
    return RulePack("security", ComplianceCategory.SECURITY, rules)


def privacy_rule_pack() -> RulePack:
    """内置隐私合规规则包——从 PatternRegistry 生成 PRIVACY 类别规则

    模式来源变更（E-2 重构）：
    - 旧：privacy_rule_pack 内硬编码 3 条 ComplianceRule
    - 新：从 PatternRegistry 获取 PRIVACY 类别模式，自动转换为 ComplianceRule
    - 新增覆盖：中国 PII（身份证号/手机号/银行卡号）现在也从 PatternRegistry 生成
    """
    registry = get_pattern_registry()
    rules = registry.to_compliance_rules(category=ComplianceCategory.PRIVACY)
    return RulePack("privacy", ComplianceCategory.PRIVACY, rules)


def architecture_rule_pack() -> RulePack:
    """内置架构合规规则包"""
    rules = [
        ComplianceRule(
            id="arch-cross-domain-import",
            category=ComplianceCategory.ARCHITECTURE,
            pattern=r'from\s+(?:ui|view|controller)\s+import\s+(?:model|service|dao)',
            severity="medium",
            description="Cross-domain import violation (UI importing Model)",
            remediation="Follow layered architecture: UI → Service → DAO",
            languages=["python"],
        ),
        ComplianceRule(
            id="arch-global-state",
            category=ComplianceCategory.ARCHITECTURE,
            pattern=r'^\s*(?:var|let)\s+\w+\s*=\s*(?:null|undefined|{})\s*;?\s*$',
            severity="low",
            description="Global mutable state",
            remediation="Use dependency injection or context objects",
            languages=["javascript", "typescript"],
        ),
    ]
    return RulePack("architecture", ComplianceCategory.ARCHITECTURE, rules)


def legal_rule_pack() -> RulePack:
    """内置 AI 法律风险评估规则包"""
    from harness.rule_packs.legal import get_legal_pack
    return get_legal_pack()

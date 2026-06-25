"""
harness-cook 合规规则引擎 — 规则检查器

包含可插拔的匹配策略接口（IRuleChecker）及其实现：
- RegexChecker: 正则表达式匹配（默认，单文件模式，向后兼容）
- DependencyGraphChecker: 依赖图架构检查（跨文件，检测分层违规/循环依赖/过深链路）
- ASTChecker: AST 结构检查（检测 God Class/深继承等）
- CrossFileChecker: 跨文件模式检查（检测分散逻辑/重复抽象）
- MatcherRegistry: matcher_type → IRuleChecker 实例映射
"""

import ast
import fnmatch
import logging
import re
from collections import deque
from typing import Optional, Protocol, Any

from harness.types import (
    Artifact, ComplianceRule, ComplianceResult, ScanContext,
)
from harness.language_registry import LanguageRegistry


logger = logging.getLogger("harness.compliance")


# ═══════════════════════════════════════════════════════════
#  IRuleChecker — 可插拔匹配策略接口
# ═══════════════════════════════════════════════════════════

class IRuleChecker(Protocol):
    """规则检查器接口——可插拔的匹配策略

    与原有 _apply_rule 的区别：
    - _apply_rule：单文件 + 正则匹配
    - IRuleChecker：可接收完整 ScanContext，做跨文件分析
    """

    def check(
        self,
        rule: ComplianceRule,
        artifact: Artifact,
        context: ScanContext,
    ) -> ComplianceResult: ...

    def matches_scope(
        self,
        rule: ComplianceRule,
        artifact: Artifact,
    ) -> bool: ...


# ═══════════════════════════════════════════════════════════
#  RegexChecker — 正则匹配检查器（提取原有逻辑）
# ═══════════════════════════════════════════════════════════

class RegexChecker:
    """正则匹配检查器——提取原有 _apply_rule 逻辑，行为完全不变"""

    def check(self, rule: ComplianceRule, artifact: Artifact, context: ScanContext) -> ComplianceResult:
        """正则匹配——消费 matcher_config 中的可选策略键（case_sensitive/min_line_count/negative_pattern）。

        设计原则：matcher_config 是检查器的扩展点，每个检查器消费自己理解的键。
        默认大小写不敏感（IGNORECASE）以兼容绝大多数规则（如 SEC-001 需匹配 Password/PASSWORD）；
        需精确大小写的规则（如 CODE-001 的 [A-Z]）通过 case_sensitive=True 显式开启。
        """
        try:
            config = rule.matcher_config or {}

            # min_line_count：文件行数不足阈值时跳过（避免对短文件/空文件误报，如 LEGAL-001）
            min_line_count = config.get("min_line_count")
            if min_line_count is not None:
                if len(artifact.content.splitlines()) < min_line_count:
                    return ComplianceResult(
                        rule_id=rule.id,
                        passed=True,
                        severity=rule.severity,
                        findings=[],
                    )

            # case_sensitive：默认 False（IGNORECASE），True 则精确匹配
            case_sensitive = bool(config.get("case_sensitive", False))
            flags = re.MULTILINE | (0 if case_sensitive else re.IGNORECASE)
            pattern = re.compile(rule.pattern, flags)
            matches = pattern.findall(artifact.content)

            # negative_pattern：命中负向模式视为已妥善处理，不再报告（如 LEGAL-001 的 AI 免责声明）
            negative_pattern = config.get("negative_pattern")
            if matches and negative_pattern:
                if re.compile(negative_pattern, flags).search(artifact.content):
                    return ComplianceResult(
                        rule_id=rule.id,
                        passed=True,
                        severity=rule.severity,
                        findings=[],
                    )

            if matches:
                locations = []
                for match in pattern.finditer(artifact.content):
                    line_num = artifact.content[:match.start()].count('\n') + 1
                    locations.append({
                        "line": line_num,
                        "match": match.group(),
                        "start": match.start(),
                        "end": match.end(),
                    })

                return ComplianceResult(
                    rule_id=rule.id,
                    passed=False,
                    severity=rule.severity,
                    findings=[f"Found {len(matches)} instances of {rule.description}"],
                    remediation=rule.remediation,
                    locations=locations,
                )
            else:
                return ComplianceResult(
                    rule_id=rule.id,
                    passed=True,
                    severity=rule.severity,
                    findings=[],
                )
        except re.error as e:
            logger.error(f"Rule {rule.id} has invalid regex pattern: {e}")
            return ComplianceResult(
                rule_id=rule.id,
                passed=True,  # 正则错误时不误报
                severity=rule.severity,
                findings=[f"Rule pattern error: {e}"],
            )

    def matches_scope(self, rule: ComplianceRule, artifact: Artifact) -> bool:
        """检查产出物是否属于指定语言"""
        if not rule.languages:
            return True  # 空=全部语言
        for lang in rule.languages:
            config = LanguageRegistry.get(lang)
            if config:
                for ext in config["extensions"]:
                    if artifact.path.lower().endswith(ext):
                        return True
            # 旧规则可能用的语言名不在 LanguageRegistry 中（如 sql, shell, yaml 等）
            # 保留直接扩展名匹配作为 fallback
            legacy_exts = {
                "sql": [".sql"], "shell": [".sh", ".bash"], "yaml": [".yaml", ".yml"],
                "json": [".json"], "dockerfile": [".dockerfile"],
                "html": [".html", ".htm"], "css": [".css", ".scss"],
            }
            exts = legacy_exts.get(lang, [])
            if any(artifact.path.lower().endswith(ext) for ext in exts):
                return True
        return False


# ═══════════════════════════════════════════════════════════
#  DependencyGraphChecker — 依赖图架构检查器
# ═══════════════════════════════════════════════════════════

class DependencyGraphChecker:
    """依赖图架构检查器——利用 DependencyGraph 做跨文件架构检查

    支持的检查项（通过 matcher_config.check 指定）：
    - "layer_violation": 分层依赖方向违规（ARCH-001）
    - "cycle": 循环依赖（ARCH-002）
    - "deep_chain": 过深依赖链（ARCH-003）

    需要 ScanContext.dependency_graph 不为 None。
    """

    def check(self, rule: ComplianceRule, artifact: Artifact, context: ScanContext) -> ComplianceResult:
        """依赖图架构检查"""
        if context.dependency_graph is None:
            logger.warning(f"Rule {rule.id} requires dependency graph but ScanContext has none, skipping")
            return ComplianceResult(
                rule_id=rule.id,
                passed=True,
                severity=rule.severity,
                findings=["Skipped: no dependency graph available"],
            )

        config = rule.matcher_config
        check_type = config.get("check", "layer_violation")

        if check_type == "layer_violation":
            violations = self._check_layer_violation(config, context)
        elif check_type == "cycle":
            violations = self._check_cycles(context)
        elif check_type == "deep_chain":
            violations = self._check_deep_chain(config, context)
        else:
            logger.warning(f"Unknown dependency_graph check type: {check_type}")
            return ComplianceResult(
                rule_id=rule.id,
                passed=True,
                severity=rule.severity,
                findings=[f"Unknown check type: {check_type}"],
            )

        if violations:
            findings = [v.get("description", str(v)) for v in violations]
            locations = [{"line": 0, "match": v.get("description", ""), "start": 0, "end": 0} for v in violations]
            return ComplianceResult(
                rule_id=rule.id,
                passed=False,
                severity=rule.severity,
                findings=findings,
                remediation=rule.remediation,
                locations=locations,
            )
        else:
            return ComplianceResult(
                rule_id=rule.id,
                passed=True,
                severity=rule.severity,
                findings=[],
            )

    def matches_scope(self, rule: ComplianceRule, artifact: Artifact) -> bool:
        """依赖图规则对所有文件适用——按 layer_mapping 过滤时更精确"""
        # 依赖图规则不按语言过滤，它看的是整个项目的依赖结构
        return True

    # ─── 分层违规检测 ──────────────────────────────────

    def _classify_layer(self, file_path: str, layer_mapping: dict) -> Optional[str]:
        """将文件路径归类到架构层

        layer_mapping 的 pattern 格式为 */xxx/* ，表示路径中包含 xxx/ 目录段。
        fnmatch 不理解路径分隔符，所以改用路径段包含检测：
        将 */xxx/* 转换为 xxx/ 关键字，检查路径中是否包含该目录段。
        """
        for layer, patterns in layer_mapping.items():
            for pattern in patterns:
                # 将 glob pattern */xxx/* 转换为路径段关键字 xxx/
                # 提取中间的目录名
                keyword = pattern.replace("*/", "").replace("/*", "").strip("/")
                if keyword and (file_path.startswith(keyword + "/") or ("/" + keyword + "/") in file_path):
                    return layer
                # 也支持 fnmatch 精确匹配（如 views/*）
                if fnmatch.fnmatch(file_path, pattern):
                    return layer
        return None

    def _check_layer_violation(self, config: dict, context: ScanContext) -> list[dict]:
        """检查分层依赖方向违规——ARCH-001"""
        layer_mapping = config.get("layer_mapping", {})
        forbidden_directions = config.get("forbidden_directions", [])
        graph = context.dependency_graph

        violations = []
        # 遍历依赖图的所有节点
        nodes = graph._nodes if hasattr(graph, '_nodes') else {}
        for node_id, node in nodes.items():
            file_layer = self._classify_layer(node_id, layer_mapping)
            if not file_layer:
                continue
            # 检查该文件的依赖是否违反分层规则
            deps = node.dependencies if hasattr(node, 'dependencies') else set()
            for dep_path in deps:
                dep_layer = self._classify_layer(dep_path, layer_mapping)
                if not dep_layer:
                    continue
                for rule_dir in forbidden_directions:
                    if file_layer == rule_dir["from_layer"] and dep_layer == rule_dir["to_layer"]:
                        violations.append({
                            "source": node_id,
                            "source_layer": file_layer,
                            "target": dep_path,
                            "target_layer": dep_layer,
                            "description": f"{node_id} ({file_layer}) → {dep_path} ({dep_layer}): "
                                           f"{file_layer} layer directly imports {dep_layer} layer",
                        })
        return violations

    # ─── 循环依赖检测 ──────────────────────────────────

    def _check_cycles(self, context: ScanContext) -> list[dict]:
        """检测循环依赖——DFS 回溯法（ARCH-002）"""
        graph = context.dependency_graph
        nodes = graph._nodes if hasattr(graph, '_nodes') else {}
        cycles = []
        seen_cycles = set()  # 防止重复报告同一环

        def dfs(start: str, current: str, visited: set, path: list):
            deps = set()
            node = nodes.get(current)
            if node:
                deps = node.dependencies if hasattr(node, 'dependencies') else set()

            for dep in deps:
                if dep == start and len(path) > 1:
                    cycle_key = tuple(sorted(path))
                    if cycle_key not in seen_cycles:
                        seen_cycles.add(cycle_key)
                        cycles.append({
                            "cycle": path + [start],
                            "description": f"Circular dependency: {' → '.join(path + [start])}",
                        })
                elif dep not in visited:
                    dfs(start, dep, visited | {dep}, path + [dep])

        for node_id in nodes:
            dfs(node_id, node_id, {node_id}, [node_id])

        return cycles

    # ─── 过深依赖链检测 ────────────────────────────────

    def _check_deep_chain(self, config: dict, context: ScanContext) -> list[dict]:
        """检测过深依赖链——BFS 计算最大深度（ARCH-003）"""
        max_depth = config.get("max_depth", 5)
        graph = context.dependency_graph
        nodes = graph._nodes if hasattr(graph, '_nodes') else {}

        violations = []
        for node_id in nodes:
            # BFS 计算该节点的依赖链最大深度
            depth = 0
            visited = {node_id}
            queue = deque([(node_id, 0)])

            while queue:
                current, d = queue.popleft()
                if d > depth:
                    depth = d

                node = nodes.get(current)
                if node:
                    deps = node.dependencies if hasattr(node, 'dependencies') else set()
                    for dep in deps:
                        if dep not in visited:
                            visited.add(dep)
                            queue.append((dep, d + 1))

            if depth > max_depth:
                violations.append({
                    "file": node_id,
                    "depth": depth,
                    "max_allowed": max_depth,
                    "description": f"{node_id} has dependency chain depth {depth}, "
                                   f"exceeds max allowed {max_depth}",
                })

        return violations


# ═══════════════════════════════════════════════════════════
#  ASTChecker — AST 结构检查器
# ═══════════════════════════════════════════════════════════

class ASTChecker:
    """AST 结构检查器——多语言通用

    通过 LanguageRegistry 动态选择解析器：
    - Python: stdlib ast 模块
    - 其他语言: tree-sitter（根据 LanguageRegistry 注册的 grammar）

    支持的检查项（通过 matcher_config.ast_check 指定）：
    - "god_class": God Class / God Component 检测（ARCH-004）
    - "deep_inheritance": 深继承检测（ARCH-005）
    """

    # 支持的文件扩展名（与 CrossFileChecker 一致，LanguageRegistry 作为主入口）
    SUPPORTED_EXTENSIONS = (
        ".py", ".pyw", ".js", ".jsx", ".mjs", ".ts", ".tsx", ".vue",
        ".java", ".go", ".rs", ".rb", ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx",
        ".kt", ".kts",
    )

    def _get_extension(self, path: str) -> str:
        """获取文件扩展名"""
        lower = path.lower()
        for ext in self.SUPPORTED_EXTENSIONS:
            if lower.endswith(ext):
                return ext
        return ""

    def check(self, rule: ComplianceRule, artifact: Artifact, context: ScanContext) -> ComplianceResult:
        """AST 结构检查——根据文件类型选择解析器"""
        config = rule.matcher_config
        ast_check = config.get("ast_check", "god_class")

        lang_info = LanguageRegistry.get_by_extension(artifact.path)
        if lang_info is None:
            return ComplianceResult(
                rule_id=rule.id, passed=True, severity=rule.severity, findings=[],
            )

        lang_name, lang_config = lang_info

        if lang_name == "python":
            return self._check_python(rule, artifact, config, ast_check)
        elif lang_config.get("tree_sitter_module"):
            return self._check_tree_sitter(rule, artifact, config, ast_check, lang_name)
        else:
            return ComplianceResult(
                rule_id=rule.id, passed=True, severity=rule.severity, findings=[],
            )

    def matches_scope(self, rule: ComplianceRule, artifact: Artifact) -> bool:
        """AST 检查适用于所有有 tree-sitter grammar 或 Python stdlib 的语言"""
        if rule.languages:
            checker = RegexChecker()
            return checker.matches_scope(rule, artifact)
        lang_info = LanguageRegistry.get_by_extension(artifact.path)
        return lang_info is not None

    def _get_extension(self, path: str) -> str:
        """获取文件扩展名"""
        lower = path.lower()
        for ext in self.SUPPORTED_EXTENSIONS:
            if lower.endswith(ext):
                return ext
        return ""

    # ─── Python AST 检查 ──────────────────────────────────

    def _check_python(self, rule, artifact, config, ast_check) -> ComplianceResult:
        """Python AST 检查——使用 stdlib ast 模块"""
        try:
            tree = ast.parse(artifact.content)
        except SyntaxError:
            return ComplianceResult(
                rule_id=rule.id, passed=True, severity=rule.severity,
                findings=["Skipped: file has syntax errors"],
            )

        if ast_check == "god_class":
            violations = self._check_python_god_class(config, tree, artifact)
        elif ast_check == "deep_inheritance":
            violations = self._check_python_deep_inheritance(config, tree, artifact)
        else:
            return ComplianceResult(
                rule_id=rule.id, passed=True, severity=rule.severity,
                findings=[f"Unknown AST check: {ast_check}"],
            )

        return self._build_result(rule, violations)

    def _check_python_god_class(self, config: dict, tree: ast.AST, artifact: Artifact) -> list[dict]:
        """Python God Class 检测 — 支持 simple(阈值) 和 compound(ATFD+WMC+TCC) 模式"""
        god_class_mode = config.get("god_class_mode", "simple")

        if god_class_mode == "compound":
            from harness.god_class_metrics import GodClassMetrics, make_thresholds_from_config
            thresholds = make_thresholds_from_config(config)
            gcm = GodClassMetrics(thresholds)
            return gcm.check_python(tree, artifact)

        # simple 模式: 原有方法数阈值检测
        threshold = config.get("threshold", 15)
        violations = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = [
                    n for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                if len(methods) > threshold:
                    line = node.lineno if hasattr(node, 'lineno') else 0
                    violations.append({
                        "line": line,
                        "match": node.name,
                        "start": 0,
                        "end": 0,
                        "description": f"God Class '{node.name}' has {len(methods)} methods, "
                                       f"exceeds threshold {threshold}",
                    })
        return violations

    def _check_python_deep_inheritance(self, config: dict, tree: ast.AST, artifact: Artifact) -> list[dict]:
        """Python 深继承检测"""
        threshold = config.get("threshold", 4)
        class_bases: dict[str, list[str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                base_names = []
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        base_names.append(base.id)
                    elif isinstance(base, ast.Attribute):
                        base_names.append(base.attr)
                class_bases[node.name] = base_names

        def inheritance_depth(class_name: str, visited: set = None) -> int:
            if visited is None:
                visited = set()
            if class_name in visited or class_name not in class_bases:
                return 1
            visited.add(class_name)
            bases = class_bases[class_name]
            if not bases:
                return 1
            max_parent_depth = max(
                (inheritance_depth(b, visited) for b in bases), default=1,
            )
            return max_parent_depth + 1

        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                depth = inheritance_depth(node.name)
                external_bases = [
                    b for b in class_bases[node.name]
                    if b not in class_bases and b not in ("object", "ABC", "Exception", "BaseException")
                ]
                estimated_depth = depth + len(external_bases)
                if estimated_depth > threshold:
                    line = node.lineno if hasattr(node, 'lineno') else 0
                    violations.append({
                        "line": line,
                        "match": node.name,
                        "start": 0,
                        "end": 0,
                        "description": f"Class '{node.name}' has inheritance depth {estimated_depth}, "
                                       f"exceeds threshold {threshold} "
                                       f"(bases: {', '.join(class_bases[node.name])})",
                    })
        return violations

    # ─── JS/TS tree-sitter 检查 ─────────────────────────────

    def _check_tree_sitter(self, rule, artifact, config, ast_check, lang_name) -> ComplianceResult:
        """通用 tree-sitter AST 检查"""
        try:
            tree = self._parse_tree_sitter(artifact, lang_name)
        except Exception:
            return ComplianceResult(
                rule_id=rule.id, passed=True, severity=rule.severity,
                findings=["Skipped: tree-sitter parsing error"],
            )

        if tree is None:
            return ComplianceResult(
                rule_id=rule.id, passed=True, severity=rule.severity,
                findings=["Skipped: tree-sitter grammar not available"],
            )

        if ast_check == "god_class":
            violations = self._check_ts_god_class(config, tree, artifact)
        elif ast_check == "deep_inheritance":
            violations = self._check_ts_deep_inheritance(config, tree, artifact, lang_name)
        else:
            return ComplianceResult(
                rule_id=rule.id, passed=True, severity=rule.severity,
                findings=[f"Unknown AST check: {ast_check}"],
            )

        return self._build_result(rule, violations)

    def _parse_tree_sitter(self, artifact: Artifact, lang_name: str = None):
        """用 tree-sitter 解析任意语言文件"""
        from tree_sitter import Language, Parser

        if lang_name is None:
            lang_info = LanguageRegistry.get_by_extension(artifact.path)
            if lang_info is None:
                return None
            lang_name = lang_info[0]

        lang_obj = LanguageRegistry.get_tree_sitter_language(lang_name)
        if lang_obj is None:
            logger.debug(f"tree-sitter language for {lang_name} not available")
            return None

        parser = Parser(lang_obj)
        return parser.parse(artifact.content.encode())

    def _check_ts_god_class(self, config: dict, tree, artifact: Artifact) -> list[dict]:
        """通用 tree-sitter God Class / God Component 检测

        适用于所有有 tree-sitter grammar 的语言：
        - JS/TS: class_declaration 的 method_definition
        - Java: class_declaration 的 method_declaration
        - Go: 暂不支持 class（Go 没有 class）
        - Rust: 暂不支持 class
        - C/C++: struct 内的 function_definition
        - Kotlin: class_declaration 的 function_declaration

        支持 simple(方法数阈值) 和 compound(ATFD+WMC+TCC) 模式
        """
        god_class_mode = config.get("god_class_mode", "simple")

        if god_class_mode == "compound":
            from harness.god_class_metrics import GodClassMetrics, make_thresholds_from_config
            thresholds = make_thresholds_from_config(config)
            gcm = GodClassMetrics(thresholds)
            return gcm.check_tree_sitter(tree, artifact)

        # simple 模式: 原有方法数阈值检测
        threshold = config.get("threshold", 15)
        violations = []

        # 不同语言的类和方法节点类型
        class_types = {
            "javascript": ("class_declaration", "method_definition", "generator_method_definition"),
            "typescript": ("class_declaration", "method_definition", "generator_method_definition"),
            "java": ("class_declaration", "method_declaration"),
            "kotlin": ("class_declaration", "function_declaration"),
            "ruby": ("class", "method"),
            "c": ("struct_specifier", "function_definition"),
            "cpp": ("class_specifier", "function_definition"),
            "go": ("function_declaration",),  # Go 没有 class
            "rust": ("struct_item",),  # Rust 没有 class 方法
            "vue": ("class_declaration", "method_definition", "generator_method_definition"),
        }

        lang_info = LanguageRegistry.get_by_extension(artifact.path)
        lang_name = lang_info[0] if lang_info else "javascript"
        class_type, *method_types = class_types.get(lang_name, ("class_declaration", "method_definition"))

        def walk(node):
            if node.type == class_type:
                name_node = node.child_by_field_name("name")
                name = name_node.text.decode() if name_node else "anonymous"
                body = node.child_by_field_name("body")
                if body:
                    methods = [n for n in body.children if n.type in method_types]
                    if len(methods) > threshold:
                        violations.append({
                            "line": node.start_point[0] + 1,
                            "match": name,
                            "start": node.start_byte,
                            "end": node.end_byte,
                            "description": f"God Class '{name}' has {len(methods)} methods, "
                                           f"exceeds threshold {threshold}",
                        })
            for child in node.children:
                walk(child)

        walk(tree.root_node)
        return violations

    def _check_ts_deep_inheritance(self, config: dict, tree, artifact: Artifact, lang_name: str) -> list[dict]:
        """通用 tree-sitter 深继承检测

        适用于 Java/JS/TS/Kotlin/Ruby/C++ 等有继承概念的语言。
        Go/Rust/C 暂不支持（它们没有类继承）。
        """
        threshold = config.get("threshold", 4)

        # 不同语言的继承节点类型
        heritage_types = {
            "javascript": "class_heritage",
            "typescript": "class_heritage",
            "java": "superclass",
            "kotlin": "superclass_call_expression",
            "ruby": None,  # Ruby 用 < ParentName 语法
            "cpp": None,   # C++ 的继承在 class_specifier 的 base_clause
            "vue": "class_heritage",
        }

        # Java 特有的 extends 关键字在 class_declaration 的子节点中
        # class_declaration 的 superclass 字段直接给出基类名

        classes: dict[str, list[str]] = {}

        def walk(node):
            if node.type == "class_declaration":
                name_node = node.child_by_field_name("name")
                name = name_node.text.decode() if name_node else "anonymous"
                base_names = []

                # Java: superclass 字段直接给出基类名
                superclass = node.child_by_field_name("superclass")
                if superclass and superclass.type == "superclass":
                    # superclass 节点包含 extends 关键字 + 类型名
                    for sc in superclass.children:
                        if sc.type in ("type_identifier", "identifier"):
                            base_names.append(sc.text.decode())

                # JS/TS: class_heritage 节点
                heritage_type = heritage_types.get(lang_name)
                if heritage_type:
                    for child in node.children:
                        if child.type == heritage_type:
                            for hc in child.children:
                                if hc.type == "identifier":
                                    base_names.append(hc.text.decode())
                                elif hc.type == "member_expression":
                                    base_names.append(hc.text.decode().split(".")[-1])

                # Kotlin: 构造函数中的继承
                if lang_name == "kotlin":
                    for child in node.children:
                        if child.type == "superclass_call_expression":
                            for sc in child.children:
                                if sc.type == "type_identifier":
                                    base_names.append(sc.text.decode())

                # C++: base_clause
                if lang_name == "cpp":
                    for child in node.children:
                        if child.type == "base_clause":
                            for bc in child.children:
                                if bc.type == "type_identifier":
                                    base_names.append(bc.text.decode())

                classes[name] = base_names

            for child in node.children:
                walk(child)

        walk(tree.root_node)

        # 计算继承深度（同 Python 逻辑）
        def inheritance_depth(class_name: str, visited: set = None) -> int:
            if visited is None:
                visited = set()
            if class_name in visited or class_name not in classes:
                return 1
            visited.add(class_name)
            bases = classes[class_name]
            if not bases:
                return 1
            return max(inheritance_depth(b, visited) for b in bases) + 1

        # 不同语言的已知外部基类（不算深度）
        external_whitelist = {
            "javascript": ("Object", "Component", "React", "EventEmitter", "Error"),
            "typescript": ("Object", "Component", "React", "EventEmitter", "Error"),
            "java": ("Object", "Exception", "RuntimeException", "Thread", "ArrayList", "HashMap"),
            "kotlin": ("Any", "Exception", "Thread"),
            "ruby": ("Object", "BasicObject", "Exception"),
            "cpp": ("std::exception", "std::runtime_error"),
            "vue": ("Object", "Component", "React", "EventEmitter", "Error"),
        }
        whitelist = external_whitelist.get(lang_name, ("Object", "Exception", "Error"))

        violations = []
        for name, bases in classes.items():
            depth = inheritance_depth(name)
            external_bases = [b for b in bases if b not in classes and b not in whitelist]
            estimated_depth = depth + len(external_bases)
            if estimated_depth > threshold:
                violations.append({
                    "line": 0,
                    "match": name,
                    "start": 0,
                    "end": 0,
                    "description": f"Class '{name}' has inheritance depth {estimated_depth}, "
                                   f"exceeds threshold {threshold} "
                                   f"(bases: {', '.join(bases)})",
                })
        return violations

    # ─── 通用结果构建 ──────────────────────────────────

    def _build_result(self, rule, violations) -> ComplianceResult:
        """构建 ComplianceResult"""
        if violations:
            findings = [v["description"] for v in violations]
            return ComplianceResult(
                rule_id=rule.id, passed=False, severity=rule.severity,
                findings=findings, remediation=rule.remediation, locations=violations,
            )
        return ComplianceResult(
            rule_id=rule.id, passed=True, severity=rule.severity, findings=[],
        )


# ═══════════════════════════════════════════════════════════
#  CrossFileChecker — 跨文件模式检查器
# ═══════════════════════════════════════════════════════════

class CrossFileChecker:
    """跨文件模式检查器——需要 ScanContext 中多个 artifact

    支持 Python + JS/TS/Vue 的跨文件分析。

    支持的检查项（通过 matcher_config.check 指定）：
    - "scattered_logic": 分散逻辑检测（ARCH-006）
    - "duplicate_abstraction": 重复抽象检测（ARCH-007）
    """

    SUPPORTED_EXTENSIONS = (".py", ".js", ".jsx", ".mjs", ".ts", ".tsx", ".vue")

    def check(self, rule: ComplianceRule, artifact: Artifact, context: ScanContext) -> ComplianceResult:
        """跨文件模式检查"""
        config = rule.matcher_config
        check_type = config.get("check", "scattered_logic")

        if check_type == "scattered_logic":
            violations = self._check_scattered_logic(config, artifact, context)
        elif check_type == "duplicate_abstraction":
            violations = self._check_duplicate_abstraction(config, artifact, context)
        else:
            logger.warning(f"Unknown cross_file check type: {check_type}")
            return ComplianceResult(
                rule_id=rule.id,
                passed=True,
                severity=rule.severity,
                findings=[f"Unknown check: {check_type}"],
            )

        if violations:
            findings = [v["description"] for v in violations]
            return ComplianceResult(
                rule_id=rule.id,
                passed=False,
                severity=rule.severity,
                findings=findings,
                remediation=rule.remediation,
                locations=violations,
            )
        else:
            return ComplianceResult(
                rule_id=rule.id,
                passed=True,
                severity=rule.severity,
                findings=[],
            )

    def matches_scope(self, rule: ComplianceRule, artifact: Artifact) -> bool:
        """跨文件规则按 scope 限定范围"""
        scope = rule.matcher_config.get("scope", [])
        if not scope:
            return True  # 无 scope 限定 = 全部文件
        for pattern in scope:
            if fnmatch.fnmatch(artifact.path, pattern):
                return True
        return False

    # ─── 分散逻辑检测 ──────────────────────────────────

    def _check_scattered_logic(self, config: dict, artifact: Artifact, context: ScanContext) -> list[dict]:
        """分散逻辑检测——同一概念在多个文件中分散实现（ARCH-006）

        支持 Python + JS/TS/Vue 文件。
        """
        spread_threshold = config.get("spread_threshold", 3)
        scope = config.get("scope", [])

        ext = self._get_extension(artifact.path)
        if not ext:
            return []

        # 提取当前文件中的概念关键词
        concepts: dict[str, list[str]] = {}
        try:
            names = self._extract_concept_names(artifact)
        except Exception:
            names = self._extract_concept_names_regex(artifact)

        for name in names:
            if len(name) > 3:
                concepts[name] = [artifact.path]

        # 在其他 artifacts 中搜索同一概念
        for other_artifact in context.artifacts:
            if other_artifact.path == artifact.path:
                continue
            if scope:
                in_scope = any(fnmatch.fnmatch(other_artifact.path, p) for p in scope)
                if not in_scope:
                    continue
            other_ext = self._get_extension(other_artifact.path)
            if not other_ext:
                continue
            try:
                other_names = self._extract_concept_names(other_artifact)
            except Exception:
                other_names = self._extract_concept_names_regex(other_artifact)
            for name in other_names:
                if name in concepts and other_artifact.path not in concepts[name]:
                    concepts[name].append(other_artifact.path)

        # 检测分散逻辑
        violations = []
        for concept, files in concepts.items():
            if len(files) > spread_threshold:
                violations.append({
                    "line": 0,
                    "match": concept,
                    "start": 0,
                    "end": 0,
                    "description": f"Concept '{concept}' scattered across {len(files)} files: "
                                   f"{', '.join(files)}",
                })
        return violations

    # ─── 重复抽象检测 ──────────────────────────────────

    def _check_duplicate_abstraction(self, config: dict, artifact: Artifact, context: ScanContext) -> list[dict]:
        """重复抽象检测——函数结构高度相似（ARCH-007）

        支持 Python + JS/TS/Vue 文件。
        """
        similarity_threshold = config.get("similarity_threshold", 0.8)
        scope = config.get("scope", [])

        ext = self._get_extension(artifact.path)
        if not ext:
            return []

        # 提取当前文件中所有函数签名特征
        current_signatures: dict[str, dict] = {}
        try:
            current_signatures = self._extract_function_signatures(artifact)
        except Exception:
            current_signatures = self._extract_function_signatures_regex(artifact)

        # 在其他 artifacts 中搜索相似函数
        violations = []
        for other_artifact in context.artifacts:
            if other_artifact.path == artifact.path:
                continue
            if scope:
                in_scope = any(fnmatch.fnmatch(other_artifact.path, p) for p in scope)
                if not in_scope:
                    continue
            other_ext = self._get_extension(other_artifact.path)
            if not other_ext:
                continue
            try:
                other_signatures = self._extract_function_signatures(other_artifact)
            except Exception:
                other_signatures = self._extract_function_signatures_regex(other_artifact)

            for other_name, other_feat in other_signatures.items():
                for cur_name, cur_feat in current_signatures.items():
                    if cur_name == other_name:
                        continue
                    cur_sim = self._feature_similarity(
                        cur_feat.get("arg_count", 0), other_feat.get("arg_count", 0),
                        cur_feat.get("returns", ""), other_feat.get("returns", ""),
                        cur_feat.get("body_line_count", 1), other_feat.get("body_line_count", 1),
                    )
                    if cur_sim >= similarity_threshold:
                        violations.append({
                            "line": 0,
                            "match": f"{cur_name} ≈ {other_name}",
                            "start": 0,
                            "end": 0,
                            "description": f"Duplicate abstraction: "
                                           f"'{cur_name}' in {artifact.path} ≈ "
                                           f"'{other_name}' in {other_artifact.path} "
                                           f"(similarity: {cur_sim:.0%})",
                        })
                        break  # 每个 other 函数只报一次

        return violations

    def _feature_similarity(
        self,
        arg_count_a: int, arg_count_b: int,
        returns_a: str, returns_b: str,
        body_lines_a: int, body_lines_b: int,
    ) -> float:
        """计算两个函数的签名特征相似度（0.0 ~ 1.0）

        特征维度：
        - 参数数量相似度（权重 0.4）
        - 返回值类型匹配（权重 0.3）
        - 函数体行数相似度（权重 0.3）
        """
        # 参数数量相似度
        max_args = max(arg_count_a, arg_count_b, 1)
        arg_sim = 1 - abs(arg_count_a - arg_count_b) / max_args

        # 返回值类型匹配
        if returns_a and returns_b:
            ret_sim = 1.0 if returns_a == returns_b else 0.0
        elif not returns_a and not returns_b:
            ret_sim = 1.0  # 都没有返回值声明
        else:
            ret_sim = 0.0  # 一个有返回值声明，一个没有

        # 函数体行数相似度
        max_lines = max(body_lines_a, body_lines_b, 1)
        line_sim = 1 - abs(body_lines_a - body_lines_b) / max_lines

        return 0.4 * arg_sim + 0.3 * ret_sim + 0.3 * line_sim

    # ─── 辅助方法 ──────────────────────────────────────

    def _get_extension(self, path: str) -> str:
        """获取文件扩展名"""
        lower = path.lower()
        for ext in self.SUPPORTED_EXTENSIONS:
            if lower.endswith(ext):
                return ext
        return ""

    def _extract_concept_names(self, artifact: Artifact) -> list[str]:
        """从 artifact 中提取概念名称（类名/函数名/组件名）"""
        ext = self._get_extension(artifact.path)
        if ext == ".py":
            return self._extract_concept_names_python(artifact)
        elif ext in (".js", ".jsx", ".mjs", ".ts", ".tsx", ".vue"):
            return self._extract_concept_names_js_ts(artifact)
        return []

    def _extract_concept_names_python(self, artifact: Artifact) -> list[str]:
        """Python 概念名称提取"""
        try:
            tree = ast.parse(artifact.content)
        except SyntaxError:
            return []
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                names.append(node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.append(node.name)
        return names

    def _extract_concept_names_js_ts(self, artifact: Artifact) -> list[str]:
        """JS/TS 概念名称提取——使用 tree-sitter"""
        try:
            tree = ASTChecker()._parse_tree_sitter(artifact, lang_name="javascript")
        except Exception:
            return self._extract_concept_names_regex(artifact)
        if tree is None:
            return self._extract_concept_names_regex(artifact)

        names = []
        def walk(node):
            if node.type == "class_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    names.append(name_node.text.decode())
            elif node.type == "function_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    names.append(name_node.text.decode())
            elif node.type == "lexical_declaration" or node.type == "variable_declaration":
                for child in node.children:
                    if child.type == "variable_declarator":
                        name_node = child.child_by_field_name("name")
                        if name_node and name_node.type == "identifier":
                            # 如 const MyComponent = () => {}
                            val = child.child_by_field_name("value")
                            if val and val.type in ("arrow_function", "function_expression", "call_expression"):
                                names.append(name_node.text.decode())
            for child in node.children:
                walk(child)
        walk(tree.root_node)
        return names

    def _extract_concept_names_regex(self, artifact: Artifact) -> list[str]:
        """正则 fallback 提取概念名称"""
        names = []
        # Python class/function
        for match in re.finditer(r'class\s+(\w+)', artifact.content):
            names.append(match.group(1))
        for match in re.finditer(r'def\s+(\w+)', artifact.content):
            names.append(match.group(1))
        # JS/TS class/function
        for match in re.finditer(r'class\s+(\w+)', artifact.content):
            names.append(match.group(1))
        for match in re.finditer(r'function\s+(\w+)', artifact.content):
            names.append(match.group(1))
        # JS arrow function const Xxx = () => {}
        for match in re.finditer(r'const\s+(\w+)\s*=\s*\(', artifact.content):
            names.append(match.group(1))
        return names

    def _extract_function_signatures(self, artifact: Artifact) -> dict[str, dict]:
        """从 artifact 中提取函数签名特征"""
        ext = self._get_extension(artifact.path)
        if ext == ".py":
            return self._extract_signatures_python(artifact)
        elif ext in (".js", ".jsx", ".mjs", ".ts", ".tsx", ".vue"):
            return self._extract_signatures_js_ts(artifact)
        return {}

    def _extract_signatures_python(self, artifact: Artifact) -> dict[str, dict]:
        """Python 函数签名提取"""
        try:
            tree = ast.parse(artifact.content)
        except SyntaxError:
            return {}
        signatures = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                arg_count = len(node.args.args)
                returns = ""
                if node.returns:
                    if isinstance(node.returns, ast.Name):
                        returns = node.returns.id
                    elif isinstance(node.returns, ast.Constant):
                        returns = str(node.returns.value)
                signatures[node.name] = {
                    "arg_count": arg_count,
                    "returns": returns,
                    "body_line_count": len(node.body),
                    "file": artifact.path,
                }
        return signatures

    def _extract_signatures_js_ts(self, artifact: Artifact) -> dict[str, dict]:
        """JS/TS 函数签名提取——使用 tree-sitter"""
        try:
            checker = ASTChecker()
            lang_info = LanguageRegistry.get_by_extension(artifact.path)
            lang_name = lang_info[0] if lang_info else "javascript"
            tree = checker._parse_tree_sitter(artifact, lang_name=lang_name)
        except Exception:
            return self._extract_signatures_regex(artifact)
        if tree is None:
            return self._extract_signatures_regex(artifact)

        signatures = {}
        def walk(node):
            if node.type == "method_definition":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = name_node.text.decode()
                    params = node.child_by_field_name("parameters")
                    arg_count = len([c for c in (params.children if params else []) if c.type == "identifier"]) if params else 0
                    body = node.child_by_field_name("body")
                    body_lines = (body.end_point[0] - body.start_point[0] + 1) if body else 1
                    signatures[name] = {
                        "arg_count": arg_count,
                        "returns": "",
                        "body_line_count": body_lines,
                        "file": artifact.path,
                    }
            elif node.type == "function_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = name_node.text.decode()
                    params = node.child_by_field_name("parameters")
                    arg_count = len([c for c in (params.children if params else []) if c.type == "identifier"]) if params else 0
                    body = node.child_by_field_name("body")
                    body_lines = (body.end_point[0] - body.start_point[0] + 1) if body else 1
                    signatures[name] = {
                        "arg_count": arg_count,
                        "returns": "",
                        "body_line_count": body_lines,
                        "file": artifact.path,
                    }
            for child in node.children:
                walk(child)
        walk(tree.root_node)
        return signatures

    def _extract_signatures_regex(self, artifact: Artifact) -> dict[str, dict]:
        """正则 fallback 提取函数签名"""
        signatures = {}
        # Python
        for match in re.finditer(r'def\s+(\w+)\s*\(([^)]*)\)', artifact.content):
            name = match.group(1)
            args = match.group(2).split(",") if match.group(2) else []
            arg_count = len([a.strip() for a in args if a.strip() and a.strip() != "self"])
            body_start = match.end()
            # 估算函数体行数
            body_lines = artifact.content[body_start:].split("\n")[0:30]
            meaningful_lines = [l for l in body_lines if l.strip() and not l.strip().startswith("#")]
            signatures[name] = {"arg_count": arg_count, "returns": "", "body_line_count": len(meaningful_lines), "file": artifact.path}
        # JS function
        for match in re.finditer(r'function\s+(\w+)\s*\(([^)]*)\)', artifact.content):
            name = match.group(1)
            args = match.group(2).split(",") if match.group(2) else []
            arg_count = len([a.strip() for a in args if a.strip()])
            signatures[name] = {"arg_count": arg_count, "returns": "", "body_line_count": 5, "file": artifact.path}
        # JS arrow function
        for match in re.finditer(r'const\s+(\w+)\s*=\s*\(([^)]*)\)\s*=>', artifact.content):
            name = match.group(1)
            args = match.group(2).split(",") if match.group(2) else []
            arg_count = len([a.strip() for a in args if a.strip()])
            signatures[name] = {"arg_count": arg_count, "returns": "", "body_line_count": 5, "file": artifact.path}
        return signatures


# ═══════════════════════════════════════════════════════════
#  MatcherRegistry — 匹配器注册表
# ═══════════════════════════════════════════════════════════

class MatcherRegistry:
    """匹配器注册表——matcher_type → IRuleChecker 实例映射"""

    _matchers: dict[str, IRuleChecker] = {}

    @classmethod
    def register(cls, matcher_type: str, checker: IRuleChecker) -> None:
        """注册匹配器"""
        cls._matchers[matcher_type] = checker

    @classmethod
    def get(cls, matcher_type: str) -> Optional[IRuleChecker]:
        """获取匹配器"""
        return cls._matchers.get(matcher_type)

    @classmethod
    def default(cls) -> None:
        """注册内置匹配器 + 初始化语言注册表

        外部引擎集成使用 try/except ImportError 注册：
        SDK 未安装 → 不注册 → 规则回退 RegexChecker
        """
        if not LanguageRegistry._languages:
            LanguageRegistry.default()
        cls.register("regex", RegexChecker())
        cls.register("dependency_graph", DependencyGraphChecker())
        cls.register("ast", ASTChecker())
        cls.register("cross_file", CrossFileChecker())

        # ─── 外部引擎集成注册（try/except ImportError）───
        # 护栏层：Guardrails AI
        try:
            from harness.integrations.guardrails_ai_checker import GuardrailsAIChecker
            cls.register("guardrails_ai", GuardrailsAIChecker())
        except ImportError:
            logger.debug("guardrails-ai SDK not installed — GuardrailsAIChecker not registered")

        # 护栏层：Helicone
        try:
            from harness.integrations.helicone_checker import HeliconeMiddlewareChecker
            cls.register("helicone", HeliconeMiddlewareChecker())
        except ImportError:
            logger.debug("helicone SDK not installed — HeliconeMiddlewareChecker not registered")

        # ─── 合规层引擎注册（try/except ImportError）───
        # SonarQube（引用模式——从 CI 缓存检索结果）
        try:
            from harness.integrations.sonarqube_checker import SonarQubeChecker
            cls.register("sonarqube", SonarQubeChecker())
        except ImportError:
            logger.debug("sonarqube SDK not installed — SonarQubeChecker not registered")

        # OPA（实时策略评估）
        try:
            from harness.integrations.opa_checker import OPAChecker
            cls.register("opa", OPAChecker())
        except ImportError:
            logger.debug("opa SDK not installed — OPAChecker not registered")

        # ArchUnit（Java 架构合规）
        try:
            from harness.integrations.archunit_checker import ArchUnitChecker
            cls.register("archunit", ArchUnitChecker())
        except ImportError:
            logger.debug("archunit SDK not installed — ArchUnitChecker not registered")

        # DepCruiser（JS/TS 依赖合规）
        try:
            from harness.integrations.dep_cruiser_checker import DepCruiserChecker
            cls.register("dep_cruiser", DepCruiserChecker())
        except ImportError:
            logger.debug("dep-cruiser SDK not installed — DepCruiserChecker not registered")

        # ─── 护栏层引擎注册（新增）───
        try:
            from harness.integrations.nemo_guardrails_checker import NeMoGuardrailsChecker
            cls.register("nemo", NeMoGuardrailsChecker())
        except ImportError:
            logger.debug("nemoguardrails SDK not installed — NeMoGuardrailsChecker not registered")

        try:
            from harness.integrations.llama_guard_checker import LlamaGuardChecker
            cls.register("llama-guard", LlamaGuardChecker())
        except ImportError:
            logger.debug("transformers/torch not installed — LlamaGuardChecker not registered")

    @classmethod
    def get_by_language(cls, language: str) -> Optional[IRuleChecker]:
        """语言感知路由——根据文件语言建议最佳合规引擎

        路由表：
        - java → archunit
        - javascript / typescript → dep_cruiser
        - 通用 → opa（如果可用）

        语言路由是建议性的，用户可通过 matcher_type 显式覆盖。
        引擎不可用时回退标准路由（regex → dependency_graph）。

        Args:
            language: 语言名称（如 "java", "javascript", "typescript"）

        Returns:
            对应的 IRuleChecker 实例，或 None
        """
        LANGUAGE_ROUTING = {
            "java": "archunit",
            "javascript": "dep_cruiser",
            "typescript": "dep_cruiser",
            "vue": "dep_cruiser",
        }

        # 查路由表
        preferred = LANGUAGE_ROUTING.get(language)
        if preferred:
            checker = cls.get(preferred)
            if checker is not None:
                return checker

        # 回退：opa（通用策略引擎）
        opa = cls.get("opa")
        if opa is not None:
            return opa

        # 最终回退：regex
        return cls.get("regex")

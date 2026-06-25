"""
影响分析实现——文件级影响分析器

从 impact_types.py 分离的实现模块，满足 Phase 4 开发计划交付物要求:
  packages/core/harness/impact_analyzer.py — 影响分析基础实现(文件级)

核心能力:
  1. 从项目目录构建依赖图(Python/JS/TS/Java/Go/Rust/Kotlin/Ruby/C/C++ import扫描)
  2. 变更文件 → 反向依赖 → 直接影响
  3. 传递性依赖(BFS) → 间接影响
  4. 风险分级(HIGH/MEDIUM/LOW) + 审批建议

与 harness 其他模块协作:
  - 高风险变更 → gates.py 触发额外门禁检查
  - 影响分析结果 → audit.py 记录决策轨迹
  - validator_types.py 的 IValidator 可引用影响分析结果

架构分层:
  - impact_types.py: 纯类型定义(DependencyNode/DependencyGraph/ImpactRiskLevel/ImpactAnalysis/IImpactAnalyzer)
  - impact_analyzer.py: 实现逻辑(FileImpactAnalyzer + get_impact_analyzer)
  - 类型定义与实现分离，避免 types 模块膨胀，同时保持向后兼容的重导出
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Set

# 从类型模块导入纯数据结构(无循环依赖风险)
from harness.impact_types import (
    CallGraphNode,
    DependencyGraph,
    DependencyNode,
    ImpactAnalysis,
    ImpactRisk,
    ImpactRiskLevel,
    IImpactAnalyzer,
)

logger = logging.getLogger("harness.impact")


# ═══════════════════════════════════════════════════════════
#  文件级影响分析器——核心实现
# ═══════════════════════════════════════════════════════════

class FileImpactAnalyzer:
    """文件级影响分析器——基于依赖图做影响传播

    设计:
    1. 从项目目录构建依赖图(import关系)
    2. 变更文件 → 查找反向依赖 → 直接影响
    3. 直接影响的反向依赖 → 间接影响(BFS 2层)
    4. 汇总风险级别

    风险分级规则:
    - HIGH: 入口文件变更 或 影响>5个文件
    - MEDIUM: 影响2-5个文件
    - LOW: 影响0-1个文件

    首期简化:
    - import扫描只做简单文本匹配(不做AST解析)
    - 不做函数级调用图
    """

    def __init__(self, project_root: Optional[str] = None,
                 high_threshold: int = 5, medium_threshold: int = 1):
        self._project_root = project_root or os.getcwd()
        self._graph = DependencyGraph()
        self._built = False
        self._high_threshold = high_threshold    # 影响>此值=HIGH风险
        self._medium_threshold = medium_threshold  # 影响>此值=MEDIUM风险

    # ─── 依赖图构建 ───────────────────────────────────

    def build_graph_from_project(self, root: Optional[str] = None) -> None:
        """从项目目录构建依赖图——扫描所有支持语言的 import

        支持 Python + JS/TS + Java + Go + Rust + Ruby + Kotlin + C/C++ 的 import 扫描。
        通过 LanguageRegistry 动态识别文件类型和 import 模式。
        """
        root = root or self._project_root
        self._graph = DependencyGraph()

        # 收集所有支持语言的文件(延迟导入 compliance 避免循环依赖)
        supported_exts: Set[str] = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".vue"}
        try:
            from harness.compliance import LanguageRegistry
            if not LanguageRegistry._languages:
                LanguageRegistry.default()
            supported_exts = LanguageRegistry.all_supported_extensions()
        except ImportError:
            pass  # LanguageRegistry 不可用时用默认扩展名集合

        code_files: List[str] = []
        for dirpath, _, filenames in os.walk(root):
            # 跳过隐藏目录和构建产物
            dirs_to_skip = {
                ".git", "__pycache__", "node_modules", ".venv",
                "dist", "build", ".next", "target", "bin",
            }
            if any(skip in dirpath for skip in dirs_to_skip):
                continue
            for fn in filenames:
                lower_fn = fn.lower()
                if any(lower_fn.endswith(ext) for ext in supported_exts):
                    full_path = os.path.join(dirpath, fn)
                    rel_path = os.path.relpath(full_path, root)
                    code_files.append(rel_path)

        # 添加所有文件节点
        entry_names = {
            "main.py", "app.py", "__init__.py", "index.py",
            "index.js", "index.ts", "main.ts", "App.vue",
        }
        for rel_path in code_files:
            is_entry = rel_path in entry_names
            self._graph.add_node(rel_path, is_entry_point=is_entry)

        # 扫描 import 关系
        for rel_path in code_files:
            full_path = os.path.join(root, rel_path)
            imports = self._scan_file_imports(full_path, rel_path, root)
            for imp_path in imports:
                self._graph.add_edge(rel_path, imp_path)

        self._built = True
        logger.info(f"依赖图构建完成: {self._graph.stats()}")

    def _scan_file_imports(self, file_path: str, source_rel: str, root: str) -> List[str]:
        """扫描文件 import 语句——多语言通用

        通过 LanguageRegistry 确定语言类型，选择对应的解析策略：
        - Python: 正则匹配 import/from 语句
        - JS/TS/Vue: tree-sitter 解析 import/require（正则 fallback）
        - Java: tree-sitter 解析 import 语句 + 包路径→文件路径转换（正则 fallback）
        - Go: tree-sitter 解析 import 语句（正则 fallback）
        - 其他: 正则 fallback
        """
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except (IOError, OSError):
            return []

        # 延迟导入 LanguageRegistry 避免循环依赖
        lang_info = None
        try:
            from harness.compliance import LanguageRegistry
            lang_info = LanguageRegistry.get_by_extension(source_rel)
        except ImportError:
            pass

        if lang_info is None:
            # 简单的扩展名匹配 fallback
            ext = os.path.splitext(source_rel)[1].lower()
            if ext == ".py":
                return self._scan_python_imports(content)
            elif ext in (".js", ".jsx", ".mjs", ".ts", ".tsx", ".vue"):
                return self._scan_js_ts_imports(content, source_rel, root)
            elif ext == ".java":
                return self._scan_java_imports(content, source_rel, root)
            elif ext == ".go":
                return self._scan_go_imports(content, source_rel, root)
            else:
                return []

        lang_name, lang_config = lang_info

        if lang_name == "python":
            return self._scan_python_imports(content)
        elif lang_name in ("javascript", "typescript", "vue"):
            return self._scan_js_ts_imports(content, source_rel, root)
        elif lang_name == "java":
            return self._scan_java_imports(content, source_rel, root)
        elif lang_name == "go":
            return self._scan_go_imports(content, source_rel, root)
        elif lang_name in ("kotlin", "ruby", "rust", "c", "cpp"):
            return self._scan_general_imports(content, source_rel, root, lang_config)
        else:
            return []

    # ─── Python import 扫描 ──────────────────────────

    def _scan_python_imports(self, content: str) -> List[str]:
        """扫描 Python import 语句"""
        import_pattern = re.compile(r'^import\s+([a-zA-Z0-9_.]+)', re.MULTILINE)
        from_pattern = re.compile(r'^from\s+([a-zA-Z0-9_.]+)\s+import', re.MULTILINE)

        imported_modules: Set[str] = set()
        for match in import_pattern.findall(content):
            imported_modules.add(match)
        for match in from_pattern.findall(content):
            imported_modules.add(match)

        result: List[str] = []
        for mod in imported_modules:
            parts = mod.split(".")
            possible_paths = [
                os.path.join(*parts) + ".py",
                os.path.join(*parts, "__init__.py"),
            ]
            for rel in possible_paths:
                if self._graph.get_node(rel):
                    result.append(rel)

        return result

    # ─── JS/TS/Vue import 扫描 ──────────────────────

    def _scan_js_ts_imports(self, content: str, source_rel: str, root: str) -> List[str]:
        """扫描 JS/TS/Vue import 语句——tree-sitter + 正则 fallback"""
        imported_paths: Set[str] = set()

        # 尝试 tree-sitter 解析
        try:
            imported_paths = self._scan_js_ts_imports_treesitter(content)
        except ImportError:
            # tree-sitter 不可用，用正则 fallback
            imported_paths = self._scan_js_ts_imports_regex(content)

        # 将相对路径转换为项目内的文件路径
        source_dir = os.path.dirname(source_rel)
        result: List[str] = []

        for imp_path in imported_paths:
            if not imp_path.startswith(".") and not imp_path.startswith("/"):
                # 绝对/包路径引用（如 'react', 'lodash'），跳过
                continue

            # 解析相对路径
            resolved = os.path.normpath(os.path.join(source_dir, imp_path))

            # 尝试多种扩展名匹配
            for ext in ("", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".vue",
                        "/index.js", "/index.ts", "/index.vue"):
                candidate = resolved + ext
                if self._graph.get_node(candidate):
                    result.append(candidate)

        return result

    def _scan_js_ts_imports_treesitter(self, content: str) -> Set[str]:
        """使用 tree-sitter 解析 JS/TS import 语句"""
        import tree_sitter_javascript as tsjs
        from tree_sitter import Language, Parser

        js_lang = Language(tsjs.language())
        parser = Parser(js_lang)
        tree = parser.parse(content.encode())

        imported_paths: Set[str] = set()

        def walk(node):
            if node.type == "import_statement":
                for child in node.children:
                    if child.type == "string":
                        for frag in child.children:
                            if frag.type == "string_fragment":
                                imported_paths.add(frag.text.decode())
            elif node.type == "call_expression":
                func = node.child_by_field_name("function")
                if func and func.type == "identifier" and func.text.decode() == "require":
                    for child in node.children:
                        if child.type == "arguments":
                            for arg in child.children:
                                if arg.type == "string":
                                    for frag in arg.children:
                                        if frag.type == "string_fragment":
                                            imported_paths.add(frag.text.decode())
            for child in node.children:
                walk(child)

        walk(tree.root_node)
        return imported_paths

    def _scan_js_ts_imports_regex(self, content: str) -> Set[str]:
        """正则 fallback 解析 JS/TS import 语句"""
        imported_paths: Set[str] = set()

        import_from = re.compile(r'''import\s+.*?\s+from\s+['"]([^'"]+)['"]''', re.MULTILINE)
        for match in import_from.findall(content):
            imported_paths.add(match)

        import_side = re.compile(r'''import\s+['"]([^'"]+)['"]''', re.MULTILINE)
        for match in import_side.findall(content):
            imported_paths.add(match)

        require_pattern = re.compile(r'''require\s*\(\s*['"]([^'"]+)['"]\s*\)''', re.MULTILINE)
        for match in require_pattern.findall(content):
            imported_paths.add(match)

        return imported_paths

    # ─── Java import 扫描 ───────────────────────────

    def _scan_java_imports(self, content: str, source_rel: str, root: str) -> List[str]:
        """扫描 Java import 语句——tree-sitter + 正则 fallback"""
        imported_paths: Set[str] = set()

        try:
            import tree_sitter_java as tsjava
            from tree_sitter import Language, Parser

            lang = Language(tsjava.language())
            parser = Parser(lang)
            tree = parser.parse(content.encode())

            def walk(node):
                if node.type == "import_declaration":
                    for child in node.children:
                        if child.type in ("scoped_identifier", "identifier"):
                            imported_paths.add(child.text.decode())
                for child in node.children:
                    walk(child)

            walk(tree.root_node)
        except ImportError:
            import_pattern = re.compile(r'^import\s+([a-zA-Z0-9_.]+)\s*;', re.MULTILINE)
            for match in import_pattern.findall(content):
                imported_paths.add(match)

        # Java 包路径→文件路径转换: com.example.dao.UserDao → com/example/dao/UserDao.java
        result: List[str] = []
        for pkg_path in imported_paths:
            rel = pkg_path.replace(".", "/") + ".java"
            if self._graph.get_node(rel):
                result.append(rel)

        return result

    # ─── Go import 扫描 ─────────────────────────────

    def _scan_go_imports(self, content: str, source_rel: str, root: str) -> List[str]:
        """扫描 Go import 语句——tree-sitter + 正则 fallback"""
        imported_paths: Set[str] = set()

        try:
            import tree_sitter_go as tsgo
            from tree_sitter import Language, Parser

            lang = Language(tsgo.language())
            parser = Parser(lang)
            tree = parser.parse(content.encode())

            def walk(node):
                if node.type == "import_declaration":
                    for child in node.children:
                        if child.type == "import_spec":
                            for sc in child.children:
                                if sc.type in ("string_literal", "interpreted_string_literal"):
                                    path = sc.text.decode().strip('"').strip("'")
                                    imported_paths.add(path)
                        elif child.type in ("string_literal", "interpreted_string_literal"):
                            path = child.text.decode().strip('"').strip("'")
                            imported_paths.add(path)
                for child in node.children:
                    walk(child)

            walk(tree.root_node)
        except ImportError:
            single_import = re.compile(r'^import\s+["`]([^"`]+)["`]', re.MULTILINE)
            multi_import = re.compile(r'["`]([^"`]+)["`]', re.MULTILINE)
            for match in single_import.findall(content):
                imported_paths.add(match)
            for match in multi_import.findall(content):
                imported_paths.add(match)

        # Go 只识别项目内的相对路径
        result: List[str] = []
        for imp_path in imported_paths:
            for ext in ("", ".go", "/__init__.go"):
                candidate = imp_path + ext
                if self._graph.get_node(candidate):
                    result.append(candidate)

        return result

    # ─── 通用 import 扫描(Kotlin/Ruby/Rust/C/C++) ──

    def _scan_general_imports(self, content: str, source_rel: str, root: str,
                              lang_config: dict) -> List[str]:
        """通用 import 扫描——用于 Kotlin/Ruby/Rust/C/C++ 等语言的正则 fallback"""
        import_pattern_str = lang_config.get("import_pattern")
        if not import_pattern_str:
            return []

        try:
            pattern = re.compile(import_pattern_str, re.MULTILINE)
            modules = pattern.findall(content)
        except re.error:
            return []

        result: List[str] = []
        for mod in modules:
            if not mod:
                continue
            parts = mod.replace(".", "/")
            for ext in ("", ".kt", ".rs", ".rb", ".c", ".cpp", ".h", ".hpp"):
                candidate = parts + ext
                if self._graph.get_node(candidate):
                    result.append(candidate)

        return result

    # ─── 影响分析 ─────────────────────────────────────

    def analyze_impact(self, change_files: List[str]) -> ImpactAnalysis:
        """分析变更影响

        步骤:
        1. 变更文件 → 反向依赖(谁依赖我) = 直接影响
        2. 直接影响文件 → 传递性反向依赖(2层) = 间接影响
        3. 计算风险级别
        """
        if not self._built:
            logger.warning("依赖图未构建,影响分析结果不完整")

        direct_impacts: Set[str] = set()
        indirect_impacts: Set[str] = set()

        for f in change_files:
            # 直接影响: 依赖变更文件的文件
            dependents = self._graph.get_dependents(f)
            direct_impacts.update(dependents)

            # 间接影响: 传递性依赖(2层)
            transitive = self._graph.get_transitive_dependents(f, max_depth=2)
            indirect_impacts.update(transitive)

        # 移除已属于直接影响的文件
        direct_set = direct_impacts
        indirect_only = indirect_impacts - direct_set - set(change_files)

        # 计算风险级别
        total_affected = len(direct_impacts) + len(indirect_only)
        has_entry_change = any(
            self._graph.get_node(f) and self._graph.get_node(f).is_entry_point
            for f in change_files
        )

        if has_entry_change or total_affected > self._high_threshold:
            risk_level = ImpactRiskLevel.HIGH
        elif total_affected > self._medium_threshold:
            risk_level = ImpactRiskLevel.MEDIUM
        else:
            risk_level = ImpactRiskLevel.LOW

        requires_review = risk_level == ImpactRiskLevel.HIGH

        risk = ImpactRisk(
            level=risk_level,
            reason=f"影响{total_affected}个文件{'，含入口文件' if has_entry_change else ''}",
            requires_review=requires_review,
        )

        return ImpactAnalysis(
            change_files=change_files,
            direct_impacts=direct_impacts,
            indirect_impacts=indirect_only,
            risk=risk,
            affected_count=total_affected,
            requires_review=requires_review,
        )

    # ─── IImpactAnalyzer Protocol 实现 ───────────────

    def get_dependencies(self, file_path: str) -> DependencyNode:
        """获取文件的依赖节点"""
        node = self._graph.get_node(file_path)
        if node is None:
            return DependencyNode(id=file_path)
        return node

    def get_call_graph(self, symbol: str) -> CallGraphNode:
        """获取调用图(首期简化→文件级)"""
        node = self._graph.get_node(symbol)
        if node is None:
            return CallGraphNode(id=symbol)
        # 将文件级依赖映射为"调用"
        return CallGraphNode(
            id=symbol,
            calls=node.dependencies,
            called_by=node.dependents,
        )

    def get_graph(self) -> DependencyGraph:
        """获取底层依赖图"""
        return self._graph

    def stats(self) -> Dict[str, Any]:
        """分析器统计"""
        return {
            "built": self._built,
            "project_root": self._project_root,
            "graph": self._graph.stats(),
        }


# ═══════════════════════════════════════════════════════════
#  单例工厂——按项目路径隔离
# ═══════════════════════════════════════════════════════════

_analyzers: Dict[str, FileImpactAnalyzer] = {}


def get_impact_analyzer(project_root: Optional[str] = None) -> FileImpactAnalyzer:
    """获取影响分析器(按项目隔离)"""
    global _analyzers
    key = project_root or os.getcwd()
    if key not in _analyzers:
        _analyzers[key] = FileImpactAnalyzer(project_root=key)
    return _analyzers[key]


# ═══════════════════════════════════════════════════════════
#  重导出——保持向后兼容
# ═══════════════════════════════════════════════════════════

__all__ = [
    "CallGraphNode",
    "DependencyGraph",
    "DependencyNode",
    "FileImpactAnalyzer",
    "ImpactAnalysis",
    "ImpactRisk",
    "ImpactRiskLevel",
    "IImpactAnalyzer",
    "get_impact_analyzer",
]

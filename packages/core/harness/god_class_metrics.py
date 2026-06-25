"""
God Class 精度提升模块: ATFD + WMC + TCC 三维复合检测

ArchUnit 式判定规则:
  ATFD > few  AND  WMC > high  AND  TCC < low  →  God Class

指标定义:
  ATFD (Access To Foreign Data): 类访问外部数据属性的次数
  WMC (Weighted Method Count): 类所有方法的 cyclomatic complexity 总和
  TCC (Tight Class Cohesion): 方法对共享属性访问的比例

Python 用 stdlib ast; 其他语言用 tree-sitter.
阈值可配置, 默认值参照 ArchUnit: ATFD>5, WMC>47, TCC<0.33.
"""

import ast
import logging
from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List, Set, Tuple

from harness.types import Artifact

logger = logging.getLogger("harness.god_class_metrics")


# ═══════════════════════════════════════════════════════════
#  默认阈值
# ═══════════════════════════════════════════════════════════

DEFAULT_ATFD_FEW = 5
DEFAULT_WMC_HIGH = 47
DEFAULT_TCC_LOW = 0.33


# ═══════════════════════════════════════════════════════════
#  数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class ClassMetrics:
    """单个类的三维指标"""
    class_name: str
    line: int
    atfd: int = 0
    wmc: int = 0
    tcc: float = 0.0
    method_count: int = 0
    is_god_class: bool = False
    reason: str = ""


@dataclass
class CompoundThresholds:
    """复合检测阈值"""
    atfd_few: int = DEFAULT_ATFD_FEW
    wmc_high: int = DEFAULT_WMC_HIGH
    tcc_low: float = DEFAULT_TCC_LOW


# ═══════════════════════════════════════════════════════════
#  GodClassMetrics — 主类
# ═══════════════════════════════════════════════════════════

class GodClassMetrics:
    """ATFD + WMC + TCC 三维复合 God Class 检测

    用法:
        gcm = GodClassMetrics()
        violations = gcm.check_python(tree, artifact, thresholds)
        violations = gcm.check_tree_sitter(tree, artifact, thresholds)
    """

    def __init__(self, thresholds: Optional[CompoundThresholds] = None):
        self.thresholds = thresholds or CompoundThresholds()

    def is_god_class(self, metrics: ClassMetrics) -> bool:
        """判定: ATFD > few AND WMC > high AND TCC < low"""
        t = self.thresholds
        result = (
            metrics.atfd > t.atfd_few
            and metrics.wmc > t.wmc_high
            and metrics.tcc < t.tcc_low
        )
        if result:
            metrics.is_god_class = True
            metrics.reason = (
                f"God Class '{metrics.class_name}': ATFD={metrics.atfd}(>{t.atfd_few}), "
                f"WMC={metrics.wmc}(>{t.wmc_high}), TCC={metrics.tcc:.2f}(<{t.tcc_low:.2f})"
            )
        return result

    # ─── Python (stdlib ast) ─────────────────────────────

    def check_python(
        self, tree: ast.AST, artifact: Artifact, thresholds: Optional[CompoundThresholds] = None,
    ) -> list[dict]:
        """Python God Class 复合检测"""
        if thresholds:
            self.thresholds = thresholds

        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                metrics = self._analyze_python_class(node)
                if self.is_god_class(metrics):
                    violations.append({
                        "line": metrics.line,
                        "match": metrics.class_name,
                        "start": 0,
                        "end": 0,
                        "description": metrics.reason,
                    })
        return violations

    def _analyze_python_class(self, class_node: ast.ClassDef) -> ClassMetrics:
        """分析单个 Python 类的三维指标"""
        class_name = class_node.name
        line = class_node.lineno if hasattr(class_node, 'lineno') else 0

        # 收集自身属性 (self.xxx) — 定义 + 赋值
        own_attrs: set[str] = set()
        methods: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

        for stmt in class_node.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(stmt)
                # self.xxx 赋值 → 自身属性
                for child in ast.walk(stmt):
                    if isinstance(child, ast.Assign):
                        for target in child.targets:
                            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                                if target.value.id == "self":
                                    own_attrs.add(target.attr)
            elif isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        own_attrs.add(target.id)

        method_count = len(methods)

        # WMC: 各方法的 cyclomatic complexity 总和
        wmc = sum(self._python_cyclomatic_complexity(m) for m in methods)

        # ATFD: 访问外部数据属性的次数
        atfd = self._python_atfd(class_node, methods, own_attrs)

        # TCC: 方法对共享自身属性的比例
        tcc = self._python_tcc(methods, own_attrs)

        return ClassMetrics(
            class_name=class_name, line=line,
            atfd=atfd, wmc=wmc, tcc=tcc,
            method_count=method_count,
        )

    def _python_cyclomatic_complexity(self, func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
        """计算单个方法的 cyclomatic complexity

        CC = 1 + (决策点数: if/for/while/and/or/ternary/except/with/assert)
        """
        cc = 1
        for child in ast.walk(func_node):
            # if 语句
            if isinstance(child, ast.If):
                cc += 1
            # for / while 循环
            elif isinstance(child, (ast.For, ast.While)):
                cc += 1
            # except 分支
            elif isinstance(child, ast.ExceptHandler):
                cc += 1
            # boolean and / or
            elif isinstance(child, ast.BoolOp):
                cc += len(child.values) - 1
            # ternary ifexpr
            elif isinstance(child, ast.IfExp):
                cc += 1
            # assert (视为决策点)
            elif isinstance(child, ast.Assert):
                cc += 1
        return cc

    def _python_atfd(
        self, class_node: ast.ClassDef, methods: list, own_attrs: set[str],
    ) -> int:
        """ATFD: 访问外部数据属性的次数

        外部数据属性 = 非 self.xxx 且非自身属性定义的 Attribute 访问
        即 obj.attr 形式, 其中 obj 不是 self, 或者 self.attr 但 attr 不在 own_attrs
        """
        atfd = 0
        # 类定义中直接赋值的类属性也属于自身
        class_own_attrs = own_attrs.copy()

        for method in methods:
            for child in ast.walk(method):
                if isinstance(child, ast.Attribute):
                    # self.xxx 但 xxx 不在 own_attrs → 外部(父类属性)
                    if isinstance(child.value, ast.Name) and child.value.id == "self":
                        if child.attr not in class_own_attrs:
                            atfd += 1
                    # obj.xxx (obj 不是 self) → 外部数据
                    elif isinstance(child.value, ast.Name) and child.value.id != "self":
                        # 排除函数调用链式属性 (如 os.path.join 不算 ATFD)
                        # 只计读取式属性访问 (Load context)
                        if isinstance(child.ctx, ast.Load):
                            atfd += 1
                    # 链式属性 (如 self.config.value) → 部分算外部
                    elif isinstance(child.value, ast.Attribute):
                        # self.xxx.yyy → 如果 xxx 不在 own_attrs, 则算外部
                        # 保守做法: 只计直接链式外属性
                        pass  # 链式不重复计, 避免膨胀

        return atfd

    def _python_tcc(self, methods: list, own_attrs: set[str]) -> float:
        """TCC: 方法对共享自身属性的比例

        TCC = (共享至少一个属性的 method pairs) / (所有可能的 method pairs)
        如果只有 ≤1 个方法, TCC = 1.0 (完全内聚)
        """

        if len(methods) <= 1:
            return 1.0

        # 每个方法访问的 self.xxx 属性集合
        method_attrs: list[set[str]] = []
        for method in methods:
            attrs = set()
            for child in ast.walk(method):
                if isinstance(child, ast.Attribute):
                    if isinstance(child.value, ast.Name) and child.value.id == "self":
                        if child.attr in own_attrs:
                            attrs.add(child.attr)
            method_attrs.append(attrs)

        # 计算共享至少一个属性的 method pairs
        total_pairs = len(methods) * (len(methods) - 1) // 2
        connected_pairs = 0
        for i in range(len(method_attrs)):
            for j in range(i + 1, len(method_attrs)):
                if method_attrs[i] & method_attrs[j]:
                    connected_pairs += 1

        return connected_pairs / total_pairs if total_pairs > 0 else 1.0

    # ─── Tree-sitter (多语言) ─────────────────────────────

    def check_tree_sitter(
        self, tree: Any, artifact: Artifact, thresholds: Optional[CompoundThresholds] = None,
    ) -> list[dict]:
        """tree-sitter God Class 复合检测"""
        if thresholds:
            self.thresholds = thresholds

        from harness.compliance import LanguageRegistry

        lang_info = LanguageRegistry.get_by_extension(artifact.path)
        if lang_info is None:
            return []
        lang_name = lang_info[0]

        violations = []

        # 不同语言的类和方法节点类型
        class_types = {
            "javascript": ("class_declaration", ("method_definition", "generator_method_definition")),
            "typescript": ("class_declaration", ("method_definition", "generator_method_definition")),
            "java": ("class_declaration", ("method_declaration",)),
            "kotlin": ("class_declaration", ("function_declaration",)),
            "ruby": ("class", ("method",)),
            "cpp": ("class_specifier", ("function_definition",)),
            "vue": ("class_declaration", ("method_definition", "generator_method_definition")),
        }

        lang_config = class_types.get(lang_name)
        if lang_config is None:
            return []

        class_type_name, method_type_names = lang_config

        def walk_ts(node):
            if node.type == class_type_name:
                metrics = self._analyze_ts_class(node, method_type_names)
                if self.is_god_class(metrics):
                    violations.append({
                        "line": metrics.line,
                        "match": metrics.class_name,
                        "start": 0,
                        "end": 0,
                        "description": metrics.reason,
                    })
            for child in node.children:
                walk_ts(child)

        walk_ts(tree.root_node)
        return violations

    def _analyze_ts_class(
        self, class_node: Any, method_type_names: tuple[str, ...],
    ) -> ClassMetrics:
        """分析单个 tree-sitter 类的三维指标"""
        name_node = class_node.child_by_field_name("name")
        class_name = name_node.text.decode() if name_node else "anonymous"
        line = class_node.start_point[0] + 1

        body = class_node.child_by_field_name("body")
        if not body:
            return ClassMetrics(class_name=class_name, line=line, tcc=1.0)

        # 收集方法节点
        method_nodes = [n for n in body.children if n.type in method_type_names]
        method_count = len(method_nodes)

        # 收集自身属性 (this.xxx / self.xxx / 等)
        own_attrs: set[str] = self._ts_collect_own_attrs(body, method_nodes)

        # WMC: 各方法的 cyclomatic complexity 总和
        wmc = sum(self._ts_cyclomatic_complexity(m) for m in method_nodes)

        # ATFD: 访问外部数据属性
        atfd = self._ts_atfd(body, method_nodes, own_attrs)

        # TCC: 方法对共享自身属性的比例
        tcc = self._ts_tcc(method_nodes, own_attrs)

        return ClassMetrics(
            class_name=class_name, line=line,
            atfd=atfd, wmc=wmc, tcc=tcc,
            method_count=method_count,
        )

    def _ts_collect_own_attrs(self, body: Any, method_nodes: list) -> set[str]:
        """收集类自身属性名称"""
        own_attrs: set[str] = set()

        for method in method_nodes:
            method_text = method.text.decode()
            # this.xxx = ... 或 this.xxx → 自身属性
            for child in method.children:
                self._ts_collect_this_assigns(child, own_attrs)

        # 类级别属性声明 (JS/TS: property_identifier)
        for child in body.children:
            if child.type == "public_field_definition" or child.type == "field_definition":
                name = child.child_by_field_name("name")
                if name:
                    own_attrs.add(name.text.decode())

        return own_attrs

    def _ts_collect_this_assigns(self, node: Any, own_attrs: set[str]):
        """递归收集 this.xxx 赋值中的属性名"""
        # assignment_expression: this.xxx = value
        if node.type == "assignment_expression":
            left = node.child_by_field_name("left")
            if left and left.type == "member_expression":
                obj = left.child_by_field_name("object")
                prop = left.child_by_field_name("property")
                if obj and prop:
                    obj_text = obj.text.decode()
                    if obj_text in ("this", "self"):
                        own_attrs.add(prop.text.decode())
        for child in node.children:
            self._ts_collect_this_assigns(child, own_attrs)

    def _ts_cyclomatic_complexity(self, method_node: Any) -> int:
        """tree-sitter 节点的 cyclomatic complexity"""
        cc = 1
        # 递增决策点
        decision_types = {
            "if_statement", "for_statement", "for_in_statement",
            "while_statement", "do_statement", "catch_clause",
            "ternary_expression", "switch_case",
            "conditional_expression",
        }
        for child in method_node.children:
            cc += self._ts_count_decisions(child, decision_types)
        return cc

    def _ts_count_decisions(self, node: Any, decision_types: set[str]) -> int:
        """递归计数决策节点"""
        count = 0
        if node.type in decision_types:
            count += 1
        # boolean and/or 操作 (在 expression 里)
        if node.type in ("binary_expression", "logical_expression"):
            op = None
            for child in node.children:
                if child.type in ("&&", "&&", "and", "or", "||"):
                    count += 1
        for child in node.children:
            count += self._ts_count_decisions(child, decision_types)
        return count

    def _ts_atfd(self, body: Any, method_nodes: list, own_attrs: set[str]) -> int:
        """tree-sitter ATFD 计算"""
        atfd = 0

        for method in method_nodes:
            for child in method.children:
                atfd += self._ts_count_foreign_access(child, own_attrs)

        return atfd

    def _ts_count_foreign_access(self, node: Any, own_attrs: set[str]) -> int:
        """递归计算外部数据属性访问"""
        count = 0
        # member_expression: obj.prop 或 this.prop
        if node.type == "member_expression":
            obj = node.child_by_field_name("object")
            prop = node.child_by_field_name("property")
            if obj and prop:
                obj_text = obj.text.decode()
                prop_text = prop.text.decode()
                # this.prop 但 prop 不在 own_attrs → 外部
                if obj_text in ("this", "self"):
                    if prop_text not in own_attrs:
                        count += 1
                # obj.prop (obj 不是 this/self) → 外部
                elif obj_text not in ("this", "self", "super"):
                    count += 1

        for child in node.children:
            count += self._ts_count_foreign_access(child, own_attrs)

        return count

    def _ts_tcc(self, method_nodes: list, own_attrs: set[str]) -> float:
        """tree-sitter TCC 计算"""
        if len(method_nodes) <= 1:
            return 1.0

        method_attrs: list[set[str]] = []
        for method in method_nodes:
            attrs = self._ts_method_own_attrs(method, own_attrs)
            method_attrs.append(attrs)

        total_pairs = len(method_nodes) * (len(method_nodes) - 1) // 2
        connected_pairs = 0
        for i in range(len(method_attrs)):
            for j in range(i + 1, len(method_attrs)):
                if method_attrs[i] & method_attrs[j]:
                    connected_pairs += 1

        return connected_pairs / total_pairs if total_pairs > 0 else 1.0

    def _ts_method_own_attrs(self, method_node: Any, own_attrs: set[str]) -> set[str]:
        """收集方法中访问的自身属性"""
        attrs = set()
        for child in method_node.children:
            self._ts_collect_method_own_attrs(child, own_attrs, attrs)
        return attrs

    def _ts_collect_method_own_attrs(
        self, node: Any, own_attrs: set[str], attrs: set[str],
    ):
        """递归收集方法中的自身属性访问"""
        if node.type == "member_expression":
            obj = node.child_by_field_name("object")
            prop = node.child_by_field_name("property")
            if obj and prop:
                obj_text = obj.text.decode()
                prop_text = prop.text.decode()
                if obj_text in ("this", "self") and prop_text in own_attrs:
                    attrs.add(prop_text)

        for child in node.children:
            self._ts_collect_method_own_attrs(child, own_attrs, attrs)


# ═══════════════════════════════════════════════════════════
#  便捷函数
# ═══════════════════════════════════════════════════════════

def make_thresholds_from_config(config: dict) -> CompoundThresholds:
    """从 matcher_config dict 构建 CompoundThresholds"""
    return CompoundThresholds(
        atfd_few=config.get("atfd_few", DEFAULT_ATFD_FEW),
        wmc_high=config.get("wmc_high", DEFAULT_WMC_HIGH),
        tcc_low=config.get("tcc_low", DEFAULT_TCC_LOW),
    )
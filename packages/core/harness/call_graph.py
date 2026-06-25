"""
harness-cook 谊用图: call_graph 方法级调用图构建器

调用 CallGraphBuilder.scan 方法调用关系并生成 CallGraph 对用例:
    builder = CallGraphBuilder()
    cg = builder.scan_python(code)
    for caller, callees in cg.calls:
        print(f"{caller} -> {callees}")
"""
import ast
import logging
import re
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Set

from collections import defaultdict

logger = logging.getLogger("harness.call_graph")


@dataclass
class CallGraph:
    """调用图数据结构"""
    calls: Dict[str, List[str]] = field(default_factory=lambda: defaultdict(list))
    # method → 定义位置
    definitions: Dict[str, int] = field(default_factory=dict)
    # file → 方法列表
    file_methods: Dict[str, List[str]] = field(default_factory=lambda: defaultdict(list))
class CallGraphBuilder:
    """
    Python 调用图构建器 — 基于 stdlib ast
    
    分析:
    1. 函数/方法定义 (def xxx)
    2. 函数调用 (xxx())
    3. 方法调用 (self.xxx(), obj.xxx())
    
    输出 CallGraph: calls[name] -> [callee_names]
    """
    def scan_python(self, code: str, filepath: str = "") -> CallGraph:
        """扫描 Python 代码生成调用图"""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            logger.warning(f"Syntax error in {filepath}, skipping call graph")
            return CallGraph()
        graph = CallGraph()
        # Phase 1: 收集所有定义
        definitions = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                line = node.lineno if hasattr(node, 'lineno') else 0
                definitions[name] = line
                graph.definitions[name] = line
                graph.file_methods[filepath].append(name)
            elif isinstance(node, ast.ClassDef):
                class_name = node.name
                class_line = node.lineno if hasattr(node, 'lineno') else 0
                definitions[class_name] = class_line
                graph.definitions[class_name] = class_line
                # 类方法
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_name = f"{class_name}.{item.name}"
                        method_line = item.lineno if hasattr(item, 'lineno') else 0
                        definitions[method_name] = method_line
                        graph.definitions[method_name] = method_line
                        graph.file_methods[filepath].append(method_name)
        # Phase 2: 收集所有调用
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                caller = self._get_enclosing_func_name(node, tree)
                callee = self._get_call_name(node)
                if caller and callee:
                    graph.calls[caller].append(callee)
        return graph
    def _get_enclosing_func_name(self, call_node: ast.Call, tree: ast.AST) -> str:
        """找到包含 Call 节点的最近函数定义"""
        # 遍历 tree 找到包含此 call 的函数
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    if child is call_node:
                        return node.name
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for child in ast.walk(item):
                            if child is call_node:
                                return f"{node.name}.{item.name}"
        return "<module>"
    def _get_call_name(self, call_node: ast.Call) -> str:
        """提取调用目标名称"""
        func = call_node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name):
                if func.value.id == "self":
                    # self.method() → ClassName.method (上下文推断)
                    return func.attr  # 简化为方法名
                return f"{func.value.id}.{func.attr}"
            return func.attr
        return ""
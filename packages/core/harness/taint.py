"""
harness-cook 污点追踪(Taint Tracking)

09号竞品报告指出"没有污点追踪"(Semgrep Pro 有)。
本模块提供基础 source→sink 数据流追踪能力:
  1. TaintSource — 污染源(user input, env vars, file read, network)
  2. TaintSink — 危险汇聚点(eval, exec, SQL, subprocess, network send)
  3. TaintTracker — AST 级数据流追踪(Python stdlib ast), 标记变量→传播→检测汇聚点

当前只支持 Python(stdlib ast), 其他语言可后续扩展(tree-sitter)。
"""

import ast
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, List, Set, Tuple

logger = logging.getLogger("harness.taint")


# ═══════════════════════════════════════════════════════════
#  污点类型定义
# ═══════════════════════════════════════════════════════════

class TaintSourceType(Enum):
    """污染源类型"""
    USER_INPUT = "user_input"        # request.get, input(), sys.argv
    ENV_VAR = "env_var"              # os.environ, os.getenv
    FILE_READ = "file_read"          # open().read(), Path.read_text()
    NETWORK = "network"              # requests.get, urllib
    DATABASE = "database"            # cursor.fetchone
    COMMAND_ARG = "command_arg"      # subprocess arguments


class TaintSinkType(Enum):
    """危险汇聚点类型"""
    EVAL = "eval"                    # eval(), exec()
    SQL = "sql"                      # cursor.execute(f-string)
    SUBPROCESS = "subprocess"        # subprocess.call/run/shell=True
    OS_SYSTEM = "os_system"          # os.system(), os.popen()
    NETWORK_SEND = "network_send"    # requests.post, urllib.request
    FILE_WRITE = "file_write"        # open().write() with tainted content
    DESERIALIZATION = "deserialization"  # pickle.loads, yaml.load


@dataclass
class TaintSource:
    """污染源定义"""
    type: TaintSourceType
    pattern: str          # 函数/方法名正则
    description: str
    arg_index: int = 0    # 哪个参数是 tainted(默认返回值)


@dataclass
class TaintSink:
    """危险汇聚点定义"""
    type: TaintSinkType
    pattern: str          # 函数/方法名正则
    description: str
    arg_index: int = 0    # 哪个参数接收 tainted(默认第0个)


@dataclass
class TaintFinding:
    """污点追踪发现"""
    source_type: TaintSourceType
    sink_type: TaintSinkType
    source_line: int
    sink_line: int
    source_var: str
    description: str
    severity: str = "high"


# ═══════════════════════════════════════════════════════════
#  内置 Source / Sink 定义
# ═══════════════════════════════════════════════════════════

BUILTIN_SOURCES: List[TaintSource] = [
    TaintSource(TaintSourceType.USER_INPUT, r"\binput\b", "Python input() — user-supplied data"),
    TaintSource(TaintSourceType.ENV_VAR, r"os\.environ\.get|os\.getenv", "Environment variable read"),
    TaintSource(TaintSourceType.FILE_READ, r"\.read\b|\.read_text\b", "File read operation"),
    TaintSource(TaintSourceType.NETWORK, r"requests\.\w+|urllib\.request", "Network fetch"),
    TaintSource(TaintSourceType.COMMAND_ARG, r"sys\.argv", "Command-line argument"),
    TaintSource(TaintSourceType.DATABASE, r"cursor\.fetch\w+", "Database query result"),
]

BUILTIN_SINKS: List[TaintSink] = [
    TaintSink(TaintSinkType.EVAL, r"\beval\b|\bexec\b", "eval/exec — arbitrary code execution"),
    TaintSink(TaintSinkType.SQL, r"cursor\.execute|execute\(", "SQL execution — injection risk"),
    TaintSink(TaintSinkType.SUBPROCESS, r"subprocess\.\w+|os\.system|os\.popen", "Subprocess call — command injection"),
    TaintSink(TaintSinkType.OS_SYSTEM, r"os\.system\b|os\.popen\b", "os.system — shell command execution"),
    TaintSink(TaintSinkType.NETWORK_SEND, r"requests\.post|urllib\.request\.urlopen", "Network send — SSRF/data exfiltration"),
    TaintSink(TaintSinkType.DESERIALIZATION, r"pickle\.loads|yaml\.load", "Unsafe deserialization"),
    TaintSink(TaintSinkType.FILE_WRITE, r"\.write\b|\.write_text\b", "File write with tainted content"),
]


# ═══════════════════════════════════════════════════════════
#  污点追踪器
# ═══════════════════════════════════════════════════════════

class TaintTracker:
    """
    AST 级污点追踪器——source → propagation → sink detection

    用法:
        tracker = TaintTracker()
        findings = tracker.track_python(code, filepath)
        for f in findings:
            print(f"{f.source_type} → {f.sink_type}: {f.description}")
    """

    def __init__(
        self,
        sources: Optional[List[TaintSource]] = None,
        sinks: Optional[List[TaintSink]] = None,
    ):
        self.sources = sources or BUILTIN_SOURCES
        self.sinks = sinks or BUILTIN_SINKS

    def track_python(self, code: str, filepath: str = "") -> List[TaintFinding]:
        """对 Python 代码执行污点追踪"""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            logger.warning(f"Syntax error in {filepath}, skipping taint analysis")
            return []

        # Phase 1: 识别污染源(tainted 变量)
        tainted_vars: Dict[str, Tuple[TaintSourceType, int, str]] = {}
        self._identify_sources(tree, tainted_vars)

        # Phase 2: 传播(赋值链)
        self._propagate(tree, tainted_vars)

        # Phase 3: 检测汇聚点(tainted 变量流入 sink)
        findings = self._detect_sinks(tree, tainted_vars, filepath)

        return findings

    # ─── Phase 1: Source 识别 ────────────────────────────

    def _identify_sources(self, tree: ast.AST, tainted_vars: Dict) -> None:
        """识别所有污染源赋值"""
        for node in ast.walk(tree):
            # x = input() / x = os.environ.get("Y") 等
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        source_match = self._match_source(node.value)
                        if source_match:
                            tainted_vars[target.id] = (
                                source_match.type,
                                node.lineno if hasattr(node, 'lineno') else 0,
                                target.id,
                            )

            # x = request.get(...) 形式的 Call
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        source_match = self._match_source(node.value)
                        if source_match and target.id not in tainted_vars:
                            tainted_vars[target.id] = (
                                source_match.type,
                                node.lineno if hasattr(node, 'lineno') else 0,
                                target.id,
                            )

    def _match_source(self, node: ast.AST) -> Optional[TaintSource]:
        """检查 AST 节点是否匹配污染源"""
        # 直接函数调用
        if isinstance(node, ast.Call):
            func_name = self._get_func_name(node.func)
            for source in self.sources:
                if re.search(source.pattern, func_name):
                    return source

        # 属性方法调用 (obj.method())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr_chain = self._get_attr_chain(node.func)
            for source in self.sources:
                if re.search(source.pattern, attr_chain):
                    return source

        return None

    # ─── Phase 2: 传播 ────────────────────────────────────

    def _propagate(self, tree: ast.AST, tainted_vars: Dict) -> None:
        """传播污染: y = x → y 也是 tainted"""
        # 多轮传播直到稳定
        max_rounds = 10
        for _ in range(max_rounds):
            new_tainted = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            # 检查 RHS 是否引用了 tainted 变量
                            if target.id not in tainted_vars:
                                rhs_refs = self._collect_names(node.value)
                                for ref in rhs_refs:
                                    if ref in tainted_vars:
                                        new_tainted[target.id] = tainted_vars[ref]
                                        break
            if not new_tainted:
                break
            tainted_vars.update(new_tainted)

    # ─── Phase 3: Sink 检测 ────────────────────────────────

    def _detect_sinks(self, tree: ast.AST, tainted_vars: Dict, filepath: str) -> List[TaintFinding]:
        """检测 tainted 变量流入危险汇聚点"""
        findings = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = self._get_func_name(node.func)
                sink_match = self._match_sink(node.func)
                if sink_match:
                    # 检查参数中是否有 tainted 变量
                    for arg in node.args:
                        arg_refs = self._collect_names(arg)
                        for ref in arg_refs:
                            if ref in tainted_vars:
                                source_info = tainted_vars[ref]
                                findings.append(TaintFinding(
                                    source_type=source_info[0],
                                    sink_type=sink_match.type,
                                    source_line=source_info[1],
                                    sink_line=node.lineno if hasattr(node, 'lineno') else 0,
                                    source_var=ref,
                                    description=f"Tainted variable '{ref}' (from {source_info[0].value}) "
                                                f"flows into {sink_match.type.value} at line {node.lineno}",
                                    severity="critical" if sink_match.type in (
                                        TaintSinkType.EVAL, TaintSinkType.OS_SYSTEM
                                    ) else "high",
                                ))

            # f-string SQL 检测 (不通过函数参数而是通过字符串拼接)
            if isinstance(node, ast.JoinedStr):
                sink_match = None
                # 检查是否在 cursor.execute 调用中
                for parent_ctx in self._get_parent_calls(node, tree):
                    parent_func = self._get_func_name(parent_ctx.func)
                    for sink in self.sinks:
                        if sink.type == TaintSinkType.SQL and re.search(sink.pattern, parent_func):
                            sink_match = sink
                            break
                if sink_match:
                    for val in node.values:
                        if isinstance(val, ast.FormattedValue) and isinstance(val.value, ast.Name):
                            if val.value.id in tainted_vars:
                                source_info = tainted_vars[val.value.id]
                                findings.append(TaintFinding(
                                    source_type=source_info[0],
                                    sink_type=TaintSinkType.SQL,
                                    source_line=source_info[1],
                                    sink_line=node.lineno if hasattr(node, 'lineno') else 0,
                                    source_var=val.value.id,
                                    description=f"Tainted variable '{val.value.id}' used in f-string SQL",
                                    severity="critical",
                                ))

        return findings

    def _match_sink(self, node: ast.AST) -> Optional[TaintSink]:
        """检查 AST 节点是否匹配危险汇聚点"""
        func_name = self._get_func_name(node)
        attr_chain = self._get_attr_chain(node) if isinstance(node, ast.Attribute) else ""
        for sink in self.sinks:
            if re.search(sink.pattern, func_name) or re.search(sink.pattern, attr_chain):
                return sink
        return None

    # ─── AST 辅助方法 ────────────────────────────────────

    def _get_func_name(self, node: ast.AST) -> str:
        """获取函数调用的名称字符串"""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute)):
            return self._get_func_name(node.func)
        return ""

    def _get_attr_chain(self, node: ast.Attribute) -> str:
        """获取属性链: os.environ.get"""
        parts = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))

    def _collect_names(self, node: ast.AST) -> Set[str]:
        """收集 AST 节点中引用的所有变量名"""
        names = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                names.add(child.id)
        return names

    def _get_parent_calls(self, target_node: ast.AST, tree: ast.AST) -> List[ast.Call]:
        """获取包含目标节点的父级 Call 节点"""
        parents = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for arg in node.args:
                    if self._contains_node(arg, target_node):
                        parents.append(node)
        return parents

    def _contains_node(self, node: ast.AST, target: ast.AST) -> bool:
        """检查 node 是否包含 target"""
        for child in ast.walk(node):
            if child is target:
                return True
        return False
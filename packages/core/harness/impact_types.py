"""
影响分析适配层——从 nextX IImpactAnalyzer/CallGraph/DependencyGraph 提取的设计蓝图

Harness 统一管控 Agent 的影响评估:
- 变更会影响哪些代码(文件级影响分析)
- 影响有多严重(风险分级)
- 是否需要额外审批(高风险变更)

nextX 的核心设计模式:
1. IImpactAnalyzer: analyzeImpact() — 变更影响评估接口
2. CallGraphNode: 函数调用图节点(caller→callee)
3. DependencyNode: 依赖图节点(文件→依赖)
4. ImpactAnalysis: 直接影响+间接影响+风险级别
5. ImpactRisk: risk级别(high/medium/low) + reason

harness-cook 适配定位:
- 首期只做文件级影响分析(不含AST级) → AST级留给codeops产品层
- 基于简单文件依赖关系做分析(不做函数级调用图)
- 与Phase 4 Validator协作: 高风险变更触发额外验证
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Set

logger = logging.getLogger("harness.impact")


# ═══════════════════════════════════════════════════════════
#  影响风险级别——从 nextX ImpactAnalysis.risk 提取
# ═══════════════════════════════════════════════════════════

class ImpactRiskLevel(Enum):
    """影响风险级别——3级"""
    HIGH = "high"      # 高风险: 核心文件,影响面大
    MEDIUM = "medium"  # 中风险: 模块文件,影响可控
    LOW = "low"        # 低风险: 边缘文件,影响有限


# ═══════════════════════════════════════════════════════════
#  依赖图节点——从 nextX DependencyNode 提取
# ═══════════════════════════════════════════════════════════

@dataclass
class DependencyNode:
    """依赖图节点——文件级依赖
    
    从 nextX DependencyNode 适配(函数级→文件级):
    - id: 文件路径
    - dependencies: 该文件依赖的文件列表(import关系)
    - dependents: 依赖该文件的文件列表(反向关系)
    - is_entry_point: 是否入口文件(main/index)
    """
    id: str = ""                           # 文件路径
    dependencies: Set[str] = field(default_factory=set)   # 我依赖谁
    dependents: Set[str] = field(default_factory=set)      # 谁依赖我
    is_entry_point: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_dependency(self, target: str) -> None:
        """添加依赖关系"""
        self.dependencies.add(target)
    
    def add_dependent(self, source: str) -> None:
        """添加反向依赖"""
        self.dependents.add(source)


# ═══════════════════════════════════════════════════════════
#  调用图节点——从 nextX CallGraphNode 提取(首期简化)
# ═══════════════════════════════════════════════════════════

@dataclass
class CallGraphNode:
    """调用图节点——函数级(首期简化为文件级)
    
    从 nextX CallGraphNode 适配:
    - 首期不做AST级调用图,只做文件级
    - id: 文件路径(代替函数名)
    - calls: 该文件调用/引用的文件
    - called_by: 调用/引用该文件的文件
    """
    id: str = ""                           # 函数名/文件路径
    calls: Set[str] = field(default_factory=set)          # 我调用谁
    called_by: Set[str] = field(default_factory=set)       # 谁调用我
    metadata: Dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════
#  影响风险——从 nextX ImpactRisk 提取
# ═══════════════════════════════════════════════════════════

@dataclass
class ImpactRisk:
    """影响风险——风险级别+原因"""
    level: ImpactRiskLevel = ImpactRiskLevel.LOW
    reason: str = ""
    requires_review: bool = False           # 是否需要人工审批


# ═══════════════════════════════════════════════════════════
#  影响分析结果——从 nextX ImpactAnalysis 提取
# ═══════════════════════════════════════════════════════════

@dataclass
class ImpactAnalysis:
    """影响分析结果——直接影响+间接影响+风险级别
    
    从 nextX ImpactAnalysis 提取:
    - direct_impacts: 直接受影响的文件(被变更文件依赖的文件)
    - indirect_impacts: 间接受影响的文件(依赖链2层以上)
    - risk: 总体风险级别
    - change_files: 发生变更的文件
    """
    change_files: List[str] = field(default_factory=list)
    direct_impacts: Set[str] = field(default_factory=set)
    indirect_impacts: Set[str] = field(default_factory=set)
    risk: ImpactRisk = field(default_factory=ImpactRisk)
    affected_count: int = 0                 # 总受影响数
    requires_review: bool = False
    
    def total_impact_count(self) -> int:
        """总影响数"""
        return len(self.direct_impacts) + len(self.indirect_impacts)
    
    def summary(self) -> str:
        """分析概要"""
        risk_str = self.risk.level.value
        return (
            f"[{risk_str}] 变更{len(self.change_files)}个文件,"
            f"直接影响{len(self.direct_impacts)}个,"
            f"间接影响{len(self.indirect_impacts)}个"
            f"{' [需审批]' if self.requires_review else ''}"
        )


# ═══════════════════════════════════════════════════════════
#  IImpactAnalyzer — Protocol接口
# ═══════════════════════════════════════════════════════════

class IImpactAnalyzer(Protocol):
    """影响分析接口——从 nextX IImpactAnalyzer 提取
    
    核心方法:
    - analyzeImpact(): 分析变更影响
    - getDependencies(): 获取依赖图
    - getCallGraph(): 获取调用图(首期简化)
    """
    def analyze_impact(self, change_files: List[str]) -> ImpactAnalysis: ...
    def get_dependencies(self, file_path: str) -> DependencyNode: ...
    def get_call_graph(self, symbol: str) -> CallGraphNode: ...


# ═══════════════════════════════════════════════════════════
#  依赖图——从 nextX DependencyGraph 适配
# ═══════════════════════════════════════════════════════════

class DependencyGraph:
    """依赖图——文件级依赖关系
    
    从 nextX DependencyGraph 适配:
    - nodes: 所有文件的依赖节点
    - 添加节点+边
    - 查询依赖/反向依赖
    - 计算影响传播路径
    """
    
    def __init__(self):
        self._nodes: Dict[str, DependencyNode] = {}
    
    def add_node(self, file_path: str, is_entry_point: bool = False) -> DependencyNode:
        """添加节点"""
        if file_path not in self._nodes:
            self._nodes[file_path] = DependencyNode(
                id=file_path,
                is_entry_point=is_entry_point,
            )
        return self._nodes[file_path]
    
    def add_edge(self, source: str, target: str) -> None:
        """添加依赖边: source 依赖 target"""
        src_node = self.add_node(source)
        tgt_node = self.add_node(target)
        src_node.add_dependency(target)
        tgt_node.add_dependent(source)
    
    def get_node(self, file_path: str) -> Optional[DependencyNode]:
        """获取节点"""
        return self._nodes.get(file_path)
    
    def get_dependencies(self, file_path: str) -> Set[str]:
        """获取文件的直接依赖"""
        node = self._nodes.get(file_path)
        return node.dependencies if node else set()
    
    def get_dependents(self, file_path: str) -> Set[str]:
        """获取依赖该文件的文件(反向依赖)"""
        node = self._nodes.get(file_path)
        return node.dependents if node else set()
    
    def get_transitive_dependents(self, file_path: str, max_depth: int = 3) -> Set[str]:
        """获取传递性反向依赖(影响传播)
        
        BFS遍历反向依赖链,最多max_depth层。
        """
        visited: Set[str] = set()
        current_level: Set[str] = {file_path}
        result: Set[str] = set()
        
        for depth in range(max_depth):
            next_level: Set[str] = set()
            for f in current_level:
                if f in visited:
                    continue
                visited.add(f)
                dependents = self.get_dependents(f)
                next_level.update(dependents)
                result.update(dependents)
            current_level = next_level
            if not current_level:
                break
        
        return result
    
    def entry_points(self) -> List[str]:
        """入口文件列表"""
        return [n.id for n in self._nodes.values() if n.is_entry_point]
    
    def all_nodes(self) -> List[DependencyNode]:
        """所有节点"""
        return list(self._nodes.values())
    
    def stats(self) -> Dict[str, Any]:
        """图统计"""
        return {
            "total_nodes": len(self._nodes),
            "total_edges": sum(len(n.dependencies) for n in self._nodes.values()),
            "entry_points": len(self.entry_points()),
        }


# ═══════════════════════════════════════════════════════════
#  影响分析实现——延迟导入 impact_analyzer.py
# ═══════════════════════════════════════════════════════════
#
# FileImpactAnalyzer 和 get_impact_analyzer 的定义已移至
# impact_analyzer.py（实现模块），此处通过 __getattr__ 延迟导入，
# 保证 `from harness.impact_types import FileImpactAnalyzer` 等旧路径仍可工作。

_LAZY_IMPORT_NAMES = {"FileImpactAnalyzer", "get_impact_analyzer"}


def __getattr__(name: str) -> Any:
    """延迟导入——避免 impact_types ↔ impact_analyzer 循环依赖

    FileImpactAnalyzer / get_impact_analyzer 的实际定义在
    impact_analyzer.py 中。首次访问时才触发导入，此时两个模块
    的顶层定义已全部就绪，不会触发循环导入问题。
    """
    if name in _LAZY_IMPORT_NAMES:
        from harness.impact_analyzer import FileImpactAnalyzer, get_impact_analyzer
        globals()["FileImpactAnalyzer"] = FileImpactAnalyzer
        globals()["get_impact_analyzer"] = get_impact_analyzer
        return globals()[name]
    raise AttributeError(f"module 'harness.impact_types' has no attribute '{name}'")
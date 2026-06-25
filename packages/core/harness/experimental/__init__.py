"""
harness-cook Experimental Modules

实验性模块——接口和实现可能在未来版本中变更。

这些模块有完整类型但可能缺乏完整的集成：
- knowledge.py: 知识管理（有 LocalKnowledgeProvider，但持久化依赖文件系统）
- validator_types.py: Validator 接口（有类型定义，但与 compliance/guardrails 集成不完整）
- impact_analyzer.py: 影响分析（有接口，但实现为 stub）

新增实验性模块：
- autonomous_loop.py: 自主循环引擎（DAGEngine 迭代执行，/loop 模式）
- cross_file_scanner.py: 跨文件合规扫描器（影响分析 + 合规传播）
- multi_agent_orchestrator.py: 多 Agent 编排器（六步流水线转 DAG）

使用建议：
- 可以导入和使用，但注意 API 可能变化
- 不推荐在生产环境中依赖
- 所有导出类均被 @experimental 装饰器标记
"""

from functools import wraps
import warnings


def experimental(feature_name: str, version: str = "0.1.0"):
    """
    标记函数或类为实验性

    用法：
        @experimental("KnowledgeProvider")
        def create_knowledge():
            pass
    """
    def decorator(func_or_class):
        if isinstance(func_or_class, type):
            # 对类（包括 Enum、dataclass）：添加 __experimental__ 标记
            # 不改变类本身，避免破坏 Enum 迭代和 dataclass 特性
            func_or_class.__experimental__ = {
                "feature_name": feature_name,
                "version": version,
            }
            func_or_class.__doc__ = (
                f"@experimental ({feature_name}, since v{version}) — "
                f"API may change in future versions.\n\n"
                + (func_or_class.__doc__ or "")
            )
            return func_or_class
        # 对函数：保持原有行为，运行时警告
        @wraps(func_or_class)
        def wrapper(*args, **kwargs):
            warnings.warn(
                f"{feature_name} is experimental (since v{version}). "
                f"API may change in future versions.",
                UserWarning,
                stacklevel=2,
            )
            return func_or_class(*args, **kwargs)
        return wrapper
    return decorator


# ─── 导出实验性模块的主要类 ──────────────────────────────

from harness.experimental.autonomous_loop import (
    AutonomousLoopConfig,
    AutonomousLoopEngine,
    AutonomousLoopResult,
)
from harness.experimental.cross_file_scanner import (
    CrossFileScanEngine,
    CrossFileScanResult,
    CrossFileRiskGrade,
    FileCompliancePropagation,
)
from harness.experimental.multi_agent_orchestrator import (
    MultiAgentOrchestrator,
    OrchestrationResult,
    PipelineConfig,
    PIPELINE_STEPS,
)

# ─── @experimental 装饰器标记 ──────────────────────────────

AutonomousLoopConfig = experimental("AutonomousLoopConfig")(AutonomousLoopConfig)
AutonomousLoopEngine = experimental("AutonomousLoopEngine")(AutonomousLoopEngine)
AutonomousLoopResult = experimental("AutonomousLoopResult")(AutonomousLoopResult)

CrossFileScanEngine = experimental("CrossFileScanEngine")(CrossFileScanEngine)
CrossFileScanResult = experimental("CrossFileScanResult")(CrossFileScanResult)
CrossFileRiskGrade = experimental("CrossFileRiskGrade")(CrossFileRiskGrade)
FileCompliancePropagation = experimental("FileCompliancePropagation")(FileCompliancePropagation)

MultiAgentOrchestrator = experimental("MultiAgentOrchestrator")(MultiAgentOrchestrator)
OrchestrationResult = experimental("OrchestrationResult")(OrchestrationResult)
PipelineConfig = experimental("PipelineConfig")(PipelineConfig)

__all__ = [
    # 装饰器
    "experimental",
    # 自主循环引擎
    "AutonomousLoopConfig",
    "AutonomousLoopEngine",
    "AutonomousLoopResult",
    # 跨文件合规扫描器
    "CrossFileScanEngine",
    "CrossFileScanResult",
    "CrossFileRiskGrade",
    "FileCompliancePropagation",
    # 多 Agent 编排器
    "MultiAgentOrchestrator",
    "OrchestrationResult",
    "PipelineConfig",
    "PIPELINE_STEPS",
]

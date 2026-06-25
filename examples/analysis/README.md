# 代码分析示例

> 调用图构建、污点追踪、God Class 检测、变更影响分析——四大代码分析引擎

**定位**：代码分析示例展示 harness-cook 的静态分析能力——从调用关系追踪到安全污点流，从反模式检测到变更影响传播。

## 运行

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/analysis/demo_analysis.py
```

## 输出内容

| Demo | 说明 |
|------|------|
| 1. 调用图构建 | CallGraphBuilder.scan_python() → 方法级调用关系图 |
| 2. 污点追踪 | TaintTracker.track_python() → source→sink 数据流安全分析，含自定义 source/sink |
| 3. God Class 检测 | ATFD/WMC/TCC 三维指标，复合阈值判定 |
| 4. 变更影响分析 | DependencyGraph 依赖图构建 + ImpactAnalysis 影响传播路径 |

## 核心逻辑

```python
from harness.call_graph import CallGraphBuilder
from harness.taint import TaintTracker
from harness.god_class_metrics import GodClassMetrics, ClassMetrics
from harness.impact_analyzer import ImpactAnalyzer

# 调用图
builder = CallGraphBuilder()
graph = builder.scan_python(code)       # → 方法级调用关系

# 污点追踪
tracker = TaintTracker()
findings = tracker.track_python(code)   # → source→sink 安全风险

# God Class 检测
metrics = GodClassMetrics()
is_god = metrics.is_god_class(class_metrics)  # → ATFD/WMC/TCC 三维判定

# 影响分析
analyzer = ImpactAnalyzer(project_root=".")
analysis = analyzer.analyze_impact(["config.py"])  # → 依赖传播 + 风险级别
```

## 适用场景

- 安全审计——检测用户输入到危险函数的数据流（SQL注入/XSS/命令注入）
- 代码质量——识别 God Class 反模式，推荐拆分
- 变更评估——修改核心文件前评估影响范围和风险级别
- 依赖分析——构建文件级依赖图，找出关键入口点

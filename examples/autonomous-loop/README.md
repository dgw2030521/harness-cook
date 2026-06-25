# 自主循环 & 跨文件合规扫描示例

> 自主循环引擎迭代执行 + 收敛检测 + 跨文件影响传播 + 风险分级

**注意**: 此示例使用 `@experimental` 模块，API 可能变更。

## 运行

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/autonomous-loop/demo_autonomous_loop.py
```

## 输出内容

| Demo | 说明 |
|------|------|
| 1. 自主循环引擎 | AutonomousLoopEngine 配置 + DAG 工作流迭代执行，观察收敛行为 |
| 2. 循环条件对比 | 5 种停止条件：max_iterations / convergence_window / budget_token_limit / convergence_check callback / Gate 升级中断 |
| 3. 跨文件合规扫描 | CrossFileScanEngine 影响传播——变更文件 → 直接/间接影响 → 按层级选择合规规则范围 |
| 4. 风险分级 | CrossFileRiskGrade 5 级评定——CLEAN / LOW / MEDIUM / HIGH / CRITICAL 的触发条件 |

## 核心 API

### AutonomousLoopEngine（自主循环引擎）

```python
from harness.experimental.autonomous_loop import (
    AutonomousLoopEngine,   # 自主循环引擎
    AutonomousLoopConfig,   # 循环配置
    AutonomousLoopResult,   # 循环结果
)

# 用法
dag_engine = DAGEngine()
loop_engine = AutonomousLoopEngine(dag_engine)
result = loop_engine.run(workflow, config)
```

**AutonomousLoopConfig 配置项**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `max_iterations` | int | 10 | 最大迭代次数（硬上限） |
| `convergence_window` | int | 2 | 连续 N 次无新发现则停止 |
| `budget_token_limit` | int | 0 | token 预算上限（0=不限制） |
| `budget_time_limit_ms` | int | 0 | 时间预算上限（0=不限制） |
| `convergence_check` | Callable | None | 自定义收敛检查函数 |

**AutonomousLoopResult 结果字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `iterations` | int | 实际迭代次数 |
| `converged` | bool | 是否收敛 |
| `budget_exhausted` | bool | 预算是否耗尽 |
| `contexts` | List[ExecutionContext] | 各迭代的执行上下文 |
| `total_tokens` | int | 累计 token 消耗 |
| `total_duration_ms` | int | 累计耗时 |
| `stop_reason` | str | 停止原因："converged:no_new_discoveries" / "converged:custom" / "budget_exhausted:token" / "budget_exhausted:time" / "max_iterations" / "escalated" |

**停止条件优先级**：budget > escalated > convergence_check > convergence_window > max_iterations

### CrossFileScanEngine（跨文件合规扫描）

```python
from harness.experimental.cross_file_scanner import (
    CrossFileScanEngine,            # 跨文件合规扫描引擎
    CrossFileScanResult,            # 扫描结果
    CrossFileRiskGrade,             # 风险评级枚举
    FileCompliancePropagation,      # 单文件合规传播结果
)
```

**合规传播规则范围**：

| 影响层级 | 扫描规则范围 |
|----------|-------------|
| 变更文件 (is_change_file) | 全规则 |
| 直接影响 (direct) | security + architecture 类规则 |
| 间接影响 (indirect) | 仅 critical 严重性规则 |

### CrossFileRiskGrade（风险评级）

| 级别 | 触发条件 |
|------|----------|
| CLEAN | total_violations = 0 |
| LOW | 影响风险=low + 违规severity 为 low/medium |
| MEDIUM | 影响风险=medium + 违规severity 为 medium/low；或影响风险=low + 违规severity 为 critical/high |
| HIGH | 影响风险=high + 违规severity 为 medium/low；或影响风险=medium + 违规severity 为 critical |
| CRITICAL | 影响风险=high + 违规severity 为 critical/high |

## 适用场景

- AI Agent 自主迭代执行——反复扫描/修复直到收敛，避免无限循环
- 变更影响评估——修改核心文件后自动检测影响范围和合规风险
- CI/CD 门禁——高风险变更阻断发布，低风险变更自动放行
- 合规审计——跨文件合规违规追踪，从变更源头沿依赖链传播

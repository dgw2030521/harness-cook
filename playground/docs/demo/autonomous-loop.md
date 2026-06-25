# 自主循环 Demo

> AutonomousLoopEngine + CrossFileScanEngine——实验性模块的自主迭代与跨文件扫描

**定位**：自主循环是 harness-cook 的实验性能力——Agent 自主迭代直到收敛，跨文件合规扫描追踪影响传播链。

⚠️ **注意**：这是 `@experimental` 模块，API 可能变更。

完整可运行脚本见项目 `examples/autonomous-loop/` 目录（`demo_autonomous_loop.py`）。

---

## Demo 1：自主循环引擎

```python
from harness.experimental.autonomous_loop import (
    AutonomousLoopEngine, AutonomousLoopConfig, AutonomousLoopResult,
)

config = AutonomousLoopConfig(
    max_iterations=5,           # 最大迭代次数
    convergence_threshold=0.95, # 收敛阈值
    gate_pass_required=True,    # 每轮需门禁通过
)

engine = AutonomousLoopEngine(config)

# 启动自主循环
result = engine.run(
    task="修复 main.py 中的安全违规",
    initial_code="...",
)

print(f"迭代次数: {result.iterations}")
print(f"是否收敛: {result.converged}")
print(f"最终状态: {result.final_state}")
```

### 预期输出

| 观察项 | 说明 |
|--------|------|
| `max_iterations` | 最大迭代上限（防止无限循环） |
| `convergence_threshold` | 收敛判定阈值（质量分数 ≥ 阈值 → 停止） |
| `gate_pass_required` | 每轮迭代必须通过门禁审批 |

---

## Demo 2：循环终止条件

```python
# 三种终止条件

# 条件 1：达到最大迭代
config1 = AutonomousLoopConfig(max_iterations=10)

# 条件 2：质量分数收敛
config2 = AutonomousLoopConfig(convergence_threshold=0.95)

# 条件 3：门禁审批通过
config3 = AutonomousLoopConfig(gate_pass_required=True)

# 组合条件——任一满足即停止
config_combined = AutonomousLoopConfig(
    max_iterations=10,
    convergence_threshold=0.95,
    gate_pass_required=True,
)
```

### 终止条件

| 条件 | 说明 | 安全保障 |
|------|------|---------|
| `max_iterations` | 硬上限防止无限循环 | 必配 |
| `convergence_threshold` | 质量收敛后停止迭代 | 可选 |
| `gate_pass_required` | 门禁通过即停止 | 可选 |

---

## Demo 3：跨文件合规扫描

```python
from harness.experimental.cross_file_scanner import (
    CrossFileScanEngine, CrossFileScanResult, CrossFileRiskGrade,
    FileCompliancePropagation,
)

scanner = CrossFileScanEngine()

# 扫描跨文件合规传播
result = scanner.scan(
    root_file="app.py",
    project_dir="/path/to/project",
)

print(f"扫描文件数: {result.files_scanned}")
print(f"传播链长度: {len(result.propagation_chain)}")

for prop in result.propagation_chain:
    print(f"  {prop.source_file} → {prop.target_file}: {prop.risk_grade.value}")
```

### 预期输出

| 观察项 | 说明 |
|--------|------|
| `propagation_chain` | 合规违规的跨文件传播路径 |
| `risk_grade` | 每个传播节点的风险级别 |

---

## Demo 4：风险分级

```python
# 四级风险分级
grades = [
    CrossFileRiskGrade.LOW,       # 低风险——仅影响自身
    CrossFileRiskGrade.MEDIUM,    # 中风险——影响 2-3 个下游文件
    CrossFileRiskGrade.HIGH,      # 高风险——影响核心入口文件
    CrossFileRiskGrade.CRITICAL,  # 严重——影响安全/合规关键文件
]

for grade in grades:
    print(f"  {grade.value}: {grade.description}")
```

### 风险级别

| RiskGrade | 说明 | 处置建议 |
|-----------|------|---------|
| LOW | 仅影响自身 | 记录即可 |
| MEDIUM | 影响 2-3 个下游 | 建议审查 |
| HIGH | 影响核心入口 | 必须审查 |
| CRITICAL | 影响安全/合规关键文件 | 立即阻断 |

---

## Profile YAML 配置示例

```yaml
autonomous_loop:
  max_iterations: 5
  convergence_threshold: 0.95
  gate_pass_required: true

cross_file_scan:
  enabled: true
  max_depth: 5                 # 传播链最大追踪深度
  critical_patterns:           # 严重风险模式
    - "security-violation"
    - "data-leak"
```

---

## 相关导航

- 📖 原理 → [门禁层](/guide/gate-layer) · [合规层](/guide/compliance-layer)
- 🏃 跑代码 → [examples/autonomous-loop/](../../examples/autonomous-loop/)
- ⚠️ 实验性 → API 可能变更，不建议生产环境直接使用

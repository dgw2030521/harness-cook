# 学习 + 调度示例

> 模式挖掘、反模式检测、智能调度——从历史轨迹中学习 + 并行分组 + Token 预估 + 关键路径

**定位**：学习引擎从 Agent 执行历史中挖掘成功/失败模式，智能调度器基于 DAG 拓扑生成最优并行执行计划。

## 运行

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/learning-scheduler/demo_learning_scheduler.py
```

## 输出内容

| Demo | 说明 |
|------|------|
| 1. 经验存储 | ExperienceStore 记录执行轨迹——成功/失败轨迹积累历史数据 |
| 2. 模式挖掘 | PatternMiner.mine() 从历史轨迹中发现成功/失败/浪费模式 |
| 3. 智能调度 | SmartScheduler.plan() → 并行分组 + 关键路径 + 检查点 |
| 4. 资源管理 | Token/RPM 跟踪 + 推荐执行模式（aggressive/balanced/conservative） |
| 5. 反模式检测 | 识别 Token 超预估、频繁失败组合、资源浪费等常见陷阱 |

## 核心逻辑

```python
from harness.learning import ExperienceStore, PatternMiner
from harness.scheduler import SmartScheduler, SmartSchedulerConfig

# 经验存储 + 模式挖掘
store = ExperienceStore()
store.store(execution_trace)          # 记录轨迹
miner = PatternMiner(store)
recommendations = miner.mine()        # 挖掘模式 → 生成推荐

# 智能调度
scheduler = SmartScheduler(config=SmartSchedulerConfig(
    max_parallelism=4,
    token_budget=200000,
))
plan = scheduler.plan(dag_workflow)   # → 并行分组 + 关键路径 + 检查点
```

## 适用场景

- 多次执行后自动学习——哪些 Agent 组合成功率高、哪些经常失败
- 大型 DAG 工作流——智能调度找出最优并行执行顺序
- Token 预算有限——自动推荐保守/激进执行模式
- 反模式预警——Token 超预估、资源浪费自动检测

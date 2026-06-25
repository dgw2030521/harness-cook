# 智能调度器

> harness-cook 的「**时序大脑**」——资源感知调度、并行度优化、token 预算控制

**快速导航**：[📖 原理（本页）](#原理) · [🎓 使用方法](/tutorial/basic-usage) · [🏃 可运行 Demo](/demo/learning-scheduler)

---

## 原理

### 拓扑分析→并行分组

SmartScheduler 分析 DAG 拓扑结构，将节点分为可并行执行的层级（parallel_groups）。同一层内节点无依赖，可同时运行。

### token 预估

根据 AgentRegistry 中的 Agent 信息估算每层 token 消耗，帮助用户在执行前预判总成本。

### 关键路径识别

标记影响总执行时间的最长路径（critical_path），用户可据此优化瓶颈节点。

### 资源警告

token 不足或并行度过高时发出 ResourceWarning，提示用户调整参数或减少并行度。

### 闭环反馈

接收 Learning 模块的 RECOMMENDATION 事件，自动调整调度参数（token_ratio、timeout_ratio 等）。

```python
from harness.scheduler import SmartScheduler

scheduler = SmartScheduler()
plan = scheduler.plan(workflow)

# 调度计划内容
print(f"并行分组: {plan.parallel_groups}")
print(f"预估 token: {plan.estimated_tokens}")
print(f"关键路径: {plan.critical_path}")

# 资源更新与检查
scheduler.update_resource(tokens_used=500, rpm_used=10, parallelism=2)
can_more = scheduler.can_execute_more()    # → bool
mode = scheduler.recommend_mode()          # → "conservative"/"moderate"/"aggressive"
```

### 核心概念

| 类 | 职责 |
|----|------|
| SmartScheduler | 资源感知调度器 |
| SmartSchedulerConfig | 调度配置（并行度、token_ratio 等） |
| SchedulePlan | 调度计划（并行分组、预估 token、关键路径） |
| ResourceUsage | 资源用量（tokens、rpm、并行度） |
| Recommendation | Learning 模块推送的调度建议 |

### 调度流程

```mermaid
flowchart LR
    A[分析 DAG 拓扑] --> B[并行分组]
    B --> C[估算每层 token]
    C --> D[识别关键路径]
    D --> E[生成 SchedulePlan]
    E --> F[执行时动态更新资源]
    F --> G[Learning 推荐 → 调整参数]
```

<details>
<summary>ASCII 原图</summary>

```
分析 DAG 拓扑 → 并行分组 → 估算每层 token → 识别关键路径 → 生成 SchedulePlan
→ 执行时动态更新资源 → Learning 推荐 → 调整参数
```
</details>

### 与 Learning 模块协作

| 事件类型 | 方向 | 作用 |
|----------|------|------|
| RECOMMENDATION | Learning → Scheduler | 调整 token_ratio、timeout_ratio |
| SCHEDULE_WARNING | Scheduler → EventBus | 资源不足告警 |

---

## 配置

### Profile YAML 配置

```yaml
scheduler:
  max_parallelism: 4        # 最大并行度
  token_ratio: 1.2          # token 预估放大系数
  timeout_ratio: 1.5        # 超时预估放大系数
  rpm_limit: 60             # RPM 限制
```

---

更多配置细节见 [基础用法教程](/tutorial/basic-usage)，可运行 Demo 见 [学习+调度 Demo](/demo/learning-scheduler)。
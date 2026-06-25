# Agent 调用分层路由 Demo

> ModelTier 三级分层 + TokenTracker 成本追踪 + GateManager 通知推送 + 构造函数注入解耦

**定位**：Agent 调用分层路由是 harness-cook 的「成本与质量」控制层——PREMIUM/STANDARD/FAST 三级按任务匹配、Token 跟踪预算控制、门禁结果多通道通知、构造函数依赖注入。

> **注意**：harness-cook 对接的是用户的 AI Agent（Claude Code / Copilot CLI / Cursor 等），不直接调用 LLM。`ModelTier` 分层控制的是 **Agent 调用的模型层级**，而不是 harness-cook 自身去调 LLM。

完整可运行脚本见项目 `examples/llm-tiering/` 目录（`demo_llm_tiering.py`）。

---

## Demo 1：Agent 调用分层路由

```python
from harness.llm import ModelTier, LLMConstraints

# 三级模型分层
constraints = LLMConstraints(
    tier=ModelTier.STANDARD,
    allowed_models=["gpt-4", "gpt-3.5-turbo", "claude-3-haiku"],
    blocked_models=["gpt-4-32k"],        # 高成本模型禁止
    max_tokens=4096,
    temperature_range=(0.0, 1.0),
)

# 模型验证
print(f"gpt-4 允许? {constraints.validate_model('gpt-4')}")
print(f"gpt-4-32k 允许? {constraints.validate_model('gpt-4-32k')}")

# 温度验证
print(f"温度 0.7 有效? {constraints.validate_temperature(0.7)}")

# 约束摘要
print(constraints.summary())
```

### 三级分层

| ModelTier | 定位 | 适用场景 | 成本级别 |
|-----------|------|---------|---------|
| PREMIUM | 高质量输出 | 架构设计、安全审查 | 💰💰💰 |
| STANDARD | 日常编码 | 代码生成、Bug 修复 | 💰💰 |
| FAST | 快速响应 | 格式化、简单问答 | 💰 |

> 三级分层控制的是**约束 Agent 使用的模型层级**，harness-cook 自身不调 LLM——它是给 Agent 设边界，不是自己开车。

---

## Demo 2：Token 跟踪与成本估算

```python
from harness.llm import TokenTracker, TokenUsageRecord

tracker = TokenTracker()

# 记录 token 使用
tracker.record(TokenUsageRecord(
    model="gpt-4",
    tier=ModelTier.STANDARD,
    input_tokens=500,
    output_tokens=1000,
    task_id="task-001",
))

# 成本估算
cost = tracker.estimate_cost(model="gpt-4", input_tokens=500, output_tokens=1000)
print(f"本次调用成本: ${cost:.4f}")

# 预算检查
is_over = tracker.check_over_limit(budget=10.0)
print(f"超出预算? {is_over}")

# 使用统计
stats = tracker.stats()
print(f"总 token: {stats.total_tokens}")
print(f"总成本: ${stats.total_cost:.2f}")
```

### 分层定价

| 模型 | Tier | Input Price | Output Price |
|------|------|------------|-------------|
| gpt-4 | STANDARD | $0.03/1K | $0.06/1K |
| gpt-3.5-turbo | FAST | $0.0005/1K | $0.0015/1K |
| claude-3-opus | PREMIUM | $0.015/1K | $0.075/1K |

---

## Demo 3：门禁通知推送

```python
from harness.gate_notification import (
    GateManager, INotifier, LocalNotifier, NotificationPriority, GateNotification
)

# 使用本地通知器（默认）——开发/调试场景
manager = GateManager(notifier=LocalNotifier())

# 也可自定义通知器实现 INotifier Protocol
class SlackNotifier(INotifier):
    def send(self, notification: GateNotification) -> bool:
        # 推送到 Slack Webhook
        print(f"[Slack] 通知已发送到 #{notification.recipient}")
        return True

manager_slack = GateManager(notifier=SlackNotifier())

# 创建审批 gate + 发送通知
notification = manager.create_gate(
    gate_id="quality_gate",
    recipient="team-lead",
    message="质量门禁未通过——3项安全违规",
    priority=NotificationPriority.URGENT,
    deadline_minutes=30,
)

print(f"审批通知已创建: {notification.gate_id}")
print(f"优先级: {notification.priority.value}")
print(f"截止时间: {notification.deadline}")

# 等待审批（轮询通知器，超时自动降级）
decision = manager.wait_for_approval("quality_gate", timeout_seconds=60)
print(f"审批结果: {decision.value}")  # approved/rejected/timeout/cancelled

# 审批记录追溯
records = manager.get_records()
for r in records:
    print(f"  Gate {r.gate_id}: {r.decision.value} (by {r.decided_by})")
```

### 通知机制

| 组成 | 类 | 说明 |
|------|----|------|
| 通知器协议 | `INotifier` | 定义 `send(notification)` 方法，可自定义实现 |
| 本地通知器 | `LocalNotifier` | 默认实现——打印到终端 |
| 通知优先级 | `NotificationPriority` | URGENT/NORMAL/INFO 三级 |
| 管理器 | `GateManager` | 创建审批 → 发送通知 → 等待审批 → 超时降级 |
| 审批记录 | `GateApprovalRecord` | 追溯每次审批决策

---

## Demo 4：依赖注入模式

harness-cook 核心模块支持两种使用方式：全局单例模式（快速上手）和依赖注入模式（生产推荐）。

```python
# 全局单例模式——快速上手
from harness import get_registry, get_bus, DAGEngine

engine = DAGEngine()  # 自动使用全局单例 registry/bus/gate_engine

# 依赖注入模式——生产环境推荐
from harness import AgentRegistry, EventBus, DAGEngine
from harness.gates import GateEngine

bus = EventBus()
registry = AgentRegistry(bus=bus)
gate_engine = GateEngine(bus=bus)

# 显式注入所有依赖——完全可控
engine = DAGEngine(
    registry=registry,
    gate_engine=gate_engine,
    bus=bus,
)

# 也可只注入部分依赖——其余自动使用全局单例
engine = DAGEngine(registry=custom_registry)  # bus/gate_engine 自动获取
```

### 注入模式对比

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| 全局单例 | 隐式获取依赖，零配置 | 测试、简单场景 |
| 依赖注入 | 显式传入依赖，完全可控 | 生产环境、需替换实现 |

**插拔机制**：构造函数参数可选——传了就用传入的，不传就用全局单例。无需 DI 容器，Python 的函数参数天然就是依赖注入。

---

## Profile YAML 配置示例

```yaml
llm:
  tier: standard
  allowed_models:
    - gpt-4
    - gpt-3.5-turbo
  blocked_models:
    - gpt-4-32k
  max_tokens: 4096
  temperature_range: [0.0, 1.0]

token_tracking:
  budget: 50.0            # 日预算上限（美元）
  alert_threshold: 0.8    # 80% 时告警

gate_notification:
  channels:
    - email
    - slack
  critical_only: false    # 所门禁结果都通知
```

---

## 相关导航

- 📖 原理 → [门禁层](/guide/gate-layer) · [核心概念](/guide/core-concepts)
- 🏃 跑代码 → [examples/llm-tiering/](../../examples/llm-tiering/)
- 🎓 方法 → [门禁审批](/tutorial/gate-approval)

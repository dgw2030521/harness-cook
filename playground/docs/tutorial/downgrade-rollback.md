# 降级与回滚

本教程展示如何使用 DowngradeEngine 配置超时降级策略、使用 RollbackEngine 创建文件快照并还原，以及两者与 DAGEngine 的联动使用。RollbackEngine 概念见 [自动回滚](/guide/rollback)。

## Step 1: 理解降级与回滚的关系

降级和回滚是两种不同的安全机制，分别应对不同的失败场景：

| 机制 | 应对场景 | 核心能力 |
|------|---------|---------|
| DowngradeEngine | 门禁审批超时/无响应 | 自动选择降级动作（跳过/简化/中止） |
| RollbackEngine | Agent 执行失败导致文件损坏 | 快照文件内容，失败时还原到快照状态 |

两者在 DAGEngine 中联动：
- 节点执行前 → RollbackEngine 创建快照
- 节点门禁超时 → DowngradeEngine 决策降级
- 节点执行失败 → RollbackEngine 恢复快照（AUTO 模式下自动触发）

## Step 2: 降级策略配置

### 降级动作

三种降级动作见 [降级策略](/guide/downgrade#降级动作)。实操配置时按风险级别选择动作即可——高风险用 ABORT，中风险用 SIMPLIFY，低风险用 SKIP。

### DowngradePolicy

`DowngradePolicy` 按风险级别配置不同的超时阈值和降级动作：

```python
from harness.downgrade import DowngradePolicy, DowngradeEngine
from harness.gate_notification import DowngradeAction

policy = DowngradePolicy(
    name="project-alpha",

    # 按风险级别设置超时（分钟）
    high_timeout_minutes=15,      # 高风险：短超时，快速 abort
    medium_timeout_minutes=30,    # 中风险：中等超时
    low_timeout_minutes=60,       # 低风险：长超时，给更多审批时间

    # 按风险级别设置降级动作
    high_action=DowngradeAction.ABORT,     # 高风险超时 → 中止
    medium_action=DowngradeAction.SIMPLIFY, # 中风险超时 → 简化
    low_action=DowngradeAction.SKIP,        # 低风险超时 → 跳过

    # 自定义回调（降级执行前的 hook）
    on_downgrade_callback=lambda gate_id, action, reason: print(f"降级: {gate_id} → {action.value}"),

    # 通知设置
    notify_on_downgrade=True,
    fallback_message_template="审批超时({risk}),自动降级({action})",
)

# 查询策略
print(policy.get_timeout("high"))   # → 15
print(policy.get_action("low"))     # → DowngradeAction.SKIP
```

::: tip
策略设计原则：高风险场景用短超时+ABORT（宁可失败也不放行），低风险场景用长超时+SKIP（给审批更多时间，超时后安全放行）。
:::

## Step 3: 执行降级决策

`DowngradeEngine` 根据策略执行降级决策：

```python
from harness.downgrade import DowngradeEngine, DowngradePolicy

engine = DowngradeEngine(policy=policy)

# 执行降级——根据风险级别选择动作
decision = engine.execute_downgrade(
    gate_id="gate-security-001",
    risk_level="high",
    reason="审批超时15分钟",
)

# decision 是 GateApprovalDecision:
# - SKIP → APPROVED（有条件放行）
# - SIMPLIFY → APPROVED（简化后放行）
# - ABORT → REJECTED（中止执行）

print(f"决策: {decision.value}")   # → "rejected" (高风险 → ABORT)
```

降级结果映射：

| 降级动作 | 对应决策 | 含义 |
|---------|---------|------|
| SKIP | APPROVED | 跳过门禁，有条件通过 |
| SIMPLIFY | APPROVED | 简化变更，有条件通过 |
| ABORT | REJECTED | 中止执行 |

## Step 4: 降级事件追踪

每次降级都会产生审计记录，`DowngradeTracker` 统计降级率和瓶颈门禁：

```python
# 降级引擎自带 tracker
tracker = engine.tracker

# 查询降级事件
events = tracker.get_events(gate_id="gate-security-001", limit=10)
for event in events:
    print(event.summary())
    # → [abort] gate=gate-security-001 risk=high reason=审批超时... policy=project-alpha

# 统计降级率
stats = tracker.stats()
print(f"总降级次数: {stats['total_downgrades']}")
print(f"按动作分布: {stats['by_action']}")
print(f"瓶颈门禁: {stats['bottleneck_gates']}")
```

瓶颈门禁是降级次数最多的 gate_id——频繁超时意味着审批流程有问题，需要优化审批速度或调整超时阈值。

## Step 5: 引擎统计

`DowngradeEngine.stats()` 合并策略配置和追踪统计：

```python
stats = engine.stats()
print(f"策略名: {stats['policy']['name']}")
print(f"高风险超时: {stats['policy']['high_timeout']} 分钟")
print(f"低风险动作: {stats['policy']['low_action']}")
print(f"降级总次数: {stats['tracker']['total_downgrades']}")
```

## Step 6: 回滚策略——RollbackPolicy

`RollbackPolicy` 定义节点失败时的回滚行为：

| 策略 | 值 | 行为 |
|------|---|------|
| NONE | `"none"` | 不创建快照，不回滚 |
| MANUAL | `"manual"` | 创建快照，但失败时不自动回滚（需手动调用） |
| AUTO | `"auto"` | 创建快照，失败时自动回滚到快照状态 |

```python
from harness.types import RollbackPolicy

# 安全开发场景——失败自动回滚
policy = RollbackPolicy.AUTO

# 保守场景——快照保留但需人工确认才回滚
policy = RollbackPolicy.MANUAL

# 低风险场景——不快照不回滚
policy = RollbackPolicy.NONE
```

## Step 7: 创建文件快照

`RollbackEngine` 在节点执行前创建文件快照——拷贝文件内容 + 计算 SHA-256 hash：

```python
from harness.rollback import RollbackEngine, SnapshotSet

engine = RollbackEngine()

# 创建快照——节点执行前
snapshot_set = engine.create_snapshot(
    execution_id="ex-1",
    node_id="code",
    file_paths=[
        "/projects/my-api/src/auth/middleware.ts",
        "/projects/my-api/src/auth/jwt.ts",
        "/projects/my-api/package.json",
    ],
)

print(f"快照ID: {snapshot_set.snapshot_id}")
print(f"快照文件数: {len(snapshot_set.snapshots)}")

# 每个文件快照包含：
for snapshot in snapshot_set.snapshots:
    print(f"  文件: {snapshot.file_path}")
    print(f"  SHA-256: {snapshot.content_hash}")
    print(f"  时间戳: {snapshot.timestamp}")
```

快照存储在 `~/.harness/rollback/` 目录，每个执行上下文有独立快照目录。SHA-256 hash 确保内容完整性。

## Step 8: 恢复快照

节点失败时，恢复快照将所有文件还原到快照时的内容：

```python
from harness.rollback import RollbackResult

# 恢复快照——节点失败时
result = engine.restore_snapshot(snapshot_set.snapshot_id)

print(f"成功: {result.success}")
print(f"还原文件数: {result.files_restored}")
print(f"失败文件数: {result.files_failed}")
print(f"耗时: {result.duration_ms}ms")

if not result.success:
    for error in result.errors:
        print(f"  错误: {error}")
```

恢复逻辑：
- 文件在快照时存在 → 写入快照内容还原
- 文件在快照时不存在 → 删除当前文件（如果存在）
- 文件在快照时读取失败 → 尝试删除当前文件

## Step 9: 验证快照完整性

`verify_snapshot` 检查当前文件 hash 是否与快照一致——判断文件是否被修改：

```python
from harness.rollback import VerifyResult

verify = engine.verify_snapshot(snapshot_set.snapshot_id)

print(f"一致: {verify.consistent}")
print(f"一致文件数: {verify.files_consistent}")
print(f"被修改文件数: {verify.files_modified}")
print(f"缺失文件数: {verify.files_missing}")

if verify.modified_paths:
    print(f"被修改的文件: {verify.modified_paths}")
if verify.missing_paths:
    print(f"缺失的文件: {verify.missing_paths}")
```

## Step 10: 管理快照生命周期

### 列出快照

```python
# 列出所有快照
all_snapshots = engine.list_snapshots()

# 按执行ID过滤
snapshots = engine.list_snapshots(execution_id="ex-1")

# 按节点ID过滤
snapshots = engine.list_snapshots(node_id="code")
```

### 清理过期快照

```python
# 清理超过 TTL（默认7天）和超过数量上限（默认100）的快照
deleted = engine.cleanup_snapshots()

# 自定义 TTL 和上限
deleted = engine.cleanup_snapshots(
    ttl_seconds=86400 * 3,  # 3天过期
    max_snapshots=50,        # 最多保留50个
)

print(f"清理了 {deleted} 个过期快照")
```

## Step 11: 降级与回滚联动

DAGEngine 在执行节点时自动集成降级和回滚：

```python
from harness.engine import DAGEngine
from harness.rollback import RollbackEngine, get_rollback_engine
from harness.downgrade import DowngradeEngine, DowngradePolicy
from harness.gates import GateEngine
from harness.registry import AgentRegistry
from harness.bus import EventBus
from harness.types import RollbackPolicy, GateMode, DAGNode, DAGEdge, DAGWorkflow

bus = EventBus()
registry = AgentRegistry(bus=bus)
gate_engine = GateEngine(bus=bus)
rollback_engine = get_rollback_engine()
downgrade_engine = DowngradeEngine(policy=DowngradePolicy(
    name="dev-safety",
    high_action=DowngradeAction.ABORT,
    medium_action=DowngradeAction.SIMPLIFY,
    low_action=DowngradeAction.SKIP,
))

# 创建 DAGEngine——传入降级引擎和回滚策略
engine = DAGEngine(
    registry=registry,
    gate_engine=gate_engine,
    bus=bus,
    rollback_engine=rollback_engine,
    rollback_policy=RollbackPolicy.AUTO,       # 自动回滚
    downgrade_engine=downgrade_engine,          # 降级引擎
)

# 执行工作流
workflow = DAGWorkflow(
    id="wf-with-safety",
    name="带降级和回滚的工作流",
    nodes=[
        DAGNode(
            id="code", agent_type="coder", task="实现登录功能",
            metadata={"risk_level": "medium"},   # 降级引擎读取风险级别
            gate=GateDefinition(id="gate-code", mode=GateMode.HYBRID, checks=[]),
        ),
    ],
    edges=[],
)

context = engine.execute(workflow, initial_context={
    "file_paths": ["/projects/my-api/src/auth.ts"],  # 快照文件列表
})

# 检查结果
if context.escalated:
    print(f"升级人工: {context.escalation_reason}")
else:
    print(f"成功完成: {list(context.completed_nodes)}")

# 查看快照和回滚记录
for node_id, snapshot_id in context.node_snapshots.items():
    print(f"节点 {node_id} 的快照: {snapshot_id}")
for node_id, rollback_result in context.rollback_results.items():
    print(f"节点 {node_id} 的回滚: {rollback_result}")
```

联动流程：

1. 节点执行前 → RollbackEngine 创建快照（MANUAL/AUTO 模式）
2. 节点执行 → Agent 执行任务
3. 门禁检查失败 → DowngradeEngine 评估降级（如有配置）
4. 降级通过 → 有条件放行，Pipeline 继续
5. 降级拒绝/无降级引擎 → 升级人工
6. AUTO 模式下失败 → RollbackEngine 自动回滚到快照
7. MANUAL 模式下失败 → 需手动调用 `restore_snapshot`

## Step 12: 工厂函数和单例

```python
# 获取默认回滚引擎（单例）
from harness.rollback import get_rollback_engine
rollback_engine = get_rollback_engine()

# 获取按策略名隔离的降级引擎
from harness.downgrade import get_downgrade_engine, DowngradePolicy
default_engine = get_downgrade_engine()                          # 默认策略
custom_engine = get_downgrade_engine(
    policy_name="strict",
    policy=DowngradePolicy(name="strict", high_action=DowngradeAction.ABORT),
)
```

下一步 → [Pipeline 编排](./pipeline) | [Adapter 部署](./adapter-deployment)

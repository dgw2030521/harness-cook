# 降级 + 回滚 Demo

> 门禁超时自动降级（ABORT/SIMPLIFY/SKIP） + 执行失败自动回滚（文件快照恢复）

**定位**：降级和回滚是 harness-cook 的安全网机制——门禁审批超时自动降级不阻塞流程，Agent 执行失败自动回滚到快照版本。

完整可运行脚本见项目 `examples/downgrade-rollback/` 目录（`demo_downgrade_rollback.py`）。

---

## Demo 1：降级策略配置

```python
from harness.downgrade import DowngradePolicy, DowngradeAction

policy = DowngradePolicy(
    name="production",
    high_timeout_minutes=15,     # 高风险: 15分钟超时 → abort
    medium_timeout_minutes=30,   # 中风险: 30分钟超时 → simplify
    low_timeout_minutes=60,      # 低风险: 60分钟超时 → skip
)

# 查看各级别策略
for risk in ["high", "medium", "low"]:
    timeout = policy.get_timeout(risk)
    action = policy.get_action(risk)
    print(f"{risk}: 超时={timeout}分钟, 动作={action.value}")
```

### 预期输出

| 风险级别 | 超时时间 | 降级动作 |
|---------|---------|---------|
| high | 15 分钟 | ABORT |
| medium | 30 分钟 | SIMPLIFY |
| low | 60 分钟 | SKIP |

降级动作含义见 [降级策略](/guide/downgrade#降级动作)

---

## Demo 2：降级事件追踪

```python
from harness.downgrade import DowngradeTracker, DowngradeEvent, DowngradeAction

tracker = DowngradeTracker()

# 记录降级事件
tracker.record(DowngradeEvent(
    gate_id="quality_gate",
    risk_level="high",
    action=DowngradeAction.ABORT,
    reason="审批超时15分钟",
    timeout_minutes=15,
    policy_name="production",
))
tracker.record(DowngradeEvent(
    gate_id="security_gate",
    risk_level="medium",
    action=DowngradeAction.SIMPLIFY,
    reason="审批超时30分钟",
    timeout_minutes=30,
    policy_name="production",
))

stats = tracker.stats()
print(f"降级统计: {stats}")
print(f"瓶颈门禁: {tracker.bottleneck_gates()}")
```

### 预期输出

| 观察项 | 期望值 |
|--------|--------|
| `stats` | 包含总降级次数、各级别分布 |
| `bottleneck_gates()` | 返回降级频率最高的门禁 ID |

---

## Demo 3：回滚快照创建

```python
from harness.rollback import RollbackEngine

engine = RollbackEngine()

# 执行前创建快照——create_snapshot 接收文件路径列表，自行读取磁盘内容
from pathlib import Path
file_paths = ["/tmp/demo_main.py", "/tmp/demo_config.yaml"]
Path("/tmp/demo_main.py").write_text("print('original content')")
Path("/tmp/demo_config.yaml").write_text("version: 1.0")

snapshot_set = engine.create_snapshot(
    execution_id="exec-001",
    node_id="coder-node",
    file_paths=file_paths,
)

print(f"快照集 ID: {snapshot_set.snapshot_id}")
print(f"文件数: {len(snapshot_set.snapshots)}")
for s in snapshot_set.snapshots:
    print(f"  {s.file_path}: hash={s.content_hash[:16]}...")
```

### 预期输出

| 观察项 | 期望值 |
|--------|--------|
| `snapshot_set.snapshot_id` | 自动生成的唯一 ID |
| `len(snapshot_set.snapshots)` | 2（两个文件的快照） |
| `content_hash[:16]` | SHA-256 哈希前16位 |

---

## Demo 4：回滚恢复 + 验证

```python
engine = RollbackEngine()

from pathlib import Path
# 创建快照前先写入原始内容到磁盘
Path("__demo__.py").write_text("print('original')")

# 创建快照
snapshot_set = engine.create_snapshot(
    execution_id="exec-002",
    node_id="coder-node",
    file_paths=["__demo__.py"],
)

# 模拟 Agent 执行修改了文件
Path("__demo__.py").write_text("print('MODIFIED BY AGENT')")

# 回滚到快照版本——restore_snapshot 接收 snapshot_id，从快照恢复原内容
result = engine.restore_snapshot(snapshot_set.snapshot_id)

print(f"回滚成功: {result.success}")
print(f"恢复文件数: {result.files_restored}")

# 验证快照完整性——verify_snapshot 接收 snapshot_id
is_valid = engine.verify_snapshot(snapshot_set.snapshot_id)
print(f"完整性验证: {is_valid}")
```

### 预期输出

| 观察项 | 期望值 |
|--------|--------|
| `result.success` | `True` |
| `result.files_restored` | 1 |
| `engine.verify_snapshot(snapshot_id)` | `True`（SHA-256 哈希链完整） |

---

## Profile YAML 配置示例

```yaml
downgrade:
  policy: production
  high_timeout_minutes: 15
  medium_timeout_minutes: 30
  low_timeout_minutes: 60

rollback:
  enabled: true
  auto_snapshot: true          # 执行前自动创建快照
  verify_on_restore: true      # 回滚后验证 SHA-256 完整性
```

---

## 相关导航

- 📖 架构原理 → [降级引擎](/guide/downgrade) · [回滚引擎](/guide/rollback)
- 🎓 使用方法 → [降级配置](/tutorial/downgrade-rollback)

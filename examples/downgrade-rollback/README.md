# 降级 + 回滚示例

> 门禁超时自动降级（ABORT/SIMPLIFY/SKIP） + 执行失败自动回滚（文件快照恢复）

**定位**：降级和回滚是 harness-cook 的安全网机制——门禁审批超时自动降级不阻塞流程，Agent 执行失败自动回滚到快照版本。

## 运行

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/downgrade-rollback/demo_downgrade_rollback.py
```

## 输出内容

| Demo | 说明 |
|------|------|
| 1. 降级策略 | 按风险级别配置超时阈值和降级动作（high→ABORT, medium→SIMPLIFY, low→SKIP） |
| 2. 降级事件追踪 | 审计降级决策——统计降级率、识别瓶颈门禁 |
| 3. 回滚快照创建 | 执行前自动创建文件快照（SHA-256 hash） |
| 4. 回滚恢复 | 失败后自动恢复到快照版本 |
| 5. 回滚验证 | SHA-256 哈希确认恢复后内容与快照一致 |

## 核心逻辑

```python
from harness.downgrade import DowngradePolicy, DowngradeTracker
from harness.rollback import RollbackEngine

# 降级策略——按风险级别自动降级
policy = DowngradePolicy(
    high_action=DowngradeAction.ABORT,    # 高风险 → 直接中断
    medium_action=DowngradeAction.SIMPLIFY, # 中风险 → 简化处理
    low_action=DowngradeAction.SKIP,       # 低风险 → 跳过审批
)

# 回滚引擎——执行前创建快照，失败后恢复
engine = RollbackEngine()
snapshot_set = engine.create_snapshot(execution_id, node_id, files)
result = engine.restore(snapshot_id, files)
```

## 适用场景

- 门禁审批超时——团队审批人不在，自动降级不阻塞流程
- Agent 修改文件失败——自动回滚到执行前版本，不留损坏文件
- 合规审计——降级决策有完整追踪记录

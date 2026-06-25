# DeerFlow 治理桥接示例

DeerFlow 多智能体框架接入 harness-cook 治理——Gate 门禁注入 + Profile 配置翻译 + 治理检查点嵌入。

## 定位

DeerFlow 是多智能体协作框架。通过 `DeerFlowBridge`，harness-cook 的 Gate 门禁定义可翻译为 DeerFlow 的验证步骤，Profile 配置可翻译为 DeerFlow workflow，在工作流中自动注入治理检查点。

## 运行

```bash
cd examples/deerflow-integration
python demo_deerflow_bridge.py
```

## 输出内容

| 步骤 | 说明 |
|------|------|
| 1. Gate → DeerFlow 验证步骤 | 门禁定义翻译为 DeerFlow validation step（含 interrupt_on_failure 等属性） |
| 2. Profile → DeerFlow workflow | Profile + Gate 翻译为完整的 DeerFlow workflow（含治理检查步骤） |
| 3. execute_with_governance | 在已有 workflow 中注入治理检查点——对比原始步骤数与增强步骤数 |
| 4. 三档门禁对比 | strict/hybrid/loose 三种模式下的 interrupt_on_failure 行为差异 |

## 核心逻辑

```python
from harness.integrations.deerflow_bridge import DeerFlowBridge

bridge = DeerFlowBridge()

# Gate → DeerFlow 验证步骤
validation = bridge.translate_gate_to_validation(gate_definition)

# Profile → DeerFlow workflow
workflow = bridge.translate_profile_to_workflow(profile)

# 在已有 workflow 中注入治理检查点
result = bridge.execute_with_governance(existing_workflow, config={
    "gate_mode": "hybrid",
    "inject_governance": True,
})
```

## 三档门禁在 DeerFlow 中的行为

| 模式 | interrupt_on_failure | 说明 |
|------|---------------------|------|
| strict | `True` | 任何违规 → 中断工作流 |
| hybrid | 部分 `True` | critical/high → 中断，其余仅记录 |
| loose | `False` | 所有违规仅记录，不中断 |

## 适用场景

- 团队使用 DeerFlow 构建多智能体工作流，需要在工作流中注入合规/护栏/门禁检查
- 让 DeerFlow 工作流的每一步产出都经过治理验证

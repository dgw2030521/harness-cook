# LangGraph 治理中间件示例

LangGraph 多步推理框架接入 harness-cook 治理中间件——节点级合规检查 + 门禁阻断 + 状态图治理包裹。

## 定位

LangGraph 是多步推理/状态图工作流框架。通过 `LangGraphMiddleware`，每个 LangGraph 节点可包裹治理检查（输入护栏、输出护栏、合规检查、门禁评审），在工作流执行过程中实时阻断违规。

## 运行

```bash
cd examples/langgraph-integration
pip install harness-cook[langgraph]
python demo_langgraph_governance.py
```

**前置**：`pip install harness-cook[langgraph]` 安装 LangGraph SDK。未安装时步骤 3（build_governance_graph）会跳过。

## 输出内容

| 步骤 | 说明 |
|------|------|
| 1. LangGraphGovernanceNode | 直接执行治理节点——输入护栏 + 输出护栏 + 合规检查 + 门禁评审 |
| 2. wrap_node_with_governance | 包裹已有节点函数，自动在执行前后插入治理检查 |
| 3. build_governance_graph | 构建带治理检查的完整 StateGraph（需要 langgraph 包） |
| 4. 三档门禁对比 | strict/hybrid/loose 下的 gate_decision 和 blocked 行为差异 |

## 核心逻辑

```python
from harness.integrations.langgraph_middleware import (
    LangGraphGovernanceNode,
    wrap_node_with_governance,
)

# 方式 1：直接使用治理节点
governance_node = LangGraphGovernanceNode(config={
    "check_input_guardrails": True,
    "check_output_guardrails": True,
    "check_compliance": True,
    "gate_mode": "hybrid",
})
result = governance_node.execute(state)

# 方式 2：包裹已有节点
wrapped = wrap_node_with_governance(my_node, config={"gate_mode": "hybrid"})
wrapped_result = wrapped(state)
```

## 与 DeerFlow Bridge 的区别

| 维度 | DeerFlow Bridge | LangGraph Middleware |
|------|----------------|---------------------|
| 框架 | DeerFlow（多智能体协作） | LangGraph（多步推理/状态图） |
| 治理方式 | Gate → workflow 验证步骤 | 节点级包裹 + 状态图注入 |
| 侵入性 | 配置翻译（低侵入） | 函数包裹（中等侵入） |
| 前置依赖 | 无额外 SDK | 需要 langgraph 包 |

## 适用场景

- 团队使用 LangGraph 构建多步推理工作流，需要在每个节点前后插入治理检查
- 让 LangGraph 状态图的每一步产出都经过护栏/合规/门禁验证
- 需要实时阻断——推理过程中检测到违规立即中断

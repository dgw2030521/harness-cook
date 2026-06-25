# hermes-bridge 示例

Hermes Agent + harness-cook 集成：通过 MCP Server 让 Hermes 的 Agent 接入 Harness 管控。

## 运行

```bash
# 确保 harness-cook MCP Server 已启动（hermes mcp test harness-cook）
cd examples/hermes-bridge
pip install -r requirements.txt
python hermes_bridge.py
```

## 说明

本示例演示:
- Hermes delegate_task → Harness Agent 的桥接
- MCP Server 远程调用（harness_run、harness_check 等）
- HarnessClient 知识注入——Agent 自动获取项目知识
- 审计溯源——所有 Agent 行为有迹可查
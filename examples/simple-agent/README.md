# simple-agent 示例

最简单的 harness-cook 使用：一个 Agent，一个约束，一个任务。

## 运行

```bash
cd examples/simple-agent
pip install -r requirements.txt
python simple_agent.py
```

## 说明

本示例演示:
- `@simple_agent` 极简装饰器——只需 name 即可接入 Harness
- 约束自动生效——`no_destructive=True` 会阻止破坏性操作
- `TaskResult` 返回格式——Harness 统一的产出物格式
- `AgentClient` 查询——查看 Agent 信息摘要
# multi-agent 示例

多 Agent 协作：Coder 写代码 → Reviewer 检查 → Tester 测试。

## 运行

```bash
cd examples/multi-agent
pip install -r requirements.txt
python multi_agent.py
```

## 说明

本示例演示:
- 多个 `@harness_agent` 协作——不同 Agent 有不同的约束和能力
- DAGWorkflow 编排——定义 Agent 之间的依赖和执行顺序
- HarnessClient 一站式——编排+合规+审计统一入口
- 合规扫描——自动检查产出物是否违反安全/隐私规则
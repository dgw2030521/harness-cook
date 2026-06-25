# Pipeline 编排示例

> 六步流水线编排 + MCP 编码 Pipeline——Analyst→Coder→Validator→Committer，含门禁强制执行

**定位**：Pipeline 示例展示两种编排方式——Python API（MultiAgentOrchestrator）和 MCP 工具（harness_pipeline_run），前者可直接运行脚本，后者在 IDE 中通过 MCP 工具调用。

## 运行

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/pipeline/demo_pipeline.py
```

## 输出内容

| Demo | 说明 |
|------|------|
| 1. 六步流水线定义 | PIPELINE_STEPS 角色分配——Analyst/Planner/Coder/Reviewer/Validator/Committer |
| 2. Pipeline 配置 | 门禁模式（strict/hybrid/loose）+ 步骤跳过 + 重试策略 |
| 3. DAG 工作流构建 | 流水线转 DAG + reviewer 失败→coder 重试条件分支 |
| 4. MCP Pipeline 工具 | harness_pipeline_run——在 IDE 中直接触发编码流水线 |
| 5. Pipeline 结果结构 | StepResult + OrchestrationResult 数据结构说明 |

## 核心逻辑

```python
from harness.experimental import MultiAgentOrchestrator, PipelineConfig

# Python API 方式——直接编排
engine = DAGEngine()
orchestrator = MultiAgentOrchestrator(engine)
result = orchestrator.execute("修复 XSS 漏洞", PipelineConfig(
    gate_mode=GateMode.HYBRID,
    skip_steps=["plan", "review"],
))

# MCP 工具方式——在 IDE 中调用
# harness_pipeline_run(task="修复XSS漏洞", gate_mode="hybrid")
```

## 适用场景

- 自动编码流水线——从需求分析到代码提交的全流程自动化
- 门禁强制执行——每步都经过合规检查，失败自动重试或暂停
- 条件分支——reviewer 失败自动回到 coder 重试，不浪费 token
- IDE 集成——通过 MCP 工具在 Claude Code / Cursor / Copilot CLI 中直接触发

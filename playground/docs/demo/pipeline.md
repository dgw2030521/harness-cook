# Pipeline 编排 Demo

> 六步流水线编排 + MCP 编码 Pipeline——Analyst→Planner→Coder→Reviewer→Validator→Committer，含门禁强制执行

> ⚠️ 本 Demo 展示的是 `harness.experimental.PIPELINE_STEPS` 六步实验性流水线（含 planner/reviewer）。标准默认流水线为四步（analyst/coder/validator/committer），见 [Pipeline 教程](/tutorial/pipeline)。

**定位**：Pipeline 示例展示两种编排方式——Python API（MultiAgentOrchestrator）和 MCP 工具（harness_pipeline_run），前者可直接运行脚本，后者在 IDE 中通过 MCP 工具调用。

完整可运行脚本见项目 `examples/pipeline/` 目录（`demo_pipeline.py`）。

---

## Demo 1：六步流水线定义

```python
from harness.experimental import PIPELINE_STEPS

# 六步流水线角色分配
for agent_type, step_name, description in PIPELINE_STEPS:
    print(f"{agent_type.value:12s} → {step_name:10s} → {description}")
```

### 流水线步骤

| 步序 | Agent 类型 | 步骤名 | 描述 |
|------|-----------|--------|------|
| 1 | analyst | analyze | 分析需求和影响评估 |
| 2 | planner | plan | 任务分解和策略制定 |
| 3 | coder | implement | 代码生成和修复实现 |
| 4 | reviewer | review | 代码审查和质量检查 |
| 5 | validator | validate | 测试验证和合规检查 |
| 6 | committer | commit | 变更提交和发布操作 |

---

## Demo 2：Pipeline 配置

```python
from harness.experimental import PipelineConfig
from harness.gates import GateMode

# 默认配置
default_config = PipelineConfig()
print(f"跳过步骤: {default_config.skip_steps}")
print(f"最大重试: {default_config.max_retries}")
print(f"门禁模式: {default_config.gate_mode}")

# 自定义配置——跳过 planner 和 reviewer
custom_config = PipelineConfig(
    skip_steps=["plan", "review"],
    max_retries=3,
    gate_mode=GateMode.STRICT,
    task_description="修复安全漏洞",
)
```

### 配置选项

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `skip_steps` | 跳过的步骤列表 | `[]`（全部执行） |
| `max_retries` | 门禁失败最大重试 | 2 |
| `gate_mode` | 门禁严格度 | `hybrid` |
| `task_description` | 任务描述 | 空 |

---

## Demo 3：DAG 工作流构建

```python
from harness.experimental import MultiAgentOrchestrator, PipelineConfig
from harness.engine import DAGEngine

engine = DAGEngine()
orchestrator = MultiAgentOrchestrator(engine)

# 构建工作流（不执行）
config = PipelineConfig(
    task_description="修复 XSS 漏洞",
    gate_mode=GateMode.HYBRID,
)
workflow = orchestrator.build_workflow(config)

print(f"节点数: {len(workflow.nodes)}")
print(f"边数: {len(workflow.edges)}")
print(f"入口: {workflow.entry_node}")
```

### DAG 特性

| 特性 | 说明 |
|------|------|
| 条件分支 | reviewer 失败 → coder 重试（闭环重试机制） |
| 门禁节点 | implement/review/validate 三步有门禁 |
| 串行依赖 | 每步依赖前一步输出 |

---

## Demo 4：MCP 工具调用（IDE 集成）

```python
# MCP 工具: harness_pipeline_run
# 参数:
#   task: "修复 XSS 漏洞"
#   gate_mode: "hybrid"  (strict/hybrid/loose)
#   agents: ["analyst", "coder", "validator", "committer"]
#   max_retries: 2
#   working_directory: "."
```

三档门禁模式见 [门禁层原理](/guide/gate-layer#三档门禁模式)

### MCP 工具在 IDE 中的使用方式

| IDE | 调用方式 |
|-----|---------|
| Claude Code | `harness_pipeline_run(task='修复XSS漏洞', gate_mode='hybrid')` |
| Cursor | MCP 工具面板 → `harness_pipeline_run` |
| Copilot CLI | `harness_pipeline_run --task "修复XSS漏洞" --gate-mode hybrid` |

---

## Demo 5：Pipeline 结果结构

```python
# StepResult —— 每步执行结果
step = StepResult(
    agent="coder",
    status="completed",
    output="代码修改完成",
    duration_ms=3000,
    gate_passed=True,
    retries=0,
)

# OrchestrationResult —— 整体流水线结果
result = OrchestrationResult(
    workflow_id="pipeline-1",
    pipeline_steps=6,
    completed_steps=5,
    failed_steps=0,
    success=True,
    last_artifacts=[...],  # 最后完成的 Agent 产出
)
```

### 结果字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `workflow_id` | str | 工作流 ID |
| `completed_steps` | int | 完成步骤数 |
| `failed_steps` | int | 失败步骤数 |
| `success` | bool | 整体是否成功 |
| `last_artifacts` | list | 最后完成的 Agent 产出 |

---

## Profile YAML 配置示例

```yaml
pipeline:
  default_agents: [analyst, coder, validator, committer]
  gate_mode: hybrid
  max_retries: 2
  skip_steps: []                # 不跳过任何步骤
```

---

## 相关导航

- 📖 架构原理 → [流水线编排](/tutorial/pipeline)
- 🎓 使用方法 → [Pipeline 使用](/tutorial/pipeline)

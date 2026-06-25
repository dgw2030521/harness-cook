# Agents 模块

harness-cook 的 **Agents 包** (`packages/agents`) 是执行层——方向盘和引擎。它实现了 ReAct 推理循环、工具调用、四角色编码流水线和带 gate 检查的 Orchestrator 调度器。

> Harness 是刹车（约束层），Agents 是方向盘（执行层）。两者配合才能让 AI 真正落地。

## 架构概览

```
harness_agents/
  ├── tool_executor.py   工具调用引擎（6 个内置工具 + 动态注册）
  ├── react_runtime.py   ReAct 推理循环（think → act → observe → think）
  ├── coding_agents.py   四角色编码 Agent 定义（Analyst / Coder / Validator / Committer）
  └── orchestrator.py    流水线调度器（带 gate 检查 + 重试 + 合规扫描）
```

## 核心组件

### ToolExecutor

独立模块，不依赖 harness core，纯 stdlib 实现。

6 个内置工具：
- `read_file` — 读取文件内容
- `write_file` — 写入文件内容
- `search_code` — 代码搜索（行级匹配）
- `run_command` — 执行 shell 命令
- `list_files` — 目录文件列表
- `edit_file` — 定点编辑（old_string → new_string）

动态注册：`executor.register_tool(name, handler, schema)` 添加自定义工具。

### AgentRuntime (ReAct Loop)

ReAct = Reasoning + Acting。循环过程：

1. **Think** — Agent 分析当前状态，决定下一步
2. **Act** — 选择并调用一个工具
3. **Observe** — 获取工具返回结果
4. 重复直到输出 `Final Answer:` 或达到 max_rounds

关键配置：`max_rounds`, `temperature`, `allowed_tools`, `system_prompt`。

### Coding Agents 四角色

Analyst → Coder → Validator → Committer 流水线：

| 角色 | 职责 | 可用工具 |
|------|------|----------|
| **Analyst** | 分析任务、定位影响范围 | read_file, search_code, list_files |
| **Coder** | 编写代码修改 | write_file, edit_file, read_file, run_command |
| **Validator** | 验证修改是否正确 | run_command, read_file, search_code |
| **Committer** | 生成提交信息、整理变更 | run_command (git) |

### Orchestrator

流水线调度器，带 gate 检查机制：

1. 按 PipelineConfig.agents 序列顺序执行每个 Agent
2. 每个 Agent 输出经过 gate 检查
3. Gate 失败时自动重试（max_retries 次）
4. 不可恢复的 gate 失败 → 流水线中止
5. 可选合规扫描（harness SDK ComplianceEngine）

Gate 模式：
- `strict` — 严格：gate 失败必须人工介入
- `hybrid` — 混合：失败可自动重试（默认）
- `loose` — 松散：所有 gate 自动放行

```python
from harness_agents.orchestrator import Orchestrator, PipelineConfig

config = PipelineConfig(
    task="Fix the login timeout bug",
    working_directory="/path/to/project",
    gate_mode="hybrid",
    max_retries=2,
)
orch = Orchestrator(config)
result = orch.run()
```

## 与 Harness Core 的关系

Agents 包是**独立执行层**，通过条件导入连接 Harness Core：

- 无 Harness SDK → Agents 可独立运行（fallback 内置 gate）
- 有 Harness SDK → 自动接入合规扫描、DAG 引擎、审计存储 + 外部引擎集成

这是「刹车 + 方向盘」的设计核心：**Agents 可以脱离 Harness 独立跑，但接入 Harness 后获得完整的约束保障 + 外部引擎能力**。

## MCP Server 工具

harness-cook MCP Server 新增 3 个 agents 相关工具：

| 工具名 | 功能 |
|--------|------|
| `harness_pipeline_run` | 启动编码流水线（Analyst→Coder→Validator→Committer） |
| `harness_pipeline_status` | 查询流水线执行状态 |
| `harness_agent_list` | 列出可用 Agent 角色及工具配置 |

通过 `hermes mcp call harness-cook harness_pipeline_run '{"task": "...", "gate_mode": "hybrid"}'` 调用。

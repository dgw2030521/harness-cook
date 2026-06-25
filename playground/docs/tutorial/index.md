# 教程简介

本教程系列通过可运行的代码示例，手把手带你掌握 harness-cook 的核心功能。

## 前置条件

- Python 3.9+ （`python3` 可执行）
- harness-cook 源码（`packages/core` 在项目路径中）
- 基础 Python 知识（dataclass、enum、装饰器）

## 教程概览

| # | 教程 | 学到什么 |
|---|------|----------|
| 1 | [基础用法](./basic-usage) | Agent 定义、注册、装饰器接入 |
| 2 | [护栏使用](./guardrails-usage) | 输入/输出护栏、PII 检测、敏感信息脱敏、自定义规则 |
| 3 | [合规扫描](./compliance-scan) | 规则包加载、代码扫描、违规处理、外部引擎集成 |
| 4 | [审计使用](./audit-usage) | 审计日志查询、追踪导出、OTel 集成 |
| 5 | [门禁审批](./gate-approval) | 门禁模式配置、检查函数、重试策略、通知推送 |
| 6 | [DAG 工作流](./dag-workflow) | 节点/边定义、拓扑排序、执行与结果跟踪 |
| 7 | [Pipeline 编排](./pipeline) | 四步流水线、gate_mode 三档、自定义 Agent 序列、重试策略 |
| 8 | [降级与回滚](./downgrade-rollback) | DowngradePolicy 配置、RollbackEngine 快照/恢复、DAG 联动 |
| 9 | [Adapter 部署](./adapter-deployment) | 5 个适配器对比、有-hooks vs 无-hooks 治理路径、一键部署、优先级链 |
| 10 | [MCP 集成](./mcp-integration) | MCP Server 启动、JSON-RPC 交互、25 个工具调用、引擎路由 |
| 11 | [AI 法律风险扫描](./legal-scan) | Legal 规则包、中文法规合规、门禁集成、MCP 调用 |
| 12 | [Superpowers Skill Bridge](./superpowers-skill-bridge) | superpowers 自动发现、语义映射、namespace 防碰撞、MCP 集成 |

每个教程包含完整可运行代码。建议从「基础用法」开始，按序递进。

## 运行方式

```bash
cd harness-cook/packages/core
PYTHONPATH=. python3 your_script.py
```

或在 playground 目录直接运行 demo：

```bash
python3 playground/demo_basic.py
```

## 可选引擎安装

如需使用外部引擎，安装对应的可选依赖：

```bash
pip install harness-cook[guardrails]     # Guardrails AI 护栏引擎
pip install harness-cook[sonarqube]      # SonarQube 合规引擎
pip install harness-cook[integrations]   # 所有外部引擎
```

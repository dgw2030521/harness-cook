# harness mcp

harness-cook 的 MCP（Model Context Protocol）Server，将治理能力封装为标准工具注入 Agent 运行环境。完整介绍见根目录 [README](../../README.md)。

## 能力

通过 MCP 协议向 Agent 暴露治理工具，覆盖：

- **护栏** — input/output guardrails 检查、PII 过滤
- **合规** — 合规扫描、规则包加载、架构规则执行
- **审计** — 审计日志查询、审计链校验
- **知识** — 知识库查询与语义检索
- **门禁** — gate 审批创建与决策
- **Pipeline** — 编排任务执行与状态查询

## 运行

```bash
# 作为 MCP Server 启动（Agent 平台通过配置接入）
python packages/mcp/harness_mcp_server.py
```

`harness activate` 会自动将 MCP Server 配置写入目标 Agent 的配置文件。

## 适配器差异

- 有原生 hooks 的平台（claude-code / copilot-cli）：hooks + MCP 双通道
- 无 hooks 的平台（hermes / cursor / openai）：治理完全经 MCP Server / function calling 承载


# MCP 集成

本教程展示如何启动 harness-cook MCP Server、发送 JSON-RPC 2.0 请求、调用 25 个工具覆盖五大领域。

## Step 1: MCP Server 概述

harness-cook MCP Server 基于 JSON-RPC 2.0 over stdio 协议实现，使用官方 MCP Python SDK。

协议版本：`2024-11-05`，Server 名称：`harness-cook`。

25 个可用工具，覆盖五大领域。高频工具简介：

| 工具 | 领域 | 必需参数 | 一句话说明 |
|------|------|----------|-----------|
| `harness_check` | 合规检查 | `path` | 对指定路径执行合规扫描 |
| `harness_guardrails_check` | 合规检查 | `content` | 输入/输出护栏，检测 PII 和安全风险 |
| `harness_pipeline_run` | 工作流 | `task` | 启动 analyst→coder→validator→committer 四步流水线 |
| `harness_bridge_deploy` | 配置 | — | 将 Profile 部署到 Agent 平台 |
| `harness_audit` | 审计追踪 | `query` | 搜索审计日志 |

完整 25 工具列表见 [MCP 工具全量 Demo](/demo/mcp-full)。

## Step 2: 创建 MCP Server 实例

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "packages/mcp"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "packages/core"))

from harness_mcp_server import HarnessMCPServer

server = HarnessMCPServer()
```

Server 内部自动创建 EventBus、AgentRegistry、DAGEngine、ComplianceEngine、GateEngine 等核心组件。

## Step 3: 发送 initialize 请求

MCP 协议要求先初始化再调用工具：

```python
init_request = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "clientInfo": {"name": "my-client", "version": "1.0.0"},
    },
}

response = server.handle_request(init_request)
print(response["result"]["serverInfo"])
# → {"name": "harness-cook", "version": "0.1.0"}
print(response["result"]["protocolVersion"])
# → "2024-11-05"
```

初始化成功后，Server 状态变为 `initialized=True`。

## Step 4: 查看可用工具（25 个）

```python
tools_request = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
}

response = server.handle_request(tools_request)
print(f"工具总数: {len(response['result']['tools'])}")  # → 25
for tool in response["result"]["tools"]:
    domain = {
        "harness_check": "合规", "harness_guardrails_check": "合规", "harness_rule_import": "合规",
        "harness_audit": "审计", "harness_trace_export": "审计", "harness_status": "审计",
        "harness_plan": "工作流", "harness_run": "工作流",
        "harness_pipeline_run": "工作流", "harness_pipeline_status": "工作流",
        "harness_gate_create": "门禁",
        "harness_register": "注册", "harness_agent_list": "注册",
        "harness_profile_list": "配置", "harness_profile_load": "配置",
        "harness_skill_list": "配置", "harness_skill_register": "配置", "harness_bridge_deploy": "配置",
    }.get(tool['name'], "其他")
    print(f"  [{domain}] {tool['name']}: {tool['description'][:40]}...")
```

## Step 5: 调用 harness_check（合规扫描）

```python
check_request = {
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
        "name": "harness_check",
        "arguments": {
            "path": "config.py",
            "pack_names": ["security", "data"],
        },
    },
}

response = server.handle_request(check_request)
for result in response["result"]["content"]:
    if "违规" in result.get("text", ""):
        print(result["text"])
```

`pack_names` 可选，不指定时加载所有规则包。`engine` 参数支持 `builtin/sonarqube/opa/archunit/dep_cruiser` 引擎路由。

## Step 6: 调用 harness_guardrails_check（护栏检查）

```python
guardrails_request = {
    "jsonrpc": "2.0",
    "id": 4,
    "method": "tools/call",
    "params": {
        "name": "harness_guardrails_check",
        "arguments": {
            "content": "用户邮箱是 zhangsan@example.com，手机号 13812345678",
            "direction": "input",
        },
    },
}

response = server.handle_request(guardrails_request)
# 返回脱敏后的内容和检测结果
print(response["result"]["content"][0]["text"])
```

`direction` 参数：`input`（输入护栏）或 `output`（输出护栏）。`engine` 参数支持 `builtin` 或 `guardrails-ai`。

## Step 7: 调用 harness_pipeline_run（Pipeline 编排）

```python
pipeline_request = {
    "jsonrpc": "2.0",
    "id": 5,
    "method": "tools/call",
    "params": {
        "name": "harness_pipeline_run",
        "arguments": {
            "task": "修复登录页面的 XSS 安全漏洞",
            "gate_mode": "hybrid",
        },
    },
}

response = server.handle_request(pipeline_request)
print(f"Pipeline 任务: {response['result']['content'][0]['text'][:60]}...")
```

`agents` 参数可选——默认 analyst→coder→validator→committer 四步流水线。`gate_mode` 支持 `strict/hybrid/loose`。

## Step 8: 调用 harness_bridge_deploy（配置部署）

```python
bridge_request = {
    "jsonrpc": "2.0",
    "id": 6,
    "method": "tools/call",
    "params": {
        "name": "harness_bridge_deploy",
        "arguments": {
            "adapter": "claude-code",
        },
    },
}

response = server.handle_request(bridge_request)
print(f"部署结果: {response['result']['content'][0]['text'][:60]}...")
```

`adapter` 支持 `claude-code/copilot-cli/hermes/cursor/openai`。`profile_name` 可选——未指定时自动解析活跃 Profile。

## Step 9: stdio 模式部署

MCP Server 的标准部署方式是通过 stdio 通信：

```json
{
  "mcpServers": {
    "harness-cook": {
      "command": "python3",
      "args": ["-m", "harness_mcp_server"],
      "cwd": "/path/to/harness-cook/packages/mcp"
    }
  }
}
```

::: tip
harness-cook MCP Server 零外部依赖——只需要 Python 3.9+ 标准库即可运行。YAML 支持可选（安装 pyyaml 后解锁工作流解析功能）。完整 25 工具调用演示见 [MCP 全量 Demo](/demo/mcp-full)。
:::

下一步 → [门禁审批](./gate-approval) · [DAG 工作流](./dag-workflow)

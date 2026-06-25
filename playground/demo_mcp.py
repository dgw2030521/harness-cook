#!/usr/bin/env python3
"""
harness-cook MCP Server Demo

本demo展示 HarnessMCPServer 的程序化使用方式（非stdio模式）：
  1. 创建 HarnessMCPServer 实例
  2. 发送 initialize 请求
  3. 发送 tools/list 请求
  4. 发送 harness_check 合规检查
  5. 发送 harness_guardrails_check 护栏检查

运行方式:
  python playground/demo_mcp.py

无需任何外部依赖（core模块），MCP Server内部可选依赖PyYAML用于解析workflow YAML。
"""

import sys
import os
import json

# ── 设置 sys.path，确保能找到 harness 和 harness_mcp_server ──────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CORE_DIR = os.path.join(_PROJECT_ROOT, "packages", "core")
_MCP_DIR = os.path.join(_PROJECT_ROOT, "packages", "mcp")
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)
if _MCP_DIR not in sys.path:
    sys.path.insert(0, _MCP_DIR)

# ── 导入 MCP Server ──────────────────────────────────────────────
from harness_mcp_server import HarnessMCPServer, TOOL_DEFINITIONS


# ═══════════════════════════════════════════════════════════════════
#  辅助函数：格式化打印
# ═══════════════════════════════════════════════════════════════════

def print_header(title: str) -> None:
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_sub(title: str) -> None:
    print()
    print(f"── {title} ──")


def print_json(label: str, data: dict) -> None:
    """格式化打印 JSON 数据"""
    print(f"  {label}:")
    print(json.dumps(data, indent=2, ensure_ascii=False))


def send_request(server: HarnessMCPServer, request: dict) -> dict:
    """发送 JSON-RPC 请求并打印响应"""
    method = request.get("method", "unknown")
    print(f"\n  → 发送请求: method={method}")

    if "params" in request:
        params_preview = json.dumps(request.get("params", {}), ensure_ascii=False)
        # 截断太长的参数
        if len(params_preview) > 200:
            params_preview = params_preview[:200] + "...(截断)"
        print(f"    params: {params_preview}")

    response = server.handle_request(request)

    # 检查是否是错误响应
    if "error" in response:
        print(f"\n  ← 错误响应:")
        print_json("error", response["error"])
    else:
        print(f"\n  ← 成功响应:")
        # 截断太长的结果
        result_str = json.dumps(response.get("result", {}), ensure_ascii=False)
        if len(result_str) > 500:
            result_preview = json.dumps(response.get("result", {}), ensure_ascii=False)
            # 美化截断
            preview = result_preview[:500] + "...(截断)"
            print(f"    {preview}")
        else:
            print_json("result", response.get("result", {}))

    return response


# ═══════════════════════════════════════════════════════════════════
#  Step 1: 创建 HarnessMCPServer
# ═══════════════════════════════════════════════════════════════════

print_header("Step 1: 创建 HarnessMCPServer")

server = HarnessMCPServer()
print("  HarnessMCPServer 实例创建成功!")
print(f"  Server名称: {server.SERVER_NAME}")
print(f"  Server版本: {server.SERVER_VERSION}")
print(f"  协议版本: {server.PROTOCOL_VERSION}")
print(f"  已初始化: {server._initialized}")


# ═══════════════════════════════════════════════════════════════════
#  Step 2: 发送 initialize 请求
# ═══════════════════════════════════════════════════════════════════

print_header("Step 2: 发送 initialize 请求")

init_request = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "clientInfo": {
            "name": "demo-client",
            "version": "1.0.0",
        },
    },
}

init_response = send_request(server, init_request)
print(f"\n  ✅ Server 已初始化: {server._initialized}")


# ═══════════════════════════════════════════════════════════════════
#  Step 3: 发送 tools/list 请求
# ═══════════════════════════════════════════════════════════════════

print_header("Step 3: 发送 tools/list 请求")

list_request = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
}

list_response = send_request(server, list_request)

tools = list_response.get("result", {}).get("tools", [])
print_sub("可用工具列表")
for tool in tools:
    print(f"  📌 {tool['name']}")
    print(f"     描述: {tool['description']}")
    required = tool.get('inputSchema', {}).get('required', [])
    if required:
        print(f"     必需参数: {required}")
    print()


# ═══════════════════════════════════════════════════════════════════
#  Step 4: 发送 harness_check 合规检查
# ═══════════════════════════════════════════════════════════════════

print_header("Step 4: 发送 harness_check 合规检查")

# ── 检查一段含有安全风险的代码 ────────────────────────────────
print_sub("检查含硬编码密钥的代码")

check_request_1 = {
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
        "name": "harness_check",
        "arguments": {
            "path": "config/settings.py",
            "content": '''
# 不安全的配置文件示例
API_KEY = "sk-abc123def456ghi789jkl012mno345pqr678stu901vwx234yz"
password = "my_password_123456"
db_url = "http://api.internal.company.com/login?token=secret"
user_email = "admin@company.com"
eval("calculate_result(data)")
''',
            "pack_names": ["security", "privacy"],
        },
    },
}

check_response_1 = send_request(server, check_request_1)

# 解析并显示合规检查摘要
check_result_1 = check_response_1.get("result", {})
content_list = check_result_1.get("content", [])
if content_list:
    check_data = json.loads(content_list[0].get("text", "{}"))
    print_sub("合规检查摘要")
    print(f"  扫描路径: {check_data.get('path')}")
    print(f"  使用规则包: {check_data.get('pack_names')}")
    print(f"  总规则数: {check_data.get('total_rules')}")
    print(f"  通过: {check_data.get('passed')}")
    print(f"  违规: {check_data.get('failed')}")

    if check_data.get("failed", 0) > 0:
        print_sub("违规详情")
        for detail in check_data.get("details", []):
            if not detail.get("passed"):
                print(f"  ❌ 规则: {detail['rule_id']}")
                print(f"     严重性: {detail['severity']}")
                print(f"     发现: {detail['findings']}")
                if detail.get('remediation'):
                    print(f"     修复: {detail['remediation']}")

# ── 检查一段安全的代码 ──────────────────────────────────────
print_sub("检查安全代码（预期全部通过）")

check_request_2 = {
    "jsonrpc": "2.0",
    "id": 4,
    "method": "tools/call",
    "params": {
        "name": "harness_check",
        "arguments": {
            "path": "src/main.py",
            "content": "import os\n\ndef get_config():\n    return os.environ.get('API_KEY')\n",
            "pack_names": ["security"],
        },
    },
}

check_response_2 = send_request(server, check_request_2)


# ═══════════════════════════════════════════════════════════════════
#  Step 5: 发送 harness_guardrails_check 护栏检查
# ═══════════════════════════════════════════════════════════════════

print_header("Step 5: 发送 harness_guardrails_check 护栏检查")

# ── 输入方向：检查含有PII的用户输入 ──────────────────────────────
print_sub("输入方向: 检查含PII的内容")

guardrails_input_request = {
    "jsonrpc": "2.0",
    "id": 5,
    "method": "tools/call",
    "params": {
        "name": "harness_guardrails_check",
        "arguments": {
            "content": "请帮我分析这个用户的数据: 邮箱zhangsan@example.com, 手机13812345678, SSN 123-45-6789",
            "direction": "input",
        },
    },
}

guardrails_input_response = send_request(server, guardrails_input_request)

# 解析护栏检查结果
gi_content = guardrails_input_response.get("result", {}).get("content", [])
if gi_content:
    gi_data = json.loads(gi_content[0].get("text", "{}"))
    print_sub("输入护栏检查结果")
    print(f"  动作: {gi_data.get('action')}")
    print(f"  是否阻止: {gi_data.get('blocked')}")
    print(f"  警告: {gi_data.get('warnings')}")
    print(f"  违规: {gi_data.get('violations')}")
    print(f"  脱敏数: {len(gi_data.get('redactions', []))}")
    if gi_data.get('redactions'):
        print("  脱敏详情:")
        for r in gi_data['redactions']:
            print(f"    类型={r['type']}, 原文={r['original']}, 替换={r['redacted']}")

    # 显示脱敏后的内容（截断）
    processed = gi_data.get('processed_content', '')
    if len(processed) > 150:
        processed = processed[:150] + "...(截断)"
    print(f"  脱敏后内容: {processed}")

# ── 输出方向：检查含有unsafe code的Agent输出 ────────────────────
print_sub("输出方向: 检查含unsafe code的内容")

guardrails_output_request = {
    "jsonrpc": "2.0",
    "id": 6,
    "method": "tools/call",
    "params": {
        "name": "harness_guardrails_check",
        "arguments": {
            "content": "以下是生成的代码:\nimport os\nos.system('rm -rf /tmp/cache')\npassword = 'admin_password_123'",
            "direction": "output",
        },
    },
}

guardrails_output_response = send_request(server, guardrails_output_request)

go_content = guardrails_output_response.get("result", {}).get("content", [])
if go_content:
    go_data = json.loads(go_content[0].get("text", "{}"))
    print_sub("输出护栏检查结果")
    print(f"  动作: {go_data.get('action')}")
    print(f"  是否阻止: {go_data.get('blocked')}")
    print(f"  警告: {go_data.get('warnings')}")
    print(f"  违规: {go_data.get('violations')}")
    print(f"  脱敏数: {len(go_data.get('redactions', []))}")


# ═══════════════════════════════════════════════════════════════════
#  附加: 发送 harness_status 查看系统状态
# ═══════════════════════════════════════════════════════════════════

print_header("附加: harness_status 系统状态")

status_request = {
    "jsonrpc": "2.0",
    "id": 7,
    "method": "tools/call",
    "params": {
        "name": "harness_status",
        "arguments": {},
    },
}

status_response = send_request(server, status_request)

# 解析并显示状态摘要
st_content = status_response.get("result", {}).get("content", [])
if st_content:
    st_data = json.loads(st_content[0].get("text", "{}"))
    print_sub("系统状态摘要")

    reg = st_data.get("registry", {})
    print(f"  Registry: {reg.get('total_agents')} 个Agent, {reg.get('active_agents')} 个活跃")

    comp = st_data.get("compliance", {})
    print(f"  Compliance: {comp.get('loaded_packs')} 个规则包, {comp.get('total_rules')} 条规则")

    engine = st_data.get("engine", {})
    print(f"  Engine: {engine.get('total_executions')} 次执行")

    srv = st_data.get("server", {})
    print(f"  Server: {srv.get('name')} v{srv.get('version')}, 已初始化={srv.get('initialized')}")


# ═══════════════════════════════════════════════════════════════════
#  总结
# ═══════════════════════════════════════════════════════════════════

print_header("Demo 总结")
print(f"""
  harness-cook MCP Server Demo 完成！

  展示的 MCP 操作:
    ✅ initialize      — 初始化 MCP 连接
    ✅ tools/list       — 列出 8 个可用工具
    ✅ harness_check    — 合规扫描（安全+隐私规则包）
    ✅ harness_guardrails_check — 输入/输出护栏检查
    ✅ harness_status   — 查看系统聚合状态

  MCP Server 使用方式:
    1. 程序化调用: server.handle_request(request_dict)
       → 适合测试、嵌入其他应用
    2. Stdio模式:   server.run()
       → 适合作为 MCP Client（如 Claude Desktop）的子进程
       → stdin/stdout 逐行 JSON-RPC 通信

  下一步:
    → 查看 playground/demo_workflow.yaml 了解 YAML 工作流定义
    → 运行 playground/demo_basic.py 了解 Python API
""")
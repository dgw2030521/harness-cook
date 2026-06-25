"""
MCP 全量工具 Demo

展示 harness-cook MCP Server 的 18 个工具在 IDE 中的调用方式。
本脚本不需要实际运行 MCP server，直接调用 HarnessMCPServer 的 _tool_* 方法，
模拟 MCP 工具调用的参数与返回值。

运行方式:
  cd packages/core
  PYTHONPATH=. python3 ../../examples/mcp-full/demo_mcp_full.py

Demo 分组:
  1. 合规检查工具组 — harness_check + harness_guardrails_check + harness_rule_import
  2. 审计追踪工具组 — harness_audit + harness_trace_export + harness_status
  3. 工作流编排工具组 — harness_plan + harness_run + harness_pipeline_run + harness_pipeline_status
  4. 门禁管理工具组 — harness_gate_create
  5. 注册/配置工具组 — harness_register + harness_agent_list + harness_profile_list
                         + harness_profile_load + harness_skill_list + harness_skill_register
                         + harness_bridge_deploy
"""

import json
import sys
import os
import tempfile
import shutil

# ── 确保 harness 包可导入 ──────────────────────────────────────────
# 运行方式: cd packages/core; PYTHONPATH=. python3 ../../examples/mcp-full/demo_mcp_full.py
# PYTHONPATH=packages/core 提供 harness 核心包
# 需额外加入 packages/mcp 提供 harness_mcp_server

_mcp_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "packages", "mcp"))
_core_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "packages", "core"))
sys.path.insert(0, _mcp_dir)
sys.path.insert(0, _core_dir)

from harness_mcp_server import HarnessMCPServer


def _print_section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def _print_demo(demo_name: str, tool_name: str, args: dict, result: dict) -> None:
    """格式化打印一次 MCP 工具调用"""
    print(f"\n  ── {demo_name} ──")
    print(f"  MCP 工具: {tool_name}")
    print(f"  参数:")
    for k, v in args.items():
        val_str = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
        print(f"    {k}: {val_str}")
    print(f"  预期返回:")
    # 精简打印：只显示关键字段
    for k, v in result.items():
        if isinstance(v, list) and len(v) > 3:
            print(f"    {k}: [{len(v)} 项] — 前3项: {json.dumps(v[:3], ensure_ascii=False)}")
        elif isinstance(v, dict) and len(str(v)) > 120:
            print(f"    {k}: {{...}} — 共 {len(v)} 个键")
        else:
            print(f"    {k}: {json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v}")


# ════════════════════════════════════════════════════════════════════
#  初始化 — 创建临时项目目录避免污染真实数据
# ════════════════════════════════════════════════════════════════════

_tmp_dir = tempfile.mkdtemp(prefix="harness-mcp-demo-")
os.environ["CLAUDE_PROJECT_DIR"] = _tmp_dir

server = HarnessMCPServer(project_dir=_tmp_dir)


# ════════════════════════════════════════════════════════════════════
#  Demo 1: 合规检查工具组
# ════════════════════════════════════════════════════════════════════

def demo_compliance_group() -> None:
    _print_section("Demo 1: 合规检查工具组 — harness_check + harness_guardrails_check + harness_rule_import")

    # ── 1.1 harness_check: 基本合规扫描 ────────────────────────────
    args = {
        "path": "src/main.py",
        "pack_names": ["coding", "security"],
        "engine": "builtin",
    }
    result = server._tool_check(args)
    _print_demo("基本合规扫描", "harness_check", args, result)

    # ── 1.2 harness_check: 语言路由 ────────────────────────────────
    args = {
        "path": "src/App.java",
        "pack_names": ["coding"],
        "engine": "builtin",
        "language_routing": {"java": "archunit", "javascript": "dep_cruiser"},
    }
    result = server._tool_check(args)
    _print_demo("带语言路由的合规扫描", "harness_check", args, result)

    # ── 1.3 harness_check: 外部引擎路由 ────────────────────────────
    args = {
        "path": "src/utils.ts",
        "engine": "archunit",
        "pack_names": ["coding"],
    }
    result = server._tool_check(args)
    _print_demo("外部引擎合规扫描（archunit，SDK未安装会回退builtin）", "harness_check", args, result)

    # ── 1.4 harness_guardrails_check: 输入护栏 ──────────────────────
    args = {
        "content": "请帮我写一个登录功能，用户名是 admin，密码是 password123",
        "direction": "input",
        "engine": "builtin",
    }
    result = server._tool_guardrails_check(args)
    _print_demo("输入护栏检查（PII检测）", "harness_guardrails_check", args, result)

    # ── 1.5 harness_guardrails_check: 输出护栏 ──────────────────────
    args = {
        "content": "生成的代码中包含数据库连接字符串 mysql://root:secret@localhost:3306/db",
        "direction": "output",
        "engine": "builtin",
    }
    result = server._tool_guardrails_check(args)
    _print_demo("输出护栏检查（敏感信息检测）", "harness_guardrails_check", args, result)

    # ── 1.6 harness_guardrails_check: guardrails-ai 引擎 ───────────
    args = {
        "content": "我的手机号是 13800138000",
        "direction": "input",
        "engine": "guardrails-ai",
    }
    result = server._tool_guardrails_check(args)
    _print_demo("Guardrails AI 引擎（SDK未安装会回退builtin）", "harness_guardrails_check", args, result)

    # ── 1.7 harness_rule_import: SonarQube 规则导入 ─────────────────
    args = {
        "source": "sonarqube",
        "project_key": "my-project",
        "config": {
            "sonarqube_url": "http://localhost:9000",
            "sonarqube_token": "squ_xxx",
        },
        "languages": ["python", "java"],
    }
    result = server._tool_rule_import(args)
    _print_demo("SonarQube 规则导入", "harness_rule_import", args, result)

    # ── 1.8 harness_rule_import: ArchUnit 规则导入 ──────────────────
    args = {
        "source": "archunit",
        "project_key": "/path/to/project",
        "config": {
            "test_file": "ArchUnitTests.java",
        },
    }
    result = server._tool_rule_import(args)
    _print_demo("ArchUnit 规则导入", "harness_rule_import", args, result)

    # ── 1.9 harness_rule_import: DepCruiser 规则导入 ────────────────
    args = {
        "source": "dep_cruiser",
        "project_key": "/path/to/project",
        "config": {
            "config_file": ".dependency-cruiser.js",
        },
    }
    result = server._tool_rule_import(args)
    _print_demo("DepCruiser 规则导入", "harness_rule_import", args, result)


# ════════════════════════════════════════════════════════════════════
#  Demo 2: 审计追踪工具组
# ════════════════════════════════════════════════════════════════════

def demo_audit_group() -> None:
    _print_section("Demo 2: 审计追踪工具组 — harness_audit + harness_trace_export + harness_status")

    # ── 2.1 harness_audit: 搜索审计记录 ────────────────────────────
    args = {
        "query": "session-001",
        "limit": 10,
        "backend": "local",
    }
    result = server._tool_audit(args)
    _print_demo("搜索审计记录（本地存储）", "harness_audit", args, result)

    # ── 2.2 harness_audit: Langfuse 后端搜索 ──────────────────────
    args = {
        "query": "compliance-check",
        "limit": 20,
        "backend": "langfuse",
    }
    result = server._tool_audit(args)
    _print_demo("Langfuse 后端搜索（标记为langfuse，实际搜索仍从primary store）", "harness_audit", args, result)

    # ── 2.3 harness_trace_export: OTel JSON 格式 ───────────────────
    args = {
        "format": "otel-json",
        "query": "",
        "date_from": "2026-01-01",
        "date_to": "2026-12-31",
        "limit": 10,
    }
    result = server._tool_trace_export(args)
    _print_demo("OTel JSON 格式导出审计追踪", "harness_trace_export", args, result)

    # ── 2.4 harness_trace_export: Traceloop 格式 ───────────────────
    args = {
        "format": "traceloop",
        "query": "agent",
        "limit": 5,
    }
    result = server._tool_trace_export(args)
    _print_demo("Traceloop 格式导出审计追踪（SDK不可用会回退otel-json）", "harness_trace_export", args, result)

    # ── 2.5 harness_status: 系统聚合状态 ──────────────────────────
    args = {}
    result = server._tool_status(args)
    _print_demo("系统聚合状态", "harness_status", args, result)


# ════════════════════════════════════════════════════════════════════
#  Demo 3: 工作流编排工具组
# ════════════════════════════════════════════════════════════════════

def demo_workflow_group() -> None:
    _print_section("Demo 3: 工作流编排工具组 — harness_plan + harness_run + harness_pipeline_run + harness_pipeline_status")

    # ── 3.1 harness_plan: DAG 拓扑可视化 ──────────────────────────
    workflow_yaml = """
id: code-review-workflow
name: 代码审查工作流
nodes:
  - id: analyst
    agent_type: analyst
    task: 分析代码变更的影响范围
  - id: coder
    agent_type: coder
    task: 根据分析结果编写修复代码
  - id: validator
    agent_type: validator
    task: 验证修复代码的合规性
edges:
  - from: analyst
    to: coder
  - from: coder
    to: validator
"""
    args = {"workflow_yaml": workflow_yaml}
    result = server._tool_plan(args)
    _print_demo("DAG 拓扑可视化（3节点顺序工作流）", "harness_plan", args, result)

    # ── 3.2 harness_plan: 带并行节点的 DAG ────────────────────────
    parallel_yaml = """
id: parallel-review
name: 并行审查工作流
nodes:
  - id: security-check
    agent_type: validator
    task: 安全合规检查
  - id: quality-check
    agent_type: validator
    task: 代码质量检查
  - id: merge
    agent_type: coder
    task: 合并检查结果并修复
edges:
  - from: security-check
    to: merge
  - from: quality-check
    to: merge
"""
    args = {"workflow_yaml": parallel_yaml}
    result = server._tool_plan(args)
    _print_demo("DAG 拓扑可视化（并行汇聚工作流）", "harness_plan", args, result)

    # ── 3.3 harness_run: 执行 DAG 工作流 ──────────────────────────
    args = {"workflow_yaml": workflow_yaml}
    result = server._tool_run(args)
    _print_demo("执行 DAG 工作流", "harness_run", args, result)

    # ── 3.4 harness_pipeline_run: 编码流水线 ──────────────────────
    args = {
        "task": "修复 login.py 中的 SQL 注入漏洞",
        "working_directory": "/path/to/project",
        "gate_mode": "hybrid",
        "agents": ["analyst", "coder", "validator", "committer"],
        "max_retries": 2,
    }
    result = server._tool_pipeline_run(args)
    _print_demo("编码流水线（Analyst→Coder→Validator→Committer）", "harness_pipeline_run", args, result)

    # ── 3.5 harness_pipeline_run: strict 门禁模式 ─────────────────
    args = {
        "task": "重构 authentication 模块",
        "gate_mode": "strict",
        "agents": ["analyst", "coder", "validator"],
        "max_retries": 3,
    }
    result = server._tool_pipeline_run(args)
    _print_demo("编码流水线（strict 门禁模式）", "harness_pipeline_run", args, result)

    # ── 3.6 harness_pipeline_status: 流水线状态查询 ────────────────
    args = {}
    result = server._tool_pipeline_status(args)
    _print_demo("流水线状态查询", "harness_pipeline_status", args, result)


# ════════════════════════════════════════════════════════════════════
#  Demo 4: 门禁管理工具组
# ════════════════════════════════════════════════════════════════════

def demo_gate_group() -> None:
    _print_section("Demo 4: 门禁管理工具组 — harness_gate_create")

    # ── 4.1 harness_gate_create: strict 门禁 ──────────────────────
    args = {
        "gate_type": "strict",
        "checks": [
            {
                "id": "security-critical",
                "category": "security",
                "severity": "critical",
                "description": "所有安全规则必须通过，零容忍",
            },
            {
                "id": "no-hardcoded-secrets",
                "category": "security",
                "severity": "high",
                "description": "禁止硬编码密钥/密码",
            },
        ],
        "auto_fix": False,
    }
    result = server._tool_gate_create(args)
    _print_demo("strict 门禁（零容忍）", "harness_gate_create", args, result)

    # ── 4.2 harness_gate_create: hybrid 门禁 + 自动修复 ───────────
    args = {
        "gate_type": "hybrid",
        "checks": [
            {
                "id": "code-quality",
                "category": "logic",
                "severity": "medium",
                "description": "代码质量检查——允许低级别问题通过",
            },
            {
                "id": "test-coverage",
                "category": "logic",
                "severity": "low",
                "description": "测试覆盖率检查",
            },
        ],
        "auto_fix": True,
    }
    result = server._tool_gate_create(args)
    _print_demo("hybrid 门禁 + 自动修复", "harness_gate_create", args, result)

    # ── 4.3 harness_gate_create: loose 门禁 ────────────────────────
    args = {
        "gate_type": "loose",
        "checks": [
            {
                "id": "critical-only",
                "category": "security",
                "severity": "critical",
                "description": "仅拦截 critical 级别问题",
            },
        ],
    }
    result = server._tool_gate_create(args)
    _print_demo("loose 门禁（仅拦截 critical）", "harness_gate_create", args, result)


# ════════════════════════════════════════════════════════════════════
#  Demo 5: 注册/配置工具组
# ════════════════════════════════════════════════════════════════════

def demo_registration_group() -> None:
    _print_section("Demo 5: 注册/配置工具组 — harness_register + harness_agent_list + harness_profile_list + harness_profile_load + harness_skill_list + harness_skill_register + harness_bridge_deploy")

    # ── 5.1 harness_register: 注册 Agent ────────────────────────────
    args = {
        "agent_id": "security-reviewer",
        "name": "安全审查 Agent",
        "capabilities": ["perceive", "reason", "execute"],
        "toolsets": ["compliance", "audit"],
    }
    result = server._tool_register(args)
    _print_demo("注册安全审查 Agent", "harness_register", args, result)

    # ── 5.2 harness_register: 注册编码 Agent ────────────────────────
    args = {
        "agent_id": "auto-fixer",
        "name": "自动修复 Agent",
        "capabilities": ["execute", "self_drive"],
        "toolsets": ["coder", "validator"],
    }
    result = server._tool_register(args)
    _print_demo("注册自动修复 Agent", "harness_register", args, result)

    # ── 5.3 harness_agent_list: 列出可用 Agent ──────────────────────
    args = {}
    result = server._tool_agent_list(args)
    _print_demo("列出可用 Agent 角色", "harness_agent_list", args, result)

    # ── 5.4 harness_profile_list: 列出可用 Profile ─────────────────
    args = {}
    result = server._tool_profile_list(args)
    _print_demo("列出可用 Profile", "harness_profile_list", args, result)

    # ── 5.5 harness_profile_load: 加载指定 Profile ─────────────────
    args = {
        "name": "default",
    }
    result = server._tool_profile_load(args)
    _print_demo("加载 default Profile", "harness_profile_load", args, result)

    # ── 5.6 harness_profile_load: 自动解析 Profile ────────────────
    args = {}  # name 留空 → 自动解析（环境变量 > marker > default）
    result = server._tool_profile_load(args)
    _print_demo("自动解析 Profile（环境变量 > marker > default）", "harness_profile_load", args, result)

    # ── 5.7 harness_profile_load: 加载 frontend Profile ───────────
    args = {
        "name": "frontend",
    }
    result = server._tool_profile_load(args)
    _print_demo("加载 frontend Profile", "harness_profile_load", args, result)

    # ── 5.8 harness_skill_list: 列出已注册 Skill ──────────────────
    args = {}
    result = server._tool_skill_list(args)
    _print_demo("列出所有已注册 Skill", "harness_skill_list", args, result)

    # ── 5.9 harness_skill_list: 按槽位过滤 ─────────────────────────
    args = {"slot": "post_execute"}
    result = server._tool_skill_list(args)
    _print_demo("按 post_execute 槽位过滤 Skill", "harness_skill_list", args, result)

    # ── 5.10 harness_skill_list: 按标签过滤 ────────────────────────
    args = {"tag": "compliance"}
    result = server._tool_skill_list(args)
    _print_demo("按 compliance 标签过滤 Skill", "harness_skill_list", args, result)

    # ── 5.11 harness_skill_register: 注册新 Skill ──────────────────
    args = {
        "skill_id": "auto-lint-fix",
        "name": "自动 lint 修复",
        "description": "在代码提交前自动修复 lint 问题",
        "entry_point": "skills/auto_lint_fix.py",
        "slot": "pre_execute",
        "tags": ["compliance", "lint", "auto-fix"],
    }
    result = server._tool_skill_register(args)
    _print_demo("注册自动 lint 修复 Skill", "harness_skill_register", args, result)

    # ── 5.12 harness_skill_register: 注册 on_gate_pass Skill ───────
    args = {
        "skill_id": "notify-on-pass",
        "name": "门禁通过通知",
        "description": "门禁检查通过后发送通知",
        "entry_point": "skills/notify_pass.py",
        "slot": "on_gate_pass",
        "tags": ["notification"],
    }
    result = server._tool_skill_register(args)
    _print_demo("注册门禁通过通知 Skill", "harness_skill_register", args, result)

    # ── 5.13 harness_bridge_deploy: 部署到 Claude Code ────────────
    args = {
        "adapter": "claude-code",
    }
    result = server._tool_bridge_deploy(args)
    _print_demo("部署 Profile 到 Claude Code（自动解析）", "harness_bridge_deploy", args, result)

    # ── 5.14 harness_bridge_deploy: 部署到 Copilot CLI ────────────
    args = {
        "adapter": "copilot-cli",
        "profile_name": "frontend",
    }
    result = server._tool_bridge_deploy(args)
    _print_demo("部署 frontend Profile 到 Copilot CLI", "harness_bridge_deploy", args, result)

    # ── 5.15 harness_bridge_deploy: 部署到 Cursor ─────────────────
    args = {
        "adapter": "cursor",
        "profile_name": "default",
    }
    result = server._tool_bridge_deploy(args)
    _print_demo("部署 default Profile 到 Cursor", "harness_bridge_deploy", args, result)


# ════════════════════════════════════════════════════════════════════
#  Main
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("  Harness-Cook MCP 全量工具 Demo")
    print("  18 个 MCP 工具的调用方式与预期返回")
    print("=" * 70)

    demo_compliance_group()
    demo_audit_group()
    demo_workflow_group()
    demo_gate_group()
    demo_registration_group()

    # ── 清理临时目录 ───────────────────────────────────────────────
    shutil.rmtree(_tmp_dir, ignore_errors=True)

    print("\n" + "=" * 70)
    print("  所有 MCP Demo 完成（18 个工具，5 个分组）")
    print("=" * 70)

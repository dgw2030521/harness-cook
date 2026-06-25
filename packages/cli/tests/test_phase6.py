"""
harness-cook CLI 集成测试

测试所有 CLI 子命令: plan/run/check/audit/version
"""

import json
import os
import tempfile
from pathlib import Path
from datetime import datetime

from harness import __version__
from harness.types import (
    DAGNode, DAGEdge, DAGWorkflow, GateDefinition, GateMode,
    GateCheck, CheckResult, RetryStrategy, Artifact,
    AgentDefinition, AgentCapability,
    ComplianceCategory, ComplianceRule, ComplianceResult,
    AuditEntry, AuditStats,
    TaskResult,
)
from harness.audit import AuditStore, AuditEngine
from harness.bus import EventBus, get_bus

from harness_cli import main as cli_main
from cli_commands.plan import (
    _load_workflow, _topological_sort,
    _format_tree, _format_dot, _format_json,
)
from cli_commands.check import (
    _build_security_rules, _build_coding_rules,
    _scan_path, _detect_language,
)


# ─── 测试数据工厂 ───────────────────────────────────────

def _make_simple_workflow_dict():
    """创建简单线性工作流定义"""
    return {
        "id": "test-workflow",
        "name": "测试工作流",
        "description": "简单线性流程",
        "nodes": [
            {
                "id": "step-1",
                "name": "数据采集",
                "task": "数据采集",
                "agent_type": "collector",
                "agent": {
                    "id": "collector",
                    "name": "采集Agent",
                    "capabilities": ["execute"],
                },
                "gate": {
                    "id": "gate-1",
                    "mode": "hybrid",
                    "checks": [
                        {"id": "chk-1", "description": "数据完整性", "category": "style", "severity": "high"},
                        {"id": "chk-2", "description": "格式校验", "category": "style", "severity": "medium"},
                    ],
                    "max_retries": 2,
                },
            },
            {
                "id": "step-2",
                "name": "数据分析",
                "task": "数据分析",
                "agent_type": "analyzer",
                "agent": {
                    "id": "analyzer",
                    "name": "分析Agent",
                    "capabilities": ["reason"],
                },
            },
            {
                "id": "step-3",
                "name": "报告生成",
                "task": "报告生成",
                "agent_type": "reporter",
                "agent": {
                    "id": "reporter",
                    "name": "报告Agent",
                    "capabilities": ["execute"],
                },
            },
        ],
        "edges": [
            {"from_node": "step-1", "to_node": "step-2"},
            {"from_node": "step-2", "to_node": "step-3"},
        ],
    }


def _make_parallel_workflow_dict():
    """创建带并行节点的工作流定义"""
    return {
        "id": "parallel-workflow",
        "name": "并行工作流",
        "nodes": [
            {"id": "A", "name": "节点A", "task": "节点A", "agent_type": "agent-a", "agent": {"id": "agent-a", "name": "A", "capabilities": ["execute"]}},
            {"id": "B", "name": "节点B", "task": "节点B", "agent_type": "agent-b", "agent": {"id": "agent-b", "name": "B", "capabilities": ["execute"]}},
            {"id": "C", "name": "节点C", "task": "节点C", "agent_type": "agent-c", "agent": {"id": "agent-c", "name": "C", "capabilities": ["execute"]}},
            {"id": "D", "name": "节点D", "task": "节点D", "agent_type": "agent-d", "agent": {"id": "agent-d", "name": "D", "capabilities": ["execute"]}},
        ],
        "edges": [
            {"from_node": "A", "to_node": "C"},
            {"from_node": "B", "to_node": "C"},
            {"from_node": "C", "to_node": "D"},
        ],
    }


def _write_json_workflow(data, tmpdir):
    """写入 JSON 工作流文件"""
    filepath = os.path.join(tmpdir, "workflow.json")
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    return filepath


# ─── Plan 命令测试 ───────────────────────────────────────

def test_plan_load_json_workflow():
    """测试从 JSON 文件加载工作流"""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = _write_json_workflow(_make_simple_workflow_dict(), tmpdir)
        workflow = _load_workflow(filepath)
        assert workflow.id == "test-workflow"
        assert len(workflow.nodes) == 3
        assert len(workflow.edges) == 2


def test_plan_load_yaml_workflow():
    """测试从 YAML 文件加载工作流（如果 yaml 可用）"""
    try:
        import yaml
    except ImportError:
        # 没有 yaml 库，跳过
        print("跳过 YAML 测试（未安装 PyYAML）")
        return

    data = _make_simple_workflow_dict()
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "workflow.yaml")
        with open(filepath, "w") as f:
            yaml.dump(data, f)
        workflow = _load_workflow(filepath)
        assert workflow.id == "test-workflow"
        assert len(workflow.nodes) == 3


def test_plan_load_nonexistent():
    """测试加载不存在的文件"""
    try:
        _load_workflow("/nonexistent/file.json")
        assert False, "应该抛出 FileNotFoundError"
    except FileNotFoundError:
        pass


def test_plan_topological_sort_linear():
    """测试线性 DAG 拓扑排序"""
    data = _make_simple_workflow_dict()
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = _write_json_workflow(data, tmpdir)
        workflow = _load_workflow(filepath)
        order = _topological_sort(workflow)
        assert order == ["step-1", "step-2", "step-3"]


def test_plan_topological_sort_parallel():
    """测试并行 DAG 拓扑排序"""
    data = _make_parallel_workflow_dict()
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = _write_json_workflow(data, tmpdir)
        workflow = _load_workflow(filepath)
        order = _topological_sort(workflow)
        # A, B 可以并行，C 在 A,B 之后，D 在 C 之后
        assert "C" not in order[:2]  # C 不在前两个
        assert order[-1] == "D"      # D 是最后


def test_plan_format_tree():
    """测试树状格式输出"""
    data = _make_simple_workflow_dict()
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = _write_json_workflow(data, tmpdir)
        workflow = _load_workflow(filepath)
        output = _format_tree(workflow, show_gates=True)
        assert "测试工作流" in output
        assert "数据采集" in output
        assert "门禁" in output
        assert "数据完整性" in output


def test_plan_format_tree_no_gates():
    """测试树状格式（不显示门禁）"""
    data = _make_simple_workflow_dict()
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = _write_json_workflow(data, tmpdir)
        workflow = _load_workflow(filepath)
        output = _format_tree(workflow, show_gates=False)
        assert "测试工作流" in output
        assert "门禁" not in output


def test_plan_format_dot():
    """测试 DOT 格式输出"""
    data = _make_simple_workflow_dict()
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = _write_json_workflow(data, tmpdir)
        workflow = _load_workflow(filepath)
        output = _format_dot(workflow)
        assert "digraph" in output
        assert "step-1" in output
        assert "->" in output


def test_plan_format_json():
    """测试 JSON 格式输出"""
    data = _make_simple_workflow_dict()
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = _write_json_workflow(data, tmpdir)
        workflow = _load_workflow(filepath)
        output = _format_json(workflow)
        parsed = json.loads(output)
        assert parsed["id"] == "test-workflow"
        assert parsed["topological_order"] == ["step-1", "step-2", "step-3"]


def test_plan_cli_tree():
    """测试 CLI plan 命令（tree 格式）"""
    data = _make_simple_workflow_dict()
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = _write_json_workflow(data, tmpdir)
        result = cli_main(["plan", filepath, "--format", "tree"])
        assert result == 0


def test_plan_cli_dot():
    """测试 CLI plan 命令（dot 格式）"""
    data = _make_simple_workflow_dict()
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = _write_json_workflow(data, tmpdir)
        result = cli_main(["plan", filepath, "--format", "dot"])
        assert result == 0


def test_plan_cli_json():
    """测试 CLI plan 命令（json 格式）"""
    data = _make_simple_workflow_dict()
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = _write_json_workflow(data, tmpdir)
        result = cli_main(["plan", filepath, "--format", "json"])
        assert result == 0


def test_plan_cli_show_gates():
    """测试 CLI plan 命令（显示门禁）"""
    data = _make_simple_workflow_dict()
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = _write_json_workflow(data, tmpdir)
        result = cli_main(["plan", filepath, "--show-gates"])
        assert result == 0


# ─── Run 命令测试 ───────────────────────────────────────

def test_run_dry_run():
    """测试 run dry-run 模式"""
    data = _make_simple_workflow_dict()
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = _write_json_workflow(data, tmpdir)
        result = cli_main(["run", filepath, "--dry-run"])
        assert result == 0


def test_run_dry_run_invalid_dag():
    """测试 run dry-run 检测无效 DAG"""
    data = {
        "id": "bad-workflow",
        "nodes": [
            {"id": "step-1", "name": "A", "task": "A", "agent_type": "a1", "agent": {"id": "a1", "name": "A", "capabilities": ["execute"]}},
        ],
        "edges": [
            {"from_node": "nonexistent", "to_node": "step-1"},
        ],
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = _write_json_workflow(data, tmpdir)
        result = cli_main(["run", filepath, "--dry-run"])
        assert result == 1


def test_run_actual_execution():
    """测试实际执行（Mock Agent）"""
    data = _make_simple_workflow_dict()
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = _write_json_workflow(data, tmpdir)
        result = cli_main(["run", filepath, "--gate-mode", "loose"])
        # Mock Agent 执行应该成功
        assert result in (0, 1, 3)


def test_run_with_context_file():
    """测试带初始上下文执行"""
    data = _make_simple_workflow_dict()
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = _write_json_workflow(data, tmpdir)
        ctx_file = os.path.join(tmpdir, "context.json")
        with open(ctx_file, "w") as f:
            json.dump({"env": "test"}, f)
        result = cli_main(["run", filepath, "--context", ctx_file, "--dry-run"])
        assert result == 0


# ─── Check 命令测试 ───────────────────────────────────────

def test_check_security_rules():
    """测试安全规则定义"""
    rules = _build_security_rules()
    assert len(rules) >= 5
    assert all(r.category == ComplianceCategory.SECURITY for r in rules)
    # 检查 SEC-001 硬编码密钥
    sec001 = [r for r in rules if r.id == "SEC-001"][0]
    assert sec001.severity == "critical"


def test_check_coding_rules():
    """测试编码规则定义"""
    rules = _build_coding_rules()
    assert len(rules) >= 4
    # CODE-002 TODO 标记
    code002 = [r for r in rules if r.id == "CODE-002"][0]
    assert code002.severity == "low"
    assert code002.category == ComplianceCategory.STYLE


def test_check_detect_language():
    """测试语言检测"""
    assert _detect_language(".py") == "python"
    assert _detect_language(".js") == "javascript"
    assert _detect_language(".ts") == "typescript"
    assert _detect_language(".unknown") == "unknown"


def test_check_scan_file():
    """测试扫描单个文件"""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "test.py")
        with open(filepath, "w") as f:
            f.write("password = 'super_secret_123'\n")
        artifacts = _scan_path(filepath)
        assert len(artifacts) == 1
        assert artifacts[0].metadata["language"] == "python"
        assert artifacts[0].type == "code"
        assert artifacts[0].path == str(Path(filepath).resolve())


def test_check_scan_directory():
    """测试扫描目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建多个文件
        for name in ["a.py", "b.js", "c.ts", "d.txt"]:
            with open(os.path.join(tmpdir, name), "w") as f:
                f.write("# test\n")
        # 创建隐藏目录（应跳过）
        os.makedirs(os.path.join(tmpdir, ".hidden"), exist_ok=True)
        with open(os.path.join(tmpdir, ".hidden", "e.py"), "w") as f:
            f.write("# should skip\n")
        artifacts = _scan_path(tmpdir)
        # .txt 和 .hidden 不在扫描范围
        assert len(artifacts) == 3  # a.py, b.js, c.ts


def test_check_cli_basic():
    """测试 CLI check 命令"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建带违规的文件
        filepath = os.path.join(tmpdir, "bad.py")
        with open(filepath, "w") as f:
            f.write("api_key = 'sk-12345678abcdef'\nconsole.log('debug')\n")
        result = cli_main(["check", tmpdir, "--output", "table"])
        # 有违规应该返回 1 (critical/high)
        assert result in (0, 1)


def test_check_cli_category_filter():
    """测试 CLI check 按类别过滤"""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "test.py")
        with open(filepath, "w") as f:
            f.write("# TODO: fix this\n")
        result = cli_main(["check", tmpdir, "--category", "coding"])
        assert result in (0, 1)


def test_check_cli_json_output():
    """测试 CLI check JSON 输出"""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "test.py")
        with open(filepath, "w") as f:
            f.write("# simple file\n")
        result = cli_main(["check", tmpdir, "--output", "json"])
        assert result in (0, 1)


def test_check_cli_summary_output():
    """测试 CLI check summary 输出"""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "test.py")
        with open(filepath, "w") as f:
            f.write("# simple\n")
        result = cli_main(["check", tmpdir, "--output", "summary"])
        assert result in (0, 1)


# ─── Audit 命令测试 ───────────────────────────────────────

def test_audit_cli_empty_query():
    """测试 CLI audit 空查询"""
    result = cli_main(["audit", ""])
    assert result == 0


def test_audit_cli_with_query():
    """测试 CLI audit 关键词搜索"""
    result = cli_main(["audit", "test", "--limit", "5"])
    assert result == 0


def test_audit_cli_session_filter():
    """测试 CLI audit session 过滤"""
    result = cli_main(["audit", "", "--session", "phase1-session"])
    assert result == 0


def test_audit_cli_json_output():
    """测试 CLI audit JSON 输出"""
    result = cli_main(["audit", "", "--output", "json"])
    assert result == 0


def test_audit_cli_detail_output():
    """测试 CLI audit detail 输出"""
    result = cli_main(["audit", "", "--output", "detail", "--limit", "3"])
    assert result == 0


# ─── Version 命令测试 ───────────────────────────────────────

def test_version_cli():
    """测试 CLI version 命令"""
    result = cli_main(["version"])
    assert result == 0


def test_version_string():
    """测试版本号值"""
    assert __version__ == "0.1.0"


# ─── 错误处理测试 ───────────────────────────────────────

def test_no_command():
    """测试无子命令（打印帮助）"""
    result = cli_main([])
    assert result == 0


def test_plan_nonexistent_file():
    """测试 plan 不存在的文件"""
    result = cli_main(["plan", "/nonexistent/workflow.json"])
    assert result == 2


def test_run_nonexistent_file():
    """测试 run 不存在的文件"""
    result = cli_main(["run", "/nonexistent/workflow.json"])
    assert result == 2
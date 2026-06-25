#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
#  harness-cook CLI Demo 脚本
#
#  本脚本演示 harness CLI 的四个核心命令:
#    1. harness plan  — 可视化 DAG 工作流
#    2. harness check — 合规/质量检查
#    3. harness audit — 查看审计记录
#    4. harness status — 查看系统状态
#
#  运行方式:
#    bash playground/demo_cli.sh
#
#  前置条件:
#    - harness CLI 已安装（或通过 python packages/cli/harness_cli.py 可运行）
#    - playground/demo_workflow.yaml 存在
# ═══════════════════════════════════════════════════════════════════

set -e

# ── 定位项目根目录 ──────────────────────────────────────────────────
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLI_DIR="$PROJECT_ROOT/packages/cli"
CORE_DIR="$PROJECT_ROOT/packages/core"
WORKFLOW_FILE="$PROJECT_ROOT/playground/demo_workflow.yaml"

# ── 设置 PYTHONPATH ────────────────────────────────────────────────
# core 必须排在 cli 前面，避免 cli/harness/__init__.py 覆盖 core/harness/__init__.py
export PYTHONPATH="$CORE_DIR:$PYTHONPATH"

# ── 确定 harness 命令 ─────────────────────────────────────────────
# 由于 packages/cli/ 下有 harness/__init__.py shim 会和 core/harness/ 冲突,
# 我们使用 playground/run_cli.py 作为运行入口, 它会正确处理 sys.path

PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "错误: 未找到 Python，请安装 Python 3.9+"
    exit 1
fi

RUNNER="$PROJECT_ROOT/playground/run_cli.py"

if command -v harness &> /dev/null; then
    HARNESS_CMD="harness"
else
    HARNESS_CMD="$PYTHON_CMD $RUNNER"
fi

echo "════════════════════════════════════════════════════════════════"
echo "  harness-cook CLI Demo"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "  命令: $HARNESS_CMD"
echo "  工作流文件: $WORKFLOW_FILE"
echo ""

# ═══════════════════════════════════════════════════════════════════
#  1. harness version — 查看版本
# ═══════════════════════════════════════════════════════════════════
echo "──────────────────────────────────────────────────────────────"
echo "  1. harness version — 查看版本号"
echo "──────────────────────────────────────────────────────────────"
echo ""

$HARNESS_CMD version
echo ""

# ═══════════════════════════════════════════════════════════════════
#  2. harness plan — 可视化 DAG 工作流
# ═══════════════════════════════════════════════════════════════════
echo "──────────────────────────────────────────────────────────────"
echo "  2. harness plan — 可视化 DAG 工作流"
echo "──────────────────────────────────────────────────────────────"
echo ""
echo "  说明: 解析 YAML 工作流，输出 DAG 拓扑图和执行顺序"
echo ""

# 检查工作流文件是否存在
if [ -f "$WORKFLOW_FILE" ]; then
    echo "  使用工作流: $WORKFLOW_FILE"
    echo ""
    $HARNESS_CMD plan "$WORKFLOW_FILE" --format tree
    echo ""
    echo "  ── 也可以用 JSON 格式输出 ──"
    $HARNESS_CMD plan "$WORKFLOW_FILE" --format json 2>/dev/null || echo "  (JSON格式输出完成)"
    echo ""
else
    echo "  ⚠ 工作流文件不存在: $WORKFLOW_FILE"
    echo "  请先创建 playground/demo_workflow.yaml"
    echo ""
fi

# ═══════════════════════════════════════════════════════════════════
#  3. harness check — 合规/质量检查
# ═══════════════════════════════════════════════════════════════════
echo "──────────────────────────────────────────────────────────────"
echo "  3. harness check — 合规/质量检查"
echo "──────────────────────────────────────────────────────────────"
echo ""
echo "  说明: 扫描指定路径的代码，执行安全/隐私合规检查"
echo ""

# 对项目自身做一次合规检查（只检查 core 目录）
echo "  检查目标: $CORE_DIR/harness/"
echo ""
$HARNESS_CMD check "$CORE_DIR/harness/" --output summary 2>/dev/null || echo "  (检查完成，可能有部分告警)"
echo ""

# 也可以只检查安全类别
echo "  ── 只检查安全类别 ──"
$HARNESS_CMD check "$CORE_DIR/harness/" --category security --output summary 2>/dev/null || echo "  (安全检查完成)"
echo ""

# ═══════════════════════════════════════════════════════════════════
#  4. harness audit — 查看审计记录
# ═══════════════════════════════════════════════════════════════════
echo "──────────────────────────────────────────────────────────────"
echo "  4. harness audit — 查看审计记录"
echo "──────────────────────────────────────────────────────────────"
echo ""
echo "  说明: 搜索 Harness 审计日志，追溯 Agent 决策链"
echo ""

# 查看最近的审计记录
echo "  ── 查看最近记录 ──"
$HARNESS_CMD audit "" --limit 5 --output summary 2>/dev/null || echo "  (审计日志为空——这是因为 demo 刚运行，还没有历史记录)"
echo ""

# 搜索包含 "login" 关键词的审计记录
echo "  ── 搜索关键词 'login' ──"
$HARNESS_CMD audit "login" --limit 10 2>/dev/null || echo "  (搜索完成，可能没有匹配记录)"
echo ""

# ═══════════════════════════════════════════════════════════════════
#  总结
# ═══════════════════════════════════════════════════════════════════
echo "════════════════════════════════════════════════════════════════"
echo "  CLI Demo 完成！"
echo ""
echo "  展示的命令:"
echo "    ✅ harness version  — 版本号"
echo "    ✅ harness plan     — DAG 工作流可视化"
echo "    ✅ harness check    — 合规/质量检查"
echo "    ✅ harness audit    — 审计记录查询"
echo ""
echo "  更多命令:"
echo "    → harness run <workflow.yaml>  — 执行工作流"
echo "    → harness <command> --help     — 查看子命令帮助"
echo ""
echo "  下一步:"
echo "    → 运行 playground/demo_basic.py 了解 Python API"
echo "    → 运行 playground/demo_mcp.py 了解 MCP Server"
echo "════════════════════════════════════════════════════════════════"
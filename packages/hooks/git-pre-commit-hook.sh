#!/usr/bin/env bash
#
# harness-cook git pre-commit hook
#
# 功能：在 git commit 前自动运行 harness 合规扫描，
#       未通过的变更将被拦截，确保任何提交都经过治理验证。
#
# 安装方式：由 harness bridge deploy 自动安装到此位置，
#           或手动复制到 .git/hooks/pre-commit
#
# 退出码：
#   0 → 合规通过，commit 放行
#   1 → 合规违规，commit 拒绝
#

set -euo pipefail

# ── 检测 harness 命令是否可用 ──
if ! command -v harness &>/dev/null; then
    # harness CLI 不在 PATH 中，尝试用 Python 直接调用
    HARNESS_ROOT="${HARNESS_COOK_ROOT:-}"
    if [ -z "$HARNESS_ROOT" ]; then
        # 尝试从当前脚本位置推导
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        # .git/hooks/pre-commit → 项目根目录
        PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../" && pwd)"
        if [ -f "$PROJECT_ROOT/packages/core/harness/__init__.py" ]; then
            HARNESS_ROOT="$PROJECT_ROOT"
        fi
    fi

    if [ -n "$HARNESS_ROOT" ] && [ -f "$HARNESS_ROOT/packages/core/harness/__init__.py" ]; then
        PYTHONPATH="$HARNESS_ROOT/packages/core:$HARNESS_ROOT/packages/cli"
        CHECK_CMD="python3 -c 'from harness.compliance import ComplianceEngine; from harness.config import load_profile; profile = load_profile(); engine = ComplianceEngine(); result = engine.scan(\".\", pack_names=profile.gate_checks if profile.gate_checks else None); exit(1 if result.has_violations(severity=\"critical\") else 0)'"
    else
        echo "[harness] ⚠ harness-cook 未安装，跳过合规检查"
        exit 0
    fi
else
    CHECK_CMD="harness check --pre-commit ."
fi

# ── 获取本次提交的变更文件 ──
STAGED_FILES=""
if git diff --cached --name-only --diff-filter=ACM &>/dev/null; then
    STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM)
fi

if [ -z "$STAGED_FILES" ]; then
    # 没有文件变更（如仅修改权限），跳过检查
    exit 0
fi

# ── 运行合规扫描 ──
echo "[harness] 🔍 正在扫描提交的文件..."

SCAN_EXIT=0
eval "$CHECK_CMD" || SCAN_EXIT=$?

if [ $SCAN_EXIT -ne 0 ]; then
    echo ""
    echo "══════════════════════════════════════════════════════"
    echo "[harness gate] ❌ 合规检查未通过，commit 被拒绝"
    echo ""
    echo "请修复违规后重新提交，或运行以下命令查看详情："
    echo "  harness check ."
    echo "  harness audit"
    echo ""
    echo "如需临时绕过（仅限紧急情况）："
    echo "  git commit --no-verify"
    echo "══════════════════════════════════════════════════════"
    exit 1
fi

echo "[harness] ✅ 合规检查通过"
exit 0

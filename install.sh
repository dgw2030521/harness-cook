#!/usr/bin/env bash
# harness-cook 一键安装脚本
# 用法: git clone ... && cd harness-cook && ./install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CORE_PKG="$SCRIPT_DIR/packages/core"
CLI_PKG="$SCRIPT_DIR/packages/cli"

# 优先 python3，回退 python
PYTHON="${PYTHON:-$(command -v python3 2>/dev/null || command -v python 2>/dev/null)}"

if [ -z "$PYTHON" ]; then
  echo "❌ 未找到 python3，请先安装 Python 3.10+"
  exit 1
fi

PIP="$PYTHON -m pip"

echo "============================================"
echo "  harness-cook 一键安装"
echo "============================================"
echo "Python: $PYTHON"
echo ""

# ── Step 1: 安装核心包 ─────────────────────────────
echo "📦 [Step 1/3] 安装 harness 核心包..."
$PIP install -e "$CORE_PKG" --quiet 2>&1 && echo "  ✅ 核心包安装成功" || {
  echo "  ❌ 核心包安装失败"; exit 1
}

# ── Step 2: 安装 CLI 包（注册 harness 命令） ──────
echo "🔧 [Step 2/3] 安装 harness CLI..."
$PIP install -e "$CLI_PKG" --quiet 2>&1 && echo "  ✅ CLI 包安装成功（harness 命令已注册）" || {
  echo "  ❌ CLI 包安装失败"; exit 1
}

# ── Step 3: 验证 ────────────────────────────────────
echo "🔍 [Step 3/3] 验证安装..."
if command -v harness &>/dev/null; then
  VERSION=$(harness version 2>/dev/null || echo "unknown")
  echo "  ✅ harness 命令可用 ($VERSION)"
else
  echo "  ⚠️ harness 命令未在 PATH 中，尝试直接运行..."
  $PYTHON -m harness_cli version 2>/dev/null && echo "  ✅ python -m harness_cli 可用" || {
    echo "  ❌ 安装验证失败"; exit 1
  }
fi

echo ""
echo "============================================"
echo "  🎉 安装完成！"
echo "============================================"
echo ""
echo "下一步："
echo "  harness activate    # 一键激活（配置 MCP + hooks + skills）"

#!/usr/bin/env python3
"""
harness-cook CLI 运行器 — 解决 packages/cli/harness/ 包名冲突

由于 packages/cli/ 下有 harness/__init__.py shim 会导致与 core/harness/ 的导入冲突,
本脚本使用以下策略:
  1. 只把 packages/core/ 加入 sys.path（使 harness 包从 core 正确导入）
  2. 临时把 packages/cli/ 加入 sys.path（使 cli_commands 包可导入）
  3. 在 cli_commands 导入完成后立即移除 cli 路径
  4. 直接 exec() 执行 harness_cli.py 内容（避免模块缓存冲突）
"""

import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CORE_DIR = str(PROJECT_ROOT / "packages" / "core")
CLI_DIR = str(PROJECT_ROOT / "packages" / "cli")
CLI_FILE = CLI_DIR + "/harness_cli.py"

# 把 core 加入 sys.path（确保 harness 包从 core 正确导入）
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

# 临时把 cli 加入 sys.path（使 cli_commands 包可导入）
# 注意: 这里 harness 包已经从 core 加载完毕（因为 __version__ 已导入）
# 所以后续 cli/harness/__init__.py 不会再被 Python 发现（模块缓存）
if CLI_DIR not in sys.path:
    sys.path.insert(0, CLI_DIR)

# 预加载 cli_commands 子命令模块（避免运行时找不到）
import cli_commands

# 移除 CLI_DIR（避免后续可能的冲突）
while CLI_DIR in sys.path:
    sys.path.remove(CLI_DIR)

# 直接读取并执行 harness_cli.py（避免 import harness_cli 触发 cli/harness/__init__.py）
with open(CLI_FILE, "r") as f:
    cli_code = f.read()

if __name__ == "__main__":
    exec(cli_code)
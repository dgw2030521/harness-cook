#!/usr/bin/env python3
"""
harness update — 一键更新 harness-cook 源码和依赖

用法:
  harness update [--verbose] [--skip-install]

功能:
  1. 定位 harness-cook 源码目录
  2. 检查工作区是否有未提交修改
  3. git pull 拉取最新代码
  4. pip install -e 重新安装核心包和 CLI 包
  5. 验证更新结果（显示旧版本 → 新版本）

退出码: 0 = 更新成功, 1 = 失败, 2 = 无需更新
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _get_harness_root() -> str:
    """获取 harness-cook 源码目录

    解析优先级：
      1. 环境变量 HARNESS_COOK_ROOT
      2. 从脚本位置推导（__file__ → cli_commands/ → cli/ → packages/ → harness-cook/）
      3. 降级：当前工作目录
    """
    env_root = os.environ.get("HARNESS_COOK_ROOT", "")
    if env_root and Path(env_root).exists():
        return env_root

    # 从脚本位置推导
    script_path = Path(__file__).resolve()
    # __file__ = .../harness-cook/packages/cli/cli_commands/update.py
    # parent(1) = cli_commands/  parent(2) = cli/  parent(3) = packages/  parent(4) = harness-cook/
    candidate = script_path.parent.parent.parent.parent
    if (candidate / "packages" / "core").exists():
        return str(candidate)

    # 降级
    return str(candidate)


def _check_uncommitted_changes(root: str) -> list[str] | None:
    """检查 git 工作区是否有未提交修改

    返回值:
      list[str] — 修改文件路径列表（空列表表示工作区干净）
      None — git 命令失败（可能不是 git 仓库）
    """
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    if not result.stdout.strip():
        return []

    # 解析 porcelain 输出：每行 "XY filename" 或 "X filename"
    # XY 是 2 字符状态码（staged + unstaged），X/Y 可为空格表示无变化
    # 格式: "M file" (staged modified) 或 " M file" (unstaged modified)
    # 两种格式中，文件名从第 3 字符开始（2 字符状态 + 1 空格分隔）
    lines = result.stdout.strip().splitlines()
    filenames = []
    for line in lines:
        # porcelain 格式: 前 2 字符是 XY 状态码，第 3 字符是空格分隔符
        # 文件名从 index 3 开始；但某些 git 版本只输出 1 字符状态码
        # 安全做法：跳过前 2 字符状态码 + 1 空格，取 line[3:]
        # 若第 3 字符不是空格（紧凑格式），则 line[2:] 也不对
        # 最稳妥：用 split(maxsplit=1) 拆分状态码和文件名
        parts = line.lstrip().split(maxsplit=1)
        if len(parts) == 2:
            filenames.append(parts[1])
        elif len(parts) == 1:
            filenames.append(parts[0])
    return filenames


def _get_current_branch(root: str) -> str:
    """获取当前 git 分支名"""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return "HEAD"
    return result.stdout.strip()


def _git_pull(root: str, branch: str, verbose: bool) -> tuple[bool, bool]:
    """执行 git pull origin <branch>

    返回 (success, has_changes):
      success: git pull 命令是否成功
      has_changes: 是否有新代码拉取下来
    """
    result = subprocess.run(
        ["git", "pull", "origin", branch],
        cwd=root,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        if verbose:
            print(result.stderr, file=sys.stderr)
        print(f"  ❌ git pull 失败: {result.stderr.strip()}", file=sys.stderr)
        return (False, False)

    output = result.stdout.strip()
    if verbose and output:
        print(output)

    # 判断是否有变化："Already up to date" 表示无变化
    has_changes = "Already up to date" not in output

    if has_changes:
        print(f"  ✅ 已拉取最新代码 (origin/{branch})")
    else:
        print(f"  ℹ️ 本地已是最新版本 (origin/{branch})")

    return (True, has_changes)


def _pip_install(root: str, verbose: bool) -> bool:
    """重新安装 harness 核心包和 CLI 包

    返回 success（是否安装成功）
    """
    core_path = str(Path(root) / "packages" / "core")
    cli_path = str(Path(root) / "packages" / "cli")

    python = os.environ.get("PYTHON", "")
    if not python:
        import shutil
        python = shutil.which("python3") or shutil.which("python") or "python"

    pip_cmd = [python, "-m", "pip", "install", "-e"]

    # 安装核心包
    result_core = subprocess.run(
        pip_cmd + [core_path],
        capture_output=True,
        text=True,
    )
    if result_core.returncode != 0:
        if verbose:
            print(result_core.stderr, file=sys.stderr)
        print(f"  ❌ 核心包安装失败: {result_core.stderr.strip()}", file=sys.stderr)
        return False
    print("  ✅ 核心包安装成功")

    # 安装 CLI 包
    result_cli = subprocess.run(
        pip_cmd + [cli_path],
        capture_output=True,
        text=True,
    )
    if result_cli.returncode != 0:
        if verbose:
            print(result_cli.stderr, file=sys.stderr)
        print(f"  ❌ CLI 包安装失败: {result_cli.stderr.strip()}", file=sys.stderr)
        return False
    print("  ✅ CLI 包安装成功")

    return True


def add_update_args(subparsers):
    """注册 harness update 子命令"""
    update_parser = subparsers.add_parser(
        "update",
        help="更新 harness-cook 源码和依赖",
        description="一键更新 harness-cook：git pull 拉取最新代码 + pip install -e 重新安装依赖。",
    )
    update_parser.add_argument(
        "--verbose",
        action="store_true",
        help="显示 git/pip 完整输出",
    )
    update_parser.add_argument(
        "--skip-install",
        action="store_true",
        help="只 git pull，跳过 pip install -e",
    )


def cmd_update(args) -> int:
    """harness update 命令入口

    返回退出码: 0=成功, 1=失败, 2=无需更新
    """
    verbose = getattr(args, "verbose", False) or False
    skip_install = getattr(args, "skip_install", False) or False

    # ── Step 1: 定位源码目录 ──────────────────────────
    print("🔄 [Step 1/5] 定位源码目录...")
    root = _get_harness_root()

    # 验证目录存在
    if not Path(root).exists():
        print(f"  ❌ 源码目录不存在: {root}")
        print("  提示: 请重新安装 harness-cook (git clone + install.sh)")
        return 1

    # 验证是 git 仓库
    git_dir = Path(root) / ".git"
    if not git_dir.exists():
        print(f"  ❌ 不是 git 仓库: {root}")
        print("  提示: 请重新 clone harness-cook")
        return 1

    print(f"  ✅ 源码目录: {root}")

    # ── Step 2: 检查未提交修改 ──────────────────────────
    print("🔄 [Step 2/5] 检查工作区状态...")
    changed_files = _check_uncommitted_changes(root)

    if changed_files is None:
        print("  ❌ 无法检查工作区状态")
        return 1

    if changed_files:
        print("  ❌ 工作区有未提交修改:")
        for f in changed_files[:10]:
            print(f"     {f}")
        if len(changed_files) > 10:
            print(f"     ... 共 {len(changed_files)} 个文件")
        print("  提示: 请先提交或撤销修改后再更新")
        return 1

    print("  ✅ 工作区干净，可以安全更新")

    # ── Step 3: git pull ─────────────────────────────────
    print("🔄 [Step 3/5] 拉取最新代码...")
    branch = _get_current_branch(root)
    print(f"  当前分支: {branch}")

    # 记录旧版本号
    old_version = ""
    try:
        result_ver = subprocess.run(
            ["harness", "version"],
            capture_output=True,
            text=True,
        )
        old_version = result_ver.stdout.strip()
    except Exception:
        old_version = "unknown"

    success, has_changes = _git_pull(root, branch, verbose)

    if not success:
        return 1

    if not has_changes:
        print("🔄 [Step 5/5] 验证更新...")
        print(f"  ℹ️ 当前已是最新版本 ({old_version})")
        return 2

    # ── Step 4: pip install -e ───────────────────────────
    if not skip_install:
        print("🔄 [Step 4/5] 重新安装依赖...")
        install_ok = _pip_install(root, verbose)
        if not install_ok:
            return 1
    else:
        print("🔄 [Step 4/5] 跳过依赖安装 (--skip-install)")

    # ── Step 5: 输出结果 ────────────────────────────────
    print("🔄 [Step 5/5] 验证更新...")
    new_version = ""
    try:
        result_ver = subprocess.run(
            ["harness", "version"],
            capture_output=True,
            text=True,
        )
        new_version = result_ver.stdout.strip()
    except Exception:
        new_version = "unknown"

    if old_version != new_version and old_version != "unknown":
        print(f"  ✅ {old_version} → {new_version}")
    else:
        print(f"  ✅ {new_version}")

    print("  🎉 更新完成！")
    return 0

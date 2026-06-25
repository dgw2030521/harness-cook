#!/usr/bin/env python3
"""
harness dashboard — 启动可视化界面

启动 FastAPI Dashboard 服务，提供 Web UI 查看：
- 审计统计和历史
- Skill 执行状态和插槽分配
- Profile 配置和切换
- Gate 检查历史
- 事件流
- 合规扫描

用法:
  harness dashboard                     # 启动在 localhost:8765
  harness dashboard --port 9000         # 指定端口
  harness dashboard --host 0.0.0.0      # 允许外部访问
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _get_harness_root() -> str:
    """获取 harness-cook 安装目录"""
    env_root = os.environ.get("HARNESS_COOK_ROOT", "")
    if env_root and Path(env_root).exists():
        return env_root
    script_path = Path(__file__).resolve()
    return str(script_path.parent.parent.parent.parent)


def _detect_project_dir() -> str | None:
    """检测当前项目目录（含项目级 .harness 的目录）。

    优先级：
      1. HARNESS_PROJECT_DIR 环境变量（显式指定）
      2. CLAUDE_PROJECT_DIR 环境变量（Claude Code 场景）
      3. 从 cwd 向上查找含 .harness/ 的目录（排除 home 目录）

    关键设计：
      - 排除 home 目录的 .harness（~/.harness 是全局配置，不是项目级）
      - 没有 .harness/ 目录 → 返回 None（dashboard 依赖 .harness 数据，无数据则拒绝启动）

    Returns:
        项目根目录路径，或 None（当前目录没有项目级 .harness）
    """
    home_dir = Path.home().resolve()

    # 1. HARNESS_PROJECT_DIR 环境变量（显式指定）
    cli_dir = os.environ.get("HARNESS_PROJECT_DIR")
    if cli_dir and Path(cli_dir).exists():
        harness_dir = Path(cli_dir) / ".harness"
        if harness_dir.is_dir() and Path(cli_dir).resolve() != home_dir:
            return cli_dir
        # 显式指定了但没有 .harness 或是 home 目录 → 也返回 None
        return None

    # 2. CLAUDE_PROJECT_DIR 环境变量（Claude Code 场景）
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_dir and Path(env_dir).exists():
        harness_dir = Path(env_dir) / ".harness"
        if harness_dir.is_dir() and Path(env_dir).resolve() != home_dir:
            return env_dir
        return None

    # 3. 从 cwd 向上查找含 .harness/ 的目录（排除 home 目录）
    current = Path.cwd().resolve()
    for parent in [current] + list(current.parents):
        if parent == home_dir:
            break  # 到达 home 目录就停止，不匹配 ~/.harness
        if (parent / ".harness").is_dir():
            return str(parent)

    # 没有找到项目级 .harness → 返回 None
    return None


def cmd_dashboard(args) -> int:
    """启动 Dashboard 服务——仅在有 .harness 的项目目录下才能启动"""
    harness_root = _get_harness_root()
    dashboard_dir = Path(harness_root) / "packages" / "dashboard"
    app_path = dashboard_dir / "app.py"

    if not app_path.exists():
        print("❌ Dashboard 未找到: {}".format(app_path))
        print("💡 请确保 packages/dashboard/app.py 存在")
        return 1

    # ── 检测项目目录 ──
    # Dashboard 所有数据（审计、Profile、知识库等）都来自 .harness/ 目录。
    # 没有 .harness → 没有数据 → 没有可展示的内容 → 拒绝启动。
    project_dir = _detect_project_dir()
    if project_dir is None:
        print("=" * 60)
        print("  ❌ 当前目录没有项目级 .harness 配置")
        print("=" * 60)
        print()
        print("Dashboard 所有数据来自项目的 .harness/ 目录：")
        print("  .harness/audit/   — 审计记录")
        print("  .harness/profiles/ — 治理配置")
        print("  .harness/env       — 运行时配置")
        print()
        print("没有 .harness 目录，Dashboard 无数据可展示。")
        print()
        print("请先在项目目录下执行：")
        print("  harness activate")
        print()
        print("或切换到已激活的项目目录：")
        print("  cd /path/to/your/project && harness dashboard")
        print("=" * 60)
        return 1

    project_name = Path(project_dir).name

    # 设置环境变量
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(harness_root) / "packages" / "core")
    env["HARNESS_PROJECT_DIR"] = project_dir   # ← 传入项目目录给 Dashboard app

    print("=" * 60)
    print("  harness-cook Dashboard")
    print("=" * 60)
    print(f"  项目: {project_name} ({project_dir})")
    print(f"启动地址: http://{args.host}:{args.port}")
    print("按 Ctrl+C 停止服务")
    print("=" * 60)
    print()

    try:
        # 构建命令
        cmd = [
            sys.executable, "-m", "uvicorn",
            "app:app",
            "--host", args.host,
            "--port", str(args.port),
        ]
        if args.reload:
            cmd.append("--reload")

        # 启动 uvicorn
        result = subprocess.run(
            cmd,
            cwd=str(dashboard_dir),
            env=env,
        )
        return result.returncode
    except KeyboardInterrupt:
        print("\n👋 Dashboard 已停止")
        return 0
    except Exception as e:
        print(f"❌ 启动失败: {e}")
        return 1


def add_dashboard_args(subparsers):
    """注册 dashboard 子命令"""
    parser = subparsers.add_parser(
        "dashboard",
        help="启动可视化 Dashboard",
        description="启动 Web UI 查看审计、Skills、Profile、合规等信息",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="监听地址（默认 127.0.0.1）",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8765,
        help="监听端口（默认 8765）",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="开发模式：文件变更时自动重载",
    )

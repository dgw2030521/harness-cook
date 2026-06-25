#!/usr/bin/env python3
"""
harness docs — 启动 VitePress 文档服务器

启动 harness-cook 文档站点，提供：
- 指南、教程、Demo 等文档浏览
- 本地开发热重载
- Markdown + VitePress 交互式文档

用法:
  harness docs                       # 启动在 localhost:5173
  harness docs --port 3000           # 指定端口
  harness docs --open                # 自动打开浏览器
  harness docs --build               # 构建静态站点（不启动 dev server）
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# ── 包管理器检测 ────────────────────────────────────────────
# lock 文件 → 包管理器的映射（优先级从高到低）
_LOCK_FILE_MAP = {
    "pnpm-lock.yaml": "pnpm",
    "yarn.lock": "yarn",
    "package-lock.json": "npm",
    "bun.lockb": "bun",
}

# 包管理器 → 常见安装位置的回退路径
_PKG_BIN_FALLBACKS = {
    "pnpm": [
        "/opt/homebrew/bin/pnpm",
        "/usr/local/bin/pnpm",
        "/usr/bin/pnpm",
        os.path.expanduser("~/.local/share/pnpm/pnpm"),
    ],
    "npm": [
        "/opt/homebrew/bin/npm",
        "/usr/local/bin/npm",
        "/usr/bin/npm",
        os.path.expanduser("~/.local/bin/npm"),
    ],
    "yarn": [
        "/opt/homebrew/bin/yarn",
        "/usr/local/bin/yarn",
        "/usr/bin/yarn",
    ],
    "bun": [
        "/opt/homebrew/bin/bun",
        "/usr/local/bin/bun",
        os.path.expanduser("~/.bun/bin/bun"),
    ],
}


def _find_bin(name: str) -> str:
    """查找可执行文件：PATH 优先，回退到常见安装位置"""
    found = shutil.which(name)
    if found:
        return found
    for candidate in _PKG_BIN_FALLBACKS.get(name, []):
        if Path(candidate).exists():
            return candidate
    return ""


def _detect_pkg_manager(harness_root: str) -> tuple:
    """根据项目 lock 文件检测包管理器

    Returns:
        (pkg_name, bin_path)
        - ("pnpm", "/usr/local/bin/pnpm") — 找到了
        - ("", "") — 找不到任何可用的包管理器
    """
    root = Path(harness_root)

    # 1. 按优先级扫描 lock 文件，确定项目用哪个包管理器
    for lock_file, pkg_name in _LOCK_FILE_MAP.items():
        if (root / lock_file).exists():
            bin_path = _find_bin(pkg_name)
            if bin_path:
                return pkg_name, bin_path
            # lock 文件存在但对应的包管理器不可用 → 继续往下找
            # 不立即报错，因为用户可能装了另一个

    # 2. 没有 lock 文件 → 按常见可用性顺序尝试
    for pkg_name in ["pnpm", "npm", "yarn", "bun"]:
        bin_path = _find_bin(pkg_name)
        if bin_path:
            return pkg_name, bin_path

    # 3. 什么都找不到
    return "", ""


def _get_harness_root() -> str:
    """获取 harness-cook 安装目录"""
    env_root = os.environ.get("HARNESS_COOK_ROOT", "")
    if env_root and Path(env_root).exists():
        return env_root
    script_path = Path(__file__).resolve()
    return str(script_path.parent.parent.parent.parent)


def _ensure_deps_installed(harness_root: str) -> bool:
    """确保 VitePress 依赖已安装，未安装则用项目对应的包管理器自动安装

    Returns:
        True = 依赖就绪，False = 安装失败或包管理器不可用
    """
    vitepress_pkg = Path(harness_root) / "node_modules" / "vitepress" / "package.json"
    if vitepress_pkg.exists():
        return True

    # ── 依赖缺失，自动安装 ──
    pkg_name, bin_path = _detect_pkg_manager(harness_root)
    if not bin_path:
        print("❌ 未找到可用的包管理器 (pnpm/npm/yarn/bun)")
        print("💡 请安装 Node.js: https://nodejs.org — npm 会随 Node.js 一起安装")
        if (Path(harness_root) / "pnpm-lock.yaml").exists():
            print("💡 本项目使用 pnpm，安装方式: npm install -g pnpm")
        return False

    package_json = Path(harness_root) / "package.json"
    if not package_json.exists():
        print("❌ package.json 未找到: {}".format(package_json))
        return False

    print("📦 VitePress 依赖未安装，正在自动安装...")
    print("   {} install".format(bin_path))
    print()

    try:
        result = subprocess.run(
            [bin_path, "install"],
            cwd=harness_root,
        )
        if result.returncode != 0:
            print("❌ 依赖安装失败 (退出码 {})".format(result.returncode))
            return False

        # 安装后再验证 vitepress 确实到位了
        if vitepress_pkg.exists():
            print("✅ 依赖安装完成")
            return True
        else:
            print("❌ 安装完成但 vitepress 仍未就位，请检查 {} install 输出".format(pkg_name))
            return False
    except KeyboardInterrupt:
        print("\n⚠️ 安装被中断，依赖可能不完整")
        return False
    except Exception as e:
        print("❌ 安装过程出错: {}".format(e))
        return False


def cmd_docs(args) -> int:
    """启动 VitePress 文档服务"""
    harness_root = _get_harness_root()

    # 检查文档目录
    docs_dir = Path(harness_root) / "playground" / "docs"
    if not docs_dir.exists():
        print("❌ 文档目录未找到: {}".format(docs_dir))
        return 1

    # 确保依赖已安装（缺失则自动安装）
    if not _ensure_deps_installed(harness_root):
        return 1

    # _ensure_deps_installed 通过后 vitepress 必然可用
    vitepress_bin = Path(harness_root) / "node_modules" / ".bin" / "vitepress"

    if args.build:
        print("=" * 60)
        print("  harness-cook Docs — 构建静态站点")
        print("=" * 60)
        print(f"输出目录: {docs_dir}/.vitepress/dist")
        print("=" * 60)
        print()
        cmd = [str(vitepress_bin), "build", str(docs_dir)]
    else:
        print("=" * 60)
        print("  harness-cook Docs")
        print("=" * 60)
        print(f"启动地址: http://localhost:{args.port}")
        print("按 Ctrl+C 停止服务")
        print("=" * 60)
        print()
        cmd = [str(vitepress_bin), "dev", str(docs_dir), "--port", str(args.port)]
        if args.open:
            cmd.append("--open")

    try:
        result = subprocess.run(cmd, cwd=harness_root)
        return result.returncode
    except KeyboardInterrupt:
        print("\n👋 文档服务已停止")
        return 0
    except Exception as e:
        print("❌ 启动失败: {}".format(e))
        return 1


def add_docs_args(subparsers):
    """注册 docs 子命令"""
    parser = subparsers.add_parser(
        "docs",
        help="启动 VitePress 文档站点",
        description="启动 harness-cook 文档站点，浏览指南、教程、Demo 等文档",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=5173,
        help="开发服务器端口（默认 5173）",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="启动后自动打开浏览器",
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="构建静态站点（不启动 dev server）",
    )

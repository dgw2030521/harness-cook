#!/usr/bin/env python3
"""
lint-check hook — 代码变更后自动检查代码质量

此 hook 在代码文件变更后自动运行 lint 工具，
确保代码符合项目规范。

触发时机：PostToolUse（Write/Edit 后）
"""

import subprocess
import sys
import os
import json
from pathlib import Path


def detect_lint_command(changed_file: str) -> str:
    """根据文件类型检测 lint 命令

    智能选择合适的 lint 工具：
    - Python → ruff/flake8/black
    - JavaScript/TypeScript → eslint/prettier
    - Go → gofmt/golint
    """
    file_ext = Path(changed_file).suffix.lower()

    if file_ext == ".py":
        # 优先使用 ruff，回退到 flake8
        if subprocess.run(["which", "ruff"], capture_output=True).returncode == 0:
            return f"ruff check {changed_file}"
        elif subprocess.run(["which", "flake8"], capture_output=True).returncode == 0:
            return f"flake8 {changed_file}"
        else:
            return ""

    elif file_ext in {".js", ".jsx", ".ts", ".tsx"}:
        # 使用 eslint
        if Path("node_modules/.bin/eslint").exists():
            return f"npx eslint {changed_file}"
        else:
            return ""

    elif file_ext == ".go":
        return f"gofmt -l {changed_file}"

    else:
        return ""


def run_lint(lint_command: str, timeout: int = 30) -> tuple[bool, str]:
    """执行 lint 命令

    Returns:
        (success, output): 是否通过及输出
    """
    try:
        result = subprocess.run(
            lint_command.split(),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.getcwd()
        )

        output = result.stdout + result.stderr
        success = result.returncode == 0

        return success, output

    except subprocess.TimeoutExpired:
        return False, f"Lint 超时（{timeout}秒）"
    except Exception as e:
        return False, f"执行失败: {str(e)}"


def main():
    """主函数 — Claude Code hook 入口"""
    try:
        # 从 stdin 读取 hook 输入
        hook_input = json.loads(sys.stdin.read())
        tool_name = hook_input.get("tool_name", "")
        tool_input = hook_input.get("tool_input", {})

        # 只在文件写入/编辑后触发
        if tool_name not in {"Write", "Edit", "Patch"}:
            sys.exit(0)

        # 获取变更的文件路径
        changed_file = tool_input.get("file_path", "") or tool_input.get("path", "")
        if not changed_file:
            sys.exit(0)

        # 检测 lint 命令
        lint_command = detect_lint_command(changed_file)
        if not lint_command:
            # 没有合适的 lint 工具，跳过
            sys.exit(0)

        # 执行 lint
        print(f"🔍 检查代码质量: {changed_file}", file=sys.stderr)
        print(f"   运行: {lint_command}", file=sys.stderr)

        success, output = run_lint(lint_command)

        if success:
            print(f"✅ 代码质量检查通过", file=sys.stderr)
        else:
            print(f"⚠️  发现代码质量问题", file=sys.stderr)
            # 输出问题详情
            lines = output.strip().split('\n')
            for line in lines[:10]:  # 最多显示10行
                if line.strip():
                    print(f"   {line}", file=sys.stderr)
            if len(lines) > 10:
                print(f"   ... 还有 {len(lines) - 10} 个问题", file=sys.stderr)

        sys.exit(0)

    except Exception as e:
        print(f"⚠️  Hook 执行异常: {str(e)}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
codegraph-sync hook — 代码变更后自动同步 CodeGraph

此 hook 在代码文件变更（Write/Edit）后自动执行 `codegraph sync`，
保持代码图谱与源代码同步。

触发时机：PostToolUse（工具使用后）
适用工具：Write, Edit
"""

import subprocess
import sys
import os
from pathlib import Path


def should_sync(tool_name: str) -> bool:
    """判断是否需要同步

    只在代码文件变更工具后同步：
    - Write: 写入文件
    - Edit: 编辑文件
    - Patch: 补丁修改

    不同步的工具：
    - Read, Grep, Glob 等只读操作
    - Bash 命令（除非明确修改代码）
    """
    code_change_tools = {"Write", "Edit", "Patch", "write_file", "edit_file"}
    return tool_name in code_change_tools


def run_codegraph_sync() -> tuple[bool, str]:
    """执行 codegraph sync 命令

    Returns:
        (success, message): 是否成功及消息
    """
    try:
        # 尝试执行 codegraph sync
        result = subprocess.run(
            ["codegraph", "sync"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=os.getcwd()
        )

        if result.returncode == 0:
            return True, "CodeGraph 同步成功"
        else:
            # codegraph 命令失败，可能是未安装或未初始化
            error_msg = result.stderr.strip() or result.stdout.strip()
            return False, f"CodeGraph 同步失败: {error_msg}"

    except FileNotFoundError:
        return False, "codegraph 命令未找到，请先安装: npm install -g @codegraph/cli"
    except subprocess.TimeoutExpired:
        return False, "CodeGraph 同步超时（30秒）"
    except Exception as e:
        return False, f"执行失败: {str(e)}"


def main():
    """主函数 — Claude Code hook 入口

    Claude Code 通过 stdin 传递 JSON，包含：
    {
        "tool_name": "Write",
        "tool_input": {...},
        "tool_output": {...}
    }
    """
    import json

    try:
        # 从 stdin 读取 hook 输入
        hook_input = json.loads(sys.stdin.read())
        tool_name = hook_input.get("tool_name", "")

        # 检查是否需要同步
        if not should_sync(tool_name):
            # 不需要操作，直接退出
            sys.exit(0)

        # 执行同步
        success, message = run_codegraph_sync()

        if success:
            # 成功时输出提示（可选，Claude Code 会显示）
            print(f"✅ {message}", file=sys.stderr)
            sys.exit(0)
        else:
            # 失败时输出警告（不阻止主流程）
            print(f"⚠️  {message}", file=sys.stderr)
            sys.exit(0)  # 仍然返回 0，不阻止主流程

    except json.JSONDecodeError:
        # 无法解析输入，静默退出
        sys.exit(0)
    except Exception as e:
        # 其他异常，输出警告但不阻止
        print(f"⚠️  Hook 执行异常: {str(e)}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()

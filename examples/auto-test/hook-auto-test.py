#!/usr/bin/env python3
"""
auto-test hook — 代码变更后自动运行测试

此 hook 在代码文件变更后自动执行相关测试，
快速验证修改是否破坏现有功能。

触发时机：PostToolUse（Write/Edit 后）
"""

import subprocess
import sys
import os
import json
from pathlib import Path


def detect_test_command(changed_file: str) -> str:
    """根据变更文件检测测试命令

    智能判断应该运行哪些测试：
    - Python 文件 → pytest
    - JavaScript/TypeScript → npm test
    - Go 文件 → go test
    """
    file_ext = Path(changed_file).suffix.lower()

    if file_ext in {".py"}:
        return "python3 -m pytest -v"
    elif file_ext in {".js", ".jsx", ".ts", ".tsx"}:
        return "npm test"
    elif file_ext in {".go"}:
        return "go test ./..."
    elif file_ext in {".java", ".kt"}:
        return "./gradlew test"
    else:
        return ""


def run_tests(test_command: str, timeout: int = 60) -> tuple[bool, str]:
    """执行测试命令

    Returns:
        (success, output): 是否成功及输出
    """
    try:
        result = subprocess.run(
            test_command.split(),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.getcwd()
        )

        output = result.stdout + result.stderr
        success = result.returncode == 0

        return success, output

    except subprocess.TimeoutExpired:
        return False, f"测试超时（{timeout}秒）"
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

        # 检测测试命令
        test_command = detect_test_command(changed_file)
        if not test_command:
            # 不支持的文件类型，跳过
            sys.exit(0)

        # 执行测试
        print(f"🧪 检测到代码变更: {changed_file}", file=sys.stderr)
        print(f"   运行测试: {test_command}", file=sys.stderr)

        success, output = run_tests(test_command)

        if success:
            print(f"✅ 测试通过", file=sys.stderr)
        else:
            print(f"❌ 测试失败", file=sys.stderr)
            # 输出最后几行错误信息
            lines = output.strip().split('\n')
            for line in lines[-5:]:
                print(f"   {line}", file=sys.stderr)

        sys.exit(0)

    except Exception as e:
        print(f"⚠️  Hook 执行异常: {str(e)}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()

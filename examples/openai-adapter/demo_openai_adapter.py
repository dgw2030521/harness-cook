#!/usr/bin/env python3
"""
OpenAI 适配器使用示例

展示如何将 Profile 配置翻译为 OpenAI function calling 格式
"""

import sys
import json
from pathlib import Path

# 添加 harness-cook 到 Python 路径
harness_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(harness_root / "packages" / "core"))

from harness.adapters.openai import OpenAIAdapter
from harness.types import ProfileConfig, GateMode


def demo_basic_usage():
    """基础用法示例"""
    print("=" * 60)
    print("OpenAI 适配器 - 基础用法")
    print("=" * 60)

    # 1. 创建 OpenAI 适配器
    adapter = OpenAIAdapter()
    print(f"\n✓ 创建适配器: {adapter.name}")

    # 2. 定义 hooks 配置
    hooks_config = {
        "session_start": [
            {"type": "script", "command": "python3 scripts/init.py"},
        ],
        "pre_execute": [
            {"type": "skill", "skill_id": "validate-input"},
        ],
        "post_execute": [
            {"type": "script", "command": "python3 scripts/cleanup.py"},
            {"type": "skill", "skill_id": "auto-audit"},
        ],
    }

    print("\n✓ Hooks 配置:")
    print(json.dumps(hooks_config, indent=2))

    # 3. 翻译为 OpenAI function calling 格式
    functions_config = adapter.translate_hooks(hooks_config)

    print("\n✓ 翻译结果 (OpenAI function calling 格式):")
    print(json.dumps(functions_config, indent=2))

    return functions_config


def demo_merge_settings():
    """合并配置示例"""
    print("\n" + "=" * 60)
    print("OpenAI 适配器 - 合并配置")
    print("=" * 60)

    adapter = OpenAIAdapter()

    # 1. 现有配置
    existing_config = {
        "model": "gpt-4",
        "temperature": 0.7,
        "max_tokens": 1000,
    }

    print("\n✓ 现有配置:")
    print(json.dumps(existing_config, indent=2))

    # 2. 新的 functions
    new_hooks = {
        "functions": [
            {
                "name": "hook_session_start",
                "description": "Initialize session",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                    },
                    "required": ["command"],
                },
            },
        ],
    }

    print("\n✓ 新的 functions:")
    print(json.dumps(new_hooks, indent=2))

    # 3. 合并
    merged_config = adapter.merge_settings(existing_config, new_hooks)

    print("\n✓ 合并后的配置:")
    print(json.dumps(merged_config, indent=2))

    return merged_config


def demo_deduplication():
    """去重示例"""
    print("\n" + "=" * 60)
    print("OpenAI 适配器 - Functions 去重")
    print("=" * 60)

    adapter = OpenAIAdapter()

    # 1. 现有配置（已有某些 functions）
    existing_config = {
        "functions": [
            {
                "name": "hook_session_start",
                "description": "Old version",
            },
            {
                "name": "hook_post_execute",
                "description": "Existing function",
            },
        ],
    }

    print("\n✓ 现有配置 (已有 2 个 functions):")
    print(json.dumps(existing_config, indent=2))

    # 2. 新的 functions（包含重复的 hook_session_start）
    new_hooks = {
        "functions": [
            {
                "name": "hook_session_start",  # 重复
                "description": "New version",
            },
            {
                "name": "hook_pre_execute",  # 新增
                "description": "New function",
            },
        ],
    }

    print("\n✓ 新的 functions (包含重复):")
    print(json.dumps(new_hooks, indent=2))

    # 3. 合并（自动去重）
    merged_config = adapter.merge_settings(existing_config, new_hooks)

    print("\n✓ 合并后的配置 (自动去重):")
    print(json.dumps(merged_config, indent=2))
    print(f"\n✓ Functions 数量: {len(merged_config['functions'])} (去重后)")

    return merged_config


def main():
    """主函数"""
    print("\n🚀 OpenAI 适配器使用示例\n")

    # 运行所有示例
    demo_basic_usage()
    demo_merge_settings()
    demo_deduplication()

    print("\n" + "=" * 60)
    print("✅ 所有示例运行完成")
    print("=" * 60)
    print("\n💡 提示:")
    print("  - OpenAI 适配器将 hooks 翻译为 function calling 格式")
    print("  - 可以使用 merge_settings 合并到现有配置")
    print("  - 合并时会自动去重相同的 function")
    print("\n📚 更多信息请查看 examples/openai-adapter/README.md")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Hermes 适配器使用示例

展示如何将 Profile 配置翻译为 Hermes YAML 配置格式
"""

import sys
import yaml
from pathlib import Path

# 添加 harness-cook 到 Python 路径
harness_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(harness_root / "packages" / "core"))

from harness.adapters.hermes import HermesAdapter
from harness.types import ProfileConfig, GateMode


def demo_basic_usage():
    """基础用法示例"""
    print("=" * 60)
    print("Hermes 适配器 - 基础用法")
    print("=" * 60)

    # 1. 创建 Hermes 适配器
    adapter = HermesAdapter()
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
    print(yaml.dump(hooks_config, allow_unicode=True, default_flow_style=False))

    # 3. 翻译为 Hermes YAML 配置
    hermes_config = adapter.translate_hooks(hooks_config)

    print("✓ 翻译结果 (Hermes YAML 配置):")
    print(yaml.dump(hermes_config, allow_unicode=True, default_flow_style=False))

    return hermes_config


def demo_export_yaml():
    """导出 YAML 示例"""
    print("\n" + "=" * 60)
    print("Hermes 适配器 - 导出 YAML")
    print("=" * 60)

    adapter = HermesAdapter()

    # 创建配置
    hermes_config = {
        "version": "1.0",
        "approvals": {
            "mode": "smart",
            "cron_mode": "deny",
        },
        "security": {
            "redact_secrets": True,
            "tirith_enabled": True,
        },
        "skills": [
            {
                "name": "hook_session_start",
                "description": "Initialize session",
                "trigger": "on_session_start",
                "command": "python3 init.py",
            },
            {
                "name": "skill_auto-audit",
                "description": "Auto audit after task",
                "trigger": "after_task",
                "skill_id": "auto-audit",
            },
        ],
        "cron": [
            {
                "schedule": "0 9 * * *",
                "name": "daily-health-check",
                "command": "python3 health_check.py",
            },
        ],
    }

    print("\n✓ 配置内容:")
    print(yaml.dump(hermes_config, allow_unicode=True, default_flow_style=False))

    # 导出到临时文件
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / ".hermes" / "config.yaml"
        adapter.export_yaml(hermes_config, str(output_path))

        print(f"\n✓ 配置已导出到: {output_path}")
        print(f"✓ 文件大小: {output_path.stat().st_size} bytes")


def demo_merge_settings():
    """合并配置示例"""
    print("\n" + "=" * 60)
    print("Hermes 适配器 - 合并配置")
    print("=" * 60)

    adapter = HermesAdapter()

    # 1. 现有配置
    existing_config = {
        "version": "1.0",
        "approvals": {
            "mode": "strict",
        },
        "skills": [
            {
                "name": "existing_skill",
                "trigger": "before_task",
            },
        ],
    }

    print("\n✓ 现有配置:")
    print(yaml.dump(existing_config, allow_unicode=True, default_flow_style=False))

    # 2. 新的配置
    new_hooks = {
        "approvals": {
            "mode": "smart",  # 覆盖现有的 strict
            "cron_mode": "deny",
        },
        "skills": [
            {
                "name": "hook_session_start",
                "trigger": "on_session_start",
            },
            {
                "name": "existing_skill",  # 重复
                "trigger": "before_task",
            },
        ],
    }

    print("\n✓ 新的配置:")
    print(yaml.dump(new_hooks, allow_unicode=True, default_flow_style=False))

    # 3. 合并
    merged_config = adapter.merge_settings(existing_config, new_hooks)

    print("\n✓ 合并后的配置:")
    print(yaml.dump(merged_config, allow_unicode=True, default_flow_style=False))
    print(f"\n✓ Skills 数量: {len(merged_config['skills'])} (去重后)")
    print(f"✓ Approvals mode: {merged_config['approvals']['mode']} (新值覆盖旧值)")


def main():
    """主函数"""
    print("\n🚀 Hermes 适配器使用示例\n")

    # 运行所有示例
    demo_basic_usage()
    demo_export_yaml()
    demo_merge_settings()

    print("\n" + "=" * 60)
    print("✅ 所有示例运行完成")
    print("=" * 60)
    print("\n💡 提示:")
    print("  - Hermes 适配器将 hooks 翻译为 YAML 配置")
    print("  - 可以使用 export_yaml 导出到文件")
    print("  - 合并时会自动去重相同的 skill")
    print("\n📚 更多信息请查看 examples/hermes-adapter/README.md")


if __name__ == "__main__":
    main()

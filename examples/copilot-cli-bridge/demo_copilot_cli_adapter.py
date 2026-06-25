"""
Copilot CLI Bridge 示例

演示如何通过 harness Bridge 将 Profile 配置部署到 Copilot CLI 平台。

运行方式:
  python demo_copilot_cli_adapter.py

输出:
  - Copilot CLI 配置文件（.copilot/config.json 格式）
  - MCP server 定义
  - hook 配置映射
"""

import json
import sys

# ── 添加项目路径 ───────────────────────────────────────────────
sys.path.insert(0, "../../packages/core")

from harness.adapters.copilot_cli import CopilotCLIAdapter
from harness.adapters.base import IAgentAdapter


# ── 示例 Profile hook 配置 ────────────────────────────────────

SAMPLE_HOOKS = {
    "session_start": [
        {"type": "script", "command": "scripts/run-skill.py compliance-check"},
        {"type": "skill", "skill_id": "compliance-check"},
    ],
    "pre_execute": [
        {"type": "script", "command": "packages/hooks/pre_execute.py"},
    ],
    "post_execute": [
        {"type": "prompt", "message": "Review your changes before finalizing"},
    ],
}


def main():
    adapter = CopilotCLIAdapter()

    print("=" * 60)
    print("Copilot CLI Adapter Demo")
    print("=" * 60)

    # ── 适配器基本信息 ──────────────────────────────────────
    print(f"\nAdapter name: {adapter.name}")
    print(f"Settings path: {adapter.get_settings_path('/my/project')}")

    # ── 翻译 hooks ──────────────────────────────────────────
    harness_root = "/opt/harness-cook"
    result = adapter.translate_hooks(SAMPLE_HOOKS, harness_root=harness_root)

    print("\n--- Translated Configuration ---")
    print(json.dumps(result, indent=2))

    # ── 合并到现有配置 ──────────────────────────────────────
    existing_config = {
        "mcpServers": {
            "other-tool": {"command": "node", "args": ["server.js"]},
        },
    }

    merged = adapter.merge_settings(existing_config, result)
    print("\n--- Merged Configuration (with existing MCP servers) ---")
    print(json.dumps(merged, indent=2))

    # ── 写入配置文件路径 ────────────────────────────────────
    settings_path = adapter.get_settings_path("/my/project")
    print(f"\nConfiguration would be written to: {settings_path}")


if __name__ == "__main__":
    main()

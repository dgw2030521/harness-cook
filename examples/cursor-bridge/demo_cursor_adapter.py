"""
Cursor Bridge 示例

演示如何通过 harness Bridge 将 Profile 配置部署到 Cursor IDE 平台。

运行方式:
  python demo_cursor_adapter.py

输出:
  - Cursor MCP 配置文件（.cursor/mcp.json 格式）
  - MCP server 定义
  - harness_metadata（hook 配置供参考）
"""

import json
import sys

# ── 添加项目路径 ───────────────────────────────────────────────
sys.path.insert(0, "../../packages/core")

from harness.adapters.cursor import CursorAdapter
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
}


def main():
    adapter = CursorAdapter()

    print("=" * 60)
    print("Cursor Adapter Demo")
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
            "existing-mcp": {"command": "npx", "args": ["-y", "other-server"]},
        },
    }

    merged = adapter.merge_settings(existing_config, result)
    print("\n--- Merged Configuration (with existing MCP servers) ---")
    print(json.dumps(merged, indent=2))

    # ── 写入配置文件路径 ────────────────────────────────────
    settings_path = adapter.get_settings_path("/my/project")
    print(f"\nConfiguration would be written to: {settings_path}")

    # ── 说明 Cursor 不支持 hook 脚本 ────────────────────────
    print("\nNote: Cursor IDE does not support hook script execution.")
    print("Governance checks are performed via MCP tool calls")
    print("(harness_check, harness_guardrails_check, etc.)")


if __name__ == "__main__":
    main()

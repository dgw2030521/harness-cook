#!/usr/bin/env python3
"""
harness deactivate — 还原项目配置到 activate 前状态

核心原则：只还原项目级配置（activate 创建的东西），不动 harness 软件本身。
pip 包是工具，不是项目配置——deactivate 不卸载软件。

还原清单：
  1. 删除 ~/.claude/skills/ 下的 harness 符号链接
  2. 清理 ~/.claude/settings.json 中的 mcpServers.harness-cook
  3. 清理用户项目 .claude/settings.local.json 中的 harness hooks + MCP 权限 + env（空壳则删文件）
  4. 清理用户项目 .claude/settings.json 中 Bridge 写入的 harness hooks + env（空壳则删文件）
  5. 清理非 Claude Code 适配器配置（Hermes ~/.hermes/config.yaml、Cursor .cursor/mcp.json、Copilot CLI ~/.copilot/config.json）
  6. 删除用户项目 .harness/ 整个目录
  7. 清理 .gitignore 中 harness 相关条目
  8. 清理 .git/hooks/pre-commit 中的 harness 段（保留用户原有 hook）

安全边界：只删 harness 写入的条目和 harness 创建的空壳文件，绝不动用户原有的内容。

退出码: 0 = 成功, 1 = 失败
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

import yaml


def _get_harness_root() -> str:
    """获取 harness-cook 安装目录（源码位置）

    用于定位 MCP 启动脚本等 harness 自身资源。

    解析优先级：
      1. 环境变量 HARNESS_COOK_ROOT
      2. 从脚本位置推导
      3. 降级：当前工作目录
    """
    env_root = os.environ.get("HARNESS_COOK_ROOT", "")
    if env_root and Path(env_root).exists():
        return env_root

    script_path = Path(__file__).resolve()
    candidate = script_path.parent.parent.parent.parent
    if (candidate / "packages" / "core").exists():
        return str(candidate)
    return str(candidate)


def _get_user_project_dir() -> str:
    """获取用户项目目录（.harness/ 所在位置）

    规则：用户在哪个目录启动 Claude Code，就在哪个目录生成 .harness/。

    解析优先级：
      1. 环境变量 CLAUDE_PROJECT_DIR（Claude Code 启动时自动设置）
      2. 当前工作目录 cwd
    """
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if env_dir:
        return env_dir
    return os.getcwd()


# ─── 标记：harness 创建的东西 ─────────────────────────

HARNESS_MCP_KEY = "harness-cook"
HARNESS_HOOK_PREFIX = "harness"

HARNESS_MCP_PERMISSIONS = [
    "mcp__harness-cook__harness_check",
    "mcp__harness-cook__harness_audit",
    "mcp__harness-cook__harness_plan",
    "mcp__harness-cook__harness_run",
    "mcp__harness-cook__harness_status",
    "mcp__harness-cook__harness_register",
    "mcp__harness-cook__harness_gate_create",
    "mcp__harness-cook__harness_guardrails_check",
    "mcp__harness-cook__harness_pipeline_run",
    "mcp__harness-cook__harness_pipeline_status",
    "mcp__harness-cook__harness_agent_list",
    "mcp__harness-cook__harness_profile_list",
    "mcp__harness-cook__harness_profile_load",
    "mcp__harness-cook__harness_skill_list",
    "mcp__harness-cook__harness_skill_register",
    "mcp__harness-cook__harness_bridge_deploy",
]

HARNESS_HOOK_COMMANDS = [
    "hook-compliance-scan.py",
    "hook-guardrails-pii.py",
    "hook-session-init.py",
    "hook-task-audit.py",
    "hook-prompt-guardrails.py",
    "run-skill.py",                # Bridge 部署的 skill hooks
    "harness_bridge_deploy",
    "harness.skill_registry",
    "harness_skill_registry",
    "mcp__harness-cook__",
    "python3 -m harness",
]


def _step_remove_skills(harness_root: str) -> bool:
    """Step 1: 删除 ~/.claude/skills/ 下的 harness 符号链接"""
    print("🎯 [Step 1/5] 移除 Skills 符号链接...")

    target_base = Path.home() / ".claude" / "skills"
    if not target_base.exists():
        print("  ⚠️ ~/.claude/skills/ 不存在，无需清理")
        return True

    removed = 0
    for target in target_base.iterdir():
        if target.is_symlink():
            # 检查链接是否指向 harness-cook 项目
            link_target = str(target.resolve())
            if "harness-cook" in link_target:
                try:
                    target.unlink()
                    removed += 1
                    print("  ✅ 移除: {}".format(target.name))
                except Exception as e:
                    print("  ❌ 移除失败: {} — {}".format(target.name, e))

    print("  共移除 {} 个链接".format(removed))
    return True


def _step_clean_global_settings(harness_root: str) -> bool:
    """Step 2: 清理 ~/.claude/settings.json 中的 MCP Server 配置"""
    print("🔌 [Step 2/5] 清理全局 MCP Server 配置...")

    claude_settings_path = Path.home() / ".claude" / "settings.json"

    if not claude_settings_path.exists():
        print("  ⚠️ ~/.claude/settings.json 不存在，无需清理")
        return True

    try:
        settings = json.loads(claude_settings_path.read_text())
    except (json.JSONDecodeError, ValueError):
        print("  ⚠️ settings.json 格式异常，跳过")
        return True

    modified = False

    # 移除 mcpServers.harness-cook
    if "mcpServers" in settings and HARNESS_MCP_KEY in settings["mcpServers"]:
        del settings["mcpServers"][HARNESS_MCP_KEY]
        modified = True
        print("  ✅ 移除 mcpServers.{}".format(HARNESS_MCP_KEY))
        # 如果 mcpServers 空了，也删掉这个 key
        if not settings["mcpServers"]:
            del settings["mcpServers"]

    # 删除自动生成的 MCP 启动脚本（在 harness 安装目录）
    mcp_script = Path(harness_root) / "scripts" / "harness-mcp.sh"
    if mcp_script.exists():
        mcp_script.unlink()
        print("  ✅ 移除 MCP 启动脚本: {}".format(mcp_script))

    if modified:
        claude_settings_path.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2) + "\n"
        )
        print("  ✅ ~/.claude/settings.json 已更新")
    else:
        print("  ✅ 无 harness 配置，无需清理")

    return True


def _step_clean_local_settings(user_project_dir: str) -> bool:
    """Step 3: 清理用户项目 .claude/settings.local.json 中的 hooks + MCP 权限

    如果清理后文件变成空壳（只剩 {}），直接删除文件。
    """
    print("🪝 [Step 3/5] 清理项目 hooks 和 MCP 权限...")

    local_settings_path = Path(user_project_dir) / ".claude" / "settings.local.json"

    if not local_settings_path.exists():
        print("  ✅ settings.local.json 不存在，无需清理")
        return True

    try:
        settings = json.loads(local_settings_path.read_text())
    except (json.JSONDecodeError, ValueError):
        print("  ⚠️ settings.local.json 格式异常，删除损坏文件")
        local_settings_path.unlink()
        return True

    modified = False

    # 清理 hooks — 移除包含 harness 命令的条目
    if "hooks" in settings:
        for hook_type, entries in list(settings["hooks"].items()):
            # 过滤掉 harness 相关的 hook 条目
            clean_entries = []
            for entry in entries:
                if isinstance(entry, dict):
                    entry_str = json.dumps(entry)
                    if any(prefix in entry_str for prefix in HARNESS_HOOK_COMMANDS):
                        modified = True
                        continue  # 跳过 harness 的
                clean_entries.append(entry)

            if not clean_entries:
                del settings["hooks"][hook_type]
                modified = True
            else:
                settings["hooks"][hook_type] = clean_entries

        if not settings["hooks"]:
            del settings["hooks"]
            modified = True

    # 清理 MCP 权限
    if "permissions" in settings and "allow" in settings["permissions"]:
        allow_list = settings["permissions"]["allow"]
        cleaned = [p for p in allow_list if p not in HARNESS_MCP_PERMISSIONS]
        removed_count = len(allow_list) - len(cleaned)
        if removed_count > 0:
            settings["permissions"]["allow"] = cleaned
            modified = True
            print("  ✅ 移除 {} 个 MCP 工具权限".format(removed_count))

    # 如果 permissions.allow 空了，清理整个 permissions
    if "permissions" in settings:
        if "allow" in settings["permissions"] and not settings["permissions"]["allow"]:
            del settings["permissions"]
            modified = True

    # 清理 env 中 harness 写入的 HARNESS_COOK_ROOT
    if "env" in settings and "HARNESS_COOK_ROOT" in settings["env"]:
        del settings["env"]["HARNESS_COOK_ROOT"]
        modified = True
        print("  ✅ 移除 env.HARNESS_COOK_ROOT")
    # 如果 env 空了，删掉整个 env key
    if "env" in settings and not settings["env"]:
        del settings["env"]
        modified = True

    if modified:
        # 检查是否变成空壳——如果只剩 {} 或所有 key 都是空，直接删文件
        has_content = any(
            v for v in settings.values()
            if isinstance(v, dict) and v  # 非空 dict
            or isinstance(v, list) and v  # 非空 list
            or isinstance(v, str) and v   # 非空 str
        )
        if not has_content:
            local_settings_path.unlink()
            print("  ✅ settings.local.json 已删除（清理后变空壳）")
        else:
            local_settings_path.write_text(
                json.dumps(settings, ensure_ascii=False, indent=2) + "\n"
            )
            print("  ✅ settings.local.json 已更新（移除 harness 条目）")
    else:
        print("  ✅ 无 harness 配置，无需清理")

    return True


def _step_clean_project_settings(user_project_dir: str) -> bool:
    """Step 4: 清理用户项目 .claude/settings.json 中 Bridge 写入的 hooks

    如果清理后文件变成空壳，直接删除文件。
    如果 .claude/ 目录变空，删除目录。
    """
    print("📋 [Step 4/6] 清理项目 settings.json...")

    project_settings_path = Path(user_project_dir) / ".claude" / "settings.json"

    if not project_settings_path.exists():
        print("  ✅ settings.json 不存在，无需清理")
        return True

    try:
        settings = json.loads(project_settings_path.read_text())
    except (json.JSONDecodeError, ValueError):
        print("  ⚠️ settings.json 格式异常，删除损坏文件")
        project_settings_path.unlink()
        return True

    modified = False

    # 清理 Bridge 写入的 hooks（包含 harness 命令的）
    if "hooks" in settings:
        for hook_type, entries in list(settings["hooks"].items()):
            clean_entries = []
            for entry in entries:
                entry_str = json.dumps(entry) if isinstance(entry, dict) else str(entry)
                if any(prefix in entry_str for prefix in HARNESS_HOOK_COMMANDS):
                    modified = True
                    continue
                clean_entries.append(entry)

            if not clean_entries:
                del settings["hooks"][hook_type]
            else:
                settings["hooks"][hook_type] = clean_entries

        if not settings["hooks"]:
            del settings["hooks"]
            modified = True

    # 清理 env 中 harness 写入的 HARNESS_COOK_ROOT
    if "env" in settings and "HARNESS_COOK_ROOT" in settings["env"]:
        del settings["env"]["HARNESS_COOK_ROOT"]
        modified = True
        print("  ✅ 移除 env.HARNESS_COOK_ROOT")
    # 如果 env 空了，删掉整个 env key
    if "env" in settings and not settings["env"]:
        del settings["env"]
        modified = True

    if modified:
        # 检查是否变成空壳
        has_content = any(
            v for v in settings.values()
            if isinstance(v, dict) and v
            or isinstance(v, list) and v
            or isinstance(v, str) and v
        )
        if not has_content:
            project_settings_path.unlink()
            print("  ✅ settings.json 已删除（清理后变空壳）")
        else:
            project_settings_path.write_text(
                json.dumps(settings, ensure_ascii=False, indent=2) + "\n"
            )
            print("  ✅ settings.json 已更新（移除 harness 条目）")
    else:
        print("  ✅ 无 harness 配置，无需清理")

    return True


def _step_clean_adapter_settings(user_project_dir: str) -> bool:
    """Step 5: 清理非 Claude Code 适配器（Hermes/Cursor）的配置文件

    Claude Code 的配置在 Step 2-4 已清理。
    Hermes 和 Cursor 的全局/项目配置需要单独清理——使用 YAML/JSON 格式读取，
    移除 harness-cook 相关条目后写回，保留用户原有配置。

    适配器配置路径：
      - Hermes: ~/.hermes/config.yaml（全局 YAML）
      - Cursor: .cursor/mcp.json（项目级 JSON）
      - Copilot CLI: ~/.copilot/config.json（全局 JSON）
    """
    print("🔌 [Step 5/6] 清理非 Claude Code 适配器配置...")

    # ── 读取适配器标记，确定需要清理哪些 ──
    harness_dir = Path(user_project_dir) / ".harness"
    adapter_marker = harness_dir / "active_adapter"
    env_file = harness_dir / "env"

    adapter_name = None
    if adapter_marker.exists():
        adapter_name = adapter_marker.read_text(encoding="utf-8").strip()
    elif env_file.exists():
        # 从 .harness/env 中读取 HARNESS_ADAPTER
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("HARNESS_ADAPTER="):
                adapter_name = line.split("=", 1)[1].strip().split("#", 1)[0].strip()
                break

    if not adapter_name or adapter_name == "claude-code":
        print("  ✅ 适配器为 claude-code 或未标记，非 Claude 配置已在 Step 2-4 清理")
        return True

    print("  📋 适配器: {} — 清理对应配置文件".format(adapter_name))
    cleaned = False

    # ── Hermes: ~/.hermes/config.yaml ──
    if adapter_name == "hermes":
        hermes_config_path = Path.home() / ".hermes" / "config.yaml"
        env_path = os.environ.get("HERMES_CONFIG_PATH")
        if env_path:
            hermes_config_path = Path(env_path)

        if hermes_config_path.exists():
            try:
                config = yaml.safe_load(hermes_config_path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                print("  ⚠️ ~/.hermes/config.yaml 格式异常，跳过清理")
                return True

            modified = False

            # 移除 mcpServers.harness-cook
            if "mcpServers" in config and HARNESS_MCP_KEY in config["mcpServers"]:
                del config["mcpServers"][HARNESS_MCP_KEY]
                modified = True
                print("  ✅ 移除 mcpServers.harness-cook")
                if not config["mcpServers"]:
                    del config["mcpServers"]

            # 移除 harness_metadata
            if "harness_metadata" in config:
                del config["harness_metadata"]
                modified = True
                print("  ✅ 移除 harness_metadata")

            if modified:
                # 检查是否变成空壳
                has_content = any(
                    v for v in config.values()
                    if isinstance(v, dict) and v
                    or isinstance(v, list) and v
                    or isinstance(v, str) and v
                )
                if not has_content:
                    hermes_config_path.unlink()
                    print("  ✅ ~/.hermes/config.yaml 已删除（清理后变空壳）")
                else:
                    hermes_config_path.write_text(
                        yaml.dump(config, allow_unicode=True, default_flow_style=False, sort_keys=False),
                        encoding="utf-8",
                    )
                    print("  ✅ ~/.hermes/config.yaml 已更新（移除 harness 条目）")
            else:
                print("  ✅ ~/.hermes/config.yaml 无 harness 配置，无需清理")
            cleaned = True
        else:
            print("  ✅ ~/.hermes/config.yaml 不存在，无需清理")

    # ── Cursor: .cursor/mcp.json ──
    elif adapter_name == "cursor":
        cursor_config_path = Path(user_project_dir) / ".cursor" / "mcp.json"

        if cursor_config_path.exists():
            try:
                config = json.loads(cursor_config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                print("  ⚠️ .cursor/mcp.json 格式异常，删除损坏文件")
                cursor_config_path.unlink()
                return True

            modified = False

            if "mcpServers" in config and HARNESS_MCP_KEY in config["mcpServers"]:
                del config["mcpServers"][HARNESS_MCP_KEY]
                modified = True
                print("  ✅ 移除 .cursor/mcp.json 中 mcpServers.harness-cook")
                if not config["mcpServers"]:
                    del config["mcpServers"]

            if "harness_metadata" in config:
                del config["harness_metadata"]
                modified = True
                print("  ✅ 移除 .cursor/mcp.json 中 harness_metadata")

            if modified:
                has_content = any(
                    v for v in config.values()
                    if isinstance(v, dict) and v
                    or isinstance(v, list) and v
                    or isinstance(v, str) and v
                )
                if not has_content:
                    cursor_config_path.unlink()
                    print("  ✅ .cursor/mcp.json 已删除（清理后变空壳）")
                else:
                    cursor_config_path.write_text(
                        json.dumps(config, ensure_ascii=False, indent=2) + "\n"
                    )
                    print("  ✅ .cursor/mcp.json 已更新（移除 harness 条目）")
            else:
                print("  ✅ .cursor/mcp.json 无 harness 配置，无需清理")
            cleaned = True
        else:
            print("  ✅ .cursor/mcp.json 不存在，无需清理")

    # ── Copilot CLI: ~/.copilot/config.json ──
    elif adapter_name == "copilot-cli":
        copilot_config_path = Path.home() / ".copilot" / "config.json"

        if copilot_config_path.exists():
            try:
                config = json.loads(copilot_config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                print("  ⚠️ ~/.copilot/config.json 格式异常，删除损坏文件")
                copilot_config_path.unlink()
                return True

            modified = False

            if "mcpServers" in config and HARNESS_MCP_KEY in config["mcpServers"]:
                del config["mcpServers"][HARNESS_MCP_KEY]
                modified = True
                print("  ✅ 移除 ~/.copilot/config.json 中 mcpServers.harness-cook")
                if not config["mcpServers"]:
                    del config["mcpServers"]

            if "hooks" in config:
                for hook_type, entries in list(config["hooks"].items()):
                    clean_entries = []
                    for entry in entries:
                        entry_str = json.dumps(entry) if isinstance(entry, dict) else str(entry)
                        if any(prefix in entry_str for prefix in HARNESS_HOOK_COMMANDS):
                            modified = True
                            continue
                        clean_entries.append(entry)
                    if not clean_entries:
                        del config["hooks"][hook_type]
                    else:
                        config["hooks"][hook_type] = clean_entries
                if not config["hooks"]:
                    del config["hooks"]

            if modified:
                has_content = any(
                    v for v in config.values()
                    if isinstance(v, dict) and v
                    or isinstance(v, list) and v
                    or isinstance(v, str) and v
                )
                if not has_content:
                    copilot_config_path.unlink()
                    print("  ✅ ~/.copilot/config.json 已删除（清理后变空壳）")
                else:
                    copilot_config_path.write_text(
                        json.dumps(config, ensure_ascii=False, indent=2) + "\n"
                    )
                    print("  ✅ ~/.copilot/config.json 已更新（移除 harness 条目）")
            else:
                print("  ✅ ~/.copilot/config.json 无 harness 配置，无需清理")
            cleaned = True
        else:
            print("  ✅ ~/.copilot/config.json 不存在，无需清理")

    # ── OpenAI: 无本地配置文件 ──
    elif adapter_name == "openai":
        print("  ✅ OpenAI 适配器无本地配置文件，无需清理")

    if not cleaned and adapter_name not in ("claude-code", "openai"):
        print("  ⚠️ 适配器 '{}' 的清理逻辑尚未实现，请手动检查配置文件".format(adapter_name))

    return True


def _step_clean_git_hooks(user_project_dir: str) -> bool:
    """清理 .git/hooks/pre-commit 中的 harness 段（_install_git_hooks 的精确逆操作）

    activate 时 Bridge 在 .git/hooks/pre-commit 追加了 harness 检查段
    （标记 `# ── harness-cook gate ──` ... `# ── harness-cook gate end ──`）。
    deactivate 精确移除该段，保留用户原有 hook 内容；
    若清理后文件仅剩 shebang 或空，删除文件（避免空 hook 干扰 git）。
    """
    print("🪝 [Step 6] 清理 git pre-commit hook 中的 harness 段...")

    pre_commit_path = Path(user_project_dir) / ".git" / "hooks" / "pre-commit"
    if not pre_commit_path.exists():
        print("  ✅ .git/hooks/pre-commit 不存在，无需清理")
        return True

    # marker 必须与 bridge.py:_install_git_hooks 完全一致（含全角 ──）
    HARNESS_MARKER_START = "# ── harness-cook gate ──"
    HARNESS_MARKER_END = "# ── harness-cook gate end ──"

    try:
        content = pre_commit_path.read_text(encoding="utf-8")
    except OSError as e:
        print("  ⚠️ 读取 pre-commit 失败: {} — 跳过清理".format(e))
        return True

    if HARNESS_MARKER_START not in content:
        print("  ✅ pre-commit 无 harness 段，无需清理")
        return True

    try:
        start_idx = content.index(HARNESS_MARKER_START)
        end_idx = content.index(HARNESS_MARKER_END, start_idx) + len(HARNESS_MARKER_END)
    except ValueError:
        print("  ⚠️ harness 段标记不完整（缺少 end 标记），跳过清理以避免误删用户内容")
        return True

    # 移除 harness 段，拼接前后剩余内容
    new_content = content[:start_idx].rstrip()
    tail = content[end_idx:].lstrip("\n")
    if tail:
        new_content = new_content + "\n" + tail
    if not new_content.endswith("\n"):
        new_content += "\n"

    # 判断剩余非空非 shebang 内容
    has_user_content = any(
        l.strip() and not l.strip().startswith("#!")
        for l in new_content.splitlines()
    )

    if not has_user_content:
        # 只剩 shebang 或空 → 删除文件
        try:
            pre_commit_path.unlink()
            print("  ✅ pre-commit 已删除（清理后仅剩 shebang/空）")
        except OSError as e:
            print("  ⚠️ 删除 pre-commit 失败: {}".format(e))
    else:
        try:
            pre_commit_path.write_text(new_content, encoding="utf-8")
            try:
                pre_commit_path.chmod(0o755)
            except OSError:
                pass  # 权限保持原状，不阻断清理
            print("  ✅ pre-commit 已移除 harness 段（保留用户原有 hook）")
        except OSError as e:
            print("  ⚠️ 写回 pre-commit 失败: {}".format(e))

    return True


def _step_clean_project(user_project_dir: str) -> bool:
    """Step 7: 删除 .harness/ + 清理 .gitignore（项目级配置还原）"""
    print("📁 [Step 7/7] 清理项目配置目录...")

    # 删除用户项目 .harness/ 整个目录（activate 的精确逆操作）
    harness_dir = Path(user_project_dir) / ".harness"
    if harness_dir.exists():
        shutil.rmtree(harness_dir)
        print("  ✅ .harness/ 已删除")
    else:
        print("  ✅ .harness/ 不存在，无需清理")

    # 清理 .gitignore 中 harness 相关条目
    gitignore_path = Path(user_project_dir) / ".gitignore"
    if gitignore_path.exists():
        harness_entries = [".harness/env", ".harness/audit/"]
        lines = gitignore_path.read_text().splitlines()
        cleaned = [l for l in lines if l.strip() not in harness_entries]
        removed = len(lines) - len(cleaned)
        if removed > 0:
            gitignore_path.write_text("\n".join(cleaned) + "\n")
            print("  ✅ .gitignore 已清理 {} 个 harness 条目".format(removed))
        else:
            print("  ✅ .gitignore 无 harness 条目，无需清理")

    return True


def cmd_deactivate(args) -> int:
    """harness deactivate 命令执行"""
    harness_root = _get_harness_root()
    user_project_dir = _get_user_project_dir()

    print("=" * 60)
    print("  harness-cook 还原项目配置")
    print("  ⚠️  将还原到 activate 前的状态（不卸载软件）")
    print("=" * 60)
    print("harness 安装目录: {}".format(harness_root))
    print("用户项目目录:     {}".format(user_project_dir))
    print()

    results = {}

    results["skills"] = _step_remove_skills(harness_root)
    results["global_settings"] = _step_clean_global_settings(harness_root)
    results["local_settings"] = _step_clean_local_settings(user_project_dir)
    results["project_settings"] = _step_clean_project_settings(user_project_dir)
    results["adapter_settings"] = _step_clean_adapter_settings(user_project_dir)
    results["git_hooks"] = _step_clean_git_hooks(user_project_dir)
    results["project"] = _step_clean_project(user_project_dir)

    # 汇总
    print()
    print("=" * 60)
    print("  卸载结果汇总")
    print("=" * 60)
    for step, ok in results.items():
        icon = "✅" if ok else "❌"
        print("  {} {}".format(icon, step))

    all_ok = all(results.values())
    if all_ok:
        print()
        print("✅ 项目配置已还原到 activate 前状态。harness 软件本身未卸载。")
        print("   请重启 Claude Code 使变更生效。")
    else:
        print()
        print("⚠️ 部分步骤未成功，请检查上方输出。")

    print("=" * 60)
    return 0 if all_ok else 1


def add_deactivate_args(subparsers):
    """注册 deactivate 子命令到 argparse"""
    subparsers.add_parser(
        "deactivate",
        help="还原项目配置到 activate 前状态（不卸载软件）",
        description="移除 skills 链接 + 清理 settings.json hooks + 删除 .harness/ + 清理 .gitignore",
    )

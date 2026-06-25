#!/usr/bin/env python3
"""
harness activate — 一键激活 harness-cook 所有能力

用法:
  harness activate [--skip-install] [--skip-mcp] [--skip-hooks] [--skip-skills]

功能:
  1. 安装 harness 核心包 (pip install -e packages/core)
  2. 配置 MCP Server (写入 ~/.claude/settings.json mcpServers)
  3. 配置 hooks (写入用户项目 .claude/settings.local.json hooks + permissions)
  4. 注册 skills (创建符号链接 ~/.claude/skills/{name} → harness skills/{name})
  5. 初始化 (在用户项目创建 .harness/audit/ 目录)

退出码: 0 = 成功, 1 = 失败
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


def _get_harness_root() -> str:
    """获取 harness-cook 安装目录（源码位置）

    用于定位 hooks 脚本、skills、MCP server 等 harness 自身资源。

    解析优先级：
      1. 环境变量 HARNESS_COOK_ROOT
      2. 从脚本位置推导（__file__ → packages/cli/cli_commands/ → harness-cook/）
      3. 降级：当前工作目录
    """
    env_root = os.environ.get("HARNESS_COOK_ROOT", "")
    if env_root and Path(env_root).exists():
        return env_root

    # 从脚本位置推导：cli_commands/activate.py → packages/cli/cli_commands/ → 项目根
    script_path = Path(__file__).resolve()
    # 路径层级：__file__ = .../harness-cook/packages/cli/cli_commands/activate.py
    # parent(1) = cli_commands/  parent(2) = cli/  parent(3) = packages/  parent(4) = harness-cook/
    candidate = script_path.parent.parent.parent.parent
    if (candidate / "packages" / "core").exists():
        return str(candidate)

    # 降级：可能项目结构不同
    return str(candidate)


def _get_user_project_dir() -> str:
    """获取用户项目目录（.harness/ 应创建的位置）

    规则：用户在哪个目录启动 Claude Code，就在哪个目录生成 .harness/。

    解析优先级：
      1. 环境变量 CLAUDE_PROJECT_DIR（Claude Code 启动时自动设置）
      2. 当前工作目录 cwd
    """
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if env_dir:
        return env_dir
    return os.getcwd()


def _get_pip_index_url() -> str:
    """获取 pip 安装源——优先用户配置，降级到国内镜像

    解析优先级：
      1. 用户 pip 全局配置（pip config get global.index-url）
      2. 清华镜像（国内网络友好）
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "config", "get", "global.index-url"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    # 降级：清华镜像（国内网络最稳定）
    return "https://pypi.tuna.tsinghua.edu.cn/simple"


def _step_install_core(harness_root: str) -> bool:
    """Step 1: 安装 harness 核心包 + CLI 包（注册 harness 命令）"""
    core_path = Path(harness_root) / "packages" / "core"
    cli_path = Path(harness_root) / "packages" / "cli"

    if not core_path.exists():
        print("❌ packages/core 目录不存在，跳过安装")
        return False

    # pip 安装源——优先用户配置，降级到国内镜像
    index_url = _get_pip_index_url()
    trusted_host = "pypi.tuna.tsinghua.edu.cn" if "pypi.tuna" in index_url else ""
    print("📦 [Step 1/5] 安装 harness 核心包 + CLI...")
    print("  📡 pip 源: {}".format(index_url))

    pip_base_args = [sys.executable, "-m", "pip", "install", "-i", index_url]
    if trusted_host:
        pip_base_args += ["--trusted-host", trusted_host]

    # 通过环境变量传递镜像源——pip build dependency 子进程会继承此变量
    pip_env = os.environ.copy()
    pip_env["PIP_INDEX_URL"] = index_url
    if trusted_host:
        pip_env["PIP_TRUSTED_HOSTS"] = trusted_host

    try:
        result = subprocess.run(
            pip_base_args + ["-e", str(core_path)],
            capture_output=True, text=True, timeout=120,
            env=pip_env,
        )
        if result.returncode == 0:
            print("  ✅ 核心包安装成功")
        else:
            print("  ⚠️ 核心包安装可能有问题: {}".format(result.stderr.strip()[:500]))

        # 安装 CLI 包——注册 harness 命令到 PATH
        if cli_path.exists():
            result_cli = subprocess.run(
                pip_base_args + ["-e", str(cli_path)],
                capture_output=True, text=True, timeout=120,
                env=pip_env,
            )
            if result_cli.returncode == 0:
                print("  ✅ CLI 包安装成功（harness 命令已注册）")
            else:
                print("  ⚠️ CLI 包安装可能有问题: {}".format(result_cli.stderr.strip()[:500]))
        else:
            print("  ⚠️ packages/cli 目录不存在，跳过 CLI 包安装")

        # 验证
        result2 = subprocess.run(
            [sys.executable, "-c", "import harness; print(harness.__version__)"],
            capture_output=True, text=True, timeout=10,
        )
        if result2.returncode == 0:
            print("  ✅ harness 包已可导入 (v{})".format(result2.stdout.strip()))
            return True
        return False
    except Exception as e:
        print("  ❌ 安装失败: {}".format(e))
        return False


def _step_configure_mcp(harness_root: str, user_project_dir: str, adapter_name: Optional[str] = None) -> bool:
    """Step 2: MCP Server 配置——收敛历史错配，不再往 ~/.claude/settings.json 写 mcpServers

    设计说明（为什么此步不再写 mcpServers / 不再生成脚本）：
      - claude-code 走 hooks 自动校验、自动使用 harness 能力（见 Step 3 翻译的
        SessionStart/PreToolUse/PostToolUse 等），不依赖 MCP 入口；
      - hermes/cursor/copilot-cli 等的 MCP 配置由各自 adapter 在 Step 3
        （bridge.deploy → translate_hooks/merge_settings）写入**各自平台**配置文件
        （如 hermes 写到 ~/.hermes/config.yaml），它们不读 ~/.claude/settings.json。
      故往 ~/.claude/settings.json 写 mcpServers 对所有 adapter 都是错配：
      claude-code 不需要、其他 adapter 不读它。此步仅对 claude-code 清理
      旧版 activate 写入的遗留 mcpServers.harness-cook，避免加载冗余 MCP 入口。
    """
    print("🔌 [Step 2/5] MCP Server 配置...")
    resolved_adapter = adapter_name or "claude-code"

    if resolved_adapter == "claude-code":
        if _cleanup_stale_mcpserver():
            print("  ✅ 已清理 ~/.claude/settings.json 中遗留的 mcpServers.harness-cook")
        print("  💡 claude-code 通过 hooks 自动校验，不依赖 MCP；"
              "其他 adapter 的 MCP 由 Step 3 写入各自平台配置文件")
        return True

    print("  💡 适配器 '{}' 的 MCP 配置由 Step 3 写入各自平台配置文件，"
          "此步跳过 ~/.claude/settings.json".format(resolved_adapter))
    return True


def _cleanup_stale_mcpserver() -> bool:
    """清理 ~/.claude/settings.json 中遗留的 mcpServers.harness-cook（旧版 activate 写入）

    只删 harness-cook 这一条，保留其他 mcpServers 与无关配置。删后若 mcpServers
    为空则一并移除该键，保持配置文件整洁。文件不存在或无残留时返回 False。
    """
    claude_settings_path = Path.home() / ".claude" / "settings.json"
    if not claude_settings_path.exists():
        return False
    try:
        settings = json.loads(claude_settings_path.read_text())
    except (json.JSONDecodeError, ValueError):
        return False

    mcp = settings.get("mcpServers")
    if not isinstance(mcp, dict) or "harness-cook" not in mcp:
        return False

    del mcp["harness-cook"]
    if not mcp:
        del settings["mcpServers"]

    claude_settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2))
    return True


def _step_configure_hooks(harness_root: str, user_project_dir: str, profile_name: str = "default", adapter_name: Optional[str] = None) -> bool:
    """Step 3: 部署 Profile（声明式 hooks/skills/gates → settings.json）

    旧逻辑：硬编码 5 个 hook 脚本 → 已废弃
    新逻辑：ProfileLoader 分层查找 → 内置 preset 兜底 → Bridge deploy 到 settings.local.json

    分层查找：
      1. 项目级 .harness/profiles/ → 项目自定义（优先）
      2. 内置 packages/core/harness/profiles/ → 框架预设（兜底）

    Args:
        adapter_name: 显式指定的适配器名称（来自 --agent CLI 参数或解析优先级链）。
                      None 时由 Bridge 内部从 Profile.default_agent 推导
    """
    print("🪝 [Step 3/5] 部署 Profile (hooks/skills/gates)...")

    try:
        from harness.config import ProfileLoader
        from harness.bridge import get_bridge

        # ProfileLoader 自带分层查找——项目级优先，内置兜底
        loader = ProfileLoader(str(Path(user_project_dir) / ".harness" / "profiles"))

        profile = loader.load(profile_name)

        # 解析适配器：--agent CLI 参数 > 优先级链 > Profile.default_agent
        if adapter_name is None:
            from harness.config import resolve_active_adapter
            adapter_name = resolve_active_adapter(
                harness_dir=Path(user_project_dir) / ".harness",
                profile_adapter=profile.default_agent,
            )

        print("  📋 已加载 Profile: {} (adapter={})".format(
            profile.name, adapter_name))

        # Bridge deploy → 写入目标平台配置
        bridge = get_bridge()
        result = bridge.deploy(profile, project_dir=user_project_dir, harness_root=harness_root, adapter_name=adapter_name)

        hooks_count = result.get("hooks_deployed", 0)
        gate_checks = result.get("gate_checks", 0)
        print("  ✅ 已部署: {} 个 hooks, {} 个 gate 检查 (via {})".format(
            hooks_count, gate_checks, adapter_name))
        print("  📄 配置文件: {}".format(result.get("settings_path", "")))

    except ImportError:
        print("  ⚠️ harness 核心包未安装，回退到硬编码 hooks 配置...")
        return _step_configure_hooks_fallback(harness_root, user_project_dir)
    except Exception as e:
        print("  ⚠️ Profile 部署失败: {}，回退到硬编码配置...".format(e))
        return _step_configure_hooks_fallback(harness_root, user_project_dir)

    # MCP 工具权限：仅 Claude Code 适配器需要写入 .claude/settings.local.json
    # 其他适配器有各自的权限机制（Hermes/Copilot CLI 有自己的 config，Cursor/OpenAI 无本地权限文件）
    if adapter_name == "claude-code":
        _add_mcp_permissions(user_project_dir)
    else:
        print("  💡 适配器 '{}' 不使用 .claude/settings.local.json，跳过 MCP 权限写入".format(adapter_name))

    return True


def _step_configure_hooks_fallback(harness_root: str, user_project_dir: str) -> bool:
    """硬编码 hooks 配置（回退方案，当 Profile 不可用时使用）"""
    # settings.local.json 写到用户项目目录
    local_settings_path = Path(user_project_dir) / ".claude" / "settings.local.json"
    # hooks 脚本在 harness 安装目录
    hooks_dir = Path(harness_root) / "packages" / "hooks"

    hook_scripts = {
        "hook-compliance-scan.py": ("Write|Edit", "PostToolUse"),
        "hook-guardrails-pii.py": ("Bash", "PostToolUse"),
        "hook-session-init.py": ("", "SessionStart"),
        "hook-task-audit.py": ("", "Stop"),
        "hook-prompt-guardrails.py": ("", "UserPromptSubmit"),
    }

    missing_hooks = [s for s in hook_scripts if not (hooks_dir / s).exists()]
    if missing_hooks:
        print("  ⚠️ 缺少 hook 脚本: {}".format(", ".join(missing_hooks)))

    settings = {}
    if local_settings_path.exists():
        try:
            settings = json.loads(local_settings_path.read_text())
        except (json.JSONDecodeError, ValueError):
            settings = {}

    # hooks 命令中用 $HARNESS_COOK_ROOT 定位 hook 脚本（在 harness 安装目录），
    # 用 $CLAUDE_PROJECT_DIR 定位用户项目（由 Claude Code 自动设置）
    hooks_config = {
        "PostToolUse": [
            {
                "matcher": "Write|Edit",
                "hooks": [{"type": "command", "command": "python3 \"$HARNESS_COOK_ROOT/packages/hooks/hook-compliance-scan.py\""}],
            },
            {
                "matcher": "Bash",
                "hooks": [{"type": "command", "command": "python3 \"$HARNESS_COOK_ROOT/packages/hooks/hook-guardrails-pii.py\""}],
            },
        ],
        "SessionStart": [
            {"matcher": "", "hooks": [{"type": "command", "command": "python3 \"$HARNESS_COOK_ROOT/packages/hooks/hook-session-init.py\""}]},
        ],
        "Stop": [
            {"matcher": "", "hooks": [{"type": "command", "command": "python3 \"$HARNESS_COOK_ROOT/packages/hooks/hook-task-audit.py\""}]},
        ],
        "UserPromptSubmit": [
            {"matcher": "", "hooks": [{"type": "command", "command": "python3 \"$HARNESS_COOK_ROOT/packages/hooks/hook-prompt-guardrails.py\""}]},
        ],
    }

    # 合而非替换 — 保留用户已有 hooks，harness 的 hook 按 matcher 去重合并
    existing_hooks = settings.get("hooks", {})
    for hook_type, entries in hooks_config.items():
        existing_entries = existing_hooks.get(hook_type, [])
        # 按 matcher 去重合并
        by_matcher = {}
        for entry in existing_entries:
            by_matcher[entry.get("matcher", "")] = entry
        for entry in entries:
            by_matcher[entry.get("matcher", "")] = entry  # harness hook 覆盖同 matcher
        existing_hooks[hook_type] = list(by_matcher.values())
    settings["hooks"] = existing_hooks

    try:
        local_settings_path.parent.mkdir(parents=True, exist_ok=True)
        local_settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2))
        print("  ✅ hooks 配置已写入 .claude/settings.local.json (fallback)")
        return True
    except Exception as e:
        print("  ❌ hooks 配置写入失败: {}".format(e))
        return False


def _add_mcp_permissions(user_project_dir: str) -> None:
    """添加 MCP 工具权限到用户项目的 .claude/settings.local.json"""
    local_settings_path = Path(user_project_dir) / ".claude" / "settings.local.json"

    settings = {}
    if local_settings_path.exists():
        try:
            settings = json.loads(local_settings_path.read_text())
        except (json.JSONDecodeError, ValueError):
            settings = {}

    mcp_permissions = [
        # 原有 11 个
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
        # 新增 5 个
        "mcp__harness-cook__harness_profile_list",
        "mcp__harness-cook__harness_profile_load",
        "mcp__harness-cook__harness_skill_list",
        "mcp__harness-cook__harness_skill_register",
        "mcp__harness-cook__harness_bridge_deploy",
    ]

    if "permissions" not in settings:
        settings["permissions"] = {}
    if "allow" not in settings["permissions"]:
        settings["permissions"]["allow"] = []

    existing = set(settings["permissions"]["allow"])
    added = 0
    for perm in mcp_permissions:
        if perm not in existing:
            settings["permissions"]["allow"].append(perm)
            added += 1

    if added > 0:
        try:
            local_settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2))
            print("  ✅ 已添加 {} 个新 MCP 工具权限".format(added))
        except Exception as e:
            print("  ⚠️ MCP 权限写入失败: {}".format(e))


def _step_register_skills(harness_root: str) -> bool:
    """Step 4: 注册 Skills + 初始化 SkillRegistry"""
    print("🎯 [Step 4/5] 注册 Skills...")

    # skills 在 harness 安装目录
    skills_dir = Path(harness_root) / "skills"
    target_base = Path.home() / ".claude" / "skills"

    # 找到所有 skill 目录（有 SKILL.md 的）
    skill_names = []
    for d in skills_dir.iterdir():
        if d.is_dir() and (d / "SKILL.md").exists():
            skill_names.append(d.name)

    if not skill_names:
        print("  ⚠️ 未找到任何 skill（skills/*/SKILL.md）")
        return True

    target_base.mkdir(parents=True, exist_ok=True)

    created = 0
    for name in skill_names:
        target = target_base / name
        source = skills_dir / name

        # 移除旧链接
        if target.exists() or target.is_symlink():
            target.unlink()

        # 创建符号链接
        try:
            target.symlink_to(source)
            created += 1
            print("  ✅ {} → {}".format(target, source))
        except Exception as e:
            print("  ⚠️ {} 创建失败: {}".format(name, e))

    # 初始化 SkillRegistry（注册内置 skills）
    try:
        from harness.skill_registry import get_skill_registry, register_builtin_skills
        registry = get_skill_registry()
        register_builtin_skills(registry)
        print("  ✅ SkillRegistry 已初始化 ({} 个内置 skills)".format(len(registry.list_active())))
    except Exception as e:
        print("  ⚠️ SkillRegistry 初始化失败: {}（不影响符号链接）".format(e))

    print("  已注册 {} 个 skill".format(created))
    return created > 0


def _step_initialize(user_project_dir: str, harness_root: str, profile_name: str = "default", adapter_name: Optional[str] = None) -> bool:
    """Step 5: 在用户项目目录初始化 .harness 目录 + 复制 profile + 写入 .harness/env + 写入 adapter 标记

    核心理念：内置 profile 是模板帮初始化，.harness/profiles/ 是用户可编辑的工作副本。
    编排才是目的！用户可以直接编辑 .harness/profiles/ 下的 YAML，修改比内置更灵活。

    adapter_name 写入两个位置：
      - .harness/active_adapter 标记文件（项目级持久化）
      - .harness/env 中 HARNESS_ADAPTER 行（机器级持久化，gitignored）
    """
    print("📁 [Step 5/5] 初始化 .harness 目录...")

    harness_dir = Path(user_project_dir) / ".harness"
    audit_dir = harness_dir / "audit"
    profiles_dir = harness_dir / "profiles"

    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
        profiles_dir.mkdir(parents=True, exist_ok=True)
        print("  ✅ .harness/ 目录结构已创建")

        # ── 复制内置 profile 到 .harness/profiles/（方便用户直接编辑）──
        builtin_dir = Path(harness_root) / "packages" / "core" / "harness" / "profiles"
        copied_files = []

        # 复制选中的 profile（如果 .harness/profiles/ 下不存在同名文件）
        target_profile = profiles_dir / f"{profile_name}.yaml"
        builtin_profile = builtin_dir / f"{profile_name}.yaml"
        if not target_profile.exists() and builtin_profile.exists():
            shutil.copy2(builtin_profile, target_profile)
            copied_files.append(f"profile: {profile_name}")
        elif builtin_profile.exists():
            print("  📋 .harness/profiles/{name}.yaml 已存在，保留用户版本（不覆盖）".format(name=profile_name))
        else:
            print("  ⚠️ 内置 profile '{name}' 不存在，跳过复制".format(name=profile_name))

        if copied_files:
            print("  ✅ 已复制: {}".format(", ".join(copied_files)))
            print("  💡 .harness/profiles/ 下的文件可直接编辑——内置只是模板，编排才是目的！")

        # ── 写入 .harness/env 文件（机器级配置，gitignored）──
        env_file = harness_dir / "env"
        profile_comment = "# 仅初始化时生效，日常编辑 .harness/profiles/*.yaml 即可"
        adapter_comment = "# 仅初始化时生效，日常编辑 .harness/active_adapter 或用 --agent 切换"
        env_lines = [
            "# harness-cook 运行时配置（harness activate 写入，gitignored）",
            "HARNESS_COOK_ROOT={}".format(harness_root),
            "HARNESS_PROFILE={}  {}".format(profile_name, profile_comment),
            "HARNESS_ADAPTER={}  {}".format(adapter_name or "claude-code", adapter_comment),
        ]
        env_file.write_text("\n".join(env_lines) + "\n")
        print("  ✅ .harness/env 已写入: profile={}".format(profile_name))

        # ── 写入 .harness/active_profile 标记文件 ──
        marker_file = harness_dir / "active_profile"
        marker_file.write_text(profile_name, encoding="utf-8")
        print("  ✅ .harness/active_profile 已写入: {}".format(profile_name))

        # ── 写入 .harness/active_adapter 标记文件 ──
        resolved_adapter = adapter_name or "claude-code"
        adapter_marker = harness_dir / "active_adapter"
        adapter_marker.write_text(resolved_adapter, encoding="utf-8")
        print("  ✅ .harness/active_adapter 已写入: {}".format(resolved_adapter))

        # ── 更新 .gitignore ──
        gitignore_path = Path(user_project_dir) / ".gitignore"
        gitignore_entries = []
        if gitignore_path.exists():
            gitignore_entries = gitignore_path.read_text().splitlines()

        # .harness/env → gitignore（不同开发者 clone 位置不同）
        # .harness/audit/ → gitignore（运行时数据）
        # .harness/profiles/ → 不 gitignore（用户可编辑的工作副本，团队可能共享）
        env_entries = [".harness/env", ".harness/audit/"]
        for entry in env_entries:
            if entry not in gitignore_entries:
                gitignore_entries.append(entry)

        gitignore_path.write_text("\n".join(gitignore_entries) + "\n")
        print("  ✅ .gitignore 已更新")

        # ── 知识库种子注入：让用户第一次用就不空 ──
        _seed_knowledge(user_project_dir)

        return True
    except Exception as e:
        print("  ❌ 初始化失败: {}".format(e))
        return False


def _seed_knowledge(user_project_dir: str) -> None:
    """知识库种子注入——从项目结构自动提取基础知识，让用户第一次用就不空

    自动扫描：
    - 目录层级 → 架构知识
    - 依赖文件 → 依赖知识
    - 项目名称 → 术语表知识
    - 通用建议 → 风险/约定知识
    """
    print("  🌱 知识库种子注入...")

    try:
        from harness.knowledge import LocalKnowledgeProvider, KnowledgeEntry, KnowledgeType, KnowledgeScope
    except ImportError:
        print("  ⏭️ harness.knowledge 不可用，跳过种子注入")
        return

    provider = LocalKnowledgeProvider(project_name="default")
    provider.initialize()

    # 如果已有条目 → 不覆盖，跳过
    if len(provider._entries) > 0:
        print("  ⏭️ 知识库已有 {} 条数据，跳过种子注入".format(len(provider._entries)))
        return

    seeds = []

    # ── 从项目目录结构提取 ──
    project_path = Path(user_project_dir)
    project_name = project_path.name or "unknown-project"

    # 1. 项目架构：从顶层目录结构推断
    top_dirs = [d.name for d in project_path.iterdir() if d.is_dir() and not d.name.startswith(".")]
    arch_summary = "项目 {}: 顶层目录 {}".format(project_name, ", ".join(top_dirs[:8]) if top_dirs else "（无子目录）")
    seeds.append(KnowledgeEntry(
        type=KnowledgeType.ARCHITECTURE,
        scope=KnowledgeScope.PROJECT,
        title="{} 项目架构概览".format(project_name),
        content=arch_summary,
        tags=["架构", "自动扫描"],
        confidence=0.6,
        source="activate-seed",
    ))

    # 2. 依赖关系：检测常见依赖文件
    dep_files = ["package.json", "requirements.txt", "pyproject.toml", "go.mod", "pom.xml", "Cargo.toml"]
    found_deps = [f for f in dep_files if (project_path / f).exists()]
    if found_deps:
        dep_content = "项目使用依赖管理文件: {}".format(", ".join(found_deps))
        seeds.append(KnowledgeEntry(
            type=KnowledgeType.DEPENDENCY,
            scope=KnowledgeScope.PROJECT,
            title="{} 依赖管理".format(project_name),
            content=dep_content,
            tags=["依赖", "自动扫描"],
            confidence=0.7,
            source="activate-seed",
        ))

    # 3. 编码约定：通用最佳实践
    seeds.append(KnowledgeEntry(
        type=KnowledgeType.CONVENTION,
        scope=KnowledgeScope.PROJECT,
        title="编码约定建议",
        content="变量命名用 camelCase/snake_case（按语言惯例），提交信息用 Conventional Commits，代码注释用中文",
        tags=["约定", "最佳实践"],
        confidence=0.5,
        source="activate-seed",
    ))

    # 4. 风险提示：常见风险提醒
    seeds.append(KnowledgeEntry(
        type=KnowledgeType.RISK,
        scope=KnowledgeScope.PROJECT,
        title="常见风险提醒",
        content="注意: 用户输入需 sanitize（防 XSS）、敏感信息不入代码（用 env）、API 限流防 DDoS",
        tags=["风险", "安全"],
        confidence=0.5,
        source="activate-seed",
    ))

    # 5. 术语表：harness-cook 专有术语
    seeds.append(KnowledgeEntry(
        type=KnowledgeType.GLOSSARY,
        scope=KnowledgeScope.PROJECT,
        title="harness-cook 术语表",
        content="Gate=门禁审批, Guardrails=护栏检测, Profile=职能模板, DAG=有向无环图, Skill=插槽点技能, Hook=钩子回调",
        tags=["术语表", "harness"],
        confidence=0.9,
        source="activate-seed",
    ))

    # ── 写入 ──
    for entry in seeds:
        provider.put(entry)  # put() 已内置 auto_save，无需手动 _save_to_disk

    print("  ✅ 已注入 {} 条种子知识（类型: 架构/依赖/约定/风险/术语表）".format(len(seeds)))
    print("  💡 使用 harness knowledge list 查看全部条目")


def cmd_activate(args) -> int:
    """harness activate 命令执行"""
    harness_root = _get_harness_root()
    user_project_dir = _get_user_project_dir()

    # profile 参数（默认值: default）
    profile_name = getattr(args, "profile", "default") or "default"

    # adapter 参数（--agent CLI 参数，最高优先级）
    # None 时由 resolve_active_adapter 从优先级链推导
    cli_adapter = getattr(args, "agent", None)

    # 如果 CLI 传了 --agent，立即作为最终适配器名称
    # 否则走优先级链（env > env file > marker > profile > default）
    if cli_adapter:
        adapter_name = cli_adapter
    else:
        try:
            from harness.config import resolve_active_adapter
            adapter_name = resolve_active_adapter(
                harness_dir=Path(user_project_dir) / ".harness",
                profile_adapter=None,  # 还没加载 profile，后续 _step_configure_hooks 会再次解析
            )
        except ImportError:
            adapter_name = None

    print("=" * 60)
    print("  harness-cook 一键激活")
    print("=" * 60)
    print("harness 安装目录: {}".format(harness_root))
    print("用户项目目录:     {}".format(user_project_dir))
    print("Profile:          {}".format(profile_name))
    print("Adapter:          {}".format(adapter_name or "(将由 Profile 推导)"))
    print()

    results = {}

    if not args.skip_install:
        results["install"] = _step_install_core(harness_root)
    else:
        print("⏭️ [Step 1/5] 跳过核心包安装")

    if not args.skip_mcp:
        results["mcp"] = _step_configure_mcp(harness_root, user_project_dir, adapter_name)
    else:
        print("⏭️ [Step 2/5] 跳过 MCP Server 配置")

    if not args.skip_hooks:
        results["hooks"] = _step_configure_hooks(harness_root, user_project_dir, profile_name, adapter_name)
    else:
        print("⏭️ [Step 3/5] 跳过 hooks 配置")

    if not args.skip_skills:
        results["skills"] = _step_register_skills(harness_root)
    else:
        print("⏭️ [Step 4/5] 跳过 Skills 注册")

    if not args.skip_init:
        results["init"] = _step_initialize(user_project_dir, harness_root, profile_name, adapter_name)
    else:
        print("⏭️ [Step 5/5] 跳过初始化")

    # 汇总
    print()
    print("=" * 60)
    print("  激活结果汇总")
    print("=" * 60)
    for step, ok in results.items():
        icon = "✅" if ok else "❌"
        print("  {} {}".format(icon, step))

    all_ok = all(results.values())
    if all_ok:
        print()
        print("🎉 harness-cook 已激活！请重启 Claude Code 以使 hooks 和 MCP 生效。")
    else:
        print()
        print("⚠️ 部分步骤未成功，请检查上方输出。")

    print("=" * 60)
    return 0 if all_ok else 1


def add_activate_args(subparsers):
    """注册 activate 子命令到 argparse"""
    activate_parser = subparsers.add_parser(
        "activate",
        help="一键激活 harness-cook 所有能力",
        description="安装核心包 + 配置 MCP + 配置 hooks + 注册 skills + 初始化目录",
    )
    activate_parser.add_argument(
        "--profile",
        default="default",
        help="选择 Profile 职能模板（default/basic/frontend/backend/product/enterprise/ui），"
             "默认: default。激活后复制到 .harness/profiles/ 供用户编辑",
    )
    activate_parser.add_argument(
        "--agent",
        default=None,
        choices=["claude-code", "copilot-cli", "hermes", "cursor", "openai"],
        help="选择 Agent 适配器（部署目标平台），默认: 由优先级链推导"
             "（HARNESS_ADAPTER env > .harness/env > .harness/active_adapter > Profile adapter 字段 > claude-code）。"
             "显式指定 --agent=hermes 可覆盖所有自动推导",
    )
    activate_parser.add_argument(
        "--skip-install",
        action="store_true",
        help="跳过 pip install -e packages/core",
    )
    activate_parser.add_argument(
        "--skip-mcp",
        action="store_true",
        help="跳过 MCP Server 配置",
    )
    activate_parser.add_argument(
        "--skip-hooks",
        action="store_true",
        help="跳过 hooks 配置",
    )
    activate_parser.add_argument(
        "--skip-skills",
        action="store_true",
        help="跳过 Skills 注册",
    )
    activate_parser.add_argument(
        "--skip-init",
        action="store_true",
        help="跳过初始化（.harness/ 目录创建）",
    )

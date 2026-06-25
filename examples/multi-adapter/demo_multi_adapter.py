#!/usr/bin/env python3
"""
多 Adapter 映射对比 Demo

用【同一份 profile.yaml】喂给所有已注册 adapter + 一个极简自定义 adapter，
并排对比：
  1. AdapterRegistry 自动发现 + 新 agent 手动接入
  2. 同一 hook_point 在各 adapter 的原生事件名映射差异
  3. 同一 hooks 配置 → 各 adapter translate_hooks 产出结构差异
  4. supports_hooks 分层（有-hooks 自动强制 vs 无-hooks MCP 降级）+ S-5 执行策略
  5. F 方案 translate_gates_to_hooks 的 per-adapter 差异（仅 claude-code 产出 gate hook）
  6. bridge.deploy(adapter_name=...) 端到端：指定不同 agent → 产出不同平台配置文件

运行:
  cd packages/core
  PYTHONPATH=. python3 ../../examples/multi-adapter/demo_multi_adapter.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# ── 定位 harness-cook 根 + 加 core 到 path（仿 examples/openai-adapter）──
_HARNESS_ROOT = Path(__file__).resolve().parent.parent.parent
_CORE = _HARNESS_ROOT / "packages" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

# 引入同目录的自定义 adapter
sys.path.insert(0, str(Path(__file__).resolve().parent))
from my_agent_adapter import MyAgentAdapter  # noqa: E402

from harness.adapters.claude_code import ClaudeCodeAdapter  # noqa: E402
from harness.adapters.copilot_cli import CopilotCLIAdapter  # noqa: E402
from harness.adapters.cursor import CursorAdapter  # noqa: E402
from harness.adapters.hermes import HermesAdapter  # noqa: E402
from harness.adapters.openai import OpenAIAdapter  # noqa: E402
from harness.bridge import HarnessBridge, get_adapter_registry  # noqa: E402
from harness.config import ProfileLoader  # noqa: E402

PROFILE_DIR = Path(__file__).resolve().parent
HARNESS_ROOT_ABS = str(_HARNESS_ROOT)

# demo 关注的 hook_point（覆盖会话级/任务级/异常级/门禁级）
DEMO_HOOK_POINTS = ["session_start", "pre_execute", "post_execute", "on_error",
                    "on_gate_pass", "on_gate_fail"]

SEP = "=" * 72


def _load_profile():
    """加载共享 profile.yaml（ProfileLoader 按 name 加载，文件须命名 profile.yaml）。"""
    loader = ProfileLoader(profiles_dir=str(PROFILE_DIR))
    return loader.load("profile")


def _all_adapters():
    """返回 demo 要对比的 adapter 实例列表（5 内置 + 1 自定义）。"""
    return [
        ClaudeCodeAdapter(),
        CopilotCLIAdapter(),
        CursorAdapter(),
        HermesAdapter(),
        OpenAIAdapter(),
        MyAgentAdapter(),
    ]


def demo_discovery():
    """1. AdapterRegistry 自动发现 + 新 agent 手动接入。"""
    print(f"\n{SEP}\n1️⃣  Adapter 发现与注册\n{SEP}")
    registry = get_adapter_registry()
    discovered = registry.discover()
    print(f"✓ discover() 自动发现内置 adapter: {discovered}")

    # 模拟"未来新 agent 接入"：手动 register（比依赖 .harness/adapters/ 的
    # cwd 扫描更可靠；生产里也可放 .harness/adapters/ 被 discover 扫到）
    if not registry.has("my-agent"):
        registry.register("my-agent", MyAgentAdapter)
        print("✓ 手动 register('my-agent', MyAgentAdapter) — 新 agent 已接入")
    else:
        print("✓ my-agent 已在注册表")

    all_names = registry.list_adapters()
    print(f"\n📋 当前可用 adapter（{len(all_names)} 个）: {all_names}")
    print("\n💡 结论：新 agent 平台只需实现 IAgentAdapter 几个方法 + register，"
          "即可被 bridge.deploy(adapter_name=...) 端到端翻译，无需改 core。")


def demo_hook_point_map_comparison():
    """2. 同一 hook_point 在各 adapter 的原生事件名映射差异。"""
    print(f"\n{SEP}\n2️⃣  hook_point → 原生事件名 映射差异（per-adapter）\n{SEP}")
    adapters = _all_adapters()
    names = [a.name for a in adapters]

    # 表头
    header = f"{'hook_point':<16} " + " ".join(f"{n:<22}" for n in names)
    print(header)
    print("-" * len(header))
    for hp in DEMO_HOOK_POINTS:
        cells = []
        for a in adapters:
            # hook_point_map 是 adapter 各自的映射表；无映射记为 —
            mapping = a.hook_point_map
            cells.append(mapping.get(hp, "—") or "—")
        print(f"{hp:<16} " + " ".join(f"{c:<22}" for c in cells))

    print("\n💡 结论：同一 session_start，claude-code→SessionStart、hermes→on_session_start、"
          "openai 无此映射（只 3 个）、my-agent→my_agent_on_start。映射完全 per-adapter，"
          "on_gate_pass/on_gate_fail 在多数 adapter 无映射（对不上原生事件）。")


def demo_translate_hooks_comparison():
    """3. 同一 hooks 配置 → 各 adapter translate_hooks 产出结构差异。"""
    print(f"\n{SEP}\n3️⃣  translate_hooks 产出结构差异（同一 profile.hooks 输入）\n{SEP}")
    profile = _load_profile()
    adapters = _all_adapters()

    for a in adapters:
        out = a.translate_hooks(profile.hooks, harness_root=HARNESS_ROOT_ABS)
        # 产出顶层 key 体现结构差异
        top_keys = list(out.keys()) if isinstance(out, dict) else f"<{type(out).__name__}>"
        # 统计规模
        try:
            size = sum(len(v) if isinstance(v, list) else len(v) if isinstance(v, dict) else 1
                       for v in out.values()) if isinstance(out, dict) else 0
        except Exception:
            size = "?"

        print(f"\n── {a.name} (supports_hooks={a.supports_hooks}) ──")
        print(f"  顶层 keys: {top_keys}")
        print(f"  产出预览（截断 300 字符）:")
        preview = json.dumps(out, ensure_ascii=False, default=str)[:300]
        print(f"  {preview}")

    print("\n💡 结论：结构完全不同——claude-code 产原生 hook entries（PreToolUse/PostToolUse），"
          "copilot-cli 产 {hooks, mcpServers}，cursor/hermes/my-agent 产 {mcpServers, harness_metadata}"
          "（hook 不执行只保留），openai 产 {functions}（function calling）。")


def demo_supports_hooks_stratification():
    """4. supports_hooks 分层 + S-5 执行策略。"""
    print(f"\n{SEP}\n4️⃣  supports_hooks 分层与 S-5 执行策略\n{SEP}")
    adapters = _all_adapters()

    header = f"{'adapter':<14} {'supports_hooks':<16} {'execution_strategy':<16} {'降级路径'}"
    print(header)
    print("-" * 78)
    for a in adapters:
        caps = a.get_capabilities()
        strategy = caps.resolve_execution_strategy()
        strategy_val = getattr(strategy, "value", str(strategy))
        if a.supports_hooks:
            degrade = "hooks 自动强制执行（无需降级）"
        else:
            degrade = "MCP 工具 + prompt + git hook 降级"
        print(f"{a.name:<14} {str(a.supports_hooks):<16} {strategy_val:<16} {degrade}")

    print("\n💡 结论：claude-code / copilot-cli（supports_hooks=True）gate 与 hooks 自动强制执行；"
          "cursor / openai / hermes / my-agent（False）走 MCP+prompt+git 降级（S-5 FALLBACK）。")


def demo_gates_to_hooks_per_adapter():
    """5. F 方案 translate_gates_to_hooks 的 per-adapter 差异。"""
    print(f"\n{SEP}\n5️⃣  translate_gates_to_hooks（F 方案）per-adapter 差异\n{SEP}")
    profile = _load_profile()
    adapters = _all_adapters()

    # 运行时三种形态（事实来自 base.py:114 IAgentAdapter Protocol 默认方法体为 `...`）：
    #   - 覆盖并产出非空：claude-code（claude_code.py:372 覆盖）→ PreToolUse[Write|Edit]
    #   - 继承默认空实现：copilot-cli/cursor/hermes/openai（显式继承 IAgentAdapter，未覆盖
    #     → 继承 base 的 `...` 体 → 调用隐式返回 None）
    #   - 完全无此方法：my-agent（不继承 IAgentAdapter）→ getattr 返回 None
    header = f"{'adapter':<14} {'方法来源':<16} {'产出'}"
    print(header)
    print("-" * 72)
    for a in adapters:
        fn = getattr(a, "translate_gates_to_hooks", None)
        if fn is None:
            print(f"{a.name:<14} {'无（未继承）':<16} getattr→None → bridge 跳过，gate 走 prompt+git 降级")
            continue
        out = fn(profile.gate_checks, profile.default_gate_mode,
                 harness_root=HARNESS_ROOT_ABS)
        if not out:
            # 继承的 base 方法体为 `...`，隐式 return None（用 {out!r} 如实展示真实返回值）
            print(f"{a.name:<14} {'继承默认':<16} 调用返回 {out!r}（基类方法体为 `...`）"
                  f"→ 不产出 gate hook，走降级")
        else:
            matchers = []
            for ht, entries in out.items():
                for e in entries:
                    matchers.append(f"{ht}[{e.get('matcher', '')}]")
            print(f"{a.name:<14} {'覆盖实现':<16} {', '.join(matchers)} → 写文件前自动 deny 违规")

    print("\n💡 结论：base.py:114 在 IAgentAdapter Protocol 上定义了 translate_gates_to_hooks，"
          "方法体为 `...`（调用隐式返回 None）。显式继承 IAgentAdapter 的 adapter 会继承这个"
          "默认空实现——只有 claude-code 覆盖了它（claude_code.py:372）→ 产出 "
          "PreToolUse[Write|Edit]→gate 脚本，写文件前自动 deny 违规；"
          "copilot-cli/cursor/hermes/openai 继承默认 → 调用返回 None，不产出 gate hook；"
          "my-agent 不继承 IAgentAdapter → getattr 直接 None。三者行为等效：只有 claude-code "
          "真正自动拦截，其余 gate 走 prompt+git 降级（S-5 FALLBACK）。F 方案是 per-adapter 的"
          "——有-hooks 平台覆盖此方法即获得自动拦截，无需改 core。")


def demo_bridge_deploy_by_adapter():
    """6. bridge.deploy(adapter_name=...) 端到端：指定不同 agent → 不同配置文件。"""
    print(f"\n{SEP}\n6️⃣  bridge.deploy 端到端：adapter_name → 平台配置文件\n{SEP}")
    profile = _load_profile()
    bridge = HarnessBridge()

    # openai 的 get_settings_path 返回 ""（无本地配置文件）→ deploy 写文件会出错，
    # 与官方 examples/openai-adapter 一致：只展示 translate_hooks，不 deploy。
    deploy_targets = ["claude-code", "copilot-cli", "cursor", "hermes", "my-agent"]

    for name in deploy_targets:
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                if name == "hermes":
                    # hermes get_settings_path 默认写全局 ~/.hermes/config.yaml，
                    # 重定向到临时目录避免污染全局
                    os.environ["HERMES_CONFIG_PATH"] = os.path.join(tmpdir, "config.yaml")
                result = bridge.deploy(
                    profile,
                    project_dir=tmpdir,
                    harness_root=HARNESS_ROOT_ABS,
                    adapter_name=name,
                )
                settings_path = Path(result.get("settings_path", ""))
                exists = settings_path.exists()
                print(f"\n── adapter={name} ──")
                print(f"  status={result.get('status')}  supports_hooks={result.get('supports_hooks')}"
                      f"  hooks_deployed={result.get('hooks_deployed')}"
                      f"  execution_strategy={result.get('execution_strategy')}")
                print(f"  配置文件: {settings_path}")
                print(f"  文件已生成: {'✅' if exists else '❌'}"
                      f"{f'  大小={settings_path.stat().st_size}B' if exists else ''}")
            except Exception as e:
                print(f"\n── adapter={name} ── ⚠️ deploy 跳过/失败: {e}")
            finally:
                if name == "hermes":
                    os.environ.pop("HERMES_CONFIG_PATH", None)

    # openai 单独展示（只 translate_hooks，不 deploy）
    print(f"\n── adapter=openai（get_settings_path 返回空串，不写文件，仅展示 translate_hooks）──")
    oa = OpenAIAdapter()
    out = oa.translate_hooks(profile.hooks, harness_root=HARNESS_ROOT_ABS)
    funcs = out.get("functions", []) if isinstance(out, dict) else []
    print(f"  产出 {len(funcs)} 个 function calling 定义，示例: "
          f"{json.dumps(funcs[0], ensure_ascii=False, default=str)[:200] if funcs else '无'}")

    print("\n💡 结论：同一 profile + bridge.deploy(adapter_name=X) → 各 adapter 把配置写到"
          "各自原生路径（.claude/settings.json / .copilot/config.json / .cursor/mcp.json / "
          ".myagent/config.json / hermes 全局）。activate 时指定 agent，deploy 即针对它映射。"
          "全部在临时目录内，不污染真实项目（hermes 用 HERMES_CONFIG_PATH 重定向，openai 无本地文件跳过）。")


def main():
    # 行缓冲：管道下 stdout 默认块缓冲，会让框架的 stderr 告警全堆到输出开头；
    # 改行缓冲后告警与各段按时间顺序交错，便于看清每段触发了什么框架行为。
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    print("\n🚀 多 Adapter 映射对比 Demo")
    print(f"   共享 profile: {PROFILE_DIR / 'profile.yaml'}")
    print(f"   harness root: {HARNESS_ROOT_ABS}")
    print("   ⚠️ 预告：本 demo 不初始化 SkillRegistry，框架会对 profile 中的 skill_id "
          "报 E-10、对 on_gate_pass/on_gate_fail 报 'Unknown hook point — skipping'。")
    print("        这些都是【预期告警】（框架 fail-open 继续），正是要展示的"
          "'skill 悬空容错'与'对不上原生事件的插槽被跳过'，不影响对比结论。")

    demo_discovery()
    demo_hook_point_map_comparison()
    demo_translate_hooks_comparison()
    demo_supports_hooks_stratification()
    demo_gates_to_hooks_per_adapter()
    demo_bridge_deploy_by_adapter()

    print(f"\n{SEP}\n✅ 所有对比段运行完成\n{SEP}")
    print("\n📚 关键结论：")
    print("  • 映射是 per-adapter 的：每个 adapter 自带 hook_point_map + translate_hooks")
    print("  • supports_hooks 分层：有-hooks 自动强制，无-hooks 走 MCP+prompt+git 降级（S-5）")
    print("  • F 方案 gate hook 也是 per-adapter：仅 claude-code 覆盖并产出 PreToolUse[Write|Edit]，"
          "其余继承默认空实现或未继承 → 走降级")
    print("  • 新 agent 接入：实现 IAgentAdapter 几个方法 + register，无需改 core")
    print("  • activate 指定 agent → bridge.deploy(adapter_name) 端到端按它映射")


if __name__ == "__main__":
    main()

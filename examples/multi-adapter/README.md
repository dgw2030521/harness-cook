# Multi-Adapter 映射对比 Demo

> **同一份 Profile → 喂遍所有 adapter + 一个极简自定义 adapter，并排对比"映射差异 + 产出差异 + supports_hooks 分层降级 + F 方案 gate hook 的 per-adapter 差异"**。

## 定位

`examples/` 下已有 5 个 per-adapter 孤立 demo（`openai-adapter`/`hermes-adapter`/`hermes-bridge`/`copilot-cli-bridge`/`cursor-bridge`），每个各自硬编码一份 hook 配置单独展示一个 adapter。**本 demo 把多 adapter 放一起**：用同一份 `profile.yaml` 喂给所有已注册 adapter + 一个极简自定义 adapter（`my-agent`），并排展示差异，并端到端跑 `bridge.deploy(adapter_name=...)` 产出不同平台配置文件。

支撑的架构主张：**未来新 agent 有不同的 hook 标准（事件名/格式/触发机制都不同），只需在 adapter 里编写映射，activate 指定对应 agent 即可针对它映射**——这条链路现在就支持，本 demo 即为实证。

## 用法

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/multi-adapter/demo_multi_adapter.py
```

无需 `pip install`（只消费 harness core 现有 API）。全部 `bridge.deploy` 在 `tempfile.TemporaryDirectory()` 内跑，不污染真实项目（hermes 用 `HERMES_CONFIG_PATH` 重定向到临时目录，openai 无本地配置文件只展示 `translate_hooks`）。

> ⚠️ **预期告警**：本 demo 不初始化 `SkillRegistry`，框架会对 `profile.yaml` 中的 `skill_id`（auto-audit/auto-fix）报 `E-10`、对 `on_gate_pass`/`on_gate_fail` 报 `Unknown hook point — skipping`。这些都是**预期行为**（框架 fail-open 继续），正是要展示的"skill 悬空容错"与"对不上原生事件的插槽被跳过"，不影响对比结论。脚本开头已预告，并启用 stdout 行缓冲让告警与各段按时间顺序交错。

## 6 段对比

| # | 段 | 展示什么 |
|---|----|---------|
| 1 | Adapter 发现与注册 | `discover()` 自动发现 5 个内置 adapter + 手动 `register("my-agent", MyAgentAdapter)` 演示新 agent 接入 |
| 2 | hook_point → 原生事件名映射差异 | 同一 `session_start`/`pre_execute`/`on_error` 在各 adapter 映射成不同原生事件名（`SessionStart`/`on_session_start`/`function_call_before`/`my_agent_on_start`…）；`on_gate_pass`/`on_gate_fail` 在所有 adapter 都无映射（对不上原生事件） |
| 3 | translate_hooks 产出结构差异 | 同一 `profile.hooks` 喂各 adapter，产出结构完全不同：claude-code 产原生 hook entries、copilot-cli 产 `{hooks, mcpServers}`、cursor/hermes/my-agent 产 `{mcpServers, harness_metadata}`（hook 不执行只保留）、openai 产 `{functions}`（function calling） |
| 4 | supports_hooks 分层 + S-5 执行策略 | claude-code/copilot-cli（`supports_hooks=True`）gate 与 hooks 自动强制执行；cursor/openai/hermes/my-agent（`False`）走 MCP+prompt+git 降级（`resolve_execution_strategy()` 返回 `fallback`） |
| 5 | translate_gates_to_hooks（F 方案）per-adapter 差异 | `base.py:114` 在 `IAgentAdapter` Protocol 上定义此方法、方法体为 `...`（调用返回 None）。只有 claude-code 覆盖它（`claude_code.py:372`）→ 产出 `PreToolUse[Write|Edit]`→gate 脚本自动 deny；copilot-cli/cursor/hermes/openai 继承默认 → 返回 None；my-agent 不继承 IAgentAdapter → getattr 直接 None。三者行为等效：只有 claude-code 真正自动拦截，其余 gate 走 prompt+git 降级 |
| 6 | bridge.deploy 端到端 | `bridge.deploy(profile, project_dir=tmpdir, harness_root=ABS, adapter_name=name)` 指定不同 adapter 产出不同平台配置文件：`.claude/settings.json` / `.copilot/config.json` / `.cursor/mcp.json` / `.myagent/config.json` / hermes 重定向到 tmpdir |

## 关键结论

- **映射是 per-adapter 的**：每个 adapter 自带 `hook_point_map` + `translate_hooks`，事件名与产出格式都各自定义。
- **supports_hooks 分层**：有-hooks 平台（claude-code/copilot-cli）自动强制执行；无-hooks 平台（cursor/openai/hermes/my-agent）走 MCP+prompt+git 降级（S-5 FALLBACK）。
- **F 方案 gate hook 也是 per-adapter 的**：仅 claude-code 覆盖并产出 `PreToolUse[Write|Edit]`，其余继承默认空实现或未继承 → 走降级。不是全局写死——换一个有-hooks 平台，覆盖 `translate_gates_to_hooks` 即获得自动拦截。
- **新 agent 接入路径**：实现 `IAgentAdapter` 几个方法（`name`/`supports_hooks`/`hook_point_map`/`get_capabilities`/`translate_hooks`/`get_settings_path`/`merge_settings`）+ `register`，即可被 `bridge.deploy(adapter_name=...)` 端到端翻译，**无需改 core**。见 `my_agent_adapter.py`（约 60 行）。
- **activate 指定 agent → 针对它映射**：`bridge.deploy(adapter_name=X)` 按 X 选 adapter，调它的 `translate_hooks`/`translate_gates_to_hooks` 产出 X 平台原生配置。

## 文件清单

| 文件 | 作用 |
|------|------|
| `demo_multi_adapter.py` | 主对比脚本，6 个 `demo_*()` 函数 |
| `profile.yaml` | 共享示例 profile（故意保留 `on_gate_pass`/`on_gate_fail` 展示"对不上原生事件"） |
| `my_agent_adapter.py` | 极简自定义 adapter，演示"未来新 agent 接入"（不继承 IAgentAdapter、`supports_hooks=False`、不覆盖 `translate_gates_to_hooks`） |

## 与其他 adapter demo 的关系

本 demo 是**对比型**（横切多 adapter），其余 5 个是**单 adapter 深入型**（各展一个平台的完整翻译细节）。先跑本 demo 看全局映射差异，再按需跑单 adapter demo 看细节。

## License

MIT

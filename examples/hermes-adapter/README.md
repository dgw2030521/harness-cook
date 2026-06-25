# Hermes 适配器示例

## 概述

本示例展示如何使用 harness-cook 的 Hermes 适配器，将 Profile 配置翻译为 Hermes YAML 配置格式。

## 使用场景

当你需要在 Hermes 中使用 harness-cook 的 hooks 配置时，可以使用 Hermes 适配器自动翻译配置。

## 代码示例

```python
"""
Hermes 适配器使用示例

展示如何将 Profile 配置翻译为 Hermes YAML 配置格式
"""

from harness.adapters.hermes import HermesAdapter
from harness.config import ProfileConfig, GateMode

# 1. 创建 Profile 配置
profile = ProfileConfig(
    name="my-hermes-profile",
    description="Hermes 平台配置",
    default_adapter="hermes",
    hooks={
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
    },
    gates=[
        {
            "id": "no-secrets",
            "category": "security",
            "severity": "critical",
            "description": "禁止硬编码密钥",
        },
    ],
    gate_mode=GateMode.HYBRID,
)

# 2. 创建 Hermes 适配器
adapter = HermesAdapter()

# 3. 翻译 hooks 配置
hermes_config = adapter.translate_hooks(profile.hooks)

print("翻译结果（Hermes YAML 格式）:")
import yaml
print(yaml.dump(hermes_config, allow_unicode=True, default_flow_style=False))

# 4. 导出到文件
adapter.export_yaml(hermes_config, ".hermes/config.yaml")
print("\n✅ 配置已导出到 .hermes/config.yaml")
```

## Hermes 配置格式

Hermes 使用 YAML 配置，主要包含以下部分：

```yaml
version: "1.0"

# 审批配置
approvals:
  mode: smart          # smart=低风险自动，高风险问人
  cron_mode: deny      # cron任务禁止危险操作

# 安全配置
security:
  redact_secrets: true  # 自动脱敏
  tirith_enabled: true  # 安全策略引擎

# 技能配置（从 harness hooks 翻译）
skills:
  - name: hook_session_start
    description: "Hook skill for session_start"
    trigger: on_session_start
    command: "python3 scripts/init.py"
    metadata:
      hook_point: session_start
      type: script

  - name: skill_validate-input
    description: "Skill: validate-input"
    trigger: before_task
    skill_id: validate-input
    metadata:
      hook_point: pre_execute
      type: skill

# 定时任务
cron: []
```

## 运行示例

```bash
cd examples/hermes-adapter
python3 demo_hermes_adapter.py
```

## Hook 点到 Trigger 的映射

| Harness Hook Point | Hermes Trigger |
|-------------------|----------------|
| `session_start` | `on_session_start` |
| `session_end` | `on_session_end` |
| `pre_execute` | `before_task` |
| `post_execute` | `after_task` |
| `on_error` | `on_error` |
| `pre_tool_use` | `before_tool` |
| `post_tool_use` | `after_tool` |

## 在 Hermes 中使用

1. 导出配置：
```bash
python3 demo_hermes_adapter.py
```

2. 在 Hermes 中加载配置：
```bash
hermes config load .hermes/config.yaml
```

3. 验证配置：
```bash
hermes config show
```

## 与其他适配器的对比

| 适配器 | 目标平台 | 输出格式 | 配置文件 |
|--------|----------|----------|----------|
| ClaudeCodeAdapter | Claude Code | settings.json | `.claude/settings.json` |
| OpenAIAdapter | OpenAI | function calling | API 请求参数 |
| HermesAdapter | Hermes | YAML | `.hermes/config.yaml` |

## 扩展自定义适配器

如果需要支持其他平台，可以继承 `IAgentAdapter` 接口：

```python
from harness.adapters.base import IAgentAdapter

class MyCustomAdapter(IAgentAdapter):
    @property
    def name(self) -> str:
        return "my-custom-platform"

    def translate_hooks(self, hooks_config: dict, harness_root: str = None) -> dict:
        # 实现翻译逻辑
        pass

    def get_settings_path(self, project_dir: str) -> str:
        # 返回配置文件路径
        pass

    def merge_settings(self, existing: dict, new_hooks: dict) -> dict:
        # 实现合并逻辑
        pass
```

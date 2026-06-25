# OpenAI 适配器示例

## 概述

本示例展示如何使用 harness-cook 的 OpenAI 适配器，将 Profile 配置翻译为 OpenAI function calling 格式。

## 使用场景

当你需要将 harness-cook 的 hooks 配置迁移到 OpenAI 平台时，可以使用 OpenAI 适配器自动翻译配置。

## 代码示例

```python
"""
OpenAI 适配器使用示例

展示如何将 Profile 配置翻译为 OpenAI function calling 格式
"""

from harness.adapters.openai import OpenAIAdapter
from harness.config import ProfileConfig, GateMode

# 1. 创建 Profile 配置
profile = ProfileConfig(
    name="my-openai-profile",
    description="OpenAI 平台配置",
    default_adapter="openai",
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

# 2. 创建 OpenAI 适配器
adapter = OpenAIAdapter()

# 3. 翻译 hooks 配置
functions_config = adapter.translate_hooks(profile.hooks)

print("翻译结果：")
print(functions_config)

# 输出示例：
# {
#     "functions": [
#         {
#             "name": "hook_session_start",
#             "description": "Hook function for session_start",
#             "parameters": {
#                 "type": "object",
#                 "properties": {
#                     "command": {"type": "string", "description": "Command to execute"},
#                     "context": {"type": "object", "description": "Execution context"},
#                 },
#                 "required": ["command"],
#             },
#             "metadata": {
#                 "hook_point": "session_start",
#                 "command": "python3 scripts/init.py",
#                 "type": "script",
#             },
#         },
#         # ... 其他 functions
#     ],
# }

# 4. 合并到现有配置
existing_config = {
    "model": "gpt-4",
    "temperature": 0.7,
}

merged_config = adapter.merge_settings(existing_config, functions_config)

print("\n合并后的配置：")
print(merged_config)

# 5. 使用合并后的配置调用 OpenAI API
# from openai import OpenAI
# client = OpenAI()
# response = client.chat.completions.create(
#     model=merged_config["model"],
#     messages=[{"role": "user", "content": "Hello!"}],
#     functions=merged_config["functions"],
# )
```

## 运行示例

```bash
cd examples/openai-adapter
python3 demo_openai_adapter.py
```

## 注意事项

1. OpenAI 适配器将 harness-cook 的 hooks 概念映射为 OpenAI 的 function calling 格式
2. 每个 hook 被翻译为一个 function definition
3. 适配器会自动处理参数 schema 和 metadata
4. 可以通过 `merge_settings` 方法将翻译后的 functions 合并到现有配置中

## 与其他适配器的对比

| 适配器 | 目标平台 | 输出格式 |
|--------|----------|----------|
| ClaudeCodeAdapter | Claude Code | settings.json hooks 段 |
| OpenAIAdapter | OpenAI | function calling schema |

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

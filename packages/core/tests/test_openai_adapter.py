"""
OpenAI 适配器测试

测试覆盖：
- Hook 翻译为 OpenAI function calling 格式
- Settings 合并
- 适配器名称
"""

import pytest

from harness.adapters.openai import OpenAIAdapter
from harness.types import ProfileConfig


class TestOpenAIAdapter:
    """OpenAI 适配器测试"""

    def test_adapter_name(self):
        """测试适配器名称"""
        adapter = OpenAIAdapter()
        assert adapter.name == "openai"

    def test_translate_script_hooks(self):
        """测试翻译 script hook"""
        adapter = OpenAIAdapter()
        hooks_config = {
            "session_start": [
                {"type": "script", "command": "python3 init.py"},
            ],
            "post_execute": [
                {"type": "script", "command": "python3 cleanup.py"},
            ],
        }

        result = adapter.translate_hooks(hooks_config)

        assert "functions" in result
        assert len(result["functions"]) == 2

        # 检查第一个 function
        func1 = result["functions"][0]
        assert func1["name"] == "hook_session_start"
        assert func1["metadata"]["command"] == "python3 init.py"
        assert func1["metadata"]["type"] == "script"

        # 检查第二个 function
        func2 = result["functions"][1]
        assert func2["name"] == "hook_post_execute"
        assert func2["metadata"]["command"] == "python3 cleanup.py"

    def test_translate_skill_hooks(self):
        """测试翻译 skill hook"""
        adapter = OpenAIAdapter()
        hooks_config = {
            "pre_execute": [
                {"type": "skill", "skill_id": "auto-audit"},
            ],
        }

        result = adapter.translate_hooks(hooks_config)

        assert "functions" in result
        assert len(result["functions"]) == 1

        func = result["functions"][0]
        assert func["name"] == "skill_auto-audit"
        assert func["metadata"]["skill_id"] == "auto-audit"
        assert func["metadata"]["type"] == "skill"

    def test_translate_empty_hooks(self):
        """测试翻译空 hooks"""
        adapter = OpenAIAdapter()
        hooks_config = {}

        result = adapter.translate_hooks(hooks_config)

        assert "functions" in result
        assert len(result["functions"]) == 0

    def test_merge_settings_new_functions(self):
        """测试合并新 functions"""
        adapter = OpenAIAdapter()

        existing = {"model": "gpt-4"}
        new_hooks = {
            "functions": [
                {"name": "hook_session_start", "parameters": {}},
            ],
        }

        result = adapter.merge_settings(existing, new_hooks)

        assert result["model"] == "gpt-4"
        assert "functions" in result
        assert len(result["functions"]) == 1
        assert result["functions"][0]["name"] == "hook_session_start"

    def test_merge_settings_dedup_functions(self):
        """测试合并时去重 functions"""
        adapter = OpenAIAdapter()

        existing = {
            "functions": [
                {"name": "hook_session_start", "parameters": {}},
            ],
        }
        new_hooks = {
            "functions": [
                {"name": "hook_session_start", "parameters": {}},  # 重复
                {"name": "hook_post_execute", "parameters": {}},
            ],
        }

        result = adapter.merge_settings(existing, new_hooks)

        # 应该去重，只保留 2 个
        assert len(result["functions"]) == 2
        names = [f["name"] for f in result["functions"]]
        assert "hook_session_start" in names
        assert "hook_post_execute" in names

    def test_get_settings_path(self):
        """测试获取配置文件路径"""
        adapter = OpenAIAdapter()
        path = adapter.get_settings_path("/tmp/project")

        # OpenAI 没有本地配置文件，返回空字符串
        assert path == ""

    def test_function_parameters_schema(self):
        """测试 function 参数 schema"""
        adapter = OpenAIAdapter()
        hooks_config = {
            "session_start": [
                {"type": "script", "command": "python3 init.py"},
            ],
        }

        result = adapter.translate_hooks(hooks_config)
        func = result["functions"][0]

        # 检查 parameters schema
        assert "parameters" in func
        assert func["parameters"]["type"] == "object"
        assert "properties" in func["parameters"]
        assert "command" in func["parameters"]["properties"]
        assert "context" in func["parameters"]["properties"]
        assert "required" in func["parameters"]
        assert "command" in func["parameters"]["required"]

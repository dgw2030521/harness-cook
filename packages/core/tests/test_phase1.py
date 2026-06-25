"""
Phase 1 测试: SDK接入层 — AgentConstraints + @harness_agent 装饰器

覆盖:
- AgentConstraints: 字段默认值、validate_file_access、validate_command、summary
- ConstraintViolation: 创建和timestamp自动填充
- DecoratedAgent: 包装函数、execute带约束检查、estimate_tokens
- @harness_agent装饰器: 自动注册、事件发布、参数传递
- AgentType: 角色分类枚举
"""

import pytest
import uuid
from harness.types import (
    AgentCapability, AgentType, AgentDefinition, IExecutableAgent,
    TaskResult, Artifact, GateMode
)
from harness.constraints import AgentConstraints, AgentPriority, ConstraintViolation, ConstraintSeverity, ConstraintType
from harness.decorators import harness_agent, DecoratedAgent
from harness.registry import AgentRegistry, get_registry
from harness.bus import EventBus, BusEventType, BusEvent, get_bus


# ── AgentConstraints ──

class TestAgentConstraintsDefaults:
    """约束默认值——无限制Agent"""

    def test_default_values(self):
        c = AgentConstraints()
        assert c.file_patterns == []
        assert c.max_changes is None
        assert c.require_review is False
        assert c.no_destructive is False
        assert c.timeout is None
        assert c.priority == AgentPriority.NORMAL
        assert c.allowed_commands == []
        assert c.max_tokens is None
        assert c.description == ""

    def test_no_constraints_allows_everything(self):
        """无约束 → 任何文件/命令都允许"""
        c = AgentConstraints()
        assert c.validate_file_access("anything.py") is True
        assert c.validate_command("rm -rf /") is True
        assert c.is_destructive_blocked() is False
        assert c.needs_review() is False

    def test_summary_no_constraints(self):
        c = AgentConstraints()
        assert c.summary() == "无约束"


class TestAgentConstraintsFilePatterns:
    """文件模式约束"""

    def test_matching_pattern(self):
        c = AgentConstraints(file_patterns=["*.py", "*.ts"])
        assert c.validate_file_access("main.py") is True
        assert c.validate_file_access("app.ts") is True

    def test_non_matching_pattern(self):
        c = AgentConstraints(file_patterns=["*.py"])
        assert c.validate_file_access("main.js") is False
        assert c.validate_file_access("config.yaml") is False

    def test_glob_pattern(self):
        c = AgentConstraints(file_patterns=["src/**/*.py"])
        assert c.validate_file_access("src/harness/engine.py") is True
        assert c.validate_file_access("tests/test_core.py") is False

    def test_empty_patterns_allows_all(self):
        c = AgentConstraints(file_patterns=[])
        assert c.validate_file_access("anything.go") is True


class TestAgentConstraintsCommands:
    """命令白名单约束"""

    def test_allowed_command(self):
        c = AgentConstraints(allowed_commands=["pytest", "git status"])
        assert c.validate_command("pytest -v tests/") is True
        assert c.validate_command("git status") is True

    def test_disallowed_command(self):
        c = AgentConstraints(allowed_commands=["pytest"])
        assert c.validate_command("npm test") is False
        assert c.validate_command("rm -rf /") is False

    def test_command_with_args(self):
        c = AgentConstraints(allowed_commands=["pytest"])
        assert c.validate_command("pytest --tb=short -v") is True

    def test_empty_commands_allows_all(self):
        c = AgentConstraints(allowed_commands=[])
        assert c.validate_command("dangerous_cmd") is True


class TestAgentConstraintsDestructive:
    """破坏性操作约束"""

    def test_no_destructive_blocks(self):
        c = AgentConstraints(no_destructive=True)
        assert c.is_destructive_blocked() is True

    def test_destructive_allowed(self):
        c = AgentConstraints(no_destructive=False)
        assert c.is_destructive_blocked() is False

    def test_require_review(self):
        c = AgentConstraints(require_review=True)
        assert c.needs_review() is True


class TestAgentConstraintsSummary:
    """约束摘要显示"""

    def test_full_summary(self):
        c = AgentConstraints(
            file_patterns=["*.py"],
            max_changes=50,
            require_review=True,
            no_destructive=True,
            timeout=300,
            max_tokens=4000,
            allowed_commands=["pytest", "git"],
        )
        s = c.summary()
        assert "文件限制" in s
        assert "最多变更" in s
        assert "必须审查" in s
        assert "禁破坏性操作" in s
        assert "超时" in s
        assert "Token上限" in s
        assert "命令白名单" in s

    def test_partial_summary(self):
        c = AgentConstraints(max_changes=10, timeout=60)
        s = c.summary()
        assert "最多变更" in s
        assert "超时" in s
        assert "文件限制" not in s


# ── ConstraintViolation ──

class TestConstraintViolation:
    """约束违规记录"""

    def test_creation(self):
        v = ConstraintViolation(
            agent_id="test-agent",
            constraint_type=ConstraintType.FILE_PATTERN,
            detail="file not allowed",
            severity=ConstraintSeverity.BLOCKING
        )
        assert v.agent_id == "test-agent"
        assert v.constraint_type == ConstraintType.FILE_PATTERN
        assert v.severity == ConstraintSeverity.BLOCKING
        assert v.timestamp is not None  # 自动填充

    def test_custom_timestamp(self):
        v = ConstraintViolation(
            agent_id="a",
            constraint_type="destructive",
            detail="blocked",
            timestamp="2024-01-01T00:00:00"
        )
        assert v.timestamp == "2024-01-01T00:00:00"


# ── AgentType ──

class TestAgentType:
    """角色分类枚举"""

    def test_all_types(self):
        expected = ["analyst", "planner", "coder", "reviewer", "validator", "committer"]
        values = [t.value for t in AgentType]
        assert values == expected

    def test_definition_with_type(self):
        d = AgentDefinition(
            id="coder-1",
            name="Code Writer",
            capabilities=[AgentCapability.EXECUTE],
            toolsets=["terminal"],
            agent_type=AgentType.CODER,
        )
        assert d.agent_type == AgentType.CODER

    def test_definition_without_type(self):
        d = AgentDefinition(
            id="generic",
            name="Generic Agent",
            capabilities=[AgentCapability.REASON],
            toolsets=["web"],
        )
        assert d.agent_type is None


# ── DecoratedAgent ──

class TestDecoratedAgentExecute:
    """装饰Agent的execute方法"""

    def _make_simple_agent(self):
        """创建一个简单的测试Agent"""
        def simple_fn(task: str, context: dict) -> TaskResult:
            return TaskResult(
                task_id=context.get("task_id", "t-1"),
                agent_id="test-agent",
                status="completed",
                artifacts=[Artifact(type="code", path="main.py", content="print('hello')")],
                duration_ms=100,
                tokens_used=500,
            )

        definition = AgentDefinition(
            id="test-agent",
            name="Test Agent",
            capabilities=[AgentCapability.EXECUTE],
            toolsets=["terminal"],
        )
        constraints = AgentConstraints()
        agent = DecoratedAgent(
            fn=simple_fn,
            definition=definition,
            constraints=constraints,
            gate_mode=GateMode.HYBRID,
        )
        return agent

    def test_basic_execute(self):
        """无约束 → 正常执行"""
        agent = self._make_simple_agent()
        result = agent.execute("write hello world", {"task_id": "t-1"})
        assert result.status == "completed"
        assert result.agent_id == "test-agent"
        assert len(result.artifacts) == 1

    def test_estimate_tokens_default(self):
        """无max_tokens → 启发式估算"""
        agent = self._make_simple_agent()
        tokens = agent.estimate_tokens("short task")
        assert tokens > 0
        # 启发式: len("short task")*4 + 500 = 10*4+500 = 540
        assert tokens == 540

    def test_estimate_tokens_with_limit(self):
        """有max_tokens → 上限估算"""
        constraints = AgentConstraints(max_tokens=200)
        definition = AgentDefinition(
            id="limited-agent", name="Limited",
            capabilities=[AgentCapability.EXECUTE], toolsets=[]
        )
        def fn(task, ctx): return TaskResult(task_id="t", agent_id="a", status="completed", artifacts=[], duration_ms=0)
        agent = DecoratedAgent(fn=fn, definition=definition, constraints=constraints, gate_mode=GateMode.LOOSE)
        tokens = agent.estimate_tokens("a very long task description that would exceed the limit")
        assert tokens <= 200  # 不超过上限


class TestDecoratedAgentConstraintCheck:
    """装饰Agent的约束检查"""

    def test_destructive_task_blocked(self):
        """破坏性任务被约束禁止"""
        def fn(task, ctx): return TaskResult(task_id="t", agent_id="a", status="completed", artifacts=[], duration_ms=0)
        constraints = AgentConstraints(no_destructive=True)
        definition = AgentDefinition(id="safe-agent", name="Safe", capabilities=[AgentCapability.EXECUTE], toolsets=[])
        agent = DecoratedAgent(fn=fn, definition=definition, constraints=constraints, gate_mode=GateMode.STRICT)
        
        result = agent.execute("delete all files in the directory", {"task_id": "t-1"})
        assert result.status == "failed"
        assert "约束违规" in result.error
        assert "破坏性操作" in result.error

    def test_file_pattern_blocked(self):
        """不在白名单的文件被禁止"""
        def fn(task, ctx): return TaskResult(task_id="t", agent_id="a", status="completed", artifacts=[], duration_ms=0)
        constraints = AgentConstraints(file_patterns=["*.py"])
        definition = AgentDefinition(id="py-agent", name="Python Agent", capabilities=[AgentCapability.EXECUTE], toolsets=[])
        agent = DecoratedAgent(fn=fn, definition=definition, constraints=constraints, gate_mode=GateMode.STRICT)
        
        result = agent.execute("modify config", {"task_id": "t-1", "target_files": ["config.yaml"]})
        assert result.status == "failed"
        assert "文件" in result.error

    def test_command_blocked(self):
        """不在白名单的命令被禁止"""
        def fn(task, ctx): return TaskResult(task_id="t", agent_id="a", status="completed", artifacts=[], duration_ms=0)
        constraints = AgentConstraints(allowed_commands=["pytest"])
        definition = AgentDefinition(id="cmd-agent", name="Command Agent", capabilities=[AgentCapability.EXECUTE], toolsets=[])
        agent = DecoratedAgent(fn=fn, definition=definition, constraints=constraints, gate_mode=GateMode.STRICT)
        
        result = agent.execute("run tests", {"task_id": "t-1", "commands": ["npm test"]})
        assert result.status == "failed"
        assert "命令" in result.error

    def test_max_changes_post_check(self):
        """变更文件数超限 → 后置检查标记escalated"""
        def fn(task, ctx):
            return TaskResult(
                task_id="t", agent_id="a", status="completed",
                artifacts=[
                    Artifact(type="code", path="f1.py", content=""),
                    Artifact(type="code", path="f2.py", content=""),
                    Artifact(type="code", path="f3.py", content=""),
                ],
                duration_ms=100
            )
        constraints = AgentConstraints(max_changes=2)
        definition = AgentDefinition(id="limited-changes", name="Limited", capabilities=[AgentCapability.EXECUTE], toolsets=[])
        agent = DecoratedAgent(fn=fn, definition=definition, constraints=constraints, gate_mode=GateMode.HYBRID)
        
        result = agent.execute("change 3 files", {"task_id": "t"})
        assert result.status == "escalated"
        assert "constraint_violations" in result.metadata


# ── @harness_agent 装饰器 ──

class TestHarnessAgentDecorator:
    """装饰器完整流程"""

    def setup_method(self):
        """每个测试前重置registry和bus"""
        get_registry()._agents.clear()
        bus = get_bus()
        bus._handlers.clear()
        bus._history.clear()

    def test_basic_decorator(self):
        """基本装饰 → 自动注册+可调用"""
        @harness_agent(
            name="test-reviewer",
            capabilities=[AgentCapability.PERCEIVE, AgentCapability.REASON],
            toolsets=["terminal", "file"],
        )
        def review(task: str, context: dict) -> TaskResult:
            return TaskResult(
                task_id=context.get("task_id", "t-1"),
                agent_id="test-reviewer",
                status="completed",
                artifacts=[],
                duration_ms=50,
            )
        
        # 检查是DecoratedAgent
        assert isinstance(review, DecoratedAgent)
        # 检查自动注册
        registry = get_registry()
        assert registry.get(review.definition.id) is not None
        # 直接调用
        result = review("review code", {"task_id": "t-1"})
        assert result.status == "completed"

    def test_decorator_with_constraints(self):
        """装饰器带约束"""
        @harness_agent(
            name="safe-agent",
            capabilities=[AgentCapability.EXECUTE],
            constraints=AgentConstraints(
                file_patterns=["*.py"],
                max_changes=10,
                no_destructive=True,
                timeout=60,
            ),
            gate_mode=GateMode.STRICT,
        )
        def safe_execute(task: str, context: dict) -> TaskResult:
            return TaskResult(
                task_id=context.get("task_id", "t"),
                agent_id="safe-agent",
                status="completed",
                artifacts=[],
                duration_ms=10,
            )
        
        assert isinstance(safe_execute, DecoratedAgent)
        assert safe_execute.constraints.file_patterns == ["*.py"]
        assert safe_execute.constraints.max_changes == 10
        assert safe_execute.gate_mode == GateMode.STRICT

    def test_decorator_with_priority(self):
        """装饰器带优先级"""
        @harness_agent(
            name="high-priority",
            capabilities=[AgentCapability.EXECUTE],
            priority=AgentPriority.HIGH,
        )
        def important(task: str, context: dict) -> TaskResult:
            return TaskResult(task_id="t", agent_id="a", status="completed", artifacts=[], duration_ms=0)
        
        assert isinstance(important, DecoratedAgent)
        assert important.constraints.priority == AgentPriority.HIGH

    def test_decorator_publishes_event(self):
        """装饰器注册时发布BusEvent"""
        bus = get_bus()
        # 清空历史
        bus._history.clear()

        @harness_agent(
            name="event-test",
            capabilities=[AgentCapability.REASON],
            toolsets=["web"],
        )
        def agent_fn(task, ctx):
            return TaskResult(task_id="t", agent_id="a", status="completed", artifacts=[], duration_ms=0)
        
        # 检查事件历史
        registered_events = [e for e in bus._history if e.type == BusEventType.AGENT_REGISTERED]
        assert len(registered_events) >= 1
        event = registered_events[-1]
        assert event.data["name"] == "event-test"
        assert "capabilities" in event.data

    def test_decorator_no_auto_register(self):
        """auto_register=False → 不注册"""
        @harness_agent(
            name="manual-agent",
            capabilities=[AgentCapability.EXECUTE],
            auto_register=False,
        )
        def manual(task, ctx):
            return TaskResult(task_id="t", agent_id="a", status="completed", artifacts=[], duration_ms=0)
        
        registry = get_registry()
        assert registry.get(manual.definition.id) is None

    def test_decorator_with_agent_type(self):
        """装饰器+AgentType角色"""
        @harness_agent(
            name="the-coder",
            capabilities=[AgentCapability.EXECUTE],
        )
        def code_fn(task, ctx):
            return TaskResult(task_id="t", agent_id="a", status="completed", artifacts=[], duration_ms=0)
        
        # AgentType是定义在AgentDefinition上的，装饰器也可以手动设置
        # 这里验证definition可以携带agent_type
        assert isinstance(code_fn, DecoratedAgent)

    def test_decorator_preserves_fn_attrs(self):
        """装饰器保留原函数属性"""
        def my_fn(task, ctx):
            """My function docstring"""
            return TaskResult(task_id="t", agent_id="a", status="completed", artifacts=[], duration_ms=0)
        
        agent = harness_agent(
            name="attr-test",
            capabilities=[AgentCapability.EXECUTE],
        )(my_fn)
        
        assert agent.__name__ == "my_fn"
        assert agent.__doc__ == "My function docstring"


# ── AgentPriority ──

class TestAgentPriority:
    def test_all_levels(self):
        expected = ["low", "normal", "high", "critical"]
        values = [p.value for p in AgentPriority]
        assert values == expected
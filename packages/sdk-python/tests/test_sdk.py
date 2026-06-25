"""
harness-sdk Python SDK 测试

覆盖:
  - @harness_agent / @simple_agent 装饰器
  - Hook 生命周期钩子
  - Agent 接入接口 (create/register/get/list)
  - HarnessClient (编排/合规/审计/知识)
  - FunctionWrapper (普通函数→IExecutableAgent)
"""

import pytest


# ─── 装饰器测试 ────────────────────────────────────────

class TestDecorators:
    """@harness_agent 和 @simple_agent 装饰器测试"""

    def test_harness_agent_basic(self):
        """@harness_agent 基本用法——装饰函数并调用"""
        from harness_sdk.decorators import harness_agent
        from harness.types import AgentCapability, TaskResult

        @harness_agent(
            name="test-reviewer",
            capabilities=[AgentCapability.PERCEIVE, AgentCapability.REASON],
            auto_register=False,  # 测试不污染全局Registry
        )
        def review(task: str, context: dict) -> TaskResult:
            return TaskResult(
                task_id=context.get("task_id", "t-1"),
                agent_id="test-reviewer",
                status="completed",
                artifacts=[],
                duration_ms=100,
            )

        # 验证返回 DecoratedAgent
        assert hasattr(review, "execute")
        assert hasattr(review, "definition")
        assert review.definition.name == "test-reviewer"

        # 调用
        result = review("review code", {"task_id": "t-1"})
        assert result.status == "completed"
        assert result.task_id == "t-1"

    def test_simple_agent_minimal(self):
        """@simple_agent 极简版——只需name"""
        from harness_sdk.decorators import simple_agent
        from harness.types import TaskResult

        @simple_agent(name="simple-worker", auto_register=False)
        def work(task: str, context: dict) -> TaskResult:
            return TaskResult(
                task_id=context.get("task_id", "t-1"),
                agent_id="simple-worker",
                status="completed",
                artifacts=[],
                duration_ms=50,
            )

        assert hasattr(work, "execute")
        assert work.definition.name == "simple-worker"
        # 默认 capabilities
        assert len(work.definition.capabilities) >= 2

    def test_simple_agent_with_constraints(self):
        """@simple_agent 自定义约束参数"""
        from harness_sdk.decorators import simple_agent
        from harness.types import TaskResult

        @simple_agent(
            name="constrained-worker",
            max_changes=10,
            no_destructive=True,
            timeout=60,
            auto_register=False,
        )
        def safe_work(task: str, context: dict) -> TaskResult:
            return TaskResult(
                task_id="t-1",
                agent_id="constrained-worker",
                status="completed",
                artifacts=[],
                duration_ms=30,
            )

        # 约束属性
        assert safe_work.constraints.max_changes == 10
        assert safe_work.constraints.is_destructive_blocked()

    def test_harness_agent_with_string_capabilities(self):
        """@simple_agent 用 str 传 capabilities"""
        from harness_sdk.decorators import simple_agent
        from harness.types import TaskResult, AgentCapability

        @simple_agent(
            name="flex-worker",
            capabilities=["perceive", "execute"],
            auto_register=False,
        )
        def flex(task: str, context: dict) -> TaskResult:
            return TaskResult(
                task_id="t-1",
                agent_id="flex-worker",
                status="completed",
                artifacts=[],
                duration_ms=10,
            )

        assert AgentCapability.PERCEIVE in flex.definition.capabilities
        assert AgentCapability.EXECUTE in flex.definition.capabilities


# ─── Hook 测试 ────────────────────────────────────────

class TestHooks:
    """生命周期钩子测试"""

    def test_before_hook_basic(self):
        """@before_hook 注册和执行"""
        from harness_sdk.hooks import before_hook, HookResult, HookContext, HookChain

        call_count = 0

        @before_hook
        def log_input(ctx: HookContext) -> HookResult:
            nonlocal call_count
            call_count += 1
            assert ctx.task == "test task"
            return HookResult.CONTINUE

        # 创建 HookChain 并添加
        chain = HookChain()
        chain.add(log_input)

        # 运行
        abort_reason = chain.run_before("test task", "test-agent", "a-1", {})
        assert abort_reason is None  # 没有ABORT
        assert call_count == 1

    def test_after_hook_basic(self):
        """@after_hook 注册和执行"""
        from harness_sdk.hooks import after_hook, HookResult, HookContext, HookChain
        from harness.types import TaskResult

        results_seen = []

        @after_hook
        def capture_result(ctx: HookContext) -> HookResult:
            results_seen.append(ctx.result.status)
            return HookResult.CONTINUE

        chain = HookChain()
        chain.add(capture_result)

        result = TaskResult(
            task_id="t-1", agent_id="a-1", status="completed",
            artifacts=[], duration_ms=100,
        )
        chain.run_after(result, "task", "agent", "a-1", {})
        assert "completed" in results_seen

    def test_error_hook_basic(self):
        """@error_hook 注册和执行"""
        from harness_sdk.hooks import error_hook, HookResult, HookContext, HookChain

        errors_seen = []

        @error_hook
        def report_error(ctx: HookContext) -> HookResult:
            errors_seen.append(ctx.error)
            return HookResult.CONTINUE

        chain = HookChain()
        chain.add(report_error)

        chain.run_on_error("something broke", "task", "agent", "a-1", {})
        assert "something broke" in errors_seen

    def test_hook_chain_abort(self):
        """HookChain ABORT 流控"""
        from harness_sdk.hooks import before_hook, HookResult, HookContext, HookChain

        @before_hook
        def abort_hook(ctx: HookContext) -> HookResult:
            return HookResult.ABORT

        chain = HookChain()
        chain.add(abort_hook)

        abort_reason = chain.run_before("task", "agent", "a-1", {})
        assert abort_reason is not None
        assert "abort" in abort_reason.lower() or "Aborted" in abort_reason

    def test_hook_chain_stats(self):
        """HookChain 统计"""
        from harness_sdk.hooks import before_hook, after_hook, HookResult, HookContext, HookChain

        @before_hook
        def hook1(ctx): return HookResult.CONTINUE

        @after_hook
        def hook2(ctx): return HookResult.CONTINUE

        chain = HookChain()
        chain.add(hook1)
        chain.add(hook2)

        stats = chain.stats()
        assert stats["before_hooks"] == 1
        assert stats["after_hooks"] == 1
        assert stats["total_hooks"] == 2


# ─── Agent 接入测试 ────────────────────────────────────────

class TestAgentAPI:
    """create_agent / register_agent / get_agent / list_agents 测试"""

    def test_create_agent(self):
        """create_agent 快速创建 AgentDefinition"""
        from harness_sdk.agent import create_agent
        from harness.types import AgentCapability

        defn = create_agent(
            name="my-worker",
            capabilities=["perceive", "execute"],
            toolsets=["terminal"],
        )
        assert defn.name == "my-worker"
        assert AgentCapability.PERCEIVE in defn.capabilities
        assert AgentCapability.EXECUTE in defn.capabilities
        assert defn.id == "my-worker"

    def test_register_and_get_agent(self):
        """register_agent → get_agent 流程"""
        from harness_sdk.agent import register_agent, get_agent, create_agent
        from harness.types import TaskResult

        def my_handler(task: str, context: dict) -> TaskResult:
            return TaskResult(
                task_id=context.get("task_id", "t-1"),
                agent_id="sdk-test-agent",
                status="completed",
                artifacts=[],
                duration_ms=50,
            )

        defn = create_agent("sdk-test-agent", capabilities=["perceive"])
        client = register_agent(defn, my_handler)

        # 通过 client 直接运行
        result = client.run("test task", {"task_id": "t-1"})
        assert result.status == "completed"

        # 通过 get_agent 获取
        retrieved = get_agent("sdk-test-agent")
        assert retrieved is not None
        assert retrieved.info().name == "sdk-test-agent"

    def test_function_wrapper(self):
        """普通函数包装为 IExecutableAgent"""
        from harness_sdk._wrapper import FunctionWrapper
        from harness_sdk.agent import create_agent
        from harness.types import TaskResult

        def handler(task: str, context: dict) -> TaskResult:
            return TaskResult(
                task_id=context.get("task_id", "t-1"),
                agent_id="wrap-test",
                status="completed",
                artifacts=[],
                duration_ms=10,
            )

        defn = create_agent("wrap-test", ["perceive"])
        wrapper = FunctionWrapper(handler, defn)

        result = wrapper.execute("test", {"task_id": "t-1"})
        assert result.status == "completed"

    def test_function_wrapper_error_handling(self):
        """FunctionWrapper 异常处理"""
        from harness_sdk._wrapper import FunctionWrapper
        from harness_sdk.agent import create_agent

        def bad_handler(task: str, context: dict):
            raise ValueError("boom")

        defn = create_agent("error-test", ["perceive"])
        wrapper = FunctionWrapper(bad_handler, defn)

        result = wrapper.execute("test", {"task_id": "t-1"})
        assert result.status == "failed"
        assert "boom" in result.error


# ─── Client 测试 ────────────────────────────────────────

class TestHarnessClient:
    """HarnessClient 接口测试"""

    def test_create_client(self):
        """create_client 创建客户端"""
        from harness_sdk.client import create_client

        client = create_client("test-project")
        assert client is not None

    def test_client_stats(self):
        """client.stats() 返回统计"""
        from harness_sdk.client import create_client

        client = create_client("stats-test")
        stats = client.stats()
        assert "audit" in stats
        assert "knowledge" in stats

    def test_client_compliance_scan(self):
        """client.compliance_scan() 合规扫描"""
        from harness_sdk.client import create_client
        from harness.types import Artifact

        client = create_client("scan-test")

        artifacts = [
            Artifact(type="code", path="test.py", content="password = '123'", metadata={}),
        ]

        results = client.compliance_scan(artifacts, packs=["security"])
        assert isinstance(results, list)

    def test_client_single_task(self):
        """client.run_single_task() 单任务执行"""
        from harness_sdk.client import create_client
        from harness_sdk.agent import create_agent, register_agent
        from harness.types import TaskResult

        def handler(task, ctx):
            return TaskResult(
                task_id=ctx.get("task_id", "t-1"),
                agent_id="single-task-agent",
                status="completed",
                artifacts=[], duration_ms=50,
            )

        client = create_client("single-test")

        defn = create_agent("single-task-agent", ["perceive"])
        register_agent(defn, handler)

        result = client.run_single_task("single-task-agent", "do work", {"task_id": "t-1"})
        assert result.status == "completed"

    def test_client_knowledge(self):
        """client 知识注入"""
        from harness_sdk.client import create_client

        client = create_client("knowledge-test")

        # 添加知识
        entry_id = client.add_knowledge(
            title="Project uses React",
            content="This project uses React + TypeScript for frontend.",
            type="architecture",
            scope="project",
            tags=["react", "frontend"],
            source="human",
        )
        assert entry_id is not None

        # 查询知识
        context = client.inject_knowledge("React", type_filter="architecture")
        assert len(context.relevant_entries) > 0
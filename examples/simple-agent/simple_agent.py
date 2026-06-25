"""
simple-agent 示例——最简 harness-cook 使用

演示:
  1. @simple_agent 极简装饰器
  2. 约束自动生效（no_destructive 会阻止破坏性操作）
  3. TaskResult 返回格式
  4. AgentClient 查询 Agent 信息
"""

from harness_sdk import simple_agent, TaskResult, Artifact, get_agent


# ─── 1. 定义 Agent ──────────────────────────────────

@simple_agent(
    name="hello-worker",
    # 只需 name，其余自动生成默认:
    # capabilities = [PERCEIVE, REASON]
    # constraints = { max_changes=20, no_destructive=True, timeout=300 }
)
def hello(task: str, context: dict) -> TaskResult:
    """Hello Worker——最简单的 Agent"""
    print(f"  [hello-worker] 收到任务: {task}")

    # 业务逻辑: 生成一个"hello"产出物
    greeting = f"Hello from harness-cook! Task: {task}"

    return TaskResult(
        task_id=context.get("task_id", "t-001"),
        agent_id="hello-worker",
        status="completed",
        artifacts=[
            Artifact(type="doc", path="hello.txt", content=greeting, metadata={}),
        ],
        duration_ms=50,
        tokens_used=100,
        metadata={"greeting": greeting},
    )


# ─── 2. 执行正常任务 ────────────────────────────────

print("=== simple-agent 示例 ===")
print()

# 正常任务 → 成功
print("1. 正常任务:")
result = hello("review the README file", {"task_id": "t-001"})
print(f"  状态: {result.status}")
print(f"  产出物: {len(result.artifacts)} 件")
print()

# ─── 3. 约束生效——破坏性操作被阻止 ────────────────

print("2. 破坏性操作（约束阻止）:")
result2 = hello("delete all files and rm -rf /", {"task_id": "t-002"})
print(f"  状态: {result2.status}")
print(f"  错误: {result2.error}")
print()

# ─── 4. 查询 Agent 信息 ────────────────────────────

print("3. Agent 信息:")
agent = get_agent("hello-worker")
if agent:
    info = agent.info()
    print(f"  ID: {info.id}")
    print(f"  名称: {info.name}")
    print(f"  能力: {info.capabilities}")
    print(f"  门禁: {info.gate_mode}")
else:
    print("  Agent 未注册（auto_register=True 时自动注册）")

print()
print("=== 示例完成 ===")
"""
multi-agent 示例——多 Agent DAG 编排协作

场景: Coder 写代码 → Reviewer 检查 → Tester 测试

演示:
  1. 多个 @harness_agent 定义不同角色（不同约束和能力）
  2. DAGWorkflow 编排 Agent 之间的依赖和执行顺序
  3. HarnessClient 一站式接口（编排+合规+审计）
  4. 合规扫描——自动检查产出物
"""

from harness_sdk import (
    harness_agent, TaskResult, Artifact,
    AgentConstraints, Priority,
    Capability, GateMode,
    DAGNode, DAGEdge, DAGWorkflow,
    create_client, create_agent, register_agent,
)


# ─── 1. 定义三个 Agent ──────────────────────────────

@harness_agent(
    name="coder",
    capabilities=[Capability.PERCEIVE, Capability.EXECUTE],
    constraints=AgentConstraints(
        file_patterns=["*.py", "*.ts"],
        max_changes=10,          # Coder 最多改10个文件
        no_destructive=True,
        timeout=300,
        priority=Priority.NORMAL,
        allowed_commands=["pytest", "git", "python"],
        max_tokens=8000,
    ),
    gate_mode=GateMode.HYBRID,
    toolsets=["terminal", "file"],
)
def coder_fn(task: str, context: dict) -> TaskResult:
    """Coder——写代码"""
    print(f"  [Coder] 写代码: {task}")

    # 模拟产出: 一个 Python 文件
    code_content = "def hello():\n    return 'Hello from harness-cook!'"

    return TaskResult(
        task_id=context.get("task_id", "t-001"),
        agent_id="coder",
        status="completed",
        artifacts=[
            Artifact(type="code", path="hello.py", content=code_content, metadata={"role": "coder"}),
        ],
        duration_ms=500,
        tokens_used=2000,
    )


@harness_agent(
    name="reviewer",
    capabilities=[Capability.PERCEIVE, Capability.REASON],
    constraints=AgentConstraints(
        file_patterns=["*.py"],
        max_changes=0,           # Reviewer 不改文件，只检查
        no_destructive=True,
        require_review=True,     # Reviewer 需要人工确认
        timeout=120,
        priority=Priority.HIGH,  # Reviewer 优先级高
        max_tokens=4000,
    ),
    gate_mode=GateMode.STRICT,  # Reviewer 用严格门禁
    toolsets=["terminal", "file"],
)
def reviewer_fn(task: str, context: dict) -> TaskResult:
    """Reviewer——检查代码质量"""
    print(f"  [Reviewer] 检查: {task}")

    # 模拟产出: 一个检查报告
    review_content = "Code quality: PASS. No security issues found."

    return TaskResult(
        task_id=context.get("task_id", "t-002"),
        agent_id="reviewer",
        status="completed",
        artifacts=[
            Artifact(type="doc", path="review.md", content=review_content, metadata={"role": "reviewer"}),
        ],
        duration_ms=300,
        tokens_used=1000,
    )


@harness_agent(
    name="tester",
    capabilities=[Capability.EXECUTE],
    constraints=AgentConstraints(
        file_patterns=["*.py", "test_*.py"],
        max_changes=5,           # Tester 可以写测试文件
        no_destructive=True,
        timeout=180,
        priority=Priority.NORMAL,
        allowed_commands=["pytest"],
        max_tokens=2000,
    ),
    gate_mode=GateMode.LOOSE,   # Tester 用宽松门禁
    toolsets=["terminal"],
)
def tester_fn(task: str, context: dict) -> TaskResult:
    """Tester——运行测试"""
    print(f"  [Tester] 测试: {task}")

    # 模拟产出: 一个测试文件 + 测试结果
    test_content = "def test_hello():\n    assert hello() == 'Hello from harness-cook!'"

    return TaskResult(
        task_id=context.get("task_id", "t-003"),
        agent_id="tester",
        status="completed",
        artifacts=[
            Artifact(type="test", path="test_hello.py", content=test_content, metadata={"role": "tester"}),
            Artifact(type="log", path="pytest.log", content="1 passed in 0.01s", metadata={"role": "tester"}),
        ],
        duration_ms=200,
        tokens_used=500,
    )


# ─── 2. 定义 DAG Workflow ────────────────────────────

print("=== multi-agent 示例 ===")
print()

print("1. 定义 DAG Workflow (Coder → Reviewer → Tester):")

workflow = DAGWorkflow(
    id="code-pipeline",
    name="code-pipeline",
    nodes=[
        DAGNode(id="coder-node", agent_type="coder", task="实现 hello() 函数", inputs=[], outputs=["reviewer-node"]),
        DAGNode(id="reviewer-node", agent_type="reviewer", task="代码质量检查", inputs=["coder-node"], outputs=["tester-node"]),
        DAGNode(id="tester-node", agent_type="tester", task="运行单元测试", inputs=["reviewer-node"], outputs=[]),
    ],
    edges=[
        DAGEdge(from_node="coder-node", to_node="reviewer-node"),
        DAGEdge(from_node="reviewer-node", to_node="tester-node"),
    ],
    entry_node="coder-node",
)
print(f"  Workflow ID: {workflow.id}")
print(f"  节点: {len(workflow.nodes)} 个")
print(f"  边: {len(workflow.edges)} 条")
print()

# ─── 3. 直接执行各 Agent（简化版，不走 DAG）─────────

print("2. 直接执行各 Agent:")
coder_result = coder_fn("实现 hello() 函数", {"task_id": "t-001"})
print(f"  Coder → 状态: {coder_result.status}, 产出物: {len(coder_result.artifacts)}")

reviewer_result = reviewer_fn("代码质量检查", {"task_id": "t-002"})
print(f"  Reviewer → 状态: {reviewer_result.status}, 产出物: {len(reviewer_result.artifacts)}")

tester_result = tester_fn("运行单元测试", {"task_id": "t-003"})
print(f"  Tester → 状态: {tester_result.status}, 产出物: {len(tester_result.artifacts)}")
print()

# ─── 4. HarnessClient 合规扫描 ────────────────────

print("3. HarnessClient 合规扫描:")
client = create_client("multi-agent-demo")

all_artifacts = (
    coder_result.artifacts +
    reviewer_result.artifacts +
    tester_result.artifacts
)

scan_results = client.compliance_scan(all_artifacts, packs=["security", "privacy"])
print(f"  扫描了 {len(all_artifacts)} 个产出物")
for r in scan_results:
    print(f"  规则 {r.rule_id}: {'PASS' if r.passed else 'FAIL'} (severity={r.severity})")
print()

# ─── 5. 审计统计 ────────────────────────────────────

print("4. Harness 审计统计:")
stats = client.audit_stats()
print(f"  总任务: {stats.total_tasks}")
print(f"  交付: {stats.delivered}")
print()

# ─── 6. 约束阻止破坏性操作 ──────────────────────────

print("5. 约束阻止破坏性操作:")
bad_result = coder_fn("delete all test files and remove directory", {"task_id": "t-bad"})
print(f"  Coder 收到破坏性任务 → 状态: {bad_result.status}")
print(f"  错误: {bad_result.error}")
print()

print("=== 示例完成 ===")
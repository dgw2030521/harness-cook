"""
hermes-bridge 示例——Hermes Agent + harness-cook 集成

场景: Hermes 的 delegate_task 子 Agent 通过 MCP Server 接入 Harness 管控

演示:
  1. Hermes → Harness 桥接流程
  2. MCP Server 远程调用
  3. HarnessClient 知识注入
  4. 审计溯源
"""

from harness_sdk import (
    harness_agent, TaskResult, Artifact,
    AgentConstraints, Priority,
    Capability, GateMode,
    create_client, list_agents,
)


# ─── 1. 定义 Hermes 桥接 Agent ──────────────────────

@harness_agent(
    name="hermes-coder",
    capabilities=[Capability.PERCEIVE, Capability.EXECUTE, Capability.COLLABORATE],
    constraints=AgentConstraints(
        file_patterns=["*.py", "*.ts", "*.js"],
        max_changes=30,
        no_destructive=True,
        require_review=False,    # Hermes 子 Agent 不需要人工审查（Hermes 自己管）
        timeout=600,            # Hermes 子 Agent 超时较长
        priority=Priority.HIGH,
        allowed_commands=["pytest", "git", "python", "npm", "pnpm"],
        max_tokens=12000,
    ),
    gate_mode=GateMode.HYBRID,
    toolsets=["terminal", "file", "web"],
)
def hermes_coder(task: str, context: dict) -> TaskResult:
    """Hermes Coder——Hermes delegate_task 的子 Agent 桥接

    在真实场景中，Hermes 通过 delegate_task 派出子 Agent，
    子 Agent 的行为通过 harness_agent 装饰器接入 Harness 管控。
    """
    print(f"  [hermes-coder] Hermes 子 Agent 收到任务: {task}")

    # 模拟产出（实际场景中，子 Agent 会用 terminal/file 工具真正执行）
    code = (
        "def process_data(data):\n"
        "    if not data:\n"
        "        return None\n"
        "    return {'processed': True, 'count': len(data)}\n"
    )

    return TaskResult(
        task_id=context.get("task_id", "h-001"),
        agent_id="hermes-coder",
        status="completed",
        artifacts=[
            Artifact(type="code", path="process.py", content=code, metadata={"bridge": "hermes"}),
        ],
        duration_ms=1200,
        tokens_used=3000,
        metadata={"source": "hermes-delegate"},
    )


@harness_agent(
    name="hermes-reviewer",
    capabilities=[Capability.PERCEIVE, Capability.REASON],
    constraints=AgentConstraints(
        file_patterns=["*.py", "*.ts"],
        max_changes=5,           # Reviewer 只做少量修改建议
        no_destructive=True,
        require_review=True,
        timeout=300,
        priority=Priority.CRITICAL,
        max_tokens=6000,
    ),
    gate_mode=GateMode.STRICT,
    toolsets=["terminal", "file"],
)
def hermes_reviewer(task: str, context: dict) -> TaskResult:
    """Hermes Reviewer——审查子 Agent 的产出"""
    print(f"  [hermes-reviewer] 审查 Hermes 子 Agent 产出: {task}")

    return TaskResult(
        task_id=context.get("task_id", "h-002"),
        agent_id="hermes-reviewer",
        status="completed",
        artifacts=[
            Artifact(type="doc", path="review.md", content="PASS: 代码质量良好", metadata={"bridge": "hermes"}),
        ],
        duration_ms=800,
        tokens_used=1500,
    )


# ─── 2. 桥接流程演示 ────────────────────────────────

print("=== hermes-bridge 示例 ===")
print()

print("1. Hermes → Harness 桥接流程:")
print("   Hermes delegate_task → 子 Agent → harness_agent 装饰器 → Harness 约束+门禁")
print()

# 执行 Hermes Coder
print("2. Hermes 子 Agent (Coder) 执行任务:")
coder_result = hermes_coder("实现数据处理函数", {"task_id": "h-001", "source": "hermes"})
print(f"  状态: {coder_result.status}")
print(f"  产出物: {len(coder_result.artifacts)} 件")
print(f"  元数据: source={coder_result.metadata.get('source', 'N/A')}")
print()

# 执行 Hermes Reviewer 审查 Coder 产出
print("3. Hermes 子 Agent (Reviewer) 审查产出:")
review_result = hermes_reviewer("审查 process.py 代码质量", {"task_id": "h-002", "source": "hermes"})
print(f"  状态: {review_result.status}")
print(f"  产出物: {len(review_result.artifacts)} 件")
print()

# ─── 3. HarnessClient 合规+知识 ────────────────────

print("4. Harness Client 合规扫描:")
client = create_client("hermes-bridge-demo")

all_artifacts = coder_result.artifacts + review_result.artifacts
scan_results = client.compliance_scan(all_artifacts, packs=["security"])
for r in scan_results:
    print(f"  规则 {r.rule_id}: {'PASS' if r.passed else 'FAIL'}")
print()

# 知识注入
print("5. 知识注入（为 Hermes 子 Agent 提供项目知识）:")
# 先添加一条知识
client.add_knowledge(
    title="项目编码规范",
    content="本项目使用 Python 3.9+，遵循 PEP 8，使用 pytest 测试。",
    type="convention",
    scope="project",
    tags=["python", "coding-style"],
    source="human",
)

# 查询知识并注入到 Agent context
knowledge_ctx = client.inject_knowledge("编码规范", type_filter="convention")
print(f"  查到 {len(knowledge_ctx.relevant_entries)} 条相关知识")
for entry in knowledge_ctx.relevant_entries:
    print(f"  [{entry.type.value}/{entry.scope.value}] {entry.title}")
print()

# ─── 4. 审计溯源 ────────────────────────────────────

print("6. 审计溯源:")
stats = client.audit_stats()
print(f"  总任务: {stats.total_tasks}")
print(f"  已交付: {stats.delivered}")
print(f"  升级: {stats.escalated}")
print()

# ─── 5. 约束阻止 ────────────────────────────────────

print("7. 约束阻止破坏性操作:")
bad_result = hermes_coder("truncate table and drop database", {"task_id": "h-bad"})
print(f"  状态: {bad_result.status}")
print(f"  错误: {bad_result.error}")
print()

# ─── 6. 已注册 Agent ────────────────────────────────

print("8. 已注册 Agent 列表:")
agents = list_agents()
for a in agents:
    print(f"  {a.id}: {a.name} (能力: {a.capabilities})")
print()

print("=== 示例完成 ===")
print()
print("桥接总结:")
print("  Hermes 的 delegate_task 子 Agent 通过 @harness_agent 接入 Harness，")
print("  获得约束管控 + 质量门禁 + 合规扫描 + 审计溯源 + 知识注入。")
print("  MCP Server 则提供远程调用接口，让 Hermes 不导入 Python 包也能使用 Harness。")
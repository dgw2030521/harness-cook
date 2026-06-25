---
name: auto-review
description: "Multi-agent cross-review — coder agent produces, reviewer agent verifies. Automatic quality gate without human intervention."
version: 1.0.0
trigger: When a task involves producing code/config changes that should be reviewed before committing. Source lives in ~/ProjectsOnGitlab/harness-cook/skills/auto-review/SKILL.md
---

# Auto-Review Skill

Two-agent review pattern: one agent produces work, another independently reviews it. Only approved work gets committed.

## The Pattern

```
Task arrives
  → Agent A (coder) executes task, produces changes
  → Auto-verify runs on Agent A's output
  → If verify PASS:
    → Agent B (reviewer) reviews Agent A's changes independently
    → Reviewer checks: correctness, security, style, edge cases
    → If reviewer APPROVES → commit + deliver
    → If reviewer REJECTS → feedback loop back to Agent A with specific issues
  → If verify FAIL:
    → Auto-fix loop (up to 3 cycles)
    → If still FAIL → escalate to human
```

## How to Execute with Hermes

### Using delegate_task (in-process, fast)

```python
# Step 1: Coder agent completes the task (main agent does this)
# Step 2: Kick off reviewer sub-agent

from hermes_tools import delegate_task, read_file, terminal

# Get the diff of what was changed
diff = terminal("git diff")

# Send to reviewer
review_result = delegate_task(
    goal="Review the following code changes for correctness, security issues, and edge cases. Approve or reject with specific feedback.",
    context=f"""You are a code reviewer. Review these changes independently.

Changed files diff:
{diff}

Review criteria:
1. Correctness: Does the code do what it claims to do?
2. Security: Are there any injection, auth, or data exposure risks?
3. Edge cases: Are error cases handled? What about empty/null inputs?
4. Style: Does it follow project conventions?
5. Testing: Are there sufficient tests for the changes?

Output format:
APPROVE or REJECT
If REJECT, list each issue with file, line, and suggested fix.""",
    toolsets=["file", "terminal"],
)
```

### Using Kanban (cross-profile, durable)

For larger tasks that need durable review:

```bash
# Create review task on the board
hermes kanban create --title "Review: auth token refresh fix" \
  --description "Review changes in src/auth/refresh.ts for correctness and security" \
  --assignee reviewer-profile
```

## Reviewer Checklist (auto-generated per file type)

### Code review checklist

```
1. [ ] Logic correctness — does it solve the stated problem?
2. [ ] No hardcoded secrets/credentials
3. [ ] Error handling for all edge cases (null, empty, timeout, concurrent)
4. [ ] No unnecessary dependencies added
5. [ ] Follows project naming/style conventions
6. [ ] Has appropriate test coverage
7. [ ] No breaking changes to existing APIs
8. [ ] Performance considerations (N+1 queries, unnecessary loops)
9. [ ] Type safety (no implicit any, proper generics)
10. [ ] Documentation for non-obvious logic
```

### Config review checklist

```
1. [ ] Valid syntax (YAML/JSON/TOML parses correctly)
2. [ ] No sensitive values exposed
3. [ ] Backward compatible (existing configs still work)
4. [ ] No unnecessary feature flags toggled
```

## Feedback Loop

When reviewer REJECTS:

```yaml
review_feedback:
  status: REJECT
  issues:
    - file: "src/auth/refresh.ts"
      line: 45
      issue: "Mutex timeout of 30s is too long for auth refresh — should be 10s max"
      suggestion: "Change timeout from 30000 to 10000"
    
    - file: "tests/auth/refresh.test.ts"
      line: 12
      issue: "Test doesn't cover concurrent refresh timeout scenario"
      suggestion: "Add test case: two concurrent refresh requests, first one exceeds timeout"
```

The coder agent receives this feedback and makes targeted fixes. Then re-submit for review. Max 2 review cycles before escalation.

## Escalation Rules

| Condition | Action |
|-----------|--------|
| 2 review rejections in a row | Escalate to human — something is fundamentally wrong |
| Reviewer and coder disagree on approach | Escalate to human — architectural decision needed |
| Security concern flagged by reviewer | ALWAYS escalate to human — never auto-approve security fixes |
| All checks pass | Auto-commit — no human needed |

## Executable Script

本 Skill 提供可执行脚本，可直接运行或通过 MCP 工具调用：

```bash
# 直接运行 — 门禁审查（默认 hybrid 模式）
python3 skills/auto-review/review_gate.py --path . --mode hybrid --output table

# 严格模式
python3 skills/auto-review/review_gate.py --path . --mode strict --output table

# JSON 输出（机器可读）
python3 skills/auto-review/review_gate.py --path . --mode hybrid --output json

# 通过 MCP 工具调用
mcp__harness-cook__harness_gate_create gate_type="hybrid" checks=[...]
mcp__harness-cook__harness_check path="." pack_names=["coding", "security"]
```

脚本功能：
1. 获取 git diff 变更文件列表
2. 构建 `Artifact` 列表（按文件类型分类）
3. 调用 harness `GateEngine.check(default_coding_gate)` 执行门禁检查
4. 输出门禁结果：通过/不通过 + 详细违规 + 升级信息 + 自动修复统计

退出码：0 = 门禁通过，1 = 门禁不通过

### 与 The Pattern 的关系

脚本实现了 "The Pattern" 中 Agent B（reviewer）的**自动化审查部分**：
- 替代了需要 `hermes_tools.delegate_task` 的手动审查流程
- `GateEngine` 提供了可编程的门禁规则（比手动 checklist 更系统化）
- 三个模式对应不同严格度：strict（零容忍）、hybrid（允许低级别违规）、loose（仅拦截 critical）
- 升级机制自动触发：critical 级别违规 → 升级人工

**注意**：脚本处理的是**自动化门禁检查**部分。对于需要人类判断的审查（架构决策、安全审查），仍应遵循 "The Pattern" 中的 Agent B 审查流程和升级规则。

## Pitfalls

1. Don't make the reviewer and coder the same model context — that defeats the purpose of independent review. Use delegate_task with a fresh context.
2. Don't let the review loop run forever — max 2 review cycles, then escalate.
3. Don't auto-approve changes that touch auth/security/crypto — these ALWAYS need human review regardless of automated check results.
4. Don't skip review for trivial changes (docs, comments, formatting) — only review substantive logic changes.
5. Don't make the reviewer re-implement the code — review is about checking, not rewriting.
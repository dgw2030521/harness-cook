---
name: auto-audit
description: "Automatic audit trail — Agent records decisions, actions, and outcomes without human command. Audit happens by default, not on request."
version: 1.0.0
trigger: After any task that changes files, makes decisions, or executes significant operations. Source lives in ~/ProjectsOnGitlab/harness-cook/skills/auto-audit/SKILL.md
---

# Auto-Audit Skill

Audit is not something you command. It happens automatically. Every significant action gets recorded.

## Audit Log Format

Each audit entry is a structured record written to the project's `.harness/audit/` directory:

```yaml
# .harness/audit/YYYY-MM-DD-HHMMSS-task-summary.yaml
timestamp: "2026-06-07T16:30:00+08:00"
task: "Fix auth token refresh race condition"
session_id: "20260607_163000_abc123"

decisions:
  - id: d1
    question: "Should we use mutex or atomic for the race condition?"
    chosen: "Mutex with timeout"
    reasoning: "Atomic doesn't guarantee ordering; mutex provides explicit locking semantics that match the business requirement (one refresh at a time)"
    alternatives_considered: ["Atomic counter", "Redis lock", "Queue-based"]

actions:
  - id: a1
    type: "file_write"
    target: "src/auth/refresh.ts"
    description: "Added mutex-based token refresh with 30s timeout"
    pre_state: "No locking mechanism, concurrent refresh possible"
    post_state: "Mutex guard with acquire/release pattern"
    
  - id: a2  
    type: "test_write"
    target: "tests/auth/refresh.test.ts"
    description: "Added concurrent refresh test case"
    
  - id: a3
    type: "command_exec"
    command: "npx tsc --noEmit"
    result: "PASS (0 errors)"

outcomes:
  verification: "auto-verify PASS"
  files_changed: ["src/auth/refresh.ts", "tests/auth/refresh.test.ts"]
  tests_passed: true
  delivered: true

risk_assessment:
  impact_level: "medium"  # auth is security-sensitive
  rollback_possible: true
  rollback_command: "git checkout HEAD -- src/auth/refresh.ts tests/auth/refresh.test.ts"
```

## When Audit Triggers

Audit triggers automatically after these events:

1. **File changes** — any write_file, patch, or terminal command that modifies project files
2. **Decision points** — when the agent chose between alternatives (e.g., architecture choices, API design)
3. **Delegation** — when delegating tasks to sub-agents (record what was delegated and why)
4. **Verification** — when auto-verify runs (pass/fail results)
5. **Escalation** — when an issue is escalated to human

## Audit Storage

```
.harness/audit/
  ├── YYYY-MM-DD-HHMMSS-task-summary.yaml   # individual entries
  ├── index.yaml                              # searchable index (date, task, tags)
  └── stats.yaml                              # aggregate stats (total tasks, pass rate, etc.)
```

The `.harness/` directory lives in the project root. It's gitignored by default but can be committed for compliance requirements.

## Index Structure

The index file enables fast searching without reading all entries:

```yaml
# .harness/audit/index.yaml
entries:
  - id: "2026-06-07T16:30:00-auth-fix"
    timestamp: "2026-06-07T16:30:00"
    task_summary: "Fix auth token refresh race condition"
    tags: ["auth", "security", "bug-fix"]
    outcome: "delivered"
    verification: "pass"
    files: ["src/auth/refresh.ts"]
  
  - id: "2026-06-07T14:00:00-doc-update"  
    timestamp: "2026-06-07T14:00:00"
    task_summary: "Update API documentation for v2 endpoints"
    tags: ["docs", "api"]
    outcome: "delivered"
    verification: "pass"
    files: ["docs/api/v2.md"]
```

## Stats Structure

```yaml
# .harness/audit/stats.yaml
total_tasks: 47
delivered: 39
auto_fixed: 5
escalated: 3
verification_pass_rate: 0.89
common_failure_patterns:
  - "typescript type errors in generated code"
  - "missing test coverage for new modules"
```

## Implementation in Agent Loop

When the agent completes a task, it should:

1. Check if `.harness/audit/` directory exists in the project. If not, create it.
2. Write the audit entry file using write_file
3. Update the index file using patch (append new entry)
4. Update stats file using patch (increment counters)

This happens as the LAST step of any task, after auto-verify completes.

## Executable Script

本 Skill 提供可执行脚本，可直接运行或通过 MCP 工具调用：

```bash
# 直接运行 — 查看审计摘要（表格格式）
python3 skills/auto-audit/audit_report.py --output table

# 查看审计详情
python3 skills/auto-audit/audit_report.py --output detail

# JSON 输出（机器可读）
python3 skills/auto-audit/audit_report.py --query "auth" --limit 20 --output json

# 通过 MCP 工具调用
mcp__harness-cook__harness_audit query="auth" limit=20
```

脚本功能：
1. 查询 harness `AuditEngine` 中的审计记录（支持关键词搜索）
2. 如果 harness 包不可用，回退到读取 `.harness/audit/` 目录的 JSON 文件
3. 支持三种输出格式：table（摘要）、detail（详情）、json（机器可读）
4. 处理两种数据源：`AuditEntry` 对象（harness 内建）和 dict（文件回退）

退出码：0（始终成功，审计是观测性的而非阻塞性的）

### 与 Implementation in Agent Loop 的关系

脚本提供了 Step "Implementation in Agent Loop" 中描述功能的**查询端**：
- 自动写入仍由 `hook-task-audit.py`（Stop hook）完成
- 脚本负责**读取和展示**已有审计记录
- MCP 工具 `harness_audit` 提供同样的查询能力

## Pitfalls

1. Don't write audit entries for trivial operations (reading a file, searching, etc.) — only for actions that change state or make decisions.
2. Don't let audit files grow unbounded — stats should track volume; if >100 entries, suggest archiving old ones.
3. Don't include secrets in audit entries — the redact_secrets config should apply here too.
4. Don't block task delivery on audit failure — audit is observational, not a gate. If audit writing fails, still deliver the task, just log the audit failure separately.
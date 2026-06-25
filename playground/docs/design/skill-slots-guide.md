# Skill 插槽点完整指南

> 17 个插槽点，覆盖 Agent 执行的完整生命周期

## 插槽点分类

### 1. 会话级（2个）

| 插槽 | 触发时机 | 典型用途 | 示例 Skills |
|------|---------|---------|------------|
| `SESSION_START` | 会话开始 | 环境初始化、加载配置、显示欢迎信息 | `env-setup`, `welcome-banner` |
| `SESSION_END` | 会话结束 | 清理临时文件、生成会话摘要、保存状态 | `session-summary`, `cleanup` |

### 2. 任务级（3个）

| 插槽 | 触发时机 | 典型用途 | 示例 Skills |
|------|---------|---------|------------|
| `PRE_EXECUTE` | Agent 执行任务前 | 输入验证、权限检查、依赖检查 | `validate-input`, `check-deps` |
| `POST_EXECUTE` | Agent 执行任务后 | 结果验证、审计记录、通知 | `auto-audit`, `notify-result` |
| `ON_ERROR` | 任务执行异常时 | 错误记录、自动恢复、告警 | `error-handler`, `auto-recover` |

### 3. 工具级（2个）

| 插槽 | 触发时机 | 典型用途 | 示例 Skills |
|------|---------|---------|------------|
| `PRE_TOOL_USE` | 使用工具前 | 权限检查、内容过滤、风险评估 | `permission-check`, `content-filter` |
| `POST_TOOL_USE` | 使用工具后 | 结果验证、合规扫描、PII 检测 | `compliance-scan`, `pii-detect` |

### 4. 门禁级（2个）

| 插槽 | 触发时机 | 典型用途 | 示例 Skills |
|------|---------|---------|------------|
| `ON_GATE_PASS` | 门禁检查通过后 | 自动部署、生成报告、标记完成 | `auto-deploy`, `generate-report` |
| `ON_GATE_FAIL` | 门禁检查失败时 | 自动修复、升级人工、生成修复建议 | `auto-fix`, `escalate-human` |

### 5. 文件级（1个）

| 插槽 | 触发时机 | 典型用途 | 示例 Skills |
|------|---------|---------|------------|
| `ON_FILE_CHANGE` | 文件变更时 | 自动格式化、lint 检查、同步更新 | `auto-format`, `lint-check`, `sync-deps` |

### 6. 提交级（2个）

| 插槽 | 触发时机 | 典型用途 | 示例 Skills |
|------|---------|---------|------------|
| `PRE_COMMIT` | 提交代码前 | 代码审查、测试运行、提交信息检查 | `auto-review`, `run-tests` |
| `POST_COMMIT` | 提交代码后 | 推送通知、更新看板、触发 CI | `notify-push`, `trigger-ci` |

### 7. 协作级（2个）

| 插槽 | 触发时机 | 典型用途 | 示例 Skills |
|------|---------|---------|------------|
| `ON_DELEGATE` | 委派任务给子 Agent 时 | 记录委派原因、设置超时、监控进度 | `delegate-tracker` |
| `ON_CONFLICT` | 检测到冲突时 | 冲突分析、自动合并、人工仲裁 | `conflict-analyzer` |

### 8. 决策级（2个）

| 插槽 | 触发时机 | 典型用途 | 示例 Skills |
|------|---------|---------|------------|
| `ON_DECISION` | Agent 做出重要决策时 | 记录决策原因、评估风险、存档 | `decision-logger` |
| `ON_ESCALATION` | 问题升级到人工时 | 通知相关人、生成上下文、暂停等待 | `notify-human` |

### 9. 交互级（1个）

| 插槽 | 触发时机 | 典型用途 | 示例 Skills |
|------|---------|---------|------------|
| `USER_PROMPT_SUBMIT` | 用户提交提示词时 | 提示词优化、安全检查、上下文注入 | `prompt-enhancer` |

---

## 与 Claude Code Hooks 的映射

| Skill 插槽 | Claude Code Hook | 说明 |
|-----------|------------------|------|
| `SESSION_START` | `SessionStart` | ✅ 直接映射 |
| `SESSION_END` | `Stop` | ✅ 直接映射 |
| `PRE_TOOL_USE` | `PreToolUse` | ✅ 直接映射 |
| `POST_TOOL_USE` | `PostToolUse` | ✅ 直接映射 |
| `USER_PROMPT_SUBMIT` | `UserPromptSubmit` | ✅ 直接映射 |
| `PRE_EXECUTE` | `PreToolUse` | 映射到工具使用前 |
| `POST_EXECUTE` | `PostToolUse` | 映射到工具使用后 |
| `ON_FILE_CHANGE` | `PostToolUse` + matcher | 通过 matcher 过滤 Write/Edit |
| `ON_ERROR` | 内部实现 | 通过异常捕获触发 |
| `ON_GATE_PASS/FAIL` | 内部实现 | 通过门禁检查触发 |
| `PRE_COMMIT` | 内部实现 | 通过 git 命令拦截 |
| `POST_COMMIT` | 内部实现 | 通过 git 命令拦截 |
| `ON_DELEGATE` | 内部实现 | 通过委派机制触发 |
| `ON_CONFLICT` | 内部实现 | 通过冲突检测触发 |
| `ON_DECISION` | 内部实现 | 通过决策记录触发 |
| `ON_ESCALATION` | 内部实现 | 通过升级机制触发 |

---

## 内置 Skills 与插槽映射

| Skill | 插槽 | 功能 |
|-------|------|------|
| `auto-audit` | `POST_EXECUTE` | 任务完成后自动记录审计日志 |
| `auto-review` | `POST_EXECUTE` | 代码变更后自动审查 |
| `auto-verify` | `ON_GATE_PASS` | 门禁通过后自动验证 |
| `harness-bridge` | 多插槽 | 桥接 harness 核心能力 |

---

## 配置示例

```yaml
# .harness/profiles/default.yaml
profile:
  name: default

skills:
  # 会话级
  - id: env-setup
    slot: session_start
    command: "python3 skills/env-setup/init.py"

  # 任务级
  - id: auto-audit
    slot: post_execute
    command: "python3 skills/auto-audit/audit.py"

  # 门禁级
  - id: auto-fix
    slot: on_gate_fail
    command: "python3 skills/auto-fix/fix.py"

  # 决策级
  - id: decision-logger
    slot: on_decision
    command: "python3 skills/decision-logger/log.py"
```

---

## 总结

**17 个插槽点**覆盖了 Agent 执行的完整生命周期——从会话开始到结束，从工具调用到决策升级，每个关键节点都可以挂载自定义 Skills，实现真正的"可配置脚手架"。

# Skill 插槽点扩展总结

> 从 7 个到 17 个的扩展过程和分类

## 变更概览

将 Skill 插槽点从 **7 个**扩展到 **17 个**，覆盖 Agent 执行的完整生命周期。

### 原有 7 个

1. SESSION_START
2. SESSION_END
3. PRE_EXECUTE
4. POST_EXECUTE
5. ON_ERROR
6. ON_GATE_PASS
7. ON_GATE_FAIL

### 新增 10 个

8. `PRE_TOOL_USE` — 使用工具前
9. `POST_TOOL_USE` — 使用工具后
10. `ON_FILE_CHANGE` — 文件变更时
11. `PRE_COMMIT` — 提交代码前
12. `POST_COMMIT` — 提交代码后
13. `ON_DELEGATE` — 委派任务时
14. `ON_CONFLICT` — 检测到冲突时
15. `ON_DECISION` — 做出重要决策时
16. `ON_ESCALATION` — 问题升级到人工时
17. `USER_PROMPT_SUBMIT` — 用户提交提示词时

## 插槽分类

| 分类 | 数量 | 插槽 |
|------|------|------|
| 会话级 | 2 | SESSION_START, SESSION_END |
| 任务级 | 3 | PRE_EXECUTE, POST_EXECUTE, ON_ERROR |
| 工具级 | 2 | PRE_TOOL_USE, POST_TOOL_USE |
| 门禁级 | 2 | ON_GATE_PASS, ON_GATE_FAIL |
| 文件级 | 1 | ON_FILE_CHANGE |
| 提交级 | 2 | PRE_COMMIT, POST_COMMIT |
| 协作级 | 2 | ON_DELEGATE, ON_CONFLICT |
| 决策级 | 2 | ON_DECISION, ON_ESCALATION |
| 交互级 | 1 | USER_PROMPT_SUBMIT |

## 与 Claude Code Hooks 映射

| Skill 插槽 | Claude Code Hook | 实现方式 |
|-----------|------------------|----------|
| `SESSION_START` | `SessionStart` | ✅ 直接映射 |
| `SESSION_END` | `Stop` | ✅ 直接映射 |
| `PRE_TOOL_USE` | `PreToolUse` | ✅ 直接映射 |
| `POST_TOOL_USE` | `PostToolUse` | ✅ 直接映射 |
| `USER_PROMPT_SUBMIT` | `UserPromptSubmit` | ✅ 直接映射 |
| `PRE_EXECUTE` | `PreToolUse` | 映射到工具使用前 |
| `POST_EXECUTE` | `PostToolUse` | 映射到工具使用后 |
| `ON_FILE_CHANGE` | `PostToolUse` + matcher | 通过 matcher 过滤 |
| `ON_ERROR` | 内部实现 | 异常捕获触发 |
| `ON_GATE_PASS/FAIL` | 内部实现 | 门禁检查触发 |
| `ON_ESCALATION` | 内部实现 | 升级机制触发 |
| `PRE_COMMIT` | 内部实现 | git 命令拦截 |
| `POST_COMMIT` | 内部实现 | git 命令拦截 |
| `ON_DELEGATE` | 内部实现 | 委派机制触发 |
| `ON_CONFLICT` | 内部实现 | 冲突检测触发 |
| `ON_DECISION` | 内部实现 | 决策记录触发 |

## 修改文件

1. **packages/core/harness/types.py** — 扩展 SkillSlotName 枚举，新增 10 个插槽点
2. **packages/core/harness/bridge.py** — 更新 HOOK_POINT_MAP，优化映射逻辑
3. **packages/core/harness/engine.py** — 异常处理添加 ON_ERROR 插槽，门禁升级添加 ON_ESCALATION

## 典型 Skills 示例

### 工具级
- `permission-check` — PRE_TOOL_USE：检查工具使用权限
- `compliance-scan` — POST_TOOL_USE：扫描合规性
- `pii-detect` — POST_TOOL_USE：检测 PII 信息

### 文件级
- `auto-format` — ON_FILE_CHANGE：自动格式化代码
- `lint-check` — ON_FILE_CHANGE：Lint 检查

### 提交级
- `auto-review` — PRE_COMMIT：自动代码审查
- `run-tests` — PRE_COMMIT：运行测试
- `trigger-ci` — POST_COMMIT：触发 CI

### 协作级
- `delegate-tracker` — ON_DELEGATE：跟踪委派任务
- `auto-merge` — ON_CONFLICT：自动合并

### 决策级
- `decision-logger` — ON_DECISION：记录决策
- `notify-human` — ON_ESCALATION：通知人工

## 测试结果

✅ 37 passed in 0.11s

## 价值

1. **细粒度控制** — 17 个插槽点覆盖了 Agent 执行的每个关键节点
2. **可扩展** — 用户可以在任意插槽挂载自定义 Skills
3. **业界对齐** — 与 Claude Code hooks、业界标准 Skill 模式对齐
4. **完整生命周期** — 从会话开始到结束，从工具调用到决策升级，全覆盖

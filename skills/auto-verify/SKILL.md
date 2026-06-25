---
name: auto-verify
description: "Automatic verification harness — Agent checks its own work after completing a task. Reduces human verification burden."
version: 1.0.0
trigger: After completing any code/config/doc change task, before committing or delivering results. Source lives in ~/ProjectsOnGitlab/harness-cook/skills/auto-verify/SKILL.md
---

# Auto-Verify Skill

Agent completes a task → this skill triggers → automated quality checks run → pass = deliver, fail = auto-fix or escalate.

## Verification Pipeline

### Step 1: Detect what was changed

```
git diff --name-only HEAD (or git status for uncommitted changes)
```

Classify each changed file by type:
- `.ts/.js/.py/.go` → code
- `.md/.txt` → docs
- `.yaml/.json/.toml` → config
- `.css/.scss/.less` → style

### Step 2: Run type-specific checks

#### Code files (.ts/.js/.py)

```bash
# TypeScript/JavaScript
npx tsc --noEmit                    # type check
npx eslint <changed-files>          # lint (if .eslintrc exists)
npm run test -- --changed           # run related tests (if available)

# Python
python -m py_compile <file>         # syntax check
ruff check <file>                   # lint (if ruff installed)
pytest <related-test-file>          # run related tests (if available)
```

Only run tools that exist in the project. Check first:
```bash
[ -f "tsconfig.json" ] && echo "has-ts"
[ -f ".eslintrc*" ] || [ -f "eslint.config.*" ] && echo "has-eslint"
[ -f "pytest.ini" ] || [ -f "pyproject.toml" ] && echo "has-pytest"
```

#### Config files (.yaml/.json/.toml)

```bash
# Validate YAML syntax
python3 -c "import yaml; yaml.safe_load(open('<file>'))"

# Validate JSON syntax
python3 -c "import json; json.load(open('<file>'))"

# Validate TOML syntax
python3 -c "import tomllib; tomllib.load(open('<file>', 'rb'))"
```

#### Doc files (.md)

```bash
# Check markdown lint (if mdlint available)
npx markdownlint <file>

# Check link integrity (relative links only — local files)
grep -oP '\[.*?\]\((?!http)(.*?)\)' <file> | check each path exists
```

### Step 3: Aggregate results

Build a verification report:

```
VERIFICATION REPORT
===================
Files changed: 3
  - src/auth.ts (code)
  - config.yaml (config)  
  - README.md (docs)

Checks run: 5
  ✅ tsc --noEmit: PASS (0 errors)
  ✅ yaml safe_load: PASS
  ✅ markdown link check: PASS
  ❌ eslint src/auth.ts: FAIL (2 errors)
    - line 12: unexpected var, use let/const
    - line 34: missing return type annotation
  ⚠️ pytest: SKIPPED (no test found for auth.ts)

Overall: FAIL (1 check failed)
```

### Step 4: Decision logic

| Result | Action |
|--------|--------|
| ALL PASS | Proceed — commit/deliver results |
| MINOR FAIL (lint/style) | Auto-fix with patch, re-verify, then proceed |
| MAJOR FAIL (type errors, test failures) | Return failure details to the calling agent for self-correction |
| NO CHECKS AVAILABLE | Proceed with warning — flag for human review if gateway connected |

### Step 5: Auto-fix loop (minor failures only)

For lint/style issues, attempt auto-fix:
```bash
npx eslint --fix <file>     # auto-fix lint
npx prettier --write <file> # auto-fix format
```

After auto-fix, re-run verification. Max 3 auto-fix cycles. If still failing after 3 cycles, escalate.

### Step 6: Escalation trigger

Escalate to human ONLY when:
- Type errors that can't be auto-fixed
- Test failures after 2 correction attempts
- No verification tools available in the project
- Security/compliance concerns detected

## Executable Script

本 Skill 提供可执行脚本，可直接运行或通过 MCP 工具调用：

```bash
# 直接运行（终端）
python3 skills/auto-verify/verify.py --path . --packs security,coding --output table

# JSON 输出（机器可读）
python3 skills/auto-verify/verify.py --path . --packs security,coding --output json

# 通过 MCP 工具调用
mcp__harness-cook__harness_check path="." pack_names=["security", "coding"]
```

脚本功能：
1. 获取 git diff 变更文件列表
2. 调用 harness `ComplianceEngine` 合规扫描（支持 coding/security/data/devops 规则包）
3. 对变更文件做语法检查（Python/YAML/JSON/TOML）
4. 输出验证报告（通过/失败 + 详细违规列表）

退出码：0 = 全部通过，1 = 有违规或检查失败

### 与 Step 2 的关系

脚本中的合规扫描对应 Step 2 的"类型检查"步骤，**额外**提供了：
- harness ComplianceEngine 合规扫描（检查安全违规、编码规范等）
- 多格式输出（table/json）
- 退出码支持（可直接在 CI/CD 中使用）

## Pitfalls

1. Don't run full project test suite on every change — only run tests related to changed files. Full suite is too slow and wastes tokens.
2. Don't assume tools exist — always check first with `[ -f ... ]` or `which`.
3. Don't auto-fix type errors or logic bugs — only auto-fix lint/style. Logic errors need the calling agent to reason about.
4. Don't run verification on files you didn't change — stick to `git diff` output.
5. For projects without any verification infrastructure, don't block delivery — just note "unverified" and proceed.
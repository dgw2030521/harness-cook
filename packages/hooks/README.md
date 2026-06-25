# harness hooks

harness-cook 的 hook 脚本集合，为各 Agent 平台提供执行阶段约束。完整介绍见根目录 [README](../../README.md)。

## 定位

hook 是 Agent 执行流各阶段（session 启动、pre/post execute、文件变更、gate 通过/失败等）触发的脚本，承载"Hooks 定约束"那一层。在有原生 hooks 的平台（Claude Code / Copilot CLI）直接注入 settings.json；在无 hooks 的平台经 MCP Server 等价能力承载。

## 内容

- `git-pre-commit-hook.sh` — git pre-commit 兜底，不合规代码无法通过 commit
- 各生命周期插槽的 hook 脚本（session-init / pre-execute / post-execute / on-gate-fail 等）

> 所有 Agent 默认安装 git pre-commit hook 作为双保险：即使平台层 hook 失效，commit 阶段仍会拦截。

## 与 skills 的区别

- **hooks** 定约束（是否允许、是否拦截）
- **skills** 定步骤（如何执行某段流程）

详见 [docs/38-Hook槽位映射机制与多平台架构演进-20260615.md](../../docs/38-Hook槽位映射机制与多平台架构演进-20260615.md)。

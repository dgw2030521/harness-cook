# 变更日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 规范，并采用 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.1.0] - 2026-06-25

首个公开版本（Alpha）。harness-cook 定位为 **Agent 治理集成总线**：不重复造底层引擎，专注对接 Guardrails AI、SonarQube、OPA、Langfuse 等专业组件，承载 Profile 声明式配置、分级门禁、引擎路由总线、MCP 注入四类核心不可外包能力。

### 新增

- **Profile 声明式配置**：一份 YAML 统一定义护栏 / 合规 / 门禁 / 审计策略，Bridge 自动翻译为各 Agent 原生格式。
- **三档分级门禁**：strict（阻断）/ hybrid（人工审批）/ loose（仅记录）三种模式，支持不合规内容实时拦截。
- **引擎路由总线**：PatternRegistry 统一注册检测引擎，语言感知自动路由（Java→ArchUnit、JS→dep-cruiser 等），4 级降级策略保障引擎异常时业务不中断。
- **MCP 注入**：将治理能力封装为 25 个标准 MCP 工具注入 Agent 运行环境。
- **5 个 Agent 适配器**：claude-code（原生 hooks）、copilot-cli（hooks + MCP 双通道）、hermes、cursor、openai（MCP / function calling），新增平台仅需一个 `.py` 文件。
- **架构合规规则系统**：7 条跨文件架构规则（ARCH-001 分层依赖 / ARCH-002 循环依赖 / ARCH-003 过深依赖链 / ARCH-004 God Class / ARCH-005 深继承链 / ARCH-006 分散逻辑 / ARCH-007 重复抽象），支持 11 种语言。
- **知识库三层治理**：architecture / convention / risk / decision / pattern 等知识类型，支持语义检索与一键激活为合规规则。
- **可观测性**：审计日志、可视化看板（packages/dashboard），审计链可校验。
- **跨平台部署**：`harness activate` 一键部署到目标 Agent 平台，自动安装 git pre-commit hook 兜底。
- **多语言 SDK**：Python SDK、TypeScript SDK、VS Code 扩展、CLI 工具。

[Unreleased]: https://github.com/harness-cook/harness-cook/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/harness-cook/harness-cook/releases/tag/v0.1.0

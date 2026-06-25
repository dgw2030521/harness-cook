# 设计思路

> harness-cook 的设计决策记录——每个模块为什么这样设计、走过什么弯路、最终为什么选了这个方案。

这里公开的是项目设计过程中有学习价值的技术决策文档。涵盖方法论对照、架构定位、机制设计、知识治理四大维度。

## 设计哲学

- [从 Prompt Engineering 到 Harness Engineering](/design/philosophy-intro) — 为什么 Prompt 不够？Harness Engineering 的五大原则和六大运行时组件
- [方法论对照分析](/design/methodology-comparison) — harness-cook 如何全面覆盖并超越 Harness Engineering 方法论
- [与 AI Agent 架构的机制对比](/design/agent-architecture-comparison) — 两者共享同一结构骨架，但填入的内容不同

## 架构定位与策略

- [编排平台治理中间件](/design/governance-middleware) — harness-cook 从 MCP 插件进化到编排框架治理中间件
- [适配器架构与多 Agent 部署](/design/adapter-architecture) — 5 个适配器的策略层级分析，无-hooks Agent 的治理增强方向
- [Prompt-Driven 强提示 + Git Hook 补偿](/design/prompt-driven-git-hook) — 已实现的"事前提示 + 事后拦截"双保险方案
- [.harness 作为项目配置总目录](/design/harness-directory) — 内置 hook/skill 直接调用、项目自包含的架构决策

## 机制与工程

- [Skill 插槽点完整指南](/design/skill-slots-guide) — 17 个插槽点，覆盖 Agent 执行的完整生命周期
- [Skill 插槽点扩展总结](/design/skill-slots-extension) — 从 7 个到 17 个的扩展过程和分类
- [Hook 槽位映射机制](/design/hook-slot-mapping) — 17 个自定义槽位如何映射到 Claude Code 原生 hook 事件
- [路径处理机制](/design/path-resolution) — 内置路径绝对化转换 + 多级检测策略
- [降级机制与内置托底](/design/degradation-fallback) — "不装不影响，装了自动增强"的吸收式架构

## 知识治理

- [知识库与 Memory 互补关系](/design/knowledge-memory-design) — 知识库管"项目发现了什么"，Memory 管"人怎么想"；MCP 工具主动查询而非注入

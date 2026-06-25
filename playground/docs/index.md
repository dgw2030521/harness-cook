---
layout: home

hero:
  name: harness-cook
  text: Agent 治理集成总线
  tagline: "不造发动机，造方向盘 + 仪表盘 + 刹车踏板 —— 让 AI 从「能干活」变成「可靠地干活」"
  actions:
    - theme: brand
      text: 快速开始
      link: /guide/quick-start
    - theme: alt
      text: 什么是 Harness
      link: /guide/what-is-harness
    - theme: alt
      text: Demo
      link: /demo/

features:
  - icon: 🚌
    title: 治理集成总线
    details: "像 Kubernetes 一样做治理总线——护栏委托 Guardrails AI/NeMo，合规委托 SonarQube/ArchUnit/OPA，审计委托 Langfuse/Arize/Datadog。只保留组合价值：Profile配置 + 三档门禁 + 引擎路由 + MCP注入。"
  - icon: 🚧
    title: 三档门禁系统
    details: "GateEngine 三级门禁模式 (strict / hybrid / loose)——编排层不做、审计层不做、合规层不做，只有 harness-cook 做事前拦截。违规产出不交付，合规不通过升级人工。"
  - icon: 🔀
    title: 引擎路由总线
    details: "MatcherRegistry + IAuditStore + IAgentAdapter 三总线——ExternalEngineChecker 模板方法：探测→fallback→翻译→调用→翻译响应→catch回退。多类别引擎集成（护栏/合规/审计/导出/编排中间件五大类），引擎不可用时自动降级到内置 checker。"
  - icon: 🔌
    title: MCP 注入 · Bridge 部署
    details: "一份 Profile YAML → Bridge 条件分支部署到 5 个 Agent 平台（Claude/Copilot/Hermes/Cursor/OpenAI）→ hook-capable Agent 用 mild prompt + hooks 自动触发，no-hooks Agent 用 mandatory prompt + git hook 兜底。MCP Server 25 个工具注入 Agent 环境。"
  - icon: 📏
    title: 合规引擎 + 语言感知路由
    details: "ComplianceEngine 4 个内置 RulePack (26 条规则) + 外部引擎 (SonarQube/ArchUnit/dep-cruiser/OPA) + 语言感知自动路由 (Java→ArchUnit, JS→dep-cruiser, 通用→OPA) + 规则导入器。"
  - icon: 🔒
    title: 审计多后端 + OTel 标准化
    details: "MultiAuditStore 本地永远主存储 + Langfuse/Arize/Datadog/Helicone 按配置叠加（火忘式双写）。IAuditStore Protocol 统一契约。审计事件 → OTel Span 格式，任何 collector 可消费。"
---

<div class="vp-home-extra">

## ⚡ 一行命令上手

```bash
git clone <repo-url> && cd harness-cook
harness activate                  # 默认 Claude Code
harness activate --agent hermes   # Hermes
harness activate --agent cursor   # Cursor IDE
```

重启 Agent 平台即可生效。还原只需 `harness deactivate`，不留任何配置残留。

📖 5 分钟完整流程 → [快速开始](/guide/quick-start)

## 🎯 支持的 Agent 平台

5 个适配器，按治理强度分两类：

- **强制性**（hooks 自动触发）：Claude Code、Copilot CLI —— mild prompt，hooks 即治理
- **建议性→接近强制**（MCP + mandatory prompt + git hook 兜底）：Hermes、Cursor、OpenAI

> 📖 各平台详细对比 + 3 步激活 + 配置对照表 → [Agent 平台指南](/guide/agent-platforms) · [Adapter 快速上手](/guide/adapter-quickstart)

</div>

<style>
.vp-home-extra {
  max-width: 960px;
  margin: 0 auto;
  padding: 48px 24px 64px;
}
.vp-home-extra h2 {
  font-size: 20px;
  font-weight: 600;
  margin-bottom: 16px;
  border-bottom: none;
  letter-spacing: -0.02em;
}
.vp-home-extra pre {
  border-radius: 8px;
  margin-bottom: 8px;
}
.vp-home-extra table {
  width: 100%;
  font-size: 14px;
}
</style>

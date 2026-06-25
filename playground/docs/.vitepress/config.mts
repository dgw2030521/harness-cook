import { defineConfig } from 'vitepress'
import { withMermaid } from 'vitepress-plugin-mermaid'

export default withMermaid(defineConfig({
  lang: 'zh-CN',
  title: 'harness-cook',
  description: '通用 Agent Harness SDK —— Agent 决策执行，Harness 稳定约束',

  // GitHub Pages 部署路径：
  //   根仓库 <user>.github.io            → '/'
  //   子路径 <user>.github.io/<repo>/    → '/<repo>/'
  base: '/harness-cook/',

  ignoreDeadLinks: true,

  themeConfig: {
    nav: [
      { text: '指南', link: '/guide/' },
      { text: '设计思路', link: '/design/' },
      { text: '教程', link: '/tutorial/' },
      { text: 'Demo', link: '/demo/' },
      { text: 'CLI', link: '/cli/' },
    ],

    sidebar: {
      '/design/': [
        {
          text: '设计思路总览',
          items: [
            { text: '总览', link: '/design/' },
          ],
        },
        {
          text: '设计哲学',
          items: [
            { text: 'Harness Engineering', link: '/design/philosophy-intro' },
            { text: '方法论覆盖分析', link: '/design/methodology-comparison' },
            { text: '形态与 Agent 关系', link: '/design/harness-form-and-agent' },
            { text: 'Agent 架构对比', link: '/design/agent-architecture-comparison' },
          ],
        },
        {
          text: '架构定位与策略',
          items: [
            { text: '编排平台治理中间件', link: '/design/governance-middleware' },
            { text: '适配器架构与多 Agent 部署', link: '/design/adapter-architecture' },
            { text: 'Prompt-Driven + Git Hook', link: '/design/prompt-driven-git-hook' },
            { text: '.harness 目录设计', link: '/design/harness-directory' },
          ],
        },
        {
          text: '机制与工程',
          items: [
            { text: 'Skill 插槽点指南', link: '/design/skill-slots-guide' },
            { text: 'Skill 插槽点扩展', link: '/design/skill-slots-extension' },
            { text: 'Hook 槽位映射', link: '/design/hook-slot-mapping' },
            { text: '路径处理机制', link: '/design/path-resolution' },
            { text: '降级机制与内置托底', link: '/design/degradation-fallback' },
          ],
        },
        {
          text: '知识治理',
          items: [
            { text: '知识库与 Memory 互补', link: '/design/knowledge-memory-design' },
          ],
        },
      ],
      '/guide/': [
        {
          text: '基础入门',
          items: [
            { text: '指南总览', link: '/guide/' },
            { text: '什么是 Harness', link: '/guide/what-is-harness' },
            { text: '快速开始', link: '/guide/quick-start' },
            { text: '核心概念', link: '/guide/core-concepts' },
          ],
        },
        {
          text: '治理四层',
          items: [
            { text: '护栏层', link: '/guide/guardrails-layer' },
            { text: '合规层', link: '/guide/compliance-layer' },
            { text: '审计层', link: '/guide/audit-layer' },
            { text: '门禁层', link: '/guide/gate-layer' },
            { text: '门禁通知', link: '/guide/gate-notification' },
          ],
        },
        {
          text: '智能增强',
          items: [
            { text: '自学习与推荐', link: '/guide/learning' },
            { text: '知识管理', link: '/guide/knowledge' },
            { text: '影响分析', link: '/guide/impact-analysis' },
            { text: '污点追踪', link: '/guide/taint-tracking' },
          ],
        },
        {
          text: '执行管控',
          items: [
            { text: 'DAG 编排引擎', link: '/guide/dag-engine' },
            { text: '智能调度器', link: '/guide/scheduler' },
            { text: '多 Agent 协商', link: '/guide/negotiation' },
            { text: '降级策略', link: '/guide/downgrade' },
            { text: '自动回滚', link: '/guide/rollback' },
            { text: 'Agent 约束与资源管控', link: '/guide/constraints' },
          ],
        },
        {
          text: '引擎集成',
          items: [
            { text: '引擎集成总线', link: '/guide/engine-bus' },
            { text: '规则包', link: '/guide/rule-packs' },
            { text: '声明式规则', link: '/guide/declarative-rules' },
            { text: '规则市场', link: '/guide/rule-market' },
          ],
        },
        {
          text: '编排平台',
          items: [
            { text: 'LangGraph 中间件', link: '/guide/langgraph-middleware' },
            { text: 'DeerFlow 桥接', link: '/guide/deerflow-bridge' },
            { text: '自主循环(@experimental)', link: '/guide/autonomous-loop' },
          ],
        },
        {
          text: '接入与配置',
          items: [
            { text: '@harness_agent 装饰器', link: '/guide/decorators' },
            { text: '配置系统', link: '/guide/config-system' },
            { text: '依赖注入模式', link: '/guide/dependency-injection' },
            { text: 'Hook 注册与执行', link: '/guide/hook-registry' },
            { text: 'Skill 插槽点', link: '/guide/skill-slots' },
            { text: 'Superpowers Bridge', link: '/guide/superpowers-bridge' },
          ],
        },
        {
          text: 'Agent 平台',
          items: [
            { text: 'Agent 平台指南', link: '/guide/agent-platforms' },
            { text: 'Adapter 快速上手', link: '/guide/adapter-quickstart' },
            { text: 'Claude Code', link: '/guide/agent-claude-code' },
            { text: 'Hermes', link: '/guide/agent-hermes' },
            { text: 'Copilot CLI', link: '/guide/agent-copilot-cli' },
            { text: 'Cursor', link: '/guide/agent-cursor' },
            { text: 'OpenAI/Codex', link: '/guide/agent-openai' },
          ],
        },
        {
          text: '工具与界面',
          items: [
            { text: 'Bridge', link: '/guide/bridge' },
            { text: 'CLI', link: '/guide/cli' },
            { text: 'MCP Server', link: '/guide/mcp-server' },
            { text: 'Dashboard', link: '/guide/dashboard' },
            { text: '可视化报告', link: '/guide/report' },
            { text: 'OTel 集成', link: '/guide/otel-integration' },
          ],
        },
        {
          text: '内部机制',
          items: [
            { text: '调用链追踪', link: '/guide/call-graph' },
            { text: 'Agent 调用分层路由', link: '/guide/llm-tiering' },
            { text: 'Agents 模块', link: '/guide/agents-module' },
          ],
        },
      ],
      '/cli/': [
        {
          text: 'CLI 命令参考',
          items: [
            { text: '全部命令', link: '/cli/' },
          ],
        },
        {
          text: '安装与更新',
          items: [
            { text: 'activate', link: '/cli/activate' },
            { text: 'deactivate', link: '/cli/deactivate' },
            { text: 'update', link: '/cli/update' },
            { text: 'version', link: '/cli/version' },
          ],
        },
        {
          text: '编排与执行',
          items: [
            { text: 'plan', link: '/cli/plan' },
            { text: 'run', link: '/cli/run' },
          ],
        },
        {
          text: '合规与审计',
          items: [
            { text: 'check', link: '/cli/check' },
            { text: 'audit', link: '/cli/audit' },
            { text: 'report', link: '/cli/report' },
            { text: 'log', link: '/cli/log' },
          ],
        },
        {
          text: '智能与知识',
          items: [
            { text: 'knowledge', link: '/cli/knowledge' },
            { text: 'learn', link: '/cli/learn' },
          ],
        },
        {
          text: '可视化与文档',
          items: [
            { text: 'dashboard', link: '/cli/dashboard' },
            { text: 'docs', link: '/cli/docs' },
          ],
        },
      ],
      '/tutorial/': [
        {
          text: '基础入门',
          items: [
            { text: '教程简介', link: '/tutorial/' },
            { text: '基础用法', link: '/tutorial/basic-usage' },
          ],
        },
        {
          text: '治理层',
          items: [
            { text: '护栏使用', link: '/tutorial/guardrails-usage' },
            { text: '合规扫描', link: '/tutorial/compliance-scan' },
            { text: '审计使用', link: '/tutorial/audit-usage' },
            { text: '门禁审批', link: '/tutorial/gate-approval' },
          ],
        },
        {
          text: '编排与执行',
          items: [
            { text: 'DAG 工作流', link: '/tutorial/dag-workflow' },
            { text: 'Pipeline 编排', link: '/tutorial/pipeline' },
            { text: '降级与回滚', link: '/tutorial/downgrade-rollback' },
          ],
        },
        {
          text: '集成与部署',
          items: [
            { text: 'Adapter 部署', link: '/tutorial/adapter-deployment' },
            { text: 'MCP 集成', link: '/tutorial/mcp-integration' },
            { text: '法律风险扫描', link: '/tutorial/legal-scan' },
            { text: 'Superpowers Bridge', link: '/tutorial/superpowers-skill-bridge' },
          ],
        },
      ],
      '/demo/': [
        {
          text: '核心功能',
          items: [
            { text: 'Demo 总览', link: '/demo/' },
            { text: '护栏 Demo', link: '/demo/guardrails' },
            { text: '合规 Demo', link: '/demo/compliance' },
            { text: '审计 Demo', link: '/demo/audit' },
            { text: '门禁 Demo', link: '/demo/gate' },
          ],
        },
        {
          text: '编排与执行',
          items: [
            { text: 'Pipeline 编排 Demo', link: '/demo/pipeline' },
            { text: 'DAG 工作流 Demo', link: '/demo/dag-workflow' },
            { text: '协商 Demo', link: '/demo/negotiation' },
            { text: '学习 + 调度 Demo', link: '/demo/learning-scheduler' },
            { text: '降级 + 回滚 Demo', link: '/demo/downgrade-rollback' },
            { text: '自主循环 Demo', link: '/demo/autonomous-loop' },
            { text: 'Agent 调用分层路由 Demo', link: '/demo/llm-tiering' },
          ],
        },
        {
          text: '引擎与集成',
          items: [
            { text: '引擎集成 Demo', link: '/demo/engine-integration' },
            { text: '外部引擎集成 Demo', link: '/demo/external-engines' },
            { text: 'MCP 全量 Demo', link: '/demo/mcp-full' },
            { text: 'Superpowers Bridge Demo', link: '/demo/superpowers-bridge' },
            { text: 'CodeGraph 同步 Demo', link: '/demo/codegraph-sync' },
            { text: '审计后端 Demo', link: '/demo/audit-backends' },
          ],
        },
        {
          text: '分析与验证',
          items: [
            { text: '代码分析 Demo', link: '/demo/analysis' },
            { text: 'Lint 检查 Demo', link: '/demo/lint-check' },
            { text: '自动测试 Demo', link: '/demo/auto-test' },
            { text: '知识/规则/报告 Demo', link: '/demo/knowledge-rule-report' },
            { text: '法律风险扫描 Demo', link: '/demo/legal-scan' },
          ],
        },
        {
          text: '综合',
          items: [
            { text: '完整工作流 Demo', link: '/demo/complete-workflow' },
            { text: '全面验证', link: '/demo/verification' },
          ],
        },
      ],
    },

    search: {
      provider: 'local',
    },

    footer: {
      message: 'Released under the MIT License.',
      copyright: 'Copyright © 2026 harness-cook contributors',
    },
  },
}), { class: 'mermaid' })

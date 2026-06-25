# Harness Cook Examples

> **代码展示**——可直接运行的 Python 脚本集合。每个子目录包含完整脚本和依赖，`pip install` 后即可跑起来。

**定位**：`examples/` = **可运行的代码**，`playground/docs/demo/` = **文档介绍**。同一个主题，examples 给你脚本直接跑，demo 给你文档看原理和预期输出。想跑代码 → 来这里；想看讲解 → 去 Demo。

---

## 示例总览

| 示例 | 定位 | 难度 | 有对应 Demo? |
|------|------|------|-------------|
| **入门与基础** | | | |
| [simple-agent](./simple-agent/) | 最简入门：一个 Agent + 一个约束 + 一个任务 | ⭐ | ❌ |
| [multi-agent](./multi-agent/) | 多 Agent 协作：Coder → Reviewer → Tester | ⭐⭐ | ❌ |
| [custom-rules](./custom-rules/) | 自定义合规规则包，harness-cook 自动发现加载 | ⭐⭐ | ❌ |
| [declarative-rules](./declarative-rules/) | YAML 声明式门禁规则，无需写 Python | ⭐⭐ | ❌ |
| **自动化 Hook** | | | |
| [auto-test](./auto-test/) | 代码变更后自动检测语言并运行测试（pytest/npm test） | ⭐⭐ | ✅ |
| [lint-check](./lint-check/) | 代码变更后自动运行 lint（ruff/eslint） | ⭐⭐ | ✅ |
| [codegraph-sync](./codegraph-sync/) | 代码变更后自动同步 CodeGraph | ⭐⭐ | ✅ |
| [complete-workflow](./complete-workflow/) | 组合所有 hooks → lint → test → sync → audit 完整流程 | ⭐⭐⭐ | ✅ |
| [legal-risk-scan](./legal-risk-scan/) | LEGAL 规则包 14 条 AI 法律风险扫描 | ⭐⭐ | ✅（legal-scan） |
| [superpowers-bridge](./superpowers-bridge/) | superpowers skills → SkillRegistry 自动桥接 | ⭐⭐ | ✅ |
| **平台适配器** | | | |
| [openai-adapter](./openai-adapter/) | Profile 配置 → OpenAI function calling 格式翻译 | ⭐⭐ | ❌ |
| [hermes-adapter](./hermes-adapter/) | Profile 配置 → Hermes YAML 格式翻译 | ⭐⭐ | ❌ |
| [hermes-bridge](./hermes-bridge/) | Hermes Agent 通过 MCP Server 接入 Harness 管控 | ⭐⭐ | ❌ |
| [copilot-cli-bridge](./copilot-cli-bridge/) | Profile 配置 → Copilot CLI 适配器部署 | ⭐⭐ | ❌ |
| [cursor-bridge](./cursor-bridge/) | Profile 配置 → Cursor 适配器部署 | ⭐⭐ | ❌ |
| [multi-adapter](./multi-adapter/) | 同一 Profile → 多 adapter 映射对比 + 自定义 adapter 接入 | ⭐⭐ | ❌ |
| **核心引擎能力** | | | |
| [guardrails](./guardrails/) | 护栏层 PII 检测/红脱/阻断 + 中国特定 PII | ⭐⭐ | ✅ |
| [audit](./audit/) | SHA-256 哈希链验证 + 审计记录搜索 | ⭐⭐ | ✅ |
| [downgrade-rollback](./downgrade-rollback/) | 门禁超时自动降级 + 执行失败自动回滚 | ⭐⭐ | ✅ |
| [negotiation](./negotiation/) | 多 Agent 冲突检测 + 自动合并 + 辩论解决 | ⭐⭐⭐ | ✅ |
| [learning-scheduler](./learning-scheduler/) | 模式挖掘 + 智能调度（并行分组/关键路径） | ⭐⭐⭐ | ✅ |
| [pipeline](./pipeline/) | 六步流水线编排 + MCP 编码 Pipeline | ⭐⭐⭐ | ✅ |
| **代码分析引擎** | | | |
| [analysis](./analysis/) | 调用图 + 污点追踪 + God Class + 影响分析 | ⭐⭐ | ✅ |
| **外部引擎集成** | | | |
| [external-engines](./external-engines/) | SonarQube + ArchUnit + DepCruiser + OPA + 规则导入 | ⭐⭐⭐ | ✅ |
| **知识/规则/报告** | | | |
| [knowledge-rule-report](./knowledge-rule-report/) | 知识库 + 规则市场 + 合规报告 + 语言识别 + 验证器 | ⭐⭐ | ✅ |
| **审计后端** | | | |
| [audit-backends](./audit-backends/) | Langfuse + Arize + Datadog + MultiStore + OTel | ⭐⭐⭐ | ✅ |
| **实验性模块** | | | |
| [autonomous-loop](./autonomous-loop/) | 自主循环引擎 + 跨文件合规扫描 | ⭐⭐⭐ | ✅ |
| **工具与成本** | | | |
| [mcp-full](./mcp-full/) | 25 个 MCP 工具全量调用演示 | ⭐⭐ | ✅ |
| [llm-tiering](./llm-tiering/) | LLM 分层 + Token 跟踪 + 通知推送 + DI 容器 | ⭐⭐⭐ | ✅ |
| **外部框架集成** | | | |
| [deerflow-integration](./deerflow-integration/) | DeerFlow 多智能体框架治理集成 | ⭐⭐⭐ | ❌ |
| [langgraph-integration](./langgraph-integration/) | LangGraph 多步推理治理中间件集成 | ⭐⭐⭐ | ❌ |

---

## 入门与基础

### simple-agent — 最简入门

```bash
cd examples/simple-agent
pip install -r requirements.txt
python simple_agent.py
```

一个 Agent、一个约束、一个任务——5 分钟理解 harness-cook 核心概念。

### multi-agent — 多 Agent 协作

```bash
cd examples/multi-agent
pip install -r requirements.txt
python multi_agent.py
```

Coder 写代码 → Reviewer 检查 → Tester 测试，演示多 Agent DAG 编排和门禁约束。

### custom-rules — 自定义合规规则包

```bash
pip install harness-cook
mkdir -p .harness/rules
cp custom_pii.py .harness/rules/
```

创建团队专属合规规则，harness-cook 自动发现并加载。

### declarative-rules — YAML 声明式门禁

```bash
cd examples/declarative-rules
python demo_declarative_rules.py
```

通过 YAML 配置文件定义质量门禁，无需编写 Python 代码——适合非开发者快速配置。

---

## 自动化 Hook

### auto-test — 自动测试

```bash
cp examples/auto-test/hook-auto-test.py your-project/hooks/
```

代码变更后智能检测文件语言，自动运行 pytest/npm test/go test 等相应测试命令。

### lint-check — 自动 Lint

```bash
cp examples/lint-check/hook-lint-check.py your-project/hooks/
```

代码变更后自动运行 ruff/eslint/gofmt 等质量检查工具。

### codegraph-sync — CodeGraph 自动同步

```bash
cp examples/codegraph-sync/hook-codegraph-sync.py your-project/hooks/
```

代码变更后自动同步 CodeGraph，保持代码图谱实时更新——推荐所有使用 CodeGraph 的项目配置。

### complete-workflow — 完整工作流

```bash
python3 packages/cli/harness_cli.py activate \
  --profile-path examples/complete-workflow/profile.yaml
```

组合所有 hooks：lint → test → sync → audit，一步到位的自动化开发工作流。

### legal-risk-scan — 法律风险扫描

```bash
cd examples/legal-risk-scan
python demo_legal_scan.py
```

LEGAL 规则包 14 条规则，扫描 AI 生成内容的法律风险（版权/商标/隐私合规等）。

### superpowers-bridge — Superpowers 桥接

```bash
cd examples/superpowers-bridge
python demo_superpowers_bridge.py
```

将 Claude Code superpowers 插件的 skills 自动发现并注册到 harness-cook SkillRegistry。

---

## 平台适配器

将 harness-cook Profile 配置翻译/部署到不同 Agent 平台——**不装不影响，装了自动增强**。

### openai-adapter — OpenAI 适配器

```bash
cd examples/openai-adapter
python demo_openai_adapter.py
```

Profile 配置 → OpenAI function calling 格式翻译，让 OpenAI Agent 也受 harness-cook 管控。

### hermes-adapter — Hermes 适配器

```bash
cd examples/hermes-adapter
python demo_hermes_adapter.py
```

Profile 配置 → Hermes YAML 格式翻译，适配 Hermes Agent 平台。

### hermes-bridge — Hermes 桥接

```bash
cd examples/hermes-bridge
pip install -r requirements.txt
python hermes_bridge.py
```

Hermes Agent 通过 MCP Server 接入 Harness 管控——双向桥接。

### copilot-cli-bridge — Copilot CLI 桥接

```bash
cd examples/copilot-cli-bridge
python demo_copilot_cli_adapter.py
```

Profile 配置 → GitHub Copilot CLI 适配器部署，让 Copilot CLI 也受治理约束。

### cursor-bridge — Cursor 桥接

```bash
cd examples/cursor-bridge
python demo_cursor_adapter.py
```

Profile 配置 → Cursor IDE 适配器部署，让 Cursor 也受治理约束。

### multi-adapter — 多 Adapter 映射对比

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/multi-adapter/demo_multi_adapter.py
```

同一份 Profile 喂遍所有 adapter + 一个极简自定义 adapter，并排对比映射差异/产出差异/supports_hooks 分层降级/F 方案 gate hook 的 per-adapter 差异，并端到端 `bridge.deploy(adapter_name=...)` 产出不同平台配置——支撑"未来新 agent 接入只需实现 adapter + register"的架构主张。

---

## 核心引擎能力

### guardrails — 护栏层

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/guardrails/demo_guardrails.py
```

PII 检测/红脱/阻断——12 种 PII 类型（含中国特定：手机号/身份证/银行卡），REDACT 和 BLOCK 两种动作。

### audit — 审计追踪

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/audit/demo_audit.py
```

SHA-256 哈希链验证——3 条审计记录写入 + 搜索 + 完整性验证 + 统计，不可篡改的审计日志。

### downgrade-rollback — 降级 + 回滚

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/downgrade-rollback/demo_downgrade_rollback.py
```

降级引擎——门禁超时按风险级别自动降级（high→ABORT, medium→SIMPLIFY, low→SKIP）；回滚引擎——执行前创建 SHA-256 文件快照，失败后自动恢复。

### negotiation — 多 Agent 协商

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/negotiation/demo_negotiation.py
```

冲突检测 + 自动合并 + 辩论解决——两个 Agent 修改同一文件时的协商机制：非重叠自动合并、重叠辩论裁决、无法解决升级人工。

### learning-scheduler — 学习 + 调度

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/learning-scheduler/demo_learning_scheduler.py
```

经验存储记录执行轨迹 → PatternMiner 挖掘成功/失败模式 → SmartScheduler 并行分组 + Token 预估 + 关键路径 + 检查点。

### pipeline — Pipeline 编排

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/pipeline/demo_pipeline.py
```

六步流水线编排——Analyst→Coder→Validator→Committer，门禁强制执行 + reviewer 失败回 coder 重试条件分支。也可通过 MCP 工具 `harness_pipeline_run` 在 IDE 中直接调用。

---

## 代码分析引擎

### analysis — 调用图 + 污点追踪 + God Class + 影响分析

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/analysis/demo_analysis.py
```

四大代码分析引擎——CallGraphBuilder 方法级调用图、TaintTracker 数据流安全分析、GodClassMetrics ATFD/WMC/TCC 三维指标、ImpactAnalyzer 依赖图 + 影响传播路径。

文档介绍见 VitePress Demo 页面 [代码分析](../playground/docs/demo/analysis)——代码片段+预期输出+配置说明。

---

## 外部引擎集成

### external-engines — SonarQube + ArchUnit + DepCruiser + OPA + 规则导入

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/external-engines/demo_external_engines.py
```

四种外部合规引擎 + 规则导入器接入——SonarQube 代码质量、ArchUnit 架构约束、DepCruiser 依赖约束、OPA 策略引擎、规则导入器（从外部引擎导入合规规则包）。每个引擎都有降级回退机制——「不装不影响，装了自动增强」。

文档介绍见 VitePress Demo 页面 [外部引擎集成](../playground/docs/demo/external-engines)。

---

## 知识/规则/报告

### knowledge-rule-report — 知识库 + 规则市场 + 合规报告 + 语言识别 + 验证器

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/knowledge-rule-report/demo_knowledge_rule_report.py
```

五大知识治理模块——10 种知识类型的 LocalKnowledgeProvider、团队规则共享的 RuleMarket、HTML/JSON 合规报告生成、17 种语言的自动识别 LanguageRegistry、验证器类型系统 ValidatorRegistry。

文档介绍见 VitePress Demo 页面 [知识/规则/报告](../playground/docs/demo/knowledge-rule-report)。

---

## 审计后端

### audit-backends — Langfuse + Arize + Datadog + MultiStore + OTel

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/audit-backends/demo_audit_backends.py
```

五大审计存储后端——Langfuse LLM 可观测、Arize ML 可观测、Datadog 企业监控、MultiAuditStore 双写故障降级、Traceloop/OTel 标准导出。SDK 未安装自动降级到本地 JSON 存储。

文档介绍见 VitePress Demo 页面 [审计后端](../playground/docs/demo/audit-backends)。

---

## 实验性模块

### autonomous-loop — 自主循环引擎 + 跨文件合规扫描

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/autonomous-loop/demo_autonomous_loop.py
```

⚠️ **@experimental** 模块，API 可能变更。

自主循环引擎——Agent 自主迭代直到收敛（max_iterations / convergence / gate_pass）；跨文件合规扫描——CrossFileScanEngine 影响传播链追踪 + CrossFileRiskGrade 5级风险评定。

文档介绍见 VitePress Demo 页面 [自主循环](../playground/docs/demo/autonomous-loop)。

---

## 工具与成本

### mcp-full — 25 个 MCP 工具全量调用

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/mcp-full/demo_mcp_full.py
```

25 个 MCP 工具完整调用演示——合规检查（harness_check / harness_guardrails_check / harness_rule_import）、审计追踪（harness_audit / harness_trace_export / harness_status）、工作流编排（harness_plan / harness_run / harness_pipeline_run / harness_pipeline_status）、门禁管理（harness_gate_create / harness_gate_approve / harness_hook_trigger）、注册配置（7个工具）、知识管理（harness_knowledge_query / harness_knowledge_search / harness_knowledge_stats / harness_knowledge_activate / harness_knowledge_deactivate）。

文档介绍见 VitePress Demo 页面 [MCP 全量](../playground/docs/demo/mcp-full)。

### llm-tiering — LLM 分层 + Token 跟踪 + 通知推送 + DI 容器

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/llm-tiering/demo_llm_tiering.py
```

四大成本与质量控制模块——ModelTier PREMIUM/STANDARD/FAST 三级分层 + LLMConstraints 约束、TokenTracker 使用记录 + 分级成本 + 预算控制、GateNotificationManager 多通道通知、DIContainer 服务注册 + 插拔替换。

文档介绍见 VitePress Demo 页面 [LLM 分层调用](../playground/docs/demo/llm-tiering)。

---

## 外部框架集成

### deerflow-integration — DeerFlow 集成

```bash
cd examples/deerflow-integration
python demo_deerflow_bridge.py
```

DeerFlow 多智能体框架接入 harness-cook 治理——DAG 执行 + 门禁审批 + 审计追踪。

### langgraph-integration — LangGraph 集成

```bash
cd examples/langgraph-integration
python demo_langgraph_governance.py
```

LangGraph 多步推理接入 harness-cook 治理中间件——节点级合规检查 + 门禁阻断。

---

## 快速上手推荐路径

| 你想做什么 | 推荐示例 |
|-----------|---------|
| 5 分钟了解 harness-cook | `simple-agent` |
| 让代码变更自动跑测试 | `auto-test` |
| 让代码变更自动跑 lint | `lint-check` |
| 保持 CodeGraph 实时同步 | `codegraph-sync` |
| 一步到位的完整自动化 | `complete-workflow` |
| 扫描 AI 生成内容的法律风险 | `legal-risk-scan` |
| 让 OpenAI Agent 受治理约束 | `openai-adapter` |
| 多 Agent 协作 + 门禁 | `multi-agent` |
| PII 检测和红脱 | `guardrails` |
| 审计追踪不可篡改 | `audit` |
| 门禁超时自动降级 | `downgrade-rollback` |
| 多 Agent 修改同一文件协商 | `negotiation` |
| 从执行历史学习优化调度 | `learning-scheduler` |
| 自动编码流水线 | `pipeline` |
| 安全污点追踪和调用图 | `analysis` |
| 接入 SonarQube/OPA 等外部引擎 | `external-engines` |
| 团队知识库和规则共享 | `knowledge-rule-report` |
| Langfuse/Arize 审计后端 | `audit-backends` |
| Agent 自主迭代循环 | `autonomous-loop` |
| 25 个 MCP 工具全量 | `mcp-full` |
| LLM 分层调用和成本控制 | `llm-tiering` |
| 对比多 adapter 映射差异 | `multi-adapter` |
| 演示新 agent 接入路径 | `multi-adapter` |

---

## 与 VitePress Demo 的关系

| 关系 | 说明 |
|------|------|
| 重叠主题（19 个） | auto-test / lint-check / codegraph-sync / complete-workflow / legal-risk-scan ↔ legal-scan / superpowers-bridge / guardrails / audit / downgrade-rollback / negotiation / learning-scheduler / pipeline / analysis / external-engines / knowledge-rule-report / audit-backends / autonomous-loop / mcp-full / llm-tiering |
| examples 独占（12 个） | 入门（simple-agent/multi-agent）+ 规则（custom-rules/declarative-rules）+ 适配器（openai/hermes/copilot-cli/cursor/multi-adapter）+ 集成（deerflow/langgraph） |
| Demo 独占（4 个） | 核心引擎层深层能力（compliance / dag-workflow / engine-integration / mcp-tools） |

想理解内部运作机制 → 看 [VitePress Demo](../playground/docs/demo/)
想直接跑脚本解决实际问题 → 看本目录

---

## 贡献指南

欢迎贡献新示例，请确保：

1. ✅ 包含可运行的 Python 脚本
2. ✅ 包含 README.md 说明定位和用法
3. ✅ 如有依赖则提供 requirements.txt
4. ✅ 遵循项目代码规范

## License

MIT

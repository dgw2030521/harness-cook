# Demo 演示

> **文档介绍**——代码片段 + 预期输出 + 配置示例，帮你理解每项能力的运作机制。

**定位**：`playground/docs/demo/` = **文档介绍**，项目根目录 `examples/` = **可运行的代码**。同一个主题，Demo 给你文档看原理，examples 给你脚本直接跑。想看讲解 → 来这里；想跑代码 → 去 examples。

**运行方式**：Demo 页面的代码片段可复制到终端直接执行：

```bash
cd harness-cook/packages/core
PYTHONPATH=. python3 your_demo_script.py
```

重叠主题的完整可运行脚本见项目 `examples/` 目录。

---

## 能力演示

| Demo | 说明 | 运行命令 |
|------|------|---------|
| [护栏](./guardrails) | PII 红脱/阻断、中国特定 PII、外部引擎适配器 | `python3 playground/demo_guardrails.py` |
| [合规](./compliance) | 安全扫描、自定义规则、MatcherRegistry 路由、引擎适配器 | `python3 playground/demo_compliance.py` |
| [审计](./audit) | SHA-256 链验证、MultiAuditStore 双写、外部后端、OTel 导出 | `python3 playground/demo_audit.py` |
| [门禁](./gate) | STRICT/HYBRID/LOOSE 三档模式、重试与自动修复、升级人工 | `python3 playground/demo_gate.py` |
| [引擎集成](./engine-integration) | MatcherRegistry 12 引擎、引擎可用性探测、DepCruiser 端到端、降级路径 | `python3 playground/demo_engine.py` |
| [降级 + 回滚](./downgrade-rollback) | 门禁超时自动降级（ABORT/SIMPLIFY/SKIP）+ 执行失败自动回滚（文件快照恢复） | `python3 examples/downgrade-rollback/demo_downgrade_rollback.py` |
| [协商](./negotiation) | 冲突检测、自动合并、辩论解决——多 Agent 同时修改同一文件 | `python3 examples/negotiation/demo_negotiation.py` |
| [学习 + 调度](./learning-scheduler) | 模式挖掘、反模式检测、智能调度（并行分组/关键路径/Token预估） | `python3 examples/learning-scheduler/demo_learning_scheduler.py` |
| [Pipeline 编排](./pipeline) | 六步流水线编排 + MCP 编码 Pipeline + 门禁强制执行 | `python3 examples/pipeline/demo_pipeline.py` |
| [法律风险](./legal-scan) | LEGAL 规则包 14 条规则、中文法规合规、门禁建议 | `python3 examples/legal-risk-scan/demo_legal_scan.py` |
| [Superpowers 桥接](./superpowers-bridge) | 自动发现 skill.md、语义映射、namespace 防碰撞、MCP 集成 | `python3 examples/superpowers-bridge/demo_superpowers_bridge.py` |
| [DAG 工作流](./dag-workflow) | 节点/边定义、拓扑排序执行、结果跟踪 | `python3 playground/demo_dag.py` |
| [代码分析](./analysis) | 调用图构建、污点追踪、God Class 检测、变更影响分析 | `python3 examples/analysis/demo_analysis.py` |
| [外部引擎集成](./external-engines) | SonarQube + ArchUnit + DepCruiser + OPA + 规则导入器（降级回退） | `python3 examples/external-engines/demo_external_engines.py` |
| [知识 / 规则 / 报告](./knowledge-rule-report) | 本地知识库 + 规则市场 + 合规报告 + 语言识别 + 验证器类型 | `python3 examples/knowledge-rule-report/demo_knowledge_rule_report.py` |
| [审计后端](./audit-backends) | Langfuse + Arize + Datadog + MultiStore 双写 + Traceloop/OTel 导出 | `python3 examples/audit-backends/demo_audit_backends.py` |
| [自主循环](./autonomous-loop) | AutonomousLoopEngine 自主迭代 + CrossFileScanEngine 跨文件合规扫描 | `python3 examples/autonomous-loop/demo_autonomous_loop.py` |
| [MCP 全量](./mcp-full) | 25 个 MCP 工具完整调用演示（合规/审计/工作流/门禁/配置） | `python3 examples/mcp-full/demo_mcp_full.py` |
| [LLM 分层调用](./llm-tiering) | ModelTier 三级分层 + TokenTracker 成本 + 通知推送 + DI 容器 | `python3 examples/llm-tiering/demo_llm_tiering.py` |

## 自动化工作流

| Demo | 说明 | 配置方式 |
|------|------|---------|
| [CodeGraph Sync](./codegraph-sync) | 代码变更后自动同步 CodeGraph | `post_tool_use` hook |
| [Auto Test](./auto-test) | 代码变更后自动运行测试 | `post_tool_use` hook |
| [Lint Check](./lint-check) | 代码变更后自动检查代码质量 | `post_tool_use` hook |
| [Complete Workflow](./complete-workflow) | lint → test → sync → audit 完整工作流 | 组合所有 hooks |

## 全面验证

| Demo | 说明 |
|------|------|
| [全面验证指南](./verification) | 所有能力的可运行验证脚本——引擎总线、四层治理、MCP、外部引擎 |

---

## 相关导航

- 📖 **指南**：系统架构和设计原理 → [指南首页](/guide/)
- 🎓 **教程**：步骤式使用方法 → [教程首页](/tutorial/)
- 🏃 **Demo**：可运行脚本和配置 → 本页

**三者分工**：指南讲「是什么」、教程讲「怎么用」、Demo 讲「跑起来看」。

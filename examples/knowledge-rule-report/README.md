# 知识管理 / 规则市场 / 合规报告 / 语言识别 / 验证器

> 本地知识 CRUD + 搜索、团队规则共享订阅、合规扫描 HTML/JSON 报告、多语言 import 识别、验证器类型系统

**文档介绍**见 VitePress Demo 页面 [知识规则报告](../../playground/docs/demo/knowledge-rule-report.md)——代码片段 + 预期输出 + 配置说明。本目录是可运行的脚本。

## 运行

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/knowledge-rule-report/demo_knowledge_rule_report.py
```

## 输出内容

| Demo | 说明 |
|------|------|
| 1. 本地知识提供者 | 10 种 KnowledgeType 的 CRUD + 关键词搜索 + TF-IDF 语义搜索 + 类型/标签过滤 + 统计 |
| 2. 规则市场 | 下载/安装/卸载规则包 + 搜索 + 上传自定义规则 + 规则源管理 + RulePackMetadata |
| 3. 合规报告生成 | ComplianceResult → HTML 报告 + 依赖图 HTML + DOT 格式 + DSM 方阵 + 审计仪表盘 + JSON 输出 |
| 4. 语言自动识别 | LanguageRegistry.default() 注册 17 种语言 + 文件扩展名推断 + tree-sitter 降级 + 自定义注册 |
| 5. 验证器注册表 | IssueSeverity/RequirementPriority 枚举 + CodeLocation + ValidationIssue + Requirement + ChangeDescription + ValidationContext + ValidatorRegistry 注册/执行/判定 |

## 涉及模块

| 模块 | 文件 | 核心类 |
|------|------|--------|
| 知识管理 | `packages/core/harness/knowledge.py` | KnowledgeType, KnowledgeScope, KnowledgeEntry, LocalKnowledgeProvider |
| 规则市场 | `packages/core/harness/rule_market.py` | RuleMarket, RulePackMetadata |
| 合规报告 | `packages/core/harness/report.py` | HTMLReportGenerator, DOTReportGenerator, DSMReport |
| 语言注册 | `packages/core/harness/language_registry.py` | LanguageRegistry |
| 验证器 | `packages/core/harness/validator_types.py` | ValidatorRegistry, ValidationIssue, ValidationContext, ValidationResult |
| 类型定义 | `packages/core/harness/types.py` | ComplianceResult |

## 适用场景

- AI Agent 知识管理——项目架构/约定/风险等 10 种知识的结构化存储和检索
- 团队规则共享——多团队间合规规则包的发现、下载、安装和上传
- 合规可视化——扫描结果生成自包含 HTML 报告，无需外部依赖即可浏览器查看
- 多语言架构检查——根据文件扩展名自动识别语言，tree-sitter 降级为正则 fallback
- 验证器统一调度——合规检查 + 破坏性变更检测 + 变更数量限制等多 Validator 协调执行

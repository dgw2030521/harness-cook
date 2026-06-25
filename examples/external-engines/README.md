# 外部合规引擎集成示例

> SonarQube/ArchUnit/DepCruiser/OPA 四种外部引擎集成 + 规则导入器

**文档介绍**见 VitePress Demo 页面 [外部引擎](../../playground/docs/demo/external-engines.md)——代码片段 + 预期输出 + 配置说明。本目录是可运行的脚本。

## 运行

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/external-engines/demo_external_engines.py
```

## 输出内容

| Demo | 说明 |
|------|------|
| 1. SonarQube 引擎集成 | 引用模式——从 CI 缓存检索 SonarQube 扫描结果，不可用时降级到 RegexChecker |
| 2. ArchUnit 架构规则检查 | Java 分层违规/循环依赖检查，不可用时降级到 DependencyGraphChecker |
| 3. DepCruiser 依赖约束检查 | JS/TS 依赖方向违规检查，不可用时降级到 DependencyGraphChecker |
| 4. OPA 策略引擎检查 | Rego 实时策略评估，支持 HTTP 和嵌入式两种模式，不可用时降级到 RegexChecker |
| 5. 规则导入器 | 从 SonarQube API / ArchUnit 配置 / DepCruiser 配置导入规则包，返回 RulePack |

## 核心架构

所有外部引擎集成继承 `ExternalEngineChecker` 基类，采用模板方法模式：

```
探测可用性 → 不可用则降级 → 翻译请求 → 调用引擎 → 翻译响应 → 错误回退
```

降级机制保证引擎不可用时自动回退到内置 checker，不阻塞主流程。

## 引擎对照

| 引擎 | 适用语言 | 降级目标 | 安装方式 |
|------|---------|---------|---------|
| SonarQube | 多语言 | RegexChecker | `pip install harness-cook[sonarqube]` |
| ArchUnit | Java | DependencyGraphChecker | `pip install harness-cook[archunit]` + JDK 8+ |
| DepCruiser | JS/TS | DependencyGraphChecker | `pip install harness-cook[dep_cruiser]` 或 `npm install dependency-cruiser` |
| OPA | 多语言 | RegexChecker | `pip install harness-cook[opa]` |

## 适用场景

- CI/CD 管线中复用 SonarQube 已有扫描结果（引用模式，不触发新扫描）
- Java 项目架构治理——分层违规、循环依赖、命名规范
- JS/TS 项目依赖方向约束——组件不直接导入 API 层
- 通用策略合规——通过 Rego 策略语言声明任意合规规则
- 跨引擎规则统一导入——将外部引擎规则翻译为 harness RulePack 格式

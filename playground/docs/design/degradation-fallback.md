# 降级机制与内置托底

> "不装不影响，装了自动增强"——外部引擎不可用时 harness-cook 如何保障治理能力

> 详见 [引擎集成总线](/guide/engine-bus)（ExternalEngineChecker 模板方法、12 引擎注册表、验证三层、SonarQube 引用模式详解）。本文聚焦**内置托底机制与各层降级路径**。

---

## 四层治理的内置托底机制

| 层 | 外部引擎 | 内置 fallback | fallback 覆盖什么 |
|----|---------|-------------|-----------------|
| **护栏层** | GuardrailsAI / NeMo / Llama Guard / Helicone | `RegexChecker` + 内置 `PIIDetector` | 12 种 PII 类型正则检测，完全本地运行 |
| **合规层** | SonarQube / OPA / ArchUnit / DepCruiser | `RegexChecker` + `ASTChecker` + `DependencyGraphChecker` | 内置 5 个 RulePack 共 50+ 条规则 |
| **审计层** | Langfuse / Arize / Datadog / Helicone | 本地 `AuditStore` | SHA-256 哈希链、搜索、完整性验证 |
| **门禁层** | — | 三档模式本身 | STRICT/HYBRID/LOOSE 不依赖任何外部服务 |

---

## 各层降级路径

所有外部引擎适配器继承 `ExternalEngineChecker` 基类，模板方法有 **4 个降级保障点**（探测→翻译→调用→响应翻译，每步出错都 fallback，不阻塞不中断）。模板方法与子类化详见 [引擎集成总线](/guide/engine-bus)。

### 护栏层降级路径

```
GuardrailsAI SDK 已安装 → GuardrailsAIChecker._call_engine() → 使用 SDK 验证器
    ↓ SDK 未安装
GuardrailsAI SDK 未安装 → fallback 到 RegexChecker
    ↓
RegexChecker → 12 种 PII 类型检测（email/phone_cn/id_card_cn/ssn/credit_card 等）
```

### 合规层降级路径

```
SonarQube 服务器可达 → HTTP API 引用 CI 扫描结果
    ↓ 服务器不可达
SonarQube 不可达 → fallback 到 RegexChecker → 内置规则包的正则模式匹配

DepCruiser 可用 → 子进程调用 dependency-cruiser
    ↓ npx/dependency-cruiser 不可用
DepCruiser 不可用 → fallback 到 DependencyGraphChecker → Python 内置依赖图分析
```

### 审计层降级路径

```
MultiAuditStore.save(entry):
  primary.save(entry)  → 本地 AuditStore → 必须成功（SHA-256 哈希链写入）
  secondary.save(entry) → LangfuseAuditStore → 火忘式写入
      ↓ Langfuse SDK 未安装 / 连接失败
  secondary 失败 → 仅 warning + AUDIT_SECONDARY_FAIL 事件，不影响主存
```

### 门禁层——无需外部引擎

| 模式 | 行为 | 需要外部引擎? |
|------|------|-------------|
| STRICT | 任何违规 → 阻断执行 | ❌ 不需要 |
| HYBRID | critical/high → 阻断，其余仅记录 | ❌ 不需要 |
| LOOSE | 所有违规仅记录，不阻断 | ❌ 不需要 |

---

## GuardrailsAI 验证器分类

| 类别 | 验证器 | 是否需要 LLM |
|------|--------|-------------|
| **本地验证器** | `PII` | ❌ 不需要 |
| | `Toxicity` | ❌ 不需要 |
| | `ValidJSON` | ❌ 不需要 |
| | `SqlInjection` | ❌ 不需要 |
| | `CodeSafety` | ❌ 不需要 |
| **推理验证器** | `Relevance` | ✅ 需要 |

对于核心功能（PII 检测、有害内容拦截），安装 SDK 即可直接使用，**无需配置 LLM API key**。

> SonarQube 引用模式、Langfuse 审计写入详解、引擎验证三层（单元测试 / SDK 本地验证 / 远程服务验证）见 [引擎集成总线](/guide/engine-bus)。

---

## 总结

**harness-cook 的降级设计确保：用户什么都不装、什么都不配置，系统仍然能完整运行。**

- 护栏用内置 PIIDetector（12 种 PII 正则检测）
- 合规用 RegexChecker + 内置规则包（50+ 条规则）
- 审计用本地 AuditStore（SHA-256 哈希链）
- 门禁用三档模式（纯策略逻辑）

外部引擎只是**可选增强**——安装后自动生效，未安装时自动降级，不影响核心治理能力。

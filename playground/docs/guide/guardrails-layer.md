# 护栏层

> Agent 安全的第一道防线——在输入进入 Agent 之前和输出离开 Agent 之后，拦截/红脱/警告敏感信息。

**快速导航**：[📖 原理（本页）](#原理) · [🎓 使用方法](/tutorial/guardrails-usage) · [🏃 可运行 Demo](/demo/guardrails)

---

## 原理

### 双层检查架构

harness-cook 护栏采用**输入-输出双栏组合**（GuardrailsPair）设计：

- **输入护栏**（InputGuardrails）：在用户 prompt 进入 Agent 之前检查
  - PII 泄露检测（防止敏感信息进入 Agent 上下文）
  - 输入长度限制（防止超长输入消耗资源）
- **输出护栏**（OutputGuardrails）：在 Agent 产出返回用户之前检查
  - PII 泄露检测（防止 Agent 输出泄露训练数据中的敏感信息）
  - 输出长度限制
  - 代码片段安全检查

### PII 检测机制

PIIDetector 使用正则模式匹配检测 **12 种 PII 类型**：

| 类型 | 正则模式 | 说明 |
|------|---------|------|
| `email` | `[a-zA-Z0-9._%+-]+@...` | 邮箱地址 |
| `phone_us` | `\d{3}[-.]?\d{3}[-.]?\d{4}` | 美国电话 |
| `phone_intl` | `\+\d{1,3}[-.\s]?\d{4,14}` | 国际电话 |
| `ssn` | `\d{3}-\d{2}-\d{4}` | 美国 SSN |
| `credit_card` | `\d{4}[-\s]?\d{4}...` | 信用卡号 |
| `ip_address` | `\d{1,3}\.\d{1,3}...` | IP 地址 |
| `api_key_generic` | `api_key\s*[:=]\s*["']...` | API 密钥 |
| `password` | `password\s*[:=]\s*["']...` | 密码 |
| `token` | `token\s*[:=]\s*["']...` | 认证令牌 |
| `id_card_cn` | `\d{17}[\dXx]` | 中国身份证号（18位） |
| `phone_cn` | `1[3-9]\d{9}` | 中国手机号（11位） |
| `bank_card_cn` | `\d{16,19}` | 中国银行卡号 |

### 四种动作策略

| 动作 | GuardrailAction | 行为 |
|------|----------------|------|
| 阻断 | `BLOCK` | 完全拒绝，标记 blocked=True，内容不传递 |
| 红脱 | `REDACT` | 替换敏感信息为 `[REDACTED_{type}]`，内容继续传递 |
| 警告 | `WARN` | 仅记录 violations，内容原样传递 |
| 替换 | `REPLACE` | 替换为自定义内容（暂未使用） |

### 外部引擎吸收

护栏层支持 4 个外部引擎适配器，通过 ExternalEngineChecker 模板方法模式接入：

| 适配器 | 外部引擎 | fallback | 特殊能力 |
|--------|---------|----------|---------|
| GuardrailsAIChecker | Guardrails AI SDK | RegexChecker | 15 validator 映射 |
| NeMoGuardrailsChecker | NVIDIA NeMo Guardrails | RegexChecker | 多轮对话护栏、话题控制 |
| LlamaGuardChecker | Llama Guard (Meta) | RegexChecker | LLM 自评式安全分类 |
| HeliconeMiddlewareChecker | Helicone | RegexChecker | 代理层护栏（API 调用级拦截） |

每个适配器遵循相同的降级路径：`探测引擎可用性 → 不可用则 fallback → 翻译请求 → 调用引擎 → 翻译响应`。

#### GuardrailsAI 验证器分类

GuardrailsAI SDK 的验证器分为两类——安装 SDK 即可使用的本地验证器，和需要 LLM API key 的推理验证器：

| 类别 | 验证器 | 是否需要 LLM | 说明 |
|------|--------|-------------|------|
| **本地验证器** | `PII` | ❌ 不需要 | 正则 + 模式匹配检测个人隐私信息 |
| | `Toxicity` | ❌ 不需要 | 有害/冒犯性内容检测 |
| | `ValidJSON` | ❌ 不需要 | JSON 格式验证 |
| | `ValidPython` | ❌ 不需要 | Python 语法验证 |
| | `SqlInjection` | ❌ 不需要 | SQL 注入模式检测 |
| | `CodeSafety` | ❌ 不需要 | 代码安全风险检测 |
| **推理验证器** | `Relevance` | ✅ 需要 | 相关性/幻觉检测，需要 LLM 推理能力 |

对于护栏层的核心功能（PII 检测、有害内容拦截），安装 `guardrails-ai` SDK 即可直接使用，无需配置 LLM API key。只有 Relevance/幻觉检测这类需要 LLM 推理的验证器才需要额外配置。

---

## 配置

### InputGuardrailConfig

```python
from harness.types import InputGuardrailConfig, GuardrailAction

config = InputGuardrailConfig(
    # 检测哪些 PII 类型（默认全部 12 种）
    detect_pii_types=["email", "phone_cn", "id_card_cn", "ssn", "credit_card", "api_key_generic"],
    # PII 检测后的动作：BLOCK / REDACT / WARN
    pii_action=GuardrailAction.REDACT,
    # 最大输入长度（超过则 BLOCK）
    max_input_length=10000,
)
```

### OutputGuardrailConfig

```python
from harness.types import OutputGuardrailConfig, GuardrailAction

config = OutputGuardrailConfig(
    # 是否检测输出中的 PII
    detect_pii_in_output=True,
    # 输出 PII 的动作：REDACT / BLOCK / WARN
    output_pii_action=GuardrailAction.REDACT,
    # 最大输出长度
    max_output_length=5000,
    # 是否检查输出中的代码片段安全性
    check_code_safety=False,
)
```

### GuardrailsPair 组合

```python
from harness.guardrails import GuardrailsPair

pair = GuardrailsPair(
    input_config=input_config,
    output_config=output_config,
    # 可选：EventBus 用于事件通知
    bus=event_bus,
)
```

### Profile YAML 配置

```yaml
guardrails:
  engine: builtin              # builtin / guardrails-ai / nemo / llama-guard / helicone
  input:
    pii_types: [email, phone_cn, id_card_cn, ssn, credit_card]
    pii_action: redact
    max_length: 10000
  output:
    detect_pii: true
    pii_action: redact
    max_length: 5000
```

---

更多配置细节见 [护栏使用教程](/tutorial/guardrails-usage)，可运行 Demo 见 [护栏 Demo](/demo/guardrails)。

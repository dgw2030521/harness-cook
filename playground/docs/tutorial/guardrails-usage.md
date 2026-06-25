# 护栏使用教程

> 逐步掌握 harness-cook 护栏层——从 PII 检测到外部引擎接入。

**快速导航**：[📖 原理](/guide/guardrails-layer) · [🎓 教程（本页）](#教程步骤) · [🏃 Demo](/demo/guardrails)

---

## 前置

```bash
cd harness-cook/packages/core
export PYTHONPATH=.
```

---

## 步骤 1：创建护栏配置

```python
from harness.types import InputGuardrailConfig, OutputGuardrailConfig, GuardrailAction

# 输入护栏——拦截进入模型前的敏感信息
input_config = InputGuardrailConfig(
    detect_pii_types=["email", "phone_cn", "id_card_cn", "ssn"],
    pii_action=GuardrailAction.REDACT,  # 红脱敏感信息
    max_input_length=10000,
)

# 输出护栏——拦截模型输出中的敏感信息
output_config = OutputGuardrailConfig(
    detect_pii_in_output=True,
    output_pii_action=GuardrailAction.REDACT,
    max_output_length=5000,
)
```

**PII 类型选择**：内置支持 12 种 PII 类型，中国常用的是 `phone_cn`、`id_card_cn`、`bank_card_cn`。

---

## 步骤 2：组合护栏对

```python
from harness.guardrails import GuardrailsPair

pair = GuardrailsPair(
    input_config=input_config,
    output_config=output_config,
)
```

GuardrailsPair 是输入-输出护栏的组合——一个对象同时处理进出两端。

---

## 步骤 3：检查输入

```python
# 安全输入——无 PII
result = pair.check_input("写一个求和函数")
print(f"安全输入: violations={result.violations}, blocked={result.blocked}")

# 含 PII 的输入——自动红脱
result = pair.check_input("用户张三的手机号13812345678，身份证410105199001011234")
print(f"PII 输入: violations={result.violations}")
print(f"红脱后: {result.processed_content}")
# → "用户张三的手机号[REDACTED_phone_cn]，身份证[REDACTED_id_card_cn]"
```

---

## 步骤 4：检查输出

```python
# 含 PII 的输出
result = pair.check_output("生成的邮箱是 test@example.com")
print(f"输出红脱: {result.processed_content}")
# → "生成的邮箱是 [REDACTED_email]"
```

---

## 步骤 5：切换动作策略

四种动作策略适用于不同场景：

```python
from harness.types import InputGuardrailConfig, GuardrailAction

# BLOCK：完全拒绝，适合安全关键路径
config_block = InputGuardrailConfig(
    detect_pii_types=["ssn", "credit_card"],
    pii_action=GuardrailAction.BLOCK,
)

# WARN：仅记录，适合开发阶段
config_warn = InputGuardrailConfig(
    detect_pii_types=["email"],
    pii_action=GuardrailAction.WARN,
)

# REDACT：替换敏感信息，适合生产环境（推荐）
config_redact = InputGuardrailConfig(
    detect_pii_types=["email", "phone_cn"],
    pii_action=GuardrailAction.REDACT,
)
```

---

## 步骤 6：使用 EventBus 通知

```python
from harness.bus import EventBus

bus = EventBus()
pair = GuardrailsPair(
    input_config=input_config,
    output_config=output_config,
    bus=bus,
)

# 监听护栏事件
bus.subscribe(lambda e: print(f"事件: {e.type}"))

result = pair.check_input("email: test@test.com")
# Bus 会发出 GUARDRAIL_VIOLATION 事件
```

---

## 步骤 7：Profile YAML 配置

Profile YAML 段定义见 [护栏层原理](/guide/guardrails-layer#profile-yaml-配置)（`guardrails.engine` / `input.pii_types` / `input.pii_action` / `output.*` 等）。上面步骤 1-6 的 Python 配置即对应 YAML 中 `engine: builtin` 的字段。

---

## 步骤 8：GuardrailsAI 外部引擎（可选）

### 安装

```bash
pip install guardrails-ai
# 或通过 harness-cook extras
pip install harness-cook[guardrails]
```

安装后 SDK 即可使用——**不需要 LLM API key**。GuardrailsAI SDK 本身就有内置的本地验证器（regex-based），可以直接在本地运行。

### 验证器分类

验证器分类（本地 vs 推理、是否需要 LLM）见 [护栏层原理](/guide/guardrails-layer#guardrailsai-验证器分类)。核心结论：PII/Toxicity/ValidJSON 等是本地验证器，安装 SDK 即可使用，无需 LLM API key；仅 Relevance 需要推理后端。

### 通过 harness-cook 调用本地验证器

```python
from harness.integrations.guardrails_ai_checker import GuardrailsAIChecker
from harness.types import ComplianceRule, ComplianceCategory, Artifact, ScanContext

# 安装 SDK 后，引擎自动可用
checker = GuardrailsAIChecker()
print(f"引擎可用: {checker._is_engine_available()}")  # True（SDK 已安装）

# 定义规则——使用 PII 验证器（本地，不需要 LLM）
rule = ComplianceRule(
    id="GR-PII-001",
    category=ComplianceCategory.PRIVACY,
    pattern="no_pii",           # 自动映射到 GuardrailsAI PII validator
    severity="critical",
    description="检测个人隐私信息",
    matcher_type="guardrails_ai",
)

artifact = Artifact(
    type="code",
    path="user_input.txt",
    content="用户张三邮箱test@example.com，手机13912345678",
)

result = checker.check(rule, artifact, ScanContext(project_root="."))
print(f"通过: {result.passed}")
print(f"发现: {result.findings}")
```

### validator 名称确定优先级

harness-cook 规则到 GuardrailsAI validator 的映射有三级优先级：

1. **`matcher_config.validator`** — 直接指定 validator 名称（最高优先级）
   ```python
   rule = ComplianceRule(
       id="GR-001", pattern="custom",
       matcher_type="guardrails_ai",
       matcher_config={"validator": "PII"},  # ← 直接指定
   )
   ```

2. **`pattern` 关键词自动映射** — 通过 VALIDATOR_MAP 自动匹配
   ```python
   # pattern="no_pii" → 自动映射为 "PII"
   # pattern="no_toxicity" → 自动映射为 "Toxicity"
   # pattern="valid_json" → 自动映射为 "ValidJSON"
   ```

3. **`pattern` 原值透传** — 无法映射时，pattern 原值作为 validator 名称传给 SDK

完整映射表：

| pattern 关键词 | → GuardrailsAI validator |
|---------------|--------------------------|
| `no_pii` / `pii` | `PII` |
| `no_toxicity` / `toxicity` | `Toxicity` |
| `no_hallucination` / `hallucination` / `relevance` | `Relevance` |
| `valid_json` / `json_validation` | `ValidJSON` |
| `valid_python` / `python_validation` | `ValidPython` |
| `no_sql_injection` / `sql_injection` | `SqlInjection` |
| `no_code_safety` / `code_safety` | `CodeSafety` |

### 推理验证器使用（Relevance/幻觉检测）

如果需要使用 `Relevance` 等需要 LLM 推理的验证器，需要配置 LLM API：

```python
# GuardrailsAI 会自动读取环境变量中的 LLM API key
# OPENAI_API_KEY=sk-xxx  → 使用 OpenAI
# 或在 GuardrailsAI 配置中指定 LLM 后端

rule = ComplianceRule(
    id="GR-RELEVANCE-001",
    category=ComplianceCategory.SECURITY,
    pattern="no_hallucination",   # 自动映射为 Relevance validator
    severity="high",
    description="幻觉检测",
    matcher_type="guardrails_ai",
)
```

### Profile YAML 配置

```yaml
guardrails:
  engine: guardrails-ai         # 切换引擎 → builtin / guardrails-ai / nemo / llama-guard / helicone
  input:
    pii_types: [email, phone_cn, id_card_cn]
    pii_action: redact
    max_length: 10000
  output:
    detect_pii: true
    pii_action: redact
    max_length: 5000
```

引擎未安装时自动回退到内置 RegexChecker，不影响正常使用。

### 降级行为

| 场景 | 行为 |
|------|------|
| SDK 未安装 | 自动 fallback 到 RegexChecker |
| SDK import 失败 | fallback 到 RegexChecker |
| 验证器调用失败 | fallback 到 RegexChecker |
| 本地验证器（PII 等） | 安装 SDK 即可，无需 LLM API key |
| 推理验证器（Relevance） | 需要 LLM API key，缺少时该验证器降级 |

---

## 相关导航

- 📖 [护栏层原理](/guide/guardrails-layer)
- 🏃 [护栏 Demo](/demo/guardrails) —— 可运行脚本 + 预期输出

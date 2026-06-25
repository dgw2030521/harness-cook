# 护栏 Demo

> 跑起来看看护栏层的 PII 检测、红脱/阻断、外部引擎适配器。

## 前置

```bash
cd harness-cook/packages/core
PYTHONPATH=. python3 -c "from harness.guardrails import GuardrailsPair; print('✅ OK')"
```

---

## Demo 1：PII 检测与红脱

```python
from harness.guardrails import GuardrailsPair
from harness.types import InputGuardrailConfig, OutputGuardrailConfig, GuardrailAction

pair = GuardrailsPair(
    input_config=InputGuardrailConfig(
        detect_pii_types=["email", "phone_cn", "id_card_cn"],
        pii_action=GuardrailAction.REDACT,
    ),
    output_config=OutputGuardrailConfig(
        detect_pii_in_output=True,
        output_pii_action=GuardrailAction.REDACT,
    ),
)

# 测试输入护栏——PII 红脱
result = pair.check_input("用户张三的手机号13812345678，身份证410105199001011234")
print(f"违规: {result.violations}")           # 应列出检测到的 PII 类型
print(f"红脱: {result.redactions}")           # 应包含具体替换记录
print(f"阻断: {result.blocked}")              # REDACT 动作不阻断 → False
print(f"处理后: {result.processed_content}")   # PII 应被替换为 [REDACTED_phone_cn] 等
```

### 预期输出

| 观察项 | 期望值 |
|--------|--------|
| `result.violations` | 非空列表，包含检测到的 PII 类型描述 |
| `result.redactions` | 非空列表，每项 `{type, original, redacted}` |
| `result.blocked` | `False`（REDACT 动作不阻断） |
| `result.processed_content` | PII 已替换为 `[REDACTED_{type}]` |

---

## Demo 2：PII 阻断模式

```python
from harness.types import InputGuardrailConfig, GuardrailAction

pair = GuardrailsPair(
    input_config=InputGuardrailConfig(
        detect_pii_types=["ssn"],
        pii_action=GuardrailAction.BLOCK,  # BLOCK 动作
    ),
    output_config=OutputGuardrailConfig(detect_pii_in_output=False),
)

result = pair.check_input("SSN: 123-45-6789")
print(f"阻断: {result.blocked}")   # True
print(f"动作: {result.action}")    # GuardrailAction.BLOCK
```

### 预期输出

| 观察项 | 期望值 |
|--------|--------|
| `result.blocked` | `True` |
| `result.action` | `GuardrailAction.BLOCK` |
| `result.violations` | 包含 `"PII detected in input: 1 instances (types: ['ssn'])"` |

---

## Demo 3：中国特定 PII

```python
from harness.types import InputGuardrailConfig, GuardrailAction

pair = GuardrailsPair(
    input_config=InputGuardrailConfig(
        detect_pii_types=["phone_cn", "id_card_cn", "bank_card_cn"],
        pii_action=GuardrailAction.REDACT,
    ),
    output_config=OutputGuardrailConfig(detect_pii_in_output=False),
)

# 中国手机号
result1 = pair.check_input("联系电话：13912345678")
print(f"中国手机号红脱: {'[REDACTED_phone_cn]' in result1.processed_content}")

# 中国身份证号
result2 = pair.check_input("身份证号410105199001011234")
print(f"中国身份证红脱: {'[REDACTED_id_card_cn]' in result2.processed_content}")
```

### 预期输出

| 观察项 | 期望值 |
|--------|--------|
| 中国手机号 | `[REDACTED_phone_cn]` 出现在处理后内容 |
| 中国身份证号 | `[REDACTED_id_card_cn]` 出现在处理后内容 |

---

## Demo 4：无 PII 内容

```python
result = pair.check_input("这是一段正常的文本")
print(f"违规: {result.violations}")      # []
print(f"红脱: {result.redactions}")      # []
print(f"阻断: {result.blocked}")          # False
```

### 预期输出

| 观察项 | 期望值 |
|--------|--------|
| `result.violations` | 空列表 `[]` |
| `result.redactions` | 空列表 `[]` |
| `result.blocked` | `False` |
| `result.processed_content` | 与 `result.original_content` 完全一致 |

---

## Demo 5：外部引擎适配器

```python
from harness.integrations.guardrails_ai_checker import GuardrailsAIChecker
from harness.integrations.nemo_guardrails_checker import NeMoGuardrailsChecker
from harness.integrations.llama_guard_checker import LlamaGuardChecker
from harness.integrations.helicone_checker import HeliconeMiddlewareChecker

for cls in [GuardrailsAIChecker, NeMoGuardrailsChecker, LlamaGuardChecker, HeliconeMiddlewareChecker]:
    checker = cls()
    print(f"{cls.__name__}: engine={checker._engine_name}, 可用={checker._is_engine_available()}, fallback={checker._fallback_checker.__class__.__name__}")
```

### 预期输出

| 适配器 | engine 可用 | fallback |
|--------|------------|----------|
| GuardrailsAIChecker | `False`（SDK 未安装） | `RegexChecker` |
| NeMoGuardrailsChecker | `False` | `RegexChecker` |
| LlamaGuardChecker | `False` | `RegexChecker` |
| HeliconeMiddlewareChecker | `False` | `RegexChecker` |

引擎未安装时自动 fallback 到内置 RegexChecker，不阻塞、不报错。

---

## Demo 7：GuardrailsAI SDK 安装后本地验证器调用

**前置**：需要先安装 GuardrailsAI SDK：

```bash
pip install guardrails-ai
```

安装后即可使用本地验证器——**不需要 LLM API key**。PII、Toxicity、ValidJSON 等验证器是 regex-based，直接在本地运行。

```python
from harness.integrations.guardrails_ai_checker import GuardrailsAIChecker
from harness.types import ComplianceRule, ComplianceCategory, Artifact, ScanContext

checker = GuardrailsAIChecker()
print(f"GuardrailsAI 可用: {checker._is_engine_available()}")  # True（SDK 已安装）

# PII 验证器——本地运行，不需要 LLM
rule_pii = ComplianceRule(
    id="GR-PII-001",
    category=ComplianceCategory.PRIVACY,
    pattern="no_pii",
    severity="critical",
    description="检测个人隐私信息",
    matcher_type="guardrails_ai",
)

artifact_pii = Artifact(
    type="code",
    path="input.txt",
    content="用户邮箱 test@example.com，手机 13912345678",
)

result = checker.check(rule_pii, artifact_pii, ScanContext(project_root="."))
print(f"PII 检测: passed={result.passed}, findings={result.findings}")

# ValidJSON 验证器——本地运行
rule_json = ComplianceRule(
    id="GR-JSON-001",
    category=ComplianceCategory.STYLE,
    pattern="valid_json",
    severity="medium",
    description="JSON 格式验证",
    matcher_type="guardrails_ai",
)

artifact_json = Artifact(
    type="code",
    path="data.json",
    content='{"key": "value", "broken": }',  # 不合法 JSON
)

result2 = checker.check(rule_json, artifact_json, ScanContext(project_root="."))
print(f"JSON 验证: passed={result2.passed}, findings={result2.findings}")
```

### 预期输出

| 验证器 | 需要 LLM? | 预期结果 |
|--------|-----------|---------|
| PII | ❌ 不需要 | `passed=False`，findings 包含 PII 类型信息 |
| ValidJSON | ❌ 不需要 | `passed=False`，findings 包含 JSON 解析错误 |
| Toxicity | ❌ 不需要 | 安装后可直接调用（无需 LLM） |
| SqlInjection | ❌ 不需要 | 安装后可直接调用（无需 LLM） |
| Relevance | ✅ 需要 LLM API key | 幻觉检测需要 LLM 推理后端 |

### 验证器分类说明

GuardrailsAI SDK 验证器分本地验证器（基于正则/模式匹配，无需 LLM）和推理验证器（需要 LLM）两类，完整分类表见 [护栏层原理](/guide/guardrails-layer#guardrailsai-验证器分类)。护栏层核心功能（PII 检测、有害内容拦截）全部是本地验证器，所以安装 SDK 就能覆盖核心场景。

---

## Demo 6：MCP 工具调用

```python
from harness_mcp_server import HarnessMCPServer

server = HarnessMCPServer()
tool = next(t for t in server._TOOL_DEFINITIONS if t['name'] == 'harness_guardrails_check')
print(f"工具参数: {list(tool['inputSchema']['properties'].keys())}")
# 应包含: content, direction, engine
```

---

## Profile YAML 配置示例

Profile YAML 段定义见 [护栏层原理](/guide/guardrails-layer#profile-yaml-配置)（`guardrails.engine` / `input.pii_types` / `input.pii_action` / `output.*` 等），Demo 中的可运行脚本即对应该配置的 REDACT / BLOCK 动作与 PII 类型检测。

---

## 相关导航

- 📖 架构原理 → [护栏层](/guide/guardrails-layer)
- 🎓 使用方法 → [护栏使用](/tutorial/guardrails-usage)

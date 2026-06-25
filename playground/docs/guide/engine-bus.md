# 引擎集成总线

> harness-cook 的核心定位——像 Kubernetes 一样做治理集成，将每层治理委托给最强的专业引擎，只保留组合价值。

**快速导航**：[📖 原理（本页）](#原理) · [🏃 可运行 Demo](/demo/engine-integration)

---

## 原理

### 吸收式治理 vs 自建式治理

传统方案是**自建式**——自己实现每层治理能力（PII检测、合规扫描、审计追踪），永远追不上专业引擎的精度。

harness-cook 采用**吸收式**——做集成总线，将每层治理委托给最强引擎：

| 层 | 自建式 | 吸收式（harness-cook） |
|----|--------|----------------------|
| 护栏 | 自己写正则检测 PII | 吸收 Guardrails AI / NeMo / Llama Guard |
| 合规 | 自己写规则引擎 | 吸收 SonarQube / OPA / ArchUnit / dep-cruiser |
| 审计 | 自己写 SQLite 存储 | 吸收 Langfuse / Arize / Datadog / Helicone |

harness-cook 只保留**组合价值**：
- MCP 注入 → 25 个工具覆盖所有能力
- Bridge 部署 → 5 个适配器翻译到各平台原生格式
- 三档门禁 → STRICT/HYBRID/LOOSE 分级管控
- Profile 配置 → 一份 YAML 统管所有层

### ExternalEngineChecker 模板方法

所有引擎适配器继承 `ExternalEngineChecker` 基类，遵循**模板方法模式**：

```python
class ExternalEngineChecker(IRuleChecker):
    """引擎适配器基类——模板方法：探测→降级→翻译→调用→翻译响应"""

    def check(self, rule, artifact, context) -> ComplianceResult:
        # 1. 探测可用性（缓存式惰性探测）
        if not self._is_engine_available():
            → fallback 到内置 checker

        # 2. 翻译请求（将 ComplianceRule → 引擎原生格式）
        request = self._translate_request(rule, artifact, context)
        → 翻译失败则 fallback

        # 3. 调用引擎（通过 SDK / HTTP API / 子进程）
        response = self._call_engine(request)
        → 调用失败则 fallback

        # 4. 翻译响应（将引擎原生响应 → ComplianceResult）
        result = self._translate_response(response, rule)
        → 翻译失败则 fallback
        → 标记结果来源引擎（result.locations[i]["engine"])
```

**四个降级保障点**：每个步骤出错都自动 fallback，不阻塞，不中断。

### MatcherRegistry 注册中心

MatcherRegistry 是所有引擎适配器的注册中心枢纽：

```python
MatcherRegistry.default()  # 注册所有引擎（try/except ImportError）
```

注册机制：
- **try/except ImportError**：不装 → 不注册 → 不影响默认安装
- **模块级不 import 外部 SDK**：所有外部 SDK import 在方法级别，避免破坏默认安装
- **default() 返回 None**：修改类级 `_matchers` dict，不返回实例

引擎注册结果（按 matcher_type 列举，含内置与外部）：

| matcher_type | Checker 类 | fallback | 外部依赖 |
|-------------|-----------|----------|---------|
| `regex` | RegexChecker | — | 无 |
| `ast` | ASTChecker | — | 无 |
| `cross_file` | CrossFileChecker | — | 无 |
| `dependency_graph` | DependencyGraphChecker | — | 无 |
| `guardrails_ai` | GuardrailsAIChecker | RegexChecker | `guardrails-ai>=0.4` |
| `helicone` | HeliconeMiddlewareChecker | RegexChecker | `helicone` |
| `llama-guard` | LlamaGuardChecker | RegexChecker | `llama-guard` |
| `nemo` | NeMoGuardrailsChecker | RegexChecker | `nemoguardrails` |
| `opa` | OPAChecker | RegexChecker | `opa-python>=1.0` |
| `sonarqube` | SonarQubeChecker | RegexChecker | `python-sonarqube-api>=1.0` |
| `archunit` | ArchUnitChecker | DependencyGraphChecker | JVM + ArchUnit jar |
| `dep_cruiser` | DepCruiserChecker | DependencyGraphChecker | `dependency-cruiser` |

### IAuditStore Protocol 抽象

`@runtime_checkable` Protocol 将审计后端抽象为 5 个方法：

```python
class IAuditStore(Protocol):
    def save(self, entry: AuditEntry) -> str: ...
    def load(self, session_id: str, date_str: Optional[str] = None) -> List[AuditEntry]: ...
    def search(self, query, date_from, date_to, agent_id, limit) -> List[AuditEntry]: ...
    def verify_chain(self) -> Dict: ...
    def integrity_report(self) -> Dict: ...
```

所有后端（AuditStore / Langfuse / Arize / Datadog / Helicone / MultiAuditStore）都实现此 Protocol。

### 语言感知路由

MatcherRegistry 支持 `get_by_language(language)` 方法——根据文件语言推荐最优引擎：

```
Java → ArchUnitChecker       (架构合规最强)
JS/TS → DepCruiserChecker    (依赖合规最强)
通用 → 使用规则指定的 matcher_type
```

语言路由是**建议性的**——用户可通过 `matcher_type` 显式覆盖。

### 降级路径设计原则

1. **不装 → 不注册 → 不影响**：MatcherRegistry.default() 用 try/except ImportError
2. **不可用 → fallback → 不中断**：ExternalEngineChecker.check() 四个 fallback 保障点
3. **出错 → catch → 不阻塞**：引擎调用异常不阻塞主流程
4. **可选依赖独立**：每个 SDK 独立可选组，`pip install harness-cook` 不装任何外部引擎
5. **方法级 import**：外部 SDK import 在方法体内，模块级 import 会破坏默认安装
6. **Bus 事件可观测**：新增 AUDIT_SECONDARY_FAIL 事件，次存储失败可追踪但不阻塞

---

## 配置

### MatcherRegistry 初始化

```python
from harness.rule_checker import MatcherRegistry

# 注册所有引擎（默认安装只注册内置引擎）
MatcherRegistry.default()

# 查询引擎
mr = MatcherRegistry()
checker = mr.get("regex")           # 直接查询
checker = mr.get_by_language("java") # 语言路由查询

# 查看所有已注册引擎
for k, v in sorted(MatcherRegistry._matchers.items()):
    print(f"  {k}: {v.__class__.__name__}")
```

### ExternalEngineChecker 子类化

```python
from harness.integrations.base import ExternalEngineChecker
from harness.rule_checker import RegexChecker

class MyCustomChecker(ExternalEngineChecker):
    """自定义引擎适配器示例"""

    def __init__(self, config=None):
        super().__init__(
            engine_name="my-engine",
            fallback_checker=RegexChecker(),
            config=config,
        )

    def _probe_engine(self) -> bool:
        """探测引擎可用性——子类实现"""
        try:
            import my_engine_sdk
            return True
        except ImportError:
            return False

    def _translate_request(self, rule, artifact, context) -> dict:
        """翻译 ComplianceRule → 引擎原生请求"""
        return {
            "pattern": rule.pattern,
            "content": artifact.content,
            "path": artifact.path,
        }

    def _call_engine(self, request: dict) -> dict:
        """调用引擎——子类实现"""
        import my_engine_sdk
        return my_engine_sdk.check(request)

    def _translate_response(self, response: dict, rule) -> ComplianceResult:
        """翻译引擎原生响应 → ComplianceResult"""
        from harness.types import ComplianceResult
        return ComplianceResult(
            rule_id=rule.id,
            passed=not response.get("violations"),
            findings=response.get("violations", []),
            severity=response.get("severity", "info"),
        )
```

### 注册自定义引擎

```python
# 注册到 MatcherRegistry
MatcherRegistry.register("my_engine", MyCustomChecker())

# 使用：规则 matcher_type 指定自定义引擎
rule = ComplianceRule(
    id="CUSTOM-001",
    matcher_type="my_engine",  # 路由到 MyCustomChecker
    ...
)
```

### MultiAuditStore 配置

```python
from harness.audit import AuditStore
from harness.integrations.multi_store import MultiAuditStore
from harness.bus import EventBus

bus = EventBus()

# 默认：仅本地存储
local = AuditStore()
multi = MultiAuditStore([local], bus=bus)

# 双写：本地 + Langfuse
from harness.integrations.langfuse_store import LangfuseAuditStore
langfuse = LangfuseAuditStore(public_key="pk-xxx", secret_key="sk-xxx")
multi = MultiAuditStore([local, langfuse], bus=bus)
# → save() 双写；search()/verify_chain() 只从 local

# 三写：本地 + Langfuse + Datadog
from harness.integrations.datadog_store import DatadogAuditStore
datadog = DatadogAuditStore(api_key="xxx", site="datadoghq.com")
multi = MultiAuditStore([local, langfuse, datadog], bus=bus)
```

### Profile YAML 配置

```yaml
# 每层指定引擎
guardrails_engine:
  engine: builtin                # builtin / guardrails-ai / nemo / llama-guard / helicone
  config: {}

compliance_engine:
  engines: [builtin]             # builtin / sonarqube / opa / archunit / dep_cruiser
  language_routing:
    java: archunit
    javascript: dep_cruiser
  config: {}

audit_engine:
  backends: [local]              # local / langfuse / arize / datadog / helicone
  trace_format: builtin          # builtin / otel-json / traceloop
  collector_url: ""              # OTel Collector URL
  config: {}
```

---

## 引擎验证层级

外部引擎的验证分为三个层级——每层有不同的前提条件和可信度：

### 层级 1：单元测试（所有引擎，无额外前提）

所有引擎适配器都能验证**导入、初始化、fallback 机制**：

- `GuardrailsAIChecker()` 可创建 → `_is_engine_available()` 返回 False → fallback 到 RegexChecker
- `SonarQubeChecker()` 可创建 → `_probe_engine()` 检测无 SonarQube URL → fallback 到 RegexChecker
- `LangfuseAuditStore()` 可创建 → `_is_available()` 检测无 langfuse SDK → lazy 初始化不报错

单元测试覆盖：`tests/test_guardrails_ai_checker.py`、`tests/test_sonarqube_checker.py`、`tests/test_langfuse_store.py`。

### 层级 2：SDK 安装后本地验证（仅适用于本地验证器引擎）

安装 SDK 即可在本地实际调用引擎——**不需要远程服务**：

| 引擎 | 安装命令 | 本地可验证什么 |
|------|---------|--------------|
| **GuardrailsAI** | `pip install guardrails-ai` | PII/Toxicity/ValidJSON/SqlInjection 等 6 种本地验证器（regex-based，**不需要 LLM API key**） |
| **DepCruiser** | `npx dependency-cruiser` | 依赖图扫描（本地子进程调用） |

GuardrailsAI 的本地验证器（PII 等）安装 SDK 后直接可用，无需配置任何 LLM 后端。只有 Relevance/幻觉检测这类需要 LLM 推理的验证器才需要 API key。

### 层级 3：远程服务验证（需要团队基础设施）

需要独立运行的服务/平台——个人开发环境通常不具备，属于**团队级基础设施**：

| 引擎 | 性质 | 需要什么 | 验证方式 |
|------|------|---------|---------|
| **SonarQube** | 代码质量服务器 | SonarQube 服务器 + API token | `_call_engine()` 通过 HTTP API 从 CI 扫描结果读取已有 issue（**引用模式**，不触发新扫描） |
| **Langfuse** | LLM 可观测性平台 | Langfuse 账号 + public/secret key | `save()` 将 AuditEntry 写入 Langfuse trace/spans |
| **Arize** | ML 可观测性平台 | Arize API key + space ID | `save()` 写入 Phoenix trace |
| **Datadog** | 基础设施监控平台 | Datadog API key + site | `save()` 写入 Datadog trace |
| **OPA** | 策略引擎服务器 | OPA 服务实例 | `_call_engine()` 通过 HTTP API 执行 Rego 策略评估 |
| **ArchUnit** | Java 架构约束验证 | JVM + ArchUnit jar | `_call_engine()` 通过子进程执行 Java 测试类 |
| **NeMo Guardrails** | 多轮对话护栏 | NeMo SDK + LLM 后端 | `_call_engine()` 执行 Colang 流 |
| **Llama Guard** | LLM 安全分类 | Llama Guard 模型 + LLM 后端 | `_call_engine()` 调用模型做安全分类 |

层级 3 的验证应在**CI 环境**中进行——团队部署了 SonarQube/Langfuse 等服务后，集成测试可验证真实调用。

### SonarQube 引用模式详解

SonarQubeChecker 采用**引用模式**（reference mode）——不触发新的代码扫描，而是从最近一次 CI 扫描读取缓存结果：

```
工作流程：
1. _probe_engine: HTTP GET /api/system/status → 检查 SonarQube 连接
2. _translate_request: rule → SonarQube API 查询参数 (projectKey + rule_key)
3. _call_engine: HTTP GET /api/issues/search?projectKey=...&rules=...
4. _translate_response: SonarQube issue → ComplianceResult
```

这意味着：
- harness-cook **不替代 SonarQube 的扫描能力**——只读取 SonarQube 已有的扫描结果
- 团队 CI 流水线应先运行 SonarQube 扫描，harness-cook 合规层再引用其结果
- 没有 SonarQube 服务 → 自动 fallback 到 RegexChecker（正则模式检查）

### Langfuse 审计写入详解

LangfuseAuditStore 将每个 AuditEntry 映射为 Langfuse 的 trace + spans：

- 每个 AuditEntry → 一个 Langfuse trace（session_id 作为 trace ID）
- 每个 decision/action/outcome → trace 内的一个 span
- chain_hash → trace 的 tags（关联哈希链）
- risk_assessment → trace 的 metadata

**限制**：Langfuse SDK 没有搜索/加载 API，所以：
- `search()` → 返回空列表 + warning
- `load()` → 返回空列表
- `verify_chain()` → 返回 `{valid: True}`（Langfuse 不维护哈希链）

读取审计数据应使用**主存储**（本地 AuditStore），Langfuse 是纯写次存储。

---

更多配置细节见 [合规扫描教程](/tutorial/compliance-scan)，可运行 Demo 见 [引擎集成 Demo](/demo/engine-integration)。

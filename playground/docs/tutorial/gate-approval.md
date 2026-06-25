# 门禁审批

本教程展示如何创建质量门禁、配置门禁模式、定义检查函数和重试策略。

## Step 1: 理解门禁模式

三档门禁模式定义见 [门禁层原理](/guide/gate-layer#三档门禁模式)。实操中推荐默认使用 HYBRID：

```python
from harness.types import GateMode

mode = GateMode.HYBRID   # 推荐默认模式
```

## Step 2: 定义检查函数

结构定义见 [门禁层原理](/guide/gate-layer)。实操：GateCheck 需要一个 `check_fn`——接收 Artifact，返回 CheckResult：

```python
from harness.types import Artifact, CheckResult

def check_no_hardcoded_keys(artifact: Artifact) -> CheckResult:
    """检查产出物中是否包含硬编码密钥"""
    import re
    pattern = re.compile(r'(api_key|secret|token|password)\s*=\s*["\'][^"\']+["\']')
    matches = pattern.findall(artifact.content or "")

    if matches:
        return CheckResult(
            passed=False,
            severity="critical",
            message=f"发现硬编码密钥: {matches}",
            details={"matches": matches},
        )
    return CheckResult(
        passed=True,
        severity="critical",
        message="无硬编码密钥",
    )
```

## Step 3: 创建 GateDefinition

将检查函数组装为 GateDefinition，挂载到特定节点：

```python
from harness.types import GateDefinition, GateCheck

gate = GateDefinition(
    node_id="code",           # 挂载到 code 节点
    mode=GateMode.HYBRID,
    checks=[
        GateCheck(
            id="sec-001",
            category="security",
            severity="critical",
            description="硬编码密钥检测",
            check_fn=check_no_hardcoded_keys,
        ),
    ],
)
```

## Step 4: 注册到 GateEngine

```python
from harness.gates import GateEngine
from harness.bus import EventBus

bus = EventBus()
gate_engine = GateEngine(bus=bus)
gate_engine.register(gate)

# 将 GateEngine 传入 DAGEngine，避免双实例
engine = DAGEngine(registry=registry, gate_engine=gate_engine, bus=bus)
```

::: warning
DAGEngine 和 GateEngine 必须共享同一个 GateEngine 实例。创建顺序：先创建 GateEngine → 传给 DAGEngine 构造函数。不要让 DAGEngine 自己创建独立的 GateEngine。
:::

## Step 5: 自动修复

GateCheck 的 `auto_fix_fn` 可以在检查失败时自动修复：

```python
def auto_fix_keys(artifact: Artifact, result: CheckResult) -> Artifact:
    """自动替换硬编码密钥为占位符"""
    import re
    fixed_content = re.sub(
        r'(api_key|secret|token|password)\s*=\s*["\'][^"\']+["\']',
        r'\1 = os.environ.get("\1")',
        artifact.content or "",
    )
    return Artifact(
        type=artifact.type,
        path=artifact.path,
        content=fixed_content,
    )

gate_check_with_fix = GateCheck(
    id="sec-001-fix",
    category="security",
    severity="critical",
    description="硬编码密钥检测（支持自动修复）",
    check_fn=check_no_hardcoded_keys,
    auto_fix_fn=auto_fix_keys,       # ← 自动修复函数
)
```

`auto_fixable` 标记为 True 的规则，在 HYBRID 模式下会先尝试自动修复再判断是否阻断。

## Step 6: 重试策略

RetryStrategy 字段定义见 [门禁层原理](/guide/gate-layer#重试策略)。配置执行失败时的退避重试和升级逻辑：

```python
from harness.types import RetryStrategy

retry = RetryStrategy(
    max_retries=3,
    backoff_seconds=2.0,     # 退避间隔（2 → 4 → 8 秒）
    escalate_on_fail=True,   # 重试耗尽后升级人工
)
```

当 Agent 执行失败且门禁检查未通过时，Engine 按退避策略重试。重试全部失败后，`escalate_on_fail=True` 将 `context.escalated` 设为 True，通知人工介入。

## Step 7: 完整门禁工作流示例

```python
from harness.types import *
from harness.gates import GateEngine
from harness.engine import DAGEngine

# 1. 创建 GateEngine
gate_engine = GateEngine(bus=bus)

# 2. 注册门禁
gate_engine.register(GateDefinition(
    node_id="code",
    mode=GateMode.HYBRID,
    checks=[GateCheck(id="sec-001", ...)],
))

# 3. 创建 DAGEngine（共享 GateEngine）
engine = DAGEngine(registry=registry, gate_engine=gate_engine, bus=bus)

# 4. 执行
context = engine.execute(workflow)

# 5. 检查结果
print(f"升级人工: {context.escalated}")
print(f"失败节点: {list(context.failed_nodes)}")
```

下一步 → [DAG 工作流](./dag-workflow)
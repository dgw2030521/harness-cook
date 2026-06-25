# 门禁 Demo

> 跑起来看看门禁层的三档模式（STRICT/HYBRID/LOOSE）、重试与自动修复、升级人工审核。

## 前置

```bash
cd harness-cook/packages/core
PYTHONPATH=. python3 -c "from harness.gates import GateEngine; print('✅ OK')"
```

---

## Demo 1：STRICT 模式全阻断

```python
from harness.gates import GateEngine
from harness.types import GateDefinition, GateMode, GateCheck, CheckResult, Artifact
from harness.bus import EventBus

bus = EventBus()
engine = GateEngine(bus=bus)

def fail_check(artifact):
    return CheckResult(passed=False, severity="medium", message="测试违规")

gate = GateDefinition(
    id="strict-test",
    mode=GateMode.STRICT,
    checks=[GateCheck(id="test", category="security", severity="medium",
                      description="测试检查", check_fn=fail_check)],
)
engine.register(gate)

artifact = Artifact(type="code", path="test.py", content="test")
result = engine.evaluate("strict-test", artifact)

print(f"STRICT 模式:")
print(f"  passed: {result.passed}")      # False
print(f"  blocked: {result.blocked}")    # True（STRICT 任何失败都阻断）
print(f"  failed_checks: {result.failed_checks}")  # ≥ 1
```

### 预期输出

| 输入 | passed | blocked | 说明 |
|------|--------|---------|------|
| 全部检查通过 | `True` | `False` | 正常放行 |
| 1 项 low 严重性失败 | `False` | `True` | 任何失败都阻断 |
| 1 项 critical 严重性失败 | `False` | `True` | 任何失败都阻断 |

---

## Demo 2：HYBRID 模式分级处理

```python
from harness.types import GateMode

# 低严重性 → 仅记录，不阻断
def low_severity_fail(artifact):
    return CheckResult(passed=False, severity="low", message="低严重性违规")

gate_hybrid_low = GateDefinition(
    id="hybrid-low-test",
    mode=GateMode.HYBRID,
    checks=[GateCheck(id="low-001", category="style", severity="low",
                      description="低严重性检查", check_fn=low_severity_fail)],
)
engine.register(gate_hybrid_low)
result = engine.evaluate("hybrid-low-test", artifact)
print(f"HYBRID 低严重性: passed={result.passed}, blocked={result.blocked}")
# passed=False, blocked=False（低严重性不阻断）

# 高严重性 → 阻断
def high_severity_fail(artifact):
    return CheckResult(passed=False, severity="high", message="高严重性违规")

gate_hybrid_high = GateDefinition(
    id="hybrid-high-test",
    mode=GateMode.HYBRID,
    checks=[GateCheck(id="high-001", category="security", severity="high",
                      description="高严重性检查", check_fn=high_severity_fail)],
)
engine.register(gate_hybrid_high)
result = engine.evaluate("hybrid-high-test", artifact)
print(f"HYBRID 高严重性: passed={result.passed}, blocked={result.blocked}")
# passed=False, blocked=True（高严重性阻断）
```

### 预期输出

| 输入 | passed | blocked | 说明 |
|------|--------|---------|------|
| 仅 low 严重性失败 | `False` | `False` | 低严重性仅记录，尝试 auto_fix |
| 仅 medium 严重性失败 | `False` | `False` | 中严重性仅记录 |
| 有 high/critical 严重性失败 | `False` | `True` | 高严重性阻断执行 |

---

## Demo 3：LOOSE 模式仅记录

```python
def critical_fail(artifact):
    return CheckResult(passed=False, severity="critical", message="严重违规")

gate_loose = GateDefinition(
    id="loose-test",
    mode=GateMode.LOOSE,
    checks=[GateCheck(id="crit-001", category="security", severity="critical",
                      description="严重检查", check_fn=critical_fail)],
)
engine.register(gate_loose)
result = engine.evaluate("loose-test", artifact)
print(f"LOOSE 模式: passed={result.passed}, blocked={result.blocked}")
# passed=False, blocked=False（LOOSE 不阻断任何检查）
```

### 预期输出

| 输入 | passed | blocked | 说明 |
|------|--------|---------|------|
| 全部检查通过 | `True` | `False` | 正常放行 |
| 1 项 critical 严重性失败 | `False` | `False` | 不阻断，仅记录 |
| 全部检查失败 | `False` | `False` | 不阻断，仅记录所有失败 |

---

## Demo 4：重试与自动修复

```python
from harness.types import FixAction

auto_fixable_count = 0

def auto_fix_check(artifact):
    if auto_fixable_count < 1:
        auto_fixable_count += 1
        return CheckResult(
            passed=False, severity="low", message="可自动修复",
            auto_fix=FixAction(description="移除调试语句", confidence=0.9),
        )
    return CheckResult(passed=True, severity="info", message="修复后通过")

gate_retry = GateDefinition(
    id="retry-test",
    mode=GateMode.HYBRID,
    checks=[GateCheck(id="fix-001", category="style", severity="low",
                      description="自动修复检查", check_fn=auto_fix_check)],
    max_retries=2,
)
engine.register(gate_retry)
result = engine.evaluate("retry-test", artifact)
print(f"重试后: passed={result.passed}, retries_used={result.retries_used}, auto_fixed={result.auto_fixed}")
```

### 预期输出

| 场景 | retries_used | 说明 |
|------|-------------|------|
| 首次全部通过 | `0` | 无需重试 |
| auto_fix 成功后通过 | `1` | 修复 + 1 次重试 |

---

## Demo 5：升级人工

HYBRID 模式下 critical 失败且无 auto_fix → 升级人工审核：

| 场景 | escalated | escalation_reason |
|------|-----------|------------------|
| HYBRID + critical 失败 + 无 auto_fix | `True` | "Critical severity check failed, requires human review" |
| HYBRID + high 失败 + 重试耗尽 | `True` | "High severity check failed after retries" |

---

## Demo 6：MCP 工具创建门禁

```python
from harness_mcp_server import HarnessMCPServer

server = HarnessMCPServer()
tool = next(t for t in server._TOOL_DEFINITIONS if t['name'] == 'harness_gate_create')
print(f"参数: {list(tool['inputSchema']['properties'].keys())}")
# gate_type, checks, auto_fix
```

---

## Profile YAML 配置示例

Profile YAML 段定义见 [门禁层原理](/guide/gate-layer#profile-yaml-配置)（`gates.default_mode` / `max_retries` / `nodes` 等），Demo 中的可运行脚本即对应该配置的 `strict` / `hybrid` / `loose` 三档与重试/自动修复行为。

---

## 相关导航

- 📖 架构原理 → [门禁层](/guide/gate-layer)
- 🎓 使用方法 → [门禁审批](/tutorial/gate-approval)

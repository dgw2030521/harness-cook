# 多 Agent 协商 Demo

> 冲突检测、自动合并、辩论解决——多 Agent 同时修改同一文件时的协商机制

完整可运行脚本见项目 `examples/negotiation/` 目录（`demo_negotiation.py`）。

---

## Demo 1：冲突检测

```python
from harness.negotiation import ConflictDetector
from harness.types import Artifact

detector = ConflictDetector()

# Agent A 和 B 都修改了 config.py
artifacts_a = [
    Artifact(type="code", path="config.py", content="API_KEY = 'new-key-a'\nPORT = 8080"),
]
artifacts_b = [
    Artifact(type="code", path="config.py", content="API_KEY = 'new-key-b'\nPORT = 8080"),
]

conflicts = detector.detect({
    "coder-a": artifacts_a,
    "coder-b": artifacts_b,
})

for c in conflicts:
    print(f"冲突文件: {c.file_path}")
    print(f"Agent A: {c.agent_a}, Agent B: {c.agent_b}")
```

### 预期输出

| 观察项 | 期望值 |
|--------|--------|
| `len(conflicts)` | ≥ 1（同一文件被两个 Agent 修改） |
| `c.file_path` | `"config.py"` |
| `c.agent_a` / `c.agent_b` | `"coder-a"` / `"coder-b"` |

---

## Demo 2：自动合并（非重叠区域）

```python
from harness.negotiation import NegotiationEngine

engine = NegotiationEngine()

# 不同文件修改——无冲突
artifacts_a = [
    Artifact(type="code", path="app.py", content="# header by A\nimport os"),
]
artifacts_b = [
    Artifact(type="code", path="utils.py", content="# header by B\ndef helper(): pass"),
]

conflicts = engine.conflict_detector.detect({
    "coder-a": artifacts_a,
    "coder-b": artifacts_b,
})

print(f"冲突数: {len(conflicts)}")  # 0 → 可自动合并
```

### 预期输出

| 观察项 | 期望值 |
|--------|--------|
| `len(conflicts)` | 0（不同文件，无冲突） |
| 协商结果 | `auto_merge`——零人工干预 |

---

## Demo 3：辩论解决（重叠区域）

```python
from harness.negotiation import NegotiationEngine

engine = NegotiationEngine()

# Agent A 和 B 修改同一文件的同一位置
artifacts_a = [
    Artifact(type="code", path="config.py", content="timeout = 30  # Agent A: 30秒足够"),
]
artifacts_b = [
    Artifact(type="code", path="config.py", content="timeout = 120  # Agent B: 需要更长超时"),
]

conflicts = engine.conflict_detector.detect({
    "coder-a": artifacts_a,
    "coder-b": artifacts_b,
})

# 协商流程: detect → debate → resolve → merge/escalate
result = engine.negotiate(conflicts)
```

### 协商三种解决方式

| 方式 | 适用场景 | 说明 |
|------|---------|------|
| auto_merge | 非重叠修改 | 自动合并，零人工干预 |
| debate | 重叠修改 | Agent 各出理由，评判者裁决 |
| escalate | 无法自动解决 | 升级人类审批（最终保障） |

---

## Demo 4：完整协商流程

```
1. ConflictDetector.detect()     → 发现文件冲突
2. NegotiationEngine._try_auto_merge() → 非重叠区域自动合并
3. NegotiationEngine._debate()   → 重叠区域辩论解决
4. 升级人工                       → 无法自动解决时通知人类审批
```

---

## Profile YAML 配置示例

```yaml
negotiation:
  enabled: true
  auto_merge_threshold: 0.8      # 置信度 > 80% 时自动合并
  debate_rounds: 3               # 辩论轮数
  escalate_on_timeout: true       # 辩论超时升级人类
```

---

## 相关导航

- 📖 架构原理 → [协商引擎](/guide/negotiation-engine)
- 🎓 使用方法 → [多 Agent 协商](/tutorial/negotiation-usage)

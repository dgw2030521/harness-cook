# 多 Agent 协商示例

> 冲突检测、自动合并、辩论解决——多 Agent 同时修改同一文件时的协商机制

## 运行

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/negotiation/demo_negotiation.py
```

## 输出内容

| Demo | 说明 |
|------|------|
| 1. 冲突检测 | 两个 Agent 修改同一文件 → ConflictDetector 自动发现冲突 |
| 2. 自动合并 | 不同文件/非重叠区域 → 自动合并，零人工干预 |
| 3. 辏论解决 | 重叠区域 → Agent A/B 各出理由，评判者裁决 |
| 4. 协商流程 | detect → auto_merge → debate → escalate 完整流程概览 |

## 核心逻辑

```python
from harness.negotiation import ConflictDetector, NegotiationEngine

# 冲突检测
detector = ConflictDetector()
conflicts = detector.detect(agent_artifacts)

# 协商引擎——三种解决方式
engine = NegotiationEngine()
result = engine.negotiate(conflicts)
# auto_merge: 非重叠 → 自动合并
# debate: 重叠 → 辩论解决
# escalate: 无法解决 → 升级人类
```

## 适用场景

- 多 Agent 同时修改同一文件——自动检测冲突并协商解决
- Coder 和 Reviewer 修改同一代码段——辩论解决谁改的更好
- 前后端 Agent 同时修改配置文件——非重叠区域自动合并

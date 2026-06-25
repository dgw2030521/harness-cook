# AI 法律风险扫描

本教程展示如何使用 **Legal 规则包** 扫描 AI 生成内容中的法律风险，覆盖 14 条规则和中国法规合规。

## Step 1: 创建合规引擎并加载 Legal 规则包

```python
from harness.compliance import ComplianceEngine
from harness.rule_packs import get_legal_pack
from harness.bus import EventBus

bus = EventBus()
engine = ComplianceEngine(bus=bus)

# 加载 legal 规则包（14 条规则）
engine.load_pack(get_legal_pack())

print(engine.stats())
# → {'total_rules': 14, 'loaded_packs': 2, ...}
```

## Step 2: 了解 Legal 规则覆盖范围

Legal 规则包覆盖 5 个法律维度：

| 维度 | 规则 | 法律依据 |
|------|------|----------|
| AI 免责声明 | LEGAL-001/002 | AI 生成内容声明义务 |
| 版权归属 | LEGAL-003/005 | 版权法 |
| 许可证传染 | LEGAL-004 | GPL/AGPL 许可证条款 |
| 硬性保证 | LEGAL-006/007 | 消费者权益保护法/合同法 |
| 数据保护 | LEGAL-008/009/010 | 个人信息保护法/数据安全法 |
| 知识产权 | LEGAL-011/012 | 知识产权法 |
| 生成式AI标注 | LEGAL-013 | 生成式AI暂行办法 |
| Deepfake | LEGAL-014 | 刑法 |

## Step 3: 扫描 AI 免责声明违规

```python
from harness.types import Artifact

# 问题代码：AI 免责声明包含保证语言
artifact = Artifact(
    type="code",
    path="disclaimer.py",
    content="# This file was AI-generated. We guarantee correctness and certify completeness.",
)

results = engine.scan([artifact])
violations = [r for r in results if not r.passed]

for v in violations:
    print(f"{v.rule_id} ({v.severity}): {v.findings}")
    print(f"  → 修复: {v.remediation}")
```

预期输出：

```
LEGAL-002 (critical): AI disclaimer 包含保证性语言
  → 修复: 使用免责声明，明确声明 AI 生成且不保证正确性
LEGAL-006 (critical): 包含硬性保证声明
  → 修复: 移除保证性语言，改为"尽力而为"描述
```

**正确的免责声明**不会触发 LEGAL-002：

```python
# 正确写法：声明 AI 生成 + 不保证 + 需人工审核
clean = Artifact(
    type="code",
    path="proper_disclaimer.ts",
    content="// This file was AI-generated. No warranty of correctness. Human review required.",
)

results = engine.scan([clean])
violations = [r for r in results if not r.passed and r.rule_id == "LEGAL-002"]
# → 无违规！正确的免责声明不触发
```

## Step 4: 扫描中文法律风险

Legal 规则包支持中文内容检测：

```python
# 中文硬性保证声明
artifact = Artifact(
    type="code",
    path="cn_guarantee.py",
    content="# 本公司保证100%安全处理用户数据\ndef process(): pass",
)

results = engine.scan([artifact])
# → LEGAL-006 (critical): 包含硬性保证声明

# 个人数据交给 AI 处理
artifact = Artifact(
    type="code",
    path="pii_ai.py",
    content="# 个人信息由大模型进行分析处理\ndef analyze(data): pass",
)

results = engine.scan([artifact])
# → LEGAL-008 (high): 个人数据由 AI/LLM 处理

# 重要数据交给外部 AI
artifact = Artifact(
    type="code",
    path="critical_data.py",
    content="# 重要数据通过第三方AI API处理\ndef export(data): pass",
)

results = engine.scan([artifact])
# → LEGAL-010 (critical): 重要数据交给外部/AI
```

## Step 5: 快速扫描 API

`scan_quick()` 直接扫描字符串，适合 CI/CD 流水线集成：

```python
# 单行代码快速检查
results = engine.scan_quick("# 本公司保证100%安全处理", "inline.py")
violations = [r for r in results if not r.passed]
# → LEGAL-006 (critical)
```

## Step 6: 门禁集成

根据违规严重性推荐门禁模式：

```python
from harness.gates import Gate, GateCheck

# STRICT 门禁——阻断所有 critical 级法律风险
gate = Gate(
    gate_type="strict",
    checks=[
        GateCheck(
            id="legal-critical",
            category="legal",
            severity="critical",
            description="AI 法律风险 critical 级检查",
        ),
    ],
)

# HYBRID 门禁——阻断 critical + high，记录 medium/low
hybrid_gate = Gate(gate_type="hybrid", checks=[...])
```

| 场景 | 推荐门禁 | 阻断行为 |
|------|----------|----------|
| 有 LEGAL-002/006/009/010/014 | STRICT | 阻断执行 |
| 有 LEGAL-003/004/008 等 high | HYBRID | 阻断执行 |
| 仅 medium/low | LOOSE | 仅记录 |

## Step 7: 与其他规则包组合

Legal 规则包可与所有内置规则包共存：

```python
from harness.rule_packs import (
    get_coding_pack, get_security_pack, get_data_pack,
    get_devops_pack, get_legal_pack,
)

for factory in [get_coding_pack, get_security_pack, get_data_pack,
                get_devops_pack, get_legal_pack]:
    engine.load_pack(factory())

stats = engine.stats()
# → {'total_rules': 40, 'loaded_packs': 6, ...}
```

## Step 8: MCP 工具调用

通过 MCP Server 执行法律风险扫描：

```json
{
  "method": "harness_check",
  "params": {
    "path": "src/ai_module.py",
    "pack_names": ["legal"]
  }
}
```

## Step 9: Profile 配置集成

在 Profile 中启用 legal 规则包：

```yaml
# .harness/profiles/default.yaml
compliance:
  packs:
    - coding
    - security
    - legal          # ← 启用法律风险扫描

hooks:
  post_tool_use:
    - type: script
      command: "python3 packages/hooks/hook-compliance-scan.py"
```

## 运行完整示例

```bash
cd harness-cook/packages/core
PYTHONPATH=. python3 ../../examples/legal-risk-scan/demo_legal_scan.py
```

下一步 → [Superpowers Skill Bridge](./superpowers-skill-bridge)

# AI 法律风险扫描示例

> 使用 legal 规则包检测 AI 生成内容中的法律风险

**文档介绍**见 VitePress Demo 页面 [法律风险](../../playground/docs/demo/legal-scan.md)——代码片段 + 预期输出 + 配置说明。本目录是可运行的脚本。

## 功能

扫描代码中的 AI 法律风险，覆盖 14 条规则，包括：

| 维度 | 规则 | 法律依据 |
|------|------|----------|
| AI 免责声明 | LEGAL-001/002 | AI 生成内容声明义务 |
| 版权归属 | LEGAL-003/005 | 版权法 |
| 许可证传染 | LEGAL-004 | GPL/AGPL 许可证条款 |
| 硬性保证 | LEGAL-006 | 消费者权益保护法 |
| 个人信息保护 | LEGAL-008/009 | 个人信息保护法 |
| 数据安全 | LEGAL-010 | 数据安全法 |
| 生成式AI标注 | LEGAL-013 | 生成式AI暂行办法 |
| Deepfake | LEGAL-014 | 刑法 |

## 使用方法

### 1. 直接运行示例

```bash
cd harness-cook/packages/core
PYTHONPATH=. python3 ../../examples/legal-risk-scan/demo_legal_scan.py
```

### 2. 在代码中使用

```python
from harness.compliance import ComplianceEngine
from harness.rule_packs import get_legal_pack
from harness.types import Artifact
from harness.bus import EventBus

# 初始化引擎
engine = ComplianceEngine(bus=EventBus())
engine.load_pack(get_legal_pack())

# 构建产出物
artifact = Artifact(
    type="code",
    path="disclaimer.py",
    content="# This file was AI-generated. We guarantee correctness.",
)

# 执行扫描
results = engine.scan([artifact])

# 解读结果
for r in results:
    if not r.passed:
        print(f"违规: {r.rule_id} ({r.severity})")
        print(f"  发现: {r.findings}")
        print(f"  修复: {r.remediation}")
```

### 3. 快速扫描 API

```python
# 单行代码快速检查
results = engine.scan_quick(
    "# 本公司保证100%安全处理",
    "inline_check.py"
)
```

### 4. MCP 工具调用

```json
{
  "method": "harness_check",
  "params": {
    "path": "src/ai_module.py",
    "pack_names": ["legal"]
  }
}
```

### 5. Profile 配置集成

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

## 示例输出

### 有问题的代码

```
📄 disclaimer_with_warranty.py — AI 免责声明包含保证语言
   🔴 LEGAL-002 (critical)
      发现: AI disclaimer 包含保证性语言
      修复: 使用免责声明，明确声明 AI 生成且不保证正确性

   🔴 LEGAL-006 (critical)
      发现: 包含硬性保证声明
      修复: 移除保证性语言，改为"尽力而为"描述
```

### 干净的代码

```
📄 utils.py — 干净代码
   ✅ 未触发任何法律规则
```

## 门禁集成

根据违规严重性推荐门禁模式：

| 场景 | 推荐门禁 | 行为 |
|------|----------|------|
| 有 critical 级违规 | STRICT | 阻断执行 |
| 有 high 级违规 | HYBRID | 阻断执行 |
| 仅 medium/low | LOOSE | 仅记录 |

```python
from harness.gates import Gate, GateCheck

gate = Gate(
    gate_type="strict",
    checks=[
        GateCheck(id="legal-critical", category="legal", severity="critical",
                  description="AI 法律风险 critical 级检查"),
    ],
)
```

## 与其他规则包组合

legal 规则包可与所有内置规则包共存：

```python
from harness.rule_packs import (
    get_coding_pack, get_security_pack, get_data_pack,
    get_devops_pack, get_legal_pack,
)

for factory in [get_coding_pack, get_security_pack, get_data_pack,
                get_devops_pack, get_legal_pack]:
    engine.load_pack(factory())
```

## 自定义法律规则

参考 [examples/custom-rules/](../custom-rules/) 创建自定义规则包，类别设为 `ComplianceCategory.LEGAL`：

```python
from harness.types import ComplianceRule, ComplianceCategory
from harness.compliance import RulePack

custom_legal = ComplianceRule(
    id="LEGAL-CUSTOM-001",
    category=ComplianceCategory.LEGAL,
    pattern=r"特定正则模式",
    severity="high",
    description="自定义法律风险描述",
    remediation="修复建议",
)
```

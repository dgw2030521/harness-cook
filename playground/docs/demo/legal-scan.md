# 法律风险 Demo

> 跑起来看看 LEGAL 规则包的 14 条 AI 法律风险扫描。

**完整可运行脚本**见项目 `examples/legal-risk-scan/` 目录（`demo_legal_scan.py`）。本页是文档介绍——代码片段 + 预期输出 + 配置说明。

## 运行方式

```bash
cd harness-cook/packages/core
PYTHONPATH=. python3 ../../examples/legal-risk-scan/demo_legal_scan.py
```

---

## Demo 概述

LEGAL 规则包覆盖 14 条中国/国际 AI 法律合规规则：

| 规则 ID | 规则 | 严重性 | 适用场景 |
|---------|------|--------|---------|
| LEGAL-001 | AI 免责声明缺失 | medium | AI 生成的文件缺少免责声明 |
| LEGAL-002 | AI 免责声明含保证语言 | critical | AI 免责声明中有"保证""担保" |
| LEGAL-003 | 版权归属 AI 模型 | high | 声明版权归 AI 模型所有 |
| LEGAL-004 | GPL 许可证 import 链 | high | GPL/AGPL 许可传染 |
| LEGAL-005 | 未声明许可证 | medium | 无许可证声明 |
| LEGAL-006 | 硬性保证声明 | critical | 中文硬性保证语言 |
| LEGAL-007 | 隐性保证声明 | high | 隐含保证语义 |
| LEGAL-008 | 个人信息交给 AI | high | 个人信息由大模型处理 |
| LEGAL-009 | PII 未脱敏即交给 AI | critical | PII 数据未脱敏直接给 AI |
| LEGAL-010 | 重要数据交给外部 AI | critical | 重要数据通过第三方 AI API |
| LEGAL-011 | 安全评估报告缺失 | medium | 缺少安全评估 |
| LEGAL-012 | 数据出境违规 | high | 数据跨境传输 |
| LEGAL-013 | 生成式AI标注义务 | medium | AI 生成内容未标注 |
| LEGAL-014 | Deepfake 刑法风险 | critical | Deepfake 生成能力 |

---

## 示例代码片段

demo 脚本包含 7 个示例文件，每个触发不同的 LEGAL 规则：

| 示例 | 触发规则 | 说明 |
|------|---------|------|
| `disclaimer_with_warranty.py` | LEGAL-002 | AI 免责声明包含保证语言 |
| `copyright_ai.ts` | LEGAL-003 | 版权归属 AI 模型 |
| `gpl_import.py` | LEGAL-004 | GPL 许可证 import 链 |
| `cn_guarantee.py` | LEGAL-006 | 中文硬性保证声明 |
| `pii_ai.py` | LEGAL-008 | 个人数据交给 AI 处理 |
| `critical_data.py` | LEGAL-010 | 重要数据交给外部 AI |
| `deepfake.py` | LEGAL-014 | Deepfake 生成能力 |
| `utils.py` | 无违规 | 干净代码 |

---

## 快速扫描 API

```python
from harness.compliance import ComplianceEngine
from harness.rule_packs import get_legal_pack

engine = ComplianceEngine(bus=EventBus())
engine.load_pack(get_legal_pack())

# 单行代码快速扫描
code = "# 本公司保证100%安全处理"
results = engine.scan_quick(code, "inline_check.py")
violations = [r for r in results if not r.passed]
for v in violations:
    print(f"   {v.rule_id}: {v.findings}")
```

---

## 门禁建议

扫描结果自动生成门禁建议：

| 违规级别 | 建议门禁模式 | 行为 |
|---------|------------|------|
| 有 critical 级违规 | STRICT | critical 级违规阻断执行 |
| 有 high 级违规 | HYBRID | critical+high 级阻断，其余仅记录 |
| 仅有 medium/low 级 | LOOSE | 所有违规仅记录，不阻断 |

---

## 完整 Demo 代码

完整 Demo 代码见项目 `examples/legal-risk-scan/demo_legal_scan.py`。

---

## 相关导航

- 📖 架构原理 → [合规层](/guide/compliance-layer) · [规则包](/guide/rule-packs)
- 🎓 使用方法 → [法律风险扫描](/tutorial/legal-scan)

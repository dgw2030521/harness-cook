# 护栏示例

> PII 检测、红脱/阻断、中国特定 PII、输出护栏

**文档介绍**见 VitePress Demo 页面 [护栏](../../playground/docs/demo/guardrails.md)——代码片段 + 预期输出 + 配置说明。本目录是可运行的脚本。

## 运行

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/guardrails/demo_guardrails.py
```

## 输出内容

| Demo | 说明 |
|------|------|
| 1. PII 检测与红脱 | 手机号、身份证号 → `[REDACTED_phone_cn]` 替换 |
| 2. PII 阻断模式 | SSN 检测 → 阻断输入 |
| 3. 中国特定 PII | 手机号/身份证/银行卡红脱 |
| 4. 无 PII 内容 | 正常文本无拦截 |
| 5. 输出护栏 | AI 输出中的 PII 红脱 |

## 适用场景

- AI 助手处理用户输入时，检测并拦截/红脱个人隐私信息
- 防止 AI 输出泄露 PII（邮箱、手机号、身份证等）
- 中国企业合规——手机号/身份证号/银行卡号检测

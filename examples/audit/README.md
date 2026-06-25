# 审计示例

> SHA-256 哈希链验证、审计记录搜索、完整性报告

**文档介绍**见 VitePress Demo 页面 [审计](../../playground/docs/demo/audit.md)——代码片段 + 预期输出 + 配置说明。本目录是可运行的脚本。

## 运行

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/audit/demo_audit.py
```

## 输出内容

| Demo | 说明 |
|------|------|
| 1. 写入审计记录 + 哈希链 | 3 条记录写入，每条自动计算 SHA-256 chain_hash |
| 2. 搜索审计记录 | 按 session_id 关键词搜索 |
| 3. 验证哈希链完整性 | verify_chain() 检查链是否完整、是否有篡改 |
| 4. 完整性报告 | integrity_report() 生成全面报告 |
| 5. 审计统计 | stats() 返回记录数、时间范围等 |

## 适用场景

- AI Agent 执行任务的审计追踪——不可篡改的 SHA-256 哈希链
- 合规要求：需要审计日志不可被修改或删除
- 安全分析：检测审计记录是否被篡改

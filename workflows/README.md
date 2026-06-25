# basex 示例工作流

harness-cook 为 basex 项目提供的 3 个典型场景工作流定义。

## 快速使用

```bash
# 可视化 DAG 拓扑(不执行)
harness plan --workflow workflows/basex-examples.yaml

# 执行场景1: 代码合规扫描(不阻断)
harness run --workflow workflows/basex-examples.yaml --context basex-code-check

# 执行场景2: 构建→检查→发布(严格门禁)
harness run --workflow workflows/basex-examples.yaml --context basex-publish

# 执行场景3: 紧急修复(快速通道)
harness run --workflow workflows/basex-examples.yaml --context basex-hotfix
```

## 通过 Dashboard 观测

启动 Dashboard 后可在可视化界面实时追踪执行状态：
```bash
python packages/dashboard/app.py
# → http://localhost:8765
```

## 三个场景对比

| 场景 | 门禁模式 | 降级策略 | 适用时机 |
|------|----------|----------|----------|
| basex-code-check | 无 | 无 | 定期扫描,出报告不阻断 |
| basex-publish | strict | review→abort, deploy→skip | 正常发布,全量检查 |
| basex-hotfix | loose | deploy→skip(10分钟) | 紧急修复,快速通道 |

## 扫描覆盖

- **security pack**: XSS/SQL注入/密钥泄露/HTTP不安全/路径遍历/命令注入/调试代码残留
- **coding pack**: 命名规范/异常处理/布尔复杂度/TODO/空catch/魔术数字/长函数
- **data pack**: PII泄露/邮箱/手机号/SSN/日志隐私/数据分类标记/脱敏
- **devops pack**: CI配置/部署审批/回滚机制/环境变量/Docker安全/依赖锁定
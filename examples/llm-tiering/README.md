# LLM 分层调用与资源约束示例

> 模型分级策略、Token 成本追踪、Gate 通知推送、依赖注入容器

**文档介绍**见 VitePress Demo 页面 [LLM 分层](../../playground/docs/demo/llm-tiering.md)——代码片段 + 预期输出 + 配置说明。本目录是可运行的脚本。

## 运行

```bash
cd packages/core
PYTHONPATH=. python3 ../../examples/llm-tiering/demo_llm_tiering.py
```

## 输出内容

| Demo | 说明 |
|------|------|
| 1. LLM 分层调用 | ModelTier PREMIUM/STANDARD/FAST 三级模型 + LLMConstraints 约束（白名单/黑名单/温度验证/PromptTemplate） |
| 2. Token 跟踪 | TokenTracker 使用记录 + 分级成本估算 + 预算控制（超限检查） |
| 3. Gate 通知推送 | GateManager 多通道通知（邮件/Webhook/Slack/LocalNotifier） + 优先级 + 降级配置 |
| 4. 依赖注入容器 | DIContainer 服务注册/解析/生命周期（Singleton/Transient/Scoped） + ServiceLocator 全局访问 |

## 核心 API

| 模块 | 类/函数 | 说明 |
|------|---------|------|
| `harness.llm` | `ModelTier` | 模型分级枚举：PREMIUM / STANDARD / FAST |
| `harness.llm` | `LLMConstraints` | Agent 资源约束（token 上限、温度、模型白黑名单） |
| `harness.llm` | `TokenTracker` | Token 使用追踪器（聚合统计 + 成本估算） |
| `harness.llm` | `TokenUsageRecord` | 单次调用记录（分级、模型名、input/output tokens） |
| `harness.llm` | `PromptTemplate` | 提示词模板（参数化渲染 + 分级建议） |
| `harness.gate_notification` | `GateManager` | Gate 审批生命周期管理（创建/等待/降级） |
| `harness.gate_notification` | `GateNotification` | 通知数据模型（优先级/超时/概要） |
| `harness.gate_notification` | `INotifier` | 通知发送 Protocol 接口（send/receive） |
| `harness.gate_notification` | `LocalNotifier` | 本地日志通知器（首期实现） |
| `harness.gate_notification` | `NotificationPriority` | 通知优先级：URGENT / NORMAL / INFO |
| `harness.gate_notification` | `AutoDowngrade` | 自动降级配置（超时时间/降级动作/通知开关） |
| 本脚本 | `DIContainer` | 依赖注入容器（服务注册/解析/生命周期） |
| 本脚本 | `ServiceLocator` | 服务定位器（全局访问入口） |

## 适用场景

- AI Agent 的 LLM 调用分级——关键任务用 Premium、批量任务用 Fast
- Token 成本控制——实时追踪消耗、预算超限预警
- Gate 审批通知——多通道推送（邮件/Slack/Webhook），超时自动降级
- 依赖注入——生产环境推荐 DI 模式，测试环境可用全局单例

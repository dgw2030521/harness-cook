# harness dashboard

harness-cook 的可视化看板，实时展示 Agent 执行审计与治理状态。完整介绍见根目录 [README](../../README.md)。

## 启动

```bash
harness dashboard
```

> 在项目目录下执行，默认启动该项目的看板。无论项目是否已 `harness activate`，只要 `.harness/` 目录存在就能识别。

## 能力

- 审计日志实时流式展示
- 审计链完整性校验结果
- gate 审批状态与待办
- 规则命中与降级事件

## 开发

```bash
cd packages/dashboard
pip install -e ../../packages/core
python app.py
```

```

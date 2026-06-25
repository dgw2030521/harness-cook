# harness-sdk (Python)

harness-cook 的 Python SDK，用于以程序化方式接入治理能力。完整介绍见根目录 [README](../../README.md)。

## 定位

当你不通过 Agent 平台、而想在自有 Python 应用/CI 脚本中直接调用 harness-cook 的护栏、合规、审计能力时，使用本 SDK。

## 安装

```bash
pip install harness-sdk
```

## 能力

- 加载 Profile 配置
- 调用护栏检查（input/output guardrails、PII 过滤）
- 执行合规扫描与架构规则
- 写入与查询审计日志

## 开发

```bash
cd packages/sdk-python
pip install -e .[dev]
pytest tests/ -v
```

> 程序化 API 细节随版本演进，使用前请结合根 [README](../../README.md) 的核心概念与 [docs/](../../docs/) 设计文档。

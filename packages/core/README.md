# harness-cook core

harness-cook 的治理集成总线核心包。完整介绍见根目录 [README](../../README.md)。

## 定位

不重复造底层引擎，专注对接 Guardrails AI、SonarQube、OPA、Langfuse 等专业组件，承载四类核心不可外包能力：

- **Profile 声明式配置** — 一份 YAML 定义护栏 / 合规 / 门禁 / 审计策略
- **三档分级门禁** — strict / hybrid / loose
- **引擎路由总线** — PatternRegistry 统一注册，语言感知自动路由 + 4 级降级
- **可观测性** — 审计日志与审计链校验

## 关键模块

| 模块 | 职责 |
|------|------|
| `harness/config.py` | Profile 加载与校验 |
| `harness/engine.py` | DAGEngine 节点编排（pre_execute → execute → gate → post_execute） |
| `harness/guardrails.py` | 输入/输出护栏与 PII 过滤 |
| `harness/compliance.py` | 合规规则与规则包 |
| `harness/rule_checker.py` | 跨文件架构规则执行（dependency_graph / ast / cross_file） |
| `harness/knowledge.py` | 知识库三层治理与语义检索 |
| `harness/profiles/*.yaml` | 内置 Profile 模板（随包分发） |

## 安装

```bash
pip install harness-cook

# 多语言 AST 解析能力（可选）
pip install harness-cook[frontend]       # JS/TS
pip install harness-cook[java]
pip install harness-cook[go]
pip install harness-cook[all-languages]  # 全语言
```

## 开发

```bash
cd packages/core
pip install -e .[dev]
pytest tests/ -v
```

```

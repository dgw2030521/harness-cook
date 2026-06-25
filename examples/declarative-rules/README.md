# 声明式规则示例

## 概述

本示例展示如何使用 harness-cook 的声明式规则系统，通过 YAML 配置文件定义质量门禁规则，而无需编写 Python 代码。

## 使用场景

- 快速配置质量门禁，无需修改代码
- 团队成员可以通过配置文件自定义规则
- 将规则配置与代码分离，便于维护

## 代码示例

```python
"""
声明式规则使用示例

展示如何通过 YAML 配置定义质量门禁规则
"""

from harness.declarative_rules import (
    load_rules_from_yaml,
    create_gate_from_rules,
    load_and_create_gate,
)
from harness.gates import GateEngine
from harness.types import Artifact

# 1. 从 YAML 加载规则并创建 Gate
gate = load_and_create_gate(
    yaml_path="rules/my-rules.yaml",
    gate_id="my-quality-gate",
)

# 2. 创建 GateEngine
engine = GateEngine()

# 3. 检查 Artifact
artifact = Artifact(
    type="code",
    path="test.py",
    content="""
def my_function():
    # TODO: implement this
    eval('print("hello")')  # 不安全的 eval
    
    api_key = "sk-1234567890abcdefghijklmnopqrstuvwxyz"  # 硬编码密钥
""",
)

result = engine.check([artifact], gate)

if result.passed:
    print("✅ 检查通过")
else:
    print("❌ 检查失败")
    for check_result in result.check_results:
        if not check_result.passed:
            print(f"  - {check_result.message}")
```

## YAML 配置文件示例

```yaml
# rules/my-rules.yaml

rules:
  # 规则 1: 禁止 TODO 注释
  - id: no-todo-comments
    category: style
    severity: low
    description: "不允许 TODO 注释"
    checker: regex
    config:
      pattern: "\\bTODO\\b"
      message: "Found TODO comment - please implement or remove"

  # 规则 2: 禁止 eval/exec
  - id: no-eval-exec
    category: security
    severity: critical
    description: "禁止使用 eval/exec"
    checker: eval_detection
    config:
      severity: critical

  # 规则 3: 禁止硬编码密钥
  - id: no-hardcoded-secrets
    category: security
    severity: critical
    description: "禁止硬编码 API 密钥"
    checker: secret_patterns
    config:
      patterns:
        - "sk-[a-zA-Z0-9]{32,}"  # OpenAI API key
        - "ghp_[a-zA-Z0-9]{36}"  # GitHub token

  # 规则 4: 文件大小限制
  - id: file-size-limit
    category: style
    severity: medium
    description: "文件不超过 500 行"
    checker: file_size
    config:
      max_lines: 500
      severity: medium

  # 规则 5: 禁止 SQL 注入
  - id: no-sql-injection
    category: security
    severity: high
    description: "禁止 SQL 注入模式"
    checker: sql_injection
    config:
      severity: high
```

## 运行示例

```bash
cd examples/declarative-rules
python3 demo_declarative_rules.py
```

## 内置 Checker 列表

| Checker | 说明 | 配置参数 |
|---------|------|---------|
| `regex` | 正则表达式匹配 | `pattern`, `message`, `severity` |
| `secret_patterns` | 密钥模式匹配 | `patterns: list[str]`, `severity` |
| `eval_detection` | eval/exec 检测 | `severity` |
| `sql_injection` | SQL 注入检测 | `severity` |
| `file_size` | 文件大小限制 | `max_lines`, `severity` |

## 自定义 Checker

```python
from harness.declarative_rules import register_checker, CheckerBase
from harness.types import Artifact, CheckResult

class MyCustomChecker:
    """自定义检查器"""
    name = "my_checker"

    def check(self, artifact: Artifact, config: dict) -> CheckResult:
        # 自定义检查逻辑
        if "bad_pattern" in artifact.content:
            return CheckResult(
                passed=False,
                severity=config.get("severity", "medium"),
                message="Found bad pattern",
            )
        return CheckResult(passed=True, severity="medium", message="OK")

# 注册自定义 checker
register_checker(MyCustomChecker())
```

然后在 YAML 中使用：

```yaml
rules:
  - id: my-custom-rule
    category: custom
    severity: medium
    description: "自定义检查"
    checker: my_checker
    config:
      severity: medium
```

## 与 ComplianceRule 的关系

声明式规则系统与 ComplianceRule 互补：

- **ComplianceRule**：用于合规扫描（compliance.py），支持多语言、AST 分析
- **声明式规则**：用于质量门禁（gates.py），轻量级、易配置

两者可以共享 checker 实现。

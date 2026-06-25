"""
声明式合规规则注册

将 GateCheck 的 check_fn 从 Python 函数改为 YAML 声明+内置函数映射，
降低新增检查项的门槛。

## 使用方式

### 1. YAML 声明式规则

在 `.harness/rules/my-rules.yaml` 中定义规则：

```yaml
rules:
  - id: no-todo-comments
    category: style
    severity: low
    description: "不允许 TODO 注释"
    checker: regex
    config:
      pattern: "\\bTODO\\b"
      message: "Found TODO comment"

  - id: max-function-length
    category: style
    severity: medium
    description: "函数长度不超过 50 行"
    checker: function_length
    config:
      max_lines: 50

  - id: no-hardcoded-secrets
    category: security
    severity: critical
    description: "不允许硬编码密钥"
    checker: secret_patterns
    config:
      patterns:
        - "sk-[a-zA-Z0-9]{32,}"
        - "ghp_[a-zA-Z0-9]{36}"
```

### 2. Python 加载规则

```python
from harness.declarative_rules import load_rules_from_yaml, create_gate_from_rules

# 从 YAML 加载规则
rules = load_rules_from_yaml(".harness/rules/my-rules.yaml")

# 转换为 GateDefinition
gate = create_gate_from_rules(rules, gate_id="my-gate")
```

### 3. 内置 Checker 列表

| Checker | 说明 | 配置参数 |
|---------|------|---------|
| `regex` | 正则表达式匹配 | `pattern`, `message` |
| `secret_patterns` | 密钥模式匹配 | `patterns: list[str]` |
| `eval_detection` | eval/exec 检测 | 无 |
| `sql_injection` | SQL 注入检测 | 无 |
| `file_size` | 文件大小限制 | `max_lines` |
| `function_length` | 函数长度限制 | `max_lines` |
| `import_restrictions` | 导入限制 | `forbidden: list[str]` |
| `naming_convention` | 命名约定 | `style: "snake_case" | "camelCase" | "PascalCase"` |

### 4. 自定义 Checker

```python
from harness.declarative_rules import register_checker, CheckerBase

class MyChecker(CheckerBase):
    name = "my_checker"

    def check(self, artifact, config):
        # 自定义检查逻辑
        if "bad_pattern" in artifact.content:
            return CheckResult(
                passed=False,
                severity=config.get("severity", "medium"),
                message="Found bad pattern",
            )
        return CheckResult(passed=True, severity="medium", message="OK")

# 注册自定义 checker
register_checker(MyChecker())
```

## 与 ComplianceRule 的关系

声明式规则系统与 ComplianceRule 互补：
- **ComplianceRule**：用于合规扫描（compliance.py），支持多语言、AST 分析
- **声明式规则**：用于质量门禁（gates.py），轻量级、易配置

两者可以共享 checker 实现。
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable, Protocol

import yaml

from harness.types import Artifact, CheckResult, GateDefinition, GateCheck, GateMode

logger = logging.getLogger("harness.declarative_rules")


# ═══════════════════════════════════════════════════════════
#  Checker 接口
# ═══════════════════════════════════════════════════════════

class CheckerBase(Protocol):
    """Checker 接口——所有检查器必须实现"""

    name: str

    def check(self, artifact: Artifact, config: dict) -> CheckResult:
        """执行检查"""
        ...


# ═══════════════════════════════════════════════════════════
#  内置 Checker 实现
# ═══════════════════════════════════════════════════════════

class RegexChecker:
    """正则表达式检查器"""

    name = "regex"

    def check(self, artifact: Artifact, config: dict) -> CheckResult:
        pattern = config.get("pattern", "")
        message = config.get("message", f"Pattern matched: {pattern}")
        severity = config.get("severity", "medium")

        if not pattern:
            return CheckResult(passed=True, severity=severity, message="No pattern specified")

        try:
            if re.search(pattern, artifact.content, re.MULTILINE):
                return CheckResult(
                    passed=False,
                    severity=severity,
                    message=message,
                )
        except re.error as e:
            return CheckResult(
                passed=False,
                severity="high",
                message=f"Invalid regex pattern: {e}",
            )

        return CheckResult(passed=True, severity=severity, message="No matches")


class SecretPatternsChecker:
    """密钥模式检查器"""

    name = "secret_patterns"

    DEFAULT_PATTERNS = [
        (r'sk-[a-zA-Z0-9]{32,}', "OpenAI API key"),
        (r'ghp_[a-zA-Z0-9]{36}', "GitHub token"),
        (r'gho_[a-zA-Z0-9]{36}', "GitHub OAuth token"),
        (r'glpat-[a-zA-Z0-9\-]{20}', "GitLab token"),
        (r'xox[baprs]-[a-zA-Z0-9\-]+', "Slack token"),
    ]

    def check(self, artifact: Artifact, config: dict) -> CheckResult:
        patterns = config.get("patterns", [])
        severity = config.get("severity", "critical")

        # 合并默认模式和自定义模式
        all_patterns = self.DEFAULT_PATTERNS.copy()
        for p in patterns:
            all_patterns.append((p, "Custom pattern"))

        findings = []
        for pattern, desc in all_patterns:
            if re.search(pattern, artifact.content):
                findings.append(desc)

        if findings:
            return CheckResult(
                passed=False,
                severity=severity,
                message=f"Secret patterns detected: {', '.join(findings)}",
            )

        return CheckResult(passed=True, severity=severity, message="No secrets detected")


class EvalDetectionChecker:
    """eval/exec 检测器"""

    name = "eval_detection"

    def check(self, artifact: Artifact, config: dict) -> CheckResult:
        severity = config.get("severity", "critical")

        patterns = [
            (r'\beval\s*\(', "eval() usage"),
            (r'\bexec\s*\(', "exec() usage"),
        ]

        findings = []
        for pattern, desc in patterns:
            if re.search(pattern, artifact.content):
                findings.append(desc)

        if findings:
            return CheckResult(
                passed=False,
                severity=severity,
                message=f"Unsafe code execution: {', '.join(findings)}",
            )

        return CheckResult(passed=True, severity=severity, message="No eval/exec")


class SQLInjectionChecker:
    """SQL 注入检测器"""

    name = "sql_injection"

    def check(self, artifact: Artifact, config: dict) -> CheckResult:
        severity = config.get("severity", "high")

        patterns = [
            (r'f["\'].*SELECT.*\{.*\}.*FROM', "f-string SQL injection"),
            (r'f["\'].*INSERT.*\{.*\}.*INTO', "f-string SQL injection"),
            (r'\+\s*["\'].*SELECT', "string concatenation SQL injection"),
        ]

        findings = []
        for pattern, desc in patterns:
            if re.search(pattern, artifact.content, re.IGNORECASE | re.DOTALL):
                findings.append(desc)

        if findings:
            return CheckResult(
                passed=False,
                severity=severity,
                message=f"SQL injection patterns: {', '.join(findings)}",
            )

        return CheckResult(passed=True, severity=severity, message="No SQL injection")


class FileSizeChecker:
    """文件大小检查器"""

    name = "file_size"

    def check(self, artifact: Artifact, config: dict) -> CheckResult:
        max_lines = config.get("max_lines", 500)
        severity = config.get("severity", "medium")

        line_count = len(artifact.content.splitlines())
        if line_count > max_lines:
            return CheckResult(
                passed=False,
                severity=severity,
                message=f"File too large: {line_count} lines (max {max_lines})",
            )

        return CheckResult(
            passed=True,
            severity=severity,
            message=f"File size OK: {line_count} lines",
        )


# ═══════════════════════════════════════════════════════════
#  Checker 注册表
# ═══════════════════════════════════════════════════════════

_checkers: Dict[str, CheckerBase] = {}


def register_checker(checker: CheckerBase) -> None:
    """注册自定义 checker"""
    _checkers[checker.name] = checker
    logger.info(f"Registered checker: {checker.name}")


def get_checker(name: str) -> Optional[CheckerBase]:
    """获取 checker 实例"""
    return _checkers.get(name)


def list_checkers() -> List[str]:
    """列出所有已注册的 checker"""
    return list(_checkers.keys())


# 注册内置 checker
register_checker(RegexChecker())
register_checker(SecretPatternsChecker())
register_checker(EvalDetectionChecker())
register_checker(SQLInjectionChecker())
register_checker(FileSizeChecker())


# ═══════════════════════════════════════════════════════════
#  规则加载
# ═══════════════════════════════════════════════════════════

@dataclass
class DeclarativeRule:
    """声明式规则"""
    id: str
    category: str
    severity: str
    description: str
    checker: str
    config: dict = field(default_factory=dict)
    auto_fixable: bool = False


def load_rules_from_yaml(yaml_path: str) -> List[DeclarativeRule]:
    """从 YAML 文件加载规则"""
    path = Path(yaml_path)
    if not path.exists():
        logger.warning(f"Rule file not found: {yaml_path}")
        return []

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load rule file {yaml_path}: {e}")
        return []

    rules_data = data.get("rules", [])
    rules = []

    for rd in rules_data:
        try:
            rule = DeclarativeRule(
                id=rd.get("id", ""),
                category=rd.get("category", "logic"),
                severity=rd.get("severity", "medium"),
                description=rd.get("description", ""),
                checker=rd.get("checker", ""),
                config=rd.get("config", {}),
                auto_fixable=rd.get("auto_fixable", False),
            )
            rules.append(rule)
        except Exception as e:
            logger.warning(f"Failed to parse rule: {rd} — {e}")

    logger.info(f"Loaded {len(rules)} rules from {yaml_path}")
    return rules


def create_gate_from_rules(
    rules: List[DeclarativeRule],
    gate_id: str = "declarative-gate",
    mode: GateMode = GateMode.HYBRID,
) -> GateDefinition:
    """从声明式规则创建 GateDefinition"""
    checks = []

    for rule in rules:
        checker = get_checker(rule.checker)
        if not checker:
            logger.warning(f"Unknown checker: {rule.checker} for rule {rule.id}")
            continue

        # 创建闭包捕获 rule 和 checker
        def make_check_fn(checker, rule_config):
            def check_fn(artifact: Artifact) -> CheckResult:
                return checker.check(artifact, rule_config)
            return check_fn

        check = GateCheck(
            id=rule.id,
            category=rule.category,
            severity=rule.severity,
            description=rule.description,
            check_fn=make_check_fn(checker, rule.config),
        )
        checks.append(check)

    gate = GateDefinition(
        id=gate_id,
        checks=checks,
        mode=mode,
    )

    logger.info(f"Created gate {gate_id} with {len(checks)} checks from declarative rules")
    return gate


# ═══════════════════════════════════════════════════════════
#  便捷函数
# ═══════════════════════════════════════════════════════════

def load_and_create_gate(
    yaml_path: str,
    gate_id: str = "declarative-gate",
    mode: GateMode = GateMode.HYBRID,
) -> Optional[GateDefinition]:
    """从 YAML 加载规则并创建 GateDefinition"""
    rules = load_rules_from_yaml(yaml_path)
    if not rules:
        return None
    return create_gate_from_rules(rules, gate_id, mode)

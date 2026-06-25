# 自定义合规规则包示例

这个示例展示如何创建自定义合规规则包并让 harness-cook 自动发现加载。

## 规则包文件

将规则包 Python 文件放在项目 `.harness/rules/` 目录下（项目级）或 `~/.harness/rules/` 下（全局级）。

## 运行

```bash
pip install harness-cook
# 将 custom_pii.py 复制到项目的 .harness/rules/ 目录
mkdir -p .harness/rules
cp custom_pii.py .harness/rules/
# 运行合规扫描（自动发现自定义规则）
harness check src/
```

## 规则包开发指南

规则包是一个 Python 文件，包含 `get_xxx_pack()` 函数。函数名遵循 `get_<名称>_pack` 格式，返回 `RulePack` 实例。

### 基本结构

```python
from harness.compliance import ComplianceCategory, ComplianceRule, RulePack

def get_my_custom_pack() -> RulePack:
    """返回自定义合规规则包"""
    rules = [
        ComplianceRule(
            id="CUSTOM-001",
            category=ComplianceCategory.SECURITY,
            pattern=r"my_pattern_here",
            severity="high",
            description="描述规则检测什么",
            remediation="修复建议",
        ),
    ]
    return RulePack("my_custom", ComplianceCategory.SECURITY, rules)
```

### matcher_type 支持四种匹配策略

- `"regex"`: 正则表达式匹配（默认）
- `"dependency_graph"`: 依赖图架构检查（跨文件）
- `"ast"`: AST 结构检查（单文件）
- `"cross_file"`: 跨文件模式检查

### 使用 matcher_type

```python
ComplianceRule(
    id="CUSTOM-002",
    category=ComplianceCategory.ARCHITECTURE,
    pattern="...",  # 规则描述或模式
    matcher_type="dependency_graph",  # 使用依赖图匹配
    matcher_config={"max_depth": 5},  # 匹配器配置
    ...
)
```
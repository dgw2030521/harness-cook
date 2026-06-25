"""
架构合规规则包——真正需要跨文件/跨模块理解才能检测的架构问题

与单文件 linter（eslint/pylint/ruff）互补：
- linter 做单文件内的语法/风格检查
- architecture pack 做跨文件的结构/依赖/分层检查

7 条规则分三种 matcher_type：
- dependency_graph（ARCH-001/002/003）：需要依赖图才能检测
- ast（ARCH-004/005）：需要 AST 解析才能检测
- cross_file（ARCH-006/007）：需要跨文件上下文才能检测
"""

from harness.types import ComplianceCategory, ComplianceRule
from harness.compliance import RulePack


def get_architecture_pack() -> RulePack:
    """架构合规规则包——linter 做不到的架构级检查"""

    rules = [
        # ─── 依赖图规则 ──────────────────────────────────
        ComplianceRule(
            id="ARCH-001",
            category=ComplianceCategory.ARCHITECTURE,
            pattern="Layered architecture dependency direction violation",
            severity="high",
            description="Lower layer imported by higher layer bypassing intermediate layer",
            remediation="Follow layered dependency direction: UI → Service → DAO. Do not skip layers.",
            matcher_type="dependency_graph",
            matcher_config={
                "check": "layer_violation",
                "forbidden_directions": [
                    {"from_layer": "ui", "to_layer": "dao"},
                    {"from_layer": "ui", "to_layer": "model"},
                    {"from_layer": "service", "to_layer": "dao"},
                ],
                "layer_mapping": {
                    "ui": ["*/views/*", "*/controllers/*", "*/ui/*", "*/templates/*",
                            "*/pages/*", "*/components/*", "*/src/views/*",
                            "*/src/pages/*", "*/src/components/*"],
                    "service": ["*/services/*", "*/business/*", "*/handlers/*",
                                "*/usecases/*", "*/managers/*", "*/src/services/*",
                                "*/src/api/*", "*/src/store/*"],
                    "model": ["*/models/*", "*/domain/*", "*/entities/*",
                              "*/schemas/*", "*/types/*", "*/src/types/*",
                              "*/src/models/*", "*/src/interfaces/*"],
                    "dao": ["*/dao/*", "*/repository/*", "*/data/*", "*/persistence/*",
                            "*/db/*", "*/database/*", "*/src/dao/*", "*/src/data/*"],
                },
            },
        ),
        ComplianceRule(
            id="ARCH-002",
            category=ComplianceCategory.ARCHITECTURE,
            pattern="Circular dependency detected",
            severity="critical",
            description="Two or more modules form a circular import dependency",
            remediation="Break the cycle: extract shared logic into a separate module, "
                        "or use dependency injection / interface to invert the dependency.",
            matcher_type="dependency_graph",
            matcher_config={
                "check": "cycle",
            },
        ),
        ComplianceRule(
            id="ARCH-003",
            category=ComplianceCategory.ARCHITECTURE,
            pattern="Dependency chain exceeds max depth",
            severity="medium",
            description="A module's dependency chain depth exceeds threshold — high coupling risk",
            remediation="Reduce coupling: flatten the dependency chain by extracting common "
                        "dependencies into a shared module, or use dependency injection.",
            matcher_type="dependency_graph",
            matcher_config={
                "check": "deep_chain",
                "max_depth": 5,
            },
        ),

        # ─── AST 规则 ────────────────────────────────────
        ComplianceRule(
            id="ARCH-004",
            category=ComplianceCategory.ARCHITECTURE,
            pattern="God Class — too many methods",
            severity="high",
            description="A class has too many methods, violating Single Responsibility Principle",
            remediation="Split the class into smaller, focused classes following SRP. "
                        "Extract groups of related methods into separate classes.",
            matcher_type="ast",
            matcher_config={
                "ast_check": "god_class",
                "threshold": 15,
                "god_class_mode": "compound",
                "atfd_few": 5,
                "wmc_high": 47,
                "tcc_low": 0.33,
            },
            languages=["python", "javascript", "typescript", "vue", "java", "kotlin", "ruby", "cpp"],
        ),
        ComplianceRule(
            id="ARCH-005",
            category=ComplianceCategory.ARCHITECTURE,
            pattern="Deep inheritance chain",
            severity="high",
            description="Class inheritance chain depth exceeds threshold — fragile base class problem",
            remediation="Replace deep inheritance with composition. Use mixins or protocols "
                        "for shared behavior instead of deep class hierarchies.",
            matcher_type="ast",
            matcher_config={
                "ast_check": "deep_inheritance",
                "threshold": 4,
            },
            languages=["python", "javascript", "typescript", "vue", "java", "kotlin", "ruby", "cpp"],
        ),

        # ─── 跨文件规则 ──────────────────────────────────
        ComplianceRule(
            id="ARCH-006",
            category=ComplianceCategory.ARCHITECTURE,
            pattern="Scattered logic — same concept across too many files",
            severity="medium",
            description="A domain concept is implemented across too many different files — "
                        "poor cohesion, hard to maintain and understand",
            remediation="Consolidate the concept into a single module or cohesive package. "
                        "Use facade or coordinator pattern to provide unified access.",
            matcher_type="cross_file",
            matcher_config={
                "check": "scattered_logic",
                "spread_threshold": 3,
                "scope": ["*/models/*", "*/services/*", "*/domain/*", "*/handlers/*"],
            },
        ),
        ComplianceRule(
            id="ARCH-007",
            category=ComplianceCategory.ARCHITECTURE,
            pattern="Duplicate abstraction — structurally similar functions",
            severity="medium",
            description="Functions in different files have highly similar signatures — "
                        "likely duplicated logic that should be unified",
            remediation="Extract the common logic into a shared utility function or base class. "
                        "Apply Template Method or Strategy pattern for variations.",
            matcher_type="cross_file",
            matcher_config={
                "check": "duplicate_abstraction",
                "similarity_threshold": 0.8,
                "scope": ["*/services/*", "*/handlers/*", "*/utils/*"],
            },
        ),
    ]

    return RulePack("architecture", ComplianceCategory.ARCHITECTURE, rules)
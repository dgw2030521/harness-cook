"""Coding style compliance rule pack.

Provides rules for enforcing coding conventions such as naming, complexity,
TODO tracking, empty except handlers, magic numbers, and long functions.
"""

from __future__ import annotations

from harness.compliance import ComplianceRule, ComplianceCategory, RulePack


def get_coding_pack() -> RulePack:
    """Return the coding style compliance rule pack."""
    rules = [
        # ─── Naming conventions ────────────────────────────
        ComplianceRule(
            id="CODE-001",
            category=ComplianceCategory.STYLE,
            pattern=r"^[ \t]*(?:def|async def)\s+[A-Z]",
            severity="medium",
            description="Function name uses uppercase (should be snake_case)",
            remediation="Rename function to snake_case per PEP 8 (e.g. my_function, not MyFunction)",
            languages=["python"],
            matcher_config={"case_sensitive": True},  # [A-Z] 需精确大小写，否则 IGNORECASE 误匹配小写首字母
        ),
        ComplianceRule(
            id="CODE-002",
            category=ComplianceCategory.STYLE,
            pattern=r"^[ \t]*(?:def|async def)\s+__(?!init__|new__|repr__|str__|len__|call__|enter__|exit__|eq__|ne__|lt__|le__|gt__|ge__|hash__|bool__|iter__|next__|getitem__|setitem__|delitem__|contains__|add__|radd__|sub__|mul__|rmul__|truediv__|floordiv__|mod__|pow__|and__|or__|xor__|invert__|pos__|neg__|abs__|int__|float__|complex__|round__|index__|getattr__|setattr__|delattr__|dir__|class__|instancecheck__|subclasscheck__|copy__|deepcopy__|sizeof__|buffer__|await__|aiter__|anext__|aenter__|aexit__|fspath__|length_hint__|match_args__|slots__|doc__|name__|module__|qualname__|annotations__|type_params__|dict__|weakref__|prepared__|mro_entries__|set_name__|init_subclass__|class_getitem__|rshift__|lshift__|iadd__|isub__|imul__|itruediv__|ifloordiv__|imod__|ipow__|iand__|ior__|ixor__|irshift__|ilshift__|matmul__|rmatmul__|imatmul__)[a-zA-Z_]",
            severity="medium",
            description="Non-standard dunder method name",
            remediation="Only use well-known __dunder__ method names defined by Python data model",
            languages=["python"],
        ),
        # ─── Complexity ────────────────────────────────────
        ComplianceRule(
            id="CODE-003",
            category=ComplianceCategory.STYLE,
            pattern=r"^[ \t]*(?:if|elif|while)\b.*\b(?:and|or)\b.*\b(?:and|or)\b",
            severity="high",
            description="Boolean expression with 3+ operators — excessive complexity",
            remediation="Simplify boolean logic: extract sub-expressions into named variables or refactor with guard clauses",
            languages=["python"],
        ),
        # ─── TODO tracking ────────────────────────────────
        ComplianceRule(
            id="CODE-004",
            category=ComplianceCategory.STYLE,
            pattern=r"#\s*TODO[^\n]*",
            severity="low",
            description="Unresolved TODO comment",
            remediation="Resolve the TODO or convert to a tracked issue with a reference (e.g. # TODO(issue-123): ...)",
            auto_fixable=False,
        ),
        # ─── Empty except ─────────────────────────────────
        ComplianceRule(
            id="CODE-005",
            category=ComplianceCategory.STYLE,
            pattern=r"except\s*[A-Za-z_][A-Za-z0-9_.]*\s*:\s*pass",
            severity="high",
            description="Empty except block that silently swallows exceptions",
            remediation="Log the exception, raise a more specific error, or add a meaningful comment explaining why it is intentionally suppressed",
            languages=["python"],
        ),
        # ─── Magic numbers ────────────────────────────────
        ComplianceRule(
            id="CODE-006",
            category=ComplianceCategory.STYLE,
            pattern=r"(?:^|[=<>+\-*/%,(])\s*(?:(?:0x[0-9a-fA-F]+)|[1-9]\d{2,}|[2-9]\d)\b(?!\s*[.:]|(?:\.\d))",
            severity="medium",
            description="Magic number used without named constant",
            remediation="Replace the magic number with a named constant (e.g. MAX_RETRIES = 3) and reference the constant instead",
            languages=["python"],
        ),
        # ─── Long functions ───────────────────────────────
        ComplianceRule(
            id="CODE-007",
            category=ComplianceCategory.STYLE,
            pattern=r"^[ \t]*(?:def|async def)\s+\w+.*:[^\n]*\n(?:[ \t]+.*\n){50,}",
            severity="medium",
            description="Function body exceeds 50 lines — too long",
            remediation="Break the function into smaller focused helper functions; each function should do one thing well",
            languages=["python"],
        ),
    ]
    return RulePack("coding", ComplianceCategory.STYLE, rules)
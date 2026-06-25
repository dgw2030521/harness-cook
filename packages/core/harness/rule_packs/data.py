"""Data & Privacy Compliance Rule Pack

Scans for PII exposure, data classification violations, logging of sensitive
data, and data masking non-compliance.  All rule IDs use the DATA-xxx prefix
and fall under ComplianceCategory.PRIVACY.
"""

from __future__ import annotations

from harness.compliance import ComplianceRule, ComplianceCategory, RulePack


def get_data_pack() -> RulePack:
    """Return the data/privacy compliance rule pack."""

    rules = [
        # ─── PII: Email exposure ──────────────────────────────
        ComplianceRule(
            id="DATA-001",
            category=ComplianceCategory.PRIVACY,
            pattern=r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            severity="medium",
            description="PII email address exposure in source code",
            remediation="Move email addresses to configuration files or environment variables; never hardcode PII",
            auto_fixable=True,
        ),

        # ─── PII: Phone number exposure ───────────────────────
        ComplianceRule(
            id="DATA-002",
            category=ComplianceCategory.PRIVACY,
            pattern=r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
            severity="medium",
            description="PII phone number exposure in source code",
            remediation="Store phone numbers in external configuration; remove hardcoded phone PII from source",
            auto_fixable=True,
        ),

        # ─── PII: SSN exposure ────────────────────────────────
        ComplianceRule(
            id="DATA-003",
            category=ComplianceCategory.PRIVACY,
            pattern=r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b",
            severity="critical",
            description="Social Security Number (SSN) exposure in source code",
            remediation="SSNs must never appear in source code; use encrypted identifiers or tokenized references instead",
        ),

        # ─── Data classification markers ──────────────────────
        ComplianceRule(
            id="DATA-004",
            category=ComplianceCategory.PRIVACY,
            pattern=r"(?:CONFIDENTIAL|RESTRICTED|TOP_SECRET|SECRET|CLASSIFIED|SENSITIVE)\s*[:=]",
            severity="high",
            description="Explicit data classification marker found — verify handling policy is enforced",
            remediation="Ensure classified data follows organizational handling policies: encryption at rest, access controls, audit logging",
        ),

        # ─── Logging privacy: sensitive data in logs ──────────
        ComplianceRule(
            id="DATA-005",
            category=ComplianceCategory.PRIVACY,
            pattern=r"(?:log(?:ger)?\.|print\s*\()(?:.*(?:password|ssn|social_security|credit_card|card_number|secret|token|auth|credential).*)",
            severity="high",
            description="Sensitive data written to logs — privacy violation risk",
            remediation="Never log PII or secrets; strip/redact sensitive fields before logging, use structured logging with field-level masking",
        ),

        # ─── Data masking compliance ──────────────────────────
        ComplianceRule(
            id="DATA-006",
            category=ComplianceCategory.PRIVACY,
            pattern=r"(?:mask|redact|sanitize|anonymize|obfuscate)\s*\(\s*(?:None|nil|null)\s*\)",
            severity="high",
            description="Data masking function called with null/None argument — masking is not applied",
            remediation="Ensure masking functions receive the actual data field; null arguments mean PII passes through unmasked",
            auto_fixable=True,
        ),
    ]

    return RulePack("data", ComplianceCategory.PRIVACY, rules)
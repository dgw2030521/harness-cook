"""Security compliance rule pack for harness evaluation."""

from __future__ import annotations

from harness.compliance import ComplianceCategory, ComplianceRule, RulePack


def get_security_pack() -> RulePack:
    """Return a RulePack containing security compliance rules."""
    rules = [
        ComplianceRule(
            id="SEC-001",
            category=ComplianceCategory.SECURITY,
            pattern=r"(?:password|passwd|pwd|api_key|apikey|secret|token|access_key|private_key)\s*[:=]\s*[\"'][^\"']{8,}[\"']",
            severity="critical",
            description="Hardcoded secret or credential in source code",
            remediation="Use environment variables or a secret management tool such as Vault or AWS Secrets Manager",
            languages=["python", "javascript", "typescript", "go", "java", "ruby"],
        ),
        ComplianceRule(
            id="SEC-002",
            category=ComplianceCategory.SECURITY,
            pattern=r"f[\"'](?:SELECT|INSERT|UPDATE|DELETE|DROP)\s.*\{.*\}",
            severity="high",
            description="SQL injection via f-string interpolation in query",
            remediation="Use parameterized queries with cursor.execute(sql, params) instead of string interpolation",
            languages=["python"],
        ),
        ComplianceRule(
            id="SEC-003",
            category=ComplianceCategory.SECURITY,
            pattern=r"<script[^>]*>|document\.(?:write|innerHTML)\s*\(|\.innerHTML\s*=\s*",
            severity="high",
            description="XSS pattern — unsafe script injection or innerHTML assignment",
            remediation="Use textContent or DOM-based safe templating instead of innerHTML; sanitize all user input",
            languages=["javascript", "typescript"],
        ),
        ComplianceRule(
            id="SEC-004",
            category=ComplianceCategory.SECURITY,
            pattern=r"http://[^\s\"']+(?:api|login|auth|token|secret|key|password|credential)",
            severity="high",
            description="HTTP URL used for a sensitive endpoint instead of HTTPS",
            remediation="Use HTTPS for all endpoints that handle authentication, tokens, or secrets",
        ),
        ComplianceRule(
            id="SEC-005",
            category=ComplianceCategory.SECURITY,
            pattern=r"(?:print_stacktrace|debugger|console\.debug|logging\.debug|traceback\.print_exc|pdb|breakpoint)\s*\(",
            severity="medium",
            description="Debug information exposure — debug statements left in production code",
            remediation="Remove all debug statements before deployment; use structured logging with appropriate levels",
            languages=["python", "javascript", "typescript", "java"],
        ),
        ComplianceRule(
            id="SEC-006",
            category=ComplianceCategory.SECURITY,
            pattern=r"(?:\.\./|\.\.\\|%2e%2e[/\\%])",
            severity="high",
            description="Path traversal pattern — directory traversal attempt detected",
            remediation="Validate and sanitize all file paths; use os.path.realpath and ensure resolved paths stay within intended directories",
        ),
        ComplianceRule(
            id="SEC-007",
            category=ComplianceCategory.SECURITY,
            pattern=r"\b(?:exec|system|popen|subprocess\.(?:call|run|Popen)|os\.system|os\.exec)\s*\(",
            severity="critical",
            description="Command injection — unsafe shell command execution",
            remediation="Avoid shell=True in subprocess calls; use parameterized argument lists; never interpolate user input into commands",
            languages=["python"],
        ),
    ]
    return RulePack("security", ComplianceCategory.SECURITY, rules)
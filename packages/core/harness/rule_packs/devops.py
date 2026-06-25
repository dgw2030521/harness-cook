"""DevOps compliance rule pack for CI/CD, deployment, and infrastructure concerns."""

from __future__ import annotations

from harness.compliance import ComplianceRule, ComplianceCategory, RulePack


def get_devops_pack() -> RulePack:
    """DevOps compliance rule pack covering CI config, deployment security,
    rollback guarantees, environment variables, Docker security, and version pinning."""
    rules = [
        # ─── CI config issues ─────────────────────────────
        ComplianceRule(
            id="OPS-001",
            category=ComplianceCategory.ARCHITECTURE,
            pattern=r'(?:name|script|image|stages|steps):\s*$',
            severity="high",
            description="Missing required CI configuration field — empty or unset key detected",
            remediation="Ensure all required CI fields (name, script, image, stages, steps) have non-empty values",
            languages=["yaml"],
        ),
        # ─── Deployment security ──────────────────────────
        ComplianceRule(
            id="OPS-002",
            category=ComplianceCategory.ARCHITECTURE,
            pattern=r'\bdeploy\b.*(?:production|prod)\b(?!\s*(?:approval|approve|gate|review|check))',
            severity="critical",
            description="Deployment to production without approval gate",
            remediation="Add an approval/gate step before production deployments in the pipeline",
            languages=["yaml", "json", "python", "shell"],
        ),
        # ─── Rollback guarantees ──────────────────────────
        ComplianceRule(
            id="OPS-003",
            category=ComplianceCategory.ARCHITECTURE,
            pattern=r'\b(?:deploy|release|rollout)\b.*\b(?:production|prod)\b',
            severity="high",
            description="Missing rollback configuration for production deployment",
            remediation="Add rollback/rollback_config section or a post-deploy verification step with rollback trigger",
            auto_fixable=False,
            languages=["yaml", "json"],
        ),
        # ─── Environment variables ────────────────────────
        ComplianceRule(
            id="OPS-004",
            category=ComplianceCategory.ARCHITECTURE,
            pattern=r'\b(?:ENV|env|environment)\s*\{[^}]*(?:password|secret|token|api_key|apikey|access_key)\s*[:=]\s*["\'][^"\']+["\']',
            severity="critical",
            description="Hardcoded sensitive value in environment variable declaration",
            remediation="Use secret references (secrets.VAR_NAME) or environment variable injection from vault/secret manager",
            languages=["yaml", "dockerfile", "shell"],
        ),
        # ─── Docker security ──────────────────────────────
        ComplianceRule(
            id="OPS-005",
            category=ComplianceCategory.ARCHITECTURE,
            pattern=r'\bUSER\s+root\b',
            severity="high",
            description="Docker container configured to run as root user",
            remediation="Set USER to a non-root user (e.g., USER app or USER 1000) in the Dockerfile",
        ),
        # ─── Version pinning ──────────────────────────────
        ComplianceRule(
            id="OPS-006",
            category=ComplianceCategory.ARCHITECTURE,
            pattern=r'(?:FROM|image|require|install|pip\s+install|npm\s+install|apt-get\s+install)\s+\S+:(?:latest|stable|edge)\b',
            severity="medium",
            description="Unpinned dependency using a floating tag (latest/stable/edge)",
            remediation="Pin dependency versions to specific releases (e.g., python:3.11.4-slim instead of python:latest)",
            auto_fixable=True,
        ),
    ]
    return RulePack("devops", ComplianceCategory.ARCHITECTURE, rules)
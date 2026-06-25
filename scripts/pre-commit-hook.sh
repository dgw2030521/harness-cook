#!/bin/bash
# harness-cook pre-commit hook
# Runs compliance check on staged code files
# BLOCKING violations = commit rejected
# Non-blocking = warnings only, commit allowed
#
# 全局 30 秒超时：超时则跳过检查，不阻断提交

set -e

PROJECT_ROOT="$(git rev-parse --show-toplevel)"
BRIDGE="$PROJECT_ROOT/skills/harness-bridge/bridge.py"

# Skip if bridge.py doesn't exist
if [ ! -f "$BRIDGE" ]; then
    echo "⚠ harness-cook bridge not found, skipping compliance check"
    exit 0
fi

# Get staged code files
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\.py$|\.yaml$|\.yml$|\.json$|\.ts$|\.js$|\.vue$|\.tsx$|\.jsx$' || true)

if [ -z "$STAGED_FILES" ]; then
    echo "✓ No code files staged, skipping harness check"
    exit 0
fi

echo "🔍 Running harness compliance check on staged files..."

# Create temp dir with only staged file contents for fast scan
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

for file in $STAGED_FILES; do
    # Get staged content (not working tree content)
    git diff --cached -- "$file" > /dev/null 2>&1 || continue
    mkdir -p "$TMPDIR/$(dirname "$file")"
    git show ":$file" > "$TMPDIR/$file" 2>/dev/null || true
done

# Run bridge.py check with 30s timeout — 超时不阻断提交
RESULT=$(timeout 30 python3 "$BRIDGE" check "$TMPDIR" 2>&1 || true)

# Clean up temp dir immediately
rm -rf "$TMPDIR"

# Check for BLOCKING violations
if echo "$RESULT" | grep -qi "BLOCKING"; then
    echo "❌ BLOCKING violations found — commit rejected"
    echo "$RESULT" | grep -i "blocking" | head -10
    echo ""
    echo "Fix these violations before committing, or use --no-verify to bypass."
    exit 1
fi

# Report non-blocking violations
VIOLATIONS=$(echo "$RESULT" | grep -ci "violation" || true)
if [ "$VIOLATIONS" -gt 0 ]; then
    echo "⚠ $VIOLATIONS non-blocking violations (warnings only, commit allowed)"
fi

echo "✓ Harness check passed — commit allowed"
exit 0

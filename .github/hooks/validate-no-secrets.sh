#!/bin/bash
# Validate that no secrets or credentials are about to be exposed
# Runs before tool execution to catch dangerous commands early

set -u

# List of patterns that indicate credential exposure risk
DANGEROUS_PATTERNS=(
    "cat.*\.env"
    "echo.*WIX_API"
    "export.*API_KEY"
    "DATABASE_URL"
    "REDIS.*PASSWORD"
    "SECRET"
    "TOKEN"
    "PRIVATE_KEY"
    "print.*credential"
    "echo.*password"
)

# Check if this is an execute/terminal operation
if [[ "${TOOL_NAME:-}" != "execute" && "${TOOL_NAME:-}" != "run_in_terminal" ]]; then
    exit 0
fi

# Scan command for dangerous patterns
COMMAND="${COMMAND_TEXT:-}"

if [ -z "$COMMAND" ]; then
    exit 0
fi

for pattern in "${DANGEROUS_PATTERNS[@]}"; do
    if echo "$COMMAND" | grep -qiE "$pattern"; then
        echo "⚠️  BLOCKED: Potential credential exposure detected."
        echo "Pattern: $pattern"
        echo "Command: $COMMAND"
        echo ""
        echo "Credentials must be handled safely for public repo:"
        echo "  ✓ Use \${VAR} or \${VARIABLE} placeholders"
        echo "  ✓ Never echo/cat .env files with real values"
        echo "  ✓ Reference credentials via secure tools (1Password, Railway dashboard)"
        echo "  ✓ Use docker-compose env file injection or env var defaults"
        echo ""
        exit 1
    fi
done

exit 0

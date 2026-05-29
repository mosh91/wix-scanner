#!/bin/bash
# Lint tool output for accidentally exposed credentials
# Runs after tool execution to catch and redact any secrets in logs

set -u

# This script would lint the output of tool executions
# In practice, this is a placeholder that logs would be piped through
# to redact any accidental credential exposure

# Check if output contains common secret patterns
if [[ "${TOOL_OUTPUT:-}" =~ (api_key|API_KEY|wix_token|password|secret|private_key|Authorization) ]]; then
    echo ""
    echo "⚠️  WARNING: Tool output may contain sensitive data."
    echo "Please review the output above and verify no credentials were exposed."
    echo ""
    echo "If credentials were logged:"
    echo "  1. Rotate the credential immediately (use .github/agents/docker-fullstack-dev.agent.md)"
    echo "  2. Remove the log from git history (if committed): git filter-branch"
    echo "  3. Document the incident for audit trail"
    echo ""
fi

exit 0

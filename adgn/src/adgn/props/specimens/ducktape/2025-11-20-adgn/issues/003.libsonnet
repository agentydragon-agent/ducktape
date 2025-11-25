local I = import '../../specimens/lib.libsonnet';

// iss-003: Silent failure when --mcp-config or --initial-policy file doesn't exist

I.issueOneOccurrence(
  rationale=|||
    When user provides --mcp-config with a non-existent file path, the code silently falls
    back to empty config without error message or notification.

    Current behavior (cli.py:86-89):
    - Check if file exists
    - If not: use empty config MCPConfig(mcpServers={})
    - Server starts successfully
    - User doesn't know their config wasn't loaded

    This is problematic because:
    - User explicitly specified config file (not optional/auto-detected)
    - Non-existence likely indicates user error (typo, wrong directory, deleted file)
    - Silent fallback masks the problem
    - User discovers issue later when servers are missing

    Correct behavior (per user):
    Option 1: Remove exists() check, let FileNotFoundError propagate naturally
    Option 2: Explicitly check and report: raise click.UsageError(f"MCP config file not found: {mcp_config}")

    Both approaches fail fast at startup with clear feedback, rather than starting in wrong state.

    Same pattern exists for --initial-policy flag (cli.py:92-93).
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/cli.py': [
      [86, 89],     // --mcp-config: silent fallback to empty config
      [92, 93],     // --initial-policy: silent fallback to None (same pattern, should crash)
    ],
  }
)

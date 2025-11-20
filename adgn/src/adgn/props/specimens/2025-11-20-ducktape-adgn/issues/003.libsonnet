local I = import '../../specimens/lib.libsonnet';

// iss-003: Silent failure when --mcp-config file doesn't exist
//
// Context:
// - User provides --mcp-config path/to/file.json (cli.py:59)
// - Code checks if file exists (cli.py:86)
// - If file doesn't exist: silently falls back to empty config (cli.py:89)
// - No error message, no notification
// - Server starts with no MCP servers, user assumes config was loaded
//
// Problem:
// When user explicitly provides a config file path, non-existence likely indicates:
// - Typo in path
// - File moved/deleted
// - Wrong working directory
//
// Silently ignoring the error and starting with empty config masks the problem.
// User won't discover their config wasn't loaded until they notice servers missing.
//
// Correct behaviors (user's guidance):
// Option 1: Don't handle non-existent file at all - let it crash naturally
//   - Remove exists() check
//   - Let FileNotFoundError propagate (with clear traceback showing path)
//   - Fast-fail at startup (don't start server with wrong config)
//
// Option 2: Explicitly report error and exit (nice CLI behavior)
//   - if mcp_config and not mcp_config.exists():
//       raise click.UsageError(f"MCP config file not found: {mcp_config}")
//   - Clear, actionable error message
//
// Note: initial_policy has the same pattern (cli.py:92-93) - same issue applies
//
// Properties violated:
// 1. truthfulness: Silent failure masks error from user
// 2. no-swallowing-errors: Error condition ignored without notification
// 3. least-power: Defensive check adds complexity without benefit

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
  properties=['truthfulness', 'python/no-swallowing-errors', 'least-power'],
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/cli.py': [
      [86, 89],     // mcp_config silent fallback
      [92, 93],     // initial_policy has same pattern
    ],
  },
)

local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale= |||
    When user provides explicit config file flags (--mcp-config or --initial-policy) with
    non-existent file paths, the code silently falls back without error messages.

    Pattern (applies to both flags):
    - Check if file exists
    - If not: use fallback value (empty config or None)
    - Server starts successfully
    - User doesn't know their config wasn't loaded

    This is problematic because:
    - User explicitly specified config file (not optional/auto-detected)
    - Non-existence likely indicates user error (typo, wrong directory, deleted file)
    - Silent fallback masks the problem
    - User discovers issue later when expected configuration is missing

    Correct behavior (per user):
    Option 1: Remove exists() check, let FileNotFoundError propagate naturally
    Option 2: Explicitly check and report: raise click.UsageError(f"Config file not found: {path}")

    Both approaches fail fast at startup with clear feedback, rather than starting in wrong state.
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/agent/mcp_bridge/cli.py': [[86, 89]]},
      note: '--mcp-config flag: silent fallback to empty config MCPConfig(mcpServers={})',
      expect_caught_from: [['adgn/src/adgn/agent/mcp_bridge/cli.py']],
    },
    {
      files: {'adgn/src/adgn/agent/mcp_bridge/cli.py': [[92, 93]]},
      note: '--initial-policy flag: silent fallback to None',
      expect_caught_from: [['adgn/src/adgn/agent/mcp_bridge/cli.py']],
    },
  ],
)

local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    A short-lived variable used only to forward to a single call (e.g., `command = shell; StdioServerParameters(command=command, ...)`) adds noise without value.

    Prefer passing expressions directly at the call site or collapsing the small helper into the call, which reduces lines and one-off names the reader must mentally map.

    Example: replace
      command = shell
      args_for_shell = [...]
      StdioServerParameters(command=command, args=args_for_shell, ...)
    with
      StdioServerParameters(command=shell, args=[...], ...)
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py': [[61, 71]],
  },
)

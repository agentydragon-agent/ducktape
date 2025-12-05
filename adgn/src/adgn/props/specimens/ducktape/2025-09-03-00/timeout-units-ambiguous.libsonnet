local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    Constants representing timeouts should carry units in their type or name. `_DEFAULT_TIMEOUT: float | None = None` is ambiguous about units.

    Prefer one of two patterns:
      - Use a timedelta, e.g. `DEFAULT_TIMEOUT = timedelta(seconds=30)`, and name it DEFAULT_TIMEOUT.
      - If storing a numeric value, include the unit in the name and type, e.g. `DEFAULT_TIMEOUT_S: int | None = None`.

    Benefits: reduces confusion about whether a timeout is seconds, milliseconds, or fractional seconds; makes call sites clearer and avoids silent misconfigurations.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mcp/docker_exec/server.py': [[55, 55]],
  },
)

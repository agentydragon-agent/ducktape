local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    `attach_container_exec` has only one call site (runtime/server.py line 22) and is a
    trivial wrapper that just forwards parameters. This function should be inlined directly
    into its only caller to reduce indirection and simplify the code. The function body is
    a single await statement with parameter forwarding - no logic to justify the abstraction.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/runtime/server.py': [[22, 22]],
  },
)
